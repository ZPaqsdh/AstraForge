# -*- coding: utf-8 -*-
"""probe42: 合成理想转台数据 → 融合（验证融合数学正确性）
方法：取一帧真实深度 → 反投影点云 → 绕 Y 轴每 15° 旋转一圈（24 帧）
      → 投影回深度图（z-buffer）→ 组成理想转台数据集 → 融合
预期：若算法正确，产物应是均匀光滑的旋转体点云（无条形伪影）——
      与真实残缺数据（105°、散乱）对比，即可判定问题在数据还是算法。
"""
import sys, os, json
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import cloudmath as cm

SRC_DIR = str(ROOT.parent / '扫描输出' / 'turntable_20261013_162326')   # 需自备转台数据集
OUT = str(ROOT / '_tmp' / 'tt_synth')
os.makedirs(OUT, exist_ok=True)

FX, FY = cm.FX, cm.FY
CX_, CY_ = cm.CX, cm.CY
W, H = 640, 480

# 1) 取第 0 帧真实深度 → 点云（相机系，mm）
dep0 = np.load(os.path.join(SRC_DIR, 'frame_000.npy')).astype(np.float32)
ys, xs = np.mgrid[0:H, 0:W]
z = dep0
valid = z > 0
P = np.stack([(xs - CX_) * z / FX, (ys - CY_) * z / FY, z], axis=-1)[valid]  # (N,3) mm
print(f'源点云: {len(P)} 点（第 0 帧）')

# 2) 绕 Y 轴旋转 24 个角度 → 投影回深度图（z-buffer）→ 保存
N_FRAMES = 24
STEP = 360.0 / N_FRAMES
frames = []
for k in range(N_FRAMES):
    a = np.deg2rad(k * STEP)
    ca, sa = np.cos(a), np.sin(a)
    R = np.array([[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]], dtype=np.float32)
    Pk = P @ R.T                                     # 旋转
    Zk = Pk[:, 2]
    front = Zk > 1.0                                 # 只投影相机前方
    Xk, Yk, Zk = Pk[front, 0], Pk[front, 1], Pk[front, 2]
    u = np.round(Xk / Zk * FX + CX_).astype(np.int64)
    v = np.round(Yk / Zk * FY + CY_).astype(np.int64)
    inside = (u >= 0) & (u < W) & (v >= 0) & (v < H)
    u, v, Zk = u[inside], v[inside], Zk[inside]
    dep = np.zeros((H, W), dtype=np.uint16)
    order = np.argsort(-Zk)                          # 远的先画，近的覆盖（z-buffer）
    for j in order:
        dep[v[j], u[j]] = np.uint16(min(Zk[j], 65535))
    fn = f'frame_{k:03d}.npy'
    np.save(os.path.join(OUT, fn), dep)
    frames.append({'file': fn, 'angle': round(k * STEP, 1), 'cam_dist': 600.0})
    cov = float((dep > 0).mean() * 100)
    print(f'  帧 {k:02d} angle={k*STEP:5.1f}° 覆盖 {cov:4.1f}%')

json.dump({'mm_per_shift': 1.0, 'note': '合成理想转台数据（单帧旋转 24 视角）',
           'frames': frames},
          open(os.path.join(OUT, 'manifest.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=2)
print(f'数据集就绪 → {OUT}')

# 3) 融合（自动策略：有角度先验 → 跳过 ICP）
import time
t0 = time.time()
fused, verts, faces = cm.fuse_directory(OUT, workers=8)
print(f'=== 合成数据融合: {time.time()-t0:.1f} 秒 | 点云 {len(fused)} | 顶点 {len(verts)} 面 {len(faces)} ===')
