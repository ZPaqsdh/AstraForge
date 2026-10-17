# -*- coding: utf-8 -*-
"""probe55 BUG-009 排查：深度左侧黑带 + RGB/深度尺寸不匹配

问题（用户实测）：深度画面有一整条无数据区（RGB 同位置有画面）；两画面"尺寸不同"。
本探针（只读排查，不改任何东西）：
  ① 抓 raw 深度（decode_frame 原始，无任何翻转）→ 无效区分布（按列/按行统计）
  ② 抓 RGB 各分辨率（原生 / 640×480 / 1280×800）→ 实际尺寸与内容关系（缩放or裁剪）
  ③ 估计 RGB↔深度 的对齐关系（尺度+平移搜索，边缘相关）
  ④ 留证图 → 问题跟踪/_排查009_*.png
"""
from pathlib import Path
import sys, time
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT + '/AstraForge')
OUT = ROOT + '/问题跟踪'
from modules.device.module import AstraLink, decode_frame
import cv2

f = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 17)
def lab(img, t):
    im = Image.fromarray(np.ascontiguousarray(img.copy()))
    ImageDraw.Draw(im).text((8, 4), t, fill=(255, 255, 0), font=f)
    return np.array(im)

# ---------- ① raw 深度 ----------
rawD = None
link = AstraLink()
ok, msg = link.connect()
if not ok:
    print('设备连接失败:', (msg or '')[:80]); sys.exit(1)
link.ensure_ready()
t0 = time.time()
while time.time() - t0 < 8:
    fr = link.grab_frame(timeout=0.5)
    if fr is None:
        continue
    d = decode_frame(fr)
    if d is not None and (d > 0).sum() > 5000:
        rawD = d; break
print(f'① raw 深度: {rawD.shape} 有效像素 {(rawD>0).sum()} ({(rawD>0).mean()*100:.1f}%)')

H, W = rawD.shape
inv = rawD <= 0
# 按列无效占比（哪一列起是黑带）
col_inv = inv.mean(axis=0)
row_inv = inv.mean(axis=1)
dead_cols = np.where(col_inv > 0.9)[0]
if len(dead_cols) == 0:
    print('  无效>90% 的列: 无')
else:
    left_seg = dead_cols[dead_cols < W // 2]
    right_seg = dead_cols[dead_cols >= W // 2]
    print(f'  无效>90% 的列: 左段 {left_seg[:5].tolist()}..{left_seg[-5:].tolist()} | 右段 {right_seg[:5].tolist()}..{right_seg[-5:].tolist()}')
print(f'  全图无效占比: {inv.mean()*100:.1f}% | 左半 {inv[:, :W//2].mean()*100:.1f}% | 右半 {inv[:, W//2:].mean()*100:.1f}%')
# 边缘条带检测：最左/最右连续全无效列数
li = 0
while li < W and col_inv[li] > 0.85: li += 1
ri = 0
while ri < W and col_inv[W-1-ri] > 0.85: ri += 1
print(f'  最左连续无效列: {li} | 最右连续无效列: {ri}')
# 有效区的最大矩形（粗略）
cols_ok = col_inv < 0.5
if cols_ok.any():
    u0, u1 = np.where(cols_ok)[0][[0, -1]]
    print(f'  主要有效列范围: u ∈ [{u0}, {u1}]（宽 {u1-u0+1}）')

vis_d = np.clip((rawD - np.percentile(rawD[rawD>0], 5)) /
                (np.percentile(rawD[rawD>0], 95) - np.percentile(rawD[rawD>0], 5) + 1e-6) * 255, 0, 255).astype(np.uint8)
vis_d[rawD <= 0] = 0
vis3 = np.stack([vis_d]*3, -1)
# 无效标记叠加（红=无效）
ov = vis3.copy(); ov[inv] = (ov[inv] * 0.4 + np.array([160, 0, 0]) * 0.6).astype(np.uint8)

# ---------- ② RGB 各分辨率 ----------
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
frames = {}
if cap.isOpened():
    time.sleep(0.5)
    # 原生（不设置）
    for _ in range(10):
        ok2, fr = cap.read()
        if ok2: native = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB); break
    frames['native'] = native
    print(f'② RGB 原生: {native.shape[1]}x{native.shape[0]}')
    for (w, h, tag) in ((640, 480, '640x480'), (1280, 800, '1280x800')):
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        time.sleep(0.6)
        aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        got = None
        for _ in range(15):
            ok3, fr = cap.read()
            if ok3: got = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB); break
            time.sleep(0.1)
        if got is not None:
            frames[tag] = got
            print(f'  设置 {w}x{h} → 实际 {aw}x{ah}，帧 {got.shape[1]}x{got.shape[0]}')
    cap.release()

