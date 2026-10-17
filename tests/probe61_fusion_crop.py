# -*- coding: utf-8 -*-
"""probe61 融合链路垃圾带修复 —— BUG-012 · v0.2.8 验证（无设备 · 真实存档帧）

背景：融合 worker `_load_frame_cloud` 读帧后直接反投影，未过 crop_for_output——
旧会话帧（640×480 含固定垃圾带）融合时垃圾列派生假点（L 帧实测 9,842 个/5.1%，
模型系形成固定平面）；且垃圾方位有两种（L=flip 时代左缘 / R=B 定案后右缘）。

验证项（用真实存档帧，逐点比对）：
  ① L 帧（turntable_20261013_162326）：_load_frame_cloud == 手工「裁后反投影+降采样」
  ② R 帧（scan_session_20261015_213952）：同上（右裁 + col0=0）
  ③ 无垃圾合成帧：不裁剪（点云零损失）
  ④ 产物干净：L/R 帧的 worker 输出中无垃圾派生点（对照模拟旧行为量化差异）
用法：python tests/probe61_fusion_crop.py
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import cloudmath as cm                       # noqa: E402
from core.contracts import crop_for_output, detect_garbage_side  # noqa: E402

WS = Path(str(Path(__file__).resolve().parents[2]))
results = []


def item(name, ok, info=''):
    results.append((name, bool(ok)))
    print(('PASS ' if ok else 'FAIL ') + name + (f'  | {info}' if info else ''), flush=True)


def manual_worker(fpath, angle=0.0, cam_dist=600.0, mms=1.0):
    """手工复刻「修复后」worker 期望行为：读帧 → 方位检测 → 裁剪 → 反投影 → 降采样。"""
    dep = np.load(str(fpath)).astype(np.float32)
    rgb_path = str(fpath)[:-4] + '_rgb.png'
    rgb = None
    if Path(rgb_path).exists():
        from PIL import Image
        rgb = np.asarray(Image.open(rgb_path).convert('RGB'))
    orig_w = dep.shape[1]
    side = detect_garbage_side(dep)
    dep2, rgb2 = crop_for_output(dep, rgb)
    col0 = (21 if side == 'L' else 0) if orig_w == 640 else None
    pts = cm.depth_to_model_points(dep2, angle, cam_dist, mms, rgb=rgb2, col0=col0)
    if len(pts) > 60000:
        sel = np.random.default_rng(0).choice(len(pts), 60000, replace=False)
        pts = pts[sel]
    return cm.voxel_down(pts, 2.0), side


def worker_call(fpath, angle=0.0, cam_dist=600.0, mms=1.0):
    rgb_path = str(fpath)[:-4] + '_rgb.png'
    return cm._load_frame_cloud((str(fpath), angle, cam_dist, mms, rgb_path))


# ---- ① L 帧 ----
Lf = WS / '扫描输出' / 'turntable_20261013_162326' / 'frame_000.npy'
if Lf.exists():
    w_pts, w_ang = worker_call(Lf)
    m_pts, side = manual_worker(Lf)
    ok = w_pts.shape == m_pts.shape and np.allclose(w_pts, m_pts, rtol=0, atol=1e-9)
    item('① L 帧 worker == 手工裁后流水线（逐点一致）', ok,
         f'side={side} 点数 {len(w_pts)} vs {len(m_pts)}')
    # ④a 对照：模拟旧行为（不裁）差异量化
    dep = np.load(str(Lf)).astype(np.float32)
    pts_old = cm.depth_to_model_points(dep, 0.0, 600.0, 1.0)
    sel = np.random.default_rng(0).choice(len(pts_old), 60000, replace=False) if len(pts_old) > 60000 else slice(None)
    vox_old = cm.voxel_down(pts_old[sel], 2.0)
    diff = len(vox_old) - len(w_pts)
    print(f'[61·信息] L 帧旧行为 vs 修复：{len(vox_old)} → {len(w_pts)} 点（垃圾派生差 {diff}）')
else:
    item('① L 帧存在', False, '缺少存档')

# ---- ② R 帧（原生直发布局：垃圾在右）----
# 首选 R 会话目录；已被移走则用仍存在的原生存档帧 bug009_dec.npy（同为 R 布局）
Rf = WS / '发行' / 'AstraForge' / '扫描输出' / 'scan_session_20261015_213952' / 'frame_000.npy'
if not Rf.exists():
    Rf = WS / 'AstraForge' / '_tmp' / 'bug009_dec.npy'
if Rf.exists():
    w_pts, w_ang = worker_call(Rf)
    m_pts, side = manual_worker(Rf)
    ok = w_pts.shape == m_pts.shape and np.allclose(w_pts, m_pts, rtol=0, atol=1e-9)
    item('② R 帧 worker == 手工裁后流水线（逐点一致）', ok,
         f'side={side} 点数 {len(w_pts)} vs {len(m_pts)} | 源 {Rf.name}')
else:
    item('② R 帧存在', False, '缺少存档')


# ---- ③ 无垃圾合成帧：不裁剪 ----
def synth_clean():
    H, W = 480, 640
    rng = np.random.default_rng(3)
    d = np.zeros((H, W), np.uint16)
    d[100:400, 100:500] = rng.integers(400, 1200, size=(300, 400)).astype(np.uint16)
    return d


tmp_dir = WS / '_tools' / '_probe61_tmp'
tmp_dir.mkdir(parents=True, exist_ok=True)
try:
    s = synth_clean()
    sp = tmp_dir / 'frame_000.npy'
    np.save(str(sp), s)
    w_pts, _ = worker_call(sp)
    m_pts, side = manual_worker(sp)
    ok = side is None and w_pts.shape == m_pts.shape and np.allclose(w_pts, m_pts, rtol=0, atol=1e-9)
    item('③ 无垃圾合成帧：不裁剪且逐点一致', ok, f'side={side} 点数 {len(w_pts)}')
    # ④b 产物里无"设备垃圾面"特征（模拟旧行为基准：L 帧垃圾在模型系 X∈[-735,-689]）
    if Lf.exists():
        dep = np.load(str(Lf)).astype(np.float32)
        pts_old_all = cm.depth_to_model_points(dep, 0.0, 600.0, 1.0)
        m = (dep > 0) & (dep < 4000)
        ys, xs = np.where(m)
        garbage_mask = xs < 21
        garbage_pts = pts_old_all[garbage_mask]
        if len(garbage_pts):
            gx = (garbage_pts[:, 0].min(), garbage_pts[:, 0].max())
            gz = (garbage_pts[:, 2].min(), garbage_pts[:, 2].max())
            print(f'[61·信息] 旧行为垃圾派生点模型系位置：X {gx[0]:.0f}..{gx[1]:.0f} | Z {gz[0]:.0f}..{gz[1]:.0f}mm')
        w_pts, _ = worker_call(Lf)
        # 修复后产物里不应再出现 X<-680 的极左点（垃圾带走 X∈[-735,-689]）
        left_extreme = int((w_pts[:, 0] < -680).sum())
        item('④ L 帧产物无垃圾派生点（X<-680 计数 ≈0）', left_extreme == 0,
             f'X<-680: {left_extreme} 个（旧行为 {len(garbage_pts)} 个垃圾点）')
finally:
    for f in tmp_dir.glob('*'):
        try:
            f.unlink()
        except Exception:
            pass
    try:
        tmp_dir.rmdir()
    except Exception:
        pass

print()
print('===== probe61 结果（BUG-012 融合链路裁剪 · v0.2.8） =====')
allok = len(results) > 0
for name, ok in results:
    print(('PASS ' if ok else 'FAIL ') + name)
    allok = allok and ok
print('===== ' + ('全部通过' if allok else '存在失败项') + ' =====')
sys.exit(0 if allok else 1)