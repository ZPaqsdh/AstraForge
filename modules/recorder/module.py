# -*- coding: utf-8 -*-
"""recorder 模块 — 数据记录（快照 / 点云导出 / 连续采集 / 转台采集）。

订阅 depth.frame/rgb.frame 缓存最新帧；对外 API 供 UI 调用：
    save_snapshot()        # 深度 npy+png + RGB png → 扫描输出/
    export_cloud()         # 当前帧点云 PLY
    toggle_continuous()    # 每 2 秒自动快照
    tt_start() / tt_shoot() / tt_finish()   # 转台采集（turntable_<ts>/+manifest）
"""
import json
import os
import threading
import time

import numpy as np

from core.contracts import ModuleContext
from core import cloudmath


class RecorderModule:
    name = "recorder"
    version = "1.1.2"

    def __init__(self):
        self.ctx = None
        self.last_depth = None
        self.last_rgb = None          # numpy RGB
        self.rgb_count = 0            # RGB 帧累计计数（帧率统计用）
        self.mm_per_shift = 1.0
        self.continuous = [False]
        self._last_auto = 0.0
        self._tt = {"dir": None, "frames": [], "angle": 0.0, "ts": None}

    def setup(self, ctx: ModuleContext):
        self.ctx = ctx
        self.mm_per_shift = float(ctx.settings.get("mm_per_shift", 1.0))
        # 启动还原导出目录（data/设置.json；自定义目录随设置持久化）
        try:
            from core import appsettings
            saved = appsettings.load(ctx.data_dir).get("out_dir")
            if isinstance(saved, str) and saved.strip():
                ctx.settings["out_dir"] = saved.strip()
        except Exception:
            pass
        ctx.bus.subscribe("depth.frame", self._on_depth)
        ctx.bus.subscribe("rgb.frame", self._on_rgb)
        ctx.bus.subscribe("calib.changed", self._on_calib)
        ctx.log(f"[recorder] 就绪 v{self.version}", True)

    def start(self):
        threading.Thread(target=self._auto_loop, daemon=True).start()

    def stop(self):
        pass

    # ---- 事件（采集线程回调：原子赋值）----
    def _on_depth(self, f):
        self.last_depth = f.data

    def _on_rgb(self, f):
        self.last_rgb = f.data
        self.rgb_count += 1

    def _on_calib(self, v):
        try:
            self.mm_per_shift = float(v)
        except Exception:
            pass

    # ---- 目录 ----
    def _out_dir(self):
        """导出目录解析（三级回退，防"装在 Program Files 后不可写"）：
        ① 设置里自定义的目录（用户显式选择，优先）
        ② 默认：软件根目录旁的「扫描输出」
        ③ 根目录不可写（UAC / Program Files）→ 回退到 用户文档\\AstraForge\\扫描输出
        """
        custom = self.ctx.settings.get("out_dir")
        if custom:
            try:
                os.makedirs(custom, exist_ok=True)
                return str(custom)
            except Exception:
                pass
        cand = self.ctx.root_dir.parent / "扫描输出"
        try:
            cand.mkdir(parents=True, exist_ok=True)
            # 只做权限判定，不创建/删除探针文件：
            # 某些安全软件会拦截临时文件删除（unlink 失败），导致误判"目录不可写"
            # 而整体回退到用户文档。os.access 足以覆盖 Program Files 只读场景。
            if os.access(str(cand), os.W_OK):
                return str(cand)
        except Exception:
            pass
        try:
            from pathlib import Path
            alt = Path.home() / "Documents" / "AstraForge" / "扫描输出"
            alt.mkdir(parents=True, exist_ok=True)
            if not getattr(self, "_warned_alt", False):
                self._warned_alt = True
                try:
                    self.ctx.log(f"[recorder] 软件目录不可写 → 导出位置回退：{alt}", True)
                except Exception:
                    pass
            return str(alt)
        except Exception:
            return str(cand)

    def _base_name(self):
        return time.strftime("scan_%Y%m%d_%H%M%S")

    # ---- 快照 ----
    def save_snapshot(self, silent=False):
        """深度 npy + 深度 png + RGB png（输出端裁剪对齐，见 core.contracts）。返回基路径或 None。"""
        if self.last_depth is None:
            return None
        from PIL import Image
        from core.contracts import crop_for_output
        dep, rgb = crop_for_output(self.last_depth, self.last_rgb)
        d = self._out_dir()
        base = os.path.join(d, self._base_name())
        np.save(base + ".npy", dep)
        # 深度伪彩预览（供人肉查看；渲染逻辑独立于 preview 模块）
        import core.theme as th
        g = np.clip(dep.astype(np.float32) / th.DISP_MAX * 255.0,
                    0, 255).astype(np.uint8)
        vis = np.empty((*dep.shape, 3), dtype=np.uint8)
        vis[:] = th.LUT[g]
        vis[dep <= 0] = th.INVALID_PX
        Image.fromarray(vis).save(base + "_depth.png")
        if rgb is not None:
            Image.fromarray(rgb).save(base + "_rgb.png")
        return base

    # ---- 点云导出（当前帧）----
    def export_cloud(self):
        if self.last_depth is None:
            return None
        from core.contracts import crop_for_output
        dep, rgb = crop_for_output(self.last_depth, self.last_rgb)
        pts = cloudmath.depth_to_points(dep, self.mm_per_shift, rgb=rgb)
        d = self._out_dir()
        base = os.path.join(d, self._base_name())
        if pts.shape[1] >= 6:
            cloudmath.save_ply(base + "_cloud.ply", pts[:, :3],
                               colors=pts[:, 3:6].astype(np.uint8))
        else:
            cloudmath.save_ply(base + "_cloud.ply", pts)
        return base + "_cloud.ply"

    # ---- 连续采集（daemon 线程 2s 节拍）----
    def toggle_continuous(self):
        self.continuous[0] = not self.continuous[0]
        return self.continuous[0]

    def _auto_loop(self):
        while True:
            time.sleep(0.5)
            if not self.continuous[0] or self.last_depth is None:
                continue
            try:
                import astra_studio_clock  # noqa: F401  （占位，防误用）
            except Exception:
                pass
            now = time.time()
            if now - self._last_auto >= 2.0:
                self._last_auto = now
                self.save_snapshot(silent=True)

    # ---- 转台采集 ----
    def tt_start(self):
        self._tt = {"dir": None, "frames": [], "angle": 0.0,
                    "ts": time.strftime("%Y%m%d_%H%M%S")}

    def tt_shoot(self, step_deg=15.0, cam_dist=0.0):
        """拍一帧：深度 npy + RGB png + 角度/距离记录。返回已采帧数。"""
        if self.last_depth is None:
            return -1
        from PIL import Image
        if self._tt["ts"] is None:
            self.tt_start()               # 未经 tt_start 直接拍 → 自动开新采集
        if self._tt["dir"] is None:
            self._tt["dir"] = os.path.join(self._out_dir(),
                                           f"turntable_{self._tt['ts']}")
            os.makedirs(self._tt["dir"], exist_ok=True)
        n = len(self._tt["frames"])
        from core.contracts import crop_for_output
        dep, rgb = crop_for_output(self.last_depth, self.last_rgb)
        np.save(os.path.join(self._tt["dir"], f"frame_{n:03d}.npy"), dep)
        if rgb is not None:
            try:
                Image.fromarray(rgb).save(
                    os.path.join(self._tt["dir"], f"frame_{n:03d}_rgb.png"))
            except Exception:
                pass
        self._tt["frames"].append({
            "file": f"frame_{n:03d}.npy",
            "angle": round(self._tt["angle"], 1),
            "cam_dist": cam_dist if cam_dist > 0 else None})
        self._tt["angle"] += float(step_deg)
        return len(self._tt["frames"])

    def tt_finish(self):
        """写 manifest.json，返回目录路径（无帧返回 None）。"""
        if not self._tt["frames"]:
            return None
        man = {"mm_per_shift": self.mm_per_shift,
               "note": "转台采集：angle=拍该帧时物体已转过的角度；cam_dist=相机到转台轴距离",
               "frames": self._tt["frames"]}
        with open(os.path.join(self._tt["dir"], "manifest.json"), "w",
                  encoding="utf-8") as f:
            json.dump(man, f, ensure_ascii=False, indent=2)
        d = self._tt["dir"]
        self._tt = {"dir": None, "frames": [], "angle": 0.0, "ts": None}
        return d

    def tt_count(self):
        return len(self._tt["frames"])

    # ---- 手持扫描记录（无转台：每帧 angle=0，ICP 相对上一帧精修拼接） ----
    def scan_start(self):
        """开一轮手持扫描记录（目录 scan_session_<ts>/）。"""
        self._scan = {"dir": None, "ts": time.strftime("%Y%m%d_%H%M%S"), "n": 0}

    def scan_shoot(self):
        """拍一帧（手持）。返回已采帧数。"""
        if self.last_depth is None:
            return -1
        if not hasattr(self, "_scan") or self._scan.get("ts") is None:
            self.scan_start()
        from PIL import Image
        if self._scan["dir"] is None:
            self._scan["dir"] = os.path.join(self._out_dir(),
                                             f"scan_session_{self._scan['ts']}")
            os.makedirs(self._scan["dir"], exist_ok=True)
        n = self._scan["n"]
        from core.contracts import crop_for_output
        dep, rgb = crop_for_output(self.last_depth, self.last_rgb)
        np.save(os.path.join(self._scan["dir"], f"frame_{n:03d}.npy"), dep)
        if rgb is not None:
            try:
                Image.fromarray(rgb).save(
                    os.path.join(self._scan["dir"], f"frame_{n:03d}_rgb.png"))
            except Exception:
                pass
        self._scan["n"] += 1
        return self._scan["n"]

    def scan_finish(self):
        """写 manifest（frames angle 全 0 → 融合时走 ICP 串行精修）。返回目录。"""
        if not hasattr(self, "_scan") or not self._scan.get("n"):
            return None
        d = self._scan["dir"]
        man = {"mm_per_shift": self.mm_per_shift,
               "note": "手持扫描记录：angle 全 0，融合时以 ICP 相对上一帧精修拼接",
               "frames": [{"file": f"frame_{i:03d}.npy", "angle": 0.0,
                           "cam_dist": None} for i in range(self._scan["n"])]}
        with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(man, f, ensure_ascii=False, indent=2)
        self._scan = {"dir": None, "ts": None, "n": 0}
        return d

    def scan_count(self):
        return getattr(self, "_scan", {}).get("n", 0)


    # ---- 转台采集对话框 ----
    def open_turntable_dialog(self, master):
        import tkinter as tk
        from core.theme import BG, FG, ACCENT, OK, WARN, BTN

        win = tk.Toplevel(master)
        win.title("转台采集")
        win.configure(bg=BG)
        win.geometry("400x300")
        self.tt_start()

        frm = tk.Frame(win, bg=BG); frm.pack(fill="x", padx=14, pady=(14, 4))
        tk.Label(frm, text="步进角度 (°):", fg=FG, bg=BG, width=15,
                 anchor="w").pack(side="left")
        var_step = tk.StringVar(value="15")
        tk.Entry(frm, textvariable=var_step, width=8).pack(side="left")
        frm2 = tk.Frame(win, bg=BG); frm2.pack(fill="x", padx=14, pady=4)
        tk.Label(frm2, text="相机→转台距离(mm):", fg=FG, bg=BG, width=15,
                 anchor="w").pack(side="left")
        var_d = tk.StringVar(value="0")
        tk.Entry(frm2, textvariable=var_d, width=8).pack(side="left")
        tk.Label(win, text="（0 = 用每帧画面中心深度自动估计）", fg="#9aa0b0", bg=BG,
                 font=("Microsoft YaHei", 8)).pack(anchor="w", padx=14)

        lb_stat = tk.Label(win, text="已采 0 帧（当前角度 0°）", fg=ACCENT, bg=BG,
                           font=("Consolas", 10))
        lb_stat.pack(pady=10)

        def shoot():
            try:
                step = float(var_step.get() or 15)
                dg = float(var_d.get() or 0)
            except ValueError:
                step, dg = 15.0, 0.0
            n = self.tt_shoot(step_deg=step, cam_dist=dg)
            if n < 0:
                lb_stat.config(text="还没有画面", fg=WARN); return
            lb_stat.config(text=f"已采 {n} 帧（下一帧角度 {n * step:.0f}°）", fg=OK)

        def finish():
            d = self.tt_finish()
            if d is None:
                lb_stat.config(text="一帧都没采", fg=WARN); return
            lb_stat.config(text=f"✓ 完成 → {d}\n点「一键融合」选该目录生成模型", fg=OK)
            self.ctx.log(f"[recorder] 转台采集完成 → {d}", True)

        bf = tk.Frame(win, bg=BG); bf.pack(pady=8)
        for txt, cmd, fg in (("拍这一帧", shoot, FG), ("完成", finish, OK),
                             ("关闭", win.destroy, FG)):
            tk.Button(bf, text=txt, command=cmd, bg=BTN, fg=fg, relief="flat",
                      bd=0, padx=10, pady=3, cursor="hand2",
                      font=("Microsoft YaHei", 9)).pack(side="left", padx=6)
        win.bind("<Return>", lambda e: shoot())
