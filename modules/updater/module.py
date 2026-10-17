# -*- coding: utf-8 -*-
"""updater 模块 — GitHub OTA 无感热更新（检查/下载/校验/替换/回滚/重启）。

更新源（settings["update_source"]，未配置时 OTA 静默关闭）：
    GitHub 仓库根 raw URL，例：https://raw.githubusercontent.com/<user>/<repo>/main
远端根目录放 manifest.json（与本地同构 + 每模块 url/sha256）：
    {"app": "AstraForge", "version": "0.2.0",
     "modules": {"fusion": {"version": "1.1.0", "url": "...zip", "sha256": "..."}, ...}}

安全链：下载 → SHA256 → 解压预检（module.json 名/结构）→ 备份 → 原子替换 →
失败自动回滚；网络失败静默。Python 不能进程内重载模块——更新后需重启生效。
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from core.contracts import ModuleContext


class UpdaterModule:
    name = "updater"
    version = "1.0.0"

    def __init__(self):
        self.ctx = None
        self._timeout = 5.0

    def setup(self, ctx: ModuleContext):
        self.ctx = ctx
        src = (ctx.settings.get("update_source") or "").strip()
        ctx.log(f"[updater] 就绪 v{self.version}" +
                (f"（源: {src[:48]}…）" if len(src) > 48 else
                 (f"（源: {src}）" if src else "（未配置更新源，OTA 待启用）")), True)

    def start(self):
        pass

    def stop(self):
        pass

    # ---------- 网络 ----------
    def _get(self, url: str, timeout=None):
        req = urllib.request.Request(url, headers={
            "User-Agent": "AstraForge-Updater/1.0"})
        with urllib.request.urlopen(req, timeout=timeout or self._timeout) as r:
            return r.read()

    def remote_manifest(self):
        src = (self.ctx.settings.get("update_source") or "").strip().rstrip("/")
        if not src:
            return None, "未配置更新源"
        try:
            raw = self._get(src + "/manifest.json")
            return json.loads(raw.decode("utf-8")), None
        except Exception as e:
            return None, f"拉取失败: {str(e)[:60]}"

    @staticmethod
    def _ver_tuple(v):
        try:
            return tuple(int(x) for x in str(v).split("."))
        except Exception:
            return (0,)

    def _ver_gt(self, a, b):
        return self._ver_tuple(a) > self._ver_tuple(b)

    # ---------- 检查 ----------
    def check(self):
        """→ {"updates": {name: {local, remote, url, sha256}}, "error": str|None}

        本地版本从磁盘 module.json 现读（反映替换后的真实状态）。
        """
        rm, err = self.remote_manifest()
        if rm is None:
            return {"updates": {}, "error": err}
        rmods = rm.get("modules", {})
        out = {}
        mdir = self.ctx.root_dir / "modules"
        for d in sorted(mdir.iterdir()):
            mj = d / "module.json"
            if not d.is_dir() or d.name.startswith(".") or not mj.exists():
                continue
            try:
                lm = json.loads(mj.read_text(encoding="utf-8"))
            except Exception:
                continue
            name, lv = lm.get("name"), lm.get("version", "0")
            r = rmods.get(name)
            if r and self._ver_gt(r.get("version", "0"), lv):
                out[name] = {"local": lv, "remote": r.get("version"),
                             "url": r.get("url", ""), "sha256": r.get("sha256", "")}
        return {"updates": out, "error": None}

    # ---------- 更新（下载→校验→备份→替换，失败回滚） ----------
    def update(self, name):
        chk = self.check()
        info = chk["updates"].get(name)
        if not info:
            return False, f"{name}: 无可用更新" + (f"（{chk['error']}）" if chk["error"] else "")
        url = info.get("url") or ""
        if not url:
            return False, f"{name}: 远端清单缺 url"
        mod_dir = self.ctx.root_dir / "modules" / name
        tmp_zip = Path(tempfile.gettempdir()) / f"af_{name}_{int(time.time())}.zip"
        try:
            tmp_zip.write_bytes(self._get(url, timeout=30))
        except Exception as e:
            return False, f"下载失败: {str(e)[:60]}"
        # SHA256 校验
        want = (info.get("sha256") or "").strip().lower()
        if want:
            got = hashlib.sha256(tmp_zip.read_bytes()).hexdigest()
            if got != want:
                tmp_zip.unlink(missing_ok=True)
                return False, (f"SHA256 校验失败（期望 {want[:12]}… "
                               f"实际 {got[:12]}…）——已拒绝安装")
        # 解压预检
        stage = self.ctx.root_dir / "modules" / f".new_{name}"
        shutil.rmtree(stage, ignore_errors=True)
        try:
            with zipfile.ZipFile(tmp_zip) as z:
                z.extractall(stage)
            if not (stage / "module.json").exists():     # 兼容 zip 内嵌一层目录
                subs = [p for p in stage.iterdir() if p.is_dir()]
                if len(subs) == 1 and (subs[0] / "module.json").exists():
                    inner = subs[0]
                    for item in list(inner.iterdir()):
                        shutil.move(str(item), str(stage / item.name))
                    inner.rmdir()
            if not (stage / "module.json").exists():
                raise ValueError("包内缺少 module.json")
            nm = json.loads((stage / "module.json").read_text(encoding="utf-8"))
            if nm.get("name") != name:
                raise ValueError(f"包内模块名不符: {nm.get('name')!r} != {name!r}")
        except Exception as e:
            shutil.rmtree(stage, ignore_errors=True)
            tmp_zip.unlink(missing_ok=True)
            return False, f"包预检失败: {str(e)[:60]}"
        # 备份 → 原子替换
        backup_root = self.ctx.root_dir / "modules" / ".backup"
        backup_root.mkdir(exist_ok=True)
        bak = backup_root / f"{name}-{int(time.time())}"
        moved = False
        try:
            if mod_dir.exists():
                shutil.copytree(mod_dir, bak)
            shutil.rmtree(mod_dir, ignore_errors=True)
            shutil.move(str(stage), str(mod_dir))
            moved = True
        except Exception as e:
            if not moved and bak.exists() and not mod_dir.exists():   # 回滚
                try:
                    shutil.copytree(bak, mod_dir)
                except Exception:
                    pass
            return False, f"替换失败（已尝试回滚）: {str(e)[:60]}"
        finally:
            tmp_zip.unlink(missing_ok=True)
        self.ctx.log(f"[updater] {name} 已更新 {info['local']} → {info['remote']}"
                     f"（重启生效）", True)
        return True, f"{name} 更新成功（{info['local']} → {info['remote']}，重启生效）"

    def update_all(self):
        res = []
        chk = self.check()
        for name in list(chk["updates"].keys()):
            res.append(self.update(name))
        return res

    def restart_app(self):
        """重启进程（更新生效）。"""
        try:
            main_py = self.ctx.root_dir / "main.py"
            os.execv(sys.executable, [sys.executable, str(main_py)])
        except Exception as e:
            self.ctx.log(f"[updater] 自动重启失败，请手动重启: {e}", False)

    # ---------- UI 对话框 ----------
    def open_dialog(self, master):
        import tkinter as tk
        from core.theme import BG, FG, ACCENT, OK, WARN, ERR, BTN, BTN_HOVER

        win = tk.Toplevel(master)
        win.title("检查更新（GitHub OTA）")
        win.configure(bg=BG)
        win.geometry("480x360")

        src = (self.ctx.settings.get("update_source") or "").strip()
        lb_src = tk.Label(win, text=("更新源: " + (src if src else "未配置（settings.update_source）")),
                          fg="#9aa0b0", bg=BG, font=("Consolas", 9), anchor="w",
                          wraplength=450, justify="left")
        lb_src.pack(fill="x", padx=12, pady=(10, 4))

        lb_stat = tk.Label(win, text="点“检查更新”开始", fg=FG, bg=BG,
                           font=("Microsoft YaHei", 10), anchor="w", justify="left")
        lb_stat.pack(fill="x", padx=12)

        lf = tk.Frame(win, bg=BG)
        lf.pack(fill="both", expand=True, padx=12, pady=6)

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", pady=8)

        state = {"updates": {}}

        def render():
            for w in lf.winfo_children():
                w.destroy()
            if not state["updates"]:
                tk.Label(lf, text="（无可用更新）", fg="#9aa0b0", bg=BG,
                         font=("Microsoft YaHei", 9)).pack(anchor="w")
                return
            for name, info in state["updates"].items():
                row = tk.Frame(lf, bg=BG)
                row.pack(fill="x", pady=2)
                tk.Label(row, text=f"{name}:  {info['local']} → {info['remote']}",
                         fg=OK, bg=BG, font=("Consolas", 10), width=30,
                         anchor="w").pack(side="left")
                def do_update(n=name):
                    def run():
                        ok, msg = self.update(n)
                        win.after(0, lambda: lb_stat.config(
                            text=msg, fg=OK if ok else ERR))
                        if ok:
                            chk2 = self.check()
                            state["updates"] = chk2["updates"]
                            win.after(0, render)
                    threading.Thread(target=run, daemon=True).start()
                tk.Button(row, text="更新", command=do_update, bg=BTN, fg=FG,
                          relief="flat", bd=0, padx=8, cursor="hand2",
                          font=("Microsoft YaHei", 9)).pack(side="left", padx=4)

        def do_check():
            lb_stat.config(text="检查中…", fg=FG)
            def run():
                chk = self.check()
                state["updates"] = chk["updates"]
                txt = (f"发现 {len(chk['updates'])} 个模块可更新" if chk["updates"]
                       else ("已是最新" if not chk["error"] else f"检查失败: {chk['error']}"))
                fg = OK if chk["updates"] else (WARN if chk["error"] else "#9aa0b0")
                win.after(0, lambda: lb_stat.config(text=txt, fg=fg))
                win.after(0, render)
            threading.Thread(target=run, daemon=True).start()

        def do_all():
            def run():
                res = self.update_all()
                n_ok = sum(1 for ok, _ in res if ok)
                win.after(0, lambda: lb_stat.config(
                    text=f"批量更新完成: {n_ok}/{len(res)} 成功（重启生效）",
                    fg=OK if n_ok else WARN))
                win.after(0, render)
            threading.Thread(target=run, daemon=True).start()

        def do_restart():
            self.restart_app()

        for txt, cmd, fg2 in (("检查更新", do_check, FG), ("全部更新", do_all, OK),
                              ("重启生效", do_restart, ACCENT),
                              ("关闭", win.destroy, FG)):
            tk.Button(btns, text=txt, command=cmd, bg=BTN, fg=fg2,
                      activebackground=BTN_HOVER, activeforeground="white",
                      relief="flat", bd=0, padx=10, pady=3, cursor="hand2",
                      font=("Microsoft YaHei", 9)).pack(side="left", padx=6)
