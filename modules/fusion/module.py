# -*- coding: utf-8 -*-
"""fusion 模块 — 转台多帧融合 → 完整点云/网格。

对外 API（UI/recorder 经 pipeline.get("fusion") 调用，换实现只换本目录）：
    fuse_directory(d, **kw) -> PointCloud(+stl)      # 目录级融合（同步）
    fuse_directory_async(d, workers=None)            # 后台任务 + progress 轮询
    fuse_cancel()                                    # 请求取消（下一检查点生效）
    get_progress() -> dict                           # {stage,pct,msg,done,error,out_dir}
    depth_to_points(depth, mms, rgb=None)            # 单帧→点云（实时/3D 用）
    save_ply / load_ply / voxel_down / icp           # 算法透传（cloudmath）

性能模式（users 口径）：std/perf = max(核数-1, 1) workers，狂暴 = 全核。
GPU（cuPy 同构替换）预留：detect_gpu() 检测 NVIDIA，backbone 切换点见 README。
"""
import threading

from core.contracts import ModuleContext, PointCloud
from core import cloudmath

_GPU_CACHE = None       # GPU 检测结果缓存（避免高频子进程调用）


class FusionModule:
    name = "fusion"
    version = "1.1.0"

    def __init__(self):
        self.ctx = None
        self.progress = {"stage": "", "pct": 0.0, "msg": "",
                         "done": False, "error": None, "out_dir": None}
        self._thread = None
        self._cancel = threading.Event()

    def setup(self, ctx: ModuleContext):
        self.ctx = ctx
        ctx.log(f"[fusion] 就绪 v{self.version}（算法库 core.cloudmath）", True)

    def start(self):
        pass                        # 服务型模块：无帧流，按需调用

    def stop(self):
        self._cancel.set()

    # ---------- 对外 API ----------
    def fuse_directory(self, d, **kw):
        """目录级融合 → PointCloud（同步，内部写 fused_* 文件）。"""
        fused, verts, faces = cloudmath.fuse_directory(d, **kw)
        pc = PointCloud(points=fused[:, :3],
                        colors=fused[:, 3:6].astype("uint8") if fused.shape[1] >= 6 else None,
                        meta={"verts": verts, "faces": faces})
        return pc

    def workers_for(self, mode="std"):
        """性能模式 → 读帧并行 worker 数（原则：始终保留 1 核给系统）。"""
        import os as _os
        n = _os.cpu_count() or 4
        if mode == "turbo":
            return n                      # 狂暴：全核
        return max(n - 1, 1)              # 标准/性能：核数-1

    def fuse_directory_async(self, d, workers=None):
        """后台线程跑融合，进度经 get_progress() 读（前端轮询）。"""
        if self._thread is not None and self._thread.is_alive():
            return {"ok": False, "error": "已有融合任务在跑"}
        self._cancel.clear()
        self.progress = {"stage": "read", "pct": 0.0, "msg": "启动中…",
                         "done": False, "error": None, "out_dir": d}

        def _on_prog(stage, pct, msg):
            self.progress.update(stage=stage, pct=float(pct), msg=msg)
            if self.ctx:
                self.ctx.bus.publish("fusion.progress", dict(self.progress))

        def run():
            try:
                kw = {"on_progress": _on_prog}
                if workers and workers > 1:
                    kw["workers"] = workers
                fused, verts, faces = cloudmath.fuse_directory(
                    d, **_cancellable(self._cancel, kw))
                self.progress.update(done=True, pct=1.0,
                                     msg=f"完成：{len(fused)} 点")
                if self.ctx:
                    self.ctx.log(f"[fusion] 完成 → {d}（{len(fused)} 点）", True)
            except _Cancelled:
                self.progress.update(error="已取消", done=True)
            except Exception as e:
                self.progress.update(error=str(e)[:120], done=True)
                if self.ctx:
                    self.ctx.log(f"[fusion] 失败: {str(e)[:80]}", False)

        self._thread = threading.Thread(target=run, daemon=True,
                                        name="fusion-task")
        self._thread.start()
        return {"ok": True}

    def fuse_cancel(self):
        self._cancel.set()
        return {"ok": True}

    def get_progress(self):
        return dict(self.progress)

    def detect_gpu(self):
        """GPU 检测（CUDA/cuPy 预留：检测到 NVIDIA 才提示可用）。
        结果缓存（首次后不再跑子进程——曾因轮询高频调用 nvidia-smi
        导致控制台窗口频弹 + 阻塞单线程 server）。"""
        global _GPU_CACHE
        if _GPU_CACHE is not None:
            return dict(_GPU_CACHE)
        info = {"cuda": False, "name": None, "note": ""}
        try:
            import cupy  # noqa: F401
            info["cuda"] = True
        except ImportError:
            pass
        if not info["cuda"]:
            try:
                import subprocess
                r = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True, text=True, timeout=4,
                    creationflags=0x08000000,      # CREATE_NO_WINDOW（不弹控制台）
                )
                if r.returncode == 0 and r.stdout.strip():
                    info["name"] = r.stdout.strip().splitlines()[0]
            except Exception:
                pass
        if not info["name"] and not info["cuda"]:
            info["note"] = "无 CUDA 环境（未装 cuPy / nvidia-smi 不可用），融合走 CPU 多核"
        elif info["cuda"] and not info["name"]:
            info["name"] = "CUDA 环境可用（cuPy）"
        _GPU_CACHE = dict(info)
        return info

    # ---------- 算法透传 ----------
    def depth_to_points(self, depth, mms=1.0, rgb=None):
        return cloudmath.depth_to_points(depth, mms, rgb=rgb)

    def save_ply(self, path, pts, colors=None):
        return cloudmath.save_ply(path, pts, colors=colors)

    def load_ply(self, path, with_color=False):
        return cloudmath.load_ply(path, with_color=with_color)


class _Cancelled(Exception):
    pass


def _cancellable(cancel_evt, kw):
    """把 cancel 事件包进 on_progress：每帧回调时检查取消。"""
    orig = kw.get("on_progress")

    def wrapped(stage, pct, msg):
        if cancel_evt.is_set():
            raise _Cancelled()
        if orig:
            orig(stage, pct, msg)
    kw["on_progress"] = wrapped
    return kw
