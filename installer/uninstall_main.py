# -*- coding: utf-8 -*-
"""AstraForge 星铸 · 轻量卸载器（单文件，tkinter，不依赖 QtWebEngine）

为什么单独做一个：
- 安装器改成**单文件 exe**（内嵌 600MB 载荷）后，不能把安装器整份复制成卸载器
  （否则安装目录白白多出 700MB）；卸载器只需要“确认 + 删文件 + 清注册”，
  用系统自带的 tkinter 即可，最终 exe 约 15~25MB。

用法：
    AstraForge-卸载.exe                  # 读注册表，进卸载界面
    AstraForge-卸载.exe --silent         # 静默卸载（保留扫描输出与设置）
    AstraForge-卸载.exe --dir <目录>     # 指定安装目录
    AstraForge-卸载.exe --test-root <目录>  # 沙箱（测试用，不碰真实系统）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

APP_VERSION = '0.3.3'
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import setup_core as C  # noqa: E402

BG = '#eef1f5'
CARD = '#ffffff'
INK = '#1f2937'
SUB = '#6b7280'
BLUE = '#2563eb'
BLUE_DARK = '#1d4ed8'
RED = '#dc2626'


def _log(msg: str):
    try:
        p = Path(os.environ.get('TEMP', '.')) / 'AstraForge-setup.log'
        with p.open('a', encoding='utf-8') as f:
            f.write(f'[{time.strftime("%H:%M:%S")}] [uninst] {msg}\n')
    except Exception:
        pass


def resolve_target(args, sb) -> tuple[str, dict | None]:
    if sb.on:
        d = str(sb.root / 'install')
        return d, C.find_installed(sb)
    if args.dir:
        return args.dir, C.find_installed(sb)
    ins = C.find_installed(sb)
    return (str((ins or {}).get('dir') or ''), ins)


def do_uninstall(target: str, keep_data: bool, sb, cb=None) -> dict:
    if not target:
        return {'ok': False, 'msg': '未找到 AstraForge 的安装记录。'}
    r = C.uninstall(target, keep_data=keep_data, cb=cb, sb=sb)
    if r.get('ok') and r.get('cleanup_paths'):
        C.schedule_final_cleanup(r['cleanup_paths'])
    return r


# ------------------------------------------------------------------ GUI
class App:
    def __init__(self, root, target: str, info: dict | None, sb):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.root = root
        self.target = target
        self.sb = sb
        self.done = False
        self._worker: threading.Thread | None = None

        root.title(f'卸载 {C.APP_CN}')
        root.configure(bg=BG)
        root.geometry('520x360')
        root.resizable(False, False)
        self._center(root, 520, 360)

        style = ttk.Style()
        try:
            style.theme_use('clam')
        except Exception:
            pass
        style.configure('TProgressbar', troughcolor='#e5e7eb', background=BLUE,
                        bordercolor='#e5e7eb', lightcolor=BLUE, darkcolor=BLUE)

        card = tk.Frame(root, bg=CARD, highlightbackground='#d7dce3', highlightthickness=1)
        card.place(x=18, y=16, width=484, height=328)

        tk.Label(card, text=f'卸载 {C.APP_CN}', bg=CARD, fg=INK,
                 font=('Microsoft YaHei UI', 16, 'bold')).place(x=22, y=18)
        tk.Label(card, text=f'版本 v{(info or {}).get("version", APP_VERSION)}　·　'
                            f'{(info or {}).get("dir", target)}',
                 bg=CARD, fg=SUB, font=('Microsoft YaHei UI', 9)).place(x=22, y=52)

        tip = ('将删除程序文件、快捷方式与注册信息。\n'
               '「扫描输出」和设置数据默认保留，可随时重装继续用。')
        tk.Label(card, text=tip, justify='left', bg=CARD, fg=INK,
                 font=('Microsoft YaHei UI', 10)).place(x=22, y=84)

        self.keep = tk.BooleanVar(value=True)
        ttk.Checkbutton(card, text='保留「扫描输出」与设置（推荐）', variable=self.keep).place(x=20, y=140)

        if C.is_app_running():
            tk.Label(card, text='注意：AstraForge 正在运行，卸载会先关闭它。',
                     bg=CARD, fg=RED, font=('Microsoft YaHei UI', 9)).place(x=22, y=172)

        self.bar = ttk.Progressbar(card, mode='determinate', maximum=100)
        self.bar.place(x=22, y=204, width=440, height=14)
        self.status = tk.Label(card, text='准备就绪', bg=CARD, fg=SUB,
                               anchor='w', font=('Microsoft YaHei UI', 9))
        self.status.place(x=22, y=224, width=440)

        self.btn_cancel = tk.Button(card, text='取消', command=root.destroy,
                                    bg='#f3f4f6', fg=INK, relief='flat',
                                    font=('Microsoft YaHei UI', 10), cursor='hand2')
        self.btn_cancel.place(x=286, y=268, width=80, height=34)
        self.btn_go = tk.Button(card, text='开始卸载', command=self.start,
                                bg=BLUE, fg='white', activebackground=BLUE_DARK,
                                activeforeground='white', relief='flat',
                                font=('Microsoft YaHei UI', 10, 'bold'), cursor='hand2')
        self.btn_go.place(x=376, y=268, width=96, height=34)

        if not target or not Path(target).exists():
            self.btn_go.config(state='disabled')
            self.status.config(text='未找到安装目录，无法卸载', fg=RED)

    @staticmethod
    def _center(win, w, h):
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f'{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}')

    def _ui(self, fn, *a):
        try:
            self.root.after(0, lambda: fn(*a))
        except Exception:
            pass

    def _progress(self, pct, text):
        self._ui(self._set_progress, pct, text)

    def _set_progress(self, pct, text):
        if self.done:
            return
        self.bar['value'] = max(0, min(100, int(pct)))
        self.status.config(text=str(text), fg=SUB)

    def start(self):
        if self._worker:
            return
        self.btn_go.config(state='disabled', text='卸载中…')
        self.btn_cancel.config(state='disabled')
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _run(self):
        try:
            r = do_uninstall(self.target, self.keep.get(), self.sb, cb=self._progress)
        except Exception as e:  # noqa: BLE001
            r = {'ok': False, 'msg': f'{type(e).__name__}: {e}'}
        _log(f'gui uninstall → {r.get("ok")} {r.get("msg")} {self.target}')
        self._ui(self._done, r)

    def _done(self, r: dict):
        self.done = True
        self.bar['value'] = 100
        if r.get('ok'):
            self.status.config(text='卸载完成（扫描输出与设置已保留）', fg='#059669')
            self.btn_cancel.place_forget()
            self.btn_go.config(state='normal', text='关闭', command=self.root.destroy)
        else:
            self.status.config(text=f'卸载失败：{r.get("msg", "")}', fg=RED)
            self.btn_cancel.config(state='normal')
            self.btn_go.config(state='normal', text='重试', command=self._retry)

    def _retry(self):
        self.done = False
        self._worker = None
        self.btn_go.config(command=self.start)
        self.start()


def run_gui(target: str, info: dict | None, sb) -> int:
    import tkinter as tk
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root, target, info, sb)
    root.mainloop()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--uninstall', action='store_true', help='兼容注册表命令行（可忽略）')
    ap.add_argument('--dir', default='', help='安装目录（留空=读注册表）')
    ap.add_argument('--test-root', default='', help='沙箱测试根目录')
    ap.add_argument('--silent', action='store_true', help='静默卸载')
    ap.add_argument('--version', default=APP_VERSION)
    args = ap.parse_args()
    sb = C.Sandbox(Path(args.test_root) if args.test_root else None)
    target, info = resolve_target(args, sb)

    if args.silent:
        r = do_uninstall(target, keep_data=True, sb=sb)
        _log(f'silent → {r}')
        try:
            sys.stdout.write(json.dumps(r, ensure_ascii=False) + '\n')
        except Exception:
            pass
        return 0 if r.get('ok') else 1

    return run_gui(target, info, sb)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        _log('启动异常: ' + traceback.format_exc())
        try:
            import tkinter.messagebox as mb
            mb.showerror('AstraForge 卸载器', '启动失败：\n' + traceback.format_exc()[-800:])
        except Exception:
            pass
        sys.exit(2)
