# -*- coding: utf-8 -*-
"""probe69 深度语义终判：床带剖面 s(v) 是「直线」还是「双曲线」？

数学依据（无需标定物、与尺度无关）：
  · 3D 平面在相机里的深度剖面 z(v) = k/(v − v0)   ← 双曲线
  · 若深度值 s 就是 mm（直读）：s(v) 应该是**双曲线**
  · 若 s 是视差域、z = A/(C − s)：则 s = C − A·(v−v0)/k → s(v) 应该是**直线**
两个假设互斥 → 谁拟合得好就是谁。
"""
import numpy as np
from pathlib import Path

WS = Path(str(Path(__file__).resolve().parents[2]))
dep = np.load(str(WS / '问题跟踪' / '_0210_D2C_原始深度.npy')).astype(np.float32)
pub = np.ascontiguousarray(dep[:, :-21][:, ::-1])
H, W = pub.shape

cols = slice(240, 380)


def profile(r0, r1, step=2):
    vs, ss = [], []
    for r in range(r0, r1, step):
        m = pub[r, cols]
        m = m[m > 0]
        if len(m) > 30:
            vs.append(float(r))
            ss.append(float(np.median(m)))
    return np.array(vs), np.array(ss)


for name, r0, r1 in (('床带(下段)', 300, 478), ('中段', 260, 340), ('整幅', 40, 478)):
    v, s = profile(r0, r1)
    if len(v) < 20:
        print(f'{name}: 点太少'); continue
    # --- 模型 L：s = α·v + β（视差域）---
    A_ = np.stack([v, np.ones_like(v)], axis=1)
    coefL, resL, *_ = np.linalg.lstsq(A_, s, rcond=None)
    fitL = A_ @ coefL
    rmsL = float(np.sqrt(np.mean((s - fitL) ** 2)))
    # --- 模型 H：s = k/(v − v0) + b（直读 mm；对 v0 做一维搜索后线性拟合 k,b）---
    best = None
    for v0 in np.arange(v.min() - 200, v.min() - 0.5, 0.5):
        x = 1.0 / (v - v0)
        Ah = np.stack([x, np.ones_like(v)], axis=1)
        if not np.all(np.isfinite(Ah)):
            continue
        ch, *_ = np.linalg.lstsq(Ah, s, rcond=None)
        fitH = Ah @ ch
        rms = float(np.sqrt(np.mean((s - fitH) ** 2)))
        if best is None or rms < best[0]:
            best = (rms, v0, ch)
    rmsH, v0, ch = best
    span = float(s.max() - s.min())
    print(f'\n=== {name}（{len(v)} 点，s 跨度 {span:.0f}）===')
    print(f'  模型L 直线   : s = {coefL[0]:+.4f}·v {coefL[1]:+.1f}   RMS 残差 {rmsL:6.2f}'
          f'   （相对跨度 {rmsL/span*100:5.1f}%）')
    print(f'  模型H 双曲线 : s = {ch[0]:+.1f}/(v{v0:+.1f}) {ch[1]:+.1f}      RMS 残差 {rmsH:6.2f}'
          f'   （相对跨度 {rmsH/span*100:5.1f}%）')
    print(f'  → {"★ 直线胜（视差域/需 z=A/(C−s)）" if rmsL < rmsH else "★ 双曲线胜（直读 mm）"}'
          f'   比值 L/H = {rmsL/rmsH:.2f}')
    if name == '床带(下段)':
        print('  前 12 个点：')
        for vv, ss in list(zip(v, s))[:12]:
            print(f'    v={vv:5.0f}  s={ss:7.1f}')
        print('  后 6 个点：')
        for vv, ss in list(zip(v, s))[-6:]:
            print(f'    v={vv:5.0f}  s={ss:7.1f}')
