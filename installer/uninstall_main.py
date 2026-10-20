# -*- coding: utf-8 -*-
"""AstraForge 星铸 · 轻量卸载器（单文件，tkinter，不依赖 QtWebEngine）

为什么单独做一个：
- 安装器是单文件 exe（内嵌数百 MB 载荷），不能整份复制成卸载器；
  卸载器只需「确认 + 删文件 + 清注册」，tkinter 足够，exe 约 20MB。

用法：
    AstraForge-卸载.exe                  # 自动定位（自举/注册表），进卸载界面
    AstraForge-卸载.exe --dir <目录>     # 显式指定安装目录（注册表 UninstallString 自带）
    AstraForge-卸载.exe --silent         # 静默卸载（保留扫描输出与设置）
    AstraForge-卸载.exe --test-root <目录>  # 沙箱（测试用，不碰真实系统）

定位链（2026-10-20 定案，修「未找到安装目录」）：
    ① --dir 参数（注册表 UninstallString 已带上）
    ② 自举：自身旁边有 AstraForge.exe / install.json → 就是安装目录（便携版双击）
    ③ 注册表 InstallLocation
    ④ 都没有 → 界面给「手动选择目录…」

视觉：与主程序白色主题（index.css [data-theme=light]）逐 token 对齐，不自由发挥。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

APP_VERSION = '0.3.6'
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import setup_core as C  # noqa: E402

# ---- 主题 token（源：ui-web/src/index.css [data-theme="light"]，一字不改）----
BG = '#f3f3f3'            # --bg
CARD = '#ffffff'          # --card
BTN_BG = '#ffffff'        # --btn
BTN_HOVER = '#f0f0f0'     # --btn-hover
BORDER = '#e5e5e5'        # --border
BORDER_S = '#d6d6d6'      # --border-strong
FG = '#1b1b1b'            # --fg
MUTED = '#4f4f4f'         # --muted
DIM = '#8a8a8a'           # --dim
ACCENT = '#005fb8'        # --accent
ACCENT_HOVER = '#0078d4'  # --accent-hover
OK = '#0f7b0f'            # --ok
WARN = '#9d5d00'          # --warn
ERR = '#c42b1c'           # --err
ERR_HOVER = '#a82416'
RADIUS = 9                # --radius（卡片）；按钮 8（.af-btn）
FONT = ('Microsoft YaHei UI', 9)        # body 13.5px 中文等效
FONT_B = ('Microsoft YaHei UI', 9, 'bold')
FONT_T = ('Microsoft YaHei UI', 11, 'bold')   # .af-modal header h3 ≈ 14px
FONT_S = ('Microsoft YaHei UI', 8)            # .af-modal-hint 11px
FONT_BTN = ('Microsoft YaHei UI', 9)          # .af-btn 12px
MONO = ('Consolas', 9)


def _log(msg: str):
    try:
        p = Path(os.environ.get('TEMP', '.')) / 'AstraForge-setup.log'
        with p.open('a', encoding='utf-8') as f:
            f.write(f'[{time.strftime("%H:%M:%S")}] [uninst] {msg}\n')
    except Exception:
        pass


# ---------------------------------------------------------------- 圆角图元
def _round_rect(c, x1, y1, x2, y2, r, **kw):
    """canvas 圆角矩形（smooth polygon 近似，r=px）。"""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, splinesteps=16, **kw)


def _make_rounded_button(parent, text, command, kind='normal', w=96, h=32,
                         parent_bg=CARD, enabled=True):
    """.af-btn 复刻：高 32、圆角 8、1px 描边、12px 字。kind: normal/primary/danger/ghost。"""
    import tkinter as tk

    style = {
        'normal':  (BTN_BG, FG, BORDER_S, BTN_HOVER, FG),
        'primary': (ACCENT, '#ffffff', ACCENT, ACCENT_HOVER, '#ffffff'),
        'danger':  (ERR, '#ffffff', ERR, ERR_HOVER, '#ffffff'),
        'ghost':   (parent_bg, MUTED, parent_bg, BTN_HOVER, FG),
    }[kind]
    fill, fg, outline, hfill, hfg = style

    c = tk.Canvas(parent, width=w, height=h, bg=parent_bg, highlightthickness=0, bd=0)
    c.enabled = enabled

    def draw(hover=False):
        c.delete('all')
        f = (hfill if hover else fill) if c.enabled else BTN_BG
        o = outline
        t = (hfg if hover else fg) if c.enabled else DIM
        _round_rect(c, 1, 1, w - 1, h - 1, RADIUS - 1, fill=f, outline=o, width=1)
        c.create_text(w // 2, h // 2 + 1, text=text, fill=t, font=FONT_BTN)

    def click(_):
        if c.enabled and command:
            command()

    c.draw = draw
    c.bind('<Enter>', lambda e: draw(True) if c.enabled else None)
    c.bind('<Leave>', lambda e: draw(False))
    c.bind('<Button-1>', click)
    c.config(cursor='hand2' if enabled else 'arrow')
    draw(False)
    return c


class CheckRow:
    """.af-check 复刻：15px 圆角 4 勾选框（accent #005fb8）+ 9pt 标签。整行可点。"""
    def __init__(self, parent, text, checked=False, command=None, parent_bg=CARD):
        import tkinter as tk
        self.var = tk.BooleanVar(value=checked)
        self.cmd = command
        self.frame = tk.Frame(parent, bg=parent_bg, cursor='hand2')
        self.box = tk.Canvas(self.frame, width=15, height=15, bg=parent_bg,
                             highlightthickness=0, bd=0)
        self.box.pack(side='left', padx=(0, 6))
        self.label = tk.Label(self.frame, text=text, bg=parent_bg, fg=MUTED, font=FONT)
        self.label.pack(side='left')
        self._draw()
        for w in (self.frame, self.box, self.label):
            w.bind('<Button-1>', self._toggle)
        self.frame.bind('<Enter>', lambda e: self.label.config(fg=FG))
        self.frame.bind('<Leave>', lambda e: self.label.config(fg=MUTED))

    def _draw(self):
        c = self.box
        c.delete('all')
        if self.var.get():
            _round_rect(c, 1, 1, 14, 14, 4, fill=ACCENT, outline=ACCENT)
            c.create_line(4, 8, 6.5, 10.5, 11, 4.5, fill='#ffffff', width=2,
                          capstyle='round', joinstyle='round')
        else:
            _round_rect(c, 1, 1, 14, 14, 4, fill=CARD, outline=BORDER_S)

    def _toggle(self, _=None):
        self.var.set(not self.var.get())
        self._draw()
        if self.cmd:
            self.cmd(self.var.get())

    def get(self):
        return self.var.get()


