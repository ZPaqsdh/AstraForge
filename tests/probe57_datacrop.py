# -*- coding: utf-8 -*-
"""probe57 BUG-009 输出端裁剪 端到端验证（v0.2.8 · 真管线）

口径（2026-10-16 用户定案）：**只影响输出端**（保存/导出文件）；显示端保持原画幅。
验证项：
  ① 发布数据不裁：last_depth / last_rgb = (480, 640)（显示端原料保持原画幅）
  ② 输出裁剪 pair：crop_for_output → 均 (479, 619)；标志物位移对称（-21/-21）
  ③ 输出点云干净：裁剪 pair 的 depth_to_points 无 z≈-1313 假板
  ④ 真写文件：save_snapshot → npy(479,619) + rgb.png(619,479)；export_cloud → PLY 无假板
  ⑤ 显示端：出图 ≈402×312；悬停 pixel(0,y)==last_depth[y,21]（预览裁 21 列、数据不动）
  ⑥ 测距正常
"""
import sys, time, json, urllib.request, io as _io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import shell
import numpy as np
from PIL import Image

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
        if rec.last_depth is not None and rec.last_rgb is not None:
            break
        time.sleep(0.3)
    d, r = rec.last_depth, rec.last_rgb

    # ① 发布数据不裁（显示端原画幅）
    results.append(('① 发布深度 (480,640)（显示原画幅）', d.shape == (480, 640)))
    results.append(('① 发布 RGB (480,640)', r.shape[:2] == (480, 640)))

    # ② 输出裁剪 pair
    from core.contracts import crop_for_output
    dep_o, rgb_o = crop_for_output(d, r)
    print(f'[57] 输出 pair: {dep_o.shape} / {rgb_o.shape[:2]}')
    results.append(('② 输出 pair 均 (479,619)', dep_o.shape == (479, 619) and rgb_o.shape[:2] == (479, 619)))

    # ②b 标志物对称位移（存档会话）
    try:
        S = ROOT.parent / '扫描输出' / 'turntable_20261013_162326'
        stored = np.load(str(S / 'frame_000.npy'))
        rawD2 = np.ascontiguousarray(stored[:, ::-1])
        rgb2 = np.array(Image.open(str(S / 'frame_000_rgb.png')).convert('RGB'))
        pd2, pr2 = crop_for_output(np.ascontiguousarray(np.flip(rawD2, axis=1)), rgb2)
        # 手机环：rawRGB (201,278) → 裁剪后 (180,277)；手机块：stored (222,298) → pd2 (201,297)
        def _ring(img, u0, v0, r=45):
            sub = img[max(0, v0-r):v0+r, max(0, u0-r):u0+r].astype(np.float32)
            lum = 0.299*sub[:, :, 0] + 0.587*sub[:, :, 1] + 0.114*sub[:, :, 2]
            m = (sub.min(2) > 165) & (lum > 190)
            ys, xs = np.where(m)
            return (xs.mean() + max(0, u0-r)) if len(xs) >= 20 else None
        def _blk(dep, u0, v0, r=60):
            sub = dep[max(0, v0-r):v0+r, max(0, u0-r):u0+r].astype(np.float32)
            desk = float(np.median(dep[200:360, 80:560][dep[200:360, 80:560] > 0]))
            m = (sub > 0) & (sub < desk - 10) & (sub > desk - 160)
            ys, xs = np.where(m)
            return (xs.mean() + max(0, u0-r)) if len(xs) >= 50 else None
        sr = _ring(pr2, 180, 277); sr0 = _ring(rgb2, 201, 278)
        sb = _blk(pd2, 201, 297); sb0 = _blk(stored, 222, 298)
        dr = sr - sr0 if (sr and sr0) else None
        db = sb - sb0 if (sb and sb0) else None
        print(f'[57] 输出裁剪位移: 环 {dr:+.1f}px | 块 {db:+.1f}px')
        ok2b = dr is not None and db is not None and abs(dr + 21) < 1.2 and abs(db + 21) < 1.2 and abs(dr - db) < 1.0
    except Exception as e:
        print('[57] 标志物异常:', str(e)[:70]); ok2b = False
    results.append(('②b 输出裁剪对称（-21/-21 标志物）', ok2b))

    # ③ 输出点云无假板
    from core import cloudmath as cm
    pts = cm.depth_to_points(dep_o, 1.0, rgb=rgb_o)
    slab = int((np.abs(pts[:, 2] + 1313) < 1.5).sum())
    print(f'[57] 输出点云 {len(pts)} 点 | z≈-1313 假板: {slab} 个')
    results.append(('③ 输出点云无假板（<50）', slab < 50))

    # ④ 真写文件验证
    base_snap = rec.save_snapshot()
    ply_path = rec.export_cloud()
    d_saved = np.load(base_snap + '.npy')
    r_saved = Image.open(base_snap + '_rgb.png')
    print(f'[57] 保存文件: npy {d_saved.shape} | rgb {r_saved.size}')
    ok4 = d_saved.shape == (479, 619) and r_saved.size == (619, 479)
    # PLY 假板
    lines = open(ply_path).read().splitlines()
    hi = next(i for i, l in enumerate(lines) if l.startswith('end_header'))
    arr = np.array([[float(x) for x in l.split()[:3]] for l in lines[hi+1:] if l.strip()])
    ply_slab = int((np.abs(arr[:, 2] + 1313) < 1.5).sum())
    print(f'[57] 导出 PLY: {len(arr)} 点 | 假板 {ply_slab} 个')
    ok4 = ok4 and ply_slab < 50
    results.append(('④ 保存/导出文件：npy+rgb 等尺寸且 PLY 无假板', ok4))
    # 清理测试导出
    try:
        import os
        for p in (base_snap + '.npy', base_snap + '_rgb.png', base_snap + '_depth.png', ply_path):
            os.remove(p)
        print('[57] 测试导出已清理')
    except Exception:
        pass

    # ⑤ 显示端
    img = None
    for _ in range(5):
        with _opener.open(f'{base}/frame?kind=depth&t={time.time()}', timeout=8) as resp:
            jpg = resp.read()
        try:
            img = Image.open(_io.BytesIO(jpg)); break
        except Exception:
            time.sleep(0.8)
    w, h = img.size if img else (0, 0)
    print(f'[57] 显示出图: {w}x{h}（期望 ≈402x312）')
    results.append(('⑤ 显示出图 ≈402x312（原画幅预览）', abs(w - 402) <= 2 and abs(h - 312) <= 2))
    def pixel(x, y):
        return get_json(f'{base}/pixel?x={x}&y={y}').get('data', {}).get('v')
    ok5 = False
    for _ in range(3):
        d2 = rec.last_depth
        v0 = pixel(0, 240); v1 = pixel(618, 240)
        # v0：显示首列 ↔ 数据列 21；v1：显示末列 = 幻影列（BUG-013 清零后恒 0）
        if v0 == int(d2[240, 21]) and v1 == 0:
            ok5 = True; break
        time.sleep(0.25)
    print(f'[57] 悬停映射: pixel(0,240)={v0} vs data[240,21]={int(rec.last_depth[240,21])}'
          f' | pixel(618,240)={v1}（幻影列，期望 0）')
    results.append(('⑤b 悬停坐标：显示列 0↔数据列 21；末列=幻影清零', ok5))

    # ⑥ 测距
    m = {}
    for (x1, y1, x2, y2) in ((100, 240, 400, 300), (80, 200, 300, 260)):
        m = get_json(f'{base}/measure?x1={x1}&y1={y1}&x2={x2}&y2={y2}').get('data', {})
        if m.get('ok'):
            break
    results.append(('⑥ 测距正常', m.get('ok') is True and (m.get('dist_mm') or 0) > 0))
    print(f"[57] 测距: {m.get('dist_mm')} mm")
finally:
    try:
        pipe.stop_all()
    except Exception:
        pass

print()
print('===== probe57 结果（v0.2.7 输出端裁剪） =====')
allok = True
for name, ok in results:
    print(('PASS ' if ok else 'FAIL ') + name)
    allok = allok and ok
print('===== ' + ('全部通过' if allok else '存在失败项') + ' =====')
sys.exit(0 if allok else 1)
