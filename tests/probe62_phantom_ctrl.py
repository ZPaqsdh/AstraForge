# -*- coding: utf-8 -*-
"""probe62 幻影列修复 + 转台真连接 —— v0.2.9 验证（无设备硬要求）

A) 幻影列（BUG-013）：
  ① 判向（发布向帧=R / 原生向帧=L），裁剪后输出帧不再检出幻影
  ② 输出帧幻影列清零、画幅保持 479×619、其余列零改动
  ③ 点云差异 == 幻影列有效点数（精确核对）
  ④ 无幻影帧不误伤（合成帧原样）
B) 转台真连接（BUG-014）：
  ⑤ 未握手 → 自动扫描被拒
  ⑥ 非控制器串口/不存在串口 → 连接失败（不假连接）
  ⑦ 串口列表过滤蓝牙
  ⑧ 模拟控制器（异步假串口）→ WHO 握手成功 → 连接/自动扫描走通
用法：python tests/probe62_phantom_ctrl.py
"""
import sys
import time
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.contracts import detect_phantom_side, crop_for_output  # noqa: E402
from core import cloudmath as cm                                # noqa: E402

WS = Path(str(Path(__file__).resolve().parents[2]))
results = []


def item(name, ok, info=''):
    results.append((name, bool(ok)))
    print(('PASS ' if ok else 'FAIL ') + name + (f'  | {info}' if info else ''), flush=True)


# ============ A) 幻影列 ============
stored = np.load(str(WS / '扫描输出/turntable_20261013_162326/frame_000.npy'))  # 发布向布局：垃圾左 / 幻影右
native = np.ascontiguousarray(stored[:, ::-1])                                   # 原生布局：幻影左 / 垃圾右

side_pub = detect_phantom_side(stored)
side_nat = detect_phantom_side(native)
item('A① 判向：发布向帧=R / 原生向帧=L', side_pub == 'R' and side_nat == 'L',
     f'{side_pub}/{side_nat}')

dep_pub, _ = crop_for_output(stored, None)
dep_pub = np.ascontiguousarray(dep_pub)
item('A① 裁剪后输出帧不再检出幻影', detect_phantom_side(dep_pub) is None,
     f'shape {dep_pub.shape}')

item('A② 画幅保持 479×619', dep_pub.shape == (479, 619), dep_pub.shape)
item('A② 幻影列（末列）已清零', bool((dep_pub[:, -1] == 0).all()),
     f'原非零 {int((stored[1:, -1] > 0).sum())} 行')

manual = np.ascontiguousarray(stored[1:, 21:])          # 仅裁剪、未清幻影
item('A② 其余列零改动', bool((dep_pub[:, :-1] == manual[:, :-1]).all()))

phant_valid = (manual[:, -1] > 0) & (manual[:, -1] < 4000)
n_expect = int(phant_valid.sum())
diff = len(cm.depth_to_points(manual, 1.0)) - len(cm.depth_to_points(dep_pub, 1.0))
item('A③ 点云差异 == 幻影列有效点数', diff == n_expect,
     f'差异 {diff} vs 预期 {n_expect}（该列就是"薄片"的 479 点来源）')

dep_nat, _ = crop_for_output(native, None)
dep_nat = np.ascontiguousarray(dep_nat)
man_nat = np.ascontiguousarray(native[1:, :-21])
item('A④ 原生向帧同理（首列清零、其余不动）',
     bool((dep_nat[:, 0] == 0).all()) and bool((dep_nat[:, 1:] == man_nat[:, 1:]).all()))

syn = np.full((479, 619), 900, np.uint16)
item('A④ 合成满帧不触发', detect_phantom_side(syn) is None)
out_syn, _ = crop_for_output(syn, None)
item('A④ 合成满帧输出原样', bool((np.asarray(out_syn) == syn).all()))

# ============ B) 转台真连接 ============
import shell  # noqa: E402


class _StubBus:
    def publish(self, *a, **k):
        pass


class _StubRec:
    def tt_shoot(self, step_deg=15.0, cam_dist=0.0):
        return 0


class _StubPipe:
    bus = _StubBus()

    def get(self, name):
        return _StubRec() if name == 'recorder' else None


bridge = shell.Bridge(_StubPipe())

r = bridge.api_tt_auto(port='COM1', step_deg=15.0)
item('B⑤ 未握手 → 自动扫描被拒', r.get('ok') is False and '未连接' in str(r.get('error', '')),
     str(r.get('error'))[:52])

r2 = bridge.api_tt_connect(port='COM_DOES_NOT_EXIST_99')
item('B⑥ 不存在串口 → 连接失败', r2.get('ok') is False, str(r2.get('error'))[:52])

r3 = bridge.api_tt_connect(port='COM1')
item('B⑥ COM1（非控制器）→ 连接失败', r3.get('ok') is False, str(r3.get('error'))[:52])

st = bridge.api_tt_connect_status()
item('B⑥ 失败后状态=未连接', st.get('connected') is False)

r4 = bridge.api_serial_ports()
item('B⑦ 串口列表可用且过滤蓝牙', r4.get('ok') is True,
     f"候选 {len(r4.get('ports') or [])} / 过滤蓝牙 {r4.get('filtered', 0)}")

# B⑧ 模拟控制器：注入假 serial（WHO → ASTRATT 应答；ROT → READY）走通全链
try:
    real_serial = sys.modules.get('serial')
    import serial as _rs
    real_serial = _rs
except Exception:
    real_serial = None

fake = types.ModuleType('serial')


class _FakeSerial:
    def __init__(self, port, baud, timeout=1.0):
        self.port = port
        self._q = [b'ASTRATT:TT-SIM:0.1\n']

    def reset_input_buffer(self):
        pass

    def write(self, data):
        return len(data)

    def flush(self):
        pass

    def readline(self):
        return self._q.pop(0) if self._q else b'READY\n'

    def close(self):
        pass


fake.Serial = _FakeSerial
sys.modules['serial'] = fake
try:
    rc = bridge.api_tt_connect(port='COMSIM')
    item('B⑧ 假控制器握手成功（ASTRATT 识别）',
         rc.get('ok') is True and 'ASTRATT' in str(rc.get('device', '')), str(rc.get('device')))
    st2 = bridge.api_tt_connect_status()
    item('B⑧ 状态=已连接（端口/身份）', st2.get('connected') is True and st2.get('port') == 'COMSIM',
         f"{st2.get('port')} / {st2.get('device')}")
    ra = bridge.api_tt_auto(port='COMSIM', step_deg=360.0, wait=0.0)
    item('B⑧ 已握手 → 自动扫描放行', ra.get('ok') is True and ra.get('on') is True, ra)
    time.sleep(0.8)
    st3 = bridge.api_tt_auto_status()
    item('B⑧ 单步自动扫描正常收尾', st3.get('on') is False, st3)
    rd = bridge.api_tt_disconnect()
    st4 = bridge.api_tt_connect_status()
    item('B⑧ 断开 → 未连接', rd.get('ok') is True and st4.get('connected') is False)
finally:
    if real_serial is not None:
        sys.modules['serial'] = real_serial
    else:
        sys.modules.pop('serial', None)

print()
print('===== probe62 结果（v0.2.9 幻影列 + 转台真连接） =====')
allok = len(results) > 0
for name, ok in results:
    print(('PASS ' if ok else 'FAIL ') + name)
    allok = allok and ok
print('===== ' + ('全部通过' if allok else '存在失败项') + ' =====')
sys.exit(0 if allok else 1)
