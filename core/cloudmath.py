#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
astra_fuse.py - 转台多帧点云融合 → 完整 3D 模型
================================================
输入：转台模式采集目录（astra_studio「转台」生成）：
    turntable_<时间戳>/
        frame_000.npy ... frame_023.npy     # 480x640 深度数组（shift）
        manifest.json                        # 每帧角度 + mm_per_shift
输出（同目录）：
    fused_points.ply     融合点云（多帧平均降噪）
    fused_mesh.stl       柱面展开网格（完整 360° 模型）
    fused_preview.png    明暗预览

流程：点云生成 → 体素降采样 → 角度先验 + ICP 精修 → 体素融合 → 柱面展开 → 网格化 → STL

用法：
    python astra_fuse.py <目录> [--voxel 1.5] [--icp-iters 10] [--no-icp]

坐标约定：相机 x右/y下/z前；转台轴 ≈ 竖直方向（相机 Y 轴），物体绕 Y 轴旋转。
"""
"""AstraForge 点云算法库（core 稳定层）：深度→点云/ICP/融合/柱面网格/PLY/STL。

自包含设计：不依赖任何外部模块（OTA 时 core 稳定不动，模块可换）。
"""
import os, json, struct
import numpy as np

# ---------------- 内参（唯一源） ----------------
# BUG-015（2026-10-16 拍板 A）：改用**相机出厂标定**，废弃无出处硬编码 572/320/240。
# 来源：本机闪存 dump `固件研究_2026-10-12/嵌入固件镜像/flash_dump_old_unit_1MB.bin`
# @0x70000 起 120B = 30×float32（与 OniCTypes.h 的 OBCameraParams 逐字段吻合，
# 串号 190429200680 与本机一致）。实测解析（2026-10-16 复核）：
#   深度 l_intr = fx 580.703 / fy 580.703 / cx 318.163 / cy 249.847
#   彩色 r_intr = fx 601.275 / fy 601.275 / cx 324.221 / cy 241.019（D2C 用，见 TODO-012）
#   外参 r2l_t = [24.571, -0.197, 0.308] mm（基线 24.57mm）；r2l_r ≈ 单位阵（~0.9° 级）、
#   l_k = [-0.1129, 0.4276, -0.5524, -0.0036, 0.0051]（畸变暂不校正）
# 影响：横向尺度原偏小 1.5%（572 → 580.7）；cy 原偏上 9.85px（≈17mm@1m，纵向几何偏差的
# 主因）。z 来自 shift×mm_per_shift，不受内参影响。
FX = FY = 580.703
CX, CY = 318.163, 249.847
# 全画幅（640×480）主点。裁剪帧沿用 FX/FY，主点须随裁剪平移：
# 现行发布（flip(rawD)，垃圾在左）裁 [row0 + 左 21 列] → 619×479 主点 = (CX-21, CY-1)；
# 老 R 帧（直发 rawD，垃圾在右，见 BUG-012）右裁不左移，col0 显式传 0。
_CROP_ROW0, _CROP_COL0 = 1, 21


def cxcy_for_shape(shape, col0=None, row0=None):
    """按帧尺寸返回主点 (cx, cy)——尺寸/方位感知，保持"同一物理像素 → 同一 3D 坐标"。

    BUG-011：v0.2.7 输出端裁剪（619×479）未同步主点 → 点云/融合整体错位
    21px×z/FX（z=1.2m ≈44mm；转台各帧错位方向随角度旋转 → 环状拖影）。
    BUG-015（v0.2.10）：主点基准由硬编码 (320,240) 改为出厂标定 (CX,CY)=(318.163,249.847)，
    本函数逻辑不变（仍是"全画幅主点 − 裁剪量"），故裁剪感知自动继承新基准。
    - (480,640) 全画幅：(CX, CY)；
    - (479,619) 左裁帧（现行发布会话）：(CX-21, CY-1)；
    - 右裁帧（老 R 会话）：col0 显式传 0 → (CX, CY-1)。
    col0/row0 = 相对全画幅从**左缘/顶缘**裁掉的列/行数（None=按尺寸推断）。
    """
    h, w = int(shape[0]), int(shape[1])
    if col0 is None:
        col0 = _CROP_COL0 if w == 640 - _CROP_COL0 else 0
    if row0 is None:
        row0 = _CROP_ROW0 if h == 480 - _CROP_ROW0 else 0
    return (CX - col0, CY - row0)


# ---------------- 基础 ----------------
def depth_to_points(d, mm_per_shift=1.0, max_shift=4000, rgb=None, col0=None):
    """深度图(shift) → 相机坐标点云 Nx3 (mm)；rgb 给定时返回 Nx6（后 3 列 RGB 0-255）。
    col0=相对全画幅从左缘裁掉的列数（None=按尺寸推断；右裁老帧显式传 0）。"""
    z = d.astype(np.float32) * mm_per_shift
    H, W = d.shape
    cx, cy = cxcy_for_shape(d.shape, col0=col0)
    us, vs = np.meshgrid(np.arange(W, dtype=np.float32),
                         np.arange(H, dtype=np.float32))
    x = (us - cx) * z / FX
    y = (vs - cy) * z / FY
    m = (d > 0) & (d < max_shift)
    geo = np.stack([x[m], y[m], z[m]], axis=1).astype(np.float64)
    # 查看器坐标修正（BUG-001/002）：相机光学系（x右/y下/z前）→ 查看器/切片惯例
    #（+X 右 / +Y 上 / 场景位于 -Z 前方）。绕 X 轴 180°（y,z 取反）= 纯旋转、保持
    # 右手系——不可用水平镜像（会翻手性，模型在切片/旋转查看时即现形）。
    # 方向经三标志物实测判定（键盘灯/手机环/显示器全部吻合的唯一右手系解）。
    geo[:, 1] = -geo[:, 1]
    geo[:, 2] = -geo[:, 2]
    if rgb is None:
        return geo
    rh, rw = rgb.shape[:2]
    um = np.clip(us[m].astype(np.int64), 0, rw - 1)
    vm = np.clip(vs[m].astype(np.int64), 0, rh - 1)
    cols = rgb[vm, um, :3].astype(np.float64)
    return np.concatenate([geo, cols], axis=1)


def depth_to_model_points(d, angle_deg, cam_dist, mm_per_shift=1.0, max_shift=4000,
                          rgb=None, col0=None):
    """深度图(shift) → 模型系点云 Nx3 (mm)；rgb 给定时返回 Nx6（后 3 列 = RGB 0-255）。

    模型系：转台中心为原点，Y 轴 = 转台轴（竖直），θ=0 为参考姿态。
    流程：相机系 → 平移到转台中心系（z 减去相机到转台距离）→ R_y(-angle) 转回 θ=0。
    D2C：深度与 RGB 同分辨率时按像素坐标直接取色（u,v 原样映射）。
    col0=相对全画幅从左缘裁掉的列数（None=按尺寸推断；右裁老帧显式传 0，BUG-012）。"""
    z = d.astype(np.float32) * mm_per_shift
    H, W = d.shape
    cx, cy = cxcy_for_shape(d.shape, col0=col0)
    us, vs = np.meshgrid(np.arange(W, dtype=np.float32),
                         np.arange(H, dtype=np.float32))
    x = (us - cx) * z / FX
    y = (vs - cy) * z / FY
    m = (d > 0) & (d < max_shift)
    P = np.stack([x[m], y[m], z[m] - cam_dist], axis=1).astype(np.float64)
    a = np.deg2rad(angle_deg)
    c, s = np.cos(a), np.sin(a)
    X = P[:, 0] * c - P[:, 2] * s
    Z = P[:, 0] * s + P[:, 2] * c
    geo = np.stack([X, P[:, 1], Z], axis=1)
    # 查看器坐标修正（BUG-001/002·同 depth_to_points）：模型系 y 轴（转台轴）翻正为
    # +Y 向上、z 翻置到观察者前方（-Z）——纯旋转保持手性；下游（柱面展开/ICP/渲染）
    # 全部基于相对量，自洽不受影响。
    geo[:, 1] = -geo[:, 1]
    geo[:, 2] = -geo[:, 2]
    if rgb is None:
        return geo
    um, vm = us[m].astype(np.int64), vs[m].astype(np.int64)
    rh, rw = rgb.shape[:2]
    um = np.clip(um, 0, rw - 1); vm = np.clip(vm, 0, rh - 1)
    cols = rgb[vm, um, :3].astype(np.float64)
    return np.concatenate([geo, cols], axis=1)


def voxel_down(pts, voxel):
    """体素降采样（栅格内取均值）。pts 可为 Nx3（几何）或 Nx6（几何+颜色）。
    几何取前 3 列计栅格；颜色列一并平均。"""
    if len(pts) == 0:
        return pts
    cols = pts.shape[1]
    keys = np.floor(pts[:, :3] / voxel).astype(np.int64)
    ukeys, inv = np.unique(keys, axis=0, return_inverse=True)
    out = np.zeros((len(ukeys), cols), dtype=np.float64)
    np.add.at(out, inv, pts)
    cnt = np.bincount(inv, minlength=len(ukeys)).astype(np.float64)
    out /= np.maximum(cnt, 1)[:, None]
    return out


def rot_y(a_deg):
    """绕 Y 轴旋转 a 度的 4x4（转台：相机固定、物体转）。"""
    a = np.deg2rad(a_deg)
    c, s = np.cos(a), np.sin(a)
    T = np.eye(4)
    T[0, 0], T[0, 2] = c, s
    T[2, 0], T[2, 2] = -s, c
    return T


# ---------------- ICP ----------------
def kabsch(P, Q):
    """求 P→Q 的最优刚体变换（对应点已配对）。返回 4x4。"""
    pc, qc = P.mean(0), Q.mean(0)
    H = (P - pc).T @ (Q - qc)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = qc - R @ pc
    return T


try:                                    # 有 scipy 则用 KDTree（查询快约 100 倍）
    from scipy.spatial import cKDTree as _CKDTree
except Exception:
    _CKDTree = None


class NearestIndex:
    """最近邻索引：优先 scipy.cKDTree；无 scipy 退回分块暴力（点数已受控）。"""

    def __init__(self, reps, chunk=2048):
        self.reps = np.ascontiguousarray(reps, dtype=np.float32)
        self._tree = (_CKDTree(self.reps)
                      if (_CKDTree is not None and len(self.reps) > 0) else None)

    def query(self, P):
        """P(N,3) → 最近代表点索引 (N,)。"""
        n = len(P)
        M = len(self.reps)
        if M == 0:
            return np.full(n, -1)
        if self._tree is not None:
            _, j = self._tree.query(P, k=1, workers=-1)
            return np.asarray(j, dtype=np.int64)
        out = np.empty(n, dtype=np.int64)
        for i in range(0, n, 2048):
            blk = P[i:i + 2048].astype(np.float32)          # (b,3)
            d2 = ((blk[:, None, :] - self.reps[None, :, :]) ** 2).sum(-1)  # (b,M)
            out[i:i + 2048] = d2.argmin(1)
        return out


def icp(src, dst, T_init, iters=None, voxel=None, max_corr=12.0, min_pairs=200,
        max_src=None):
    """point-to-point ICP（最近点 + Kabsch）。src/dst: Nx3 点云。
    返回精修后的 4x4 变换。

    参数自适应（依据最近邻后端能力）：
      有 scipy.cKDTree（实测 15000 点查询 ~4ms）→ 高质量：iters=10 / voxel=4mm / src≤3万
      无 scipy（分块暴力，O(N·M)）      → 降规模保速度：iters=6 / voxel=8mm / src≤1.5万
    背景：曾因 6万×几万暴力最近邻单帧卡 >2 分钟；转台数据带角度先验会跳过 ICP（见 fuse_directory）。
    """
    if _CKDTree is not None:
        iters = 10 if iters is None else iters
        voxel = 4.0 if voxel is None else voxel
        max_src = 30000 if max_src is None else max_src
    else:
        iters = 6 if iters is None else iters
        voxel = 8.0 if voxel is None else voxel
        max_src = 15000 if max_src is None else max_src
    T = T_init.copy()
    src = np.asarray(src, dtype=np.float32)
    if len(src) > max_src:                       # 子采样（均匀间隔取点，保持分布）
        sel = np.linspace(0, len(src) - 1, max_src).astype(np.int64)
        src = src[sel]
    reps = voxel_down(dst, voxel)
    if len(reps) < 50:
        return T
    idx = NearestIndex(reps)
    for _ in range(iters):
        P = src @ T[:3, :3].T + T[:3, 3]
        j = idx.query(P)
        Q = reps[j]
        dist = np.linalg.norm(Q - P, axis=1)
        m = dist < max_corr
        if m.sum() < min_pairs:
            break
        dT = kabsch(P[m], Q[m])
        # 限制单步位移过大（防跳变）
        step = np.linalg.norm(dT[:3, 3])
        if step > 30.0:
            dT[:3, 3] *= 30.0 / step
        T = dT @ T
    return T


# ---------------- 融合 ----------------
def fuse(points_list, voxel=1.5):
    """多帧点云（模型坐标）→ 体素平均融合。"""
    allp = np.concatenate(points_list, axis=0)
    return voxel_down(allp, voxel)


# ---------------- 柱面展开 + 网格 ----------------
def cylindrical_unwrap(pts, theta_res_deg=0.6, y_res=1.0,
                       theta_span=360.0, y_range=None):
    """模型坐标点云 → 柱面网格 (r_grid, theta_grid, y_grid)。
    物体绕 Y 轴：θ=atan2(x,z), r=sqrt(x²+z²), 高度=y。"""
    r = np.sqrt(pts[:, 0] ** 2 + pts[:, 2] ** 2)
    th = np.arctan2(pts[:, 0], pts[:, 2])            # (-pi, pi]
    yv = pts[:, 1]
    if y_range is None:
        lo, hi = np.percentile(yv, [0.5, 99.5])
        y_range = (float(lo), float(hi))
    n_t = int(round(theta_span / theta_res_deg)) + 1
    n_y = int(round((y_range[1] - y_range[0]) / y_res)) + 1
    theta_grid = np.linspace(-np.pi, np.pi, n_t)
    y_grid = np.linspace(y_range[0], y_range[1], n_y)

    ti = np.clip(((th + np.pi) / (2 * np.pi) * (n_t - 1)).astype(np.int64), 0, n_t - 1)
    yi = np.clip(((yv - y_range[0]) / y_res).astype(np.int64), 0, n_y - 1)

    r_sum = np.zeros((n_y, n_t), dtype=np.float64)
    r_cnt = np.zeros((n_y, n_t), dtype=np.float64)
    np.add.at(r_sum, (yi, ti), r)
    np.add.at(r_cnt, (yi, ti), 1.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        r_grid = np.where(r_cnt > 0, r_sum / np.maximum(r_cnt, 1), np.nan)
    return r_grid, theta_grid, y_grid


def remove_outliers(pts, radius=4.0, min_nb=6):
    """统计离群点移除：半径 radius 内邻居数 < min_nb 的点判为噪点删除。
    栅格加速（27 邻域计数）。pts 可为 Nx3 或 Nx6。"""
    if len(pts) < 100:
        return pts
    keys = np.floor(pts[:, :3] / radius).astype(np.int64)
    grid = {}
    for i, k in enumerate(map(tuple, keys)):
        grid.setdefault(k, []).append(i)
    keep = np.ones(len(pts), dtype=bool)
    for i in range(len(pts)):
        k = keys[i]
        n = 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    cell = grid.get((k[0] + dx, k[1] + dy, k[2] + dz))
                    if cell:
                        n += len(cell)
        if n - 1 < min_nb:
            keep[i] = False
    return pts[keep]


def fill_grid_holes(g, max_iter=8):
    """迭代邻域均值填充 r_grid 的 NaN 洞（每次只填有≥2个有效邻域的洞，
    限次防无限扩散）。"""
    g = g.copy()
    for _ in range(max_iter):
        nan = np.isnan(g)
        if not nan.any():
            break
        s = np.zeros_like(g); c = np.zeros_like(g)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sh = np.roll(np.roll(g, dy, 0), dx, 1)
            ok = np.isfinite(sh)
            s[ok] += sh[ok]; c[ok] += 1
        fill = nan & (c >= 2)
        if not fill.any():
            break
        g[fill] = s[fill] / c[fill]
    return g


def grid_to_mesh(r_grid, theta_grid, y_grid, max_r_jump=25.0):
    """柱面 r 网格 → 顶点/三角面（复用 astra_make 的 2x2 单元法）。"""
    n_y, n_t = r_grid.shape
    valid = np.isfinite(r_grid)
    if valid.sum() < 100:
        raise ValueError("柱面网格有效点太少")
    TH, YY = np.meshgrid(theta_grid, y_grid)
    X = r_grid * np.sin(TH)
    Z = r_grid * np.cos(TH)
    Y = YY
    idx = -np.ones((n_y, n_t), dtype=np.int64)
    idx[valid] = np.arange(valid.sum())
    verts = np.stack([X[valid], Y[valid], Z[valid]], axis=1)

    v00 = valid[:-1, :-1]; v01 = valid[:-1, 1:]
    v10 = valid[1:, :-1]; v11 = valid[1:, 1:]
    r0 = np.where(np.isfinite(r_grid), r_grid, 0.0)     # nan→0，避免 nanmax 警告
    r00 = r0[:-1, :-1]; r01 = r0[:-1, 1:]
    r10 = r0[1:, :-1]; r11 = r0[1:, 1:]
    ok = v00 & v01 & v10 & v11
    dr = np.maximum.reduce([np.abs(r00 - r01), np.abs(r00 - r10),
                            np.abs(r01 - r11), np.abs(r10 - r11)])
    ok &= dr <= max_r_jump
    a, b = np.nonzero(ok)
    if len(a) == 0:
        raise ValueError("三角化后无面（r 跳变过滤过严？）")
    i00 = idx[a, b]; i01 = idx[a, b + 1]; i10 = idx[a + 1, b]; i11 = idx[a + 1, b + 1]
    faces = np.concatenate([np.stack([i00, i01, i10], axis=1),
                            np.stack([i01, i11, i10], axis=1)], axis=0)
    return verts, faces


# ---------------- 导出 ----------------
def load_ply(path, with_color=False):
    """读 ascii PLY。with_color=True 且文件含颜色属性时返回 (N,6)，否则 (N,3)。"""
    with open(path, "r", encoding="utf-8") as f:
        n = 0
        has_color = False
        for line in f:
            if line.startswith("property uchar red"):
                has_color = True
            if line.startswith("end_header"):
                break
            if line.startswith("element vertex"):
                n = int(line.split()[-1])
        cols = 6 if (with_color and has_color) else 3
        pts = np.empty((n, cols), dtype=np.float64)
        for i in range(n):
            p = f.readline().split()
            pts[i, 0] = float(p[0]); pts[i, 1] = float(p[1]); pts[i, 2] = float(p[2])
            if cols == 6:
                pts[i, 3] = float(p[3]); pts[i, 4] = float(p[4]); pts[i, 5] = float(p[5])
    return pts


def save_ply(path, pts, colors=None):
    """ascii PLY。colors: Nx3 uint8 可选。"""
    n = len(pts)
    with open(path, "w", encoding="utf-8") as f:
        f.write("ply\nformat ascii 1.0\n")
        f.write(f"element vertex {n}\n")
        f.write("property float x\nproperty float y\nproperty float z\n")
        if colors is not None:
            f.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
        f.write("end_header\n")
        if colors is None:
            for p in pts:
                f.write(f"{p[0]:.2f} {p[1]:.2f} {p[2]:.2f}\n")
        else:
            for p, c in zip(pts, colors):
                f.write(f"{p[0]:.2f} {p[1]:.2f} {p[2]:.2f} "
                        f"{int(c[0])} {int(c[1])} {int(c[2])}\n")


def render_preview(verts, faces, path, size=(900, 700)):
    """简易三视图预览（前视/侧视/俯视投影）。"""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", size, (18, 18, 26))
    dr = ImageDraw.Draw(img)
    v = verts
    # 轴向符合查看器惯例（x 右 / y 上 / z 朝向观察者）：
    #   前视 = x-y；侧视 = z-y（沿 x 看）；俯视 = x-z（沿 y 看，向下投影）
    views = [("前视", (0, 1)), ("侧视", (2, 1)), ("俯视", (0, 2))]
    for k, (name, (ax1, ax2)) in enumerate(views):
        ox = 20 + k * 290
        oy = 40
        w, h = 250, 250
        p1, p2 = v[:, ax1], v[:, ax2]
        lo1, hi1 = float(p1.min()), float(p1.max())
        lo2, hi2 = float(p2.min()), float(p2.max())
        s = 220 / max(hi1 - lo1, hi2 - lo2, 1e-6)
        # 面片重心投影（减绘制量）
        cen = v[faces].mean(axis=1)
        cx = (cen[:, ax1] - lo1) * s + ox
        cy = oy + h - (cen[:, ax2] - lo2) * s
        for x, y in zip(cx[::3], cy[::3]):
            dr.ellipse([x - 0.6, y - 0.6, x + 0.6, y + 0.6], fill=(0, 212, 255))
        dr.rectangle([ox, oy, ox + w, oy + h], outline=(60, 60, 80))
        dr.text((ox + 6, oy - 18), name, fill=(200, 200, 210))
    img.save(path)


# ---------------- 主流程 ----------------
def _load_frame_cloud(args):
    """并行 worker（模块级顶层函数，multiprocessing 可 pickle）：
    读一帧 → **输出端裁剪**（BUG-012：方位自适应去固定垃圾带）→ 深度反投影到
    模型系 → 体素降采样。返回 (pts, angle)。"""
    dpath, angle, cam_dist, mms, rgb_path = args
    dep = np.load(dpath).astype(np.float32)
    rgb = None
    if rgb_path and os.path.exists(rgb_path):
        try:
            from PIL import Image
            rgb = np.asarray(Image.open(rgb_path).convert("RGB"))
        except Exception:
            rgb = None
    # 输出端裁剪（BUG-012）：旧帧（640×480）含固定垃圾带——按方位检测去同侧
    # 21 列 + 顶行（L 向左裁 col0=21；R 向老帧右裁 col0=0）；已裁剪帧（619×479）
    # 原样（col0=None → 按尺寸推断）。合成无垃圾帧：不裁（保守，不误伤）。
    from core.contracts import crop_for_output, detect_garbage_side
    orig_w = dep.shape[1]
    side = detect_garbage_side(dep)
    dep, rgb = crop_for_output(dep, rgb)
    if orig_w == 640:
        col0 = _CROP_COL0 if side == 'L' else 0
    else:
        col0 = None                       # 已裁剪/异形帧 → 按尺寸推断主点
    if cam_dist <= 0:
        # 退化：用光轴附近深度当转台距离（近似；主点随裁剪帧尺寸平移，BUG-011）
        _cx, _cy = cxcy_for_shape(dep.shape, col0=col0)
        c = dep[int(_cy) - 3:int(_cy) + 3, int(_cx) - 3:int(_cx) + 3]
        cv = c[c > 0]
        cam_dist = float(np.median(cv)) * mms if len(cv) else 500.0
    pts = depth_to_model_points(dep, float(angle or 0.0), float(cam_dist),
                                float(mms), rgb=rgb, col0=col0)
    if len(pts) > 60000:                       # 上限保护（随机抽样）
        sel = np.random.default_rng(0).choice(len(pts), 60000, replace=False)
        pts = pts[sel]
    return voxel_down(pts, 2.0), float(angle or 0.0)


def fuse_directory(d, voxel=1.5, icp_iters=None, use_icp=None,
                   theta_res_deg=1.0, y_res=1.5, denoise=True,
                   on_progress=None, workers=None):
    """目录级融合。
    use_icp：None=自动（转台有角度先验→跳过 ICP；手持 angle 全 0→用 ICP 逐帧配准）。
    on_progress(stage, pct, msg)：UI 进度回调（None=仅 print）。
    workers：读帧并行线程数（None/1=串行；>1=线程池并行）。"""

    def say(stage, pct, msg):
        print(msg, flush=True)
        if on_progress is not None:
            try:
                on_progress(stage, pct, msg)
            except Exception:
                pass

    mf = os.path.join(d, "manifest.json")
    if not os.path.exists(mf):
        raise FileNotFoundError(f"缺少 manifest.json: {d}")
    man = json.load(open(mf, encoding="utf-8"))
    mms = float(man.get("mm_per_shift", 1.0))
    frames = man.get("frames", [])
    if len(frames) < 2:
        raise ValueError("至少需要 2 帧")

    # ---- 位姿策略自动判断（关键性能开关，实测差 14 倍）----
    # 转台数据：每帧角度已知（角度先验）→ 几何直接对齐已足够；
    #   ICP 精修实测耗 93% 时间且几乎不改变结果（点数 356,710 vs 360,386）→ 跳过
    # 手持数据：angle 全 0，无先验 → 必须 ICP 逐帧配准
    if use_icp is None:
        has_prior = any(abs(float(fr.get("angle") or 0.0)) > 0.5 for fr in frames)
        use_icp = not has_prior
    say("read", 0.02, "  位姿策略: " + ("ICP 配准（手持·无角度先验）" if use_icp
                                        else "角度先验（转台·跳过 ICP 精修）"))

    n = len(frames)
    say("read", 0.0, f"读取 {n} 帧 (mm/shift={mms}) ...")

    # ---- 帧任务表（并行/串行两路；cam_dist 由 worker 内按需计算）----
    tasks = []
    for fr in frames:
        dpath = os.path.join(d, fr["file"])
        tasks.append((dpath, fr.get("angle", 0.0),
                      float(fr.get("cam_dist") or 0.0), mms,
                      dpath[:-4] + "_rgb.png"))

    clouds, angles = [], []
    n_color = sum(1 for t in tasks if os.path.exists(t[4]))
    if n_color:
        say("read", 0.02, f"  {n_color}/{n} 帧带 RGB（D2C 顶点色）")

    if workers and workers > 1 and n >= 4:
        # 统一线程池（**不再使用 multiprocessing**）：
        # Windows spawn 的子进程会重新导入主模块 → 顶层设备初始化被重复执行
        # → 子进程反复 open 摄像头抢设备 → 融合死锁在 read 阶段（实测实锤）。
        # 读帧 = IO(np.load) + numpy/PIL 计算（均释放 GIL），线程池并行度足够，
        # 且无子进程启动开销与重导入风险 —— 源码 / exe / 脚本环境通用。
        from concurrent.futures import ThreadPoolExecutor
        say("read", 0.05, f"  并行读帧（{workers} 线程）...")
        with ThreadPoolExecutor(max_workers=min(workers, n)) as pool:
            for i, (pts, ang) in enumerate(pool.map(_load_frame_cloud, tasks)):
                clouds.append(pts)
                angles.append(ang)
                say("read", 0.05 + 0.35 * (i + 1) / n, f"  {i+1}/{n} 帧")
    else:
        for i, t in enumerate(tasks):
            pts, ang = _load_frame_cloud(t)
            clouds.append(pts)
            angles.append(ang)
            say("read", 0.05 + 0.35 * (i + 1) / n, f"  {i+1}/{n} 帧")

    # 位姿：每帧已由（角度先验 + 转台距离）直接变换到模型系；
    # ICP 仅做残差精修（相对上一帧的模型系点云，串行依赖链）
    say("icp", 0.42, "位姿精修（ICP，模型系）..." if use_icp else "位姿（仅角度先验）...")
    model_pts = []
    prev_model = None
    for i, (pc, ang) in enumerate(zip(clouds, angles)):
        geo = pc[:, :3]
        col = pc[:, 3:] if pc.shape[1] >= 6 else None
        if use_icp and prev_model is not None and len(pc) > 200:
            T = icp(geo, prev_model, np.eye(4), iters=icp_iters)
            geo = geo @ T[:3, :3].T + T[:3, 3]
        model_pts.append(np.concatenate([geo, col], axis=1) if col is not None else geo)
        prev_model = geo
        say("icp", 0.42 + 0.28 * (i + 1) / n,
            f"  {'ICP' if use_icp else '位姿'} {i+1}/{n}")

    say("fuse", 0.72, f"融合（体素 {voxel}mm）...")
    fused = fuse(model_pts, voxel)
    say("fuse", 0.78, f"融合点云: {len(fused)} 点")
    if denoise:
        before = len(fused)
        fused = remove_outliers(fused)
        say("fuse", 0.82, f"离群点移除: {before} → {len(fused)} 点")

    ply = os.path.join(d, "fused_points.ply")
    if fused.shape[1] >= 6:
        save_ply(ply, fused[:, :3], colors=fused[:, 3:6].astype(np.uint8))
    else:
        save_ply(ply, fused)

    say("mesh", 0.86, "柱面展开 + 网格化 ...")
    r_grid, theta_grid, y_grid = cylindrical_unwrap(
        fused[:, :3], theta_res_deg=theta_res_deg, y_res=y_res)
    r_grid = fill_grid_holes(r_grid)
    valid_g = int(np.isfinite(r_grid).sum())
    say("mesh", 0.90, f"  柱面网格 {r_grid.shape[1]}x{r_grid.shape[0]}，有效格 {valid_g} "
                      f"({100*valid_g/r_grid.size:.0f}%)")
    verts, faces = grid_to_mesh(r_grid, theta_grid, y_grid)
    stl = os.path.join(d, "fused_mesh.stl")
    write_stl(stl, verts, faces, name="astra_fuse")
    png = os.path.join(d, "fused_preview.png")
    render_preview(verts, faces, png)

    # 统计
    ext = verts.max(0) - verts.min(0)
    say("done", 1.0, f"完成：{len(fused)} 点 / {len(faces)} 面 / 包围盒 "
                     f"{ext[0]:.0f}x{ext[1]:.0f}x{ext[2]:.0f} mm")
    return fused, verts, faces


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    d = args[0]
    voxel = 1.5
    icp_iters = 10
    use_icp = "--no-icp" not in sys.argv
    for i, a in enumerate(sys.argv):
        if a == "--voxel" and i + 1 < len(sys.argv):
            voxel = float(sys.argv[i + 1])
        if a == "--icp-iters" and i + 1 < len(sys.argv):
            icp_iters = int(sys.argv[i + 1])
    fuse_directory(d, voxel=voxel, icp_iters=icp_iters, use_icp=use_icp)


if __name__ == "__main__":
    main()

def write_stl(path, verts, faces, name="astra_forge"):
    """二进制 STL 写出（verts Nx3 / faces Mx3）。"""
    tri = verts[faces]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    ln[ln == 0] = 1.0
    n = (n / ln).astype(np.float32)
    tri = tri.astype(np.float32)
    header = name.encode("ascii", "ignore")[:80].ljust(80, b" ")
    dtype = np.dtype([("n", "<f4", 3), ("v1", "<f4", 3), ("v2", "<f4", 3),
                      ("v3", "<f4", 3), ("attr", "<u2")])
    arr = np.zeros(len(faces), dtype=dtype)
    arr["n"] = n; arr["v1"] = tri[:, 0]; arr["v2"] = tri[:, 1]; arr["v3"] = tri[:, 2]
    with open(path, "wb") as f:
        f.write(header)
        f.write(struct.pack("<I", len(faces)))
        f.write(arr.tobytes())
    return len(faces)
