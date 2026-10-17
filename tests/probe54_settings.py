# -*- coding: utf-8 -*-
"""probe54 设置自动保存/启动还原 端到端验证（两阶段 + 备份还原）

用法：
  python probe54_settings.py backup    # 备份现有 设置.json（测试前置）
  python probe54_settings.py write     # 起真管线 → 改全部设置 → 落盘 → 退出
  python probe54_settings.py check     # 重新起真管线（=下次启动）→ 断言全部还原
  python probe54_settings.py clean     # 还原设置文件与临时目录

覆盖设置：性能模式 / 显示范围 / 导出目录 / RGB曝光 / RGB分辨率 / 预览镜像
"""
import tempfile
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # AstraForge
SET_FILE = ROOT / "data" / "设置.json"
BAK_FILE = ROOT / "data" / "设置.json.probe54bak"
ABSENT_MARK = ROOT / "data" / "设置.json.probe54absent"
TEST_OUT = Path(tempfile.gettempdir()) / 'astraforge' / 'astra-settest-out'

sys.path.insert(0, str(ROOT))


def _phase():
    return sys.argv[1] if len(sys.argv) > 1 else ""


def do_backup():
    if SET_FILE.exists():
        shutil.copy2(SET_FILE, BAK_FILE)
        print("[54] 已备份现有设置文件")
    else:
        ABSENT_MARK.write_text("absent", encoding="utf-8")
        print("[54] 无现有设置文件（已记录）")


def do_clean():
    if BAK_FILE.exists():
        shutil.move(str(BAK_FILE), str(SET_FILE))
        print("[54] 已还原测试前的设置文件")
    elif ABSENT_MARK.exists():
        if SET_FILE.exists():
            SET_FILE.unlink()
        ABSENT_MARK.unlink()
        print("[54] 已删除测试产生的设置文件（测试前不存在）")
    if TEST_OUT.exists():
        shutil.rmtree(TEST_OUT, ignore_errors=True)
        print("[54] 已清理测试导出目录")


def do_write():
    import shell
    pipe = shell.build_pipeline()
    try:
        b = shell.Bridge(pipe)
        r1 = b.api_set_perf_mode("turbo")
        r2 = b.api_set_disp_range(300, 1800)
        r3 = b.api_set_export_dir(str(TEST_OUT))
        r4 = b.api_set_flip(False)
        st = pipe.get("settings")
        st.set_exposure(-6.0)
        st.set_resolution([640, 480])
        print("[54] write:", r1.get("mode"), r2, r3.get("ok"), r4.get("preview_mirror"))
        saved = json.loads(SET_FILE.read_text(encoding="utf-8")) if SET_FILE.exists() else {}
        print("[54] 落盘内容:", json.dumps(saved, ensure_ascii=False))
        need = {"perf_mode", "disp_range", "out_dir", "preview_mirror", "exposure", "resolution"}
        missing = need - set(saved)
        print("[54] 缺失键:", missing or "无")
        sys.exit(0 if not missing else 1)
    finally:
        try:
            pipe.stop_all()
        except Exception:
            pass


def do_check():
    import shell
    pipe = shell.build_pipeline()          # = 下次启动：全部从 设置.json 还原
    try:
        fus = pipe.get("fusion")
        st = pipe.get("settings")
        rec = pipe.get("recorder")
        dev = pipe.get("device")
        checks = [
            ("性能模式还原 = turbo", getattr(fus, "_perf_mode", None) == "turbo"),
            ("显示范围还原 = [300, 1800]", list(st.disp_range) == [300.0, 1800.0]),
            ("RGB 曝光还原 = -6.0", st.exposure[0] == -6.0),
            ("RGB 分辨率还原 = [640, 480]", list(st.resolution[0] or []) == [640, 480]),
            ("导出目录还原 = 测试目录", str(rec._out_dir()) == str(TEST_OUT)),
            ("预览镜像还原 = False", shell._preview_mirror["on"] is False),
            ("重播生效：device.rgb_exposure = -6.0", dev.rgb_exposure[0] == -6.0),
        ]
        allok = True
        for name, ok in checks:
            print(("PASS " if ok else "FAIL ") + name)
            allok = allok and ok
        print("===== " + ("设置还原全部通过" if allok else "存在失败项") + " =====")
        sys.exit(0 if allok else 1)
    finally:
        try:
            pipe.stop_all()
        except Exception:
            pass


if __name__ == "__main__":
    p = _phase()
    if p == "backup":
        do_backup()
    elif p == "write":
        do_write()
    elif p == "check":
        do_check()
    elif p == "clean":
        do_clean()
    else:
        print(__doc__)
