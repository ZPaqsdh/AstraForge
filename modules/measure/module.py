# -*- coding: utf-8 -*-
"""measure 模块 — 深度画布两点 3D 测距。

UI 装配时调用 attach(canvas, get_depth, get_mms) 挂接到 preview 的深度画布；
toggle() 开关模式。使用 core.cloudmath 的相机内参反投影。
"""
import numpy as np

from core.contracts import ModuleContext
from core import cloudmath as cm


class MeasureModule:
    name = "measure"
    version = "1.0.1"

    def __init__(self):
        self.ctx = None
        self.on = False
        self.p1 = None
        self.items = []
        self.canvas = None
        self.get_depth = None
        self.get_mms = None
        self.lb_hint = None

    def setup(self, ctx: ModuleContext):
        self.ctx = ctx
        ctx.log(f"[measure] 就绪 v{self.version}", True)

    def start(self):
        pass

    def stop(self):
        self._clear_items()

    def attach(self, canvas, get_depth, get_mms, lb_hint=None):
        self.canvas = canvas
        self.get_depth = get_depth
        self.get_mms = get_mms
        self.lb_hint = lb_hint
        canvas.bind("<Button-1>", self._click)

    def _hint(self, txt):
        if self.lb_hint is not None:
            try:
                self.lb_hint.config(text=txt)
            except Exception:
                pass

    def _clear_items(self):
        if self.canvas is not None:
            for it in self.items:
                try:
                    self.canvas.delete(it)
                except Exception:
                    pass
        self.items = []
        self.p1 = None

    def toggle(self):
        self.on = not self.on
        if not self.on:
            self._clear_items()
            self._hint("")
        else:
            self._hint("测距模式: 在深度画布点两点测 3D 距离")
        return self.on

    def _click(self, e):
        if not self.on or self.get_depth is None or self.canvas is None:
            return
        depth = self.get_depth()
        if depth is None:
            return
        x, y = int(e.x), int(e.y)
        h, w = depth.shape
        if not (0 <= x < w and 0 <= y < h):
            return
        z = float(depth[y, x]) * self.get_mms()
        if z <= 0:
            self._hint("该点深度无效，重选")
            return
        if self.p1 is None:
            self.p1 = (x, y, z)
            self.items.append(self.canvas.create_oval(
                x - 4, y - 4, x + 4, y + 4, outline="#ff6b6b", width=2))
            self._hint("测量: 已选第一点，点第二点…")
            return
        x0, y0, z0 = self.p1
        cx, cy = cm.cxcy_for_shape(depth.shape)      # 尺寸感知主点（BUG-011）
        P0 = np.array([(x0 - cx) * z0 / cm.FX, (y0 - cy) * z0 / cm.FY, z0])
        P1 = np.array([(x - cx) * z / cm.FX, (y - cy) * z / cm.FY, z])
        dist = float(np.linalg.norm(P1 - P0))
        self.items.append(self.canvas.create_line(x0, y0, x, y,
                                                  fill="#ff6b6b", width=2))
        self.items.append(self.canvas.create_text(
            (x0 + x) // 2, (y0 + y) // 2 - 12, text=f"{dist:.0f} mm",
            fill="#ff6b6b", font=("Consolas", 12, "bold")))
        self._hint(f"测量结果: {dist:.1f} mm（再点开始新测量）")
        self.p1 = None
