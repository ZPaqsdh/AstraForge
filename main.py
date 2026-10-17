# -*- coding: utf-8 -*-
"""AstraForge 星铸 — 程序入口：装配模块管线 → 启动主窗口。

用法：python main.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.pipeline import Pipeline
from core.events import EventBus
from core.contracts import ModuleContext
from ui.main_window import MainWindow


def load_settings():
    """全局设置（M5 后由 calib/settings 模块接管写回；当前读旧标定文件）。"""
    s = {"mm_per_shift": 1.0}
    for cf in (ROOT / "data" / "标定.json", ROOT.parent / "标定.json"):
        try:
            if cf.exists():
                v = json.loads(cf.read_text(encoding="utf-8")).get("mm_per_shift")
                if v and 0.1 < float(v) < 10:
                    s["mm_per_shift"] = float(v)
                    break
        except Exception:
            pass
    return s


def main():
    bus = EventBus()
    pipe = Pipeline(ROOT, bus)
    pipe.load_all_modules()

    win = MainWindow(pipe)

    ctx = ModuleContext(bus=bus, device=None, settings=load_settings(),
                        log=win.log, data_dir=ROOT / "data", root_dir=ROOT,
                        ui_root=win)
    pipe.setup_all(ctx)

    # 状态 → UI 标签（经缓存，线程安全）
    bus.subscribe("device.status", lambda s: win.set_dev_status(
        f"设备: {'深度流运行中' if s.streaming else ('已连接' if s.connected else '未连接')}"))
    bus.subscribe("rgb.status", lambda s: win.set_rgb_status(s))

    win.build_preview()                 # preview 模块已 setup，建画面部件

    # measure 模块挂接到深度画布
    pv = win._pv()
    if pv is not None:
        m = pipe.get("measure")
        cal = pipe.get("calib")
        if m is not None:
            m.attach(pv.depth_canvas,
                     get_depth=lambda: pv.depth,
                     get_mms=lambda: cal.get() if cal else 1.0,
                     lb_hint=pv.lb_hover)

    # 快捷键
    win.bind("s", lambda e: win.act_save())
    win.bind("p", lambda e: win.act_export())
    win.bind("c", lambda e: win.act_continuous())
    win.bind("l", lambda e: win.act_measure())
    win.bind("g", lambda e: win.toggle_gray())
    win.bind("m", lambda e: win.toggle_mirror())
    win.bind("<space>", lambda e: win.act_pause())
    win.bind("q", lambda e: win.on_close())
    win.bind("<Escape>", lambda e: win.on_close())

    pipe.start_all()                    # device 模块此时真连设备开流

    win.refresh_tick()
    try:
        win.mainloop()
    finally:
        try:
            pipe.stop_all()
        except Exception:
            pass


if __name__ == "__main__":
    main()
