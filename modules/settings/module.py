# -*- coding: utf-8 -*-
"""settings 模块 — 显示与设备设置（事件化下发）。

职责：维护显示范围 / RGB 曝光 / RGB 分辨率的状态，变更时广播：
    setting.disp_range -> [min, max]（preview 订阅）
    setting.exposure   -> None(自动) 或数值（device 订阅）
    setting.resolution -> None(默认) 或 (w, h)（device 订阅）
对话框 open_dialog(master) 由 UI 调用。
"""
import tkinter as tk

from core.contracts import ModuleContext
from core.theme import BG, FG, MUTED, ACCENT, BTN, BTN_HOVER


class SettingsModule:
    name = "settings"
    version = "1.1.0"

    def __init__(self):
        self.ctx = None
        self.disp_range = [0.0, 2500.0]
        self.exposure = [None]
        self.resolution = [None]

    def setup(self, ctx: ModuleContext):
        self.ctx = ctx
        # 启动还原（data/设置.json）：显示范围 / RGB 曝光 / RGB 分辨率
        try:
            from core import appsettings
            d = appsettings.load(ctx.data_dir)
            dr = d.get("disp_range")
            if (isinstance(dr, (list, tuple)) and len(dr) == 2
                    and float(dr[0]) < float(dr[1])):
                self.disp_range = [float(dr[0]), float(dr[1])]
            exp = d.get("exposure")
            if exp is None or isinstance(exp, (int, float)):
                self.exposure = [None if exp is None else float(exp)]
            res = d.get("resolution")
            if res is None or (isinstance(res, (list, tuple)) and len(res) == 2):
                self.resolution = [None if res is None else [int(res[0]), int(res[1])]]
        except Exception:
            pass
        ctx.log(f"[settings] 就绪 v{self.version}", True)

    def start(self):
        # 开机重播已还原的设置（此时全模块已订阅，设备/预览随之生效）
        for topic, val in (("setting.disp_range", list(self.disp_range)),
                           ("setting.exposure", self.exposure[0]),
                           ("setting.resolution", self.resolution[0])):
            try:
                self.ctx.bus.publish(topic, val)
            except Exception:
                pass

    def stop(self):
        pass

    # ---- API ----
    def _persist(self, **kv):
        try:
            from core import appsettings
            appsettings.update(self.ctx.data_dir, **kv)
        except Exception:
            pass

    def set_disp_range(self, lo, hi):
        self.disp_range[0], self.disp_range[1] = float(lo), float(hi)
        self._persist(disp_range=list(self.disp_range))
        self.ctx.bus.publish("setting.disp_range", list(self.disp_range))

    def set_exposure(self, v):
        self.exposure[0] = v
        self._persist(exposure=(None if v is None else float(v)))
        self.ctx.bus.publish("setting.exposure", v)

    def set_resolution(self, rv):
        self.resolution[0] = rv
        self._persist(resolution=(None if rv is None else [int(rv[0]), int(rv[1])]))
        self.ctx.bus.publish("setting.resolution", rv)

    # ---- 对话框 ----
    def open_dialog(self, master):
        win = tk.Toplevel(master)
        win.title("显示与设备设置")
        win.configure(bg=BG)
        win.geometry("420x330")

        def flat_btn(text, cmd):
            b = tk.Button(win, text=text, command=cmd, bg=BTN, fg=FG,
                          activebackground=BTN_HOVER, activeforeground="white",
                          relief="flat", bd=0, padx=8, pady=3, cursor="hand2",
                          font=("Microsoft YaHei", 9))
            b.pack(pady=3)
            return b

        tk.Label(win, text="深度显示范围（shift）", fg=ACCENT, bg=BG,
                 font=("Microsoft YaHei", 10, "bold")).pack(pady=(12, 2))
        frm = tk.Frame(win, bg=BG); frm.pack(fill="x", padx=16)
        lb_lo = tk.Label(frm, text=f"{self.disp_range[0]:.0f}", fg=FG, bg=BG, width=6)
        lb_lo.pack(side="left")
        sc_lo = tk.Scale(frm, from_=0, to=2400, orient="horizontal", length=230,
                         command=lambda v: self._lo(float(v), lb_lo))
        sc_lo.set(self.disp_range[0]); sc_lo.pack(side="left")
        frm2 = tk.Frame(win, bg=BG); frm2.pack(fill="x", padx=16)
        lb_hi = tk.Label(frm2, text=f"{self.disp_range[1]:.0f}", fg=FG, bg=BG, width=6)
        lb_hi.pack(side="left")
        sc_hi = tk.Scale(frm2, from_=200, to=6000, orient="horizontal", length=230,
                         command=lambda v: self._hi(float(v), lb_hi))
        sc_hi.set(self.disp_range[1]); sc_hi.pack(side="left")

        def reset_range():
            self.set_disp_range(0, 2500)
            sc_lo.set(0); sc_hi.set(2500)
            lb_lo.config(text="0"); lb_hi.config(text="2500")
        flat_btn("重置范围 (0–2500)", reset_range)

        tk.Label(win, text="RGB 曝光（负值手动；设备不支持则无效）", fg=ACCENT, bg=BG,
                 font=("Microsoft YaHei", 10, "bold")).pack(pady=(12, 2))
        lb_exp = tk.Label(win, text="当前: 自动" if self.exposure[0] is None
                          else f"当前: {self.exposure[0]:.0f}", fg=FG, bg=BG,
                          font=("Consolas", 10))
        lb_exp.pack()
        var_auto = tk.BooleanVar(value=self.exposure[0] is None)

        def apply_exp(v):
            self.set_exposure(None if var_auto.get() else float(v))
            lb_exp.config(text="当前: 自动" if var_auto.get() else f"当前: {float(v):.0f}")
        sc_exp = tk.Scale(win, from_=-10, to=0, orient="horizontal", length=260,
                          command=apply_exp)
        if self.exposure[0] is not None:
            sc_exp.set(self.exposure[0])
        sc_exp.pack()
        tk.Checkbutton(win, text="自动曝光", variable=var_auto, bg=BG, fg=FG,
                       selectcolor=BG, activebackground=BG, activeforeground=FG,
                       command=lambda: apply_exp(sc_exp.get())).pack()

        tk.Label(win, text="RGB 分辨率（切换后自动重连）", fg=ACCENT, bg=BG,
                 font=("Microsoft YaHei", 10, "bold")).pack(pady=(10, 2))
        var_res = tk.StringVar(value="默认(640x480)")
        def set_res(v):
            self.set_resolution(None if "默认" in v else
                                ((1280, 800) if "1280" in v else (640, 480)))
        om = tk.OptionMenu(win, var_res, "默认(640x480)", "1280x800", "640x480",
                           command=set_res)
        om.configure(bg=BTN, fg=FG, relief="flat", activebackground=BTN_HOVER,
                     highlightthickness=0)
        om.pack(pady=2)

    def _lo(self, v, lb):
        if v < self.disp_range[1] - 50:
            self.set_disp_range(v, self.disp_range[1])
        lb.config(text=f"{self.disp_range[0]:.0f}")

    def _hi(self, v, lb):
        if v > self.disp_range[0] + 50:
            self.set_disp_range(self.disp_range[0], v)
        lb.config(text=f"{self.disp_range[1]:.0f}")
