# -*- coding: utf-8 -*-
"""probe71 — 方向口径（BUG-019）：数据正常方向，镜像仅预览。

无设备纯计算，验证：
  1) _preview_mirror 默认关；_pv_flip 关=原样、开=左右翻
  2) _pv_crosshair 随预览镜像翻转
  3) DeviceModule.flip 默认 False；set_flip 不再改数据方向
  4) _pv_display_depth 只裁列 + 仅在预览镜像时翻转
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import shell  # noqa: E402
from modules.device.module import DeviceModule  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


# 1) 预览镜像默认关 + 翻转方向
check("preview_mirror 默认关闭", shell._preview_mirror["on"] is False,
      str(shell._preview_mirror))
arr = np.arange(12, dtype=np.uint16).reshape(3, 4)
shell._preview_mirror["on"] = False
check("镜像关：_pv_flip 原样", np.array_equal(shell._pv_flip(arr), arr))
shell._preview_mirror["on"] = True
check("镜像开：_pv_flip 左右翻", np.array_equal(shell._pv_flip(arr), arr[:, ::-1]))
shell._preview_mirror["on"] = False

# 2) 十字准星随预览镜像
from core import cloudmath as cm  # noqa: E402
cx0 = cm.CX - shell._PV_CROP_L
cx_m = (shell._PV_RAW_W - 1 - shell._PV_CROP_L) - cx0
check("镜像关：准星用原始主点", shell._pv_crosshair(None)[0] == cx0,
      f"{shell._pv_crosshair(None)[0]} == {cx0}")
shell._preview_mirror["on"] = True
check("镜像开：准星镜像", shell._pv_crosshair(None)[0] == cx_m,
      f"{shell._pv_crosshair(None)[0]} == {cx_m}")
shell._preview_mirror["on"] = False

# 3) 设备数据方向固定
dev = DeviceModule()
check("DeviceModule.flip 默认 False", dev.flip[0] is False)
dev.set_flip(True)
check("set_flip(True) 不再翻数据", dev.flip[0] is False)

# 4) 显示层：裁 21 列，镜像才翻转
raw = np.arange(480 * 640, dtype=np.uint32).reshape(480, 640)
disp = shell._pv_display_depth(raw.copy())
check("显示裁剪 640→619", disp.shape == (480, 619), str(disp.shape))
check("镜像关：显示不翻", np.array_equal(disp[:, 0], raw[:, shell._PV_CROP_L]))
shell._preview_mirror["on"] = True
disp2 = shell._pv_display_depth(raw.copy())
check("镜像开：显示翻转", np.array_equal(disp2[:, 0], raw[:, -1]))
shell._preview_mirror["on"] = False


# 5) 测距：镜像开/关对同一物理点给出同一距离
class _FakeRec:
    last_depth = None


class _FakeCal:
    def get(self):
        return 1.0


_fd = np.tile(np.linspace(900, 1500, 640, dtype=np.float32), (480, 1))
_fd[:, 40:60] = 1200
_fd[:, 300:320] = 1300
_rec = _FakeRec()
_rec.last_depth = _fd


class _FakePipe:
    def get(self, name):
        return _rec if name == "recorder" else (_FakeCal() if name == "calib" else None)


_b = shell.Bridge(_FakePipe())
shell._preview_mirror["on"] = False
_r1 = _b.api_measure(100, 200, 400, 300)
shell._preview_mirror["on"] = True
# 显示坐标镜像：x' = (W-1) - x
_r2 = _b.api_measure(618 - 100, 200, 618 - 400, 300)
shell._preview_mirror["on"] = False
_d1 = _r1.get("dist_mm")
_d2 = _r2.get("dist_mm")
check("测距：镜像开/关同一点同距离", _d1 is not None and _d2 is not None and abs(_d1 - _d2) < 0.05,
      f"{_d1} vs {_d2}")

ok = all(x[1] for x in results)
print("\n===== probe71 结果 =====")
print(f"{sum(1 for x in results if x[1])}/{len(results)} 通过")
sys.exit(0 if ok else 1)
