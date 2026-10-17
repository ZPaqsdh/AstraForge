# -*- coding: utf-8 -*-
"""probe63 出厂内参落地 —— BUG-015 · v0.2.10 验证（无设备 · 纯离线）

用法：python tests/probe63_engine_intrinsics.py [ship]   （ship = 以发行 code/ 为 ROOT）

背景：代码内参长期为硬编码 FX=FY=572 / CX,CY=(320,240)（无出处；且 (320,240) 恰为图像
正中心 = 占位值特征）。相机出厂标定一直在本机闪存里（dump @0x70000，120B =
OBCameraParams 30×float32，串号与本机标签吻合）。2026-10-16 拍板 A：改用出厂值。
  深度 l_intr = 580.703 / 580.703 / 318.163 / 249.847
  彩色 r_intr = 601.275 / 601.275 / 324.221 / 241.019 ；外参 t = [24.571, -0.197, 0.308] mm
影响：横向尺度由偏小 1.5% 归正；cy 偏上 9.847px（≈17mm@1m）归正——纵向几何偏差主因。

验证项（无设备）：
  ① 闪存出厂标定复核：dump @0x70000 解析出的深度内参 == cloudmath 常量（逐字段 <1e-3）
  ② 串号一致性：dump @0x30000 含 '190429200680'（== 机标签 C19042920068）
  ③ 唯一源：全部业务 .py 里只有 core/cloudmath.py 定义内参常量（无 572/320/240 副本）
  ④ 主点非图像中心：证明确为标定值而非占位（|cx-320|、|cy-240| 均 > 1px）
  ⑤ 裁剪继承：cxcy_for_shape 随新基准平移（(479,619)→(CX-21,CY-1)，col0=0→(CX,CY-1)）
  ⑥ 影响量化（存档真实 L 帧）：旧/新口径点云逐点差的中位与理论（1.5% 尺度 + 9.847px 纵移）对照
"""
import re
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if len(sys.argv) > 1 and sys.argv[1] == 'ship':
    ROOT = Path(str(Path(__file__).resolve().parents[2] / '发行' / 'AstraForge' / 'code'))
    print('[63] 目标 = 发行态 code/')
sys.path.insert(0, str(ROOT))
from core import cloudmath as cm          # noqa: E402

WS = Path(str(Path(__file__).resolve().parents[2]))
DUMP = WS / '固件研究_2026-10-12' / '嵌入固件镜像' / 'flash_dump_old_unit_1MB.bin'
SERIAL = b'190429200680'
results = []


def item(name, ok, info=''):
    results.append((name, bool(ok)))
    print(('PASS ' if ok else 'FAIL ') + name + (f'  | {info}' if info else ''), flush=True)


# ---- ① 闪存出厂标定复核 ----
print(f'[63] cloudmath 内参：FX=FY={cm.FX}  CX={cm.CX}  CY={cm.CY}')
print(f'[63] （旧硬编码口径 572.0 / 320.0 / 240.0）')
c_intr = None
if DUMP.exists():
    b = DUMP.read_bytes()
    f = struct.unpack('<30f', b[0x70000:0x70000 + 120])
    l_intr = f[0:4]        # 深度（左/IR）：fx fy cx cy
    r_intr = f[4:8]        # 彩色（右）：fx fy cx cy
    t_vec = f[17:20]       # 外参平移 r2l（mm）
    l_k = f[20:25]
    c_intr = (l_intr, r_intr, t_vec, l_k)
    got = (float(cm.FX), float(cm.FY), float(cm.CX), float(cm.CY))
    ok = all(abs(a - b) < 1e-3 for a, b in zip(got, l_intr))
    item('① 出厂标定复核：dump@0x70000 深度内参 == cloudmath 常量', ok,
         f'dump {[round(v, 3) for v in l_intr]} vs 代码 {[round(v, 3) for v in got]}')
    print(f'[63·信息] 出厂彩色内参 fx/fy/cx/cy = {[round(v, 3) for v in r_intr]}'
          f'（D2C 用，TODO-012）')
    print(f'[63·信息] 出厂外参 t(r2l) = {[round(v, 3) for v in t_vec]} mm'
          f'（基线 {round(float(np.linalg.norm(t_vec)), 2)}mm）｜畸变 l_k = '
          f'{[round(v, 4) for v in l_k]}')
    # ② 串号
    idx = b.find(SERIAL)
    item('② 串号一致性：dump 含本机标签串号', idx >= 0,
         f'"{SERIAL.decode()}" @ 0x{idx:X}' if idx >= 0 else '未找到')
else:
    item('① 出厂标定复核', False, f'缺 dump {DUMP}')
    item('② 串号一致性', False, '缺 dump')

