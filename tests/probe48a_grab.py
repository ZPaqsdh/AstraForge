# -*- coding: utf-8 -*-
"""probe48a 抓帧存档：实机抓一帧 raw 深度 + raw RGB，存盘供离线分析。"""
from pathlib import Path
import sys, time
import numpy as np
from PIL import Image

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT + '/AstraForge')
from modules.device.module import AstraLink, decode_frame
import cv2

rawD = None; rawR = None
link = AstraLink()
ok, msg = link.connect()
if not ok:
    print('设备连接失败:', (msg or '')[:80]); sys.exit(1)
link.ensure_ready()
t0 = time.time()
while time.time() - t0 < 8:
    f = link.grab_frame(timeout=0.5)
    if f is None:
        continue
    d = decode_frame(f)
    if d is not None and (d > 0).sum() > 5000:
        rawD = d
        break
try:
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    time.sleep(0.4)
    for _ in range(20):
        ok3, fr = cap.read()
        if ok3 and fr is not None:
            rawR = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB); break
        time.sleep(0.12)
    cap.release()
except Exception as e:
    print('RGB 抓取异常:', str(e)[:80])
try: link.ir_off()
except Exception: pass

if rawD is None or rawR is None:
    print('抓帧不全：深度', rawD is not None, '| RGB', rawR is not None); sys.exit(1)

OUT = ROOT + '/问题跟踪'
np.save(OUT + '/_raw48_depth.npy', rawD)
Image.fromarray(rawR).save(OUT + '/_raw48_rgb.png')
print('已存 _raw48_depth.npy', rawD.shape, '| _raw48_rgb.png', rawR.shape)
print('深度有效像素:', int((rawD > 0).sum()))
