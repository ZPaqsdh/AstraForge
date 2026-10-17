# -*- coding: utf-8 -*-
"""probe68 深度模型定参：用"平面表面的列剖面必须是直线"当目标，搜 (fx, C)。

模型假设（对照三条外部证据）：
    深度值 s 是**视差域**，z = A/(C − s)，A = fx·B·k = 600·fx（B≈75mm 立体基线、k=8 子像素，
    与社区拟合 focalBL≈342857 一致）
    点云：X=(u+21-cx)z/fx, Y=(v-cy)z/fy, Z=z

判据（无需标定物）：真实场景里的**平面**（墙=正对平面、床面=斜面）在正确 (fx,C) 下，
中央列的剖面 (Y(v), Z(v)) 在 Y-Z 平面内必须是**直线**（直线不因相机姿态而改变）。
错误模型会让它弯 → 用「直线拟合残差」当目标函数，网格搜索。

对照模型：z = s（现行"直读 mm"口径）也应给一个残差，用来比较。
用法：python tests/probe68_depth_model.py
"""
import sys
from pathlib import Path

import numpy as np

WS = Path(str(Path(__file__).resolve().parents[2]))
FRAME = WS / '问题跟踪' / '_0210_D2C_原始深度.npy'
if not FRAME.exists():
    print('缺原始帧，请先跑 probe66/probe67'); sys.exit(1)

dep = np.load(str(FRAME)).astype(np.float32)
CROP_L, ROW0 = 21, 0
pub = np.ascontiguousarray(dep[:, :-CROP_L][:, ::-1])      # 发布向（与 RGB 同向）
H, W = pub.shape
CXP, CYP = 318.163 - CROP_L, 249.847                        # 发布向主点（全画幅基准 - 裁剪）
print(f'[68] 帧 {pub.shape}｜有效 {float((pub>0).mean())*100:.1f}%｜中位 {np.median(pub[pub>0]):.0f}')

# ---- 挑两个"应当是平面"的带：墙（上 2/3 均匀区）与床（下 1/3 递变区）----
rows_wall = slice(120, 260)
rows_bed = slice(330, 470)
cols = slice(250, 370)                                       # 中央列带（避开左右边缘）


def col_profile(rows, cols):
    """返回 (v, s_med)：逐行取列带中位（稳健）"""
    sub = pub[rows, cols]
    vs = np.arange(pub.shape[0])[rows]
    med = []
    for i, r in enumerate(vs):
        m = sub[i][sub[i] > 0]
        med.append(float(np.median(m)) if len(m) > 20 else np.nan)
    return vs, np.array(med)


v_wall, s_wall = col_profile(rows_wall, cols)
v_bed, s_bed = col_profile(rows_bed, cols)
print(f'[68] 墙带 s: {np.nanmin(s_wall):.0f}~{np.nanmax(s_wall):.0f}（极差 {np.nanmax(s_wall)-np.nanmin(s_wall):.0f}）')
print(f'[68] 床带 s: {np.nanmin(s_bed):.0f}~{np.nanmax(s_bed):.0f}（极差 {np.nanmax(s_bed)-np.nanmin(s_bed):.0f}）')


def line_resid(V, S, fx, C, BK=600.0):
    """把 (v,s) 按模型 z=A/(C-s) 映射到 Y-Z 平面，做全最小二乘直线拟合，返回 RMS 残差(mm)"""
    ok = np.isfinite(S) & (C - S > 1.0)
    if ok.sum() < 20:
        return np.inf, 0.0
    z = (BK * fx) / (C - S[ok])
    y = (V[ok] - CYP) * z / fx
    P = np.stack([y, z], axis=1)
    P = P - P.mean(axis=0)
    # 全最小二乘（PCA）：最小奇异值 × sqrt(1/N) = RMS 到直线距离
    u, sv, vt = np.linalg.svd(P, full_matrices=False)
    return float(sv[1] / np.sqrt(len(P))), float(z.mean())


def linear_resid(V, S):
    """对照：现行口径 z=s 下的同样残差"""
    ok = np.isfinite(S) & (S > 0)
    z = S[ok]
    y = (V[ok] - CYP) * z / 580.703
    P = np.stack([y, z], axis=1) - np.stack([y, z], axis=1).mean(axis=0)
    u, sv, vt = np.linalg.svd(P, full_matrices=False)
    return float(sv[1] / np.sqrt(len(P)))


print(f'\n[68] 对照：现行"直读 mm"口径下残差  墙 {linear_resid(v_wall,s_wall):.1f}mm'
      f'｜床 {linear_resid(v_bed,s_bed):.1f}mm')

best = None
grid = []
for fx in np.arange(540, 621, 4.0):
    for C in np.arange(1150, 2601, 10.0):
        rw, zw = line_resid(v_wall, s_wall, fx, C)
        rb, zb = line_resid(v_bed, s_bed, fx, C)
        tot = rw + rb
        grid.append((tot, fx, C, rw, rb, zw, zb))
        if best is None or tot < best[0]:
            best = (tot, fx, C, rw, rb, zw, zb)

grid.sort(key=lambda t: t[0])
print('\n[68] === 最优 12 组 (fx, C) ===')
print('   总残差   fx     C     墙残差  床残差  墙z     床z')
for tot, fx, C, rw, rb, zw, zb in grid[:12]:
    print(f'  {tot:8.1f}  {fx:6.1f} {C:6.0f}  {rw:7.1f} {rb:7.1f}  {zw:7.0f} {zb:7.0f}')

tot, fx, C, rw, rb, zw, zb = best
print(f'\n[68] ★ 最优：fx={fx:.1f}  C={C:.0f}（总残差 {tot:.1f}mm）')
print(f'    → 墙 z≈{zw:.0f}mm（残差 {rw:.1f}）｜床 z≈{zb:.0f}mm（残差 {rb:.1f}）')
print(f'    → A = 600·fx = {600*fx:.0f}（社区拟合 342857；astra_raw 常数 342000）')
print(f'    → 该 fx 对应 HFOV = {2*np.degrees(np.arctan(320/fx)):.2f}°'
      f'（设备自报 58.59° / 手册 58.4° / OBCameraParams 580.7 → 57.71°）')
print(f'    → 用该模型反查：s=1180 → z={600*fx/(C-1180):.0f}mm')

# 残差随 C 的曲线（固定最优 fx 附近）
print('\n[68] 固定 fx=%.1f，残差 vs C：' % fx)
for C in np.arange(1200, 2601, 100.0):
    rw, zw = line_resid(v_wall, s_wall, fx, C)
    rb, zb = line_resid(v_bed, s_bed, fx, C)
    print(f'   C={C:5.0f}  墙 {rw:7.1f}  床 {rb:7.1f}  合计 {rw+rb:7.1f}   墙z {zw:6.0f} 床z {zb:6.0f}')
