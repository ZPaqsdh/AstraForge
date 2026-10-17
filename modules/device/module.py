# -*- coding: utf-8 -*-
"""device 模块 — Astra 设备采集（USB 读线程 + SOF/pid 提取 + Packed11 解码 + UVC RGB）。

架构职责：
  读线程（AstraLink.start_reader）→ 提取帧 → 解码/镜像 → 事件发布：
    depth.frame : DepthFrame（每帧一次）
    rgb.frame   : RgbFrame（UVC，独立线程）
    rgb.status  : str（摄像头连接状态文案）
    device.status: DeviceStatus（启动结果）

对外 API（settings/UI 调用）：set_flip / set_rgb_index / set_exposure / set_resolution
"""
import time
import queue
import struct
import threading

import numpy as np
import usb.core
import usb.util
from astra_raw.transport import _get_backend, open_device

from core.contracts import ModuleContext, DepthFrame, RgbFrame, DeviceStatus

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    cv2 = None
    HAS_CV2 = False

# ---------------- 设备常量 ----------------
W, H = 640, 480
FRAME_BYTES = W * H * 11 // 8
SLOT = 3072
SLOTS = 139
# 内参：唯一源在 core/cloudmath.py（BUG-015 出厂标定 580.703/318.163/249.847）。
# 本模块不做反投影，故不持有副本（避免双份漂移）。
READ_BLOCK = 262144            # USB 读块（实测 256K 缺口帧率 ~11%，512K ~27%）
DEFAULT_RGB_INDEX = 0          # Astra Pro HD Camera = index 0（实测枚举复核）
# 注（BUG-009，2026-10-16 定案）：传感器固定垃圾区（顶行 + 深度右缘 21 列）的裁剪
# **只在输出端**做（保存/导出，见 core.contracts.crop_for_output）；显示端保持原画幅。

