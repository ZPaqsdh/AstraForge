#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe30_app.py — AstraForge 整机启动验证（新架构首次全链路）
启动 main.py（真设备）→ 找主窗口 → 数秒后截图 → WM_CLOSE 关闭。
"""
import subprocess
import time
import sys
import ctypes
import ctypes.wintypes as wt
from pathlib import Path

PY = sys.executable
ROOT = str(Path(__file__).resolve().parents[1])
OUT = str(Path(__file__).resolve().parents[1] / '_tmp' / '_astraforge_main.png')

print('launching AstraForge main.py ...', flush=True)
proc = subprocess.Popen([PY, 'main.py'], cwd=ROOT,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
hwnd = None
t0 = time.time()
while time.time() - t0 < 25:
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, l):
        if user32.IsWindowVisible(h):
            n = user32.GetWindowTextLengthW(h)
            if n:
                b = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(h, b, n + 1)
                if 'AstraForge' in b.value:
                    found.append(h)
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    if found:
        hwnd = found[0]
        break
    if proc.poll() is not None:
        out = proc.communicate()[0].decode('utf-8', 'replace')
        print('进程提前退出，输出:\n', out[-2000:], flush=True)
        sys.exit(2)
    time.sleep(0.5)

if hwnd is None:
    print('25 秒未找到 AstraForge 主窗口', flush=True)
    proc.terminate()
    sys.exit(3)
print(f'主窗口出现（{time.time()-t0:.1f}s）', flush=True)

time.sleep(8)   # 等设备开流+画面稳定
rect = wt.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
w, h = rect.right - rect.left, rect.bottom - rect.top
hdc = user32.GetWindowDC(hwnd)
mdc = gdi32.CreateCompatibleDC(hdc)
bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
gdi32.SelectObject(mdc, bmp)
user32.PrintWindow(hwnd, mdc, 2)
class BMIH(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]
bi = BMIH(); bi.biSize = ctypes.sizeof(BMIH)
bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount = w, -h, 1, 32
buf = ctypes.create_string_buffer(w * h * 4)
gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
from PIL import Image
img = Image.frombuffer('RGB', (w, h), buf, 'raw', 'BGRX', 0, 1)
img.save(OUT)
print(f'截图: {OUT} ({w}x{h})', flush=True)
gdi32.DeleteObject(bmp); gdi32.DeleteDC(mdc); user32.ReleaseDC(hwnd, hdc)

user32.PostMessageW(hwnd, 0x0010, 0, 0)
t0 = time.time()
while time.time() - t0 < 8:
    if proc.poll() is not None:
        break
    time.sleep(0.3)
print('退出状态:', '干净' if proc.poll() is not None else '仍在运行(WS_CLOSE后)', flush=True)
print('APP SMOKE OK', flush=True)
