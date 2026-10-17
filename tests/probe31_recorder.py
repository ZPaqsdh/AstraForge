#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe31_recorder.py — recorder + calib 模块真机验证（M5）
真机出帧 → 快照保存 / 点云导出 / 标定读写与热更新事件 全链路。
"""
import sys, time, os
from pathlib import Path

ROOT = Path(str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))

from core.pipeline import Pipeline
from core.events import EventBus
from core.contracts import ModuleContext

bus = EventBus()
calib_events = []
bus.subscribe("calib.changed", lambda v: calib_events.append(v))
bus.subscribe("module.log", lambda p: None)   # 静默

pipe = Pipeline(ROOT, bus)
pipe.load_all_modules()
print("① 模块:", list(pipe.modules), flush=True)

ctx = ModuleContext(bus=bus, device=None,
                    settings={"mm_per_shift": 1.0, "out_dir": str(ROOT.parent / "扫描输出")},
                    log=lambda m, ok: None,
                    data_dir=ROOT / 'data', root_dir=ROOT)
pipe.setup_all(ctx)
pipe.start_all()
print("② 收帧 2 秒...", flush=True)
time.sleep(2.0)

rec = pipe.get("recorder")
cal = pipe.get("calib")

# 快照
base = rec.save_snapshot()
assert base, "快照失败"
files = [f for f in os.listdir(os.path.dirname(base))
         if os.path.basename(base) in f]
print(f"③ 快照: {len(files)} 个文件 -> {[os.path.basename(f) for f in files]}", flush=True)
assert any(f.endswith('.npy') for f in files) and any(f.endswith('_rgb.png') for f in files)

# 点云导出
ply = rec.export_cloud()
assert ply and os.path.exists(ply)
sz = os.path.getsize(ply)
print(f"④ 点云导出: {os.path.basename(ply)} ({sz} bytes)", flush=True)

# 标定读写（写当前值，验证写盘+事件，无副作用）
ok = cal.set_and_save(cal.get())
assert ok and len(calib_events) == 1
cp = ROOT / 'data' / '标定.json'
print(f"⑤ 标定: 写盘 {cp.exists()} | calib.changed 事件 {calib_events}", flush=True)

# 转台采集 API（3 帧快速冒烟）
rec.tt_start()
for _ in range(3):
    rec.tt_shoot(step_deg=15.0, cam_dist=500.0)
    time.sleep(0.3)
tt_dir = rec.tt_finish()
assert tt_dir and os.path.exists(os.path.join(tt_dir, 'manifest.json'))
man = open(os.path.join(tt_dir, 'manifest.json'), encoding='utf-8').read()
print(f"⑥ 转台冒烟: {os.path.basename(tt_dir)} 帧数=3 manifest={len(man)}B", flush=True)

pipe.stop_all()
print("RECORDER+CALIB OK", flush=True)
