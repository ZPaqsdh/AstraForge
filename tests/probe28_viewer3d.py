#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe28_viewer3d.py — viewer3d 模块验证（M3）
经 pipeline 外置加载 viewer3d 模块 → open() 开 3D 工作站 →
合成"手持转动圆柱"实时/记录/导出全链路 + PrintWindow 截图。
"""
import sys, time
import numpy as np
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.pipeline import Pipeline
from core.events import EventBus
from core.contracts import ModuleContext
from core import cloudmath as F

CAM_DIST = 500.0
OUT = str(ROOT / '_tmp' / 'probe28')


def synth_cylinder():
    th = np.linspace(0, 2 * np.pi, 720, endpoint=False)
    ys = np.linspace(-100, 100, 61)
    pts = []
    for y in ys:
        r = np.full_like(th, 60.0)
        d = np.minimum(np.abs(th - np.pi / 2), 2 * np.pi - np.abs(th - np.pi / 2))
        bump = 15.0 * np.exp(-((d / 0.35) ** 2)) * np.exp(-((y - 40) / 40.0) ** 2)
        pts.append(np.stack([r * np.cos(th), np.full_like(th, y),
                             (r + bump) * np.sin(th)], axis=1))
    return np.concatenate(pts)


def main():
    model = synth_cylinder()
    print(f'合成圆柱 {len(model)} 点', flush=True)
    state = {"angle": 0.0, "frames": 0}

    def get_points():
        state["angle"] += 2.0
        state["frames"] += 1
        a = np.deg2rad(state["angle"])
        c, s = np.cos(a), np.sin(a)
        x = model[:, 0] * c + model[:, 2] * s
        z = -model[:, 0] * s + model[:, 2] * c
        P = np.stack([x, model[:, 1], z + CAM_DIST], axis=1)
        return P + np.random.default_rng(state["frames"]).normal(0, 0.5, P.shape)

    # ---- 经 pipeline 加载 viewer3d 模块（模块化路径）----
    bus = EventBus()
    pipe = Pipeline(ROOT, bus)
    pipe.load_all_modules()
    print(f'① 已加载模块: {list(pipe.modules)}', flush=True)

    root = tk.Tk()
    root.withdraw()
    ctx = ModuleContext(bus=bus, device=None, settings={},
                        log=lambda m, ok: print('  log:', m),
                        data_dir=ROOT / 'data', root_dir=ROOT, ui_root=root)
    pipe.setup_all(ctx)
    pipe.start_all()

    v3d = pipe.get('viewer3d')
    assert v3d is not None, 'viewer3d 模块未加载'
    win = v3d.open(get_points, title='3D 工作站模块测试')
    print('② 模块 open() 开窗 OK', flush=True)

    # 实时 2s
    t0 = time.time()
    while time.time() - t0 < 2.0:
        root.update(); time.sleep(0.02)
    print(f'③ 实时渲染: {win.lb_stat.cget("text")}', flush=True)

    # 记录 6s + 卡顿量化
    win._toggle_rec()
    lags = []
    t0 = time.time()
    while time.time() - t0 < 6.0:
        t1 = time.time(); root.update(); lags.append(time.time() - t1)
        time.sleep(0.02)
    win._toggle_rec()
    lags = np.array(lags) * 1000
    n = len(win.model)
    r = np.sqrt(win.model[:, 0] ** 2 + (win.model[:, 2] - CAM_DIST) ** 2)
    print(f'④ 记录: 累积 {n} 点, 半径中位 {np.median(r):.1f} (期望60), '
          f'跟踪 {win.track_q:.2f}', flush=True)
    print(f'   卡顿: 主线程最大 {lags.max():.0f}ms / 平均 {lags.mean():.1f}ms / '
          f'>200ms {int((lags > 200).sum())} 次', flush=True)

    # 导出读回
    out = str(Path(OUT) / '_v3d_module_export.ply')
    F.save_ply(out, win.model[:, :3])
    back = F.load_ply(out)
    print(f'⑤ 导出读回: {len(back)}/{len(win.model)} '
          f'{"一致 ✓" if len(back) == len(win.model) else "不一致 ✗"}', flush=True)

    # 截图
    time.sleep(0.3)
    import ctypes, ctypes.wintypes as wt
    from PIL import Image
    user32 = ctypes.windll.user32; gdi32 = ctypes.windll.gdi32
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, l):
        n = user32.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, b, n + 1)
            if '3D 工作站模块测试' in b.value:
                found.append(h)
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    if found:
        hwnd = found[0]
        rect = wt.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        hdc = user32.GetWindowDC(hwnd); mdc = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, w, h); gdi32.SelectObject(mdc, bmp)
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
        img = Image.frombuffer('RGB', (w, h), buf, 'raw', 'BGRX', 0, 1)
        png = str(Path(OUT) / '_v3d_module_station.png')
        img.save(png)
        print(f'⑥ 截图: {png}', flush=True)
        gdi32.DeleteObject(bmp); gdi32.DeleteDC(mdc); user32.ReleaseDC(hwnd, hdc)

    pipe.stop_all()
    root.destroy()
    print('VIEWER3D MODULE OK', flush=True)


if __name__ == '__main__':
    main()
