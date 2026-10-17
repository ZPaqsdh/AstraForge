# -*- coding: utf-8 -*-
"""probe50 转台角度符号实测：手机轨道一致性（8 帧样板）

原理：手机在转台轴外轨道上（帧间位置左→中→右变化）。
正确变换 = 各帧手机反旋回参考位 → 8 帧手机质心应收拢成一簇；
符号错 = 反旋方向反 → 质心散成 2 倍角扇面。
对比 2x2：输入 {旧(pubD,已镜像) / 新(rawD,未镜像)} × 角度符号 {现码'-' / 反转'+'}

输出物证：_终验50_手机检测_8帧.png（检测框）+ _终验50_角度符号.png（2x2 质心散点俯视）
"""
from pathlib import Path
import sys, json, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import label, find_objects, binary_opening

ROOT = str(Path(__file__).resolve().parents[2])
OUT = ROOT + '/问题跟踪'
S = ROOT + '/扫描输出/turntable_20261013_162326'
FX = FY = 572.0; CX, CY = 320.0, 240.0
H, W = 480, 640

man = json.load(open(S + '/manifest.json', encoding='utf-8'))
frames = man['frames']

# ---------- 逐帧检测手机凸块（在存储口径 pubD 上，u 与 R 镜像无关紧要） ----------
phones = []   # (u_pub, v, z_med, area)
ants = []
for i, fr in enumerate(frames):
    dep = np.load(os.path.join(S, fr['file'])).astype(np.float32)
    dm = dep > 0
    band = dep[200:380, 60:580]
    desk = float(np.median(band[band > 0]))
    m = (dep > 0) & (dep < desk - 12) & (dep > desk - 200)
    m[:200, :] = False; m[380:, :] = False; m[:, :60] = False; m[:, 580:] = False
    m = binary_opening(m, iterations=1)
    lab, n = label(m)
    best = None
    for j, sl in enumerate(find_objects(lab), 1):
        if sl is None:
            continue
        area = int((lab[sl] == j).sum())
        h = sl[0].stop - sl[0].start; w = sl[1].stop - sl[1].start
        if area < 700 or w < 45 or h < 28 or w > 420 or h > 300:
            continue
        cu = (sl[1].start + sl[1].stop) / 2; cv = (sl[0].start + sl[0].stop) / 2
        zm = float(np.median(dep[sl][lab[sl] == j]))
        if best is None or area > best[0]:
            best = (area, cu, cv, zm, w, h)
    if best:
        phones.append((best[1], best[2], best[3], best[0]))
        ants.append(best)
    else:
        phones.append(None); ants.append(None)
    print(f"frame_{i:03d} angle={fr['angle']:5.1f} 手机: " +
          (f"u={best[1]:.0f} v={best[2]:.0f} z={best[3]:.0f} area={best[0]}" if best else '未检出'))

# 检测可视化
f_font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 16)
tiles = []
for i, fr in enumerate(frames):
    dep = np.load(os.path.join(S, fr['file'])).astype(np.float32)
    dm = dep > 0
    lo, hi = [float(x) for x in np.percentile(dep[dm], [5, 95])]
    dv = np.clip((dep - lo) / (hi - lo + 1e-6), 0, 1) * 255
    vis = np.stack([dv] * 3, -1).astype(np.uint8)
    vis[~dm] = 0
    if ants[i]:
        area, cu, cv, zm, w, h = ants[i]
        u0 = int(cu - w / 2); v0 = int(cv - h / 2)
        vis[v0:v0 + 2, u0:u0 + w] = [0, 255, 0]; vis[v0 + h - 2:v0 + h, u0:u0 + w] = [0, 255, 0]
        vis[v0:v0 + h, u0:u0 + 2] = [0, 255, 0]; vis[v0:v0 + h, u0 + w - 2:u0 + w] = [0, 255, 0]
    im = Image.fromarray(vis).resize((320, 240))
    ImageDraw.Draw(im).text((4, 2), f"f{i} a={fr['angle']:.0f}", fill=(255, 255, 0), font=f_font)
    tiles.append(np.array(im))
rows = []
for r in range(2):
    rows.append(np.concatenate(tiles[r * 4:r * 4 + 4], 1))
Image.fromarray(np.concatenate(rows, 0)).save(OUT + '/_终验50_手机检测_8帧.png')
print('已存 _终验50_手机检测_8帧.png')