# ---------------------------------------------------------------- 定位
def _dir_info(target: str, ins: dict | None) -> dict:
    """合并目录自身 install.json 与注册表信息（自举时注册表可能没有）。"""
    info = dict(ins or {})
    if target:
        info.setdefault('dir', target)
        p = Path(target) / 'install.json'
        if p.exists():
            try:
                j = json.loads(p.read_text(encoding='utf-8'))
                if not info.get('version') or info.get('version') == '?':
                    info['version'] = str(j.get('version') or '')
                if not info.get('date') or info.get('date') == '?':
                    info['date'] = str(j.get('installed_at') or '')
            except Exception:
                pass
    if not info.get('version'):
        info['version'] = APP_VERSION
    return info


def resolve_target(args, sb) -> tuple[str, dict | None]:
    if sb.on:
        d = str(sb.root / 'install')
        return d, _dir_info(d, C.find_installed(sb))
    # ① 显式 --dir（注册表 UninstallString 自带）
    if args.dir:
        d = args.dir
        return d, _dir_info(d, C.find_installed(sb))
    # ② 自举：卸载器旁有 AstraForge.exe / install.json → 就是安装目录
    if getattr(sys, 'frozen', False):
        self_dir = Path(sys.executable).resolve().parent
        if (self_dir / C.APP_EXE).exists() or (self_dir / 'install.json').exists():
            return str(self_dir), _dir_info(str(self_dir), C.find_installed(sb))
    # ③ 注册表
    ins = C.find_installed(sb)
    d = str((ins or {}).get('dir') or '')
    return d, _dir_info(d, ins) if d else ins


