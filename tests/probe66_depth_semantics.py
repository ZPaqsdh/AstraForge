# -*- coding: utf-8 -*-
"""probe66 深度语义判定 + D2C 可行性 —— 真机抓 RGB+深度一对，做视差实测定性（只读）

背景（2026-10-16 对照三条外部证据后）：
  ① 官方《OpenNI2 SDK 规范》：`Output format 100 = 1mm depth values`（但这是**主机侧**输出口径）
  ② 官方驱动日志（本机，10-07）：`Depth.OutputFormat=100` + **ShiftScale=10 / ConstShift=200 /
     ZPD=65.0 / ZPPS=0.056983 / LDDIS=7.5 / DCRCDIS=2.63 / Fov=1.0226rad(58.59°) / Fov=0.7966rad(45.64°)**
     —— 主机侧建 S2D 表才需要这些 → 设备出的是 **shift/视差**，mm 是驱动算的
  ③ astra_raw 包作者注释：`K = fx(570) × baseline(75) × sub_pixel(8) = 342000`，`depth = K / Y11`
     → 原始值是 **1/8 像素视差**

判定手段（本探针）：
  · 深度↔彩色的**视差** = f_c·B_cd / z（f_c=601.275，B_cd=24.571mm 出厂外参，与深度尺度无关）
    - z=0.29m（K/Y11 口径）→ 视差 ≈ **51 px**（肉眼可见的大错位）
    - z=1.18m（"直读 mm"口径）→ 视差 ≈ **12.5 px**
    - z=2.5m → 6 px
  用"深度有效区轮廓/深度台阶边"对彩色梯度图做水平位移搜索，取最优位移 → 反推 z。

用法：python tests/probe66_depth_semantics.py
输出：`问题跟踪/_判读_0210_D2C_场景.png`（彩色 | 深度伪彩 | 位移搜索曲线）
"""
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules.device.module import AstraLink, decode_frame   # noqa: E402

OUT = Path(__file__).resolve().parents[2] / '问题跟踪'
F_C = 601.275      # 彩色 fx（出厂）
B_CD = 24.571      # 彩色↔深度 基线 mm（出厂外参 t）
RAW = None

# ---------- 抓帧 ----------
link = AstraLink()
ok, msgs = link.connect()
if not ok:
    print('设备连接失败:', (msgs or '')[:120]); sys.exit(1)
ok, msgs = link.ensure_ready()
if not ok:
    print('设备就绪失败:', msgs); sys.exit(1)

import cv2                                    # noqa: E402
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
rgb = None
for _ in range(20):
    okr, f = cap.read()
    if okr and f is not None:
        rgb = f
        break
    time.sleep(0.05)
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
        print('未抓到深度帧'); sys.exit(1)
    if rgb is None:
        print('未抓到 RGB 帧'); sys.exit(1)
    print(f'[66] RGB {rgb.shape} | 深度 {dep.shape} 有效 {float((dep>0).mean())*100:.1f}%')

    # 深度按显示口径（裁左 21 列 → 619；翻面）——与 RGB 同向
    d = dep[:, 21:] if dep.shape[1] == 640 else dep
    d = np.ascontiguousarray(d[:, ::-1])          # _pv_flip：镜像开关关闭时才翻；此处取直出口径
    d = dep[:, 21:]                                # 直出（B 口径：与 RGB 同向）＝不翻
    valid = d > 0

    v = d[valid]
    print(f'[66] 深度 raw：中位 {np.median(v):.0f}｜P10 {np.percentile(v,10):.0f}｜P90 {np.percentile(v,90):.0f}'
          f'｜min {v.min():.0f}｜max {v.max():.0f}')

    # ---- 视差搜索：深度有效区/深度台阶 在彩色梯度图上的最佳水平位移 ----
    H, W = d.shape
    # 深度台阶边（近/远边界）：对每个像素取其与右邻的深度差
    dv = np.abs(np.diff(d.astype(np.float32), axis=1))
    thr = np.percentile(dv[valid[:, :-1]], 99.0) if valid.any() else 1e9
    edge = np.zeros_like(d, bool)
    edge[:, :-1] = (dv > max(thr, 30.0)) & valid[:, :-1]
    ys, xs = np.nonzero(edge)
    print(f'[66] 深度台阶边像素 {len(xs)} 个（阈值 {max(thr,30.0):.0f}）')

    # RGB 梯度（灰度）
    g = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3))
    gy = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
    grad = gx + gy
    print(f'[66] RGB 梯度：中位 {np.median(grad):.1f}｜P95 {np.percentile(grad,95):.1f}')

    scores = []
    for dx in range(-80, 81):
        x2 = np.clip(xs + dx, 0, W - 1)
        s = float(np.mean(grad[ys, x2])) if len(xs) else 0.0
        scores.append((dx, s))
    best_dx, best_s = max(scores, key=lambda t: t[1])
    base_s = dict(scores)[0]
    print(f'[66] 最佳水平位移 dx={best_dx}（彩色梯度均值 {best_s:.1f} vs 0 位移 {base_s:.1f}）')
    for dx in (-60, -50, -40, -30, -20, -12, -8, 0, 8, 12, 20, 30, 40, 50, 60):
        if dx in dict(scores):
            print(f'        dx={dx:+4d} → 分数 {dict(scores)[dx]:6.1f}')

    # ---- 两种口径下 z 的预测与视差对照 ----
    raw_med = float(np.median(v))
    z_mm_hypo = raw_med
    z_disp_hypo = 342000.0 / raw_med
    for name, z in (('直读 mm 口径', z_mm_hypo), ('K/Y11 视差口径', z_disp_hypo)):
        print(f'[66] {name}: z≈{z:.0f}mm → 预测视差 {F_C*B_CD/z:.1f}px')

    # 反推：由最佳位移算 z
    if best_dx != 0:
        z_meas = F_C * B_CD / abs(best_dx)
        print(f'[66] ★ 由实测位移反推：z ≈ {z_meas:.0f} mm（对应 raw {raw_med:.0f}）')
        print(f'     → raw/z = {raw_med/z_meas:.3f}（≈1.0 支持"直读 mm"；≈0.78 支持 K/Y 关系）')

    # ---- 留证图 ----
    try:
        from PIL import Image
        dep8 = np.zeros((H, W), np.uint8)
        lo, hi = float(np.percentile(v, 2)), float(np.percentile(v, 98))
        dep8[valid] = np.clip((d[valid] - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)
        dcol = cv2.applyColorMap(dep8, cv2.COLORMAP_JET)
        dcol[~valid] = 0
        dcol = cv2.cvtColor(dcol, cv2.COLOR_BGR2RGB)
        canv = np.concatenate([cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB), dcol], axis=1)
        Image.fromarray(canv).save(OUT / '_判读_0210_D2C_场景.png')
        np.save(str(OUT / '_0210_D2C_原始深度.npy'), dep.astype(np.uint16))
        cv2.imwrite(str(OUT / '_0210_D2C_原始RGB.png'), rgb)
        print(f'[66] 留证：{(OUT / "_判读_0210_D2C_场景.png").name}')
    except Exception as e:
        print('[66] 留证失败:', e)
finally:
    try:
        cap.release()
    except Exception:
        pass
    try:
        link.ir_off()
    except Exception:
        pass
    try:
        link.dispose()
    except Exception:
        pass
    print('[66] 收尾完成')
