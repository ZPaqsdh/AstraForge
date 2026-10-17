# -*- coding: utf-8 -*-
"""probe39: 帧流优化实测（降采样/耗时/缓存/并发合并/fps）"""
import sys, time, threading, io
from pathlib import Path
from PIL import Image

ROOT = Path(str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
import shell

pipe = shell.build_pipeline()
time.sleep(3.5)                      # 等设备出帧
b = shell.Bridge(pipe)

def jpeg_size(t):
    img = Image.open(io.BytesIO(t[1]))
    return img.size, len(t[1])

# ① depth：降采样验证
t0 = time.time(); r1 = b.call('frame', 'GET', {'kind': 'depth'}, {}); t1 = time.time() - t0
sz, n = jpeg_size(r1)
print(f'depth 首帧: {sz} {n}B 渲染 {t1*1000:.0f}ms')

# ② 缓存命中
t0 = time.time(); r2 = b.call('frame', 'GET', {'kind': 'depth'}, {}); t2 = time.time() - t0
print(f'depth 缓存: {t2*1000:.1f}ms（应 <5ms）命中相同: {r1[1] == r2[1]}')

# ③ 缓存过期后重新渲染耗时
time.sleep(0.2)
t0 = time.time(); b.call('frame', 'GET', {'kind': 'depth'}, {}); t3 = time.time() - t0
print(f'depth 重渲染: {t3*1000:.0f}ms')

# ④ rgb：原尺寸
t0 = time.time(); rr = b.call('frame', 'GET', {'kind': 'rgb'}, {}); t4 = time.time() - t0
szr, nr = jpeg_size(rr)
print(f'rgb 首帧: {szr} {nr}B 渲染 {t4*1000:.0f}ms')

# ⑤ 并发合并：8 线程同时请求 depth（缓存过期后），总耗时 vs 单次
time.sleep(0.25)
results = []
def hit(i):
    t = time.time()
    b.call('frame', 'GET', {'kind': 'depth'}, {})
    results.append(time.time() - t)
ths = [threading.Thread(target=hit, args=(i,)) for i in range(8)]
t0 = time.time()
[t.start() for t in ths]; [t.join() for t in ths]
tot = time.time() - t0
print(f'8 并发 depth: 总耗时 {tot*1000:.0f}ms（合并后应≈1-2 次渲染时间）')

# ⑥ api_state 的 fps
st = b.call('state', 'GET', {}, {})
time.sleep(1.2)
st2 = b.call('state', 'GET', {}, {})
print(f'api_state: fps={st2.get("fps")} device={st2["device"]["streaming"]} 帧数str={st2.get("tt_count")}')

pipe.stop_all()
print('=== 完成 ===')