# 640 vs 1280 内容关系（等比缩放 or 裁剪？）：把 640 放大到 1280x800 比相关
if '640x480' in frames and '1280x800' in frames:
    a = frames['640x480'].astype(np.float32).mean(2)
    b = frames['1280x800'].astype(np.float32).mean(2)
    a_up = cv2.resize(a, (b.shape[1], b.shape[0]))
    ca = a_up - a_up.mean(); cb = b - b.mean()
    corr_fit = float((ca*cb).sum() / (np.sqrt((ca*ca).sum())*np.sqrt((cb*cb).sum()) + 1e-9))
    # 裁剪假设：1280 中心裁 4:3（先按高度 800 裁宽 1067）
    ch = 800; cw = int(800*4/3)
    x0 = (1280-cw)//2
    crop = b[:, x0:x0+cw]
    crop_r = cv2.resize(crop, (640, 480)).astype(np.float32)
    cc = crop_r - crop_r.mean()
    corr_crop = float((cc*(a-a.mean())).sum() / (np.sqrt((cc*cc).sum())*np.sqrt(((a-a.mean())**2).sum()) + 1e-9))
    print(f'  [关系] 640×480 vs 1280×800: 全图缩放相关 {corr_fit:.3f} | 中裁4:3再缩放相关 {corr_crop:.3f}')

# ---------- ③ RGB ↔ 深度 对齐搜索 ----------
def edge_map(g):
    g = g.astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    e = np.sqrt(gx*gx + gy*gy)
    return e

best = None
if 'native' in frames and len(frames):
    rgbf = frames.get('1280x800', frames.get('native'))
    gh, gw = 200, int(200 * rgbf.shape[1] / rgbf.shape[0])
    redge = edge_map(cv2.resize(rgbf.mean(2), (gw, gh)))
    dedge0 = edge_map(cv2.resize(vis_d.astype(np.float32), (160, 120)))
    for s in np.arange(0.7, 1.35, 0.05):
        for dx in range(-250, 251, 25):
            for dy in range(-120, 121, 20):
                M = np.float32([[s, 0, dx], [0, s, dy]])  # depth→rgb 空间
                w = cv2.warpAffine(dedge0, M, (gw, gh))
                c = float((w * redge).sum() / (np.sqrt((w*w).sum()) * np.sqrt((redge*redge).sum()) + 1e-9))
                if best is None or c > best[0]:
                    best = (c, s, dx, dy)
    print(f'③ 对齐粗搜: corr={best[0]:.3f} scale={best[1]:.2f} dx={best[2]} dy={best[3]} (depth→RGB@200px高)')
    # 细化
    c0, s0, dx0, dy0 = best
    for s in np.arange(s0-0.06, s0+0.06, 0.01):
        for dx in range(dx0-30, dx0+31, 5):
            for dy in range(dy0-25, dy0+26, 4):
                M = np.float32([[s, 0, dx], [0, s, dy]])
                w = cv2.warpAffine(dedge0, M, (gw, gh))
                c = float((w * redge).sum() / (np.sqrt((w*w).sum()) * np.sqrt((redge*redge).sum()) + 1e-9))
                if c > best[0]:
                    best = (c, s, dx, dy)
    print(f'③ 对齐细化: corr={best[0]:.3f} scale={best[1]:.3f} dx={best[2]} dy={best[3]}')
    # 叠加留证
    w = cv2.warpAffine(dedge0, np.float32([[best[1], 0, best[2]], [0, best[1], best[3]]]), (gw, gh))
    ov2 = rgbf[:gh*int(rgbf.shape[0]/gh)] if False else cv2.resize(rgbf, (gw, gh))
    ov2 = ov2.copy()
    mask = w > (w.max() * 0.25)
    ov2[mask] = (ov2[mask] * 0.35 + np.array([255, 60, 60]) * 0.65).astype(np.uint8)
    Image.fromarray(lab(ov2, f'深度边缘(红)叠RGB 对齐 corr={best[0]:.2f} s={best[1]:.2f}'))

# ---------- ④ 留证图 ----------
sep = np.full((480, 6, 3), 255, np.uint8)
tiles = [lab(vis3, 'raw 深度（原样）'), lab(ov, 'raw 深度 + 无效区(红)')]
Image.fromarray(np.concatenate([tiles[0], sep, tiles[1]], 1)).save(OUT + '/_排查009_原始深度_无效分布.png')

if '640x480' in frames and '1280x800' in frames:
    a = frames['640x480']; b = frames['1280x800']
    a2 = np.array(Image.fromarray(a).resize((b.shape[1], b.shape[0])))
    sep2 = np.full((b.shape[0], 6, 3), 255, np.uint8)
    Image.fromarray(np.concatenate([lab(a2, '640x480 放大到 1280×800'), sep2,
                                    lab(b, '1280x800 原生')], 1)).save(OUT + '/_排查009_RGB双分辨率对比.png')
print('已存 _排查009_原始深度_无效分布.png / _排查009_RGB双分辨率对比.png（+对齐叠加在最后一个 lab 图内）')

# 对齐叠加单独存
if best is not None:
    Image.fromarray(ov2).save(OUT + '/_排查009_对齐叠加.png')
    print('已存 _排查009_对齐叠加.png')

try: link.ir_off()
except Exception: pass
print('排查完成')
