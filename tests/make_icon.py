# -*- coding: utf-8 -*-
"""生成 AstraForge 图标（深度扫描意象：同心弧+传感点）→ assets/icon.ico"""
from pathlib import Path
import os

from PIL import Image, ImageDraw, ImageFont

OUT = str(Path(__file__).resolve().parents[1] / 'assets' / 'icon.ico')
os.makedirs(os.path.dirname(OUT), exist_ok=True)

img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
# 圆角深色底
d.rounded_rectangle([6, 6, 250, 250], radius=52, fill=(22, 22, 30, 255),
                    outline=(0, 212, 255, 180), width=4)
# 深度扫描弧（三层，越内越亮）
cx, cy = 128, 112
for r, w, c in ((84, 11, (0, 140, 200, 220)), (56, 11, (0, 190, 235, 240)),
                (28, 11, (0, 212, 255, 255))):
    d.arc([cx - r, cy - r, cx + r, cy + r], start=205, end=335, fill=c, width=w)
# 传感点
d.ellipse([cx - 9, cy + 2, cx + 9, cy + 20], fill=(232, 233, 238, 255))
# 底部 AF 字标
try:
    font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 58)
except Exception:
    font = ImageFont.load_default()
d.text((128, 208), "AF", font=font, fill=(232, 233, 238, 255), anchor="mm")

img.save(OUT, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print('图标 ✓', OUT)
