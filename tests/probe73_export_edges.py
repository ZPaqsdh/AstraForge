# -*- coding: utf-8 -*-
"""probe73 导出模型边缘"颗粒垃圾" —— BUG-022

现象（老大实拍）：导出的 PLY 在**正视**看不见问题，转 90° 才看到左右两侧各有一层
薄片/颗粒（像红外溅射），贴着模型边缘悬空。

根因：ToF 视场左右边缘 IR 照度下降 → 深度解算不可靠：
  · 有效率骤降（左缘 6–16%，右缘 44%→2%）
  · 深度系统性**偏近**（左缘 −100mm，右缘 −70…−180mm）
这些点投影后形成"贴边薄片"，正向与模型轮廓重合 → 看不见；侧向立刻现形。

修复：core.contracts.trim_unreliable_edges（crop_for_output 末段调用）
  · 判据：列有效率 < 0.35 且（空列 或 列中位比主体近 > 25mm）
  · 处置：整列清无效，**不清画幅**（保持 619×479，内参/主点不级联，BUG-011）
  · 保守：只从最外侧向内连续判定，遇可靠列即停；单侧上限 25% 宽度

用法：python tests/probe73_export_edges.py            # 纯合成，无需设备
      python tests/probe73_export_edges.py <frame.npy> # 附真机帧复核
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core.contracts as C  # noqa: E402
from core import cloudmath as cm  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def make_frame(body=1180, edge_cols=45, edge_bias=110, edge_fill=0.12,
               body_fill=0.92, W=619, H=479, seed=7):
    """合成一帧：中间是高有效率的主体面，左右两缘是稀疏且偏近的"薄片"。"""
    rng = np.random.default_rng(seed)
    d = np.zeros((H, W), dtype=np.uint16)
    body_mask = rng.random((H, W)) < body_fill
    d[body_mask] = (body + rng.integers(-4, 5, size=int(body_mask.sum()))).astype(np.uint16)
    if edge_cols:
        for cols in (slice(0, edge_cols), slice(W - edge_cols, W)):
            m = (rng.random((H, edge_cols)) < edge_fill)
            blk = np.zeros((H, edge_cols), dtype=np.uint16)
            blk[m] = (body - edge_bias + rng.integers(-6, 7, size=int(m.sum()))).astype(np.uint16)
            d[:, cols] = blk
    return d


print("=== ① 合成：边缘薄片应被清掉，画幅不变 ===")
f = make_frame()
out = C.trim_unreliable_edges(f)
check("画幅不变", out.shape == f.shape, str(out.shape))
left_kept = int((out[:, :45] > 0).sum())
right_kept = int((out[:, -45:] > 0).sum())
check("左缘薄片已清", left_kept == 0, f"残留 {left_kept} 点")
check("右缘薄片已清", right_kept == 0, f"残留 {right_kept} 点")
body_kept = int((out[:, 100:500] > 0).sum())
check("主体未受影响", body_kept == int((f[:, 100:500] > 0).sum()), f"{body_kept} 点")


print("\n=== ② 保守性：满幅真实场景（边缘也高有效、同深度）不得被裁 ===")
full = make_frame(edge_cols=0, body_fill=0.95)
out2 = C.trim_unreliable_edges(full)
check("满幅场景不裁边", np.array_equal(out2, full),
      f"有效点 {int((out2>0).sum())} / {int((full>0).sum())}")

print("\n=== ③ 保守性：边缘稀疏但深度与主体一致（真几何）不得被裁 ===")
sparse_ok = make_frame(edge_cols=45, edge_bias=0, edge_fill=0.1)
out3 = C.trim_unreliable_edges(sparse_ok)
check("稀疏但同深度 → 不裁", np.array_equal(out3, sparse_ok),
      f"左缘保留 {int((out3[:, :45]>0).sum())} 点")

print("\n=== ④ 上限保护：不能一路裁到画面中间 ===")
extreme = make_frame(edge_cols=300, edge_bias=200, edge_fill=0.05)
out4 = C.trim_unreliable_edges(extreme)
cleared = int(np.sum(~(out4 > 0).any(axis=0)))
cap = int(extreme.shape[1] * C._EDGE_MAX_RATIO)
check("单侧裁剪不超过 25% 宽", cleared <= cap * 2, f"共清 {cleared} 列，上限 {cap*2}")

print("\n=== ⑤ 点云侧效果：被清列不再产生点 ===")
geo_before = cm.depth_to_points(f, 1.0)
geo_after = cm.depth_to_points(out, 1.0)
zc = -geo_after[:, 2]
cx, _cy = cm.cxcy_for_shape(out.shape)      # 按画幅取主点（619 宽 → CX-21，BUG-011）
u = geo_after[:, 0] * cm.FX / zc + cx
# 被清掉的列 = 整列全零的列
zero_cols = np.where(~(out > 0).any(axis=0))[0]
left_cleared = int((zero_cols < out.shape[1] // 2).sum())
right_cleared = int((zero_cols >= out.shape[1] // 2).sum())
# 反投影回列的精度为 ±1 列（float 舍入），判据留 1 列余量
pts_in_left = int((u < left_cleared - 1).sum())
pts_in_right = int((u > out.shape[1] - right_cleared).sum())
check("被清列没有点残留（左）", pts_in_left == 0, f"u<{left_cleared-1} 有 {pts_in_left} 点")
check("被清列没有点残留（右）", pts_in_right == 0,
      f"u>{out.shape[1]-right_cleared} 有 {pts_in_right} 点")
check("点数只减少少量（<5%）", len(geo_after) > len(geo_before) * 0.95,
      f"{len(geo_before)} → {len(geo_after)}")

print("\n=== ⑥ 真机帧复核（给了路径才跑） ===")
if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
    raw = np.load(sys.argv[1]).astype(np.uint16)
    d_out, _ = C.crop_for_output(raw, None)
    v = d_out > 0
    body = float(np.median(d_out[:, 150:450][d_out[:, 150:450] > 0]))
    bad = [(c, round(float(v[:, c].mean() * 100), 1))
           for c in range(d_out.shape[1])
           if v[:, c].sum() > 5 and v[:, c].mean() < C._EDGE_FILL_MIN
           and body - float(np.median(d_out[v[:, c], c])) > C._EDGE_BIAS_MM]
    check("真机帧：无残留偏近稀疏列", len(bad) == 0, f"残留 {len(bad)} 列 {bad[:3]}")
    check("真机帧：画幅仍 479×619", d_out.shape == (479, 619), str(d_out.shape))
else:
    print("  （未提供 .npy，跳过）")

ok = all(x[1] for x in results)
print(f"\n===== probe73 结果：{sum(1 for x in results if x[1])}/{len(results)} =====")
sys.exit(0 if ok else 1)