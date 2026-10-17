# -*- coding: utf-8 -*-
"""probe58 v0.2.8 发行态验受（发行 code/ 为 ROOT 跑真管线；非装机终验）

用途：装机终验前，以 **发行/AstraForge/code/** 为 ROOT 跑真管线（与装机运行同代码，
真设备 + 真写文件），把验证清单里能自动化的项先验掉。
用法：python tests/probe58_ship_accept.py   （先确认软件没开着；跑完自动 stop_all）
验证项：
  ① 设置可读 + 性能模式启动还原
  ② 发布数据 480x640（显示端原画幅）
  ③ crop_for_output → 输出 pair 均 (479,619)
  ④ 真写文件（临时目录）：npy 479x619 / rgb.png 619x479 / PLY 假板 <50
  ⑤ 显示端出图 ≈402x312 + 悬停映射（显示列0 ↔ 数据列21）
  ⑥ 测距
留证图 → 问题跟踪/_判读_v028发行态_导出pair.png；跑完 stop_all。
"""
import io
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

SHIP = Path(str(Path(__file__).resolve().parents[2] / '发行' / 'AstraForge' / 'code'))
TMP = Path(__file__).resolve().parents[2] / '_tools' / '_preverify_out'

os.chdir(SHIP)
sys.path.insert(0, str(SHIP))

import numpy as np
from PIL import Image

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get_json(url):
    with opener.open(url, timeout=8) as r:
        return json.loads(r.read())


results = []


def check(name, ok, info=''):
    results.append((name, bool(ok)))
    print(('PASS ' if ok else 'FAIL ') + name + ((' | ' + str(info)) if info else ''), flush=True)


import shell

print(f'[预验] 发行态 ROOT = {shell.ROOT}', flush=True)
print(f'[预验] 版本 = {shell.APP_VERSION}', flush=True)

