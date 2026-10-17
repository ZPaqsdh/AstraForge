# -*- coding: utf-8 -*-
"""preview 模块 — 双画面预览（RGB + 深度伪彩/灰度）。

订阅 device 事件（depth.frame / rgb.frame），事件化渲染（有新帧才画）。
对外 API：create_widget(master) / set_gray / set_disp_range / set_mm_per_shift
"""
import time
import tkinter as tk

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

from core.contracts import ModuleContext
from core.theme import BG, FG, MUTED, CANVAS_BG, LUT, DISP_MAX
from core.theme import render_depth_vis

# 渲染统一走 core（纯 numpy，无 tkinter 依赖；HTTP 壳也用它）
render_preview = render_depth_vis


class PreviewWidget(tk.Frame):
    """双画面预览部件：左 RGB / 右 深度+色标 / 底部悬停行。"""

    def __init__(self, master, bus, settings=None):
        super().__init__(master, bg=BG)
        self.bus = bus
        settings = settings or {}
        self.depth = None                 # 最新深度帧（numpy）
        self.rgb = None                   # 最新 RGB 帧（numpy RGB）
        self.gray = [False]
        self.paused = [False]
        self.disp_range = [0.0, float(DISP_MAX)]
        self.mm_per_shift = [float(settings.get("mm_per_shift", 1.0))]
        self._pending = {"d": None, "r": None}
        self.depth_count = 0
        self.rgb_count = 0
        self._fps_n = 0
        self._fps_t = time.time()
        self.fps = 0.0
        self._photo_d = None
        self._photo_r = None

        body = tk.Frame(self, bg=BG)
        body.pack()
        self.rgb_canvas = tk.Canvas(body, width=W, height=H, bg=CANVAS_BG,
                                    highlightthickness=0)
        self.rgb_canvas.pack(side="left")
        self.depth_canvas = tk.Canvas(body, width=W + 46, height=H, bg=CANVAS_BG,
                                      highlightthickness=0)
        self.depth_canvas.pack(side="left", padx=(10, 0))
        self._build_color_scale()
        self.depth_canvas.bind("<Motion>", self._on_hover)
        self.depth_canvas.bind("<Leave>", lambda e: self.lb_hover.config(text=""))
        self.lb_hover = tk.Label(self, text="", anchor="w", font=("Consolas", 10),
                                 fg=MUTED, bg=BG)
        self.lb_hover.pack(fill="x", padx=6)

        bus.subscribe("depth.frame", self._on_depth)
        bus.subscribe("rgb.frame", self._on_rgb)
        bus.subscribe("setting.disp_range", self._on_disp_range)
        bus.subscribe("calib.changed", self._on_calib)
        self.after(8, self._tick)

    def _on_disp_range(self, rng):
        try:
            self.set_disp_range(rng[0], rng[1])
        except Exception:
            pass

    def _on_calib(self, v):
        try:
            self.set_mm_per_shift(v)
        except Exception:
            pass

    # ---- 事件回调（可能来自采集线程：只做原子赋值）----
    def _on_depth(self, f):
        self._pending["d"] = f

    def _on_rgb(self, f):
        self._pending["r"] = f

    # ---- 主线程渲染循环（事件化：有新帧才画）----
    def _tick(self):
        f = self._pending["d"]
        self._pending["d"] = None
        if f is not None:
            self.depth_count += 1
            self._fps_n += 1
            if not self.paused[0]:
                self.depth = f.data
                self._render_depth()
        f = self._pending["r"]
        self._pending["r"] = None
        if f is not None:
            self.rgb = f.data
            self.rgb_count += 1
            self._render_rgb()
        now = time.time()
        if now - self._fps_t >= 0.5:
            self.fps = self._fps_n / (now - self._fps_t)
            self._fps_t = now
            self._fps_n = 0
        self.after(8, self._tick)

    def _render_depth(self):
        vis = render_preview(self.depth, gray=self.gray[0],
                             dmin=self.disp_range[0], dmax=self.disp_range[1])
        img = Image.fromarray(vis)
        if self._photo_d is None:
            self._photo_d = ImageTk.PhotoImage(img)
            self._img_d = self.depth_canvas.create_image(0, 0, anchor="nw",
                                                         image=self._photo_d)
        else:
            self._photo_d.paste(img)

    def _render_rgb(self):
        try:
            img = Image.fromarray(self.rgb)
            if self._photo_r is None:
                self._photo_r = ImageTk.PhotoImage(img)
                self._img_r = self.rgb_canvas.create_image(0, 0, anchor="nw",
                                                           image=self._photo_r)
            else:
                self._photo_r.paste(img)
        except Exception:
            pass

    def _build_color_scale(self):
        bar_w, bar_h = 30, H
        img = Image.new("RGB", (bar_w, bar_h), (22, 22, 30))
        px = img.load()
        for y in range(bar_h):
            v = int((1.0 - y / (bar_h - 1)) * 255)
            c = LUT[v]
            for x in range(bar_w):
                px[x, y] = (int(c[0]), int(c[1]), int(c[2]))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 11)
        except Exception:
            font = ImageFont.load_default()
        top_m = DISP_MAX / 1000.0
        for m in (0.0, 0.5, 1.0, 1.5, 2.0, top_m):
            y = int((1.0 - (m / top_m)) * (bar_h - 1))
            draw.line([(bar_w - 7, y), (bar_w - 1, y)], fill=(255, 255, 255), width=1)
            txt = f"{m:.1f}m" if m >= 1.0 else f"{int(m * 1000)}mm"
            ty = min(max(y - 7, 0), bar_h - 14)
            draw.text((1, ty), txt, fill=(235, 235, 245), font=font)
        self._photo_scale = ImageTk.PhotoImage(img)
        self.depth_canvas.create_image(W + 10, 0, anchor="nw", image=self._photo_scale)

    def _on_hover(self, e):
        if self.depth is None:
            return
        x, y = int(e.x), int(e.y)
        if not (0 <= x < W and 0 <= y < H):
            return
        v = int(self.depth[y, x])
        txt = (f"指针 ({x},{y}) = {v} shift ≈ {v * self.mm_per_shift[0]:.0f} mm"
               if v > 0 else f"指针 ({x},{y}) = 无效")
        if txt != self.lb_hover.cget("text"):
            self.lb_hover.config(text=txt)

    # ---- 对外 API ----
    def toggle_gray(self):
        self.gray[0] = not self.gray[0]
        return self.gray[0]

    def toggle_pause(self):
        self.paused[0] = not self.paused[0]
        return self.paused[0]

    def set_disp_range(self, lo, hi):
        self.disp_range[0] = float(lo)
        self.disp_range[1] = float(hi)

    def set_mm_per_shift(self, v):
        self.mm_per_shift[0] = float(v)


# ---------------- 模块壳 ----------------
class PreviewModule:
    name = "preview"
    version = "1.0.0"

    def __init__(self):
        self.ctx = None
        self._widget = None

    def setup(self, ctx: ModuleContext):
        self.ctx = ctx
        ctx.log(f"[preview] 就绪 v{self.version}", True)

    def start(self):
        pass

    def stop(self):
        if self._widget is not None:
            try:
                self._widget.destroy()
            except Exception:
                pass
            self._widget = None

    def create_widget(self, master):
        self._widget = PreviewWidget(master, self.ctx.bus, self.ctx.settings)
        return self._widget