# ---- ③ 唯一源：只有 cloudmath.py 定义内参常量 ----
pat = re.compile(r'^\s*(FX|FY|CX|CY)\b[^=(]*=.*[0-9]')
src_root = ROOT if ROOT.name == 'code' else ROOT
hits = []
for p in src_root.rglob('*.py'):
    rel = p.relative_to(src_root).as_posix()
    if rel.startswith(('tests/', 'ui-web/', '__pycache__', '_tmp/', 'installer/')) \
            or '/__pycache__/' in rel:
        continue
    for i, line in enumerate(p.read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
        if pat.match(line) and 'cm.' not in line:
            hits.append(f'{rel}:{i}')
ok3 = len(hits) >= 1 and all('core/cloudmath.py' in h for h in hits)
item('③ 唯一源：业务代码仅 core/cloudmath.py 定义内参常量', ok3,
     f'命中 {hits}' if hits else '零命中（内参丢失？）')

# ---- ④ 主点非图像中心（标定值特征） ----
dx_px, dy_px = abs(cm.CX - 320.0), abs(cm.CY - 240.0)
ok4 = dx_px > 1.0 and dy_px > 1.0
item('④ 主点≠图像中心（证明为标定值而非占位）', ok4,
     f'|cx-320|={dx_px:.3f}px  |cy-240|={dy_px:.3f}px')

# ---- ⑤ 裁剪继承 ----
t1, t2, t3 = cm.cxcy_for_shape((480, 640)), cm.cxcy_for_shape((479, 619)), \
    cm.cxcy_for_shape((479, 619), col0=0)
exp = ((cm.CX, cm.CY), (cm.CX - 21, cm.CY - 1), (cm.CX, cm.CY - 1))
ok5 = all(abs(a - b) < 1e-6 for got_, want in ((t1, exp[0]), (t2, exp[1]), (t3, exp[2]))
          for a, b in zip(got_, want))
item('⑤ 裁剪继承新基准：全画幅 / 左裁(CX-21,CY-1) / 右裁col0=0', ok5,
     f'{t1} {t2} {t3}')

# ---- ⑥ 影响量化（存档真实帧） ----
Lf = WS / '扫描输出' / 'turntable_20261013_162326' / 'frame_000.npy'
if Lf.exists():
    from core.contracts import crop_for_output
    dep = np.load(str(Lf)).astype(np.float32)
    dep2, _ = crop_for_output(dep, None)
    dep2 = np.ascontiguousarray(dep2)
    new = cm.depth_to_points(dep2, 1.0, col0=21)
    FXo, FYo, CXo, CYo = cm.FX, cm.FY, cm.CX, cm.CY
    cm.FX, cm.FY, cm.CX, cm.CY = 572.0, 572.0, 320.0, 240.0
    try:
        old = cm.depth_to_points(dep2, 1.0, col0=21)
    finally:
        cm.FX, cm.FY, cm.CX, cm.CY = FXo, FYo, CXo, CYo
    n = min(len(old), len(new))
    d = new[:n] - old[:n]
    z = dep2[(dep2 > 0) & (dep2 < 4000)].astype(np.float64)
    zmed = float(np.median(z)) if len(z) else 0.0
    # 理论：横向尺度比 FX_old/FX_new；纵向平移 = (CY_new-CY_old)*z/FY_new（y 轴几何翻转 → 符号反）
    scale = 572.0 / 580.703
    dy_th = (249.847 - 240.0) * zmed / 580.703
    print(f'[63·信息] 存档 L 帧 z 中位 {zmed:.0f}mm：新旧点云中位 '
          f'|ΔX|={np.median(np.abs(d[:, 0])):.1f}mm |ΔY|={np.median(np.abs(d[:, 1])):.1f}mm'
          f' |ΔZ|={np.median(np.abs(d[:, 2])):.2f}mm')
    print(f'[63·信息] 理论：横向尺度 ×{scale:.5f}（新比旧小 {(1-scale)*100:.2f}%）｜'
          f'纵向平移 {dy_th:.1f}mm@{zmed:.0f}mm（9.847px）｜Z 不受内参影响（应 ≈0）')
    ok6 = abs(np.median(d[:, 2])) < 0.5 and np.median(np.abs(d[:, 1])) > 0.5 * dy_th
    item('⑥ 影响量化：Z 零变化 + 横向/纵向按新基准重标（存档真帧）', ok6,
         f'|ΔZ|中位 {np.median(np.abs(d[:, 2])):.2f}mm；|ΔY|中位 {np.median(np.abs(d[:, 1])):.1f}mm')
else:
    print('[63] 跳过 ⑥（无存档帧）')

print()
print('===== probe63 结果（BUG-015 出厂内参落地 · v0.2.10） =====')
allok = len(results) > 0
for name, ok in results:
    print(('PASS ' if ok else 'FAIL ') + name)
    allok = allok and ok
print('===== ' + ('全部通过' if allok else '存在失败项') + ' =====')
sys.exit(0 if allok else 1)
