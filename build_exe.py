# -*- coding: utf-8 -*-
"""build_exe.py — PyInstaller 打包 AstraForge.exe（win64, 无控制台, onedir）

要点：
- 只打包 launcher.py（含依赖收集 import）→ exe 自带 Python 与第三方依赖
- 程序代码（core/modules/ui/main.py）**不打包**，作为外置 code/ 目录分发
  ——这是 OTA 热更新（替换 code/）的前提
- 产物：发行/AstraForge/{AstraForge.exe, _internal/, code/, 使用说明.md}

用托管 venv 的 python 运行本脚本（依赖装在 venv 里）。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

VENV_PY = sys.executable
# 注：托管 Python 3.13 不含 tkinter（无 Tcl/Tk 组件），故打包环境用系统 3.14
#     （项目全部依赖 numpy/PIL/cv2/pyusb/astra_raw 都在 3.14 上）
SRC = str(Path(__file__).resolve().parent)
DIST = str(Path(__file__).resolve().parents[1] / '发行')
BUILD = os.path.join(DIST, '_build')
SPEC = os.path.join(DIST, '_spec')
ICON = os.path.join(SRC, 'assets/icon.ico')
APP_OUT = os.path.join(DIST, 'AstraForge')


def run(cmd, **kw):
    print('$', ' '.join(cmd) if isinstance(cmd, list) else cmd, flush=True)
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        sys.exit(f'命令失败: {r.returncode}')


def main():
    os.makedirs(DIST, exist_ok=True)
    # 0. 图标
    if not os.path.exists(ICON):
        run([VENV_PY, os.path.join(SRC, 'tests/make_icon.py')])

    # 1. PyInstaller 打包引导器
    cmd = [VENV_PY, '-m', 'PyInstaller', '--noconfirm', '--clean',
           '--windowed', '--onedir', '--name', 'AstraForge',
           '--distpath', DIST, '--workpath', BUILD, '--specpath', SPEC,
           '--collect-all', 'libusb_package',      # 含 libusb DLL（data 文件）
           '--hidden-import', 'astra_raw', '--hidden-import', 'astra_raw.transport']
    if os.path.exists(ICON):
        cmd += ['--icon', ICON]
    cmd.append(os.path.join(SRC, 'launcher.py'))
    run(cmd, cwd=SRC)

    # 2. 组装外置 code/（可 OTA 替换的程序代码）
    code = os.path.join(APP_OUT, 'code')
    if os.path.exists(code):
        try:
            shutil.rmtree(code)
        except Exception as e:
            # 运行中的软件以 code/ 为工作目录时删不掉——容错：改为覆盖式同步
            print(f'[warn] code/ 清理不完整（可能被运行中的软件占用）: {str(e)[:120]}')

    # 排除规则：**顶层按名字精确匹配**（ignore_patterns 不分层级，
    # 曾把 ui-web/dist/assets 误伤 → 页面 JS 404 白屏）
    _EXCL_TOP = {'tests', 'data', 'assets', 'launcher.py', '启动.bat', '_tmp',
                 'build_exe.py', '_selftest.json', '_front_report.json',
                 'shell_error.log', 'launcher_error.log', 'UI草稿', '.backup'}

    def _ignore(dirpath, names):
        rel = os.path.relpath(dirpath, SRC).replace('\\', '/')
        out = []
        for n in names:
            if rel == '.' and n in _EXCL_TOP:
                out.append(n); continue
            if n in ('node_modules', '__pycache__'):
                out.append(n); continue
            if n.endswith(('.pyc', '.spec', '.bat')):
                out.append(n); continue
            if n.startswith('.new_'):
                out.append(n); continue
        return out

    shutil.copytree(SRC, code, ignore=_ignore, dirs_exist_ok=True)

    # 3. 说明书
    for f in ('使用说明.md',):
        shutil.copy2(os.path.join(SRC, f), os.path.join(APP_OUT, f))

    # 4. 体检
    need = ['AstraForge.exe', '_internal', 'code/shell.py',
            'code/core/pipeline.py', 'code/modules/device/module.py',
            'code/modules/updater/module.py', 'code/ui-web/dist/index.html']
    missing = [n for n in need if not os.path.exists(os.path.join(APP_OUT, n))]
    if missing:
        sys.exit(f'组装缺件: {missing}')
    print('\n===== 打包完成 =====')
    print('产物: ' + APP_OUT)
    for n in sorted(os.listdir(APP_OUT)):
        print('  ', n)


if __name__ == '__main__':
    main()
