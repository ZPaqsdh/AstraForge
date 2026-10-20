# -*- coding: utf-8 -*-
"""AstraForge 桌面壳 v1 —— React UI（本地 HTTP + Edge app 窗口）+ 真模块管线。

架构（2026-10-14 定）：
  Python 后端 = 模块化管线（core/ + modules/，原样保留）
  本地 HTTP server：静态 UI（ui-web/dist）+ /api/*（前后端全走 fetch）
  Edge 应用模式窗口（固定系统 Edge 显式路径 + 独立 profile，不绑用户默认浏览器）
  软件与设备绑定：窗口关闭 → Bridge.shutdown → pipeline.stop_all（device 关红外）

用法：python shell.py [--backend edge|webview] [--hash 页名] [--selftest]
"""
import argparse
import functools
import http.server
import io
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

APP_VERSION = "0.3.6"

# 应用级更新源（与 installer/setup_core.py 的 DEFAULT_UPDATE_URL 保持一致；
# 测试可用 AF_UPDATE_URL 覆盖）。update.json 由 Release 的 latest/download 恒定入口提供。
UPDATE_URL = (os.environ.get("AF_UPDATE_URL", "").strip()
              or "https://github.com/ZPaqsdh/AstraForge/releases/latest/download/update.json")

# QtWebEngine flags（必须在 Qt 初始化前设置）：
#   --no-sandbox    ：QtWebEngineProcess 子进程在受限环境必需（否则 loadFinished=False）
#   --no-proxy-server：本机系统代理会把 127.0.0.1 请求也转发（页面加载失败白屏）
#   --disable-gpu   ：软件渲染（稳定 + 原生截图可抓）
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    + " --no-sandbox --no-proxy-server --proxy-bypass-list=<-loopback>"
      " --disable-gpu").strip()

# ---------------- 帧流缓存（服务端渲染 JPEG，请求降载） ----------------
_frame_cache = {"depth": (0.0, None), "rgb": (0.0, None)}
_frame_lock = threading.Lock()
_frame_render_lock = threading.Lock()      # 渲染互斥：并发同 kind 请求合并为一次渲染

# ---------------- 预览镜像/翻面（2026-10-16 定案 B） ----------------
# 口径（用户拍板 B）：**全链统一"镜像向"**（照镜子——人在哪边、画面/文件里也在哪边）。
#   数据层（保存帧/导出点云/融合）与预览显示**同向**：RGB 直发原始 + 深度翻一次
#   （device 模块），预览直出即与出图一致。
# 「镜像 (M)」= 预览翻面对比开关（显示层，不影响数据）：
#   开（默认）= 直出（与出图同向）；关 = 显示端左右翻面（对比查看传感器原始向）。
_preview_mirror = {"on": False}


def _pv_flip(arr):
    """预览镜像（仅显示层）：开关打开时左右翻转显示副本，不改数据数组。

    2026-10-19 纠正（BUG-019）：保存/导出/点云/融合一律是正常方向（无镜像）；
    「镜像」只是给用户预览观察用的显示开关，默认关闭。
    """
    if arr is None or not _preview_mirror["on"]:
        return arr
    import numpy as _np
    return _np.ascontiguousarray(arr[:, ::-1])


# BUG-009（2026-10-16 查明）：深度原始输出含**固定垃圾带**（恒值 1313）：顶行 + 某侧缘
# 21 列，跨会话 100% 恒定，非场景内容。
# 口径（用户定案）：**显示端也要裁掉它**（否则预览上就是一条亮色竖条，BUG-021），
# 输出端同规格（core.contracts.crop_for_output → 保存/导出文件 619×479）。
# **方位按帧自适应**（BUG-012）：垃圾带可能在某侧——`detect_garbage_side` 判向，
# 严禁写死左/右（v0.3.1 改方向后方位变了，写死左边直接踩坑，见 BUG-021）。
_PV_CROP_L = 21
_PV_RAW_W = 640          # 原始深度宽度（裁剪前）


def _pv_crop_side(d):
    """垃圾带方位（'L'/'R'）——按帧自适应，检测不出时按当前数据方位兜底 'R'。

    BUG-021（2026-10-20）：v0.3.1 把数据方向改成"正常方向（无镜像）"后，深度不再翻转，
    垃圾带随之落到**右缘**；而预览仍硬编码裁左 21 列 → 真实数据被裁掉、右缘 21 列垃圾
    （恒值 1313 → LUT 亮绿）留在画面上，即用户看到的"多出一条没有内容的竖线"。
    probe72 实测：左缘恒值占比 0.000 / 右缘 1.000 → side='R'。

    兜底 'R' 的理由：**画幅必须恒为 619 宽**（前端坐标/内参/测距都按 619 算）。
    场景太平坦导致 detect 判不出时，若原样不裁，画幅会在 640/619 之间跳，坐标立刻漂。
    当前数据方位（不翻转）就是 R，故兜底 R；老 L 帧有强垃圾带特征，一定判得出来。
    """
    if d is None or getattr(d, "ndim", 0) != 2 or d.shape[1] != _PV_RAW_W:
        return None
    try:
        from core.contracts import detect_garbage_side
        return detect_garbage_side(d) or 'R'
    except Exception:
        return 'R'


def _pv_display_depth(d):
    """预览用深度：清顶行垃圾 → 按方位裁掉侧缘垃圾带 21 列 → 清边缘幻影列
    → 按镜像开关翻面。

    仅作用于显示副本，数据数组不改；坐标（悬停/测距/准星）与屏幕所见 1:1 对应。

    - 顶行：整行恒值 1313（BUG-009），**清为无效而不裁**——保持 480 高，
      cy 不平移，避免内参级联（BUG-011 的坑）；1px 深线肉眼不可见。
    - 侧缘：裁 21 列，方位自适应（`_pv_crop_side`，BUG-021）。
    - 幻影列：两侧都查（BUG-013），清该列为无效，不再裁。
    """
    if d is None or getattr(d, "ndim", 0) != 2:
        return d
    import numpy as _np
    d = _np.asarray(d)
    from core.contracts import CROP_COL0, detect_garbage_side, detect_phantom_side

    if d.shape[1] == _PV_RAW_W:
        side = _pv_crop_side(d)
        if side == 'L':
            d = _np.ascontiguousarray(d[:, CROP_COL0:])
        elif side == 'R':
            d = _np.ascontiguousarray(d[:, :-CROP_COL0])
        else:
            d = _np.ascontiguousarray(d)

    if d.shape[1] == _PV_RAW_W - CROP_COL0:
        ph = detect_phantom_side(d)
        if ph is not None or _pv_top_garbage(d):
            d = d.copy()
            if ph == 'R':
                d[:, -1] = 0
            elif ph == 'L':
                d[:, 0] = 0
            if _pv_top_garbage(d):
                d[0, :] = 0
    return _pv_flip(d)


def _pv_top_garbage(d):
    """顶行是否整行垃圾（恒值 1313 占绝大多数）——设备级特征，跨会话恒定。"""
    try:
        from core.contracts import _GARBAGE_V
        return float((d[0, :] == _GARBAGE_V).mean()) > 0.6
    except Exception:
        return False


def _pv_crosshair(depth):
    """十字准星位置（显示坐标）：光轴（出厂主点 CX/CY，BUG-015）映射到显示画幅。

    裁左 → 主点左移 21；裁右 → 主点不动（col0=0）。显示端不裁行 → cy 不平移。
    """
    from core import cloudmath as _cm
    side = _pv_crop_side(depth)
    col0 = _PV_CROP_L if side == 'L' else 0
    cx0 = _cm.CX - col0
    if _preview_mirror["on"]:
        cx0 = ((_PV_RAW_W - _PV_CROP_L - 1) - cx0)
    return (cx0, _cm.CY)


# ---------------- 采集质量可视化（TODO-016） ----------------
# 对标 Revo Scan / Creality：开扫前先看「距离对不对、覆盖够不够」。
# 最佳距离区间与「3D 扫描」页提示一致（0.5~1.5m）；分区阈值可随标定值线性缩放（shift=mm）。
_QUAL_NEAR_MAX = 500.0      # < 太近
_QUAL_FAR_MIN = 1500.0      # > 太远
_QUAL_GRID = (6, 8)         # 质量色谱网格（行×列）


def _frame_quality(depth, mms=1.0):
    """单帧采集质量指标（纯计算，无副作用）：距离分区 / 有效覆盖率 / 分区质量网格。

    深度按**显示画幅**解析（裁垃圾带 + 清幻影列 → 与屏幕所见 1:1），故前端网格叠加
    无需再做坐标换算。降采样 ×2 提速（240×310，精度足够）。
    返回 None = 无画面；否则 dict（含 d_med / valid_pct / zone / zone_pct / grid / light / hint）。
    """
    if depth is None or getattr(depth, "ndim", 0) != 2:
        return None
    d = _pv_display_depth(depth)
    if d is None or d.ndim != 2 or d.size == 0:
        return None
    import numpy as _np
    sub = _np.asarray(d)[::2, ::2].astype(_np.float32)
    valid = sub > 0
    H, W = sub.shape
    gy = _np.linspace(0, H, _QUAL_GRID[0] + 1).astype(int)
    gx = _np.linspace(0, W, _QUAL_GRID[1] + 1).astype(int)
    grid = [[float(valid[gy[i]:gy[i + 1], gx[j]:gx[j + 1]].mean() * 100.0)
             for j in range(_QUAL_GRID[1])] for i in range(_QUAL_GRID[0])]
    n = int(valid.sum())
    if n == 0:
        return {"d_med": 0.0, "valid_pct": 0.0, "zone": "none",
                "zone_pct": {"near": 0.0, "best": 0.0, "far": 0.0},
                "grid": grid, "light": "red",
                "hint": "画面全无效：检查镜头是否被挡 / 物体是否在 0.5~1.5 米内",
                "range": [_QUAL_NEAR_MAX, _QUAL_FAR_MIN]}
    z = sub[valid].astype(_np.float64) * float(mms)
    d_med = float(_np.median(z))
    # 中央区（各边内缩 15%）有效占比 = 物体覆盖质量的代理指标
    r0, r1 = int(H * 0.15), max(int(H * 0.85), int(H * 0.15) + 1)
    c0, c1 = int(W * 0.15), max(int(W * 0.85), int(W * 0.15) + 1)
    cen = valid[r0:r1, c0:c1]
    valid_pct = float(cen.mean() * 100.0) if cen.size else 0.0
    rng = [_QUAL_NEAR_MAX, _QUAL_FAR_MIN]
    if rng[1] < rng[0]:
        rng = [rng[1], rng[0]]
    zn = float(((z < rng[0]).mean()) * 100.0)
    zf = float(((z > rng[1]).mean()) * 100.0)
    zb = max(0.0, 100.0 - zn - zf)
    zone = "near" if d_med < rng[0] else ("far" if d_med > rng[1] else "best")
    if zone != "best":
        light, hint = "red", ("距离太近：退到 0.5~1.5 米" if zone == "near"
                             else "距离太远：靠近到 0.5~1.5 米")
    elif valid_pct < 35.0:
        light, hint = "red", "覆盖不足：正对目标、避开强反光/深黑吸光面"
    elif valid_pct < 60.0:
        light, hint = "yellow", "覆盖偏低：可采，建议多角度补扫"
    else:
        light, hint = "green", "距离与覆盖良好，可以直接采"
    return {"d_med": round(d_med, 1), "valid_pct": round(valid_pct, 1), "zone": zone,
            "zone_pct": {"near": round(zn, 1), "best": round(zb, 1), "far": round(zf, 1)},
            "grid": [[round(v, 1) for v in row] for row in grid],
            "light": light, "hint": hint, "range": rng}

