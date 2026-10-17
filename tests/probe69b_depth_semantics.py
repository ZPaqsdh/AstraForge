# -*- coding: utf-8 -*-
"""probe69b 深度语义终判（限定床面段）：先打印完整剖面，再只对"床面段"拟合。"""
import numpy as np
from pathlib import Path

WS = Path(str(Path(__file__).resolve().parents[2]))
dep = np.load(str(WS / '问题跟踪' / '_0210_D2C_原始深度.npy')).astype(np.float32)
pub = np.ascontiguousarray(dep[:, :-21][:, ::-1])
cols = slice(200, 420)

vs, ss = [], []
for r in range(300, 479, 4):
    m = pub[r, cols]
    m = m[m > 0]
    if len(m) > 50:
        vs.append(float(r))
        ss.append(float(np.median(m)))
v = np.array(vs)
s = np.array(ss)

print('[69b] v : s 剖面（v 为行号）')
line = []
for vv, sv in zip(v, s):
    line.append(f'{vv:.0f}:{sv:.0f}')
print('   ' + '  '.join(line))

# 床面段 = s 明显低于墙值（墙≈1184）的部分
wall_val = float(np.median(s[:3]))
mask = s < wall_val - 3
vb, sb = v[mask], s[mask]
print(f'\n[69b] 墙参考值 {wall_val:.0f}｜判定床面段 {len(vb)} 点：v {vb.min():.0f}~{vb.max():.0f}'
      f'｜s {sb.min():.0f}~{sb.max():.0f}')

if len(vb) >= 10:
    A_ = np.stack([vb, np.ones_like(vb)], axis=1)
    cL, *_ = np.linalg.lstsq(A_, sb, rcond=None)
    rmsL = float(np.sqrt(np.mean((sb - A_ @ cL) ** 2)))
    best = None
    for v0 in np.arange(vb.min() - 300, vb.min() - 0.5, 0.25):
        x = 1.0 / (vb - v0)
        Ah = np.stack([x, np.ones_like(vb)], axis=1)
        if not np.all(np.isfinite(Ah)):
            continue
        cH, *_ = np.linalg.lstsq(Ah, sb, rcond=None)
        rms = float(np.sqrt(np.mean((sb - Ah @ cH) ** 2)))
        if best is None or rms < best[0]:
            best = (rms, v0, cH)
    rmsH, v0, cH = best
    span = float(sb.max() - sb.min())
    print(f'\n  模型L 直线   : s = {cL[0]:+.4f}·v {cL[1]:+.1f}   RMS {rmsL:5.2f}（占跨度 {rmsL/span*100:4.1f}%）')
    print(f'  模型H 双曲线 : s = {cH[0]:+.1f}/(v{v0:+.2f}) {cH[1]:+.1f}  RMS {rmsH:5.2f}'
          f'（占跨度 {rmsH/span*100:4.1f}%）')
    print(f'  → {"★★ 直线胜 → 视差域（z=A/(C−s)）" if rmsL < rmsH else "★★ 双曲线胜 → 直读 mm"}'
          f'   L/H = {rmsL/rmsH:.2f}')
    # 由直线斜率估 A（A = 斜率 × k，k 未知；这里给"若 z=k/(v−v0)"的相容性）
    print(f'\n  [提示] 若 s 是线性剖面，则任意 (A,C) 都能还原成平面；'
          f'绝对尺度只由"一个已知距离"或 A=fx·B·k 决定')
