# -*- coding: utf-8 -*-
"""应用设置持久化（data/设置.json）——所有设置自动保存、下次启动自动还原。

用法：
    from core import appsettings
    appsettings.update(data_dir, perf_mode="std")   # 写（合并）
    d = appsettings.load(data_dir)                  # 读（dict，缺文件返回 {}）

设计要点：
- 原子写（tmp + os.replace），进程崩在写一半也不会留坏文件；
- 失败静默：持久化失败绝不影响功能（只损失"记住"能力）；
- 存放位置 = 各端 data_dir（工作区/发行版 code/data/设置.json）；
  OTA 热替换 code/ 时 data/ 不在替换范围，设置不丢。
"""
import json
import os
import threading

_lock = threading.Lock()


def _path(data_dir):
    return os.path.join(str(data_dir), "设置.json")


def load(data_dir):
    """读全部设置；文件不存在/损坏 → 返回空 dict。"""
    try:
        with open(_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def update(data_dir, **kv):
    """合并写入若干键值并落盘（线程安全）。返回合并后的 dict。"""
    with _lock:
        d = load(data_dir)
        d.update(kv)
        try:
            os.makedirs(str(data_dir), exist_ok=True)
            tmp = _path(data_dir) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, _path(data_dir))
        except Exception:
            pass
        return d
