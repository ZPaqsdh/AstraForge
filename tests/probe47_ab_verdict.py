# -*- coding: utf-8 -*-
"""probe47 双验证：RGB 与深度左右关系的最终判定（A: 与RGB同向 / B: 与RGB互为镜像）
验证①（存档帧）: 找"手机"——RGB里手机(环形灯)在 u≈201；深度里手机顶面(=浅色凸台,
   深度值比桌面小)的连通块中心 u 在哪侧?
   - 若深度手机 u≈201（左）→ 存档深度与RGB【同向】→ B（两者都是镜像）→ 需双双翻转
   - 若深度手机 u≈439（右）→ 【互为镜像】→ A（深度已是现实方向）→ 只翻 RGB
验证②（实机）: 抓一帧原始深度+原始RGB，做边缘相关，看 rawDepth 与 rawRGB 同向还是镜像
"""
from pathlib import Path
import sys, time
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import label, find_objects

ROOT = str(Path(__file__).resolve().parents[2])
D = ROOT + r'/扫描输出/turntable_20261013_162326'

# ============ 验证①：存档帧里手机位置 ============
dep = np.load(D + '/frame_000.npy').astype(np.float32)
rgb = np.array(Image.open(D + '/frame_000_rgb.png').convert('RGB'))
H, W = dep.shape
print('=== 验证① 存档帧：手机（深度凸台）在深度图哪侧 ===')
print('参照：RGB 里手机（环形灯）在 u≈201（左）；RGB底部键盘灯在右(6511:4)')

# 桌面基准深度（画面中下方大片区域的中值）
desk = float(np.median(np.concatenate([dep[240:340, 0:100].flatten(), dep[240:340, 540:640].flatten()])))
desk = desk if desk > 0 else 730.0
print(f'桌面基准深度（边缘区中值）: {desk:.0f} shift')

# 手机顶面特征：比桌面近 15~80 shifts 的大连通块，位于画面中带
band = dep.copy()
m = (band > 0) & (band < desk - 12) & (band > desk - 120)
m[:170, :] = False        # 去掉显示器上沿
m[430:, :] = False        # 去掉最底部（键盘/手）
m[:, :40] = False; m[:, -40:] = False
lab, n = label(m)
best = None
for sl in find_objects(lab):
    if sl is None: continue
    h = sl[0].stop - sl[0].start; w = sl[1].stop - sl[1].start
    area = int(m[sl].sum())
    if area < 1500 or w < 60 or h < 30 or w > 350 or h > 220: continue
    cu = (sl[1].start + sl[1].stop) / 2; cv = (sl[0].start + sl[0].stop) / 2
    vv = float(np.median(dep[sl][m[sl]]))
    if best is None or area > best[0]:
        best = (area, cu, cv, w, h, vv)
if best:
    area, cu, cv, w, h, vv = best
    side = '左' if cu < W / 2 else '右'
    print(f'最大近物块: 面积 {area} | 中心 u={cu:.0f} v={cv:.0f} | {w}x{h} | 深度 {vv:.0f} → 在【{side}】')
    if abs(cu - 201) < abs(cu - 439):
        verdict1 = 'B'   # 与 RGB 同向 → 双镜像
        print('→ 深度手机位置≈RGB手机位置 → 深度与RGB【同向】→ 判定 B（双双镜像）')
    else:
        verdict1 = 'A'
        print('→ 深度手机位置≈RGB手机镜像位置 → 深度与RGB【互为镜像】→ 判定 A（深度=现实）')
else:
    verdict1 = '?'
    print('未找到显著近物块（判定不了）')

# 保存可视化：存档深度 + 该块标注
vis = np.stack([np.clip((dep - 550) / 500 * 255, 0, 255)] * 3, -1).astype(np.uint8)
vis[dep <= 0] = 10
if best:
    area, cu, cv, w, h, vv = best
    u0 = int(cu - w / 2); v0 = int(cv - h / 2)
    vis[max(0, v0):v0 + h, max(0, u0):max(0, u0) + 2] = [255, 60, 60]
    vis[max(0, v0):v0 + h, u0 + w - 2:u0 + w] = [255, 60, 60]
    vis[max(0, v0):max(0, v0) + 2, max(0, u0):u0 + w] = [255, 60, 60]
    vis[v0 + h - 2:v0 + h, max(0, u0):u0 + w] = [255, 60, 60]
