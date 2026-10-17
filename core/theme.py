# -*- coding: utf-8 -*-
"""主题与色带（core 稳定层，viewer3d/preview 等渲染模块共享）。"""
import numpy as np

from core.cloudmath import CX, CY   # 出厂标定光轴/内参唯一源（BUG-015）

BG = "#16161e"          # 窗口底
PANEL = "#1e1e2a"       # 面板/顶栏
BTN = "#26263a"         # 按钮
BTN_HOVER = "#34344e"
FG = "#e8e9ee"          # 主文字
MUTED = "#9aa0b0"       # 次文字
ACCENT = "#00d4ff"      # 强调（青）
OK = "#3fd68c"          # 成功（绿）
WARN = "#ffb454"        # 警告（黄）
ERR = "#ff6b6b"         # 错误（红）
CANVAS_BG = "#101018"
INVALID_PX = (24, 24, 30)   # 无效像素色
DISP_MAX = 2500         # 默认显示上限（shift）


def make_lut():
    """深度伪彩色带（turbo 风格：蓝=近 → 红=远）。"""
    def q(c):
        return tuple(int(v * 255 + 0.5) for v in c)
    stops = [q((0.0, 0.0, 0.2)), q((0.0, 0.4, 1.0)), q((0.0, 0.9, 0.8)),
             q((0.5, 1.0, 0.3)), q((1.0, 0.9, 0.0)), q((1.0, 0.4, 0.0)),
             q((1.0, 0.0, 0.0))]
    n = 256
    out = np.zeros((n, 3), dtype=np.uint8)
    seg = n // (len(stops) - 1)
    for i in range(len(stops) - 1):
        a, b = np.array(stops[i]), np.array(stops[i + 1])
        for j in range(seg):
            t = j / max(seg - 1, 1)
            out[i * seg + j] = (a * (1 - t) + b * t).astype(np.uint8)
    return out


LUT = make_lut()
GRAY_LUT = np.stack([np.arange(256, dtype=np.uint8)] * 3, axis=1)

# 深度画面几何常量（渲染共用）；CX/CY = 出厂标定光轴——**唯一源** core/cloudmath.py
# （BUG-015；不再复制副本，避免双份漂移）

W, H = 640, 480


def render_depth_vis(depth, gray=False, dmin=0.0, dmax=DISP_MAX, crosshair=None):
    """深度帧 → 显示图（LUT/灰度 + 无效暗色 + 中心十字）。

    纯 numpy 实现（core 层，无 tkinter 依赖）——preview 模块与
    HTTP 壳（shell.py）共用；HTTP 线程里严禁 import tkinter（线程亲和性）。
    crosshair=(cx, cy)：十字准星位置（显示坐标系）；None=用默认光轴 (CX, CY)。
    画面尺寸按输入自适应（支持裁剪后的显示副本，如 BUG-009 的 619 宽）。
    """
    vis = np.empty((depth.shape[0], depth.shape[1], 3), dtype=np.uint8)
    valid = depth > 0
    span = max(dmax - dmin, 1.0)
    g = np.clip((depth.astype(np.float32) - dmin) / span * 255.0, 0, 255).astype(np.uint8)
    vis[:] = (GRAY_LUT if gray else LUT)[g]
    vis[~valid] = INVALID_PX
    cxi, cyi = (int(crosshair[0]), int(crosshair[1])) if crosshair else (int(CX), int(CY))
    h, w = depth.shape
    if 0 <= cyi < h and 0 <= cxi < w:
        vis[max(cyi - 1, 0):cyi + 1, max(cxi - 14, 0):min(cxi + 14, w)] = (255, 255, 255)
        vis[max(cyi - 14, 0):min(cyi + 14, h), max(cxi - 1, 0):cxi + 1] = (255, 255, 255)
    return vis
