# -*- coding: utf-8 -*-
"""probe53 预览镜像/翻面 + 数据方向 端到端验证 —— 真设备管线 + HTTP 服务（无窗口）

用法：python tests/probe53_preview_mirror.py [ship]   （ship = 以发行 code/ 为 ROOT）

口径（2026-10-16 定案 B · v0.2.3）：全链统一"镜像向"——数据（保存/导出）与预览同向；
「镜像 (M)」= 预览翻面对比开关（开=直出与出图一致；关=显示端翻面）。

验证项：
  ① 新代码下服务器正常启动
  ② /api/state 默认 preview_mirror=True；device.flip==[True]（深度镜像向）
  ③ /api/frame rgb/depth 返回有效 JPEG（渲染路径无异常）
  ④ 悬停一致性：pixel(镜像开, x,y) == pixel(镜像关, mx(x), y)（同一物理像素）
  ⑤ 测距一致性：measure(开, p1,p2) == measure(关, mx(p1), mx(p2))
     注（v0.2.8 · BUG-011）：mx(x)=(DW-1)-x，DW=显示数据宽（发布数据去固定垃圾列
     后 = 619）——翻面是"显示画幅内"翻转，旧公式 (W-1-x, W=640) 是裁剪前的，
     会偏 21px 假比对；v0.2.8 主点补偿后本探针改为显示画幅公式。
  ⑥ 数据层不受开关影响：_pv_flip 不改原数组
  ⑦ 渲染差异：镜像开/关的深度帧字节不同（翻面确实作用于出图）
  ⑧ B 向数据自洽：发布的 RGB 与深度互为同向（梯度相关 同向 > 镜像）
"""
import sys, time, json, hashlib, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # AstraForge
if len(sys.argv) > 1 and sys.argv[1] == 'ship':
    ROOT = Path(str(Path(__file__).resolve().parents[2] / '发行' / 'AstraForge' / 'code'))
    print('[53] 目标 = 发行态 code/')
sys.path.insert(0, str(ROOT))
import shell                                          # noqa: E402
import numpy as np                                    # noqa: E402

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 本机必须绕系统代理

def get_json(url):
    with _opener.open(url, timeout=8) as r:
        return json.loads(r.read())

