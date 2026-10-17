# -*- coding: utf-8 -*-
"""calib 模块 — S2D 深度标定（shift→mm）核心。

职责：标定值读写（data/标定.json）+ 热更新广播（calib.changed）。
对话框 UI 由 UI 层（M6）经 open_dialog(master) 调用（本模块提供纯逻辑 + 计算）。
"""
import json
import os

from core.contracts import ModuleContext


class CalibModule:
    name = "calib"
    version = "1.0.0"

    def __init__(self):
        self.ctx = None
        self.mm_per_shift = 1.0

    def setup(self, ctx: ModuleContext):
        self.ctx = ctx
        self.mm_per_shift = float(ctx.settings.get("mm_per_shift", 1.0))
        ctx.log(f"[calib] 就绪 v{self.version}（当前 {self.mm_per_shift:.4f} mm/shift）", True)

    def start(self):
        pass

    def stop(self):
        pass

    # ---- API ----
    def get(self):
        return self.mm_per_shift

    def compute(self, known_mm, measured_shift):
        """已知距离 ÷ 实测 shift → mm/shift。"""
        if measured_shift <= 0:
            return None
        return float(known_mm) / float(measured_shift)

    def _calib_path(self):
        return self.ctx.root_dir / "data" / "标定.json"

    def set_and_save(self, mm_per_shift):
        """写盘 + 更新全局 settings + 广播（preview/viewer3d/recorder 热更新）。"""
        import time
        v = float(mm_per_shift)
        if not (0.1 < v < 10):
            return False
        self.mm_per_shift = v
        self.ctx.settings["mm_per_shift"] = v
        try:
            p = self._calib_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({
                "mm_per_shift": round(v, 4),
                "note": "S2D 标定: 真实距离mm = 深度shift × mm_per_shift",
                "date": time.strftime("%Y-%m-%d %H:%M:%S")},
                ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self.ctx.log(f"[calib] 保存失败: {e}", False)
            return False
        self.ctx.bus.publish("calib.changed", v)
        self.ctx.log(f"[calib] 已更新 {v:.4f} mm/shift", True)
        return True


    # ---- 标定对话框 ----
    def open_dialog(self, master, get_depth):
        import tkinter as tk
        import numpy as np
        from core.theme import BG, FG, ACCENT, OK, WARN, ERR, BTN

        win = tk.Toplevel(master)
        win.title("深度标定（shift → mm）")
        win.configure(bg=BG)
        win.geometry("400x330")

        tk.Label(win, text="把已知尺寸的平面（白纸/书本）正对镜头放好，\n"
                           "用尺子量出相机到它的距离，填入后采样：",
                 fg=FG, bg=BG, font=("Microsoft YaHei", 9),
                 justify="left").pack(pady=(12, 6), padx=10)

        frm = tk.Frame(win, bg=BG); frm.pack(fill="x", padx=14, pady=2)
        tk.Label(frm, text="已知距离 (mm):", fg=FG, bg=BG, width=14,
                 anchor="w").pack(side="left")
        var_d = tk.StringVar(value="500")
        tk.Entry(frm, textvariable=var_d, width=10).pack(side="left", padx=4)

        frm2 = tk.Frame(win, bg=BG); frm2.pack(fill="x", padx=14, pady=2)
        tk.Label(frm2, text="采样区边长 (px):", fg=FG, bg=BG, width=14,
                 anchor="w").pack(side="left")
        var_roi = tk.StringVar(value="40")
        tk.Entry(frm2, textvariable=var_roi, width=10).pack(side="left", padx=4)

        lb_stat = tk.Label(win, text=f"当前标定: {self.mm_per_shift:.4f} mm/shift",
                           fg=ACCENT, bg=BG, font=("Consolas", 10))
        lb_stat.pack(pady=10)
        state = {"k": None}

        def sample():
            depth = get_depth()
            if depth is None:
                lb_stat.config(text="还没有画面，无法采样", fg=WARN); return
            try:
                dist = float(var_d.get()); roi = int(var_roi.get())
            except ValueError:
                lb_stat.config(text="输入不是数字", fg=ERR); return
            r = max(4, min(roi, 200))
            c = depth[depth.shape[0] // 2 - r:depth.shape[0] // 2 + r,
                      depth.shape[1] // 2 - r:depth.shape[1] // 2 + r]
            v = c[c > 0]
            if len(v) < 50:
                lb_stat.config(text="采样区有效点太少（中心无数据？换方向/距离）",
                               fg=WARN); return
            med = float(np.median(v))
            k = self.compute(dist, med)
            state["k"] = k
            lb_stat.config(text=f"采样: {2*r}x{2*r} 区，中位深度 {med:.1f} shift\n"
                                f"→ mm/shift = {k:.4f}（点“保存标定”生效）", fg=OK)

        def save():
            if not state["k"]:
                lb_stat.config(text="先采样再保存", fg=WARN); return
            if self.set_and_save(state["k"]):
                lb_stat.config(text=f"✓ 已保存并生效: {state['k']:.4f} mm/shift", fg=OK)
            else:
                lb_stat.config(text="保存失败", fg=ERR)

        bf = tk.Frame(win, bg=BG); bf.pack(pady=8)
        for txt, cmd, fg in (("采样", sample, FG), ("保存标定", save, OK),
                             ("关闭", win.destroy, FG)):
            tk.Button(bf, text=txt, command=cmd, bg=BTN, fg=fg, relief="flat",
                      bd=0, padx=10, pady=3, cursor="hand2",
                      font=("Microsoft YaHei", 9)).pack(side="left", padx=6)
