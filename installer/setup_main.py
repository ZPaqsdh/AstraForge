# -*- coding: utf-8 -*-
"""AstraForge 星铸 · 安装器/卸载器外壳（PySide6 + QtWebEngine + QWebChannel 桥）

一个可执行文件，两种身份：
    AstraForge-安装.exe                 → 安装向导（UI草稿 v3 七个页面）
    AstraForge-卸载.exe --uninstall     → 卸载器（UI草稿 v1 四个状态）
    （注册表里写的就是后者，所以「应用和功能」里点卸载即可）

调试：
    --test-root <dir>   沙箱（注册表/快捷方式/数据都落到测试位置，不污染系统）
    --snap <png>        窗口显示若干秒后截图并退出（自检用，与应用同一套做法）
    --silent            静默模式（配合 --uninstall 用于静默卸载）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

APP_VERSION = '0.3.3'
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import setup_core as C          # noqa: E402

from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot          # noqa: E402
from PySide6.QtWebChannel import QWebChannel                        # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView               # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

ARGS = None
SB = None


def _log(msg: str):
    try:
        p = Path(os.environ.get('TEMP', '.')) / 'AstraForge-setup.log'
        with p.open('a', encoding='utf-8') as f:
            f.write(f'[{time.strftime("%H:%M:%S")}] {msg}\n')
    except Exception:
        pass


# ------------------------------------------------------------------ 桥
class Bridge(QObject):
    """JS ↔ Python。返回 JSON 字符串（QtWebChannel 用回调接收）。"""

    progress = Signal(int, str)
    finished = Signal(bool, str, str)
    cams = Signal(str)
    updateReady = Signal(str)
    driverDone = Signal(str)

    def __init__(self, view: QWebEngineView):
        super().__init__()
        self.view = view
        self.worker: threading.Thread | None = None
        self.cancel_flag = threading.Event()
        self.drag_origin = None

    # ---- 公共 ----
    def _js(self, code: str):
        self.view.page().runJavaScript(code)

    def _emit_progress(self, pct: int, stage: str):
        self.progress.emit(int(pct), str(stage))

    @Slot(result=str)
    def bootstrap(self) -> str:
        env = C.env_report()
        installed = C.find_installed(SB)
        d = (installed or {}).get('dir') or C.default_dir()
        rel = None
        if installed:
            if installed.get('residual'):
                rel = 'residual'
            else:
                c = C.cmp_version(installed.get('version', ''), ARGS.version)
                rel = 'same' if c == 0 else ('new' if c > 0 else 'old')
        payload = C._payload_path()
        need = 0
        try:
            import zipfile
            if payload:
                need = sum(z.file_size for z in zipfile.ZipFile(payload).infolist()) // 1024
        except Exception:
            pass
        return json.dumps({
            'mode': ARGS.mode,
            'version': ARGS.version,
            'env': env,
            'installed': installed,
            'relation': rel,
            'running': C.is_app_running(),
            'default_dir': d,
            'app_dir': C.APP_NAME,
            'payload_kb': need,
            'has_payload': payload is not None,
            'online_only': payload is None,
            'update_configured': bool(C._update_url()),
            'free_gb': C._disk_free_gb(d[:3] if len(d) > 2 else d),
            'drives': C.list_dir(d).get('drives', []),
            'test': bool(SB.on),
        }, ensure_ascii=False)

    @Slot(str, result=str)
    def listDir(self, path: str) -> str:
        return json.dumps(C.list_dir(path), ensure_ascii=False)

    @Slot(str, result=str)
    def mkdir(self, path: str) -> str:
        return json.dumps(C.mkdir(path), ensure_ascii=False)

    @Slot(result=str)
    def checkRunning(self) -> str:
        return json.dumps({'running': C.is_app_running()})

    @Slot()
    def killApp(self):
        C.stop_running()

    @Slot(result=str)
    def cleanResidual(self) -> str:
        return json.dumps(C.clean_residual(SB), ensure_ascii=False)

    @Slot(result=str)
    def openDriverTool(self) -> str:
        """打开随包驱动工具（Zadig，驱动处理向导按钮）。"""
        p = C.driver_tool_path()
        if not p:
            return json.dumps({'ok': False,
                               'msg': '未找到驱动工具（应位于安装包 驱动工具\\zadig.exe）'},
                              ensure_ascii=False)
        try:
            os.startfile(p)          # noqa: S606
            return json.dumps({'ok': True, 'path': p}, ensure_ascii=False)
        except Exception as e:       # noqa: BLE001
            return json.dumps({'ok': False, 'msg': str(e)}, ensure_ascii=False)

    @Slot()
    def detectCams(self):
        """异步枚举相机/驱动（PowerShell 约 2~4 秒）。结果经信号回主线程再送 JS
        —— **不能**在子线程直接 runJavaScript（QtWebEngine 跨线程访问会崩）。"""
        def run():
            try:
                r = C.detect_cameras()
            except Exception as e:            # noqa: BLE001
                r = {'ok': False, 'err': str(e)}
            self.cams.emit(json.dumps(r, ensure_ascii=False))
        threading.Thread(target=run, daemon=True).start()

    @Slot()
    def checkUpdate(self):
        """异步查上游 update.json（3~4 秒超时）。结果经信号回主线程再送 JS。"""
        def run():
            try:
                r = C.fetch_update()
            except Exception as e:            # noqa: BLE001
                r = {'ok': False, 'reason': 'error', 'msg': str(e)}
            if r.get('ok'):
                r['current'] = ARGS.version
                r['newer'] = C.cmp_version(r.get('latest', ''), ARGS.version) > 0
            self.updateReady.emit(json.dumps(r, ensure_ascii=False))
        threading.Thread(target=run, daemon=True).start()

    @Slot(str)
    def installDriver(self, driver_id: str):
        """安装匹配驱动（异步；签名 INF 走 pnputil，非管理员弹 UAC）。"""
        def run():
            try:
                r = C.install_driver(driver_id)
            except Exception as e:            # noqa: BLE001
                r = {'ok': False, 'msg': str(e)}
            self.driverDone.emit(json.dumps(r, ensure_ascii=False))
        threading.Thread(target=run, daemon=True).start()

    # ---- 安装 ----
    @Slot(str)
    def startInstall(self, opts_json: str):
        try:
            opts = json.loads(opts_json)
        except Exception:
            opts = {}
        opts.setdefault('version', ARGS.version)
        if SB.on:
            opts['dir'] = str(SB.root / 'install')      # 沙箱：强制装到测试目录
        self.cancel_flag.clear()

        def run():
            t0 = time.time()
            try:
                r = C.install(opts, cb=self._emit_progress, cancel=self.cancel_flag.is_set, sb=SB)
            except Exception as e:
                r = {'ok': False, 'msg': f'未预期错误：{e}', 'created': []}
            _log(f'install → {r.get("ok")} {r.get("msg")} ({time.time()-t0:.1f}s) {r.get("dir","")}')
            self.finished.emit(bool(r.get('ok')), str(r.get('msg', '')), str(r.get('dir', '')))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    @Slot()
    def cancelInstall(self):
        self.cancel_flag.set()

    # ---- 卸载 ----
    @Slot(bool)
    def startUninstall(self, wipe: bool):
        target = ARGS.dir or (json.loads(self.bootstrap())['installed'] or {}).get('dir') or ''
        if SB.on:
            target = str(SB.root / 'install')
        self.cancel_flag.clear()

        def run():
            try:
                r = C.uninstall(str(target), keep_data=not wipe,
                                cb=self._emit_progress, sb=SB)
            except Exception as e:
                r = {'ok': False, 'msg': f'未预期错误：{e}'}
            _log(f'uninstall → {r.get("ok")} {r.get("msg")} {target}')
            if r.get('ok') and r.get('cleanup_paths'):
                C.schedule_final_cleanup(r['cleanup_paths'])
            self.finished.emit(bool(r.get('ok')), str(r.get('msg', '')), str(target))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    # ---- 其它动作 ----
    @Slot(str)
    def launchApp(self, d: str):
        exe = Path(d) / C.APP_EXE
        if exe.exists():
            try:
                os.startfile(str(exe))          # noqa: S606
            except Exception as e:
                _log(f'launchApp 失败 {e}')

    @Slot(str)
    def openDoc(self, d: str):
        for n in ('使用说明.md', 'README.md'):
            p = Path(d) / n
            if p.exists():
                try:
                    os.startfile(str(p))        # noqa: S606
                except Exception:
                    pass
                return

    @Slot()
    def handoffUninstall(self):
        """移交卸载：启动同目录的卸载器（没有则本 exe 带 --uninstall）。"""
        cand = Path(sys.executable).resolve().parent / C.UNINST_EXE
        exe = cand if cand.exists() else Path(sys.executable)
        try:
            subprocess.Popen([str(exe), '--uninstall'] + (['--test-root', str(SB.root)] if SB.on else []))
        except Exception as e:
            _log(f'handoffUninstall 失败 {e}')

    @Slot()
    def launchRepair(self):
        cand = Path(sys.executable).resolve().parent / 'AstraForge-安装.exe'
        exe = cand if cand.exists() else Path(sys.executable)
        try:
            subprocess.Popen([str(exe)] + (['--test-root', str(SB.root)] if SB.on else []))
        except Exception as e:
            _log(f'launchRepair 失败 {e}')

    # ---- 窗口 ----
    @Slot(int, int)
    def dragStart(self, x: int, y: int):
        w = self.view.window()
        # 优先交给系统级拖动（像原生标题栏一样：跟手、可拖出屏幕、支持贴边）
        try:
            wh = w.windowHandle()
            if wh is not None and wh.startSystemMove():
                self.drag_origin = None
                return
        except Exception:
            pass
        # 回退：手动拖（screenX/Y − 窗口原点）
        self.drag_origin = (x - w.x(), y - w.y())

    @Slot(int, int)
    def dragMove(self, x: int, y: int):
        if not self.drag_origin:
            return
        self.view.window().move(x - self.drag_origin[0], y - self.drag_origin[1])

    @Slot()
    def dragEnd(self):
        self.drag_origin = None

    @Slot()
    def minimizeWindow(self):
        try:
            self.view.window().showMinimized()
        except Exception:
            pass

    @Slot()
    def exitSetup(self):
        QApplication.quit()


# ------------------------------------------------------------------ 主
def main():
    global ARGS, SB
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', default='auto', choices=['auto', 'install', 'uninstall'])
    ap.add_argument('--uninstall', action='store_true', help='以卸载器身份启动')
    ap.add_argument('--dir', default='', help='卸载目标目录（留空=读注册表）')
    ap.add_argument('--version', default=APP_VERSION, help='安装写入的版本号')
    ap.add_argument('--test-root', default='', help='沙箱测试根目录（不污染系统）')
    ap.add_argument('--silent', action='store_true', help='静默模式')
    ap.add_argument('--snap', default='', help='自检：显示 N 秒后截图并退出')
    ap.add_argument('--snap-delay', type=float, default=6.0)
    ap.add_argument('--snap-js', default='', help='自检：截图前 1.5 秒执行一段 JS（UI 验证用）')
    ap.add_argument('--update-url', default='', help='覆盖在线更新源（测试用；也可用 AF_UPDATE_URL）')
    ARGS = ap.parse_args()
    if ARGS.update_url:
        os.environ['AF_UPDATE_URL'] = ARGS.update_url
    SB = C.Sandbox(Path(ARGS.test_root) if ARGS.test_root else None)

    mode = 'uninstall' if (ARGS.uninstall or ARGS.mode == 'uninstall') else 'install'

    # 双击「AstraForge-卸载.exe」（不带任何参数）→ 直接按卸载器走，别弹安装向导
    if mode == 'install' and not ARGS.uninstall and not ARGS.test_root and not ARGS.silent:
        nm = Path(sys.executable).stem
        if '卸载' in nm or nm.lower().endswith('-uninst'):
            mode = 'uninstall'
        else:
            try:
                no_payload = C._payload_path() is None
            except Exception:
                no_payload = True
            if no_payload:
                here = Path(sys.executable).resolve().parent
                if (here / 'install.json').exists() or (here / C.APP_EXE).exists():
                    mode = 'uninstall'

    if ARGS.silent:
        # 静默：无窗口直接执行。**必须**全程兜底——窗口模式（--windowed）没有 stdout，
        # 任何未捕获异常都会变成"双击没反应"，所以这里把异常写进日志文件。
        try:
            if mode == 'uninstall':
                d = ARGS.dir or ((C.find_installed(SB) or {}).get('dir') or '')
                r = C.uninstall(d, keep_data=True, sb=SB)
                if r.get('ok') and r.get('cleanup_paths'):
                    C.schedule_final_cleanup(r['cleanup_paths'])
            else:
                opts = {'dir': ARGS.dir or C.default_dir(), 'desktop': True,
                        'startmenu': True, 'version': ARGS.version}
                if C._payload_path() is None:          # 在线下载器：静默模式也要先取载荷
                    u = C.fetch_update()
                    if u.get('ok') and u.get('payload_url'):
                        opts.update({'payload_url': u['payload_url'],
                                     'payload_sha256': u.get('payload_sha256', ''),
                                     'latest_version': u.get('latest', ''),
                                     'version': u.get('latest') or ARGS.version})
                        r = C.install(opts, sb=SB)
                    else:
                        r = {'ok': False,
                             'msg': '在线安装器：无法获取更新源（' + str(u.get('reason', '未知')) + '）'}
                else:
                    r = C.install(opts, sb=SB)
        except Exception as e:
            import traceback
            _log('silent 异常: ' + traceback.format_exc())
            r = {'ok': False, 'msg': f'{type(e).__name__}: {e}'}
        _log(f'silent {mode} → {r}')
        try:
            sys.stdout.write(json.dumps(r, ensure_ascii=False) + '\n')   # 窗口模式下 stdout 可能为 None
        except Exception:
            pass
        return 0 if r.get('ok') else 1

    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    # QtWebEngine 旗标（与主程序 shell.py 一致）：受限/无 GPU 环境下也能正常渲染
    os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS',
                          '--no-sandbox --no-proxy-server --disable-gpu')
    app = QApplication(sys.argv)
    view = QWebEngineView()
    view.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
    view.setFixedSize(780, 600)
    view.setWindowTitle(f'{C.APP_CN} · ' + ('卸载程序' if mode == 'uninstall' else '安装程序'))

    html = ROOT / 'ui' / ('uninstaller.html' if mode == 'uninstall' else 'installer.html')
    if not html.exists():
        raise SystemExit(f'缺少 UI：{html}（先跑 build_ui.py）')

    bridge = Bridge(view)
    channel = QWebChannel()
    channel.registerObject('bridge', bridge)
    view.page().setWebChannel(channel)

    bridge.progress.connect(lambda p, s: bridge._js(f'__afProgress && __afProgress({p}, {json.dumps(s)})'))
    bridge.finished.connect(lambda ok, msg, d:
                            bridge._js(f'__afDone && __afDone({str(ok).lower()}, {json.dumps(msg)}, {json.dumps(d)})'))
    bridge.cams.connect(lambda s: bridge._js('window.__afCams && window.__afCams(' + json.dumps(s) + ')'))
    bridge.updateReady.connect(lambda s: bridge._js('window.__afUpdate && window.__afUpdate(' + json.dumps(s) + ')'))
    bridge.driverDone.connect(lambda s: bridge._js('window.__afDriverResult && window.__afDriverResult(' + json.dumps(s) + ')'))

    view.load(QUrl.fromLocalFile(str(html)))
    view.show()

    if ARGS.snap:
        import PySide6.QtCore as qc

        def do_snap():
            pix = view.grab()
            okk = pix.save(str(ARGS.snap))
            print(f'[setup] snap {"saved" if okk else "FAILED"}: {ARGS.snap} ({pix.width()}x{pix.height()})')
            QApplication.quit()

        if ARGS.snap_js:
            qc.QTimer.singleShot(max(800, int(ARGS.snap_delay * 1000) - 1500),
                                 lambda: view.page().runJavaScript(ARGS.snap_js))
        qc.QTimer.singleShot(int(ARGS.snap_delay * 1000), do_snap)

    return app.exec()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        _log('启动异常: ' + traceback.format_exc())
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication([])
            QMessageBox.critical(None, 'AstraForge 安装器', '启动失败：\n' + traceback.format_exc()[-800:])
        except Exception:
            pass
        sys.exit(2)