# 帧率采样窗口（api_state / api_stats / RGB 各自独立）。
# 2026-10-15 修复：曾全部共享一个窗口——两接口轮询撞车（间隔 <0.25s）时，后到者
# 取样窗口太短直接返回 0，读数周期性闪 0（用户实测反馈的"帧率一直在跳"根因）。
_fps_meter_state = {"t": 0.0, "i": 0, "v": 0.0}
_fps_meter_stats = {"t": 0.0, "i": 0, "v": 0.0}
_fps_meter_rgb = {"t": 0.0, "i": 0, "v": 0.0}


def _rate_from_counter(cur, meter, min_gap=0.25):
    """通用计数器速率（次/秒）。独立窗口；窗口太近（<min_gap）返回上次值而非 0。"""
    now = time.time()
    t0, i0 = meter["t"], meter["i"]
    if t0 and now - t0 < min_gap:
        return meter["v"]
    v = (cur - i0) / (now - t0) if t0 else 0.0
    meter["t"], meter["i"], meter["v"] = now, cur, v
    return v


def _calc_fps(cap, meter):
    """深度采集帧率（cap.index 差分）。"""
    if cap is None:
        return 0.0
    return _rate_from_counter(cap.index, meter)


def _jpeg(arr, quality=72, scale=1.0):
    from PIL import Image
    img = Image.fromarray(arr)
    if scale and scale != 1.0:          # 降采样：预览够用，编码耗时减 2-3 倍
        img = img.resize((max(1, int(img.width * scale)),
                          max(1, int(img.height * scale))), Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


_render_cache = {}


def _get_render_preview():
    """渲染函数（core.theme，纯 numpy）——HTTP 线程里严禁 import tkinter
    （Tcl 线程亲和性：Qt 环境下会死锁挂起，曾导致 /api/frame 永不返回）。"""
    if "rp" not in _render_cache:
        from core.theme import render_depth_vis
        _render_cache["rp"] = render_depth_vis
    return _render_cache["rp"]


class ApiHandler(http.server.SimpleHTTPRequestHandler):
    """一体化 server：静态 UI + /api/*（前后端统一走 HTTP，浏览器可直调）。"""
    bridge = None

    def log_message(self, *a):
        pass

    def end_headers(self):
        # 静态文件同样禁缓存（开发期 Edge 曾缓存旧 index.html → 旧 JS）
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._api("GET")
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._api("POST")
        else:
            self.send_error(404)

    def _send_json(self, obj):
        out = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(out)

    def _send_jpeg(self, data):
        self._send_bytes(data, "image/jpeg")

    def _send_bytes(self, data, ctype="application/octet-stream"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _api(self, method):
        path = self.path.split("?")[0]
        name = path[5:].strip("/")
        query = {}
        if "?" in self.path:
            from urllib.parse import unquote
            for kv in self.path.split("?", 1)[1].split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    query[k] = unquote(v)
        body = {}
        if method == "POST":
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                body = json.loads(raw or b"{}")
            except Exception:
                body = {}
        try:
            t0 = time.time()
            result = self.bridge.call(name, method, query, body)
            if os.environ.get("ASTRAFORGE_HTTP_LOG"):
                dt = (time.time() - t0) * 1000
                if name != "heartbeat":      # 心跳太吵，静音
                    print(f"[http] {method} /{name} -> {dt:.0f}ms", flush=True)
            if isinstance(result, tuple) and result[0] == "__jpeg__":
                self._send_jpeg(result[1])
            elif isinstance(result, tuple) and result[0] == "__file__":
                self._send_bytes(result[1], result[2] if len(result) > 2 else "application/octet-stream")
            else:
                self._send_json({"ok": True, "data": result})
        except Exception as e:
            if os.environ.get("ASTRAFORGE_HTTP_LOG"):
                import traceback
                traceback.print_exc()
            self._send_json({"ok": False, "error": str(e)[:200]})


def _selfcheck(port):
    import socket as _sk
    try:
        c = _sk.create_connection(("127.0.0.1", port), timeout=2)
        c.sendall(b"GET /api/ping HTTP/1.0\r\n\r\n")
        d = c.recv(120)
        c.close()
        return "ok " + d[:40].decode("utf-8", "replace").replace("\r\n", " ")
    except Exception as e:
        return f"FAIL {type(e).__name__}: {e}"


def _placeholder(text):
    """无帧画面时的占位图（带提示文字——用户能立刻分辨'设备没连上'与'软件坏了'）。"""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (640, 480), (24, 24, 30))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 22)
    except Exception:
        font = ImageFont.load_default()
    d.text((320, 240), text, fill=(150, 150, 160), font=font, anchor="mm")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()


class _ThreadingServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """并发 server（单线程曾被测试/轮询请求阻塞 → 帧流饿死）。"""
    daemon_threads = True
    allow_reuse_address = True


def start_server(directory: Path, bridge):
    """本地 HTTP server（UI 静态 + API 一体，多线程）。返回 (port, httpd)。"""
    ApiHandler.bridge = bridge
    handler = functools.partial(ApiHandler, directory=str(directory))
    httpd = _ThreadingServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True,
                     name="ui-server").start()
    return port, httpd


def find_edge():
    for p in (r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
              r"C:/Program Files/Microsoft/Edge/Application/msedge.exe"):
        if Path(p).exists():
            return p
    return None


