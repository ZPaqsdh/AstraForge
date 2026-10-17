#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe33_exe.py — 打包后的 AstraForge.exe 启动验证（双击等效）

验证点：
  ① exe 启动 ② 主窗口出现（像真软件）③ **无控制台/黑窗**（进程名下无 ConsoleWindowClass）
  ④ 截图 ⑤ WM_CLOSE 干净退出
"""
from pathlib import Path
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

EXE = str(Path(__file__).resolve().parents[2] / '发行' / 'AstraForge' / 'AstraForge.exe')
OUT = str(Path(__file__).resolve().parents[1] / '_tmp' / '_astraforge_exe.png')

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


def enum_windows(pid=None):
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(h, l):
        if user32.IsWindowVisible(h):
            n = user32.GetWindowTextLengthW(h)
            b = ctypes.create_unicode_buffer(max(n + 1, 2))
            user32.GetWindowTextW(h, b, n + 1)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, cls, 256)
            wp = wt.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(wp))
            if pid is None or wp.value == pid:
                found.append((h, b.value, cls.value, wp.value))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def main():
    if not os.path.exists(EXE):
        sys.exit(f'不存在: {EXE}')
    print('启动 exe ...', flush=True)
    proc = subprocess.Popen([EXE], cwd=os.path.dirname(EXE))

    hwnd = None
    t0 = time.time()
    while time.time() - t0 < 30:
        ws = enum_windows(proc.pid)
        main_ws = [w for w in ws if 'AstraForge' in w[1]]
        if main_ws:
            hwnd = main_ws[0][0]
            break
        if proc.poll() is not None:
            sys.exit(f'exe 提前退出 code={proc.returncode}')
        time.sleep(0.5)
    if hwnd is None:
        proc.terminate()
        sys.exit('30 秒未出现主窗口')
    print(f'① 主窗口出现（{time.time()-t0:.1f}s）', flush=True)

    # ② 黑窗检查：该进程的所有可见窗口
    time.sleep(3)
    ws = enum_windows(proc.pid)
    cons = [w for w in ws if 'ConsoleWindowClass' in w[2] or 'CASCADIA' in w[2]]
    print(f'② 进程可见窗口: {[(w[1][:30], w[2]) for w in ws]}', flush=True)
    print(f'   控制台黑窗: {"无 ✓" if not cons else f"发现 {len(cons)} 个 ✗"}', flush=True)

    # ③ 截图
    time.sleep(4)
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 2)

    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG),
                    ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]
    bi = BMIH(); bi.biSize = ctypes.sizeof(BMIH)
    bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount = w, -h, 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    from PIL import Image
    img = Image.frombuffer('RGB', (w, h), buf, 'raw', 'BGRX', 0, 1)
    img.save(OUT)
    print(f'③ 截图: {OUT} ({w}x{h})', flush=True)
    gdi32.DeleteObject(bmp); gdi32.DeleteDC(mdc); user32.ReleaseDC(hwnd, hdc)

    # ④ 关闭
    user32.PostMessageW(hwnd, 0x0010, 0, 0)
    t0 = time.time()
    while time.time() - t0 < 10 and proc.poll() is None:
        time.sleep(0.3)
    ok = proc.poll() is not None
    if not ok:
        proc.terminate()
    print(f'④ 退出: {"干净 ✓" if ok else "强制终止"}', flush=True)
    print('EXE SMOKE OK' if (ok and not cons) else 'EXE SMOKE FAIL', flush=True)


if __name__ == '__main__':
    main()
