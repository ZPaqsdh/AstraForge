# -*- coding: utf-8 -*-
"""probe60 裁剪帧反投影主点补偿 —— BUG-011 · v0.2.8 验证（无设备 · 纯数学）

用法：python tests/probe60_principal_point.py [ship]   （ship = 以发行 code/ 为 ROOT）

背景：v0.2.7 输出端裁剪（→ 619×479）只裁数组、未补偿相机主点 → 反投影仍按
全画幅主点 (320,240) 计算，导致：
  · 导出点云横向整体错位 21*z/FX（z=1.2m ≈ 44mm）、纵向 z/FY（≈2mm）；
  · 融合（转台多帧）时错位方向随角度旋转 → 同一表面点环状偏移（环状拖影隐患）。
修复（v0.2.8）：cloudmath.cxcy_for_shape() 尺寸/方位感知主点——
(480,640)→全画幅主点（v0.2.10 起 = 出厂标定(318.163,249.847)，此前硬编码(320,240)）；
左裁(479,619)→(CX-21,CY-1)；右裁（老 R 帧，BUG-012 发现）col0=0 → (CX,CY-1)。

验证项（无设备）：
  ① 合成帧（左缘垃圾）：裁剪路径 == 全画幅参考（相机系点云，有效像素逐点一致）
  ②a 合成帧：同上（模型系点云 @0°）
  ②b 合成帧：同上（模型系点云 @90°）
  ③ 存档真实帧（右缘垃圾 rawD，存在时）：同 ①（右裁 + col0=0）
  ④ 主点表：全画幅 (CX,CY)、左裁 (CX-21,CY-1)、右裁 col0=0 (CX,CY-1)
  ⑤ 信息项：旧口径偏差统计（须 ≈ -21z/FX / +z/FY；角度旋转关系）
修复前跑本探针：①②③④ FAIL（中位偏差 30mm 级）；修复后全 PASS。
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if len(sys.argv) > 1 and sys.argv[1] == 'ship':
    ROOT = Path(str(Path(__file__).resolve().parents[2] / '发行' / 'AstraForge' / 'code'))
    print('[60] 目标 = 发行态 code/')
sys.path.insert(0, str(ROOT))
from core import cloudmath as cm          # noqa: E402
from core.contracts import crop_for_output, detect_garbage_side, detect_phantom_side  # noqa: E402

FX, FY = cm.FX, cm.FY
results = []


def item(name, ok, info=''):
    results.append((name, bool(ok)))
    print(('PASS ' if ok else 'FAIL ') + name + (f'  | {info}' if info else ''), flush=True)


def keep2d(full, side):
    """全画幅中"保留区"布尔掩码（2D）：L 去左 21 列；R 去右 21 列；均去顶行。"""
    H, W = full.shape
    ys, xs = np.mgrid[0:H, 0:W]
    if side == 'L':
        return (xs >= 21) & (ys >= 1)
    return (xs <= W - 22) & (ys >= 1)


def col0_for(side):
    return 21 if side == 'L' else 0


def cmp_pair(tag, full, side, model=None):
    """全画幅参考（按方位过滤垃圾区）vs 裁剪帧逐点比较。
    model=(angle_deg, cam_dist) 时走模型系；否则相机系。
    v0.2.9：裁剪帧若检出幻影列（BUG-013）该列被清零 → 参考集合同步剔除其源列。"""
    cropped, _ = crop_for_output(full, None)
    cropped = np.ascontiguousarray(cropped)
    expect_shape = (full.shape[0] - 1, full.shape[1] - 21)
    if cropped.shape != expect_shape:
        item(tag, False, f'裁剪形状 {cropped.shape} != {expect_shape}')
        return
    m = (full > 0) & (full < 4000)
    keep = keep2d(full, side)
    # 幻影源列剔除（与 crop_for_output 的清零动作保持一致）：
    # 在全画幅上检测（裁剪帧上该列已被清零、检不出来）
    ph = detect_phantom_side(full)
    if ph is not None:
        full_col = 0 if ph == 'L' else full.shape[1] - 1
        H, W = full.shape
        ys, xs = np.mgrid[0:H, 0:W]
        keep = keep & (xs != full_col)
    sel = keep[m]
    c0 = col0_for(side)
    if model is None:
        pf = cm.depth_to_points(full, 1.0)
        pc = cm.depth_to_points(cropped, 1.0, col0=c0)
    else:
        ang, cd = model
        pf = cm.depth_to_model_points(full, ang, cd, 1.0)
        pc = cm.depth_to_model_points(cropped, ang, cd, 1.0, col0=c0)
    a = pf[sel]
    if a.shape == pc.shape and np.allclose(a, pc, rtol=0, atol=1e-6):
        item(tag, True, f'{len(a)} 点逐点一致')
        return
    n = min(len(a), len(pc))
    if n == 0:
        item(tag, False, '无对齐点')
        return
    d = a[:n] - pc[:n]
    zs = cropped[(cropped > 0) & (cropped < 4000)]
    zmed = float(np.median(zs)) if len(zs) else 0.0
    item(tag, False, f'点数 {len(a)} vs {len(pc)}；中位 |Δx|={np.median(np.abs(d[:, 0])):.1f}mm'
                     f' |Δy|={np.median(np.abs(d[:, 1])):.1f}mm（z中位 {zmed:.0f}）')


# ---- 合成帧（含真实布局：左缘垃圾带 + 顶行垃圾；避开已知有效块）----
H, W = 480, 640
rng = np.random.default_rng(7)
full = np.zeros((H, W), np.uint16)
full[120:360, 120:520] = rng.integers(300, 1500, size=(240, 400)).astype(np.uint16)
full[60, 600] = 800            # 角落小有效区（检验子集对齐）
full[430, 40] = 1200
full[:, :21] = 1313            # 左缘 21 列垃圾带（真实设备特征）
full[0, :] = 1313              # 顶行垃圾
side_syn = detect_garbage_side(full)
item('合成帧方位检测 = L', side_syn == 'L', f'检测 {side_syn}')
dep_c, _ = crop_for_output(full, None)
cropped = np.ascontiguousarray(dep_c)
print(f'[60] 合成帧 {full.shape} → 裁剪 {cropped.shape}（crop_for_output 契约一致）')

# ① 相机系
cmp_pair('① 相机系点云：裁剪 == 全画幅参考（逐点一致）', full, 'L')

# ② 模型系（转台，cam_dist=600）
for ang in (0.0, 90.0):
    cmp_pair(f'②{"a" if ang == 0 else "b"} 模型系点云 @{ang:.0f}°：裁剪 == 全画幅参考',
             full, 'L', model=(ang, 600.0))

# ③ 存档真实帧（rawD：右缘垃圾 → 右裁 + col0=0）
arch = Path(__file__).resolve().parents[1] / '_tmp' / 'bug009_dec.npy'
if arch.exists():
    raw = np.load(str(arch))
    side_arch = detect_garbage_side(raw)
    item('③ 存档帧方位检测 = R', side_arch == 'R', f'检测 {side_arch}')
    cmp_pair('③ 存档真实帧（右裁）：裁剪 == 全画幅参考', raw, side_arch or 'R')
else:
    print('[60] 跳过 ③（无存档帧 _tmp/bug009_dec.npy）')

# ④ 主点表
f = getattr(cm, 'cxcy_for_shape', None)
if f is None:
    item('④ 主点表 cxcy_for_shape', False, '未实现（修复前）')
else:
    t1, t2, t3 = f((480, 640)), f((479, 619)), f((479, 619), col0=0)
    exp = ((cm.CX, cm.CY), (cm.CX - 21, cm.CY - 1), (cm.CX, cm.CY - 1))
    ok4 = all(abs(a - b) < 1e-6 for got, want in ((t1, exp[0]), (t2, exp[1]), (t3, exp[2]))
              for a, b in zip(got, want))
    item(f'④ 主点表（出厂内参 {cm.CX:.3f}/{cm.CY:.3f}）：全画幅/左裁(CX-21,CY-1)/右裁col0=0',
         ok4, f'{t1} / {t2} / {t3}  期望 {exp}')

# ⑤ 信息项：旧口径偏差统计 + 旋转关系
if f is not None:
    print('\n[60·信息] 旧口径（裁后仍按全画幅主点、未随裁剪平移）偏差量化（合成 L 帧）：')
    orig = cm.cxcy_for_shape
    cm.cxcy_for_shape = lambda shape, col0=None, row0=None: (cm.CX, cm.CY)
    try:
        pts_bug = cm.depth_to_points(cropped, 1.0)
    finally:
        cm.cxcy_for_shape = orig
    pts_fix = cm.depth_to_points(cropped, 1.0, col0=21)
    zc = cropped[(cropped > 0) & (cropped < 4000)].astype(np.float64)
    dz = pts_bug - pts_fix
    # x：bug-fix = -21·z/FX；y：几何 y 有 -1 翻转 → +z/FY
    ex = np.abs(dz[:, 0] + 21.0 * zc / FX)
    ey = np.abs(dz[:, 1] - 1.0 * zc / FY)
    print(f'  中位 |Δx|={np.median(np.abs(dz[:,0])):.1f}mm |Δy|={np.median(np.abs(dz[:,1])):.1f}mm'
          f'；与理论残差 max {ex.max():.2e} / {ey.max():.2e}（~0 = 理论吻合）')
    print('  模型系（转台）错位随角度旋转（环状偏移来源）：')
    vecs = {}
    for ang in (0.0, 90.0, 180.0, 270.0):
        cm.cxcy_for_shape = lambda shape, col0=None, row0=None: (cm.CX, cm.CY)
        try:
            mb = cm.depth_to_model_points(cropped, ang, 600.0, col0=None)
        finally:
            cm.cxcy_for_shape = orig
        mf = cm.depth_to_model_points(cropped, ang, 600.0, col0=21)
        v = mb - mf
        vecs[ang] = v
        mag = float(np.median(np.linalg.norm(v, axis=1)))
        print(f'    角度 {ang:5.1f}°：中位偏移 {mag:.1f} mm')
    a0, a180 = vecs[0.0], vecs[180.0]
    if len(a0) == len(a180) and len(a0) > 0:
        cosv = (np.sum(a0 * a180, axis=1) /
                (np.linalg.norm(a0, axis=1) * np.linalg.norm(a180, axis=1) + 1e-9))
        print(f'    0° 与 180° 偏移向量余弦（中位）：{float(np.median(cosv)):+.3f}（≈-1 → 反向成环）')

print()
print('===== probe60 结果（BUG-011 主点补偿 · v0.2.8） =====')
allok = len(results) > 0
for name, ok in results:
    print(('PASS ' if ok else 'FAIL ') + name)
    allok = allok and ok
print('===== ' + ('全部通过' if allok else '存在失败项') + ' =====')
sys.exit(0 if allok else 1)