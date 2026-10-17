# -*- coding: utf-8 -*-
"""probe45: 真实 HTTP 路径复现帧率跳动
模拟浏览器 FrameImg 链式加载：GET → 读完 → 25ms → 下一帧
双链并发（rgb + depth），统计每秒得帧数、慢帧、连接错误
"""
import sys, time, threading, urllib.request
from pathlib import Path

ROOT = Path(str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
import shell

pipe = shell.build_pipeline()
time.sleep(3.5)
b = shell.Bridge(pipe)

port, httpd = shell.start_server(ROOT / 'ui-web' / 'dist', b)
print(f'服务器端口: {port}')

def chain_http(kind, seconds=8, gap=25, out=None):
    counts = [0] * seconds
    slow = []
    errs = []
    t0 = time.time()
    while True:
        el = time.time() - t0
        if el >= seconds: break
        sec = int(el)
        url = f'http://127.0.0.1:{port}/api/frame?kind={kind}&t={int(time.time()*1000)}'
        t1 = time.time()
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = resp.read()
            dt = time.time() - t1
            counts[sec] += 1
            if dt > 0.25:
                slow.append(f'{kind} 第{sec}s 耗时{dt*1000:.0f}ms ({len(data)}B)')
        except Exception as e:
            errs.append(f'{kind} 第{sec}s {type(e).__name__}: {str(e)[:70]}')
        if gap:
            time.sleep(gap / 1000.0)
    if out is not None:
        out[kind] = (counts, slow, errs)
    return counts, slow, errs

print('=== 双链并发（HTTP 真实路径，各 8 秒，间隔 25ms）===')
out = {}
t1 = threading.Thread(target=chain_http, args=('rgb', 8, 25, out))
t2 = threading.Thread(target=chain_http, args=('depth', 8, 25, out))
t1.start(); t2.start(); t1.join(); t2.join()

for kind in ('rgb', 'depth'):
    c, slow, errs = out.get(kind, ([], [], []))
    zeros = sum(1 for x in c if x == 0)
    print(f'{kind}: 每秒 {c} | 均值 {sum(c)/max(len(c),1):.1f} | 0帧秒 {zeros}/{len(c)}')
    for s in slow[:6]: print('   慢帧:', s)
    for e in errs[:6]: print('   错误:', e)

httpd.shutdown()
pipe.stop_all()
print('完成')