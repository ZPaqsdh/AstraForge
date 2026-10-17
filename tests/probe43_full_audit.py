# -*- coding: utf-8 -*-
"""probe43: 全功能真机冒烟审计
逐个实调用后端 API，验证返回值；有副作用的做安全处理（开→关、改→还原）。
不调用：shutdown（会退出）/open_dir（弹资源管理器）/set_export_dir（改用户设置）/fuse（耗时长，已单独验证过）
"""
import sys, time
from pathlib import Path

ROOT = Path(str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
import shell

pipe = shell.build_pipeline()
time.sleep(3.5)
b = shell.Bridge(pipe)

PASS, FAIL, SKIP = [], [], []

def probe(name, method='GET', q=None, body=None, check=None, note=''):
    t0 = time.time()
    try:
        r = b.call(name, method, q or {}, body or {})
        dt = (time.time() - t0) * 1000
        ok = True
        info = ''
        if isinstance(r, dict):
            if r.get('ok') is False:
                ok = False
                info = str(r.get('error'))[:60]
            else:
                keys = [k for k in r.keys() if k != 'ok'][:4]
                info = ','.join(keys)
        elif isinstance(r, tuple):
            info = f'{len(r[1])}B'
        if check:
            chk_ok, chk_info = check(r)
            ok = ok and chk_ok
            info = (info + ' | ' + chk_info).strip(' |')
        (PASS if ok else FAIL).append(f'{name} ({dt:.0f}ms) {info}' + (f'  ← {note}' if note else ''))
    except Exception as e:
        FAIL.append(f'{name} 异常: {type(e).__name__}: {str(e)[:80]}')

# ---------- 只读类 ----------
probe('ping', 'GET', {'msg': 'x'})
probe('state', 'GET')
probe('stats', 'GET')
probe('logs', 'GET', {'n': 5})
probe('frame', 'GET', {'kind': 'depth'}, check=lambda r: (r[1][:2] == b'\xff\xd8', 'JPEG'))
probe('frame', 'GET', {'kind': 'rgb'}, check=lambda r: (r[1][:2] == b'\xff\xd8', 'JPEG'))
probe('pixel', 'GET', {'x': 320, 'y': 240})
probe('about', 'GET')
probe('diag', 'GET')
probe('list_dirs', 'GET')
probe('scan_count', 'GET')
probe('tt_status', 'GET')
probe('tt_auto_status', 'GET')
probe('fuse_progress', 'GET')
probe('serial_ports', 'GET')
probe('check_update', 'GET', note='未配源→预期提示')
probe('heartbeat', 'POST', body={})

# ---------- 设置类（改→还原）----------
probe('set_flip', 'POST', body={'on': False}); probe('set_flip', 'POST', body={'on': True}, note='还原')
probe('set_gray', 'POST', body={'on': True}); probe('set_gray', 'POST', body={'on': False}, note='还原')
probe('set_paused', 'POST', body={'on': True}); probe('set_paused', 'POST', body={'on': False}, note='还原')
probe('set_disp_range', 'POST', body={'lo': 0, 'hi': 2500})
probe('set_perf_mode', 'POST', body={'mode': 'std'})

# ---------- 采集类（产生测试产物）----------
probe('save_snapshot', 'POST', body={}, note='生成快照文件')
probe('export_cloud', 'POST', body={}, note='生成 PLY')
probe('toggle_continuous', 'POST', body={}); time.sleep(0.3)
probe('toggle_continuous', 'POST', body={}, note='关（还原）')

# ---------- 转台类 ----------
probe('tt_shoot', 'POST', body={'step_deg': 15})
probe('tt_shoot', 'POST', body={'step_deg': 15})
probe('tt_finish', 'POST', body={}, note='写 manifest + 目录')

# ---------- 手持扫描类 ----------
probe('scan_start', 'POST', body={})
probe('scan_shoot', 'POST', body={})
probe('scan_shoot', 'POST', body={})
probe('scan_finish', 'POST', body={}, note='写 manifest + 目录')

# ---------- 工具类 ----------
probe('calib_sample', 'GET', {'known_mm': 500, 'roi': 40})
probe('measure', 'POST', body={'x1': 300, 'y1': 220, 'x2': 340, 'y2': 260})

pipe.stop_all()

print('=== 全 API 冒烟审计结果 ===')
print(f'✓ 通过 {len(PASS)} 项 / ✗ 失败 {len(FAIL)} 项')
print('\n--- 通过明细 ---')
for p in PASS:
    print('  ✓', p)
if FAIL:
    print('\n--- 失败明细 ---')
    for f in FAIL:
        print('  ✗', f)
print(f'\n跳过（需人工/有干扰）: shutdown / open_dir / set_export_dir / fuse（已单独验证）')
