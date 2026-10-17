# -*- coding: utf-8 -*-
"""AstraForge 主窗口（v0.1 最小可用版：双画面 + 设备状态 + 3D 工作站入口）。

线程安全约定：log()/状态回调均可能来自采集线程——只写内存缓存，
真正的 tkinter 标签更新一律在 refresh_tick（主线程 500ms 节拍）里做。
"""
import collections
import time
import tkinter as tk

from core.theme import (BG, PANEL, FG, MUTED, ACCENT, OK, WARN, ERR,
                        BTN, BTN_HOVER)


class MainWindow(tk.Tk):
    def __init__(self, pipe):
        super().__init__()
        self.pipe = pipe
        self.title("AstraForge 星铸 · 深度扫描工作台")
        self.configure(bg=BG)
        self.geometry("1680x860")
        self._dev_status = "设备: 启动中…"
        self._rgb_status = "RGB: --"
        self._log_lines = collections.deque(maxlen=40)
        self._preview = None
        self._last_log = ""

        # ---- 顶栏 ----
        top = tk.Frame(self, bg=PANEL)
        top.pack(fill="x")
        tk.Label(top, text="AstraForge", font=("Microsoft YaHei", 15, "bold"),
                 fg=ACCENT, bg=PANEL).pack(side="left", padx=12, pady=6)
        tk.Label(top, text="星铸", font=("Microsoft YaHei", 10),
                 fg=MUTED, bg=PANEL).pack(side="left")
        self.lb_dev = tk.Label(top, text="设备: 启动中…", fg=MUTED, bg=PANEL,
                               font=("Microsoft YaHei", 10))
        self.lb_dev.pack(side="left", padx=14)
        self.lb_rgb = tk.Label(top, text="RGB: --", fg=MUTED, bg=PANEL,
                               font=("Microsoft YaHei", 10))
        self.lb_rgb.pack(side="left", padx=6)
        self.lb_fps = tk.Label(top, text="", fg=MUTED, bg=PANEL,
                               font=("Consolas", 10))
        self.lb_fps.pack(side="right", padx=12)

        # ---- 主区 ----
        self.main = tk.Frame(self, bg=BG)
        self.main.pack(fill="both", expand=True, padx=8, pady=6)

        # ---- 右栏（先建，preview 后填左侧）----
        self.side = tk.Frame(self.main, bg=BG)
        self.side.pack(side="right", fill="y", padx=(10, 0))
        self.lb_info = tk.Label(self.side, text="--", justify="left", anchor="nw",
                                font=("Consolas", 11), fg=FG, bg=BG)
        self.lb_info.pack(fill="x")

        def flat_btn(text, cmd):
            b = tk.Button(self.side, text=text, command=cmd, bg=BTN, fg="#c8cad4",
                          activebackground=BTN_HOVER, activeforeground="white",
                          relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
                          font=("Microsoft YaHei", 10), anchor="w")
            b.pack(fill="x", pady=2)
            b.bind("<Enter>", lambda e: b.config(bg=BTN_HOVER))
            b.bind("<Leave>", lambda e: b.config(bg=BTN))
            return b

        def group(title):
            tk.Label(self.side, text=f"\n{title}", fg=MUTED, bg=BG, anchor="w",
                     font=("Microsoft YaHei", 9, "bold")).pack(fill="x")
        group("采集")
        flat_btn("保存帧 (S)", self.act_save)
        flat_btn("导出点云 (P)", self.act_export)
        flat_btn("连续采集 (C)", self.act_continuous)
        group("建模")
        flat_btn("▣ 3D 扫描工作站", self.open_3d)
        flat_btn("转台采集", self.act_turntable)
        flat_btn("一键融合", self.act_fuse)
        group("工具")
        flat_btn("标定", self.act_calib)
        flat_btn("测距 (L)", self.act_measure)
        flat_btn("显示设置", self.act_settings)
        flat_btn("检查更新", self.act_update)
        group("画面")
        flat_btn("灰度 / 伪彩 (G)", self.toggle_gray)
        flat_btn("镜像修正 (M)", self.toggle_mirror)
        flat_btn("暂停 (空格)", self.act_pause)
        be = tk.Button(self.side, text="退出程序 (Q)", command=self.on_close,
                       bg="#3a2230", fg="#ff8f8f", activebackground="#552a3a",
                       activeforeground="white", relief="flat", bd=0, padx=10,
                       pady=4, cursor="hand2", font=("Microsoft YaHei", 10),
                       anchor="w")
        be.pack(fill="x", pady=(8, 2))
        be.bind("<Enter>", lambda e: be.config(bg="#552a3a"))
        be.bind("<Leave>", lambda e: be.config(bg="#3a2230"))

        self.lb_log = tk.Label(self.side, text="", justify="left", anchor="nw",
                               wraplength=300, font=("Microsoft YaHei", 9),
                               fg=WARN, bg=BG)
        self.lb_log.pack(fill="both", expand=True, pady=(10, 0))

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._closing = False

    # ---- preview 部件（模块 setup 后调用）----
    def build_preview(self):
        pm = self.pipe.get("preview")
        if pm is None:
            return
        self._preview = pm.create_widget(self.main)
        self._preview.pack(side="left")

    # ---- 线程安全入口（可从任意线程调用）----
    def log(self, msg, ok=True):
        self._log_lines.append((time.strftime("%H:%M:%S"), msg, ok))

    def set_dev_status(self, text):
        self._dev_status = text

    def set_rgb_status(self, text):
        self._rgb_status = text

    # ---- 主线程刷新节拍 ----
    def refresh_tick(self):
        if self._closing:
            return
        self.lb_dev.config(text=self._dev_status,
                           fg=OK if "运行" in self._dev_status or "就绪" in self._dev_status
                           else MUTED)
        self.lb_rgb.config(text=self._rgb_status,
                           fg=OK if "已连接" in self._rgb_status else MUTED)
        if self._preview is not None:
            self.lb_fps.config(text=f"{self._preview.fps:.1f} fps")
            pl = self.pipe.get("device")
            dev_ln = pl.link if pl is not None else None
            stat = [
                f"深度帧 : {self._preview.depth_count}",
                f"RGB 帧 : {self._preview.rgb_count}",
                f"数据帧率: {self._preview.fps:.1f} fps",
            ]
            if dev_ln is not None:
                stat += [
                    f"丢包补偿: {dev_ln.padded_frames} 帧 / {dev_ln.gap_total} 槽",
                    f"拒帧    : {dev_ln.rejected}",
                ]
            stat.append("镜像    : " +
                        ("开" if (pl is not None and pl.get_flip()) else "关"))
            self.lb_info.config(text="\n".join(stat))
        if self._log_lines:
            lines = [f"[{t}] {m}" for t, m, ok in list(self._log_lines)[-12:]]
            txt = "\n".join(lines)
            if txt != self._last_log:
                self._last_log = txt
                self.lb_log.config(text=txt)
        self.after(400, self.refresh_tick)

    # ---- 动作 ----
    def open_3d(self):
        v = self.pipe.get("viewer3d")
        if v is None:
            return

        def get_points():
            pv = getattr(self.pipe.get("preview"), "_widget", None)
            if pv is None or pv.depth is None:
                return None
            from core import cloudmath as cm
            return cm.depth_to_points(pv.depth, pv.mm_per_shift[0], rgb=pv.rgb)

        v.open(get_points, title="3D 扫描工作站 — 实时")

    def toggle_gray(self):
        pv = getattr(self.pipe.get("preview"), "_widget", None)
        if pv is not None:
            g = pv.toggle_gray()
            self.log(f"深度显示: {'灰度' if g else '伪彩'}")

    def toggle_mirror(self):
        dev = self.pipe.get("device")
        if dev is not None:
            dev.set_flip(not dev.get_flip())
            self.log(f"镜像修正: {'开' if dev.get_flip() else '关'}")

    def on_close(self):
        self._closing = True
        try:
            self.pipe.stop_all()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    # ---- 模块动作（全部经 pipeline 调模块 API）----
    def _pv(self):
        return getattr(self.pipe.get("preview"), "_widget", None)

    def act_save(self):
        rec = self.pipe.get("recorder")
        base = rec.save_snapshot() if rec else None
        self.log("已保存快照" if base else "还没有画面", bool(base))

    def act_export(self):
        rec = self.pipe.get("recorder")
        p = rec.export_cloud() if rec else None
        self.log(f"点云已导出 → {p}" if p else "还没有画面", bool(p))

    def act_continuous(self):
        rec = self.pipe.get("recorder")
        if rec:
            on = rec.toggle_continuous()
            self.log(f"连续采集: {'开' if on else '关'}")

    def act_turntable(self):
        rec = self.pipe.get("recorder")
        if rec:
            rec.open_turntable_dialog(self)

    def act_fuse(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="选择转台采集目录（含 manifest.json）",
                                    initialdir=str(self.pipe.root.parent / "扫描输出"))
        if not d:
            return
        self.log(f"开始融合: {d}（几十秒~几分钟）")
        import threading

        def run():
            try:
                self.pipe.get("fusion").fuse_directory(d)
                self.log("融合完成 → 已打开目录", True)
                import os
                try:
                    os.startfile(d)
                except Exception:
                    pass
            except Exception as e:
                self.log(f"融合失败: {str(e)[:60]}", False)
        threading.Thread(target=run, daemon=True).start()

    def act_calib(self):
        cal = self.pipe.get("calib")
        pv = self._pv()
        if cal and pv:
            cal.open_dialog(self, lambda: pv.depth)

    def act_measure(self):
        m = self.pipe.get("measure")
        if m:
            on = m.toggle()
            self.log(f"测距模式: {'开（画布点两点）' if on else '关'}")

    def act_settings(self):
        st = self.pipe.get("settings")
        if st:
            st.open_dialog(self)

    def act_pause(self):
        pv = self._pv()
        if pv:
            on = pv.toggle_pause()
            self.log(f"已暂停预览" if on else "已恢复预览")

    def act_update(self):
        up = self.pipe.get("updater")
        if up:
            up.open_dialog(self)
