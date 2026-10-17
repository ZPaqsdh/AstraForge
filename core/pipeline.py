# -*- coding: utf-8 -*-
"""管线引擎：模块加载（外置/可热替换）、装配、启停。

OTA 地基：
- load_module_dir 用 importlib 从**目录**加载模块——GitHub 热更新只需
  替换 modules/<name>/ 目录内容 + 重启进程，无需重装（PyInstaller 打包后
  模块在程序同级目录，照样可换）。
- 启动顺序按 module.json 的 depends_on 拓扑排序。
"""
import importlib.util
import json
import sys
import threading
from pathlib import Path

from .events import EventBus


class Pipeline:
    def __init__(self, root: Path, bus: EventBus | None = None):
        self.root = Path(root)
        self.bus = bus or EventBus()
        self.modules: dict[str, object] = {}          # name -> Module 实例
        self._meta: dict[str, dict] = {}              # name -> module.json
        self._lock = threading.Lock()

    # ---------- 外置模块加载（热更新核心） ----------
    def load_module_dir(self, mod_dir: Path):
        """从目录加载模块：读 module.json → importlib 加载入口类 → 实例化。"""
        mod_dir = Path(mod_dir)
        meta = json.loads((mod_dir / "module.json").read_text(encoding="utf-8"))
        entry = meta["entry"]                          # "module.py:FusionModule"
        py_file, cls_name = entry.split(":")
        py_path = mod_dir / py_file
        if not py_path.exists():
            raise FileNotFoundError(f"模块入口不存在: {py_path}")
        # 以文件路径加载（模块目录整体可替换 → 热更新）
        mod_name = f"af_mod_{meta['name']}"
        spec = importlib.util.spec_from_file_location(mod_name, py_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        cls = getattr(mod, cls_name)
        inst = cls()
        if getattr(inst, "name", None) != meta["name"]:
            raise ValueError(f"模块名不一致: {inst.name!r} != {meta['name']!r}")
        with self._lock:
            self.modules[meta["name"]] = inst
            self._meta[meta["name"]] = meta
        return inst

    def load_all_modules(self, modules_dir: Path | None = None):
        """加载 modules/ 下全部模块（按 depends_on 拓扑排序后装配）。"""
        mdir = Path(modules_dir or (self.root / "modules"))
        loaded = [self.load_module_dir(p) for p in sorted(mdir.iterdir())
                  if p.is_dir() and (p / "module.json").exists()]
        # 拓扑排序（depends_on）
        ordered, seen = [], set()

        def visit(name):
            if name in seen or name not in self.modules:
                return
            seen.add(name)
            for dep in self._meta[name].get("depends_on", []):
                visit(dep)
            ordered.append(name)

        for name in list(self.modules):
            visit(name)
        self._order = ordered
        return loaded

    # ---------- 装配与启停 ----------
    def setup_all(self, ctx):
        for name in getattr(self, "_order", list(self.modules)):
            try:
                self.modules[name].setup(ctx)
            except Exception as e:
                self.bus.publish("module.log", (f"模块 {name} setup 失败: {e}", False))

    def start_all(self):
        for name in getattr(self, "_order", list(self.modules)):
            try:
                self.modules[name].start()
            except Exception as e:
                self.bus.publish("module.log", (f"模块 {name} start 失败: {e}", False))

    def stop_all(self):
        for name in reversed(getattr(self, "_order", list(self.modules))):
            try:
                self.modules[name].stop()
            except Exception:
                pass

    def get(self, name: str):
        return self.modules.get(name)

    def versions(self) -> dict:
        return {n: self._meta[n].get("version", "?") for n in self.modules}