pipe = shell.build_pipeline()                         # 真设备管线（连相机）
results = []
try:
    bridge = shell.Bridge(pipe)
    port, srv = shell.start_server(ROOT / 'ui-web' / 'dist', bridge)
    base = f'http://127.0.0.1:{port}/api'
    print(f'[53] server port={port}')
    rec = pipe.get('recorder')

    # 等帧
    t0 = time.time()
    while time.time() - t0 < 12:
        if rec.last_depth is not None and rec.last_rgb is not None:
            break
        time.sleep(0.3)
    ok_frames = rec.last_depth is not None and rec.last_rgb is not None
    results.append(('① 管线出帧（深度+RGB）', ok_frames))
    if not ok_frames:
        raise SystemExit('[53] 无帧，终止')

    # ② state
    st = get_json(base + '/state')
    pm = st.get('data', {}).get('preview_mirror')
    results.append(('② /api/state preview_mirror=True（默认）', pm is True))

    # ③ JPEG 有效
    def get_jpeg(kind):
        with _opener.open(f'{base}/frame?kind={kind}&t={time.time()}', timeout=8) as r:
            return r.read()
    j_rgb = get_jpeg('rgb'); j_dep = get_jpeg('depth')
    results.append(('③ RGB 帧为有效 JPEG', j_rgb[:2] == b'\xff\xd8' and len(j_rgb) > 1000))
    results.append(('③ 深度帧为有效 JPEG', j_dep[:2] == b'\xff\xd8' and len(j_dep) > 1000))

    H, W = rec.last_depth.shape
    DW = W - 21          # 显示数据宽（发布数据去固定垃圾列后；镜像翻转在显示画幅内）
    def mx(x):           # 镜像（显示翻面）对应屏幕列——同一物理像素；v0.2.8
        return (DW - 1) - x

    def pixel(x, y):
        d = get_json(f'{base}/pixel?x={x}&y={y}')
        return d.get('data', {}).get('v')
    def set_mirror(v):
        get_json(f'{base}/set_flip?on={1 if v else 0}')

    # 找两个有效深度点（供 ④⑤ 用；无效点会让断言空过）
    set_mirror(True)
    valid_pts = []
    for y in (200, 260, 320, 380, 240):
        for x in (100, 220, 340, 460, 580, 300):
            v = pixel(x, y)
            if v and v > 0:
                valid_pts.append((x, y, v))
                if len(valid_pts) >= 2:
                    break
        if len(valid_pts) >= 2:
            break
    print(f'[53] 有效测试点: {valid_pts}')
    results.append(('窗口内找到 ≥2 个有效深度点', len(valid_pts) >= 2))

    # ④ 悬停一致性：pixel(开,x,y) == pixel(关,mx(x),y)（同一物理像素）
    ok4 = True
    if valid_pts:
        x, y, _ = valid_pts[0]
        set_mirror(True)
        v_on = pixel(x, y)
        set_mirror(False)
        v_off = pixel(mx(x), y)
        same = (v_on == v_off and (v_on or 0) > 0)
        print(f'[53] 悬停一致性 ({x},{y}): 开={v_on} | 关@{mx(x)}={v_off} → {"OK" if same else "不一致"}')
        if not same:
            time.sleep(0.3)
            set_mirror(True); v_on = pixel(x, y)
            set_mirror(False); v_off = pixel(mx(x), y)
            same = (v_on == v_off and (v_on or 0) > 0)
        ok4 = same
    results.append(('④ 悬停：镜像开(x,y) == 关(mx(x),y)（有效点）', ok4))

    # ⑤ 测距一致性（用两个有效点；镜像开/关对应点 = 同一物理像素）
    ok5 = False
    if len(valid_pts) >= 2:
        (x1, y1, _), (x2, y2, _) = valid_pts[0], valid_pts[1]
        set_mirror(True)
        m_on = get_json(f'{base}/measure?x1={x1}&y1={y1}&x2={x2}&y2={y2}').get('data', {})
        set_mirror(False)
        m_off = get_json(f'{base}/measure?x1={mx(x1)}&y1={y1}&x2={mx(x2)}&y2={y2}').get('data', {})
        ok5 = (m_on.get('ok') is True and m_off.get('ok') is True
               and m_on.get('dist_mm') == m_off.get('dist_mm')
               and (m_on.get('dist_mm') or 0) > 0)
        print(f"[53] 测距: 开={m_on.get('dist_mm')} 关(镜像点)={m_off.get('dist_mm')} → {'OK' if ok5 else '不一致/无效'}")
    results.append(('⑤ 测距：镜像开/关对应点结果一致（有效>0）', ok5))

    # ⑥ 数据数组不被改动
    set_mirror(True)
    d = rec.last_depth; rrgb = rec.last_rgb
    d_before = d.copy(); rgb_before = rrgb.copy()
    shell._pv_flip(d); shell._pv_flip(rrgb)
    same_d = bool((d == d_before).all()); same_rgb = bool((rrgb == rgb_before).all())
    results.append(('⑥ _pv_flip 不改动数据数组（深度/RGB）', same_d and same_rgb))

    # ⑦ 镜像开/关渲染差异（同代码路径，翻转确实生效）
    set_mirror(True); j1 = get_jpeg('depth')
    set_mirror(False); j2 = get_jpeg('depth')
    results.append(('⑦ 深度帧 开/关字节不同（翻面生效）', j1 != j2))

    # ⑧ B 向数据自洽：发布 RGB 与发布深度互为同向（梯度相关：同向 > 镜像）
    dev = pipe.get('device')
    results.append(('②b device.flip == [True]（深度镜像向）', list(dev.flip) == [True]))

    def _grad(g):
        g = g.astype(np.float32)
        gx = np.zeros_like(g); gy = np.zeros_like(g)
        gx[:, 1:-1] = g[:, 2:] - g[:, :-2]
        gy[1:-1, :] = g[2:, :] - g[:-2, :]
        return np.sqrt(gx ** 2 + gy ** 2)

    def _corr(a, b):
        a = a - a.mean(); b = b - b.mean()
        n1 = np.sqrt((a * a).sum()); n2 = np.sqrt((b * b).sum())
        return float((a * b).sum() / (n1 * n2)) if n1 > 0 and n2 > 0 else 0.0

    dep2 = rec.last_depth.astype(np.float32)
    dm2 = dep2 > 0
    lo2, hi2 = [float(x) for x in np.percentile(dep2[dm2], [5, 95])] if dm2.any() else (0, 1)
    dv2 = np.clip((dep2 - lo2) / (hi2 - lo2 + 1e-6), 0, 1) * 255
    dv2[~dm2] = float(np.median(dv2[dm2])) if dm2.any() else 0
    gD = _grad(dv2); gR = _grad(rec.last_rgb.mean(2))
    c_same = _corr(gD, gR); c_mirr = _corr(gD[:, ::-1], gR)
    print(f'[53] 数据对同向性: 同向 {c_same:+.4f} | 镜像 {c_mirr:+.4f}')
    results.append(('⑧ 发布数据 RGB↔深度 同向（B 口径自洽）', abs(c_same) >= abs(c_mirr)))

    # 复位默认（镜像开 = 直出）
    set_mirror(True)
finally:
    try:
        pipe.stop_all()
    except Exception as e:
        print('[53] stop_all 异常:', e)

print()
print('===== probe53 结果 =====')
allok = True
for name, ok in results:
    print(('PASS ' if ok else 'FAIL ') + name)
    allok = allok and ok
print('===== ' + ('全部通过' if allok else '存在失败项') + ' =====')
sys.exit(0 if allok else 1)
