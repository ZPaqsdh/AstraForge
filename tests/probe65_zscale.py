# -*- coding: utf-8 -*-
"""probe65 深度尺度（z）实测复核 —— 对照 Orbbec OpenNI2 规范 · 只读

用法：python tests/probe65_zscale.py [已知距离mm]

背景（2026-10-16 对照官方《Orbbec OpenNI2.0-SDK C++接口使用规范 1.0.2》）：
  · `[Depth] Output format. 100 - 1mm depth values (default), 102 - u9.2 Shift values`
  · `[Depth] Input format. 3 - Packed 11-bit (default on non-Android)`
  → 深度值**本身就是 mm**（设备端已用出厂参数换算）；u9.2 视差模式量级完全不同
    （1.2m 处只该出现 ~47 这种小数字，我们实测是 700~1300）→ 我们收到的就是 1mm 深度。
  推论：`mm_per_shift` 应为 **1.0**；本仓历史出现过 0.774（10-13 16:25 旧 studio 记录）——
  本探针用"卷尺实测距离 vs 画面读数"一次性闭环。

本探针只读：不改标定文件、不改设备配置；结束时停流 + 关激光（正常收尾链）。
判读：把屏/画面中心区对准一个"能用卷尺量的平面"，量出相机到它的距离 D 传参进来：
  · raw/D ≈ 1.0 → 1.0 正确（历史 0.774 是坏样本）
  · raw/D ≈ 1.29 → 反而要 0.774（异常，回报）
"""
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules.device.module import AstraLink, decode_frame   # noqa: E402

OUT = Path(__file__).resolve().parents[2] / '问题跟踪'
ROI = 60          # 中心 ROI 边长（px，取 60×60）

known = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0

link = AstraLink()
ok, msgs = link.connect()
if not ok:
    print('设备连接失败:', (msgs or '')[:120])
    sys.exit(1)
ok, msgs = link.ensure_ready()
if not ok:
    print('设备就绪失败:', msgs)
    sys.exit(1)

dep = None
t0 = time.time()
while time.time() - t0 < 10:
    fr = link.grab_frame(timeout=0.5)
    if fr is None:
        continue
    d = decode_frame(fr)
    if d is not None and (d > 0).sum() > 5000:
        dep = d
        break

try:
    if dep is None:
        print('未抓到有效深度帧'); sys.exit(1)

    H, W = dep.shape
    cy, cx = H // 2, W // 2
    h = ROI // 2
    roi = dep[cy - h:cy + h, cx - h:cx + h]
    v = roi[roi > 0]
    v_all = dep[dep > 0]

    print(f'[65] 帧 {dep.shape}｜有效 {float((dep > 0).mean() * 100):.1f}%')
    print(f'[65] 中心 {ROI}×{ROI}（u∈[{cx-h},{cx+h}), v∈[{cy-h},{cy+h})）：'
          f'中位 {np.median(v):.0f}｜均值 {v.mean():.0f}｜min {v.min():.0f}｜max {v.max():.0f}'
          f'（有效 {len(v)}/{roi.size}）' if len(v) else '[65] 中心 ROI 全无效')
    print(f'[65] 全帧有效像素：中位 {np.median(v_all):.0f}｜P10 {np.percentile(v_all, 10):.0f}'
          f'｜P90 {np.percentile(v_all, 90):.0f}  （单位按规范= mm）')
    # 分带（近/中/远）计数，看数据是否落在 1mm 语义的合理区间
    for lo, hi, name in ((0, 400, '近 <0.4m'), (400, 2000, '中 0.4~2m'),
                         (2000, 4000, '远 2~4m'), (4000, 10 ** 9, '超 4m')):
        m = (dep >= lo) & (dep < hi) & (dep > 0)
        print(f'       {name}: {float(m.mean()) * 100:5.1f}%')

    if known > 0 and len(v):
        med = float(np.median(v))
        print(f'\n[65] 实测量对比：画面中心读数 {med:.0f} vs 卷尺实测 {known:.0f} mm')
        print(f'     → 比值 raw/D = {med / known:.3f}'
              f'（1.000 = 1mm 直读，正确；≈1.29 = 该用 0.774；其它 = 回报数值）')

    # 留证图：深度伪彩 + 中心 ROI 框（供确认"量的是同一处"）
    try:
        from PIL import Image, ImageDraw
        lo, hi = float(np.percentile(v_all, 5)), float(np.percentile(v_all, 95))
        g = np.clip((dep.astype(np.float32) - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)
        rgb = np.stack([g, g, g], axis=2)
        rgb[dep <= 0] = (20, 20, 26)
        im = Image.fromarray(rgb)
        dr = ImageDraw.Draw(im)
        dr.rectangle([cx - h, cy - h, cx + h, cy + h], outline=(255, 255, 0), width=2)
        p = OUT / '_判读_0210深度尺度_ROI.png'
        im.save(p)
        np.save(str(OUT / '_0210深度尺度_原始帧.npy'), dep.astype(np.uint16))
        print(f'\n[65] 留证：{p}（黄框=量取区域）+ _0210深度尺度_原始帧.npy')
    except Exception as e:
        print('[65] 留证图失败:', e)
finally:
    try:
        link.ir_off()
    except Exception:
        pass
    try:
        link.dispose()
    except Exception:
        pass
    print('[65] 收尾完成（停流 + 关激光 + 释放 USB）')
