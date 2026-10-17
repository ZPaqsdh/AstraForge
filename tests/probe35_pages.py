#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe35_pages.py — P1 路由验证：逐页起壳 + BitBlt 截图
用法：python probe35_pages.py capture turntable about ...
"""
import sys
import subprocess, time, ctypes, ctypes.wintypes as wt, sys
from pathlib import Path

PY = sys.executable
ROOT = str(Path(__file__).resolve().parents[1])
OUT = str(Path(__file__).resolve().parents[1] / '_tmp' / 'pages')
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


def shot(tag, hash_frag):
    p = subprocess.Popen([PY, 'shell.py', '--backend', 'edge', '--hash', hash_frag],
                         cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    time.sleep(11)
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, l):
        if user32.IsWindowVisible(h):
            n = user32.GetWindowTextLengthW(h)
            b = ctypes.create_unicode_buffer(max(n + 1, 2))
            user32.GetWindowTextW(h, b, n + 1)
            if 'AstraForge' in b.value:
                r = wt.RECT(); user32.GetWindowRect(h, ctypes.byref(r))
                if r.right - r.left > 500:
                    found.append((h, r))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    ok = False
    if found:
        hwnd, rect = found[0]
        user32.SetForegroundWindow(hwnd); time.sleep(2)
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, hh = rect.right - rect.left, rect.bottom - rect.top
        src = user32.GetWindowDC(0); mdc = gdi32.CreateCompatibleDC(src)
        bmp = gdi32.CreateCompatibleBitmap(src, w, hh); gdi32.SelectObject(mdc, bmp)
        gdi32.BitBlt(mdc, 0, 0, w, hh, src, rect.left, rect.top, 0x00CC0020)
        class B(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                        ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                        ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]
        bi = B(); bi.biSize = ctypes.sizeof(B)
        bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount = w, -hh, 1, 32
        buf = ctypes.create_string_buffer(w * hh * 4)
        gdi32.GetDIBits(mdc, bmp, 0, hh, buf, ctypes.byref(bi), 0)
        from PIL import Image
        img = Image.frombuffer('RGB', (w, hh), buf, 'raw', 'BGRX', 0, 1)
        img.save(rf'{OUT}/_p1_{tag}.png')
        print(f'[ok] {tag} → _p1_{tag}.png ({w}x{hh})', flush=True)
        ok = True
        gdi32.DeleteObject(bmp); gdi32.DeleteDC(mdc); user32.ReleaseDC(0, src)
    else:
        print(f'[fail] {tag}: 窗口未找到', flush=True)
    p.terminate(); time.sleep(1)
    subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True)
    subprocess.run(['taskkill', '/IM', 'msedge.exe', '/F'], capture_output=True)
    return ok


if __name__ == '__main__':
    pages = sys.argv[1:] or ['capture', 'turntable', 'about']
    for h in pages:
        shot(h, h)
        time.sleep(1)
    print('DONE', flush=True)
