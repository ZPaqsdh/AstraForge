#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe29_device.py — device 模块真机验证（M4）
加载 device 模块 → 连设备开流 → 订阅事件 3 秒 → 统计深度/RGB 帧率与形状。
"""
import sys, time
from pathlib import Path

ROOT = Path(str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))

from core.pipeline import Pipeline
from core.events import EventBus
from core.contracts import ModuleContext

bus = EventBus()
stats = {"d": 0, "r": 0, "d_shape": None, "r_shape": None, "dtype": None}
bus.subscribe("depth.frame", lambda f: (
    stats.__setitem__("d", stats["d"] + 1),
    stats.__setitem__("d_shape", f.data.shape),
    stats.__setitem__("dtype", str(f.data.dtype))))
bus.subscribe("rgb.frame", lambda f: (
    stats.__setitem__("r", stats["r"] + 1),
    stats.__setitem__("r_shape", f.data.shape)))
bus.subscribe("rgb.status", lambda s: print("  rgb.status:", s, flush=True))
bus.subscribe("module.log", lambda p: print("  log:", p[0], flush=True))

pipe = Pipeline(ROOT, bus)
pipe.load_all_modules()
print("① 已加载模块:", list(pipe.modules), flush=True)

ctx = ModuleContext(bus=bus, device=None, settings={},
                    log=lambda m, ok: print("  log:", m, flush=True),
                    data_dir=ROOT / 'data', root_dir=ROOT)
pipe.setup_all(ctx)
pipe.start_all()
print("② device.start 完成，收流 3 秒...", flush=True)
time.sleep(3.0)
print(f"③ depth.frame: {stats['d']} 帧 ({stats['d']/3:.1f} fps) "
      f"shape={stats['d_shape']} dtype={stats['dtype']}", flush=True)
print(f"④ rgb.frame:   {stats['r']} 帧 ({stats['r']/3:.1f} fps) "
      f"shape={stats['r_shape']}", flush=True)
pipe.stop_all()
print("⑤ 已停止", flush=True)
assert stats["d"] > 30, "深度帧太少！"
assert stats["d_shape"] == (480, 640), f"深度形状异常: {stats['d_shape']}"
print("DEVICE MODULE OK", flush=True)