def run_qt_window(url: str, bridge, snap_path=None, snap_delay=8.0,
                  size="1600x950"):
    """PySide6 / QtWebEngine 内置浏览器窗口（开源 Chromium 内核，完全内置）。

    —— 不依赖系统任何浏览器；窗口关闭 → exec 返回 → 调用方统一收尾。
    snap_path：自检用——窗口显示 N 秒后原生截图（view.grab，绕开 BitBlt 抓不到
    Chromium 合成层的问题）并自动关窗。
    """
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWidgets import QApplication, QMainWindow
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEnginePage
    import sys as _sys

    app = QApplication.instance() or QApplication(_sys.argv[:1])

    # 单实例锁：双开会抢 USB 设备/端口 —— 提示并退出（锁随进程结束自动释放）
    from PySide6.QtCore import QSharedMemory
    from PySide6.QtWidgets import QMessageBox
    _inst_lock = QSharedMemory("AstraForge-SingleInstance")
    if not _inst_lock.create(1):
        # BUG-025 教训：老大双击了新版本，结果弹这个框、继续用旧窗口（旧界面 + 旧 API），
        # 看起来像"新版本没修好"。所以这里主动把已有窗口拉到前台，并说清楚"它可能不是最新界面"。
        try:
            import ctypes
            hwnd = ctypes.windll.user32.FindWindowW(None, "AstraForge 星铸")
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 9)        # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        QMessageBox.warning(None, "AstraForge 星铸",
                            "软件已经在运行，已为你切到那个窗口。\n\n"
                            "注意：那个窗口是**更早启动的**，界面可能还是旧版本。\n"
                            "要确认版本/看到这次修复：先把它完全关闭，再双击启动。")
        print("[shell] 检测到已有实例，本次启动退出", flush=True)
        return

    web_log = ROOT / "shell_web.log"

    class _LogPage(QWebEnginePage):
        """捕获页面 console（JS 报错是白屏类问题的唯一直接证据）。"""
        def javaScriptConsoleMessage(self, level, message, line, src):
            msg = f"[web:{level.name}] {str(src).split('/')[-1]}:{line} {message}"
            print(msg, flush=True)
            try:
                if web_log.exists() and web_log.stat().st_size > 1_000_000:
                    web_log.write_text("", encoding="utf-8")   # 轮转：超 1MB 清空
                with open(web_log, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass

    class MainWin(QMainWindow):
        def closeEvent(self, e):
            print("[shell] Qt 窗口关闭 → 收尾", flush=True)
            # 3 秒保底（防收尾异常导致进程挂住）
            def _force():
                time.sleep(3.0)
                os._exit(0)
            threading.Thread(target=_force, daemon=True).start()
            e.accept()

    try:
        web_log.write_text("", encoding="utf-8")
    except Exception:
        pass
    win = MainWin()
    win.setWindowTitle("AstraForge 星铸")
    if size:
        # 显式尺寸（测试/排障用）：固定，不设最小限制
        try:
            _w, _h = (int(x) for x in size.lower().split("x"))
        except Exception:
            _w, _h = 1600, 950
        win.resize(_w, _h)
    else:
        # 生产：默认 = 屏幕 92%（封顶 1600x950）居中；最小 1280x800（画面保底），
        # 用户可任意放大（无上限），不能拖到更小（防画面/布局被压坏）
        try:
            scr = app.primaryScreen().availableGeometry()
            dw = min(1600, int(scr.width() * 0.92))
            dh = min(950, int(scr.height() * 0.92))
        except Exception:
            scr, dw, dh = None, 1600, 950
        win.resize(dw, dh)
        win.setMinimumSize(min(1280, dw), min(800, dh))
        if scr is not None:
            try:
                win.move(scr.x() + (scr.width() - dw) // 2,
                         scr.y() + (scr.height() - dh) // 2)
            except Exception:
                pass
        print(f"[shell] 窗口: 默认 {dw}x{dh}（屏幕 {scr.width() if scr else '?'}x"
              f"{scr.height() if scr else '?'}）｜最小 1280x800（可无限放大）", flush=True)
    view = QWebEngineView()
    view.setPage(_LogPage(view))
    view.loadFinished.connect(
        lambda ok: print(f"[web] loadFinished: {ok}", flush=True))
    # 页面 title 变化 → 同步窗口标题
    view.titleChanged.connect(lambda t: win.setWindowTitle(t or "AstraForge 星铸"))
    view.load(QUrl(url))
    win.setCentralWidget(view)

    if snap_path:
        def do_snap():
            # 顺带诊断画面 img 状态（complete / naturalWidth / src）
            view.page().runJavaScript(
                "(function(){var ims=document.querySelectorAll('img');"
                "var out=[];for(var i=0;i<ims.length;i++){var x=ims[i];"
                "out.push([x.complete,x.naturalWidth,x.naturalHeight,"
                "(x.src||'').substring(0,70)].join('|'));}"
                "return out.length?out.join(' ;; '):'no-img';})()",
                lambda r: print(f"[diag] imgs: {r}", flush=True))
            pix = view.grab()
            ok = pix.save(str(snap_path))
            print(f"[shell] snap {'saved' if ok else 'FAILED'}: {snap_path} "
                  f"({pix.width()}x{pix.height()})", flush=True)
            QTimer.singleShot(800, win.close)     # 给诊断回调 0.8s
        QTimer.singleShot(int(snap_delay * 1000), do_snap)

    win.show()
    print("[shell] Qt 窗口已显示（QtWebEngine）", flush=True)
    app.exec()


def _shutdown_and_exit(bridge, label="窗口已关闭"):
    print(f"[shell] {label} → 执行收尾（关红外/停设备）", flush=True)
    try:
        if bridge.pipeline is not None:
            bridge.pipeline.stop_all()
            print("[bridge] shutdown: 管线已收尾（红外已关）", flush=True)
    except Exception as e:
        print(f"[bridge] shutdown 收尾异常: {e}", flush=True)
    os._exit(0)


# ================= 桥接：API → 真模块 =================
class _UpdateWatcher:
    """后台更新检测：启动 4s 后首检 → 每 12h 一次（老大 2026-10-20 口径）。

    语义要点（照老大原话实现）：
    - **打开客户端就检测**：进程起来 4s（等首屏渲染完）后立刻查一次；
    - **每 12 小时一次**：之后按单调时钟每 43200s 一次，避免休眠导致漂移；
    - **关闭后重置**：状态**不落盘**，进程退出即丢；下次启动重新计时并立即检测。
    失败静默（只记状态），连续 ≥3 次才让 UI 显示"检查失败"。
    """

    FIRST_DELAY = 4.0
    INTERVAL = 12 * 3600.0
    FAILS_TO_SHOW = 3

    def __init__(self, bridge=None, first_delay=None, interval=None):
        self._bridge = bridge
        self.first_delay = self.FIRST_DELAY if first_delay is None else float(first_delay)
        self.interval = self.INTERVAL if interval is None else float(interval)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._state = {
            "current": APP_VERSION, "latest": "", "has_update": False,
            "checked_at": "", "next_check_at": "", "error": None, "fails": 0,
            "mode": "installed" if (ROOT.parent / "AstraForge.exe").exists() else "dev",
            "notes_url": "", "payload_url": "", "payload_sha256": "",
            "can_apply": (ROOT.parent / "AstraForge.exe").exists(),
            "first_delay": self.first_delay, "interval": self.interval,
        }

    # ---- 生命周期 ----
    def start(self):
        if os.environ.get("AF_NO_UPDATE_WATCH", "").strip().lower() in ("1", "true", "yes", "on"):
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="update-watch")
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()

    def _loop(self):
        if self._stop.wait(self.first_delay):
            return
        while not self._stop.is_set():
            self.check_now()
            with self._lock:
                self._state["next_check_at"] = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(time.time() + self.interval))
            if self._sleep(self.interval):
                return

    def _sleep(self, seconds: float) -> bool:
        """按单调时钟睡满 seconds（分片，便于 stop 与避免休眠漂移）。"""
        deadline = time.monotonic() + max(0.0, float(seconds))
        while not self._stop.is_set():
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            if self._stop.wait(min(left, 60.0)):
                return True
        return True

    # ---- 状态 ----
    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def absorb(self, result: dict):
        """把「手动检查」的结果并入自动检测状态（避免两套数字打架）。"""
        if not isinstance(result, dict) or not result.get("ok"):
            return
        with self._lock:
            self._state.update(
                current=str(result.get("current") or APP_VERSION),
                latest=str(result.get("latest") or ""),
                has_update=bool(result.get("has_update")),
                checked_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                error=None, fails=0,
                notes_url=str(result.get("notes_url") or ""),
                payload_url=str(result.get("payload_url") or ""),
                payload_sha256=str(result.get("payload_sha256") or ""),
                can_apply=bool(result.get("can_apply")),
                mode=str(result.get("mode") or self._state.get("mode") or "dev"),
            )

    def check_now(self) -> dict:
        """立即检测一次（后台线程与手动接口共用）。返回最新状态。"""
        bridge = self._bridge
        data, err = (None, "更新器未初始化")
        try:
            if bridge is not None:
                data, err = bridge._fetch_update_manifest()
        except Exception as e:  # noqa: BLE001
            data, err = None, f"{type(e).__name__}: {str(e)[:80]}"
        with self._lock:
            if data is None:
                self._state["fails"] = int(self._state.get("fails") or 0) + 1
                self._state["error"] = str(err or "检查失败")
                self._state["checked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                return dict(self._state)
            latest = str(data.get("latest") or "")
            self._state.update(
                current=APP_VERSION,
                latest=latest,
                has_update=_ver_gt(latest, APP_VERSION),
                checked_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                error=None, fails=0,
                notes_url=str(data.get("notes_url") or ""),
                payload_url=str(data.get("payload_url") or ""),
                payload_sha256=str(data.get("payload_sha256") or ""),
            )
            return dict(self._state)


class Bridge:
    """JS ↔ Python 桥接。前端 fetch('/api/xxx') 或 window.pywebview.api.xxx()。"""

    _logs = []            # build_pipeline 注入（模块日志）
    _rgb_status = ["未连接"]
    _beat = {"last": 0.0, "got": False}    # 心跳（窗口存活判定）

    def __init__(self, pipeline=None):
        self.pipeline = pipeline
        self._dev_lock = threading.Lock()
        self._upd_lock = threading.Lock()
        self._upd = {"phase": "idle", "pct": 0, "msg": "", "path": "",
                     "latest": "", "error": None}
        self._scan_cache = (0.0, None)
        self._scan_lock = threading.Lock()   # 枚举串行化：并发请求不叠加 PowerShell
        # 自动更新检测（启动即检 + 每 12h；不落盘 → 关闭重置）
        self._upd_watch = _UpdateWatcher(self)
        self._upd_watch.start()

    # ---- 模块快捷取用 ----
    def _m(self, name):
        return self.pipeline.get(name) if self.pipeline else None

    def call(self, name, method, query, body):
        fn = getattr(self, "api_" + name.replace("/", "_"), None)
        if fn is None:
            raise KeyError(f"unknown api: {name}")
        if method == "GET":
            return fn(**{k: _num(v) for k, v in query.items()})
        return fn(**(body or {}))

    # ---------- 状态 / 帧 ----------
    def api_ping(self, msg=""):
        return "pong"

    def api_state(self):
        dev = self._m("device")
        rec = self._m("recorder")
        cal = self._m("calib")
        fus = self._m("fusion")
        st = {"app": "AstraForge", "version": APP_VERSION,
              "device": {"connected": False, "streaming": False, "info": ""},
              "rgb": self._rgb_status[0], "fps": 0.0,
              "preview_mirror": bool(_preview_mirror["on"]),
              "export_dir": "", "calib": 1.0, "perf_mode": "std",
              "cpu_cores": os.cpu_count() or 4, "gpu": None,
              "rec_continuous": False, "tt_count": 0,
              "modules": self.pipeline.versions() if self.pipeline else {}}
        if dev is not None:
            link = getattr(dev, "link", None)
            opened = bool(link is not None and getattr(link, "dev", None) is not None)
            st["device"]["connected"] = opened
            st["device"]["streaming"] = bool(opened and getattr(link, "stream_on", False))
            st["device"]["info"] = "2BC5:0403"
            # 复位/重连瞬间计数器会被清零，算出来可能是负数 → 夹到 0，界面不显示 -27fps
            st["fps"] = max(0.0, round(_calc_fps(getattr(dev, "cap", None), _fps_meter_state), 1))
        if rec is not None:
            st["export_dir"] = str(rec._out_dir())
            st["rec_continuous"] = bool(rec.continuous[0])
            st["tt_count"] = rec.tt_count()
        if cal is not None:
            st["calib"] = cal.get()
        if fus is not None:
            st["gpu"] = fus.detect_gpu()
            st["perf_mode"] = getattr(fus, "_perf_mode", "std")
        return st

    def api_logs(self, n=30, **kw):
        return {"logs": [f"{'✓' if ok else '✗'} {m}" for m, ok in self._logs[-int(n):]]}

    def _no_frame_jpeg(self):
        dev = self._m("device")
        if dev is None:
            text = "模块未装配"
        elif dev.link is None:
            text = "设备未连接（检查 USB 连接）"
        elif not dev.link.stream_on:
            text = "正在连接设备…"
        else:
            text = "等待画面…"
        return ("__jpeg__", _placeholder(text))

    def api_frame(self, kind="depth", gray="0", **kw):
        """最新帧 JPEG。双重检查锁 + 渲染互斥：
        命中缓存（50ms 内）直接返回；并发同 kind 请求在渲染锁内合并（只渲染一次）；
        降采样编码（深度 0.65x / RGB 0.85x）——配合前端 25ms 链式间隔，目标 15-20fps 流畅预览。
        **kw：容忍前端防缓存参数（t=时间戳等）——曾因不接受 t 而 500。"""
        rec = self._m("recorder")
        if rec is None:
            return self._no_frame_jpeg()

        # 灰度判定 + 缓存 key（深度图按 伪彩/灰度 分开缓存——切换即时生效；
        # 镜像开关也进 key——切换后立即重渲染，不吃旧缓存）
        # 注意：query 参数经 _num() 转换后 "1" 会变数字 1，必须宽松判断
        gray_on = str(gray).strip().lower() in ("1", "true", "yes", "on")
        ckey = (f"{kind}:{int(_preview_mirror['on'])}"
                + ("" if kind == "rgb" else f":{'g' if gray_on else 'c'}"))

        def _cached():
            with _frame_lock:
                ts, c = _frame_cache.get(ckey, (0.0, None))
                return c if (c is not None and time.time() - ts < 0.05) else None

        hit = _cached()
        if hit is not None:
            return ("__jpeg__", hit)
        with _frame_render_lock:
            hit = _cached()                      # 排队期间可能已被并发请求渲染
            if hit is not None:
                return ("__jpeg__", hit)
            if kind == "rgb":
                arr = rec.last_rgb
                if arr is None:
                    return self._no_frame_jpeg()
                data = _jpeg(_pv_flip(arr), 72, scale=0.85)   # 显示层镜像（数据不动）
            else:
                depth = rec.last_depth
                if depth is None:
                    return self._no_frame_jpeg()
                rng = [0.0, 2500.0]
                st = self._m("settings")
                if st is not None:
                    rng = st.disp_range
                dd = _pv_display_depth(depth)
                vis = _get_render_preview()(dd, gray=gray_on,
                                            dmin=rng[0], dmax=rng[1],
                                            crosshair=_pv_crosshair(depth))
                data = _jpeg(vis, 72, scale=0.65)
            with _frame_lock:
                _frame_cache[ckey] = (time.time(), data)
        return ("__jpeg__", data)

    def api_pixel(self, x=0, y=0):
        """深度画布悬停查值（shift → mm）。取像素用显示层画面（按方位裁垃圾带+镜像）——
        与屏幕上看到的图 1:1 对应（镜像/裁剪变化时查询位置不漂移）。"""
        rec = self._m("recorder")
        cal = self._m("calib")
        if rec is None or rec.last_depth is None:
            return {"v": 0, "mm": 0}
        dep = _pv_display_depth(rec.last_depth)
        xi, yi = int(x), int(y)
        h, w = dep.shape
        if not (0 <= xi < w and 0 <= yi < h):
            return {"v": 0, "mm": 0}
        v = int(dep[yi, xi])
        mms = cal.get() if cal else 1.0
        return {"x": xi, "y": yi, "v": v, "mm": round(v * mms, 1)}

    def api_stats(self):
        dev = self._m("device")
        rec = self._m("recorder")
        link = getattr(dev, "link", None) if dev else None
        cap = getattr(dev, "cap", None) if dev else None
        fps = _calc_fps(cap, _fps_meter_stats)
        rgb_c = getattr(rec, "rgb_count", 0) if rec else 0
        rgb_fps = _rate_from_counter(rgb_c, _fps_meter_rgb)
        return {"fps": round(fps, 1),
                "rgb_fps": round(rgb_fps, 1),
                "rgb_frames": rgb_c,
                "frames": cap.index if cap else 0,
                "padded": getattr(link, "padded_frames", 0) if link else 0,
                "rejected": getattr(link, "rejected", 0) if link else 0,
                "gap": getattr(link, "gap_total", 0) if link else 0}

    def api_quality(self, **kw):
        """实时采集质量（TODO-016）：距离分区 / 有效覆盖率 / 分区质量网格。

        供采集页「距离条三段色 + 状态灯 + 质量色谱」使用。无画面时返回
        {"ok": False, "error": ...}（前端静默跳过，不弹错）。
        """
        rec = self._m("recorder")
        cal = self._m("calib")
        if rec is None or getattr(rec, "last_depth", None) is None:
            return {"ok": False, "error": "还没有画面"}
        q = _frame_quality(rec.last_depth, cal.get() if cal else 1.0)
        if q is None:
            return {"ok": False, "error": "画面不可用"}
        q["ok"] = True
        return q

    # ---------- 设备：检测 / 连接 / 断开 ----------
    _PS_CAM = (
        "$d = Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB\\VID_2BC5*' }; "
        "foreach ($x in $d) { "
        "$s = (Get-PnpDeviceProperty -InstanceId $x.InstanceId -KeyName "
        "'DEVPKEY_Device_Service' -ErrorAction SilentlyContinue).Data; "
        "Write-Output ($x.InstanceId + '|' + $x.Status + '|' + $s) }"
    )

    def _usb_cameras(self):
        """快速枚举（pyusb + 项目 libusb 后端，约 0.3s）：正常 WinUSB 下先走这里。

        返回 None 表示"不可判定"（无设备/驱动冲突/后端异常），回退 PowerShell 慢查。
        """
        try:
            import usb.core
            from astra_raw.transport import _get_backend
            devs = list(usb.core.find(find_all=True, idVendor=0x2BC5,
                                      backend=_get_backend()))
        except Exception:
            return None
        if not devs:
            return None
        out = {"ok": True, "depth": {"found": False, "state": "absent"},
               "color": {"found": False}, "devices": [], "fast": True}
        for d in devs:
            pid = f"{int(d.idProduct):04X}"
            item = {"pid": pid, "status": "OK",
                    "service": "WinUSB" if pid == "0403" else "usbvideo",
                    "state": "ready" if pid == "0403" else "other",
                    "instance": f"USB\\VID_2BC5&PID_{pid}"}
            out["devices"].append(item)
            if pid == "0403":
                out["depth"] = dict(item, found=True)
            elif pid == "0501":
                out["color"] = {"found": True, "service": "usbvideo"}
        return out

    def _pnp_cameras(self, deep=False):
        """只读枚举 2BC5 设备：默认 pyusb 快查；deep=True 走 PowerShell 查驱动绑定。

        BUG-026：PowerShell 冷启动经常 >10s（或被安全软件拦），原来的 10s 超时
        会直接判成"没有设备"——前端每 6 秒轮询一次 → 每次都卡 10 秒 + 结果还是
        没设备，表现就是"重新检测永远找不到相机"。现在：
        - 深查超时放宽到 25s；
        - 深查失败时**回退到 pyusb 快查结果**，不把"查询失败"当成"设备不存在"。
        """
        fast = self._usb_cameras()
        if not deep:
            if fast and fast.get("depth", {}).get("found"):
                return fast
        import re as _re
        out = {"ok": False, "depth": {"found": False, "state": "absent"},
               "color": {"found": False}, "devices": []}
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                                "-Command", self._PS_CAM],
                               capture_output=True, timeout=25,
                               creationflags=0x08000000)
            txt = (r.stdout or b"").decode("utf-8", "replace")
        except Exception as e:
            out["error"] = str(e)[:100]
            if fast is not None:            # 深查失败 → 至少给 pyusb 的真实结论
                fast = dict(fast)
                fast["deep_failed"] = True
                return fast
            return out
        for line in txt.splitlines():
            line = line.strip()
            if "VID_2BC5" not in line:
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            iid, status, svc = parts[0].strip(), parts[1].strip(), parts[2].strip()
            m = _re.search(r"PID_([0-9A-Fa-f]{4})", iid)
            pid = m.group(1).upper() if m else ""
            low = svc.lower()
            if "winusb" in low:
                state = "ready"
            elif low.startswith("obdrv") or "orbbec" in low:
                state = "conflict"
            elif not svc:
                state = "nodriver"
            else:
                state = "other"
            item = {"pid": pid, "status": status, "service": svc,
                    "state": state, "instance": iid}
            out["devices"].append(item)
            if pid == "0501":
                out["color"] = {"found": True, "service": svc}
            elif pid:
                out["depth"] = dict(item, found=True)
        out["ok"] = True
        return out

    def api_device_scan(self, deep=0, fast=0, **kw):
        """设备枚举。

        - `fast=1`：只走 pyusb（约 0.3s，不碰 PowerShell）——给前端后台轮询用，
          拔掉设备时也立刻返回，不会把界面卡在"检测中"。
        - `deep=1`：强制 PowerShell 深查（驱动绑定/服务名），用于「重新检测」。
        默认：先快查，快查判不出（无设备/驱动冲突）再深查。
        """
        deep = bool(str(deep).strip().lower() in ("1", "true", "yes", "on"))
        fast_only = bool(str(fast).strip().lower() in ("1", "true", "yes", "on"))
        now = time.time()
        ts, cached = self._scan_cache
        if not deep and cached is not None and now - ts < 3.0:
            return cached
        with self._scan_lock:               # 串行化：并发轮询不叠加子进程
            if fast_only:
                r = self._usb_cameras()
                if r is None:
                    r = {"ok": False, "fast": True,
                         "depth": {"found": False, "state": "absent"},
                         "color": {"found": False}, "devices": [],
                         "error": "pyusb 未枚举到 2BC5 设备（可能没插、或被非 WinUSB 驱动占用）"}
                self._scan_cache = (now, r)
                return r
            r = self._pnp_cameras(deep=deep)
            if not deep:
                self._scan_cache = (now, r)
            return r

    def api_device_connect(self, **kw):
        dev = self._m("device")
        if dev is None:
            return {"ok": False, "error": "device 模块未装配（--no-pipeline 调试模式）"}
        with self._dev_lock:
            link = getattr(dev, "link", None)
            if link is not None and getattr(link, "dev", None) is not None:
                return {"ok": True, "already": True, "connected": True,
                        "streaming": bool(getattr(link, "stream_on", False))}
            try:
                dev.stop()
            except Exception:
                pass
            if self.pipeline:
                self.pipeline.bus.publish("module.log", ("[device] 正在重新连接…", True))
            dev.stop_evt = threading.Event()
            dev.link = None
            try:
                dev.start()
            except Exception as e:
                return {"ok": False, "error": f"连接异常：{str(e)[:120]}"}
            link = getattr(dev, "link", None)
            opened = bool(link is not None and getattr(link, "dev", None) is not None)
            for m in (_fps_meter_state, _fps_meter_stats, _fps_meter_rgb):
                m.update(t=0.0, i=0, v=0.0)      # 重连后帧计数归零，避免负帧率
            if self.pipeline:
                self.pipeline.bus.publish(
                    "module.log",
                    ("[device] 已连接 2BC5:0403" if opened else
                     "[device] 未找到设备或驱动不可用（2BC5:0403）", opened))
            return {"ok": opened, "connected": opened,
                    "streaming": bool(opened and getattr(link, "stream_on", False)),
                    "error": "" if opened else "未找到设备（2BC5:0403），或驱动被占用/需要 WinUSB"}

    def api_device_reset(self, **kw):
        """USB 设备级复位（BUG-025）：只复位这台相机，不重启软件。

        顺序：USB reset（端口重新枚举，红外必断）→ 释放句柄 → 等枚举 → 重新连接。
        用于"深度流卡死 / 帧不动 / 关流没反应"——不用拔线，也不用重启程序。
        """
        dev = self._m("device")
        if dev is None:
            return {"ok": False, "error": "device 模块未装配（--no-pipeline 调试模式）"}
        steps = []
        with self._dev_lock:
            link = getattr(dev, "link", None)
            handle = getattr(link, "dev", None) if link is not None else None
            if handle is not None:
                try:
                    handle.reset()          # libusb 端口复位：纯 USB 层，不发设备命令
                    steps.append("usb-reset ok")
                except Exception as e:      # noqa: BLE001
                    steps.append(f"usb-reset 失败：{str(e)[:80]}")
            else:
                steps.append("没有已打开的句柄（仅做重新连接）")
            try:
                dev.stop()                  # 停线程 + 清资源（内部失败也会 reset 兜底）
                steps.append("关闭流 ok")
            except Exception as e:          # noqa: BLE001
                steps.append(f"关闭流异常：{str(e)[:80]}")
            time.sleep(1.2)                 # 等 Windows 重新枚举
            dev.stop_evt = threading.Event()
            dev.link = None
            try:
                dev.start()
                steps.append("重新连接 ok")
            except Exception as e:          # noqa: BLE001
                steps.append(f"重新连接异常：{str(e)[:80]}")
                return {"ok": False, "steps": steps, "error": str(e)[:160]}
            link = getattr(dev, "link", None)
            opened = bool(link is not None and getattr(link, "dev", None) is not None)
            stream = bool(opened and getattr(link, "stream_on", False))
        if self.pipeline:
            self.pipeline.bus.publish(
                "module.log", (f"[device] USB 复位完成（打开={opened} 流={stream}）", opened))
        return {"ok": opened, "connected": opened, "streaming": stream, "steps": steps,
                "error": "" if opened else "复位后仍打不开设备：检查线材/端口，或换一个 USB 口"}

    def api_device_disconnect(self, **kw):
        dev = self._m("device")
        if dev is None:
            return {"ok": False, "error": "device 模块未装配"}
        with self._dev_lock:
            try:
                dev.stop()
            except Exception as e:
                return {"ok": False, "error": f"断开异常：{str(e)[:120]}"}
            dev.link = None
            for m in (_fps_meter_state, _fps_meter_stats, _fps_meter_rgb):
                m.update(t=0.0, i=0, v=0.0)
            if self.pipeline:
                self.pipeline.bus.publish("module.log", ("[device] 已断开（红外已关）", True))
        return {"ok": True, "connected": False}

    # ---------- 采集 ----------
    def api_save_snapshot(self, **kw):
        rec = self._m("recorder")
        if rec is None:
            raise RuntimeError("recorder 模块未装配")
        base = rec.save_snapshot()
        if not base:
            return {"ok": False, "error": "还没有画面"}
        return {"ok": True, "path": base + ".npy", "png": base + "_depth.png",
                "rgb_png": base + "_rgb.png" if os.path.exists(base + "_rgb.png") else ""}

    def api_export_cloud(self, **kw):
        rec = self._m("recorder")
        if rec is None:
            raise RuntimeError("recorder 模块未装配")
        p = rec.export_cloud()
        if not p:
            return {"ok": False, "error": "还没有画面"}
        return {"ok": True, "path": p}

    def api_toggle_continuous(self, **kw):
        rec = self._m("recorder")
        if rec is None:
            raise RuntimeError("recorder 模块未装配")
        on = rec.toggle_continuous()
        return {"ok": True, "on": on}

    def api_set_gray(self, on=False, **kw):
        pv = self._m("preview")
        w = getattr(pv, "_widget", None) if pv else None
        if w is not None:
            w.gray[0] = bool(on)
        return {"ok": True, "gray": bool(on)}

    def api_set_flip(self, on=True, **kw):
        """预览镜像（显示层，默认关）：打开后两个预览画面左右翻转，便于观察。
        保存帧、导出点云、融合等数据始终是正常方向（无镜像）。
        自动保存：下次启动还原。"""
        _preview_mirror["on"] = bool(on)
        try:
            from core import appsettings
            appsettings.update(ROOT / "data", preview_mirror_v2=bool(on))
        except Exception:
            pass
        return {"ok": True, "preview_mirror": bool(on)}

    def api_set_paused(self, on=False, **kw):
        """暂停预览。Qt 架构：前端 FrameImg(paused) 停止拉流（真正省资源）；
        经典版（tkinter）走 preview._widget.paused。本接口同时返回状态供诊断。"""
        pv = self._m("preview")
        w = getattr(pv, "_widget", None) if pv else None
        if w is not None:                      # 经典版路径
            w.paused[0] = bool(on)
        return {"ok": True, "paused": bool(on)}

    # ---------- 转台 ----------
    def api_tt_shoot(self, step_deg=15.0, cam_dist=0.0, **kw):
        rec = self._m("recorder")
        if rec is None:
            raise RuntimeError("recorder 模块未装配")
        n = rec.tt_shoot(step_deg=float(step_deg), cam_dist=float(cam_dist))
        return {"ok": n >= 0, "count": n}

    def api_tt_finish(self, **kw):
        rec = self._m("recorder")
        if rec is None:
            raise RuntimeError("recorder 模块未装配")
        d = rec.tt_finish()
        return {"ok": bool(d), "dir": d}

    def api_tt_status(self, **kw):
        rec = self._m("recorder")
        return {"count": rec.tt_count() if rec else 0,
                "continuous": bool(rec.continuous[0]) if rec else False}

    def api_serial_ports(self, **kw):
        """串口检测（转台控制器；无 pyserial 时不可用）。
        过滤蓝牙/软串口（实测本机 12 口中 11 个是蓝牙，属噪声；控制器为 USB 串口）。"""
        try:
            import serial.tools.list_ports as lp
            raw = [(p.device, p.description or "") for p in lp.comports()]
            cand = [x for x in raw if "蓝牙" not in x[1] and "Bluetooth" not in x[1]]
            return {"ok": True, "ports": (cand if cand else raw),
                    "filtered": len(raw) - len(cand)}
        except ImportError:
            return {"ok": False, "ports": [],
                    "error": "未安装 pyserial（自动模式不可用，请用手动模式）"}

    # ---------- 转台控制器：真实连接（串口 + WHO 握手 + ID 校验） ----------
    # 协议（与自研控制器固件约定）：连接时发 "WHO\n" → 控制器应答
    # "ASTRATT:<ID>:<版本>"；前缀不符（含无应答/超时）即拒绝连接——不是什么
    # 设备都能连（本机 12 个串口里 11 个是蓝牙，必须靠握手区分）。
    _CTRL_HELLO = "WHO"
    _CTRL_PREFIX = "ASTRATT"

    def _verify_controller(self, port):
        """打开串口 → WHO 握手 → 校验 ASTRATT 前缀 → 关闭。返回 (ok, info/err)。"""
        try:
            import serial
        except ImportError:
            return False, "未安装 pyserial"
        try:
            ser = serial.Serial(port, 115200, timeout=1.2)
        except Exception as e:
            return False, f"串口打不开：{str(e)[:60]}"
        try:
            ser.reset_input_buffer()
            ser.write((self._CTRL_HELLO + "\n").encode())
            ser.flush()
            line = ""
            t0 = time.time()
            while time.time() - t0 < 2.0:
                line = ser.readline().decode("ascii", "ignore").strip()
                if line:
                    break
            if not line:
                return False, "控制器无应答（未识别设备）"
            if not line.startswith(self._CTRL_PREFIX):
                return False, f"非本机控制器（应答：{line[:24]}）"
            return True, line
        finally:
            try:
                ser.close()
            except Exception:
                pass

    def api_tt_connect(self, port="", **kw):
        """连接控制器：真实串口握手（WHO→ASTRATT），通过才记为已连接。"""
        if not port:
            return {"ok": False, "error": "未选择串口"}
        ok, info = self._verify_controller(port)
        if ok:
            self._tt_ctrl = {"port": port, "hello": info}
            if self.pipeline:
                self.pipeline.bus.publish("module.log",
                                          (f"[tt] 控制器已连接：{info}（{port}）", True))
            return {"ok": True, "port": port, "device": info}
        self._tt_ctrl = None
        return {"ok": False, "error": info}

    def api_tt_disconnect(self, **kw):
        self._tt_ctrl = None
        return {"ok": True}

    def api_tt_connect_status(self, **kw):
        c = getattr(self, "_tt_ctrl", None) or {}
        return {"connected": bool(c), "port": c.get("port", ""),
                "device": c.get("hello", "")}

    def api_tt_auto(self, port="", step_deg=15.0, wait=0.8, **kw):
        """自动扫描（ESP32 控制器：ROT <角度> → READY → 拍摄 → 循环）。
        前置：必须先「连接」完成握手（WHO → ASTRATT:<ID>:<版本>），否则拒绝。"""
        rec = self._m("recorder")
        if rec is None:
            raise RuntimeError("recorder 模块未装配")
        try:
            import serial  # noqa: F401
        except ImportError:
            return {"ok": False, "error": "未安装 pyserial"}
        if not port:
            return {"ok": False, "error": "未指定串口"}
        c = getattr(self, "_tt_ctrl", None) or {}
        if not c or c.get("port") != port:
            return {"ok": False, "error": "未连接控制器（先点「连接」完成握手）"}
        if getattr(self, "_tt_auto_on", False):
            self._tt_auto_on = False
            return {"ok": True, "on": False}
        self._tt_auto_on = True

        def run():
            try:
                ser = serial.Serial(port, 115200, timeout=3)
                total = int(round(360 / max(float(step_deg), 1)))
                for i in range(total):
                    if not self._tt_auto_on:
                        break
                    ser.write(f"ROT {step_deg}\n".encode())
                    ser.flush()
                    t0 = time.time()
                    while time.time() - t0 < 10:
                        line = ser.readline().decode("ascii", "ignore").strip()
                        if line == "READY":
                            break
                    time.sleep(float(wait))       # 稳定等待
                    if not self._tt_auto_on:
                        break
                    rec.tt_shoot(step_deg=float(step_deg))
                ser.close()
            except Exception as e:
                if self.pipeline:
                    self.pipeline.bus.publish("module.log",
                                              (f"[tt-auto] 失败: {e}", False))
            finally:
                self._tt_auto_on = False

        threading.Thread(target=run, daemon=True, name="tt-auto").start()
        return {"ok": True, "on": True}

    def api_tt_auto_status(self, **kw):
        return {"on": bool(getattr(self, "_tt_auto_on", False))}

    # ---------- 手持扫描记录（Scan3D 页） ----------
    def api_scan_start(self, **kw):
        rec = self._m("recorder")
        if rec is None:
            raise RuntimeError("recorder 模块未装配")
        rec.scan_start()
        return {"ok": True}

    def api_scan_shoot(self, **kw):
        rec = self._m("recorder")
        if rec is None:
            raise RuntimeError("recorder 模块未装配")
        n = rec.scan_shoot()
        return {"ok": n >= 0, "count": n}

    def api_scan_finish(self, **kw):
        rec = self._m("recorder")
        if rec is None:
            raise RuntimeError("recorder 模块未装配")
        d = rec.scan_finish()
        return {"ok": bool(d), "dir": d}

    def api_scan_count(self, **kw):
        rec = self._m("recorder")
        return {"count": rec.scan_count() if rec else 0}

    # ---------- 融合 ----------
    def api_fuse(self, dir="", **kw):
        fus = self._m("fusion")
        if fus is None:
            raise RuntimeError("fusion 模块未装配")
        if not dir:
            return {"ok": False, "error": "未选择目录"}
        workers = fus.workers_for(getattr(fus, "_perf_mode", "std"))
        return fus.fuse_directory_async(dir, workers=workers)

    def api_fuse_progress(self, **kw):
        fus = self._m("fusion")
        return fus.get_progress() if fus else {}

    def api_fuse_cancel(self, **kw):
        fus = self._m("fusion")
        return fus.fuse_cancel() if fus else {"ok": False}

    def api_list_dirs(self, **kw):
        """扫描输出目录下的可融合采集目录（turntable_ 转台 / scan_session_ 手持）。

        返回给融合工作台直接渲染：帧数、类型、覆盖角度、时间、产物、预览图。
        """
        rec = self._m("recorder")
        base = Path(rec._out_dir()) if rec else ROOT.parent / "扫描输出"
        out = []
        if base.exists():
            for d in sorted(base.iterdir(), reverse=True):
                if not d.is_dir() or not (d.name.startswith("turntable_")
                                          or d.name.startswith("scan_session_")):
                    continue
                frames = len(list(d.glob("frame_*.npy")))
                man = {}
                try:
                    mf = d / "manifest.json"
                    if mf.exists():
                        man = json.loads(mf.read_text(encoding="utf-8"))
                except Exception:
                    man = {}
                angle = 0.0
                for fr in (man.get("frames") or []):
                    try:
                        angle = max(angle, float(fr.get("angle") or 0.0))
                    except Exception:
                        pass
                arts = []
                for p in d.iterdir():
                    # 只把融合产物当"产物"；frame_*.npy / frame_*_rgb.png 是输入帧，不展示
                    if p.is_file() and p.name.startswith("fused_") and p.suffix.lower() in (".ply", ".stl", ".png", ".obj"):
                        arts.append({"name": p.name, "size": p.stat().st_size,
                                     "path": str(p)})
                arts.sort(key=lambda x: x["name"])
                preview = next((a for a in arts if a["name"] == "fused_preview.png"), None)
                try:
                    mtime = d.stat().st_mtime
                    date = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
                except Exception:
                    mtime, date = 0, ""
                out.append({"name": d.name, "path": str(d), "frames": frames,
                            "type": "turntable" if d.name.startswith("turntable_") else "handheld",
                            "coverage": round(angle, 1), "date": date, "mtime": mtime,
                            "artifacts": arts,
                            "preview": preview["path"] if preview else "",
                            "fused": bool(preview)})
        return {"dirs": out, "base": str(base)}

    # ---------- 标定 / 测距 ----------
    def api_calib_sample(self, known_mm=500.0, roi=40, **kw):
        rec = self._m("recorder")
        cal = self._m("calib")
        if rec is None or rec.last_depth is None:
            return {"ok": False, "error": "还没有画面"}
        import numpy as np
        r = max(4, min(int(roi), 200))
        d = rec.last_depth
        c = d[d.shape[0] // 2 - r:d.shape[0] // 2 + r,
              d.shape[1] // 2 - r:d.shape[1] // 2 + r]
        v = c[c > 0]
        if len(v) < 50:
            return {"ok": False, "error": "采样区有效点太少（中心无数据？换方向/距离）"}
        med = float(np.median(v))
        k = cal.compute(float(known_mm), med)
        return {"ok": True, "median": round(med, 1), "k": round(k, 4)}

    def api_calib_save(self, k=0.0, **kw):
        cal = self._m("calib")
        if cal is None:
            raise RuntimeError("calib 模块未装配")
        ok = cal.set_and_save(float(k))
        return {"ok": ok, "k": float(k)}

    def api_measure(self, x1=0, y1=0, x2=0, y2=0, **kw):
        """深度画布两点 3D 测距（相机内参反投影）。取像素用显示层画面（裁垃圾带+镜像）
        与屏幕 1:1；反投影用**尺寸感知主点**（BUG-011；出厂基准 CX/CY，BUG-015），翻面对比
        模式下先把显示坐标映射回发布坐标——两种模式对同一物理像素结果一致。"""
        rec = self._m("recorder")
        cal = self._m("calib")
        if rec is None or rec.last_depth is None:
            return {"ok": False, "error": "还没有画面"}
        import numpy as np
        from core import cloudmath as cm
        raw = rec.last_depth
        d = _pv_display_depth(raw)
        mms = cal.get() if cal else 1.0
        # 主点按**真实裁剪方位**取（BUG-021）：裁左 → col0=21；裁右 → col0=0。
        col0 = 0
        if raw is not None and getattr(raw, "ndim", 0) == 2 and raw.shape[1] == _PV_RAW_W:
            col0 = _PV_CROP_L if _pv_crop_side(raw) == 'L' else 0
        cx, cy = cm.cxcy_for_shape(d.shape, col0=col0)   # 尺寸感知主点（BUG-011）
        dw = d.shape[1]
        back = _preview_mirror["on"]             # 预览镜像：显示坐标 → 数据坐标
        pts = []
        for (xi, yi) in ((int(x1), int(y1)), (int(x2), int(y2))):
            h, w = d.shape
            if not (0 <= xi < w and 0 <= yi < h):
                return {"ok": False, "error": "坐标越界"}
            z = float(d[yi, xi]) * mms
            if z <= 0:
                return {"ok": False, "error": f"点({xi},{yi})深度无效"}
            xu = (dw - 1 - xi) if back else xi
            pts.append(np.array([(xu - cx) * z / cm.FX,
                                 (yi - cy) * z / cm.FY, z]))
        dist = float(np.linalg.norm(pts[1] - pts[0]))
        return {"ok": True, "dist_mm": round(dist, 1)}

    # ---------- 设置 ----------
    def api_settings(self, **kw):
        rec = self._m("recorder")
        fus = self._m("fusion")
        st = self._m("settings")
        return {"export_dir": str(rec._out_dir()) if rec else str(ROOT.parent / "扫描输出"),
                "perf_mode": getattr(fus, "_perf_mode", "std") if fus else "std",
                "disp_range": st.disp_range if st else [0.0, 2500.0],
                "preview_mirror": bool(_preview_mirror["on"]),
                "cpu_cores": os.cpu_count() or 4,
                "version": APP_VERSION,
                "gpu": fus.detect_gpu() if fus else None}

    def api_set_export_dir(self, dir="", **kw):
        rec = self._m("recorder")
        if rec is None or not dir:
            return {"ok": False, "error": "目录不能为空"}
        rec.ctx.settings["out_dir"] = dir
        try:
            Path(dir).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return {"ok": False, "error": f"无法创建目录: {e}"}
        try:                                   # 自动保存：下次启动还原
            from core import appsettings
            appsettings.update(rec.ctx.data_dir, out_dir=dir)
        except Exception:
            pass
        return {"ok": True, "dir": dir}

    def api_set_perf_mode(self, mode="std", **kw):
        """性能三档：std=核数-1不用GPU / perf=核数-1+GPU / turbo=全核+GPU。"""
        fus = self._m("fusion")
        if fus is None:
            return {"ok": False}
        if mode not in ("std", "perf", "turbo"):
            return {"ok": False, "error": "未知模式"}
        fus._perf_mode = mode
        try:                                   # 自动保存：下次启动还原
            from core import appsettings
            appsettings.update(ROOT / "data", perf_mode=mode)
        except Exception:
            pass
        if self.pipeline:
            self.pipeline.bus.publish("module.log",
                (f"[perf] 性能模式 → {mode}（workers="
                 f"{fus.workers_for(mode)}）", True))
        return {"ok": True, "mode": mode, "workers": fus.workers_for(mode)}

    def api_set_disp_range(self, lo=0.0, hi=2500.0, **kw):
        st = self._m("settings")
        if st is not None:
            st.set_disp_range(float(lo), float(hi))
        return {"ok": True}

    def api_open_dir(self, path="", **kw):
        if not path:
            return {"ok": False, "error": "空路径"}
        try:
            os.startfile(path)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:100]}

    def api_open_url(self, url="", **kw):
        """用系统默认浏览器打开链接（QtWebEngine 内 window.open 会开子窗口，不可靠）。"""
        u = (url or "").strip()
        if not u.lower().startswith(("http://", "https://", "mailto:")):
            return {"ok": False, "error": "仅允许 http/https/mailto"}
        try:
            os.startfile(u)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:100]}

    def api_paths(self, **kw):
        """安装布局与可打开的真实路径（关于页 / 设置页使用）。

        驱动工具路径统一走 `core.driverpack`（BUG-024）：随包布局是
        `驱动工具/zadig/zadig.exe`，旧代码少一层 `zadig/` 导致永远找不到。
        """
        rec = self._m("recorder")
        install_root = ROOT.parent
        from core import driverpack
        drv = driverpack.summary()
        driver_tool = drv["zadig"]
        driver_pack = drv["pack_dir"]
        uninstaller = ""
        for cand in (install_root / "AstraForge-卸载.exe",
                     install_root / "_setup" / "AstraForge-卸载.exe"):
            if cand.exists():
                uninstaller = str(cand)
                break
        return {"root": str(ROOT), "install_root": str(install_root),
                "installed": (install_root / "AstraForge.exe").exists(),
                "export": str(rec._out_dir()) if rec else str(ROOT.parent / "扫描输出"),
                "data": str(ROOT / "data"),
                "driver_tool": driver_tool,
                "driver_pack": driver_pack,
                "driver_pack_ok": bool(driver_pack),
                "driver_zadig_ok": bool(driver_tool),
                "uninstaller": uninstaller,
                "log": str(ROOT / "shell_web.log"),
                "python": sys.version.split()[0]}

    # ---------- 驱动库（随包 驱动工具/，程序内可修复/安装/支持新设备） ----------
    def api_driver_state(self, deep=0, **kw):
        """设备 + 驱动判定 + 驱动库可用性。

        deep=1 强制重新枚举（走 PowerShell 查驱动绑定，约 1–25s）；
        deep=0 用 pyusb 快查（约 0.3s），页面打开/轮询不再被枚举拖住。
        `blockers` 直接告诉界面"这个按钮为什么不能点"，避免出现一片灰按钮。
        """
        from core import driverpack
        deep_on = bool(str(deep).strip().lower() in ("1", "true", "yes", "on"))
        scan = self.api_device_scan(deep=1 if deep_on else 0,
                                    fast=0 if deep_on else 1)
        depth = (scan or {}).get("depth") or {}
        vid = "2BC5"
        pid = str(depth.get("pid") or "")
        entry = driverpack.match_device(vid, pid) if pid else None
        pack = driverpack.summary()
        pack_ok = bool(pack.get("has_pack"))
        zadig_ok = bool(pack.get("zadig_ok"))
        blockers = {}
        if not pack_ok:
            blockers["pack"] = ("没有驱动库（驱动工具/manifest.json）——"
                                "便携目录请把 installer/driver/pack 复制成 驱动工具/；"
                                "安装版请重新运行安装器")
        if not zadig_ok:
            blockers["zadig"] = "驱动库里没有 zadig/zadig.exe（驱动向导不可用）"
        if not depth.get("found"):
            blockers["device"] = ("没枚举到 2BC5:0403（没插、线松，或驱动不是 WinUSB）——"
                                  "插好后点「重新检测」")
        elif not entry:
            blockers["match"] = f"驱动库没有 2BC5:{pid} 的条目（这台机型未收录）"
        return {
            "scan": scan,
            "depth": depth,
            "driver_pack": pack,
            "matched": ({
                "id": entry.get("id"), "name": entry.get("name"),
                "method": entry.get("method"),
            } if entry else None),
            "can_install": bool(entry) and pack_ok,
            "pack_ok": pack_ok,
            "zadig_ok": zadig_ok,
            "deep": deep_on,
            "blockers": blockers,
            "admin": driverpack.is_admin(),
        }

    def api_driver_manifest(self, **kw):
        """驱动库清单（支持的机型 / 安装方式 / Zadig 是否就绪）。"""
        from core import driverpack
        return driverpack.summary()

    def api_driver_install(self, driver_id="", **kw):
        """安装/修复驱动（应用内）。不传 driver_id 时按当前设备 VID/PID 自动匹配。"""
        from core import driverpack
        if not driver_id:
            scan = self.api_device_scan(deep=1)
            depth = (scan or {}).get("depth") or {}
            entry = driverpack.match_device("2BC5", str(depth.get("pid") or ""))
            if not entry:
                return {"ok": False,
                        "error": "没有匹配到驱动条目（先插好相机并点「重新检测」）"}
            driver_id = str(entry.get("id"))
        return driverpack.install_driver(driver_id)

    def api_driver_open_tool(self, **kw):
        """拉起随包 Zadig（路径来自 manifest.tools.zadig，修 BUG-024）。"""
        from core import driverpack
        p = driverpack.zadig_path()
        if not p:
            return {"ok": False,
                    "error": "未找到驱动工具（应位于 驱动工具/zadig/zadig.exe）",
                    "hint": "驱动库缺失时请重新运行安装器覆盖安装"}
        try:
            os.startfile(p)      # noqa: S606
            return {"ok": True, "path": p}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:120]}

    def api_driver_open_folder(self, **kw):
        """打开驱动库目录（手动排查/换 INF 用）。"""
        from core import driverpack
        d = driverpack.pack_dir()
        if not d:
            return {"ok": False, "error": "驱动库目录不存在"}
        try:
            os.startfile(str(d))   # noqa: S606
            return {"ok": True, "path": str(d)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:120]}

    def api_driver_uninstall(self, oem="", **kw):
        """卸载已发布的驱动包（pnputil /delete-driver）。不传 oem 自动找 Orbbec/Astra。"""
        from core import driverpack
        return driverpack.uninstall_driver(oem or "")

    def api_launch_exe(self, path="", **kw):
        """启动 exe（卸载器等）。比 open_dir 语义更明确，不接受目录。"""
        p = (path or "").strip()
        if not p:
            return {"ok": False, "error": "空路径"}
        if not p.lower().endswith(".exe"):
            return {"ok": False, "error": "仅允许 .exe 文件"}
        if not os.path.isfile(p):
            return {"ok": False, "error": f"文件不存在：{p}"}
        try:
            os.startfile(p)  # noqa: S606
            return {"ok": True, "launched": p}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:120]}

    def api_artifact(self, path="", **kw):
        """读取导出目录内的产物图片（融合预览），只允许 png/jpg，防路径穿越。"""
        rec = self._m("recorder")
        base = Path(rec._out_dir()) if rec else (ROOT.parent / "扫描输出")
        try:
            base = base.resolve()
            p = Path(path).resolve()
            if p != base and base not in p.parents:
                return {"ok": False, "error": "路径不在导出目录内"}
            if not p.is_file():
                return {"ok": False, "error": "文件不存在"}
            ctype = {".png": "image/png", ".jpg": "image/jpeg",
                     ".jpeg": "image/jpeg"}.get(p.suffix.lower())
            if not ctype:
                return {"ok": False, "error": "只支持图片"}
            if p.stat().st_size > 20 * 1024 * 1024:
                return {"ok": False, "error": "图片过大"}
            return ("__file__", p.read_bytes(), ctype)
        except Exception as e:
            return {"ok": False, "error": str(e)[:100]}

    # ---------- 关于 / 诊断 / OTA ----------
    def api_about(self, **kw):
        return {"app": "AstraForge", "version": APP_VERSION,
                "license": "Apache-2.0",
                "modules": self.pipeline.versions() if self.pipeline else {},
                "note": "For Orbbec Astra devices. Not affiliated with Orbbec."}

    def api_diag(self, **kw):
        """诊断信息（反馈给 AI/开发者用）：系统 + 设备 + 模块 + 最近日志。"""
        import platform
        dev = self._m("device")
        link = getattr(dev, "link", None) if dev else None
        return {"app": "AstraForge", "version": APP_VERSION,
                "os": f"{platform.system()} {platform.version()}",
                "python": platform.python_version(),
                "cpu_cores": os.cpu_count(),
                "device": {"connected": link is not None,
                           "streaming": bool(link and link.stream_on),
                           "padded": getattr(link, "padded_frames", 0) if link else 0,
                           "rejected": getattr(link, "rejected", 0) if link else 0},
                "modules": self.pipeline.versions() if self.pipeline else {},
                "gpu": (self._m("fusion").detect_gpu() if self._m("fusion") else None),
                "fps": {"depth": round(_fps_meter_stats["v"], 1),
                        "rgb": round(_fps_meter_rgb["v"], 1),
                        "rgb_frames": getattr(self._m("recorder"), "rgb_count", 0)
                        if self._m("recorder") else 0},
                "logs": [f"{'✓' if ok else '✗'} {m}" for m, ok in self._logs[-15:]],
                "ts": time.strftime("%Y-%m-%d %H:%M:%S")}

    def api_report_ready(self, data=None, **kw):
        """前端页面就绪上报（自测/诊断数据）。"""
        (ROOT / "_front_report.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[bridge] report_ready:", str(data)[:300], flush=True)
        return "ok"

    def api_check_update(self, **kw):
        up = self._m("updater")
        if up is None:
            return {"ok": False, "error": "updater 模块未装配"}
        try:
            res = up.check()
            return {"ok": True, "result": res}
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    # ---------- 应用级更新（update.json → 下载 → 校验 → 退出后替换） ----------
    def _fetch_update_manifest(self, timeout=6.0):
        import urllib.request
        try:
            req = urllib.request.Request(UPDATE_URL, headers={
                "User-Agent": "AstraForge-App/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            if not isinstance(data, dict) or not data.get("latest"):
                return None, "update.json 格式不正确"
            return data, None
        except Exception as e:
            return None, f"{type(e).__name__}: {str(e)[:90]}"

    def api_update_check(self, **kw):
        """应用更新检查：读 Release 的 update.json，与本机 APP_VERSION 比较。"""
        data, err = self._fetch_update_manifest()
        if data is None:
            return {"ok": False, "error": err, "current": APP_VERSION}
        latest = str(data.get("latest"))
        can_apply = (ROOT.parent / "AstraForge.exe").exists()
        result = {"ok": True, "current": APP_VERSION, "latest": latest,
                  "has_update": _ver_gt(latest, APP_VERSION),
                  "payload_url": str(data.get("payload_url") or ""),
                  "payload_sha256": str(data.get("payload_sha256") or ""),
                  "notes_url": str(data.get("notes_url") or ""),
                  "min_installer": str(data.get("min_installer") or ""),
                  "can_apply": can_apply,
                  "mode": "installed" if can_apply else "dev"}
        try:
            self._upd_watch.absorb(result)     # 与自动检测共用一份状态
        except Exception:
            pass
        return result

    def api_update_state(self, **kw):
        """自动更新状态（前端轮询：侧栏红点 / 顶部横幅 / 关于页）。"""
        st = self._upd_watch.snapshot()
        # 失败未达阈值时对 UI 隐藏错误（静默），达到才暴露
        if st.get("error") and int(st.get("fails") or 0) < _UpdateWatcher.FAILS_TO_SHOW:
            st["error"] = None
            st["error_hidden"] = True
        return st

    def api_update_check_now(self, **kw):
        """手动触发一次自动检测器刷新（含计时重置）。"""
        return self._upd_watch.check_now()

    def api_update_download(self, url="", sha256="", latest="", **kw):
        """后台下载更新包（.part → SHA-256 → 改名）；进度用 /api/update_status 轮询。"""
        if not url:
            return {"ok": False, "error": "缺少下载地址"}
        with self._upd_lock:
            if self._upd.get("phase") == "downloading":
                return {"ok": True, "state": dict(self._upd)}
            dest_dir = Path(tempfile.gettempdir()) / "AstraForge" / "updates"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"AstraForge-{latest or 'latest'}-payload.zip"
            self._upd = {"phase": "downloading", "pct": 0, "msg": "连接下载源…",
                         "path": str(dest), "latest": latest, "error": None}

        def run():
            import hashlib
            import urllib.request
            tmp = dest.with_name(dest.name + ".part")
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "AstraForge-App/1.0"})
                with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
                    total = int(r.headers.get("Content-Length") or 0)
                    h = hashlib.sha256()
                    got = 0
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        h.update(chunk)
                        got += len(chunk)
                        pct = int(got * 100 / total) if total else 0
                        with self._upd_lock:
                            self._upd.update(pct=pct,
                                             msg=f"下载中 {got // 1048576} MB")
                want = (sha256 or "").strip().lower()
                if want and h.hexdigest() != want:
                    try:
                        tmp.unlink()
                    except Exception:
                        pass
                    with self._upd_lock:
                        self._upd.update(phase="error", error="SHA-256 校验失败，已删除下载文件")
                    return
                if dest.exists():
                    dest.unlink()
                tmp.replace(dest)
                with self._upd_lock:
                    self._upd.update(phase="done", pct=100, msg="下载完成，校验通过",
                                     sha256=h.hexdigest())
            except Exception as e:
                try:
                    tmp.unlink()
                except Exception:
                    pass
                with self._upd_lock:
                    self._upd.update(phase="error",
                                     error=f"{type(e).__name__}: {str(e)[:100]}")

        threading.Thread(target=run, daemon=True, name="app-update-dl").start()
        return {"ok": True, "state": dict(self._upd)}

    def api_update_status(self, **kw):
        with self._upd_lock:
            return dict(self._upd)

    def api_update_apply(self, **kw):
        """把已下载的 payload 写入安装目录，然后尝试自动重启。

        先在本进程内解压覆盖 `code/` 与根文档（Windows 允许覆盖运行中的 .py /
        静态资源），这样即使重启脚本被安全软件拦下，更新文件也已经落盘；
        `AstraForge.exe / _internal` 正在运行、可能被锁，失败则跳过并提示用安装器。
        用户设置与日志不覆盖。
        """
        with self._upd_lock:
            st = dict(self._upd)
        if st.get("phase") != "done":
            return {"ok": False, "error": "还没有下载完成的更新包"}
        install = ROOT.parent
        exe = install / "AstraForge.exe"
        if not exe.exists():
            return {"ok": False, "error": "当前是开发目录，不能自动覆盖；请用安装器更新"}
        zip_path = Path(st.get("path") or "")
        if not zip_path.exists():
            return {"ok": False, "error": "更新包不存在，请重新下载"}

        replaced, skipped = 0, []
        skip_names = {"code/data/设置.json", "code/data/标定.json",
                      "code/shell_web.log"}
        try:
            import shutil
            import zipfile
            base = install.resolve()
            with zipfile.ZipFile(zip_path) as z:
                for info in z.infolist():
                    name = info.filename
                    if not name or name.endswith("/") or name in skip_names:
                        continue
                    target = (install / name).resolve()
                    if target != base and base not in target.parents:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        with z.open(info) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        replaced += 1
                    except (PermissionError, OSError):
                        skipped.append(name)
        except Exception as e:
            return {"ok": False, "error": f"写入更新失败：{str(e)[:120]}"}

        if not replaced:
            return {"ok": False, "error": "没有可写入的文件（更新包结构异常）",
                    "skipped": skipped[:20]}

        # 更新安装清单版本
        try:
            ij = install / "install.json"
            data = json.loads(ij.read_text(encoding="utf-8")) if ij.exists() else {}
            data["version"] = st.get("latest") or data.get("version", "")
            data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            ij.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        except Exception:
            pass

        # 重启脚本：只负责拉起新进程（文件已在本进程内写好）
        script = Path(tempfile.gettempdir()) / "AstraForge" / "restart_app.ps1"
        script.parent.mkdir(parents=True, exist_ok=True)
        ps = (f"Start-Sleep -Seconds 2\n"
              f"Start-Process -FilePath '{exe}'\n")
        try:
            script.write_text(ps, encoding="utf-8-sig")
            subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-WindowStyle", "Hidden", "-File", str(script)],
                close_fds=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x00000008 | 0x00000200)
        except Exception:
            pass  # 文件已更新，重启可手动完成

        def _bye():
            time.sleep(1.0)
            os._exit(0)
        threading.Thread(target=_bye, daemon=True, name="app-update-exit").start()
        need_installer = any(s.startswith(("AstraForge.exe", "_internal", "驱动工具"))
                             for s in skipped)
        return {"ok": True, "replaced": replaced,
                "skipped": skipped[:20], "needs_installer": need_installer,
                "msg": "更新已写入，正在重启应用…"}

    # ---------- 心跳（窗口存活判定：Edge 多进程模型下 proc.wait 不可靠） ----------
    _beat = {"last": 0.0, "got": False}

    def api_heartbeat(self, **kw):
        self._beat["last"] = time.time()
        self._beat["got"] = True
        return {"ok": True}

    # ---------- 收尾（软件与设备绑定） ----------
    def api_shutdown(self, **kw):
        try:
            if self.pipeline is not None:
                self.pipeline.stop_all()
                print("[bridge] shutdown: 管线已收尾（红外已关）", flush=True)
        except Exception as e:
            print(f"[bridge] shutdown 收尾异常: {e}", flush=True)

        def _exit():
            time.sleep(0.3)
            os._exit(0)
        threading.Thread(target=_exit, daemon=True).start()
        return {"ok": True}




