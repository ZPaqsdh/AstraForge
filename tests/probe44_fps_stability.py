# -*- coding: utf-8 -*-
"""probe44: RGB 帧率稳定性实测
① 单链拉流（模拟前端 FrameImg 链式加载：每帧 + 25ms 间隔）各 8 秒
② 双链并发（depth + rgb 同时拉，用户真实场景）
统计每秒得帧数，定位"0 帧"卡顿来源（后端 or 前端）
"""
import sys, time, threading
from pathlib import Path

ROOT = Path(str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
import shell

pipe = shell.build_pipeline()
time.sleep(3.5)
b = shell.Bridge(pipe)

def chain(kind, seconds=8, gap=0.025, out=None):
    """链式拉流：帧完成 → 等 gap → 再拉下一帧"""
    counts = [0] * seconds
    t0 = time.time()
    while True:
        el = time.time() - t0
        if el >= seconds: break
        sec = int(el)
        t1 = time.time()
        try:
            b.call('frame', 'GET', {'kind': kind, 't': str(time.time())}, {})
        except Exception as e:
            print(f'  [{kind}] 请求异常: {type(e).__name__}: {str(e)[:60]}')
        dt = time.time() - t1
        counts[sec] += 1
        if dt > 0.3:
            print(f'  [{kind}] 慢帧! 耗时 {dt*1000:.0f}ms (第 {sec} 秒)')
        time.sleep(gap)
    if out is not None:
        out[kind] = counts
    return counts

print('=== ① 单链测试（先 rgb 后 depth，各 8 秒）===')
r1 = chain('rgb', 8)
print('rgb  每秒帧数:', r1)
d1 = chain('depth', 8)
print('depth 每秒帧数:', d1)

print()
print('=== ② 双链并发（depth + rgb 同时，各 8 秒）===')
out = {}
t_rgb = threading.Thread(target=chain, args=('rgb', 8, 0.025, out))
t_dep = threading.Thread(target=chain, args=('depth', 8, 0.025, out))
t_rgb.start(); t_dep.start()
t_rgb.join(); t_dep.join()
print('rgb  每秒帧数:', out.get('rgb'))
print('depth 每秒帧数:', out.get('depth'))

pipe.stop_all()
print()
print('=== 分析 ===')
for name, arr in [('单链rgb', r1), ('单链depth', d1),
                  ('并发rgb', out.get('rgb')), ('并发depth', out.get('depth'))]:
    if not arr: continue
    zeros = sum(1 for x in arr if x == 0)
    print(f'{name}: 均值 {sum(arr)/len(arr):.1f} | 最小 {min(arr)} | 0帧秒数 {zeros}/{len(arr)}')