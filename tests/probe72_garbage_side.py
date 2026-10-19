# -*- coding: utf-8 -*-
"""probe72 预览垃圾带方位 —— 证实 v0.3.1 方向纠正后垃圾带跑到右缘

背景：v0.3.1 把数据方向改成"正常方向（无镜像）"（深度不再翻转、RGB 翻一次）。
但 shell._pv_display_depth 仍**硬编码裁左缘 21 列**（d[:, 21:]）。若垃圾带实际在
右缘，则：裁掉的是真实数据，右缘 21 列垃圾带（恒值 1313 → LUT 亮绿）留在画面上
→ 用户看到"深度预览右缘多出一条没有内容的竖线"。

判据（真机，只读）：
  1. 原始 640×480 深度：左缘 21 列 / 右缘 21 列的"恒值 1313"占比
  2. 裁左 21 后，新右缘是否仍是垃圾带（整列恒值）
  3. 按 LUT 渲染该列的显示颜色 → 是否亮绿（≈ #90fa42）

用法：python tests/probe72_garbage_side.py
"""
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.contracts import (CROP_COL0, _GARBAGE_V, detect_garbage_side,   # noqa: E402
                            detect_phantom_side)
from core.theme import LUT, render_depth_vis                              # noqa: E402
from modules.device.module import AstraLink, decode_frame                 # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'✓' if ok else '✗'} {name}" + (f"  [{detail}]" if detail else ""))


def grab_depth(timeout=12.0):
    """连设备抓一帧原始深度（640×480 uint16 shift）。"""
    link = AstraLink()
    ok, msgs = link.connect()
    if not ok:
        print("设备连接失败:", str(msgs)[:160])
        return None
    ok, msgs = link.ensure_ready()
    if not ok:
        print("设备就绪失败:", str(msgs)[:160])
        return None
    frame = None
    t0 = time.time()
    while time.time() - t0 < timeout:
        raw = link.grab_frame(timeout=1.0)
        if not raw:
            continue
        try:
            dep = decode_frame(raw)
        except Exception:
            continue
        if isinstance(dep, np.ndarray) and dep.ndim == 2:
            frame = dep
            break
    try:
        link.stop_reader()
        link.ir_off()
        if link.dev is not None:
            import usb.util
            usb.util.dispose_resources(link.dev)
    except Exception:
        pass
    return frame