def _blank_frame():
    import numpy as np
    return np.full((480, 640, 3), (24, 24, 30), dtype=np.uint8)


def _num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return float(v)
        except (TypeError, ValueError):
            return v


def _ver_tuple(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except (TypeError, ValueError):
        return (0,)


def _ver_gt(a, b):
    return _ver_tuple(a) > _ver_tuple(b)


def build_pipeline():
    """装配真模块管线（与 main.py 同一套；tk UI 不建）。"""
    from core.pipeline import Pipeline
    from core.events import EventBus
    from core.contracts import ModuleContext

    bus = EventBus()
    pipe = Pipeline(ROOT, bus)
    pipe.load_all_modules()

    settings = {"mm_per_shift": 1.0}
    for cf in (ROOT / "data" / "标定.json", ROOT.parent / "标定.json"):
        try:
            if cf.exists():
                v = json.loads(cf.read_text(encoding="utf-8")).get("mm_per_shift")
                if v and 0.1 < float(v) < 10:
                    settings["mm_per_shift"] = float(v)
                    break
        except Exception:
            pass

    log_fn = lambda m, ok=True: bus.publish("module.log", (m, ok))
    ctx = ModuleContext(bus=bus, device=None, settings=settings,
                        log=log_fn, data_dir=ROOT / "data", root_dir=ROOT,
                        ui_root=None)
    pipe.setup_all(ctx)

    # 模块日志 → 前端（经 /api/logs 轮询）
    logs = []
    bus.subscribe("module.log", lambda t: logs.append(t))

    # RGB 状态文案跟踪
    rgb_status = ["未连接"]
    bus.subscribe("rgb.status", lambda s: rgb_status.__setitem__(0, s))

    pipe.start_all()

    # 启动还原（data/设置.json）：性能模式 / 预览镜像
    # （导出目录由 recorder.setup 自还原；显示范围/曝光/分辨率由 settings 模块还原并重播）
    try:
        from core import appsettings
        saved = appsettings.load(ROOT / "data")
        fus = pipe.get("fusion")
        pm = saved.get("perf_mode")
        if fus is not None and pm in ("std", "perf", "turbo"):
            fus._perf_mode = pm
        # 旧键 preview_mirror 的语义与现在相反（旧 True=直出/不镜像），
        # 不再读取；新键 preview_mirror_v2 才表示"预览镜像"。
        pv = saved.get("preview_mirror_v2")
        if isinstance(pv, bool):
            _preview_mirror["on"] = pv
    except Exception:
        pass

    Bridge._logs = logs
    Bridge._rgb_status = rgb_status
    return pipe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["qt", "edge", "webview"], default="qt",
                    help="窗口内核（默认 qt=内置 QtWebEngine；edge=系统 Edge 窗口）")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--hash", default="")
    ap.add_argument("--no-pipeline", action="store_true",
                    help="不装配设备管线（纯 UI 调试用）")
    ap.add_argument("--profile", default="edge_profile",
                    help="Edge profile 目录名（换名=全新缓存，默认 edge_profile）")
    ap.add_argument("--size", default="",
                    help="窗口尺寸 WxH（测试用；默认自动=屏幕 92%% 封顶 1600x950）")
    ap.add_argument("--snap", default="",
                    help="自检：Qt 窗口显示 8 秒后原生截图到该路径并退出")
    ap.add_argument("--serve-only", action="store_true",
                    help="只起本地 HTTP 服务、不开窗口（UI 开发/无设备预览用）")
    args = ap.parse_args()

    dist = ROOT / "ui-web" / "dist"
    if not (dist / "index.html").exists():
        raise RuntimeError(f"UI 产物不存在: {dist}（先 npm run build）")

    pipeline = None
    if not args.no_pipeline:
        pipeline = build_pipeline()
        print("[shell] 模块管线已装配并启动（device 真连设备）", flush=True)

    bridge = Bridge(pipeline)
    port, _srv = start_server(dist, bridge)
    url = f"http://127.0.0.1:{port}/index.html" + (f"#{args.hash}" if args.hash else "")
    print(f"[shell] UI ready: {url}（浏览器可直接打开调试）", flush=True)
    print(f"[shell] server 自检(即时): {_selfcheck(port)}", flush=True)

    def _watchdog():
        while True:
            time.sleep(30)
            r = _selfcheck(port)
            if r.startswith("FAIL"):
                print("[shell] !! server 异常:", r, flush=True)
    threading.Thread(target=_watchdog, daemon=True, name="watchdog").start()

    if args.serve_only:
        print(f"[shell] serve-only：{url}（Ctrl+C 结束）", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return

    if args.backend == "qt":
        try:
            run_qt_window(url, bridge, snap_path=(args.snap or None),
                          size=args.size)
        except ImportError as e:
            print(f"[shell] QtWebEngine 不可用（{e}）——回退系统 Edge 窗口", flush=True)
            args.backend = "edge"
        else:
            _shutdown_and_exit(bridge)

    if args.backend == "edge":
        edge = find_edge()
        if not edge:
            raise RuntimeError("未找到 Edge 浏览器（需要系统安装 Microsoft Edge）")
        # profile 放用户可写目录（安装到 Program Files 时 code/ 可能只读）
        profile = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "AstraForge" / (args.profile or "edge_profile")
        profile.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [edge, f"--app={url}", "--window-size=1600,950",
             f"--user-data-dir={profile}", "--no-first-run",
             "--no-proxy-server", "--proxy-bypass-list=<-loopback>",
             "--disable-features=msEdgeSidebarV2,msEdgeWorkspaces"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=0x08000000,      # CREATE_NO_WINDOW（windowed exe 下保险）
        )
        print(f"[shell] Edge app 已拉起 (PID {proc.pid})", flush=True)
        # Edge 是多进程模型：启动器可能立即退出（窗口进程独立）——不能用
        # proc.wait 判"窗口关闭"。改为心跳判定：
        #   页面每 3s POST /api/heartbeat；心跳断 >8s = 窗口关闭 → 收尾退出；
        #   90s 内从未收到心跳 = 页面加载失败 → 落盘诊断后退出。
        beat = Bridge._beat
        t0 = time.time()
        reason = ""
        while True:
            time.sleep(1.5)
            now = time.time()
            if beat["got"] and now - beat["last"] > 15:
                reason = "窗口已关闭（心跳断）"
                break
            if not beat["got"] and now - t0 > 90:
                reason = "页面 90s 未加载（检查 shell_error.log / Edge 是否可用）"
                break
        print(f"[shell] {reason} → 执行收尾（关红外/停设备）", flush=True)
        if not beat["got"]:
            try:
                out = (proc.stdout.read() or b"").decode("utf-8", "replace")[-1500:]
            except Exception:
                out = "(无输出)"
            (ROOT / "shell_error.log").write_text(
                f"页面未加载。Edge 输出:\n{out}", encoding="utf-8")
        _shutdown_and_exit(bridge, reason)
    elif args.backend == "webview":
        import webview
        win = webview.create_window("AstraForge 星铸", url=url,
                                    width=1600, height=900, js_api=bridge)
        try:
            webview.start()
        finally:
            _shutdown_and_exit(bridge)


if __name__ == "__main__":
    main()