class AstraLink:
    def __init__(self):
        self.dev = None
        self.seq = 0x7000
        self.stream_on = False
        self._buf = bytearray()
        self._buf_lock = threading.Lock()   # 读线程/提取线程共享缓冲锁
        self._last_raw = None       # 上一帧原始数据（丢包缺口填补源）
        self.rejected = 0           # 被拒帧计数（边界异常）
        self.padded_frames = 0      # 丢包补偿帧计数
        self.gap_total = 0          # 累计补偿的槽数
        self._reader_thread = None
        self._stop_reader = threading.Event()

    def connect(self):
        BE = _get_backend()
        self.dev = usb.core.find(idVendor=0x2BC5, idProduct=0x0403, backend=BE)
        if self.dev is None:
            return False, "设备未找到（2BC5:0403）——请检查 USB 连接"
        try:
            open_device(self.dev)
        except Exception as e:
            return False, f"打开设备失败: {str(e)[:60]}"
        return True, "设备已连接"

    def raw(self, cmd, payload=b"", tmo=1200):
        assert cmd != 0x0053, "0x53 blacklisted"
        sq = self.seq & 0xFFFF
        self.seq = (self.seq + 1) & 0xFFFF
        fr = (b"\x47\x4d" + (len(payload) // 2).to_bytes(2, "little")
              + cmd.to_bytes(2, "little") + sq.to_bytes(2, "little") + payload)
        try:
            self.dev.ctrl_transfer(0x40, 0, 0, 0, fr, 2500)
        except Exception:
            return ("OUTFAIL", b"")
        rep = None
        for attempt in range(2):
            try:
                rep = bytes(self.dev.ctrl_transfer(0xC0, 0, 0, 0, 4096,
                                                   tmo if attempt == 0 else 300))
                break
            except Exception:
                rep = None
        if not rep or len(rep) < 10 or rep[:2] != b"RB":
            return ("NOREPLY", b"")
        rid = int.from_bytes(rep[6:8], "little")
        return ("FRESH" if rid == sq else "STALE", rep[10:])

    def setparam(self, pid, val):
        return self.raw(0x0003, pid.to_bytes(2, "little") + val.to_bytes(2, "little"))

    def door_open(self):
        return self.setparam(18, 3)[0] == "FRESH"

    def ensure_ready(self):
        msgs = []
        st, _ = self.raw(0x0000)
        if st != "FRESH":
            return False, ["设备无响应——可能被占用或卡死；试拔插后重开本软件"]
        msgs.append("命令通道正常")
        if self.door_open():
            msgs.append("写入门控: 已开启")
        else:
            msgs.append("写入门控: 关闭 → 触发解锁…")
            self.raw(0x24, bytes.fromhex("0100"), tmo=2000)
            time.sleep(0.7)
            if not self.door_open():
                return False, msgs + ["解锁失败——请检查/重试"]
            msgs.append("解锁成功 ✓")
        for pid, val, name in ((18, 3, "深度格式"), (19, 1, "分辨率"), (6, 2, "启动流")):
            st, _ = self.setparam(pid, val)
            msgs.append(f"{name} SetParam({pid},{val}): {st}")
            time.sleep(0.15)
        self.raw(0x2A, bytes.fromhex("0100"))
        msgs.append("激光使能 ✓")
        self.stream_on = True
        self.start_reader()         # 读线程与处理分离：读永不停顿（USB 丢包对策）
        return True, msgs

    @staticmethod
    def _find_sof(buf, start=0):
        return buf.find(b"\x52\x42\x00\x71", start)

    # ---------- 读线程（与处理分离：读永不停顿，USB 丢包对策）----------
    def start_reader(self):
        """启动后台读取线程。背景（2026-10-13 分离实验实测）：读循环每停顿
        约 5ms 即产生大量丢包（设备/驱动缓冲溢出，实测每帧 5ms 停顿 → 缺口
        从 1.6 槽/帧 暴涨到 17 槽/帧）。因此读与解码必须分离：
        读线程只做 read，永不停顿；解码等处理留给消费线程。"""
        if self._reader_thread is not None and self._reader_thread.is_alive():
            return
        self._stop_reader.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def _reader_loop(self):
        while not self._stop_reader.is_set():
            try:
                chunk = bytes(self.dev.read(0x81, READ_BLOCK, timeout=200))
            except Exception:
                time.sleep(0.005)
                continue
            if chunk:
                with self._buf_lock:
                    self._buf += chunk
                    if len(self._buf) > 8_000_000:   # 防御性上限（正常不触发）
                        del self._buf[:-4_000_000]

    def ir_off(self):
        """关闭红外（应用与设备绑定的收尾）：停深度流 → 关激光 → 停读线程。

        背景（2026-10-14 用户实测）：旧版退出只 stop_reader + dispose，
        固件层红外仍在投射（关应用后 IR 还亮）。协议反向操作：
          setparam(6,0)  停流（ensure_ready 里 6,2 启动流的反向）
          raw(0x2A,"0000") 关激光（ensure_ready 里 0x2A "0100" 开启的反向）
        返回 (ok, msgs)：ok=False 时调用方应做 USB reset 兜底。
        """
        msgs = []
        ok = True
        if self.dev is None:
            return True, ["设备未连接，无需关闭"]
        try:
            st, _ = self.setparam(6, 0)
            msgs.append(f"停流 SetParam(6,0): {st}")
            ok = ok and st == "FRESH"
        except Exception as e:
            msgs.append(f"停流命令异常: {str(e)[:50]}")
            ok = False
        time.sleep(0.12)
        try:
            st, _ = self.raw(0x2A, bytes.fromhex("0000"))
            msgs.append(f"关激光(0x2A,0000): {st}")
            ok = ok and st == "FRESH"
        except Exception as e:
            msgs.append(f"关激光命令异常: {str(e)[:50]}")
            ok = False
        try:
            self.stop_reader()
            msgs.append("读线程已停")
        except Exception:
            pass
        self.stream_on = False
        return ok, msgs

    def stop_reader(self):
        self._stop_reader.set()
        t = self._reader_thread
        if t is not None:
            t.join(timeout=0.8)

    def grab_frame(self, timeout=1.0):
        """取一帧：锁内切出帧字节区间 → 锁外解析（SOF→SOF 对齐 + pid 缺口补偿）。

        修复史：2026-10-13 起，帧边界 = 相邻两个 SOF 的间距（不再假设恒 139 槽，
        USB 丢包会让帧变短）；读线程与处理分离消除"读间隙丢包"。
        """
        if self._reader_thread is None:
            self.start_reader()
        t0 = time.time()
        while time.time() - t0 < timeout:
            seg = None
            pid1 = 0
            with self._buf_lock:
                i1 = self._find_sof(self._buf)
                if i1 >= 0:                      # 注意: find 未命中返回 -1（不是 None）
                    i2 = self._find_sof(self._buf, i1 + 4)
                    if i2 >= 0:
                        span = i2 - i1
                        pid1 = int.from_bytes(self._buf[i1 + 4:i1 + 6], "little")
                        pid2 = int.from_bytes(self._buf[i2 + 4:i2 + 6], "little")
                        if span % SLOT == 0 and 100 * SLOT <= span <= SLOTS * SLOT \
                                and (pid2 - pid1) % 65536 == SLOTS:
                            seg = bytes(self._buf[i1:i2])
                            del self._buf[:i2]
                        else:
                            # 边界异常（假 SOF 或严重损坏）：跳过该候选继续找
                            self.rejected += 1
                            del self._buf[:i1 + 4]
            if seg is not None:
                frame, gap = self._parse_segment(seg, pid1)
                self._last_raw = frame
                if gap:
                    self.padded_frames += 1
                    self.gap_total += gap
                return frame
            time.sleep(0.003)                    # 等读线程补数据
        return None

    def _parse_segment(self, seg, pid1):
        """锁外解析：按 packetID 精确摆放各槽；缺口用上一帧同位置数据
        填补（静态场景几乎不可见），无历史则补零。返回 (frame_bytes, gap_slots)。"""
        slots = {}
        p, n = 0, len(seg)
        while p + SLOT <= n:
            if seg[p:p + 2] == b"\x52\x42":
                pid = int.from_bytes(seg[p + 4:p + 6], "little")
                rel = (pid - pid1) % 65536
                if 0 <= rel < SLOTS:
                    slots[rel] = seg[p + 12:p + SLOT]
            p += SLOT
        parts = []
        gap = 0
        for k in range(SLOTS):
            payload = slots.get(k)
            if payload is not None:
                parts.append(payload)
            else:
                gap += 1
                off = k * 3060
                if self._last_raw is not None and off + 3060 <= len(self._last_raw):
                    parts.append(self._last_raw[off:off + 3060])
                else:
                    parts.append(b"\x00" * 3060)
        return b"".join(parts)[:FRAME_BYTES], gap



def decode_frame(data):
    a = np.frombuffer(data, dtype=np.uint8)
    a = a[: (len(a) // 11) * 11].reshape(-1, 11).astype(np.uint16)
    b0, b1, b2, b3, b4, b5, b6, b7, b8, b9, b10 = (a[:, i] for i in range(11))
    o = np.empty((a.shape[0], 8), dtype=np.uint16)
    o[:, 0] = (b0 << 3) | (b1 >> 5)
    o[:, 1] = ((b1 & 0x1F) << 6) | (b2 >> 2)
    o[:, 2] = ((b2 & 0x03) << 9) | (b3 << 1) | (b4 >> 7)
    o[:, 3] = ((b4 & 0x7F) << 4) | (b5 >> 4)
    o[:, 4] = ((b5 & 0x0F) << 7) | (b6 >> 1)
    o[:, 5] = ((b6 & 0x01) << 10) | (b7 << 2) | (b8 >> 6)
    o[:, 6] = ((b8 & 0x3F) << 5) | (b9 >> 3)
    o[:, 7] = ((b9 & 0x07) << 8) | b10
    return o.reshape(H, W)



class RGBThread(threading.Thread):
    """UVC 摄像头采集（线程内管理 VideoCapture，index 可动态切换）"""
    def __init__(self, bus, stop_event, status_cb, get_index, get_exposure=None,
                 get_resolution=None):
        super().__init__(daemon=True)
        self.bus = bus
        self.stop_event = stop_event
        self.status_cb = status_cb
        self.get_index = get_index
        self.get_exposure = get_exposure
        self.get_resolution = get_resolution
        self._cur_index = None
        self._last_exp = None
        self._last_res = None

    def run(self):
        cap = None
        while not self.stop_event.is_set():
            want = self.get_index()
            if cap is not None and want != self._cur_index:
                cap.release(); cap = None
            if cap is None:
                if not HAS_CV2:
                    self.status_cb("RGB: 无 cv2 库")
                    time.sleep(2); continue
                cap = cv2.VideoCapture(want, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap.release(); cap = None
                    self.status_cb(f"RGB: 摄像头 {want} 打不开（按 R 切换序号）")
                    time.sleep(1.5)
                    continue
                self._cur_index = want
                self.status_cb(f"RGB: 已连接 (index={want})")
                if self.get_resolution is not None:
                    rv = self.get_resolution()
                    if rv:
                        try:
                            cap.set(cv2.CAP_PROP_FRAME_WIDTH, rv[0])
                            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, rv[1])
                        except Exception:
                            pass
                if self.get_exposure is not None:
                    self._last_exp = None
            if self.get_resolution is not None:
                rv = self.get_resolution()
                if rv != self._last_res:
                    self._last_res = rv
                    if cap is not None:
                        cap.release(); cap = None      # 分辨率变化 → 重连
            if self.get_exposure is not None:
                ev = self.get_exposure()
                if ev != self._last_exp:
                    self._last_exp = ev
                    try:
                        if ev is None:
                            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)   # 自动
                        else:
                            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)   # 手动
                            cap.set(cv2.CAP_PROP_EXPOSURE, ev)
                    except Exception:
                        pass
            ok, frame = cap.read()
            if not ok or frame is None:
                cap.release(); cap = None
                self.status_cb("RGB: 读取失败，重连中…")
                time.sleep(0.4)
                continue
            try:
                frame_rgb = (cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                             if HAS_CV2 else frame)
            except Exception:
                frame_rgb = frame
            # 不翻转（2026-10-16 定案 B）：全链统一"镜像向"（照镜子：人在哪边、
            # 画面/文件里也在哪边）。RGB 原始读出即镜像向，直发本方向；
            # 深度端翻一次（DeviceModule.flip=[True]）对齐到同一方向，D2C 取色一致。
            # 见 问题跟踪/问题跟踪表.md BUG-010。
            # 注：垃圾区裁剪只在输出端做（core.contracts.crop_for_output），此处不裁。
            self.bus.publish("rgb.frame", RgbFrame(data=frame_rgb, t=time.time()))
        if cap is not None:
            cap.release()


class CaptureThread(threading.Thread):
    def __init__(self, link, bus, stop_event, flip_state=None):
        super().__init__(daemon=True)
        self.link = link
        self.bus = bus
        self.stop_event = stop_event
        self.flip_state = flip_state  # list[bool]，动态切换
        self.index = 0

    def run(self):
        while not self.stop_event.is_set():
            try:
                f = self.link.grab_frame(timeout=0.5)
                if f is None:
                    time.sleep(0.01)
                    continue
                d = decode_frame(f)
                if self.flip_state is not None and self.flip_state[0]:
                    d = np.ascontiguousarray(d[:, ::-1])   # 镜像向对齐（定案 B 默认开；见 DeviceModule.__init__）
                self.index += 1
                self.bus.publish("depth.frame",
                                 DepthFrame(data=d, index=self.index, t=time.time()))
            except Exception:
                time.sleep(0.05)

# ---------------- 模块壳 ----------------
class DeviceModule:
    """device 功能模块（Module 协议）。"""
    name = "device"
    version = "1.1.3"

    def __init__(self):
        self.link = None
        self.ctx = None
        self.stop_evt = threading.Event()
        # 深度水平翻转：默认开启（2026-10-16 用户拍板 B：出图与预览同向）。
        # 全链统一"镜像向"（照镜子：人在哪边、画面/文件里也在哪边）：
        #   RGB 端直发原始（readout 即镜像向）＋ 深度端翻一次 flip(rawD) → 两侧同向，
        #   D2C 像素原样映射保持一致；预览直出（与保存/导出天然一致）。
        # 见 问题跟踪/问题跟踪表.md BUG-010。
        # 注：「镜像 (M)」按钮已改为预览翻面对比（显示层，不影响此处数据）。
        self.flip = [True]
        self.rgb_index = [DEFAULT_RGB_INDEX]
        self.rgb_exposure = [None]
        self.rgb_res = [None]
        self.ready_msgs = []

    def setup(self, ctx: ModuleContext):
        self.ctx = ctx
        ctx.bus.subscribe("setting.exposure", self.set_exposure)
        ctx.bus.subscribe("setting.resolution", self.set_resolution)
        ctx.log(f"[device] 就绪 v{self.version}", True)

    def start(self):
        bus = self.ctx.bus
        self.link = AstraLink()
        ok, msg = self.link.connect()
        if not ok:
            bus.publish("module.log", (f"[device] 连接失败: {msg}", False))
            bus.publish("device.status", DeviceStatus(connected=False, info=msg))
            return
        ok2, msgs = self.link.ensure_ready()
        self.ready_msgs = msgs
        bus.publish("device.status", DeviceStatus(connected=True, streaming=bool(ok2), info=msg))
        for m in msgs[-4:]:
            bus.publish("module.log", (f"[device] {m}", bool(ok2)))
        self.cap = CaptureThread(self.link, bus, self.stop_evt, self.flip)
        self.cap.start()
        self.rgb_thread = RGBThread(
            bus, self.stop_evt,
            lambda s: bus.publish("rgb.status", s),
            lambda: self.rgb_index[0],
            get_exposure=lambda: self.rgb_exposure[0],
            get_resolution=lambda: self.rgb_res[0])
        self.rgb_thread.start()

    def stop(self):
        """应用收尾（与设备绑定）：关红外 → 停线程 → 释放 USB。

        关红外链（ir_off）：停流 → 关激光 → 停读线程；
        协议关闭失败 → dev.reset() 物理兜底（重新枚举，IR 必断）。
        """
        self.stop_evt.set()          # CaptureThread/RGBThread 退出循环
        ok = True
        if self.link is not None and self.link.dev is not None:
            try:
                ok, msgs = self.link.ir_off()
                if self.ctx:
                    for m in msgs:
                        self.ctx.bus.publish("module.log", (f"[device] {m}", ok))
            except Exception as e:
                ok = False
                if self.ctx:
                    self.ctx.bus.publish("module.log", (f"[device] 关红外异常: {e}", False))
            if not ok:
                # 兜底：协议关闭失败 → USB reset 物理断红外
                try:
                    self.link.dev.reset()
                    if self.ctx:
                        self.ctx.bus.publish("module.log",
                            ("[device] 协议关闭失败，已 USB reset 兜底", True))
                except Exception:
                    pass
        time.sleep(0.1)
        try:
            if self.link and self.link.dev is not None:
                usb.util.dispose_resources(self.link.dev)
        except Exception:
            pass

    # ---- 对外 API ----
    def set_flip(self, v):
        self.flip[0] = bool(v)

    def get_flip(self):
        return self.flip[0]

    def set_rgb_index(self, i):
        self.rgb_index[0] = int(i)

    def get_rgb_index(self):
        return self.rgb_index[0]

    def set_exposure(self, v):
        self.rgb_exposure[0] = v

    def set_resolution(self, rv):
        self.rgb_res[0] = rv
