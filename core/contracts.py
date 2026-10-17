# -*- coding: utf-8 -*-
"""AstraForge 核心契约：模块间只认这些数据类型与协议，禁止直接 import 彼此。

设计红线（可升级/可更换的地基）：
- 模块输入输出一律是这里的数据类；换实现（如 fusion 从 ICP 换 Open3D）
  只要契约不变，pipeline 与其他模块零改动。
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

import numpy as np


@dataclass
class DepthFrame:
    """一帧深度图（相机系 shift 值，640x480 为设备原生）。"""
    data: np.ndarray                # (H, W) uint16
    index: int = 0
    t: float = 0.0


@dataclass
class RgbFrame:
    """一帧 RGB 图。"""
    data: np.ndarray                # (H, W, 3) uint8 RGB
    t: float = 0.0


@dataclass
class PointCloud:
    """点云（单位 mm）。colors 可选（D2C 顶点色）。"""
    points: np.ndarray              # (N, 3) float64
    colors: Optional[np.ndarray] = None   # (N, 3) uint8
    meta: dict = field(default_factory=dict)


@dataclass
class DeviceStatus:
    connected: bool = False
    streaming: bool = False
    info: str = ""


@dataclass
class ModuleContext:
    """模块 setup 时拿到的能力包（模块不直接碰主程序）。"""
    bus: Any                        # EventBus
    device: Any                     # 设备服务（device 模块注册后注入）
    settings: dict                  # 全局配置（标定值等，可热改）
    log: Callable[[str, bool], None]
    data_dir: Any                   # Path：模块可写目录（外置，OTA 关键）
    root_dir: Any                   # Path：软件根目录
    ui_root: Any = None             # tkinter 主窗口（UI 模块装配时注入；开子窗口用）


class Module(Protocol):
    """功能模块协议。pipeline 只跟这个接口打交道。"""
    name: str
    version: str

    def setup(self, ctx: ModuleContext) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...


# ---------------- 输出帧裁剪规格（BUG-009 定案 / BUG-012 方位自适应） ----------------
# 背景：传感器原始输出含固定垃圾区（顶行 row0 + 深度某侧缘 21 列，恒值 1313，
# 跨会话 100% 恒定）——曾使导出点云出现 10,699 个假点的"假边框"，融合链路
# 也曾把旧帧垃圾带进产物（9,842 假点/5.1%）。
# 口径（用户定案）：**只影响输出端**（保存/导出/融合文件）；**显示端保持原画幅**。
#
# 方位（2026-10-16 全量取证）：垃圾带方位=**录制期发布方向**，存档里两种并存：
#   · 10-15 21:39 之前（含 10-13/10-14/10-15 早）：发布方向 flip(rawD)，在左缘(L)；
#   · 10-15 21:39 起（方向链 B 定案后）：直发，在右缘(R)；新录制帧同样 R。
# 因此裁剪**按帧自适应判向**（检测恒值 1313 整列在哪一侧），不得盲裁固定边。
# 最终画幅 619×479：深度与彩图尺寸一致、可直接叠加/对照。
CROP_ROW0 = 1            # 顶部垃圾行数（两代一致）
CROP_COL0 = 21           # 垃圾列数（21 列，两代一致）
_GARBAGE_V = 1313        # 垃圾带恒值（设备级、跨会话恒定）
_GARBAGE_RATIO = 0.9     # 整列恒值占比阈值（实测垃圾列 ≥0.98，真实列 ~0）

# ---- 边缘幻影列（BUG-013，2026-10-16 实测定案）----
# 传感器最外一列（发布向=最右缘；原生向=最左缘）为设备边缘伪数据：整列满
# "有效"、内邻缺失时它仍出数，且值系统性偏离（比相邻真实面近约 300-400mm）。
# 危害：预览右缘一条无中生有的竖条；导出点云里一列 479 点、转 90° 成
# "一片无细节小点云"（用户实测反馈）。判据（全量 8 会话命中 8、合成帧 0 误报）：
#   边缘列有效率 ≥0.97 且 比内邻 5 列均值高 ≥0.07 且 独有行（内邻全空）≥2%。
# 处置：输出/显示均把该列清为无效（画幅/内参不变，不裁掉——避免尺寸级联）。
_PHANTOM_VALID_MIN = 0.97
_PHANTOM_DELTA_MIN = 0.07
_PHANTOM_UNIQ_MIN = 0.02


def detect_phantom_side(dep):
    """探测边缘幻影列：返回 'L'/'R'（该侧最外列是幻影）/ None（无）。
    只取边缘 6 列计算（显示热路径每帧调用，须廉价）。"""
    import numpy as np
    if dep is None or getattr(dep, "ndim", None) != 2 or dep.shape[1] < 50:
        return None
    a = dep[1:, :] if dep.shape[0] > 1 else dep
    for side in ('L', 'R'):
        blk = a[:, :6] if side == 'L' else a[:, -6:]
        v = (blk > 0) & (blk < 4000)
        col = v[:, 0] if side == 'L' else v[:, -1]
        inner = v[:, 1:] if side == 'L' else v[:, :-1]
        ev = float(col.mean())
        if ev < _PHANTOM_VALID_MIN:
            continue
        dlt = ev - float(inner.mean())
        if dlt < _PHANTOM_DELTA_MIN:
            continue
        if float((col & ~inner.any(axis=1)).mean()) < _PHANTOM_UNIQ_MIN:
            continue
        return side
    return None


def detect_garbage_side(dep):
    """探测固定垃圾带方位：返回 'L'（左缘 21 列恒 1313）/ 'R'（右缘）/
    None（无量级恒值带，如已裁剪帧/合成数据；或两侧同强=平坦场景，不裁防误伤）。"""
    import numpy as np
    if dep is None or getattr(dep, "ndim", None) != 2 or dep.shape[1] < 100:
        return None
    a = dep[1:, :]                       # 去顶行后看列（顶行使垃圾列占比略降）
    left = (a[:, :CROP_COL0] == _GARBAGE_V).mean()
    right = (a[:, -CROP_COL0:] == _GARBAGE_V).mean()
    # 设备垃圾特征：单侧强（≥0.9）、对侧弱（≤0.5）——两侧同强视为真实平坦场景，
    # 不裁（宁可不净，不可误伤真实数据）。
    if left >= _GARBAGE_RATIO and right <= 0.5:
        return 'L'
    if right >= _GARBAGE_RATIO and left <= 0.5:
        return 'R'
    return None


def crop_for_output(dep=None, rgb=None):
    """输出端裁剪（保存/导出/融合用；显示端不用）。返回 (dep', rgb')，None 原样返回。

    方位自适应（BUG-012）：检测固定垃圾带（恒值 1313）在左缘还是右缘——深度与
    RGB（同向对齐、同列）去**同侧** 21 列 + 顶行；检测不到（已裁剪帧 / 合成数据）
    原样返回。整列恒值特征强（垃圾列占比 ≥0.98 vs 真实列 ~0），两代会话均覆盖。

    边缘幻影列（BUG-013）：裁剪后标准画幅（479×619）上再检测"边缘幻影列"
    （传感器最外列伪数据：整列满有效、内邻缺失时仍出数）→ 清为无效。
    画幅与内参不变（619 宽不动），只是该列不再进 PNG/PLY/融合。

    注意：裁剪改变帧尺寸后，**反投影消费方必须同步主点**——点云/融合/测距
    统一走 `cloudmath.cxcy_for_shape(shape, col0=...)` 按裁剪量取主点（BUG-011），
    不得硬编码主点（出厂基准见 cloudmath CX/CY，BUG-015）；右缘裁剪（老 R 帧）主点不左移，
    col0 显式传 0。"""
    side = None
    if dep is not None and getattr(dep, "shape", None) is not None and dep.shape[:2] == (480, 640):
        side = detect_garbage_side(dep)
        if side == 'L':
            dep = dep[CROP_ROW0:, CROP_COL0:]
        elif side == 'R':
            dep = dep[CROP_ROW0:, :-CROP_COL0]
    if rgb is not None and getattr(rgb, "shape", None) is not None and rgb.shape[:2] == (480, 640):
        if side == 'L':
            rgb = rgb[CROP_ROW0:, CROP_COL0:]
        elif side == 'R':
            rgb = rgb[CROP_ROW0:, :-CROP_COL0]
    # BUG-013：标准输出画幅上的边缘幻影列 → 清无效（画幅/内参不动）
    if dep is not None and getattr(dep, "shape", None) is not None and dep.shape[:2] == (479, 619):
        try:
            ph = detect_phantom_side(dep)
            if ph == 'R':
                dep = dep.copy()
                dep[:, -1] = 0
            elif ph == 'L':
                dep = dep.copy()
                dep[:, 0] = 0
        except Exception:
            pass
    return dep, rgb
