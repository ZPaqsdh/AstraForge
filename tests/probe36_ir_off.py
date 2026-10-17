# -*- coding: utf-8 -*-
"""probe36：真机验证「关红外链」（2026-10-14 用户需求：关闭应用=设备下线）。

流程：connect → ensure_ready（红外开，保持 4 秒供肉眼观察）
     → ir_off()（停流+关激光+停读线程，逐步打印命令返回）
     → 重新 connect + 读 3 帧（验证设备没被关变砖）
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.device.module import AstraLink, decode_frame

print("=" * 56)
print("probe36：关红外链真机验证")
print("=" * 56)

lk = AstraLink()
ok, msg = lk.connect()
print(f"① connect: {ok} {msg}")
if not ok:
    sys.exit(1)

ok2, msgs = lk.ensure_ready()
print(f"② ensure_ready: {ok2}")
for m in msgs:
    print(f"    - {m}")
if not ok2:
    print("!! ensure_ready 失败，无法继续")
    sys.exit(1)

print("\n>>> 红外/激光应已开启 —— 保持 4 秒（可肉眼观察 IR 投影）")
time.sleep(4)

print("\n③ ir_off()（关红外链）:")
ok3, off_msgs = lk.ir_off()
for m in off_msgs:
    print(f"    - {m}")
print(f"    结果: ok={ok3}")

if not ok3:
    print("!! 协议关闭未全部 FRESH —— 需检查参数值/或走 reset 兜底")

import usb.util
usb.util.dispose_resources(lk.dev)
lk.dev = None
time.sleep(1.0)

print("\n④ 复连验证（确认设备没被关变砖）:")
lk2 = AstraLink()
ok4, msg4 = lk2.connect()
print(f"    connect: {ok4} {msg4}")
if ok4:
    ok5, msgs5 = lk2.ensure_ready()
    print(f"    ensure_ready: {ok5}")
    frames = 0
    t0 = time.time()
    while time.time() - t0 < 3 and frames < 3:
        f = lk2.grab_frame(timeout=0.6)
        if f is not None:
            d = decode_frame(f)
            frames += 1
            print(f"    读到帧 {frames}: {d.shape} {d.dtype} 有效像素="
                  f"{int((d > 0).sum())}")
    ok6, off2 = lk2.ir_off()
    print(f"    关闭: ok={ok6}")
    for m in off2:
        print(f"      - {m}")
    usb.util.dispose_resources(lk2.dev)
    print(f"\n最终: 读到 {frames} 帧 —— {'设备完好 ✓' if frames >= 3 else '复连异常 ✗'}")
print("=" * 56)