Image.fromarray(vis).save(ROOT + '/问题跟踪/_判读7_存档深度_手机块.png')
print('已存 _判读7_存档深度_手机块.png')

# ============ 验证②：实机原始帧 ============
print()
print('=== 验证② 实机：原始深度 vs 原始RGB 边缘相关 ===')
sys.path.insert(0, ROOT + '/AstraForge')
from modules.device.module import AstraLink, decode_frame

rawD = None; rawR = None
try:
    link = AstraLink()
    ok, msg = link.connect()
    if ok:
        link.ensure_ready()
        t0 = time.time()
        while time.time() - t0 < 6:
            f = link.grab_frame(timeout=0.5)
            if f is None: continue
            d = decode_frame(f)
            if d is not None and (d > 0).sum() > 1000:
                rawD = d; break
        # 同期抓 RGB
        try:
            import cv2
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            time.sleep(0.4)
            for _ in range(12):
                ok3, fr = cap.read()
                if ok3 and fr is not None:
                    rawR = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB); break
                time.sleep(0.12)
            cap.release()
        except Exception as e:
            print('RGB 抓取异常:', str(e)[:70])
        try: link.ir_off()
        except Exception: pass
    else:
        print('设备连接失败:', msg[:60] if msg else '')
except Exception as e:
    print('设备异常:', str(e)[:80])

if rawD is not None and rawR is not None:
    def grad(g):
        g = g.astype(np.float32)
        gx = np.zeros_like(g); gy = np.zeros_like(g)
        gx[:, 1:-1] = g[:, 2:] - g[:, :-2]
        gy[1:-1, :] = g[2:, :] - g[:-2, :]
        return np.sqrt(gx ** 2 + gy ** 2)
    dm = rawD > 0
    lo, hi = [float(x) for x in np.percentile(rawD[dm], [5, 95])]
    dv = np.clip((rawD - lo) / (hi - lo + 1e-6), 0, 1) * 255
    dv[~dm] = np.median(dv[dm])
    gD = grad(dv); gR = grad(rawR.mean(2))
    def corr(a, b):
        a = a - a.mean(); b = b - b.mean()
        n1 = np.sqrt((a * a).sum()); n2 = np.sqrt((b * b).sum())
        return float((a * b).sum() / (n1 * n2)) if n1 > 0 and n2 > 0 else 0.0
    c_same = corr(gD, gR); c_mirr = corr(gD[:, ::-1], gR)
    print(f'实机边缘相关: 同向 {c_same:+.4f} | 镜像 {c_mirr:+.4f}')
    verdict2 = 'A' if abs(c_same) >= abs(c_mirr) else 'B'
    print('→ 判定', verdict2, ('（rawDepth与rawRGB同向 → 现实方向=同向侧）' if verdict2 == 'A' else '（rawDepth与rawRGB互为镜像）'))

    # 拼图留证
    tiles = [np.stack([dv] * 3, -1).astype(np.uint8), np.stack([dv[:, ::-1]] * 3, -1).astype(np.uint8),
             rawR, rawR[:, ::-1]]
    sep = np.full((480, 8, 3), 60, np.uint8)
    row = np.concatenate([np.concatenate([t.astype(np.uint8), sep], 1) for t in tiles], 1)
    Image.fromarray(row).save(ROOT + '/问题跟踪/_判读7_实机原始帧.png')
    print('已存 _判读7_实机原始帧.png（深度原始|深度镜像|RGB原始|RGB镜像）')
else:
    print('实机数据不全（跳过验证②）：深度', rawD is not None, '| RGB', rawR is not None)

print()
print('=== 汇总 ===')
print('验证① 判定:', verdict1, '| 验证② 判定:', '见上' )