# -*- coding: utf-8 -*-
"""probe67 D2C 对齐实测（软件 D2C 可行性 + 深度尺度判定）—— 真机 RGB+深度，只读

思路（全部用**出厂参数**，不需标定物）：
  1. 深度原始帧 → 发布向（翻面）→ 去垃圾带（右 21 列）→ 619×480，与 RGB 同向
  2. 「无穷远对齐」：按内参把深度视场重采样到彩色视场（不算视差，只算角度）
       x/z = (u+21-cx_d)/fx_d ;  y/z = (v-cy_d)/fy_d
       u_c = fx_c·x/z + cx_c     ;  v_c = fy_c·y/z + cy_c
  3. 在彩色图上搜索残余平移 (dx,dy) —— 这就是**视差**（∝ 1/z）：
       z = fx_c·B_cd / dx      （B_cd = 24.571mm 出厂外参；fx_c = 601.275）
  4. 分带（近带/远带）分别搜索 → 每带一个 z → 与"深度值直读 mm"假设对照

用法：python tests/probe67_d2c_align.py
输出：问题跟踪/_判读_0210_D2C对齐.png（对齐叠加 + 搜索曲线）
"""
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules.device.module import AstraLink, decode_frame   # noqa: E402

OUT = Path(__file__).resolve().parents[2] / '问题跟踪'

# 出厂参数（flash 0x70000）
FXD = FYD = 580.703
CXD, CYD = 318.163, 249.847
FXC, FYC = 601.275, 601.275
CXC, CYC = 324.221, 241.019
B_CD = 24.571                     # 彩色↔深度基线 mm
CROP_L = 21

import cv2                                              # noqa: E402

link = AstraLink()
ok, msgs = link.connect()
if not ok:
    print('设备连接失败:', (msgs or '')[:120]); sys.exit(1)
ok, msgs = link.ensure_ready()
if not ok:
    print('设备就绪失败:', msgs); sys.exit(1)

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
rgb = None
for _ in range(30):
    okr, f = cap.read()
    if okr and f is not None:
        rgb = f; break
    time.sleep(0.05)
dep = None
t0 = time.time()
while time.time() - t0 < 10:
    fr = link.grab_frame(timeout=0.5)
    if fr is None:
        continue
    d = decode_frame(fr)
    if d is not None and (d > 0).sum() > 5000:
        dep = d; break

