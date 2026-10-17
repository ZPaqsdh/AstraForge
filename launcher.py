# -*- coding: utf-8 -*-
"""AstraForge 引导器（PyInstaller 打包目标）。

设计：exe 只自带 Python 运行时与第三方依赖；**程序代码在 exe 同级 code/ 目录**
（core/modules/ui/main.py）——这样 OTA 热更新替换 code/ 即可，无需重装。

下面的 import 只为让 PyInstaller 收集依赖（运行时由 code/main.py 真正使用）。
"""
import importlib
import os
import runpy
import sys

# ---- 依赖收集（勿删；PyInstaller 靠这些把依赖打进 _internal）----
import numpy            # noqa: F401
import PIL              # noqa: F401
import PIL.Image        # noqa: F401
import PIL.ImageDraw    # noqa: F401
import PIL.ImageFont    # noqa: F401
import PIL.ImageTk      # noqa: F401
import tkinter          # noqa: F401
import usb.core         # noqa: F401
import usb.util         # noqa: F401
import astra_raw        # noqa: F401
import astra_raw.transport  # noqa: F401

try:
    import cv2          # noqa: F401
except Exception:
    pass

# ---- 内置浏览器内核（QtWebEngine；勿删，PyInstaller 靠这些收集）----
try:
    import PySide6                      # noqa: F401
    import PySide6.QtCore               # noqa: F401
    import PySide6.QtWidgets            # noqa: F401
    import PySide6.QtWebEngineWidgets   # noqa: F401
except Exception:
    pass


def _base_dir():
    """exe 所在目录（PyInstaller 下 sys.executable 即 exe 路径）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def main():
    # PyInstaller + multiprocessing：冻结环境必须 freeze_support，
    # 否则融合的并行子进程会重新拉起整个 exe（弹窗/卡死）
    try:
        import multiprocessing
        multiprocessing.freeze_support()
    except Exception:
        pass
    base = _base_dir()
    try:
        code = os.path.join(base, "code")
        if not os.path.isdir(code):
            # 开发模式：从源码目录找
            code = base if os.path.isdir(os.path.join(base, "core")) else code
        # 新架构入口：shell.py（React UI + Edge 应用窗口）；回退 tk 版 main.py
        entry = os.path.join(code, "shell.py")
        if not os.path.isfile(entry):
            entry = os.path.join(code, "main.py")
        if not os.path.isfile(entry):
            _report(base, f"未找到程序代码目录：\n{code}\n\n"
                          "请确认 code/ 与 AstraForge.exe 在同一目录。")
            return 1
        os.chdir(code)
        sys.path.insert(0, code)
        runpy.run_path(entry, run_name="__main__")
        return 0
    except Exception:
        import traceback
        _report(base, traceback.format_exc())
        return 1


def _report(base, text):
    """windowed 模式无控制台——错误必须落盘 + 弹窗，否则黑箱。"""
    import time as _t
    try:
        with open(os.path.join(base, "launcher_error.log"), "a",
                  encoding="utf-8") as f:
            f.write(f"\n===== {_t.strftime('%Y-%m-%d %H:%M:%S')} =====\n{text}\n")
    except Exception:
        pass
    try:
        import tkinter as tk
        import tkinter.messagebox as mb
        r = tk.Tk()
        r.withdraw()
        mb.showerror("AstraForge 启动失败",
                     "详情已写入 launcher_error.log：\n\n" + text[-1200:])
        r.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
