# -*- coding: utf-8 -*-
"""实机实验：直连相机抓一帧原始数据（不做任何翻转）→ 判断键盘方向
同时抓 UVC RGB 原始帧，输出：
  ① 深度原始帧（伪彩）
  ② RGB 原始帧
  ③ 两者各带镜像对照版
判据：用户实物基准 —— 键盘在左下。
"""
from pathlib import Path
import sys, time
import numpy as np
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.device.module import AstraLink, decode_frame

print('连接设备…')
link = AstraLink()
ok, msg = link.connect()
print('连接:', ok, msg[:80] if msg else '')
if not ok:
    sys.exit('设备连接失败')
ok2, msgs = link.ensure_ready()
print('就绪:', ok2)
for m in msgs[-3:]:
    print('  ', m[:90])

# 抓一帧深度（不翻转）
d_raw = None
t0 = time.time()
while time.time() - t0 < 6:
    f = link.grab_frame(timeout=0.5)
    if f is None:
        continue
    d = decode_frame(f)
    if d is not None and (d > 0).sum() > 1000:
        d_raw = d
        break
print('深度原始帧:', 'OK ' + str(d_raw.shape) if d_raw is not None else '失败')

# UVC RGB 原始帧（不翻转）
rgb_raw = None
try:
    import cv2
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    for _ in range(10):
        ok3, frame = cap.read()
        if ok3 and frame is not None:
            rgb_raw = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            break
        time.sleep(0.15)
    cap.release()
    print('RGB 原始帧:', 'OK ' + str(rgb_raw.shape) if rgb_raw is not None else '失败')
except Exception as e:
    print('RGB 抓取异常:', str(e)[:80])

# 关红外 + 释放设备（设备纪律）
try:
    link.ir_off()
except Exception as e:
    print('ir_off:', str(e)[:60])

if d_raw is None and rgb_raw is None:
    sys.exit('无数据')

try:
    F = ImageFont.truetype(r'C:/Windows/Fonts/msyh.ttc', 20)
except Exception:
    F = ImageFont.load_default()
def tag(img, text):
    im = Image.fromarray(np.ascontiguousarray(img)); dr = ImageDraw.Draw(im)
    dr.rectangle([0, 0, len(text) * 20 + 16, 32], fill=(0, 0, 0))
    dr.text((7, 4), text, fill=(255, 255, 90), font=F)
    return np.array(im)
def midline(a):
    a = a.copy(); a[:, a.shape[1] // 2 - 2:a.shape[1] // 2 + 2] = [255, 40, 40]; return a

tiles = []
if d_raw is not None:
    dd = d_raw.astype(np.float32).copy(); dd[dd <= 0] = np.nan
    lo, hi = [float(x) for x in np.nanpercentile(dd, [2, 98])]
    v = np.nan_to_num(np.clip((dd - lo) / (hi - lo + 1e-6), 0, 1), nan=0)
    di = np.stack([255*v, 60+120*(1-v), 255*(1-v)], -1).astype(np.uint8)
    di[d_raw <= 0] = (18, 18, 26)
    tiles.append(('深度原始', midline(di)))
    tiles.append(('深度镜像', midline(di[:, ::-1])))
if rgb_raw is not None:
    tiles.append(('RGB原始', midline(rgb_raw)))
    tiles.append(('RGB镜像', midline(rgb_raw[:, ::-1])))

sep = np.full((tiles[0][1].shape[0], 10, 3), 60, np.uint8)
row = np.concatenate([np.concatenate([tag(t[1], t[0]), sep], 1) for t in tiles], 1)
Image.fromarray(row).save(str(Path(__file__).resolve().parents[2] / '问题跟踪' / '_实机_原始帧方向判读.png'))
print('判读图已存: 问题跟踪/_实机_原始帧方向判读.png')
print('请核对: 键盘实际在左下 → 找哪张图里键盘在左下（4 张中必有一张对）')

# 数值：RGB 底部彩灯左右
if rgb_raw is not None:
    i16 = rgb_raw.astype(np.int16)
    sat = (i16.max(2) - i16.min(2) > 60) & (i16.max(2) > 110)
    bt = sat[int(rgb_raw.shape[0]*0.66):]
    W = rgb_raw.shape[1]
    print(f'RGB原始 底部彩灯: 左 {int(bt[:, :W//2].sum())} vs 右 {int(bt[:, W//2:].sum())}')
    bt2 = sat[:, ::-1][int(rgb_raw.shape[0]*0.66):]
    print(f'RGB镜像 底部彩灯: 左 {int(bt2[:, :W//2].sum())} vs 右 {int(bt2[:, W//2:].sum())}')