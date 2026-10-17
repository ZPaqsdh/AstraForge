# -*- coding: utf-8 -*-
"""viewer3d 模块 — 3D 扫描工作站（实时预览 + ICP 记录累积 + 导出）。

对外 API（UI 经 pipeline.get("viewer3d").open(...) 调用）：
    open(get_points, title=..., static=False) -> Scan3DView 窗口
    get_points() -> Nx6(几何mm+RGB) 或 Nx3；static=True 为 PLY 静态查看

依赖：core.cloudmath（点云算法）/ core.theme（色带）/ tkinter
"""
import time
import queue
import threading

import numpy as np
import tkinter as tk
from PIL import Image, ImageDraw

from core.contracts import ModuleContext
from core import cloudmath as _cm          # 供 Scan3DView 方法内 F.* 调用
from core.theme import LUT, BG, PANEL


class Scan3DView(tk.Toplevel):
    """3D 扫描工作站：实时预览 + ICP 记录累积 + 导出。

    数据源 get_frame_points() -> Nx6 (几何 mm + RGB 0-255) 或 Nx3；None=无数据。
    记录模式：每帧点云与累积模型做 ICP 配准后融合（手持自由移动，
    无需转台）；跟踪质量灯实时反馈配准状态。
    """

    def __init__(self, master, get_frame_points, title="3D 扫描工作站",
                 static=False):
        super().__init__(master)
        self.title(title)
        self.configure(bg=BG)
        self.geometry("940x720")
        self.static = static           # PLY 静态查看（禁记录）
        self.get_frame_points = get_frame_points
        self.az, self.el = 35.0, 25.0
        self.scale = 1.0
        self.pan = [0.0, 0.0]
        self._last = None
        self.live = True                # 实时渲染开关
        self.recording = False          # 记录累积开关
        self.model = None               # 累积点云 Nx3/Nx6
        self.track_q = 1.0              # 跟踪质量 0-1
        self._fps_n = 0
        self._fps_t = time.time()
        self.fps = 0.0
        self._alive = True
        self._img_q = queue.Queue(maxsize=2)   # worker→主线程 图像队列（tkinter 非线程安全）

        # ---- 顶栏：记录控制 ----
        bar = tk.Frame(self, bg="#1e1e2a")
        bar.pack(fill="x")
        btns = ([("⬇ 导出点云", self._export, "bt_exp")] if static else
                [("● 开始记录", self._toggle_rec, "bt_rec"),
                 ("⬇ 导出点云", self._export, "bt_exp"),
                 ("清空重扫", self._clear, "bt_clr")])
        for txt, cmd, name in btns:
            b = tk.Button(bar, text=txt, command=cmd, bg="#26263a", fg="#e8e9ee",
                          activebackground="#3a3a55", activeforeground="white",
                          relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
                          font=("Microsoft YaHei", 10))
            b.pack(side="left", padx=(8 if name == "bt_rec" else 4, 4), pady=6)
            setattr(self, name, b)
        self.bt_live = tk.Button(bar, text="实时: 开", command=self._toggle_live,
                                 bg="#26263a", fg="#e8e9ee", activebackground="#3a3a55",
                                 activeforeground="white", relief="flat", bd=0,
                                 padx=10, pady=4, cursor="hand2",
                                 font=("Microsoft YaHei", 10))
        self.bt_live.pack(side="left", padx=4, pady=6)

        # ---- 状态行 ----
        st = tk.Frame(self, bg="#1e1e2a")
        st.pack(fill="x")
        self.lb_track = tk.Label(st, text="●", fg="#5a5f70", bg="#1e1e2a",
                                 font=("Microsoft YaHei", 12, "bold"))
        self.lb_track.pack(side="left", padx=(10, 2))
        self.lb_stat = tk.Label(st, text="实时预览中", fg="#9aa0b0", bg="#1e1e2a",
                                font=("Consolas", 10))
        self.lb_stat.pack(side="left")

        # ---- 画布（跟随窗口伸缩）----
        self.W, self.H = 920, 600
        self._fit_k = None              # 记录模式锁定的适配系数（防累积"呼吸"）
        self.canvas = tk.Canvas(self, width=self.W, height=self.H, bg="#101018",
                                highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<B1-Motion>", self._rotate)
        self.canvas.bind("<B3-Motion>", self._pan)
        self.canvas.bind("<MouseWheel>", self._zoom)
        self.bind("<r>", lambda e: self._reset_view())

        tk.Label(self, text="左键旋转 · 滚轮缩放 · 右键平移 · R 复位视角 · "
                            "记录时应缓慢平移/旋转设备（跟 RealSense 扫描一个手法）",
                 fg="#5a5f70", bg=BG, font=("Microsoft YaHei", 9)).pack(pady=4)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=self._worker_loop, daemon=True).start()
        self._tick()

    def _on_close(self):
        self._alive = False
        self.destroy()

    # ---------- 控制 ----------
    def _toggle_live(self):
        self.live = not self.live
        self.bt_live.config(text=f"实时: {'开' if self.live else '关'}")

    def _toggle_rec(self):
        self.recording = not self.recording
        if self.recording:
            self.model = None
            self.track_q = 1.0
            self._fit_k = None          # 新记录重新适配
            self.bt_rec.config(text="■ 停止记录", fg="#ff6b6b")
        else:
            self.bt_rec.config(text="● 开始记录", fg="#e8e9ee")

    def _clear(self):
        self.model = None
        self.track_q = 1.0
        self._fit_k = None
        self.lb_track.config(fg="#5a5f70")

    def _reset_view(self):
        self.az, self.el, self.scale, self.pan = 35.0, 25.0, 1.0, [0.0, 0.0]
        self._fit_k = None              # 重新按当前点云适配（worker 下轮重绘）

    def _on_resize(self, e):
        """窗口伸缩 → 画布尺寸跟随 → 重算适配并重渲染"""
        if e.width != self.W or e.height != self.H:
            self.W, self.H = max(e.width, 50), max(e.height, 50)
            self._fit_k = None          # 窗口变了重新适配（保持铺满，worker 重绘）

    def _rotate(self, e):
        if self._last:
            self.az = (self.az + (e.x - self._last[0]) * 0.5) % 360
            self.el = max(-89.0, min(89.0, self.el + (e.y - self._last[1]) * 0.5))
        self._last = (e.x, e.y)      # 只改参数，worker 下轮重绘

    def _pan(self, e):
        if self._last:
            self.pan[0] += e.x - self._last[0]
            self.pan[1] += e.y - self._last[1]
        self._last = (e.x, e.y)

    def _zoom(self, e):
        self.scale = max(0.05, min(50.0,
                                   self.scale * (1.15 if e.delta > 0 else 1 / 1.15)))

    # ---------- 主循环（100ms 节拍，只做轻量 UI；重活全在 worker） ----------
    def _tick(self):
        if not self._alive:
            return
        # 消费 worker 产出的图像（队列是唯一跨线程通道——tkinter 控件非线程安全）
        while not self._img_q.empty():
            try:
                self._present(self._img_q.get_nowait())
            except Exception:
                break
        self._fps_n += 1
        now = time.time()
        if now - self._fps_t >= 0.2:
            self.fps = self._fps_n / (now - self._fps_t)
            self._fps_t = now
            self._fps_n = 0
            if self.recording:
                n = 0 if self.model is None else len(self.model)
                weak = "（跟踪弱！放慢或回退到已扫区域）" if self.track_q < 0.2 else ""
                self.lb_track.config(fg=self._track_color())
                self.lb_stat.config(text=f"累积 {n} 点 | 跟踪 {self.track_q:.2f} "
                                         f"| {self.fps:.0f} fps {weak}")
            else:
                self.lb_track.config(fg="#5a5f70")
                self.lb_stat.config(text=f"实时预览 | {self.fps:.0f} fps"
                                         f"（点「开始记录」累积点云）")
        self.after(100, self._tick)

    # ---------- worker 线程：取帧/ICP 累积/构图全在这里，UI 线程不卡 ----------
    def _worker_loop(self):
        while self._alive:
            time.sleep(0.05)                     # ~20Hz 处理节拍
            if not self._alive:
                break
            try:
                pts = self.get_frame_points()
            except Exception:
                pts = None
            if self.recording and pts is not None and len(pts) > 500:
                self._accumulate(pts)
            if self.live:
                img = self._build_image()
                if img is not None:
                    if self._img_q.full():       # 满了丢最旧（保新鲜）
                        try:
                            self._img_q.get_nowait()
                        except Exception:
                            pass
                    self._img_q.put(img)

    def _track_color(self):
        if self.track_q >= 0.5:
            return "#3fd68c"
        if self.track_q >= 0.2:
            return "#ffb454"
        return "#ff6b6b"

    # ---------- ICP 累积（worker 线程内运行，限额防掉队） ----------
    def _accumulate(self, pts):
        from core import cloudmath as F
        pts_ds = F.voxel_down(pts, 4.0)
        if len(pts_ds) > 12000:
            sel = np.random.default_rng(0).choice(len(pts_ds), 12000, replace=False)
            pts_ds = pts_ds[sel]
        if self.model is None or len(self.model) < 100:
            self.model = pts_ds.copy()
            self.track_q = 1.0
            return
        g = pts_ds[:, :3]
        target = F.voxel_down(self.model[:, :3], 6.0)
        if len(target) > 15000:
            sel = np.random.default_rng(1).choice(len(target), 15000, replace=False)
            target = target[sel]
        T = F.icp(g, target, np.eye(4), iters=6)
        g_t = g @ T[:3, :3].T + T[:3, 3]
        # 跟踪质量：变换后与目标的内点比
        idx = F.NearestIndex(target)
        j = idx.query(g_t)
        d = np.linalg.norm(g_t - target[j], axis=1)
        self.track_q = float((d < 8.0).mean())
        if self.track_q >= 0.15:                    # 质量达标才累积（防污染模型）
            pts_t = pts_ds.copy()
            pts_t[:, :3] = g_t
            self.model = np.concatenate([self.model, pts_t], axis=0)
            if len(self.model) > 300000:
                self.model = F.voxel_down(self.model, 2.5)

    # ---------- 投影与渲染 ----------
    def _project(self, pts):
        # 先中心化（点云均值归零），否则非原点系（如相机系 z=500）投影后整体偏移
        P = pts - pts.mean(axis=0)
        a, e = np.deg2rad(self.az), np.deg2rad(self.el)
        ca, sa = np.cos(a), np.sin(a)
        ce, se = np.cos(e), np.sin(e)
        x = P[:, 0] * ca + P[:, 2] * sa
        z0 = -P[:, 0] * sa + P[:, 2] * ca
        y = P[:, 1] * ce - z0 * se
        z = P[:, 1] * se + z0 * ce
        span = max(np.ptp(x), np.ptp(y), 1.0)
        if self.recording:
            # 记录模式：首帧锁定适配系数——累积越大越扫越小的"呼吸"效应
            if self._fit_k is None:
                self._fit_k = min(self.W, self.H) * 0.9 / span
            k = self._fit_k * self.scale
        else:
            # 实时模式：每帧重新适配（铺满窗口短边 90%，居中）
            k = min(self.W, self.H) * 0.9 / span * self.scale
        sx = self.W / 2 + self.pan[0] + x * k
        sy = self.H / 2 + self.pan[1] - y * k
        m = (sx >= 0) & (sx < self.W) & (sy >= 0) & (sy < self.H)
        return sx, sy, m

    def _current_pts(self):
        if self.recording and self.model is not None and len(self.model) >= 50:
            return self.model
        try:
            return self.get_frame_points()
        except Exception:
            return None

    def _build_image(self):
        """worker 线程：投影+画点 → PIL Image（不碰 tkinter 控件）"""
        pts = self._current_pts()
        if pts is None or len(pts) < 50:
            return None
        if len(pts) > 16000:                      # 渲染抽样
            sel = np.random.default_rng(1).choice(len(pts), 16000, replace=False)
            pts = pts[sel]
        sx, sy, m = self._project(pts[:, :3])
        sx, sy = sx[m], sy[m]
        e = np.deg2rad(self.el)
        a = np.deg2rad(self.az)
        zc = pts[m, 1] * np.sin(e) + \
             (-pts[m, 0] * np.sin(a) + pts[m, 2] * np.cos(a)) * np.cos(e)

        img = Image.new("RGB", (self.W, self.H), (16, 16, 24))
        dr = ImageDraw.Draw(img)
        if len(zc):
            order = np.argsort(zc)               # 远的先画，近的盖上面
            zs, xs, ys = zc[order], sx[order], sy[order]
            edges = np.quantile(zs, np.linspace(0, 1, 9))
            for i in range(8):
                seg = (zs >= edges[i]) & (zs <= edges[i + 1])
                if seg.any():
                    c = LUT[int(i * 255 / 7)]
                    dr.point(list(zip(xs[seg].tolist(), ys[seg].tolist())),
                             fill=(int(c[0]), int(c[1]), int(c[2])))
        return img

    def _present(self, img):
        """主线程：贴图（快）——尺寸变化（窗口伸缩）时重建 PhotoImage"""
        if not self._alive:
            return
        if getattr(self, "photo", None) is None or \
                getattr(self, "_photo_size", None) != (self.W, self.H):
            self.photo = ImageTk.PhotoImage(img)
            self._photo_size = (self.W, self.H)
            if getattr(self, "_img_id", None) is None:
                self._img_id = self.canvas.create_image(0, 0, anchor="nw",
                                                        image=self.photo)
            else:
                self.canvas.itemconfig(self._img_id, image=self.photo)
        else:
            self.photo.paste(img)

    # ---------- 导出 ----------
    def _export(self):
        if self.model is None or len(self.model) < 1000:
            self.lb_stat.config(text="没有可导出的点云（先「开始记录」扫一会儿）")
            return
        from tkinter import filedialog
        p = filedialog.asksaveasfilename(title="导出点云", defaultextension=".ply",
                                         filetypes=[("PLY", "*.ply")])
        if not p:
            return
        try:
            from core import cloudmath as F
            if self.model.shape[1] >= 6:
                F.save_ply(p, self.model[:, :3],
                           colors=self.model[:, 3:6].astype(np.uint8))
            else:
                F.save_ply(p, self.model[:, :3])
            self.lb_stat.config(text=f"已导出 {len(self.model)} 点 → {p}")
        except Exception as ex:
            self.lb_stat.config(text=f"导出失败: {str(ex)[:40]}")


# ---------------- 模块壳 ----------------
class Viewer3DModule:
    """viewer3d 功能模块（Module 协议）。"""
    name = "viewer3d"
    version = "1.0.0"

    def __init__(self):
        self.ctx = None
        self._wins = []

    def setup(self, ctx: ModuleContext):
        self.ctx = ctx
        ctx.log(f"[viewer3d] 就绪 v{self.version}", True)

    def start(self):
        pass                        # 按需开窗，无常驻

    def stop(self):
        for w in self._wins:
            try:
                w._alive = False
                w.destroy()
            except Exception:
                pass
        self._wins = []

    def open(self, get_points, title="3D 扫描工作站", static=False):
        """开一个 3D 工作站窗口（UI 层入口）。"""
        win = Scan3DView(self.ctx.ui_root, get_points, title=title, static=static)
        self._wins.append(win)
        return win
