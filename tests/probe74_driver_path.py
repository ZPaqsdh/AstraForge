# -*- coding: utf-8 -*-
"""probe74 —— 驱动库路径解析（BUG-024）。

锁住三件事：
  ① 真实随包布局 `<安装根>/驱动工具/zadig/zadig.exe` 能被解析（旧代码少一层 `zadig/` → 永远找不到）
  ② 老布局 `驱动工具/zadig.exe` 仍兼容（向后不破）
  ③ 桌面壳（core.driverpack）与安装器（installer.setup_core）**解析结果一致**，不会漂移

用法：python tests/probe74_driver_path.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from core import driverpack  # noqa: E402
from installer import setup_core  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'✅' if ok else '❌'} {name}" + (f"  [{detail}]" if detail else ""))


MANIFEST = {
    "schema": 1,
    "updated_at": "2026-10-20",
    "drivers": [{
        "id": "winusb-astra-s-pro-0403",
        "name": "ASTRA S Pro · WinUSB",
        "match": {"vid": "2BC5", "pid": ["0403"]},
        "method": "pnputil-inf",
        "files": ["astra_s_pro/astra_s_pro.inf", "astra_s_pro/ASTRA_S_Pro.cat"],
        "requires_admin": True,
    }],
    "tools": {"zadig": "zadig/zadig.exe"},
}


def make_layout(base: Path, zadig_rel: str = "zadig/zadig.exe") -> Path:
    """造一个"安装根"：<base>/AstraForge.exe + code/ + 驱动工具/<zadig_rel>。"""
    root = base / "install"
    (root / "code").mkdir(parents=True)
    (root / "AstraForge.exe").write_bytes(b"MZ")
    pack = root / "驱动工具"
    (pack / "astra_s_pro").mkdir(parents=True)
    (pack / "manifest.json").write_text(json.dumps(MANIFEST, ensure_ascii=False), encoding="utf-8")
    (pack / "astra_s_pro" / "astra_s_pro.inf").write_text("[Version]\n", encoding="utf-8")
    (pack / "astra_s_pro" / "ASTRA_S_Pro.cat").write_bytes(b"cat")
    z = pack / zadig_rel
    z.parent.mkdir(parents=True, exist_ok=True)
    z.write_bytes(b"MZ")
    return root


def main():
    print("=== ① 真实布局：驱动工具/zadig/zadig.exe ===")
    with tempfile.TemporaryDirectory() as td:
        root = make_layout(Path(td))
        want = root / "驱动工具" / "zadig" / "zadig.exe"

        # 桌面壳：把 PROG_ROOT 指到 <安装根>/code
        old_root = driverpack.PROG_ROOT
        driverpack.PROG_ROOT = root / "code"
        try:
            got = driverpack.zadig_path()
            pack = driverpack.pack_dir()
            summary = driverpack.summary()
            match = driverpack.match_device("2BC5", "0403")
        finally:
            driverpack.PROG_ROOT = old_root

        check("driverpack 命中 驱动工具/zadig/zadig.exe",
              Path(got).resolve() == want.resolve(), got)
        check("driverpack pack_dir = 安装根/驱动工具",
              pack is not None and Path(pack).resolve() == (root / "驱动工具").resolve(), str(pack))
        check("summary 报告 zadig_ok", summary.get("zadig_ok") is True, str(summary.get("zadig")))
        check("summary 列出 1 个机型", len(summary.get("devices") or []) == 1,
              str([d.get("name") for d in summary.get("devices") or []]))
        check("VID/PID 匹配成功", bool(match) and match.get("id") == "winusb-astra-s-pro-0403",
              str((match or {}).get("id")))

        # 安装器：模拟"装到 <安装根> 后的 exe 环境"——
        # ① sys.executable 指到 <安装根>/AstraForge.exe
        # ② setup_core.__file__ 指到安装根（否则会优先命中仓库里的源码驱动库）
        import sys as _sys
        old_exe = _sys.executable
        old_meipass = getattr(_sys, "_MEIPASS", None)
        old_file = setup_core.__file__
        try:
            _sys.executable = str(root / "AstraForge.exe")
            if hasattr(_sys, "_MEIPASS"):
                delattr(_sys, "_MEIPASS")
            setup_core.__file__ = str(root / "code" / "installer" / "setup_core.py")
            inst = setup_core.driver_tool_path()
            inst_pack = setup_core.driver_pack_dir()
        finally:
            _sys.executable = old_exe
            setup_core.__file__ = old_file
            if old_meipass is not None:
                _sys._MEIPASS = old_meipass

        check("setup_core 也命中同一路径",
              Path(inst).resolve() == want.resolve(), inst)
        check("两端解析结果一致（不漂移）",
              Path(inst).resolve() == Path(got).resolve(), f"{inst} vs {got}")
        check("setup_core 的 pack_dir 也在安装根",
              inst_pack is not None and Path(inst_pack).resolve() == (root / "驱动工具").resolve(),
              str(inst_pack))

        print("\n=== ② 老布局：驱动工具/zadig.exe（向后兼容） ===")
    with tempfile.TemporaryDirectory() as td:
        root = make_layout(Path(td), zadig_rel="zadig.exe")
        old_root = driverpack.PROG_ROOT
        driverpack.PROG_ROOT = root / "code"
        try:
            got_old = driverpack.zadig_path()
        finally:
            driverpack.PROG_ROOT = old_root
        check("老布局仍能找到 zadig.exe",
              Path(got_old).resolve() == (root / "驱动工具" / "zadig.exe").resolve(), got_old)

    print("\n=== ③ 源码布局（本仓库） ===")
    src_pack = driverpack.pack_dir()
    src_zadig = driverpack.zadig_path()
    check("源码布局 pack 存在", bool(src_pack) and (src_pack / "manifest.json").exists(), str(src_pack))
    check("源码布局 zadig 存在", bool(src_zadig) and Path(src_zadig).exists(), str(src_zadig))
    check("源码布局 manifest 可读", bool(driverpack.load_manifest().get("drivers")))

    print("\n=== ④ 安装流程驱动步（ensure_depth_driver 分支） ===")
    old_detect = setup_core.detect_cameras
    try:
        setup_core.detect_cameras = lambda *a, **k: {"ok": True, "depth": {"found": False}}
        r_none = setup_core.ensure_depth_driver(auto_install=False)
        check("没插设备 → skipped（不阻塞安装）",
              r_none.get("skipped") is True and not r_none.get("ok"), str(r_none.get("msg"))[:60])

        setup_core.detect_cameras = lambda *a, **k: {
            "ok": True, "depth": {"found": True, "state": "ready", "pid": "0403", "service": "WinUSB"}}
        r_ready = setup_core.ensure_depth_driver(auto_install=True)
        check("已是 WinUSB → 跳过（幂等）",
              r_ready.get("already") is True, str(r_ready.get("msg"))[:60])

        setup_core.detect_cameras = lambda *a, **k: {
            "ok": True, "depth": {"found": True, "state": "nodriver", "pid": "0403", "service": ""}}
        r_skip = setup_core.ensure_depth_driver(auto_install=False)
        check("无驱动但未授权自动装 → pending",
              r_skip.get("pending") is True, str(r_skip.get("msg"))[:60])
    finally:
        setup_core.detect_cameras = old_detect

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n[74] {passed}/{total} 通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
