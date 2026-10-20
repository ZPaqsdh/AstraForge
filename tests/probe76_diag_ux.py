# -*- coding: utf-8 -*-
"""probe76 —— 设备/驱动诊断链（BUG-025 / BUG-026）。

锁住四件事：
  ① `fast=1` 枚举**绝不调用 PowerShell**（否则拔掉设备时界面每 6 秒卡一次）
  ② 深查失败时**回退 pyusb 结果**，不把"查不动"当"没有设备"
  ③ 缺驱动库时 `driver_state.blockers` 必须给出可执行的原因（界面不再哑灰）
  ④ `device_reset` 是 USB 级复位（不重启软件），没有设备时也返回结构化结果

用法：python tests/probe76_diag_ux.py
"""
import sys
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import shell  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'✅' if ok else '❌'} {name}" + (f"  [{detail}]" if detail else ""))


FOUND = {"ok": True, "fast": True,
         "depth": {"found": True, "pid": "0403", "state": "ready", "service": "WinUSB"},
         "color": {"found": True, "service": "usbvideo"}, "devices": []}
ABSENT = {"ok": False, "fast": True,
          "depth": {"found": False, "state": "absent"},
          "color": {"found": False}, "devices": [], "error": "没设备"}


def bridge():
    b = shell.Bridge(None)
    b._scan_cache = (0.0, None)
    return b


# ---- ① fast 不碰 PowerShell ----
b = bridge()
calls = []
with mock.patch.object(shell.Bridge, "_usb_cameras", return_value=FOUND), \
     mock.patch("subprocess.run", side_effect=lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("不应调用子进程"))):
    t0 = time.time()
    r = b.api_device_scan(fast=1)
    dt = time.time() - t0
check("fast=1 返回已找到设备", r and r.get("depth", {}).get("found") is True)
check("fast=1 不调用 PowerShell", calls == [], f"{dt*1000:.0f}ms")

# ---- ② 深查失败 → 回退 pyusb ----
b = bridge()


def boom(*a, **k):
    raise shell.subprocess.TimeoutExpired(cmd="powershell", timeout=25)


with mock.patch.object(shell.Bridge, "_usb_cameras", return_value=FOUND), \
     mock.patch("subprocess.run", side_effect=boom):
    r = b.api_device_scan(deep=1)
check("深查超时后仍报告设备（回退快查）", r.get("depth", {}).get("found") is True)
check("回退结果带 deep_failed 标记", bool(r.get("deep_failed")))

# 深查失败且快查也没有 → 明确 absent，不抛异常
b = bridge()
with mock.patch.object(shell.Bridge, "_usb_cameras", return_value=None), \
     mock.patch("subprocess.run", side_effect=boom):
    r = b.api_device_scan(deep=1)
check("深查失败且无设备 → absent 不崩", r.get("depth", {}).get("found") is False)

# ---- ③ 缺驱动库时 blockers 说清楚 ----
b = bridge()
fake_pack = {"has_pack": False, "pack_dir": "", "devices": [], "zadig": "", "zadig_ok": False}
with mock.patch.object(shell.Bridge, "_usb_cameras", return_value=FOUND), \
     mock.patch("core.driverpack.summary", return_value=fake_pack), \
     mock.patch("core.driverpack.match_device", return_value=None):
    st = b.api_driver_state()
bl = st.get("blockers") or {}
check("缺库 → blockers.pack 有说明", "pack" in bl and "驱动工具" in bl["pack"])
check("缺库 → 驱动向导不可用（blockers.zadig）", "zadig" in bl)
check("缺库 → can_install=False", st.get("can_install") is False)
check("缺库 → pack_ok/zadig_ok 都是 False", st.get("pack_ok") is False and st.get("zadig_ok") is False)

# 库与设备都在 → 不拦
entry = {"id": "winusb-astra-s-pro-0403", "name": "ASTRA S Pro · WinUSB", "method": "pnputil-inf"}
fake_ok = {"has_pack": True, "pack_dir": "X:/驱动工具", "devices": [entry],
           "zadig": "X:/驱动工具/zadig/zadig.exe", "zadig_ok": True}
b = bridge()
with mock.patch.object(shell.Bridge, "_usb_cameras", return_value=FOUND), \
     mock.patch("core.driverpack.summary", return_value=fake_ok), \
     mock.patch("core.driverpack.match_device", return_value=entry):
    st = b.api_driver_state()
check("库齐 + 设备在 → 无拦截项", st.get("blockers") == {})
check("库齐 + 设备在 → can_install=True", st.get("can_install") is True)

# ---- ④ device_reset 结构化返回（没有 device 模块时不崩）----
b = bridge()
r = b.api_device_reset()
check("没有 device 模块 → device_reset 返回 ok:False + 原因",
      r.get("ok") is False and "未装配" in str(r.get("error", "")))


class _FakeDev:
    """最小设备替身：只验证复位流程顺序，不碰真 USB。"""

    def __init__(self):
        self.link = None
        self.stop_evt = None
        self.calls = []

    def stop(self):
        self.calls.append("stop")

    def start(self):
        self.calls.append("start")


class _FakeBridge(shell.Bridge):
    def __init__(self, dev):
        super().__init__(None)
        self._fake = dev

    def _m(self, name):
        return self._fake if name == "device" else None


dev = _FakeDev()
fb = _FakeBridge(dev)
r = fb.api_device_reset()
check("device_reset 走 stop→start（USB 级复位，不重启软件）",
      dev.calls == ["stop", "start"], "/".join(r.get("steps") or []))
check("device_reset 复位后打不开会返回明确原因",
      r.get("ok") is False and "USB" in str(r.get("error", "")))

print()
passed = sum(1 for _, ok in results if ok)
print(f"[76] {passed}/{len(results)} 通过")
sys.exit(0 if passed == len(results) else 1)