def do_uninstall(target: str, keep_data: bool, remove_driver: bool, sb, cb=None) -> dict:
    if not target:
        return {'ok': False, 'msg': '未找到 AstraForge 的安装目录。'}
    r = C.uninstall(target, keep_data=keep_data, cb=cb, sb=sb,
                    remove_driver=remove_driver)
    if r.get('ok') and r.get('cleanup_paths'):
        C.schedule_final_cleanup(r['cleanup_paths'])
    return r


# ---------------------------------------------------------------- GUI
class App:
    W, H = 560, 512

    def __init__(self, root, target: str, info: dict | None, sb):
        import tkinter as tk

        self.tk = tk
        self.root = root
        self.target = target
        self.info = info or {}
        self.sb = sb
        self.done = False
        self._worker: threading.Thread | None = None

        root.title(f'卸载 {C.APP_CN}')
        root.configure(bg=BG)
        root.geometry(f'{self.W}x{self.H}')
        root.resizable(False, False)
        self._center(root, self.W, self.H)

        # 卡片底（圆角 9 = --radius，描边 --border）
        self.canvas = tk.Canvas(root, bg=BG, highlightthickness=0, bd=0)
        self.canvas.place(x=0, y=0, w=self.W, h=self.H)
        _round_rect(self.canvas, 14, 14, self.W - 14, self.H - 14, RADIUS,
                    fill=CARD, outline=BORDER, width=1)
        # 内容层（内缩 ≥ 圆角，保住卡片圆角弧）
        self.body = tk.Frame(self.canvas, bg=CARD)
        self.canvas.create_window(self.W // 2, self.H // 2, window=self.body,
                                  width=self.W - 56, height=self.H - 56)

        self._build()

    # ---- 确认态 ----
    def _build(self):
        import tkinter as tk
        for w in self.body.winfo_children():
            w.destroy()

        top = tk.Frame(self.body, bg=CARD)
        top.pack(fill='x')
        tk.Label(top, text=f'卸载 {C.APP_CN}', bg=CARD, fg=FG,
                 font=FONT_T).pack(side='left')
        tk.Label(top, text='需要管理员权限时系统会弹出确认', bg=CARD, fg=DIM,
                 font=FONT_S).pack(side='right', pady=(4, 0))

        ver = str(self.info.get('version') or APP_VERSION)
        parts = [f'版本 v{ver}']
        if self.target:
            parts.append(self.target)
        meta = ' · '.join(parts)
        tk.Label(self.body, text=meta, bg=CARD, fg=DIM, font=MONO,
                 anchor='w').pack(fill='x', pady=(4, 0))

        sep = tk.Frame(self.body, bg=BORDER, height=1)
        sep.pack(fill='x', pady=10)

        # ---- 删/留 两栏 ----
        self.cols = tk.Frame(self.body, bg=CARD)
        self.cols.pack(fill='x')
        self.col_del = tk.Frame(self.cols, bg=CARD)
        self.col_del.pack(side='left', fill='both', expand=True, padx=(0, 10))
        self.col_keep = tk.Frame(self.cols, bg=CARD)
        self.col_keep.pack(side='left', fill='both', expand=True)
        self._render_lists()

        tk.Frame(self.body, bg=CARD, height=6).pack()

        self.chk_keep = CheckRow(self.body, '保留「扫描输出」与设置（推荐）',
                                 checked=True, command=lambda _: self._render_lists())
        self.chk_keep.frame.pack(anchor='w', pady=2)
        self.chk_drv = CheckRow(self.body, '同时卸载相机驱动（默认不勾；勾选会请求管理员确认）',
                                checked=False, command=lambda _: self._render_lists())
        self.chk_drv.frame.pack(anchor='w', pady=2)

        self.warn = tk.Label(self.body, text='', bg=CARD, fg=WARN, font=FONT_S,
                             anchor='w', justify='left')
        self.warn.pack(fill='x', pady=(8, 0))
        if C.is_app_running():
            self.warn.config(text='注意：AstraForge 正在运行，卸载前会先请它温和退出（等 10 秒，超时才强杀）。')

        self.status = tk.Label(self.body, text='', bg=CARD, fg=ERR, font=FONT_S,
                               anchor='w', justify='left')
        self.status.pack(fill='x', pady=(6, 0))

        # ---- 进度条（.af-bar：5px 高、圆角 4）——执行态才显示 ----
        self.barf = tk.Frame(self.body, bg=CARD)
        self.bar = tk.Canvas(self.barf, height=5, bg=BORDER, highlightthickness=0, bd=0)
        self.bar.pack(fill='x')
        self.step = tk.Label(self.barf, text='', bg=CARD, fg=MUTED, font=FONT_S,
                             anchor='w')
        self.step.pack(fill='x', pady=(4, 0))

        # ---- 按钮行（取消在左，危险红垫底）----
        btns = tk.Frame(self.body, bg=CARD)
        btns.pack(side='bottom', fill='x', pady=(12, 0))
        self.btn_go = _make_rounded_button(btns, '开始卸载', self.start,
                                           kind='danger', w=104, h=32)
        self.btn_go.pack(side='right')
        self.btn_cancel = _make_rounded_button(btns, '取消', self.root.destroy,
                                               kind='normal', w=84, h=32)
        self.btn_cancel.pack(side='right', padx=(0, 8))
        self.btn_browse = _make_rounded_button(btns, '手动选择目录…', self.browse,
                                               kind='ghost', w=116, h=32)
        self.btn_browse.pack(side='left')

        if not self._target_ok():
            self.btn_go.enabled = False
            self.btn_go.draw(False)
            self.status.config(
                text='未找到安装目录，无法卸载。可点「手动选择目录…」指定 AstraForge 所在文件夹。')

    def _target_ok(self) -> bool:
        return bool(self.target) and Path(self.target).exists()

    def _render_lists(self):
        import tkinter as tk
        for f in (self.col_del, self.col_keep):
            for w in f.winfo_children():
                w.destroy()

        keep_data = self.chk_keep.get() if hasattr(self, 'chk_keep') else True
        rm_drv = self.chk_drv.get() if hasattr(self, 'chk_drv') else False

        del_items = [
            '程序文件（AstraForge.exe · code · _internal）',
            '驱动工具（安装包与向导）',
            '运行日志 logs/（本次会话记录随软件删）',
            '桌面与开始菜单快捷方式',
            '注册表卸载项',
            '本卸载器（退出后自动删除）',
        ]
        if rm_drv:
            del_items.append('相机驱动（Orbbec / Astra 驱动包）')
        keep_items = ['扫描输出/（扫描结果）', 'code/data/（设置与标定）'] if keep_data else []

        def head(parent, title, color, n):
            fr = tk.Frame(parent, bg=CARD)
            fr.pack(fill='x')
            dot = tk.Canvas(fr, width=8, height=8, bg=CARD, highlightthickness=0,
                            bd=0)
            dot.pack(side='left', padx=(0, 6))
            _round_rect(dot, 0, 1, 7, 8, 3, fill=color, outline=color)
            tk.Label(fr, text=f'{title}（{n} 项）', bg=CARD, fg=FG,
                     font=FONT_B).pack(side='left')

        head(self.col_del, '将删除', ERR, len(del_items))
        for t in del_items:
            tk.Label(self.col_del, text='· ' + t, bg=CARD, fg=MUTED, font=FONT_S,
                     anchor='w', justify='left', wraplength=210).pack(fill='x', pady=1)

        head(self.col_keep, '将保留', OK, len(keep_items))
        if keep_items:
            for t in keep_items:
                tk.Label(self.col_keep, text='· ' + t, bg=CARD, fg=MUTED, font=FONT_S,
                         anchor='w', justify='left', wraplength=210).pack(fill='x', pady=1)
        else:
            tk.Label(self.col_keep, text='无（全部删除，含扫描结果与设置）',
                     bg=CARD, fg=ERR, font=FONT_S, anchor='w', wraplength=210,
                     justify='left').pack(fill='x', pady=1)

    # ---- 交互 ----
    @staticmethod
    def _center(win, w, h):
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f'{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}')

    def browse(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title='选择 AstraForge 安装目录')
        if not d:
            return
        if not ((Path(d) / C.APP_EXE).exists() or (Path(d) / 'install.json').exists()):
            self.status.config(text=f'该目录不像 AstraForge 安装目录：{d}', fg=ERR)
            return
        self.target = d
        self.info = _dir_info(d, None)
        self.status.config(text='')
        self._build()

    def _ui(self, fn, *a):
        try:
            self.root.after(0, lambda: fn(*a))
        except Exception:
            pass

    def _set_progress(self, pct, text):
        if self.done:
            return
        self.bar.delete('all')
        w = max(2, int(self.bar.winfo_width() * max(0, min(100, pct)) / 100))
        _round_rect(self.bar, 0, 0, w, 5, 3, fill=ACCENT, outline=ACCENT)
        self.step.config(text=str(text))

    def start(self):
        if self._worker or not self._target_ok():
            return
        self.btn_go.enabled = False
        self.btn_go.draw(False)
        self.btn_cancel.enabled = False
        self.btn_cancel.draw(False)
        self.btn_browse.enabled = False
        self.btn_browse.draw(False)
        self.status.config(text='')
        # 进度条执行态才出现（确认态空挂是病）
        try:
            self.barf.pack(fill='x', pady=(10, 0))
            self.barf.lift()
        except Exception:
            pass
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _run(self):
        try:
            r = do_uninstall(self.target, self.chk_keep.get(),
                             self.chk_drv.get(), self.sb,
                             cb=lambda p, s: self._ui(self._set_progress, p, s))
        except Exception as e:  # noqa: BLE001
            r = {'ok': False, 'msg': f'{type(e).__name__}: {e}'}
        _log(f'gui uninstall → {r.get("ok")} {r.get("msg")} {self.target} '
             f'keep={self.chk_keep.get()} drv={self.chk_drv.get()}')
        self._ui(self._done, r)

    # ---- 完成态 ----
    def _done(self, r: dict):
        import tkinter as tk
        self.done = True
        for w in self.body.winfo_children():
            w.destroy()

        ok = bool(r.get('ok'))
        head = tk.Frame(self.body, bg=CARD)
        head.pack(fill='x')
        tk.Label(head, text='✓' if ok else '✗', bg=CARD, fg=OK if ok else ERR,
                 font=FONT_T).pack(side='left', padx=(0, 8))
        tk.Label(head, text='卸载完成' if ok else '卸载失败',
                 bg=CARD, fg=FG, font=FONT_T).pack(side='left')

        sep = tk.Frame(self.body, bg=BORDER, height=1)
        sep.pack(fill='x', pady=10)

        if ok:
            kept = r.get('kept') or []
            lines = ['已删除：程序文件、驱动工具、运行日志、快捷方式、注册信息。']
            if self.chk_drv.get():
                d = r.get('driver') or {}
                lines.append('驱动：' + str(d.get('msg') or '已处理'))
            else:
                lines.append('驱动：相机驱动仍保留在系统中，可在「设备管理器」里移除。')
            if kept:
                lines.append('已保留：' + '、'.join(kept) + '。')
                lines.append(f'数据位置：{Path(self.target) / "扫描输出"}')
            else:
                lines.append('已保留：无（按你的选择全部删除）。')
            for t in lines:
                tk.Label(self.body, text=t, bg=CARD, fg=MUTED, font=FONT,
                         anchor='w', justify='left', wraplength=440).pack(fill='x', pady=2)
        else:
            tk.Label(self.body, text='原因：' + str(r.get('msg') or '未知'),
                     bg=CARD, fg=ERR, font=FONT, anchor='w', justify='left',
                     wraplength=440).pack(fill='x', pady=2)

        btns = tk.Frame(self.body, bg=CARD)
        btns.pack(side='bottom', fill='x', pady=(16, 0))
        if ok:
            _make_rounded_button(btns, '关闭', self.root.destroy,
                                 kind='primary', w=96, h=32).pack(side='right')
        else:
            def retry():
                self.done = False
                self._worker = None
                self._build()
            _make_rounded_button(btns, '重试', retry, kind='danger',
                                 w=96, h=32).pack(side='right')
            _make_rounded_button(btns, '关闭', self.root.destroy, kind='normal',
                                 w=84, h=32).pack(side='right', padx=(0, 8))


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
    ap.add_argument('--dir', default='', help='安装目录（留空=自举/注册表）')
    ap.add_argument('--test-root', default='', help='沙箱测试根目录')
    ap.add_argument('--silent', action='store_true', help='静默卸载')
    ap.add_argument('--version', default=APP_VERSION)
    args = ap.parse_args()
    sb = C.Sandbox(Path(args.test_root) if args.test_root else None)
    target, info = resolve_target(args, sb)

    if args.silent:
        r = do_uninstall(target, keep_data=True, remove_driver=False, sb=sb)
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
