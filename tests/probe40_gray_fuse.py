# -*- coding: utf-8 -*-
"""probe40: ① 灰度渲染实测（后端像素级验证）② 融合全链路真跑（用现有 turntable 数据）"""
import sys, time, io, json
from pathlib import Path
from PIL import Image

ROOT = Path(str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
import shell

pipe = shell.build_pipeline()
time.sleep(3)
b = shell.Bridge(pipe)

# ---------- ① 灰度 ----------
def pixel_check(tag, t):
    img = Image.open(io.BytesIO(t[1])).convert('RGB')
    w, h = img.size
    # 采样 200 个点，判断 R/G/B 是否相等（灰度）
    same = 0; tot = 0
    for i in range(20, w - 20, max(1, (w - 40) // 14)):
        for j in range(20, h - 20, max(1, (h - 40) // 14)):
            r, g, bb = img.getpixel((i, j))
            tot += 1
            if r == g == bb:
                same += 1
    print(f'  {tag}: {w}x{h} 灰度像素占比 {same}/{tot} = {100*same/max(tot,1):.0f}%')

r0 = b.call('frame', 'GET', {'kind': 'depth', 'gray': '0'}, {})
pixel_check('伪彩 gray=0', r0)
r1 = b.call('frame', 'GET', {'kind': 'depth', 'gray': '1'}, {})
pixel_check('灰度 gray=1', r1)

# ---------- ② 融合 ----------
print('\n=== 融合全链路 ===')
ld = b.call('list_dirs', 'GET', {}, {})
print('list_dirs 返回:', [(d['name'], d['frames']) for d in ld['dirs']])

# 选一个有帧的 turntable 目录
target = None
for d in ld['dirs']:
    if d['frames'] >= 4:
        target = d['path']; break
if target is None and ld['dirs']:
    target = ld['dirs'][0]['path']
print('测试目录:', target)

if target:
    r = b.call('fuse', 'POST', {}, {'dir': target})
    print('启动融合:', r)
    t0 = time.time()
    while time.time() - t0 < 120:
        time.sleep(2)
        p = b.call('fuse_progress', 'GET', {}, {})
        if p.get('done') or p.get('error'):
            print(f'结束（{time.time()-t0:.0f}s）: done={p.get("done")} error={p.get("error")}')
            print('产物:', p.get('out_dir'))
            break
        print(f'  进度 {p.get("pct", 0)*100:.0f}% stage={p.get("stage")}')
    import os
    d = p.get('out_dir') or target
    for f in ('fused_points.ply', 'fused_mesh.stl', 'fused_preview.png'):
        fp = os.path.join(d, f)
        print(f'  {f}: {"✓ " + str(os.path.getsize(fp)//1024) + "KB" if os.path.exists(fp) else "✗ 缺失"}')

pipe.stop_all()
print('\n=== 完成 ===')
