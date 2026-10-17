# -*- coding: utf-8 -*-
"""probe64 采集质量可视化 —— TODO-016 · v0.2.10 验证（无设备 · 合成帧纯计算）

用法：python tests/probe64_quality.py [ship]   （ship = 以发行 code/ 为 ROOT）

被测：shell._frame_quality（后端 `api_quality` 的计算体）——供前端「距离条三段色 /
状态灯 / 质量色谱叠加」用。口径：深度按**显示画幅**解析（裁垃圾带 + 清幻影列 + 镜像），
网格 6×8 与屏幕所见 1:1（前端叠加零换算）。

验证项（无设备）：
  ① 全无效帧 → 红灯 + zone=none + 网格全 0 + 引导文案
  ② 太近（300mm）→ zone=near + 红灯 + 提示"太近"
  ③ 最佳（800mm）且全覆盖 → zone=best + 绿灯 + 有效覆盖≈100%
  ④ 太远（2200mm）→ zone=far + 红灯 + 提示"太远"
  ⑤ 覆盖不足（中央小目标）→ 红灯（有效覆盖 <35%）
  ⑥ 网格对位：只在某格放有效 → 该格 100 且其余 0（显示画幅坐标）
  ⑦ 镜像开关生效：同一帧在镜像开/关下网格左右对调（与屏幕所见一致）
  ⑧ 性能：单帧耗时中位 < 15ms（前端 1.2s 轮询无压力）
"""
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if len(sys.argv) > 1 and sys.argv[1] == 'ship':
    ROOT = Path(str(Path(__file__).resolve().parents[2] / '发行' / 'AstraForge' / 'code'))
    print('[64] 目标 = 发行态 code/')
sys.path.insert(0, str(ROOT))
import shell  # noqa: E402

results = []


def item(name, ok, info=''):
    results.append((name, bool(ok)))
    print(('PASS ' if ok else 'FAIL ') + name + (f'  | {info}' if info else ''), flush=True)


H, W = 480, 640


def frame(val=0, rows=None, cols=None):
    d = np.zeros((H, W), np.uint16)
    if rows is None:
        d[:] = val
    else:
        d[rows[0]:rows[1], cols[0]:cols[1]] = val
    return d


def q_of(d):
    return shell._frame_quality(d, 1.0)


print(f'[64] 网格 = {shell._QUAL_GRID}，最佳区 = '
      f'{shell._QUAL_NEAR_MAX:.0f}~{shell._QUAL_FAR_MIN:.0f}mm')

# ① 全无效
q = q_of(frame(0))
ok = q['light'] == 'red' and q['zone'] == 'none' and q['valid_pct'] == 0 \
    and all(v == 0 for row in q['grid'] for v in row)
item('① 全无效帧 → 红灯 / zone=none / 网格全 0', ok,
     f"light={q['light']} zone={q['zone']} valid={q['valid_pct']}%")

# ② 太近
q = q_of(frame(300))
ok = q['zone'] == 'near' and q['light'] == 'red' and '太近' in q['hint'] and abs(q['d_med'] - 300) < 1
item('② 太近 300mm → zone=near / 红灯 / 提示太近', ok,
     f"zone={q['zone']} light={q['light']} d_med={q['d_med']} hint={q['hint']}")

# ③ 最佳 + 全覆盖
q = q_of(frame(800))
ok = q['zone'] == 'best' and q['light'] == 'green' and q['valid_pct'] >= 99.0 and abs(q['d_med'] - 800) < 1
item('③ 800mm 全覆盖 → zone=best / 绿灯 / 覆盖≈100%', ok,
     f"zone={q['zone']} light={q['light']} valid={q['valid_pct']}% d_med={q['d_med']}")

# ④ 太远
q = q_of(frame(2200))
ok = q['zone'] == 'far' and q['light'] == 'red' and '太远' in q['hint']
item('④ 太远 2200mm → zone=far / 红灯 / 提示太远', ok,
     f"zone={q['zone']} light={q['light']} hint={q['hint']}")

# ⑤ 覆盖不足（中央小目标）
q = q_of(frame(800, (200, 280), (300, 380)))
ok = q['light'] == 'red' and q['valid_pct'] < 35.0
item('⑤ 中央小目标 → 覆盖不足红灯', ok,
     f"light={q['light']} valid={q['valid_pct']}% hint={q['hint']}")
q2 = q_of(frame(800, (100, 380), (150, 500)))
item('⑤b 中央大目标（约占画幅一半）→ 覆盖够，绿灯', q2['light'] == 'green',
     f"light={q2['light']} valid={q2['valid_pct']}%")

# ⑥ 网格对位（显示画幅坐标：raw 列 - 21；降采样 ÷2）
# 目标格 (0,0)：显示 行 0..38 / 列 0..38（÷2 坐标）→ raw 行 0..76 / 列 21..97
# 注意：镜像默认「开」= 直出（与出图同向，不翻面）→ 显示坐标与发布坐标同序
shell._preview_mirror['on'] = True
d = frame(800, (0, 76), (21, 97))
q = q_of(d)
g = q['grid']
ok = g[0][0] > 90.0 and all(g[i][j] == 0.0 for i in range(6) for j in range(8)
                            if (i, j) != (0, 0))
item('⑥ 网格对位（镜像=直出）：仅左上格有效 → 该格生效，其余 0', ok,
     f"g[0][0]={g[0][0]} 非零格数={sum(1 for i in range(6) for j in range(8) if g[i][j] > 0)}")

# ⑦ 镜像关闭 = 显示翻面 → 同一帧网格左右对调（与屏幕所见一致）
shell._preview_mirror['on'] = False
q_m = q_of(d)
gm = q_m['grid']
ok = gm[0][7] > 90.0 and gm[0][0] == 0.0
item('⑦ 镜像关（显示翻面）：同一帧网格左右对调', ok,
     f"翻面格(0,7)={gm[0][7]} 原格(0,0)={gm[0][0]}")
shell._preview_mirror['on'] = True

# ⑧ 性能
d = frame(800)
ts = []
for _ in range(30):
    t0 = time.perf_counter()
    q_of(d)
    ts.append((time.perf_counter() - t0) * 1000.0)
med = float(np.median(ts))
item('⑧ 单帧质量计算耗时中位 < 15ms', med < 15.0,
     f'中位 {med:.2f}ms（最大 {max(ts):.2f}ms）')

print()
print('===== probe64 结果（TODO-016 采集质量可视化 · v0.2.10） =====')
allok = len(results) > 0
for name, ok in results:
    print(('PASS ' if ok else 'FAIL ') + name)
    allok = allok and ok
print('===== ' + ('全部通过' if allok else '存在失败项') + ' =====')
sys.exit(0 if allok else 1)
