# -*- coding: utf-8 -*-
"""probe56 BUG-009 显示层裁剪 端到端验证（真管线 + HTTP）

验证项（v0.2.9：含 BUG-013 幻影列清零）：
  ① 服务出图：深度帧 JPEG 宽度 ≈ 619 * 0.65（裁剪生效）
  ② 坐标映射：pixel(0,y) == rec.last_depth[y, 21]（显示第 0 列=首个有效列）
               pixel(618,y) == 0（显示末列 = 幻影列，已清零）
  ③ 镜像关：pixel_off(618,y) == rec.last_depth[y, 21]（翻面一致）
  ④ 数据不动：rec.last_depth 仍 640 宽；[0:21] 列也未被改动（仍为垃圾带）
  ⑤ 测距仍正常（有效点 > 0）
"""
import sys, time, json, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import shell
import numpy as np
from PIL import Image
import io as _io

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def get_json(url):
    with _opener.open(url, timeout=8) as r:
        return json.loads(r.read())

pipe = shell.build_pipeline()
results = []
try:
    bridge = shell.Bridge(pipe)
    port, srv = shell.start_server(ROOT / 'ui-web' / 'dist', bridge)
    base = f'http://127.0.0.1:{port}/api'
    rec = pipe.get('recorder')
    t0 = time.time()
    while time.time() - t0 < 12:
        if rec.last_depth is not None:
            break
        time.sleep(0.3)
    if rec.last_depth is None:
        raise SystemExit('[56] 无深度帧')

    # ① 服务出图宽度（等渲染就绪，失败重试）
    img = None
    for attempt in range(6):
        with _opener.open(f'{base}/frame?kind=depth&t={time.time()}', timeout=8) as r:
            jpg = r.read()
        try:
            img = Image.open(_io.BytesIO(jpg))
            break
        except Exception:
            print(f'[56] 第{attempt+1}次白帧/非图: {len(jpg)}B 头={jpg[:12].hex()}')
            time.sleep(0.8)
    if img is None:
        raise SystemExit('[56] 深度帧始终不可用')
    w, h = img.size
    print(f'[56] 服务深度帧尺寸: {w}x{h}（期望宽 ≈ 619*0.65 ≈ 402）')
    results.append(('① 出图宽度 ≈ 402（裁剪生效）', abs(w - 402) <= 2))
    img.save(str(ROOT / '_tmp' / 'bug009_served_depth.jpg'))

    # ②/③ 坐标映射（同一帧内核对，设静态场景重试一次）
    def pixel(x, y):
        return get_json(f'{base}/pixel?x={x}&y={y}').get('data', {}).get('v')
    def set_mirror(v):
        get_json(f'{base}/set_flip?on={1 if v else 0}')
    H, W = rec.last_depth.shape
    results.append(('④a 数据仍 640 宽', W == 640))
    results.append(('④b 数据 [0:21] 列仍为 1313 垃圾带（未动数据）',
                    bool((rec.last_depth[:, :21] == 1313).all())))
    ok2 = ok3 = False
    for attempt in range(3):
        d = rec.last_depth
        set_mirror(True)
        v0 = pixel(0, 240); v1 = pixel(618, 240)
        e0 = int(d[240, 21])
        # v1: 显示末列 = 幻影列（v0.2.9 BUG-013 清零后恒 0）
        if v0 == e0 and v1 == 0:
            ok2 = True; break
        time.sleep(0.25)
    print(f'[56] 映射(镜像开): pixel(0)= {v0} vs data[240,21]= {e0} | pixel(618)= {v1}（幻影清零，期望 0）')
    results.append(('② 镜像开：显示列 0 ↔ 数据列 21；末列=幻影清零', ok2))
    for attempt in range(3):
        d = rec.last_depth
        set_mirror(False)
        v2 = pixel(618, 240)
        e2 = int(d[240, 21])
        if v2 == e2:
            ok3 = True; break
        time.sleep(0.25)
    print(f'[56] 映射(镜像关): pixel(618)= {v2} vs data[240,21]= {e2}')
    results.append(('③ 镜像关：翻面后映射一致', ok3))
    set_mirror(True)

    # ⑤ 测距（先找两个有效点）
    valid_pts = []
    for y in (220, 260, 300, 180):
        for x in (80, 200, 320, 440, 560):
            v = pixel(x, y)
            if v and v > 0:
                valid_pts.append((x, y))
                if len(valid_pts) >= 2:
                    break
        if len(valid_pts) >= 2:
            break
    print(f'[56] 有效点: {valid_pts}')
    if len(valid_pts) >= 2:
        (x1, y1), (x2, y2) = valid_pts[0], valid_pts[1]
        m = get_json(f'{base}/measure?x1={x1}&y1={y1}&x2={x2}&y2={y2}').get('data', {})
    else:
        m = {}
    results.append(('⑤ 测距正常（有效点）', m.get('ok') is True and (m.get('dist_mm') or 0) > 0))
    print(f"[56] 测距: {m.get('dist_mm')} mm")
finally:
    try:
        pipe.stop_all()
    except Exception:
        pass

print()
print('===== probe56 结果 =====')
allok = True
for name, ok in results:
    print(('PASS ' if ok else 'FAIL ') + name)
    allok = allok and ok
print('===== ' + ('全部通过' if allok else '存在失败项') + ' =====')
sys.exit(0 if allok else 1)