# ---------- 2x2 变换对比 ----------
def transform(pt_cam, angle_deg, cam_dist, sign):
    """pt_cam=(x,y,z) 相机系 → 模型系（sign=+1 现码 R(-a)；-1 反转）"""
    x, y, z = pt_cam
    P = np.array([x, y, z - cam_dist])
    a = np.deg2rad(angle_deg * sign)
    c, s = np.cos(a), np.sin(a)
    X = P[0] * c - P[2] * s
    Z = P[0] * s + P[2] * c
    return np.array([X, -P[1], -Z])   # y,z 取反（现码同款）

def centroids_for(input_kind, sign):
    pts = []
    for i, fr in enumerate(frames):
        ph = phones[i]
        if ph is None:
            continue
        u_pub, v, z, area = ph
        # 存储口径 u_pub 是 pubD 坐标；旧输入直接用，新输入 u_new = W-1-u_pub
        u = u_pub if input_kind == 'old' else (W - 1 - u_pub)
        x = (u - CX) * z / FX
        y = (v - CY) * z / FY
        # cam_dist：与管线退化逻辑一致（帧中心深度）
        dep = np.load(os.path.join(S, fr['file'])).astype(np.float32)
        cvv = dep[int(CY) - 3:int(CY) + 3, int(CX) - 3:int(CX) + 3]
        cvv = cvv[cvv > 0]
        cam_dist = float(np.median(cvv)) if len(cvv) else 500.0
        pts.append(transform((x, y, z), fr['angle'], cam_dist, sign))
    return np.array(pts)

def spread(P):
    c = P.mean(0)
    d = np.sqrt(((P[:, [0, 2]] - c[[0, 2]]) ** 2).sum(1))
    return float(d.std()), float(d.mean()), float(np.abs(d).max())

cases = [('旧输入(pubD)', 'old', +1), ('新输入(rawD) 现码-', 'new', +1), ('新输入(rawD) 反转+', 'new', -1)]
print()
print('=== 手机质心收束度（俯视 x-z 平面；越小=对齐越好）===')
results = {}
for name, kind, sign in cases:
    P = centroids_for(kind, sign)
    if len(P) < 2:
        continue
    sd, mn, mx = spread(P)
    results[name] = (P, sd, mn, mx)
    print(f'{name:22s}: 散度std={sd:7.1f}mm 平均散布={mn:7.1f}mm 最大={mx:7.1f}mm')

# 散点可视化
xall = np.concatenate([P[:, 0] for P, *_ in results.values()])
zall = np.concatenate([P[:, 2] for P, *_ in results.values()])
xr = (float(np.percentile(xall, 1)) - 20, float(np.percentile(xall, 99)) + 20)
zr = (float(np.percentile(zall, 1)) - 20, float(np.percentile(zall, 99)) + 20)
Wpx, Hpx = 360, 330
sheets = []
for name, (P, sd, mn, mx) in results.items():
    img = np.full((Hpx + 40, Wpx, 3), 20, np.uint8)
    im = Image.fromarray(img)
    dr = ImageDraw.Draw(im)
    dr.text((6, 4), f'{name}', fill=(255, 255, 0), font=f_font)
    dr.text((6, 22), f'std={sd:.0f}mm 平均={mn:.0f}mm', fill=(180, 180, 180), font=f_font)
    def sx(x):
        return int((x - xr[0]) / (xr[1] - xr[0]) * (Wpx - 30) + 15)
    def sz(z):
        return int(40 + (z - zr[0]) / (zr[1] - zr[0]) * (Hpx - 30) + 10)
    for k, p in enumerate(P):
        cx, cz = sx(p[0]), sz(p[2])
        col = (0, 220, 80) if k == 0 else (255, 160, 40)
        dr.ellipse([cx - 4, cz - 4, cx + 4, cz + 4], fill=col)
        dr.text((cx + 6, cz - 8), str(k), fill=(230, 230, 230), font=f_font)
    sheets.append(np.array(im))
sep = np.full((sheets[0].shape[0], 6, 3), 80, np.uint8)
Image.fromarray(np.concatenate([sheets[0], sep, sheets[1], sep, sheets[2]], 1)).save(
    OUT + '/_终验50_角度符号.png')
print('已存 _终验50_角度符号.png（俯视散点：绿=帧0 橙=其余帧）')
