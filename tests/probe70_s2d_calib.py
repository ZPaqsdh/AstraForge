# -*- coding: utf-8 -*-
"""probe70 S2D 深度换算标定与验证（取代旧的线性 mm/shift 口径）—— 真机，只读+落一个参数文件

背景（2026-10-16 晚查明）：
  深度流里的值 **不是毫米**，而是**视差域**（1/4 像素单位）。官方驱动是先在主机侧建
  S2D 表再输出 mm 的（本机驱动日志：OutputFormat=100 + ShiftScale/ConstShift/ZPD/ZPPS…），
  我们的 raw 路径没有这一步 → 一直把视差值当毫米用，几何非线性错误。
  正确形式（与社区反编译的官方 liborbbec.so 公式、astra_raw 的 K 常数同源）：
        z_mm = A / (C − s)          A = f_native·B·4 ≈ 342207（= ZPD/ZPPS·75·4）
  其中 C 是**每台**的零视差偏移（本机未知，需一次已知距离定标）。

用法：
  python tests/probe70_s2d_calib.py              # 只读：打印中心读数与各假设下的距离
  python tests/probe70_s2d_calib.py 1230         # 已知距离 1230mm → 算出并保存 C
输出：data/S2D标定.json（A/C/日期/依据）+ 问题跟踪/_判读_0210_S2D换算对照.png
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules.device.module import AstraLink, decode_frame   # noqa: E402

WS = Path(str(Path(__file__).resolve().parents[2]))
OUT = WS / '问题跟踪'
CFG = ROOT / 'data' / 'S2D标定.json'

ZPD_FALLBACK = 65.0
ZPPS_FALLBACK = 0.056983
B_STEREO = 75.0          # 发射器-相机 立体基线（社区口径）
K_SUB = 4.0              # f(640)·k_sub：f(640)=f_native/2，视差子像素 k_sub=8 → 合起来 ×4

A_DEFAULT = (ZPD_FALLBACK / ZPPS_FALLBACK) * B_STEREO * K_SUB
print(f'[70] A = f(640)·B·8 = {A_DEFAULT:.0f}'
      f'（= (ZPD/ZPPS={ZPD_FALLBACK/ZPPS_FALLBACK:.2f} native → 640 画幅 570.35)·75mm·8）')

known = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0

link = AstraLink()
ok, msgs = link.connect()
if not ok:
    print('设备连接失败:', (msgs or '')[:120]); sys.exit(1)
ok, msgs = link.ensure_ready()
if not ok:
    print('设备就绪失败:', msgs); sys.exit(1)

dep = None
t0 = time.time()
while time.time() - t0 < 10:
    fr = link.grab_frame(timeout=0.5)
    if fr is None:
        continue
    d = decode_frame(fr)
    if d is not None and (d > 0).sum() > 5000:
        dep = d; break

try:
    if dep is None:
        print('未抓到深度帧'); sys.exit(1)
    pub = np.ascontiguousarray(dep[:, :-21][:, ::-1])       # 发布向
    H, W = pub.shape
    cy, cx = H // 2, W // 2
    h = 30
    roi = pub[cy - h:cy + h, cx - h:cx + h]
    rv = roi[roi > 0]
    s_c = float(np.median(rv))
    v = pub[pub > 0]
    print(f'[70] 帧 {pub.shape}｜有效 {float((pub>0).mean())*100:.1f}%')
    print(f'[70] 中心 60×60 读数 s = {s_c:.0f}｜全帧中位 {np.median(v):.0f}｜范围 {v.min():.0f}~{v.max():.0f}')
    print(f'[70] 中心区在视差域的含义：disparity ≈ (C − {s_c:.0f})/4 px（C 待定）')

    if known > 0:
        C = s_c + A_DEFAULT / known
        cfg = {'A': round(A_DEFAULT, 1), 'C': round(C, 2),
               'known_mm': known, 's_center': s_c,
               'formula': 'z_mm = A / (C - s)',
               'source': 'A=f(640)·B·4（ZPD/ZPPS=1140.69 native → 640 画幅 570.35；B=75mm；视差 1/4px）',
               'date': time.strftime('%Y-%m-%d %H:%M:%S')}
        CFG.parent.mkdir(parents=True, exist_ok=True)
        CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'\n[70] ★ 由已知距离 {known:.0f}mm 定出：C = {C:.2f}（A = {A_DEFAULT:.0f}）')
        print(f'     → 中心 s={s_c:.0f} 对应 z={A_DEFAULT/(C-s_c):.0f}mm（应≈{known:.0f}）')
        print(f'     → 已写入 {CFG}')
        # 自检：全帧映射
        zz = A_DEFAULT / (C - v)
        print(f'     → 全帧换算后：中位 {np.median(zz):.0f}mm｜P10 {np.percentile(zz,10):.0f}'
              f'｜P90 {np.percentile(zz,90):.0f}｜最近 {zz.min():.0f}｜最远 {zz.max():.0f}')

        # 对照图：线性口径 vs S2D 口径（同一色标 0~4000mm）
        try:
            from PIL import Image
            def render(zmap):
                g = np.zeros(zmap.shape, np.uint8)
                ok2 = zmap > 0
                g[ok2] = np.clip(zmap[ok2] / 4000.0 * 255, 0, 255).astype(np.uint8)
                return g
            old = np.where(pub > 0, pub.astype(np.float32), 0)          # 旧：直读 mm
            new = np.where(pub > 0, A_DEFAULT / np.maximum(C - pub, 1), 0)
            canv = np.concatenate([render(old), np.full((H, 4), 255, np.uint8), render(new)], axis=1)
            Image.fromarray(canv).save(OUT / '_判读_0210_S2D换算对照.png')
            print(f'     → 对照图（左=旧直读 / 右=S2D 换算，同色标 0~4000mm）：_判读_0210_S2D换算对照.png')
        except Exception as e:
            print('     对照图失败:', e)
    else:
        print('\n[70] 未给已知距离 → 只读模式。给一个"卷尺量出的真实距离"即可定 C：')
        print('     python tests/probe70_s2d_calib.py <中心处真实距离mm>')
        for probe_z in (500, 800, 1200, 2000, 3000):
            C = s_c + A_DEFAULT / probe_z
            print(f'     若中心真实距离 = {probe_z:5d}mm → C = {C:7.2f}'
                  f'（此时全帧 {A_DEFAULT/(C-v.max()):.0f}~{A_DEFAULT/(C-v.min()):.0f}mm）')
finally:
    try:
        link.ir_off()
    except Exception:
        pass
    try:
        link.dispose()
    except Exception:
        pass
    print('[70] 收尾完成')
