# -*- coding: utf-8 -*-
"""probe52 终验：新管线全链渲染（用存档桌面帧模拟修正后的发布口径）

新管线口径（2026-10-15 定案）：
  深度发布 = rawD（不翻）；RGB 发布 = flip(rawRGB)（翻一次）。
  存档帧的反推：stored depth(.npy) 是旧口径 pubD_old=flip(rawD) → rawD = flip(stored)
               stored rgb.png 是旧口径 rawRGB（未翻）→ 新发布 = flip(stored_rgb)
验证三个输出面各自的方向（基准：键盘左下）：
  ① 深度预览（灰度） ② 点云导出（cloudmath.depth_to_points，与实际导出同函数）
  ③ 融合帧0（depth_to_model_points）俯视
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = str(Path(__file__).resolve().parents[2])
OUT = ROOT + '/问题跟踪'
S = ROOT + '/扫描输出/turntable_20261013_162326'
sys.path.insert(0, ROOT + '/AstraForge')
from core import cloudmath

# ---- 新管线发布口径（从存档反推）----
stored = np.load(S + '/frame_000.npy').astype(np.float32)     # pubD_old
rawD = np.ascontiguousarray(stored[:, ::-1])                  # 新发布深度
stored_rgb = np.array(Image.open(S + '/frame_000_rgb.png').convert('RGB'))
new_rgb = np.ascontiguousarray(stored_rgb[:, ::-1])           # 新发布 RGB
H, W = rawD.shape

f = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 20)
def lab(img, t):
    im = Image.fromarray(img.copy())
    ImageDraw.Draw(im).text((8, 6), t, fill=(255, 255, 0), font=f)
    im = np.array(im)
    im[:, W // 2 - 1:W // 2 + 1] = [255, 40, 40]
    return im

# ---- ① 深度预览（灰度，与新 app 显示同口径）----
dm = rawD > 0
lo, hi = [float(x) for x in np.percentile(rawD[dm], [5, 95])]
gray = np.clip((rawD - lo) / (hi - lo + 1e-6), 0, 1) * 255
gray[~dm] = 0
gray3 = np.stack([gray] * 3, -1).astype(np.uint8)

# ---- ② 点云导出（与 recorder.save_snapshot 同调用）----
pts6 = cloudmath.depth_to_points(rawD, 1.0, rgb=new_rgb)      # Nx6 (xyz+rgb)
print('点云点数:', len(pts6))

def render(pts, view, Wpx=430, Hpx=340, bg=16):
    """view: 'top'=X-Z 俯视 / 'front'=X-Y 前视"""
    img = np.full((Hpx, Wpx, 3), bg, np.uint8)
    if len(pts) == 0:
        return img
    rng = np.random.default_rng(0)
    P = pts[rng.choice(len(pts), min(len(pts), 90000), replace=False)]
    a1, a2 = (0, 2) if view == 'top' else (0, 1)
    u = P[:, a1]; v = P[:, a2]
    lo1, hi1 = np.percentile(u, [1, 99]); lo2, hi2 = np.percentile(v, [1, 99])
    sx = (u - lo1) / (hi1 - lo1 + 1e-6) * (Wpx - 24) + 12
    sy = (1 - (v - lo2) / (hi2 - lo2 + 1e-6)) * (Hpx - 24) + 12
    ii = np.clip(sx.astype(int), 0, Wpx - 1); jj = np.clip(sy.astype(int), 0, Hpx - 1)
    col = np.clip(P[:, 3:6], 0, 255).astype(np.uint8)
    img[jj, ii] = col
    return img

top = render(pts6, 'top'); front = render(pts6, 'front')

# ---- ③ 融合帧0（转台模型系，angle=0，cam_dist 退化值）----
c = rawD[237:243, 317:323]; cv = c[c > 0]
cam_dist = float(np.median(cv)) if len(cv) else 500.0
pts_m = cloudmath.depth_to_model_points(rawD, 0.0, cam_dist, 1.0, rgb=new_rgb)
mdl = render(pts_m, 'top')

# ---- 拼接 ----
sep = np.full((H, 6, 3), 255, np.uint8)
row1 = np.concatenate([lab(gray3, '深度预览(新): 键盘应在左下'), sep,
                       lab(new_rgb, 'RGB预览(新): 键盘应在左下')], 1)
sep2 = np.full((340, 6, 3), 255, np.uint8)
row2 = np.concatenate([lab(top, '点云俯视(导出同函数): 键盘左下/手机右'),
                       sep2,
                       lab(front, '点云前视'),
                       sep2,
                       lab(mdl, '融合模型系(帧0): 键盘左下')], 1)
# 对齐宽度：row2 三块 430*3+12=1302 vs row1 2*646=1286 → 各自独立保存
Image.fromarray(row1).save(OUT + '/_终验52_新管线预览.png')
Image.fromarray(row2).save(OUT + '/_终验52_新管线点云.png')

# ---- 数值交叉核验：手机与键盘位置 ----
# 手机（近块）在 rawD 的 u 侧：用 probe49 同法
from scipy.ndimage import label as ndlabel, find_objects
band = rawD[200:380, 60:580]
desk = float(np.median(band[band > 0]))
m = (rawD > 0) & (rawD < desk - 10) & (rawD > desk - 160)
m[:160, :] = False; m[420:, :] = False; m[:, :50] = False; m[:, -50:] = False
l2, n2 = ndlabel(m)
best = None
for i, sl in enumerate(find_objects(l2), 1):
    if sl is None:
        continue
    area = int((l2[sl] == i).sum())
    h = sl[0].stop - sl[0].start; w = sl[1].stop - sl[1].start
    if area < 800 or w < 50 or h < 25 or w > 380 or h > 260:
        continue
    cu = (sl[1].start + sl[1].stop) / 2
    if best is None or area > best[0]:
        best = (area, cu)
if best:
    print(f'手机块(rawD): u={best[1]:.0f} → {"右 ✓(预期)" if best[1] > W/2 else "左 ✗"}')

# 手机环在 RGB 的 u（新 RGB 里应到 438 左右）
lum = 0.299 * new_rgb[:, :, 0] + 0.587 * new_rgb[:, :, 1] + 0.114 * new_rgb[:, :, 2]
mn = new_rgb.min(2)
ring = (mn > 165) & (lum > 190)
l3, n3 = ndlabel(ring)
bs = None
for i, sl in enumerate(find_objects(l3), 1):
    if sl is None:
        continue
    area = int((l3[sl] == i).sum())
    h = sl[0].stop - sl[0].start; w = sl[1].stop - sl[1].start
    if area < 50 or not (200 < (sl[0].start + sl[0].stop) / 2 < 420):
        continue
    cu = (sl[1].start + sl[1].stop) / 2
    if bs is None or area > bs[0]:
        bs = (area, cu)
if bs:
    print(f'手机环(new_rgb): u={bs[1]:.0f} → {"右 ✓(预期 ~438)" if bs[1] > W/2 else "左 ✗"}')

# 点云里手机块 X 符号（应 >0=右侧；点云X=图像u方向修正后）
ph = pts6[(pts6[:, 2] < -(1500)) & (np.abs(pts6[:, 1]) < 400)]
print(f'点云 X 中位数(整体): {np.median(pts6[:, 0]):+.0f}mm（负=偏左）')
print('已存 _终验52_新管线预览.png / _终验52_新管线点云.png')