pipe = shell.build_pipeline()
try:
    bridge = shell.Bridge(pipe)
    port, srv = shell.start_server(SHIP / 'ui-web' / 'dist', bridge)
    base = f'http://127.0.0.1:{port}/api'

    # ① 设置读取 + 启动还原
    from core import appsettings
    saved = appsettings.load(SHIP / 'data')
    print(f'[预验] 发行 设置.json: {json.dumps(saved, ensure_ascii=False)}', flush=True)
    fus = pipe.get('fusion')
    pm = saved.get('perf_mode')
    check('① 设置文件可读且非空', bool(saved))
    if pm in ('std', 'perf', 'turbo'):
        check(f'① 性能模式启动还原 = {pm}', getattr(fus, '_perf_mode', None) == pm)

    # 等帧
    rec = pipe.get('recorder')
    t0 = time.time()
    while time.time() - t0 < 15:
        if rec.last_depth is not None and rec.last_rgb is not None:
            break
        time.sleep(0.3)
    d, r = rec.last_depth, rec.last_rgb
    check('② 发布深度 (480,640)', d is not None and d.shape == (480, 640),
          None if d is None else d.shape)
    check('② 发布 RGB (480,640)', r is not None and r.shape[:2] == (480, 640),
          None if r is None else r.shape[:2])

    from core.contracts import crop_for_output
    dep_o, rgb_o = crop_for_output(d, r)
    check('③ 输出 pair 均 (479,619)',
          dep_o.shape == (479, 619) and rgb_o.shape[:2] == (479, 619),
          f'{dep_o.shape}/{rgb_o.shape[:2]}')

    # ④ 真写文件（临时目录）
    TMP.mkdir(parents=True, exist_ok=True)
    rec.ctx.settings['out_dir'] = str(TMP)
    base_snap = rec.save_snapshot()
    ply_path = rec.export_cloud()
    d_saved = np.load(base_snap + '.npy')
    r_saved = Image.open(base_snap + '_rgb.png')
    check('④ npy (479,619)', d_saved.shape == (479, 619), d_saved.shape)
    check('④ rgb.png (619,479)', r_saved.size == (619, 479), r_saved.size)
    lines = open(ply_path, errors='replace').read().splitlines()
    hi = next(i for i, l in enumerate(lines) if l.startswith('end_header'))
    arr = np.array([[float(x) for x in l.split()[:3]] for l in lines[hi + 1:] if l.strip()])
    slab = int((np.abs(arr[:, 2] + 1313) < 1.5).sum())
    check('④ PLY 无假板（<50）', slab < 50, f'{len(arr)} 点 | 假板 {slab}')

    # ⑤ 显示端
    img = None
    for _ in range(6):
        with opener.open(f'{base}/frame?kind=depth&t={time.time()}', timeout=8) as resp:
            jpg = resp.read()
        try:
            img = Image.open(io.BytesIO(jpg))
            break
        except Exception:
            time.sleep(0.8)
    w, h = img.size if img else (0, 0)
    check('⑤ 显示端出图 ≈402x312', abs(w - 402) <= 2 and abs(h - 312) <= 2, f'{w}x{h}')


    def pixel(x, y):
        return get_json(f'{base}/pixel?x={x}&y={y}').get('data', {}).get('v')

    ok5 = False
    v0 = v1 = None
    for _ in range(3):
        d2 = rec.last_depth
        v0 = pixel(0, 240)
        v1 = pixel(618, 240)
        # v0: 显示首列 ↔ 数据列 21；v1: 显示末列 = 幻影列（v0.2.9 清零后恒 0）
        if v0 == int(d2[240, 21]) and v1 == 0:
            ok5 = True
            break
        time.sleep(0.25)
    check('⑤b 悬停映射 显示列0 ↔ 数据列21；末列=幻影清零',
          ok5, f'pixel(0,240)={v0} vs data[240,21]={int(rec.last_depth[240, 21])} | pixel(618,240)={v1}')

    # ⑥ 测距
    m = {}
    for (x1, y1, x2, y2) in ((100, 240, 400, 300), (80, 200, 300, 260)):
        m = get_json(f'{base}/measure?x1={x1}&y1={y1}&x2={x2}&y2={y2}').get('data', {})
        if m.get('ok'):
            break
    check('⑥ 测距正常', m.get('ok') is True and (m.get('dist_mm') or 0) > 0,
          f"{m.get('dist_mm')} mm")

    # 留证图：输出 pair 拼接（深度伪彩 | RGB）
    try:
        import core.theme as th
        g = np.clip(dep_o.astype(np.float32) / th.DISP_MAX * 255.0, 0, 255).astype(np.uint8)
        vis = np.empty((*dep_o.shape, 3), np.uint8)
        vis[:] = th.LUT[g]
        vis[dep_o <= 0] = th.INVALID_PX
        sep = np.full((dep_o.shape[0], 6, 3), 255, np.uint8)
        combo = np.concatenate([vis, sep, rgb_o], axis=1)
        out_png = Path(__file__).resolve().parents[2] / '问题跟踪' / '_判读_v028发行态_导出pair.png'
        Image.fromarray(combo).save(out_png)
        print(f'[预验] 留证图: {out_png}', flush=True)
    except Exception as e:
        print('[预验] 留证图失败:', str(e)[:80], flush=True)

    # 清理临时导出（逐文件容错：环境带安全删除钩子时改为移入隔离目录）
    trash = Path.home() / '.tmp-trash-astra'
    for p in (base_snap + '.npy', base_snap + '_rgb.png', base_snap + '_depth.png', ply_path):
        try:
            os.remove(p)
        except Exception:
            try:
                trash.mkdir(exist_ok=True)
                os.replace(p, trash / Path(p).name)
            except Exception:
                pass
    try:
        TMP.rmdir()
    except Exception:
        pass
    print('[预验] 临时导出已清理', flush=True)
finally:
    try:
        pipe.stop_all()
        print('[预验] stop_all 完成（关激光/释放相机）', flush=True)
    except Exception as e:
        print('[预验] stop_all 异常:', str(e)[:100], flush=True)

print()
print('===== 发行态预验结果（v0.2.8） =====')
allok = len(results) > 0
for name, ok in results:
    print(('PASS ' if ok else 'FAIL ') + name)
    allok = allok and ok
print('===== ' + ('全部通过' if allok else '存在失败项') + ' =====')
sys.exit(0 if allok else 1)