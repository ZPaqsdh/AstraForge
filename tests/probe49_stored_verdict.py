# -*- coding: utf-8 -*-
"""probe49 存档桌面会话·左右方向终判（10-13 转台 8 帧样板）

判定物证（同一时刻同一场景，帧对已同步）：
  物证1 手机环 —— rawRGB 里白色发光圆环（醒目唯一）
  物证2 手机块 —— pubD_old 里比桌面近的凸块（顶面）
  辅助  边缘叠加 —— pubD_old 梯度叠在 rawRGB 上，看边缘是否咬合

基准（用户）：正确方向 = 键盘在左下方。
已知：rawRGB（旧发布口径）里键盘在右下 → rawRGB = 镜像 → 正确 = M(rawRGB)。
关系：rawD ?= M(rawRGB)。若 pubD_old(=M(rawD)) 的物证与 rawRGB 同侧 → 关系成立
      → rawD = 正确方向 → 深度默认翻转应关闭（flip=False）。
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import label, find_objects, binary_opening

ROOT = str(Path(__file__).resolve().parents[2])
OUT = ROOT + '/问题跟踪'
S = ROOT + '/扫描输出/turntable_20261013_162326'

d_pub = np.load(S + '/frame_000.npy').astype(np.float32)     # 旧发布深度 = flip(rawD)
rgb = np.array(Image.open(S + '/frame_000_rgb.png').convert('RGB'))  # rawRGB
H, W = d_pub.shape
d_raw = np.ascontiguousarray(d_pub[:, ::-1])                  # 候选：rawD

# ---------- 物证1：rawRGB 里的发光圆环（手机环） ----------
lum = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
mn = rgb.min(2)
ring = (mn > 165) & (lum > 190)          # 白色高亮
ring = binary_opening(ring, iterations=1)
lab, n = label(ring)
best = None
for i, sl in enumerate(find_objects(lab), 1):
    if sl is None:
        continue
    area = int((lab[sl] == i).sum())
    h = sl[0].stop - sl[0].start; w = sl[1].stop - sl[1].start
    cu = (sl[1].start + sl[1].stop) / 2; cv = (sl[0].start + sl[0].stop) / 2
    if area < 60:
        continue
    # 环 = 中间有洞 → 用围框填充率粗判；这里只列候选项
    print(f'  RGB亮块: 面积{area:5d} 中心u={cu:5.1f} v={cv:5.1f} 框{w}x{h}')
    if 150 < cv < 420 and w > 40 and h > 30 and area < 4000:
        if best is None or area > best[0]:
            best = (area, cu, cv, w, h)
if best:
    area, cu_r, cv_r, w_r, h_r = best
    side_r = '左' if cu_r < W / 2 else '右'
    print(f'物证1 手机环(rawRGB): u={cu_r:.0f} v={cv_r:.0f} ({w_r}x{h_r}) → 【{side_r}】')
else:
    cu_r = None
    print('物证1 未找到手机环')

# ---------- 物证2：pubD_old 里的近物凸块 ----------
dm = d_pub > 0
# 桌面基准：中部大区域中值（避开底部噪声带）
band = d_pub[200:360, 80:560]
desk = float(np.median(band[(band > 0)]))
print(f'桌面基准深度: {desk:.0f} shift')
m = (d_pub > 0) & (d_pub < desk - 10) & (d_pub > desk - 160)
m[:160, :] = False       # 去掉显示器上沿
m[420:, :] = False       # 去掉底部键盘/手噪声带
m[:, :50] = False; m[:, -50:] = False
m = binary_opening(m, iterations=1)
lab2, n2 = label(m)
cand = []
for i, sl in enumerate(find_objects(lab2), 1):
    if sl is None:
        continue
    area = int((lab2[sl] == i).sum())
    h = sl[0].stop - sl[0].start; w = sl[1].stop - sl[1].start
    cu = (sl[1].start + sl[1].stop) / 2; cv = (sl[0].start + sl[0].stop) / 2
    if area < 800 or w < 50 or h < 25 or w > 380 or h > 260:
        continue
    vv = float(np.median(d_pub[sl][lab2[sl] == i]))
    cand.append((area, cu, cv, w, h, vv))
cand.sort(reverse=True)
print(f'物证2 pubD_old 近物候选块（降序）:')
for c in cand[:5]:
    side = '左' if c[1] < W / 2 else '右'
    print(f'  面积{c[0]:6d} u={c[1]:5.0f} v={c[2]:5.0f} {c[3]}x{c[4]} 深度{c[5]:.0f} → 【{side}】')
cu_d = cand[0][1] if cand else None

# ---------- 汇总判定 ----------
print()
if cu_r is not None and cu_d is not None:
    same_side = (cu_r < W / 2) == (cu_d < W / 2)
    print(f'物证对照: rawRGB 手机环 u={cu_r:.0f} | pubD_old 手机块 u={cu_d:.0f} → '
          f'{"【同侧】pubD_old≡rawRGB 方向" if same_side else "【异侧】pubD_old≠rawRGB 方向"}')
    print(f'→ 关系判定: rawD = {"M(rawRGB)" if same_side else "rawRGB"}'
          f' → 正确方向(R=M(rawRGB)) = {"rawD（应关闭深度翻转）" if same_side else "pubD_old（保持翻转）"}')

# ---------- 边缘叠加留证：pubD_old vs rawD 哪边咬合 rawRGB ----------
def grad(g):
    g = g.astype(np.float32)
    gx = np.zeros_like(g); gy = np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]
    gy[1:-1, :] = g[2:, :] - g[:-2, :]
    return np.sqrt(gx ** 2 + gy ** 2)

def norm_vis(a):
    v = np.clip((a - np.percentile(a[dm], 5)) /
                (np.percentile(a[dm], 95) - np.percentile(a[dm], 5) + 1e-6), 0, 1) * 255
    v[~dm] = 0
    return v

g_pub = grad(norm_vis(d_pub))
g_raw = grad(norm_vis(d_raw))
thr_pub = np.percentile(g_pub[dm], 92); thr_raw = np.percentile(g_raw[dm], 92)

ov1 = rgb.copy(); ov1[g_pub > thr_pub] = [255, 40, 40]
ov2 = rgb.copy(); ov2[g_raw > thr_raw] = [255, 40, 40]
f = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 20)
def lab(img, t):
    im = Image.fromarray(img)
    ImageDraw.Draw(im).text((8, 6), t, fill=(255, 255, 0), font=f)
    return np.array(im)
sep = np.full((H, 6, 3), 255, np.uint8)
sheet = np.concatenate([lab(ov1, 'pubD_old 边缘叠 rawRGB（旧口径若咬合）'),
                        sep,
                        lab(ov2, 'rawD 边缘叠 rawRGB（候选若咬合）')], 1)
Image.fromarray(sheet).save(OUT + '/_终验49_边缘咬合对比.png')
print('已存 _终验49_边缘咬合对比.png')

# 相关数值对照
def corr(a, b):
    a = a - a.mean(); b = b - b.mean()
    n1 = np.sqrt((a * a).sum()); n2 = np.sqrt((b * b).sum())
    return float((a * b).sum() / (n1 * n2)) if n1 > 0 and n2 > 0 else 0.0
gR = grad(rgb.mean(2))
print(f'数值: pubD_old↔rawRGB 梯度相关 {corr(g_pub, gR):+.4f} | rawD↔rawRGB {corr(g_raw, gR):+.4f}')

# ---------- 标注图（物证位置画框） ----------
ann = rgb.copy()
if cu_r is not None:
    u0 = int(cu_r - w_r / 2); v0 = int(cv_r - h_r / 2)
    ann[max(0, v0):v0 + h_r, max(0, u0):max(0, u0) + 3] = [0, 255, 0]
    ann[max(0, v0):v0 + h_r, u0 + w_r - 3:u0 + w_r] = [0, 255, 0]
    ann[max(0, v0):max(0, v0) + 3, max(0, u0):u0 + w_r] = [0, 255, 0]
    ann[v0 + h_r - 3:v0 + h_r, max(0, u0):u0 + w_r] = [0, 255, 0]
dvv = np.stack([norm_vis(d_pub)] * 3, -1).astype(np.uint8)
if cu_d is not None:
    a0, cu, cv, ww, hh, vv = cand[0]
    u0 = int(cu - ww / 2); v0 = int(cv - hh / 2)
    dvv[max(0, v0):v0 + hh, max(0, u0):max(0, u0) + 3] = [0, 255, 0]
    dvv[max(0, v0):v0 + hh, u0 + ww - 3:u0 + ww] = [0, 255, 0]
    dvv[max(0, v0):max(0, v0) + 3, max(0, u0):u0 + ww] = [0, 255, 0]
    dvv[v0 + hh - 3:v0 + hh, max(0, u0):u0 + ww] = [0, 255, 0]
sheet2 = np.concatenate([lab(ann, 'rawRGB + 手机环框'),
                         sep, lab(dvv, 'pubD_old + 手机块框')], 1)
Image.fromarray(sheet2).save(OUT + '/_终验49_物证标注.png')
print('已存 _终验49_物证标注.png')
