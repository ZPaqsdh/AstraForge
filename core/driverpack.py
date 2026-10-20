# -*- coding: utf-8 -*-
"""驱动库解析与安装（单一来源）—— 随包 `驱动工具/`。

BUG-024：Zadig 真实路径是 `驱动工具/zadig/zadig.exe`（多一层 `zadig/`），
但旧代码在 `shell.api_paths` 与 `installer/setup_core.driver_tool_path` 里
都写成 `驱动工具/zadig.exe` → 两处全部不命中 → 「打开驱动工具」只弹"找不到"。

本模块把"去哪找、怎么装"收敛成一份实现：
- 相对路径**优先读 manifest.json 的 tools.zadig**，不写死；
- 兜底列表只为老包兼容（`驱动工具/zadig.exe`、`installer/driver/zadig.exe`）；
- 安装器（setup_core）与桌面壳（shell.py）都按同一份候选顺序找 → 不会漂移。

目录形态：
    安装版  <安装根>/驱动工具/{manifest.json, astra_s_pro/*.inf|.cat, zadig/zadig.exe}
    源码    <程序根>/installer/driver/pack/…   （+ installer/driver/zadig.exe 旧布局）
    安装器  <_MEIPASS>/driver_pack/…            （PyInstaller onefile 内）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

DRIVER_DIR_NAME = "驱动工具"
MANIFEST_NAME = "manifest.json"

#: 桌面壳/源码布局下 `core/` 的上一层（= code 根）
PROG_ROOT = Path(__file__).resolve().parent.parent


def is_admin() -> bool:
    """当前进程是否管理员（提权安装驱动用）。"""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def candidate_dirs() -> list[Path]:
    """驱动库候选目录（按优先级）。安装根那份排最前——它是长期保留的唯一源。"""
    out: list[Path] = []

    def add(p: Path | None):
        if p is None:
            return
        try:
            if p not in out:
                out.append(p)
        except Exception:
            pass

    # 1) 安装根：<安装根>/驱动工具（程序 code/ 的父目录）
    add(PROG_ROOT.parent / DRIVER_DIR_NAME)
    # 2) exe 所在目录（onefile / 便携版）
    try:
        add(Path(sys.executable).resolve().parent / DRIVER_DIR_NAME)
    except Exception:
        pass
    # 3) 程序根下的 驱动工具（个别便携布局）
    add(PROG_ROOT / DRIVER_DIR_NAME)
    # 4) 源码布局
    add(PROG_ROOT / "installer" / "driver" / "pack")
    add(PROG_ROOT / "installer" / "driver")
    # 5) PyInstaller onefile 安装器自带
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        add(Path(meipass) / "driver_pack")
    return out


def pack_dir() -> Path | None:
    """驱动库根目录（含 manifest.json 的那一层）。"""
    for d in candidate_dirs():
        try:
            if (d / MANIFEST_NAME).exists():
                return d
        except Exception:
            continue
    return None


def load_manifest() -> dict:
    """读驱动库清单；缺失/损坏返回 {}。"""
    d = pack_dir()
    if not d:
        return {}
    try:
        data = json.loads((d / MANIFEST_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _zadig_rel_from_manifest(man: dict) -> str:
    tools = man.get("tools") or {}
    if isinstance(tools, dict):
        return str(tools.get("zadig") or "").strip()
    return ""


def zadig_path() -> str:
    """Zadig 可执行文件绝对路径；找不到返回 ""。

    顺序：manifest.tools.zadig（相对驱动库根）→ 老包兜底扫描。
    """
    d = pack_dir()
    rel = _zadig_rel_from_manifest(load_manifest())
    if d and rel:
        try:
            p = (d / rel).resolve()
            if p.exists():
                return str(p)
        except Exception:
            pass
    # 兜底：真实布局 驱动工具/zadig/zadig.exe，再兼容旧写法
    for base in candidate_dirs():
        for sub in ("zadig/zadig.exe", "zadig.exe",
                    "zadig/x64/zadig.exe", "zadig/x86/zadig.exe"):
            try:
                p = base / sub
                if p.exists():
                    return str(p)
            except Exception:
                continue
    return ""


def match_device(vid: str, pid: str) -> dict | None:
    """按 VID/PID 匹配驱动条目。"""
    vid, pid = (vid or "").upper(), (pid or "").upper()
    if not vid or not pid:
        return None
    for drv in load_manifest().get("drivers") or []:
        try:
            mt = drv.get("match") or {}
            if str(mt.get("vid", "")).upper() != vid:
                continue
            pids = [str(x).upper() for x in (mt.get("pid") or [])]
            if pid in pids:
                return drv
        except Exception:
            continue
    return None


def device_entry(driver_id: str) -> dict | None:
    for drv in load_manifest().get("drivers") or []:
        if str(drv.get("id")) == driver_id:
            return drv
    return None


def install_driver(driver_id: str) -> dict:
    """安装驱动：签名 INF 走 pnputil（非管理员自动提权）；无签名引导 Zadig。"""
    d = pack_dir()
    entry = device_entry(driver_id)
    if not d or not entry:
        return {"ok": False, "error": f"驱动条目不存在：{driver_id}",
                "hint": "驱动库缺失或 manifest 未包含该条目"}
    method = str(entry.get("method") or "")
    files = entry.get("files") or []

    if method == "pnputil-inf":
        if not files:
            return {"ok": False, "error": "manifest 未列出 INF 文件"}
        inf = (d / str(files[0])).resolve()
        if not inf.exists():
            return {"ok": False, "error": f"驱动文件缺失：{inf}"}
        if is_admin():
            try:
                r = subprocess.run(["pnputil", "/add-driver", str(inf), "/install"],
                                   capture_output=True, timeout=180)
                out = (r.stdout or b"").decode("gbk", errors="replace")
                ok = r.returncode == 0
                return {"ok": ok, "msg": "驱动已安装" if ok else "驱动安装失败",
                        "output": out[-800:], "admin": True}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": f"pnputil 调用失败：{e}"}
        ps = ("Start-Process -FilePath pnputil.exe -ArgumentList "
              f"'/add-driver','\"{inf}\"','/install' -Verb RunAs -Wait -WindowStyle Hidden")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                               capture_output=True, timeout=180)
            out = (r.stdout or b"").decode("gbk", errors="replace")
            return {"ok": r.returncode == 0, "elevated": True,
                    "msg": "已请求管理员权限；在系统弹窗确认后点「重新检测」",
                    "output": out[-400:]}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"提权失败：{e}"}

    if method == "zadig-guided":
        return {"ok": False, "guided": True, "zadig": zadig_path(),
                "msg": "该驱动无签名，需用随包驱动工具（Zadig）按向导安装"}
    return {"ok": False, "error": f"未知安装方式：{method}"}


def summary() -> dict:
    """给 UI 的驱动库摘要（不触发设备枚举）。"""
    d = pack_dir()
    man = load_manifest()
    devices = []
    for drv in man.get("drivers") or []:
        try:
            mt = drv.get("match") or {}
            devices.append({
                "id": str(drv.get("id") or ""),
                "name": str(drv.get("name") or ""),
                "vid": str(mt.get("vid") or ""),
                "pids": [str(x) for x in (mt.get("pid") or [])],
                "method": str(drv.get("method") or ""),
                "requires_admin": bool(drv.get("requires_admin")),
            })
        except Exception:
            continue
    zp = zadig_path()
    return {
        "has_pack": d is not None,
        "pack_dir": str(d) if d else "",
        "manifest_updated_at": str(man.get("updated_at") or ""),
        "devices": devices,
        "zadig": zp,
        "zadig_ok": bool(zp),
    }