def main():
    dep = grab_depth()
    if dep is None:
        print("未取得深度帧——设备被占用或未连接")
        return 2
    print(f"原始帧 shape={dep.shape} dtype={dep.dtype}")

    left = float((dep[1:, :CROP_COL0] == _GARBAGE_V).mean())
    right = float((dep[1:, -CROP_COL0:] == _GARBAGE_V).mean())
    print(f"左缘 21 列恒值占比 = {left:.3f} | 右缘 21 列恒值占比 = {right:.3f}")

    side = detect_garbage_side(dep)
    print("detect_garbage_side →", side)
    check("垃圾带方位可判定（非 None）", side in ("L", "R"), str(side))
    check("垃圾带不在左缘（预览裁左边是错的）", side == "R" or left < 0.5,
          f"left={left:.2f} right={right:.2f}")

    # 现状：预览固定裁左 21 列
    shown = np.ascontiguousarray(dep[:, CROP_COL0:])
    tail = shown[:, -CROP_COL0:]
    tail_ratio = float((tail[1:] == _GARBAGE_V).mean())
    print(f"裁左 21 后的新右缘，恒值 {_GARBAGE_V} 占比 = {tail_ratio:.3f}")
    check("裁左 21 后右缘仍有垃圾带（= 用户看到的竖线）", tail_ratio > 0.5,
          f"{tail_ratio:.2f}")

    # 该列渲染出来的颜色
    vis = render_depth_vis(shown, gray=False, dmin=0.0, dmax=2500.0)
    last = vis[:, -1].mean(axis=0).astype(int)
    print("新右缘渲染色 RGB =", tuple(last.tolist()))
    g_channel_dominant = last[1] > 180 and last[0] < 180 and last[2] < 120
    check("该列渲染为亮绿（用户截图里的绿色竖条）", g_channel_dominant,
          f"rgb={tuple(last.tolist())}")

    # 正确做法：按方位裁
    if side == "R":
        fixed = np.ascontiguousarray(dep[:, :-CROP_COL0])
    elif side == "L":
        fixed = np.ascontiguousarray(dep[:, CROP_COL0:])
    else:
        fixed = dep
    fixed_tail = float((fixed[1:, -CROP_COL0:] == _GARBAGE_V).mean())
    fixed_head = float((fixed[1:, :CROP_COL0] == _GARBAGE_V).mean())
    check("按方位裁切后两侧都不再是垃圾带",
          fixed_tail < 0.3 and fixed_head < 0.3,
          f"L={fixed_head:.2f} R={fixed_tail:.2f}")

    ph = detect_phantom_side(fixed)
    print("裁切后幻影列 →", ph)

    # ---- 修复后：预览函数必须两侧都不留垃圾 ----
    import shell as sh
    shown_fixed = sh._pv_display_depth(dep)
    print("_pv_display_depth 开镜像前 shape =", shown_fixed.shape)
    head_g = float((shown_fixed[1:, :6] == _GARBAGE_V).mean())
    tail_g = float((shown_fixed[1:, -6:] == _GARBAGE_V).mean())
    check("修复后预览左右缘都没有垃圾带",
          head_g < 0.2 and tail_g < 0.2, f"L={head_g:.2f} R={tail_g:.2f}")
    check("修复后预览画幅仍为 619 宽", shown_fixed.shape[1] == 619,
          str(shown_fixed.shape))

    # 准星必须落在显示画幅内，且与真实主点一致（裁右 → 主点不左移）
    from core import cloudmath as _cm
    cx, cy = sh._pv_crosshair(dep)
    print(f"准星显示坐标 = ({cx:.1f}, {cy:.1f})；主点 CX={_cm.CX}")
    if side == 'R':
        check("裁右时准星不减 21（主点不左移）", abs(cx - _cm.CX) < 0.6, f"{cx:.1f}")
    elif side == 'L':
        check("裁左时准星左移 21", abs(cx - (_cm.CX - CROP_COL0)) < 0.6, f"{cx:.1f}")
    check("准星在画幅内", 0 <= cx < shown_fixed.shape[1], f"{cx:.1f}")

    # 顶行也必须清掉（整行恒值 1313 → 画面顶边一条亮绿细线）
    row0_g = float((shown_fixed[0, :] == _GARBAGE_V).mean())
    row1_g = float((shown_fixed[1, :] == _GARBAGE_V).mean())
    check("修复后顶行垃圾已清", row0_g < 0.1, f"row0={row0_g:.2f} row1={row1_g:.3f}")
    vis_top = render_depth_vis(shown_fixed, gray=False, dmin=0.0, dmax=2500.0)
    top = vis_top[0].mean(axis=0).astype(int)
    top_green = top[1] > 180 and top[0] < 180 and top[2] < 120
    check("修复后顶行渲染不是亮绿", not top_green, f"rgb={tuple(top.tolist())}")

    # 渲染出的右缘不能再是亮绿
    vis2 = render_depth_vis(shown_fixed, gray=False, dmin=0.0, dmax=2500.0)
    last2 = vis2[:, -1].mean(axis=0).astype(int)
    green2 = last2[1] > 180 and last2[0] < 180 and last2[2] < 120
    check("修复后右缘渲染不再是亮绿竖条", not green2, f"rgb={tuple(last2.tolist())}")

    ok = all(x[1] for x in results)
    print(f"\n{sum(1 for x in results if x[1])}/{len(results)} 断言通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())