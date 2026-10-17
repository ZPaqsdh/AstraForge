# -*- coding: utf-8 -*-
"""probe59 v0.2.8 发行态设置持久化两阶段补测（对应装机清单第4条）

以 发行/AstraForge/code/ 为 ROOT：
  write → 改全部设置 → 落盘 → 退出（进程结束）
  check → 新进程重起（=下次启动）→ 断言全部还原
  clean → 恢复发行版原始设置文件
"""
import json
import shutil
import sys
from pathlib import Path

SHIP = Path(str(Path(__file__).resolve().parents[2] / '发行' / 'AstraForge' / 'code'))
SET_FILE = SHIP / 'data' / '设置.json'
BAK = SHIP / 'data' / '设置.json.shipbak'
ABSENT = SHIP / 'data' / '设置.json.absent'
TEST_OUT = Path(__file__).resolve().parents[2] / '_tools' / '_shiptest_out'

sys.path.insert(0, str(SHIP))
import os
os.chdir(SHIP)

phase = sys.argv[1] if len(sys.argv) > 1 else ''


def do_backup():
    if SET_FILE.exists():
        shutil.copy2(SET_FILE, BAK)
        print('[ship54] 已备份发行设置:', SET_FILE.read_text(encoding='utf-8').strip())
    else:
        ABSENT.write_text('absent')
        print('[ship54] 发行无设置文件（已记录）')


def do_clean():
    if BAK.exists():
        shutil.move(str(BAK), str(SET_FILE))
        print('[ship54] 已恢复发行设置')
    elif ABSENT.exists():
        if SET_FILE.exists():
            SET_FILE.unlink()
        ABSENT.unlink()
    if TEST_OUT.exists():
        shutil.rmtree(TEST_OUT, ignore_errors=True)
        print('[ship54] 测试目录已清')


def do_write():
    import shell
    print('[ship54] ROOT =', shell.ROOT)
    pipe = shell.build_pipeline()
    try:
        b = shell.Bridge(pipe)
        r1 = b.api_set_perf_mode('turbo')
        r2 = b.api_set_disp_range(320, 1700)
        r3 = b.api_set_export_dir(str(TEST_OUT))
        r4 = b.api_set_flip(False)
        st = pipe.get('settings')
        st.set_exposure(-6.0)
        st.set_resolution([640, 480])
        print(f'[ship54] write: {r1.get("mode")} / {r2} / {r3.get("ok")} / {r4.get("preview_mirror")}')
        saved = json.loads(SET_FILE.read_text(encoding='utf-8')) if SET_FILE.exists() else {}
        print('[ship54] 落盘:', json.dumps(saved, ensure_ascii=False))
        need = {'perf_mode', 'disp_range', 'out_dir', 'preview_mirror', 'exposure', 'resolution'}
        missing = need - set(saved)
        print('[ship54] 缺失键:', missing or '无')
        sys.exit(0 if not missing else 1)
    finally:
        try:
            pipe.stop_all()
        except Exception:
            pass


def do_check():
    import shell
    pipe = shell.build_pipeline()          # = 下次启动
    try:
        fus = pipe.get('fusion')
        st = pipe.get('settings')
        rec = pipe.get('recorder')
        dev = pipe.get('device')
        checks = [
            ('性能模式还原 = turbo', getattr(fus, '_perf_mode', None) == 'turbo'),
            ('显示范围还原 = [320, 1700]', list(st.disp_range) == [320.0, 1700.0]),
            ('RGB 曝光还原 = -6.0', st.exposure[0] == -6.0),
            ('RGB 分辨率还原 = [640, 480]', list(st.resolution[0] or []) == [640, 480]),
            ('导出目录还原 = 测试目录', str(rec._out_dir()) == str(TEST_OUT)),
            ('预览镜像还原 = False', shell._preview_mirror['on'] is False),
            ('重播生效 device.rgb_exposure = -6.0', dev.rgb_exposure[0] == -6.0),
        ]
        allok = True
        for name, ok in checks:
            print(('PASS ' if ok else 'FAIL ') + name)
            allok = allok and ok
        print('===== ' + ('发行态设置还原全过' if allok else '存在失败项') + ' =====')
        sys.exit(0 if allok else 1)
    finally:
        try:
            pipe.stop_all()
        except Exception:
            pass


if __name__ == '__main__':
    {'backup': do_backup, 'write': do_write, 'check': do_check, 'clean': do_clean}.get(phase, lambda: print(__doc__))()