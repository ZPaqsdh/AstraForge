# -*- coding: utf-8 -*-
"""probe68b 深度模型定参（修正版）：归一化"直线度"目标 + 剖面打印。

修正点：上一版用绝对残差 → 被"z 整体变小"的退化方向带偏。本版用
        score = RMS(到直线距离) / RMS(到质心距离)   —— 尺度无关，只反映**形状**。
模型  z = A/(C − s)，A=600·fx（fx 只影响 Y/Z 比例：各向异性缩放保平面 → 对"形状"无鉴别力，
      故固定 fx=580.703，只搜 C）。
"""
import sys
from pathlib import Path

import numpy as np

WS = Path(str(Path(__file__).resolve().parents[2]))
dep = np.load(str(WS / '问题跟踪' / '_0210_D2C_原始深度.npy')).astype(np.float32)
pub = np.ascontiguousarray(dep[:, :-21][:, ::-1])
H, W = pub.shape
CXP, CYP = 318.163 - 21, 249.847
FX = 580.703

cols = slice(250, 370)


def profile(rows):
    sub = pub[rows, cols]
    vs = np.arange(H)[rows]
    out = []
    for i, r in enumerate(vs):
        m = sub[i][sub[i] > 0]
        out.append(float(np.median(m)) if len(m) > 20 else np.nan)
    return vs.astype(float), np.array(out)


print('[68b] 床带剖面 s(v)（v: 中位值）')
v_bed, s_bed = profile(slice(320, 478, 4))
for v, s in zip(v_bed, s_bed):
    print(f'   v={v:3.0f}  s={s:7.1f}')
print('\n[68b] 墙带剖面 s(v)')
v_wall, s_wall = profile(slice(120, 260, 8))
for v, s in zip(v_wall, s_wall):
    print(f'   v={v:3.0f}  s={s:7.1f}')


def shape_score(V, S, C, A):
    ok = np.isfinite(S) & (C - S > 1.0)
    if ok.sum() < 12:
        return np.inf
    z = A / (C - S[ok])
    y = (V[ok] - CYP) * z / FX
    P = np.stack([y, z], axis=1)
    Pm = P - P.mean(axis=0)
    sv = np.linalg.svd(Pm, compute_uv=False)
    if sv[0] <= 0:
        return np.inf
    return float(sv[1] / sv[0])          # 奇异值比：0=完美直线


A0 = 600 * FX
print(f'\n[68b] A = 600·fx = {A0:.0f}')
print('  C       墙 score   床 score   合计      墙z     床z')
rows = []
for C in np.arange(1200, 3001, 20.0):
    sw = shape_score(v_wall, s_wall, C, A0)
    sb = shape_score(v_bed, s_bed, C, A0)
    zz = A0 / (C - np.nanmean(s_bed))
    rows.append((sw + sb, C, sw, sb, zz))
    if C <= 2600:
        print(f'  {C:5.0f}   {sw:.5f}   {sb:.5f}   {sw+sb:.5f}  {A0/(C-np.nanmean(s_wall)):6.0f} {zz:6.0f}')
best = min(rows, key=lambda t: t[0])
print(f'\n[68b] ★ 最小合计 = C {best[1]:.0f}（墙 {best[2]:.5f} 床 {best[3]:.5f}）'
      f' → 床 z≈{best[4]:.0f}mm')
print('\n[68b] 对照（现行直读口径 z=s，等效把 C 拉到很大）：')
# 直读口径当作 C→∞ 的极限形状
sw = shape_score(v_wall, s_wall, 1e9, A0)
sb = shape_score(v_bed, s_bed, 1e9, A0)
print(f'   C=∞ 极限：墙 {sw:.5f} 床 {sb:.5f} 合计 {sw+sb:.5f}（值越小说明越像直线）')
