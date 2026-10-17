# -*- coding: utf-8 -*-
"""probe41: 融合质量诊断
① 打印每帧的转台距离估计（cam_dist=None 时的中心深度近似）
② 关闭 ICP 跑一遍（纯角度先验）→ 对比产物（判断 ICP 是帮忙还是帮倒忙）
"""
import sys, os, json, time
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import cloudmath

D = str(ROOT / '_tmp' / 'tt_noicp')   # 需自备转台数据集
man = json.load(open(os.path.join(D, 'manifest.json'), encoding='utf-8'))
mms = float(man.get('mm_per_shift', 1.0))

print('=== ① 每帧转台距离估计（中心深度近似）===')
CX_, CY_ = 320, 240
ests = []
for fr in man['frames']:
    dep = np.load(os.path.join(D, fr['file'])).astype(np.float32)
    c = dep[CY_-3:CY_+3, CX_-3:CX_+3]
    cv = c[c > 0]
    est = float(np.median(cv)) * mms if len(cv) else 500.0
    # 同时看画面中心是否有有效数据（物体是否居中）
    valid = float((dep > 0).mean() * 100)
    ests.append(est)
    print(f'  {fr["file"]} angle={fr["angle"]:>5.1f}°  cam_dist≈{est:7.1f} mm  有效像素 {valid:4.1f}%')
print(f'  → 距离估计波动: min={min(ests):.0f} max={max(ests):.0f} 极差={max(ests)-min(ests):.0f} mm（越大说明物体越不居中/距离不稳）')

print('\n=== ② 关闭 ICP 融合（纯角度先验）===')
t0 = time.time()
fused, verts, faces = cloudmath.fuse_directory(D, use_icp=False, workers=6)
dt = time.time() - t0
print(f'  耗时 {dt:.0f} 秒 | 点云 {len(fused)} | 顶点 {len(verts)} 面 {len(faces)}')
print(f'  产物: {D}/fused_points.ply, fused_mesh.stl, fused_preview.png')