try:
    if dep is None or rgb is None:
        print('抓帧失败:', 'dep' if dep is None else '', 'rgb' if rgb is None else ''); sys.exit(1)

    # ---- 1) 发布向深度（翻面 + 去垃圾带右侧 21 列）----
    pub = np.ascontiguousarray(dep[:, :-CROP_L][:, ::-1])
    Hp, Wp = pub.shape
    print(f'[67] 发布向深度 {pub.shape}｜RGB {rgb.shape}｜有效 {float((pub>0).mean())*100:.1f}%')

    # ---- 2) 无穷远对齐：深度视场 → 彩色视场 ----
    vv, uu = np.mgrid[0:Hp, 0:Wp].astype(np.float32)
    X = (uu + CROP_L - CXD) / FXD          # x/z
    Y = (vv - CYD) / FYD                   # y/z
    uc = FXC * X + CXC
    vc = FYC * Y + CYC
    Hc, Wc = rgb.shape[:2]
    mapx = uc.astype(np.float32)
    mapy = vc.astype(np.float32)
    warped = cv2.remap(pub.astype(np.float32), mapx, mapy, cv2.INTER_NEAREST,
                       borderValue=0)      # 深度值（原始单位）投到彩色视场
    inside = (mapx >= 0) & (mapx <= Wc - 1) & (mapy >= 0) & (mapy <= Hc - 1)
    print(f'[67] 无穷远对齐后落在彩色画幅内的像素 {float(inside.mean())*100:.1f}%')

    # ---- 3) 深度边（台阶）+ RGB 梯度 ----
    dv = np.abs(np.diff(warped, axis=1))
    pos = warped > 0
    thr = max(float(np.percentile(dv[pos[:, :-1]], 99.0)) if pos.any() else 30.0, 30.0)
    edge = np.zeros_like(warped, bool)
    edge[:, :-1] = (dv > thr) & pos[:, :-1] & inside[:, :-1]
    g = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY).astype(np.float32)
    grad = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)) + \
        np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
    print(f'[67] 深度台阶边 {int(edge.sum())} 像素（阈值 {thr:.0f}）')

    def profile_ncc(mask, dx, dy):
        """把 mask 平移 (dx,dy) 后，取其处 RGB 梯度的均值（已做全局归一）"""
        ys, xs = np.nonzero(mask)
        x2 = np.clip(xs + dx, 0, Wc - 1)
        y2 = np.clip(ys + dy, 0, Hc - 1)
        if len(xs) < 50:
            return -9.9
        s = grad[y2, x2]
        return float((s.mean() - gm) / (gs + 1e-6))

    gm = None
    cover = np.zeros((Hc, Wc), bool)
    _x2 = np.clip(mapx, 0, Wc - 1).astype(np.int32)
    _y2 = np.clip(mapy, 0, Hc - 1).astype(np.int32)
    cover[_y2[inside], _x2[inside]] = True
    gm = float(np.mean(grad[cover])) if cover.any() else float(grad.mean())
    gs = float(np.std(grad[cover])) if cover.any() else float(grad.std())
    print(f'[67] RGB 梯度（深度覆盖区内 {float(cover.mean())*100:.1f}%）：均值 {gm:.1f}｜标准差 {gs:.1f}')

    # 分带：以深度中位数为界（近带 / 远带）
    med = float(np.median(warped[pos]))
    near = edge & (warped < med) & pos
    far = edge & (warped >= med) & pos
    print(f'[67] 分带：中位 {med:.0f}｜近带边 {int(near.sum())}｜远带边 {int(far.sum())}')

    results = {}
    for tag, m in (('全部', edge), ('近带', near), ('远带', far)):
        best = None
        curve = []
        for dx in range(-40, 41):
            sc = profile_ncc(m, dx, 0)
            curve.append((dx, sc))
            if best is None or sc > best[1]:
                best = (dx, sc)
        # 竖向也扫一遍（dy 应≈0，用于自检）
        bestdy = max(((dy, profile_ncc(m, best[0], dy)) for dy in range(-6, 7)),
                     key=lambda t: t[1])
        results[tag] = (best[0], best[1], bestdy[0], curve)
        z_impl = (FXC * B_CD / abs(best[0])) if best[0] != 0 else float('inf')
        print(f'[67] {tag}: 最佳 dx={best[0]:+d}（NCC {best[1]:+.2f}）｜dy={bestdy[0]:+d}'
              f'｜由 dx 反推 z={z_impl:.0f}mm')
        top = sorted(curve, key=lambda t: -t[1])[:5]
        print('        top5 dx/score: ' + '  '.join(f'{d:+d}/{s:+.2f}' for d, s in top))

    # ---- 4) 与两种"深度语义"假设对照 ----
    z_mm = med
    z_inv = 342000.0 / med
    print(f'\n[67] 假设对照（用远端带读数 {med:.0f}）：')
    for name, z in (('假设A：深度值直读 mm', z_mm), ('假设B：K/Y11（342000/值）', z_inv)):
        print(f'   {name} → z={z:.0f}mm → 预测视差 {FXC*B_CD/z:.1f}px')
    for tag in results:
        dx = results[tag][0]
        if dx:
            z_m = FXC * B_CD / abs(dx)
            print(f'   实测[{tag}] dx={dx:+d} → z={z_m:.0f}mm（raw {med:.0f}；'
                  f'raw/z={med/z_m:.3f}）')

    # ---- 5) 留证图：RGB 上叠深度台阶边 + 对齐位移示意 ----
    try:
        from PIL import Image
        vis = rgb.copy()
        ys, xs = np.nonzero(edge)
        vis[ys, xs] = (255, 0, 0)
        dxa = results['全部'][0]
        x2 = np.clip(xs + dxa, 0, Wc - 1)
        vis[ys, x2] = (0, 255, 255)
        Image.fromarray(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB)).save(OUT / '_判读_0210_D2C对齐.png')
        print(f'[67] 留证：_判读_0210_D2C对齐.png（红=深度边落点｜青=平移 dx 后落点）')
    except Exception as e:
        print('[67] 留证失败:', e)
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
    print('[67] 收尾完成')
