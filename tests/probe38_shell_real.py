# -*- coding: utf-8 -*-
"""probe38：shell 真管线整机验证（Edge app 窗口 + 前端自报铁证）。

沙箱网络隔离时外部连不上 shell 的 127.0.0.1——改看两条铁证：
  ① 前端自报 _front_report.json（页面活了 + DOM/颜色/canvas/img 统计）
  ② BitBlt 桌面抓屏（真实视觉，WebView 类窗口 PrintWindow 不可靠故用 BitBlt）
"""
import sys
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import time
from pathlib import Path

PY = sys.executable
ROOT = Path(str(Path(__file__).resolve().parents[1]))
SHOT = ROOT / '_tmp' / '_p3_shell_real.png'

p = subprocess.Popen([PY, 'shell.py', '--backend', 'edge', '--profile', 'edge_p38'],
                     cwd=str(ROOT),
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     text=True, errors='replace')
print('shell PID', p.pid, '等 14 秒（装配+启动+Edge 加载）...', flush=True)
time.sleep(14)

# ① 前端自报
rp = ROOT / '_front_report.json'
print('=== 前端自报 ===')
print(rp.read_text(encoding='utf-8') if rp.exists() else '（未收到）')

# ② 窗口枚举 + BitBlt 抓屏
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
found = []
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)


def cb(h, l):
    if user32.IsWindowVisible(h):
        n = user32.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(max(n + 1, 2))
        user32.GetWindowTextW(h, b, n + 1)
        if 'AstraForge' in b.value or '127.0.0.1' in b.value:
            r = wt.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            if r.right - r.left > 500:
                found.append((h, b.value, r))
    return True


user32.EnumWindows(WNDENUMPROC(cb), 0)
print('窗口:', [(f[1], f[2].right - f[2].left) for f in found])

if found:
    hwnd, title, rect = found[0]
    user32.SetForegroundWindow(hwnd)
    time.sleep(2.5)
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, hh = rect.right - rect.left, rect.bottom - rect.top
    src = user32.GetWindowDC(0)
    mdc = gdi32.CreateCompatibleDC(src)
    bmp = gdi32.CreateCompatibleBitmap(src, w, hh)
    gdi32.SelectObject(mdc, bmp)
    gdi32.BitBlt(mdc, 0, 0, w, hh, src, rect.left, rect.top, 0x00CC0020)

    class B(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                    ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

    bi = B()
    bi.biSize = ctypes.sizeof(B)
    bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount = w, -hh, 1, 32
    buf = ctypes.create_string_buffer(w * hh * 4)
    gdi32.GetDIBits(mdc, bmp, 0, hh, buf, ctypes.byref(bi), 0)
    from PIL import Image
    img = Image.frombuffer('RGB', (w, hh), buf, 'raw', 'BGRX', 0, 1)
    SHOT.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(SHOT))
    print(f'截图 ✓ {SHOT} ({w}x{hh})')
    # 像素抽查：侧栏（浅色主题应接近白/浅灰）、画布区（深度帧应有颜色）
    px_side = img.getpixel((60, 300))
    px_canvas = img.getpixel((700, 400))
    print(f'侧栏像素: {px_side} | 画布区像素: {px_canvas}')
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(0, src)

# ③ 收尾（关红外由 shell 的 proc.wait → bridge.shutdown 完成）
print('\n=== 关闭 shell（触发收尾关红外）===')
p.terminate()
time.sleep(2)
out = p.stdout.read() if p.stdout else ''
subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True)
subprocess.run(['taskkill', '/IM', 'msedge.exe', '/F'], capture_output=True)
print('shell 输出尾部:')
print(out[-800:])
