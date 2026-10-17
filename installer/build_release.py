# -*- coding: utf-8 -*-
"""build_release.py — 打「安装包」发布包（摊平结构）

产物（默认到 <项目根>/发行/安装器/AstraForge-Setup-v<版本>/）：
    AstraForge-安装.exe     安装向导入口（必须与运行时目录同级——PyInstaller onedir 硬性要求）
    _setup_internal/        安装器自带运行时（含 QtWebEngine；--contents-directory 定制名）
    payload.zip             待安装的应用整包（= 发行版内容 + 卸载器 AstraForge-卸载.exe + 其运行时）
    安装器说明.md

设计（2026-10-17 修）：
- 发布包**摊平**：入口 exe 与它的运行时同层，双击即用。
  （此前是嵌套 `AstraForge-Setup/` + 包根一个 exe 副本 → 双击报
  "Failed to load Python DLL ... _internal ..."——副本找不到同级运行时。）
- 安装完成后的安装目录 =
  启动器（AstraForge.exe）+ 应用本体（_internal/ code/ …）
  + 卸载器（AstraForge-卸载.exe）+ 卸载器运行时（_setup_internal/）。
- 卸载器运行时目录名用 --contents-directory 定制为 _setup_internal，
  避免与应用自己的 _internal 在安装目录根撞名。

用法：python installer/build_release.py [版本号]
"""
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

PY = sys.executable
WS = Path(__file__).resolve().parents[2]
SRC = WS / 'AstraForge'
INST = SRC / 'installer'
RELEASE_APP = WS / '发行' / 'AstraForge'
OUT_ROOT = WS / '发行' / '安装器'
VERSION = sys.argv[1] if len(sys.argv) > 1 else '0.2.10'
TS = time.strftime('%H%M%S')
SETUP_CONTENTS = '_setup_internal'     # 安装器/卸载器运行时目录名（与 build 命令一致）
# 本机护栏会拦"批量删除旧产物"→ 覆盖式重建不可行：产物目录与构建目录都带时间戳
OUT = OUT_ROOT / (f'AstraForge-Setup-v{VERSION}' if not (OUT_ROOT / f'AstraForge-Setup-v{VERSION}').exists()
                  else f'AstraForge-Setup-v{VERSION}-b{TS}')
WORK = OUT_ROOT / f'_build-{TS}'
DIST = WORK / 'dist'

PAYLOAD_ITEMS = ['AstraForge.exe', '_internal', 'code', '使用说明.md', 'README.md']


def run(cmd, **kw):
    print('$', ' '.join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], **kw)
    if r.returncode != 0:
        raise SystemExit(f'命令失败 rc={r.returncode}')


def step(msg):
    print(f'\n=== {msg} ({time.strftime("%H:%M:%S")})', flush=True)


def build_setup_exe():
    step('① PyInstaller 打包安装器')
    icon = SRC / 'assets' / 'icon.ico'
    cmd = [PY, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir',
           '--name', 'AstraForge-Setup',
           '--contents-directory', SETUP_CONTENTS,
           '--distpath', str(DIST), '--workpath', str(WORK / 'pyi'),
           '--specpath', str(WORK),
           '--add-data', f'{INST / "ui"}{os.pathsep}ui',
           '--collect-all', 'PySide6',
           ]
    if icon.exists():
        cmd += ['--icon', str(icon)]
    cmd.append(str(INST / 'setup_main.py'))
    run(cmd, cwd=str(INST))
    built = DIST / 'AstraForge-Setup'
    if not (built / 'AstraForge-Setup.exe').exists() or not (built / SETUP_CONTENTS).exists():
        raise SystemExit(f'打包产物缺失：{built}')
    return built


def stage_payload(setup_dir: Path):
    step('② 组装载荷（发行版 + 卸载器）')
    stage = WORK / 'payload'
    stage.mkdir(parents=True, exist_ok=True)
    for it in PAYLOAD_ITEMS:
        s = RELEASE_APP / it
        if not s.exists():
            print(f'   [warn] 缺 {s}，跳过')
            continue
        d = stage / it
        if s.is_dir():
            shutil.copytree(s, d, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            shutil.copy2(s, d)
        print(f'   + {it}')

    # 驱动工具也放进安装目录（装完后可随时再跑；约 5MB）
    if (INST / 'driver').is_dir():
        shutil.copytree(INST / 'driver', stage / '驱动工具',
                        ignore=shutil.ignore_patterns('__pycache__'))
        print('   + 驱动工具/（Zadig + 说明）')

    # 卸载器：与安装在根的应用并列 —— exe（改名副本）+ 运行时目录，都落在安装目录根
    exe_src = setup_dir / 'AstraForge-Setup.exe'
    rt_src = setup_dir / SETUP_CONTENTS
    if exe_src.exists() and rt_src.exists():
        shutil.copy2(exe_src, stage / 'AstraForge-卸载.exe')
        shutil.copytree(rt_src, stage / SETUP_CONTENTS,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        print(f'   + AstraForge-卸载.exe + {SETUP_CONTENTS}/（卸载器，安装目录根可见）')
    else:
        print('   [warn] 安装器产物不齐，卸载器未进载荷')
    lic = INST / '许可与免责声明.txt'
    if lic.exists():
        shutil.copy2(lic, stage / 'LICENSE-说明.txt')

    step('③ 压缩 payload.zip')
    zp = OUT / 'payload.zip'
    zp.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, dirs, files in os.walk(stage):
            for f in files:
                p = Path(root) / f
                z.write(p, p.relative_to(stage).as_posix())
                n += 1
                if n % 200 == 0:
                    print(f'   …{n} 个文件', flush=True)
    print(f'   payload.zip：{zp.stat().st_size/1024/1024:.0f} MB（{n} 个文件）')
    return zp


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    setup_dir = build_setup_exe()

    # 发布包摊平：入口 exe（改名副本）与运行时目录同层 —— 双击直接可用
    shutil.copy2(setup_dir / 'AstraForge-Setup.exe', OUT / 'AstraForge-安装.exe')
    shutil.copytree(setup_dir / SETUP_CONTENTS, OUT / SETUP_CONTENTS,
                    ignore=shutil.ignore_patterns('__pycache__'))
    print(f'   → {OUT / "AstraForge-安装.exe"} + {SETUP_CONTENTS}/')

    # 驱动工具随包（安装器根 驱动工具/ —— 安装前「驱动处理向导」直接调用）
    if (INST / 'driver').is_dir():
        shutil.copytree(INST / 'driver', OUT / '驱动工具',
                        ignore=shutil.ignore_patterns('__pycache__'))
        print(f'   → {OUT / "驱动工具"}/（Zadig + 说明）')

    stage_payload(setup_dir)

    (OUT / '安装器说明.md').write_text(f"""# AstraForge 星铸 · 安装包 v{VERSION}

## 怎么装（把本目录整个拷到目标机器）

1. `AstraForge-安装.exe`、`{SETUP_CONTENTS}/`、`payload.zip` 三个必须放在一起（同目录）；
2. 双击 **`AstraForge-安装.exe`** → 选安装位置（默认 `%LOCALAPPDATA%\\Programs\\AstraForge`，免管理员）
   → 勾选组件 → 立即安装。

## 装完之后（安装目录里有什么）

- **启动器**：`AstraForge.exe`（桌面 / 开始菜单也有「AstraForge 星铸」快捷方式）
- **卸载器**：`AstraForge-卸载.exe`（在安装目录根，双击即进卸载界面）；等价入口还有：
  - 开始菜单 →「卸载 AstraForge 星铸」
  - Windows 设置 → 应用 →「AstraForge 星铸」
  - 控制面板 → 程序和功能
- `install.json`：本次安装的版本 / 时间 / 选项。
- `驱动工具\\`：Zadig（安装器「驱动处理向导」使用；来源与校验见其中 README）。

卸载默认保留 `扫描输出` 与设置 `data`（任务数据不丢）。

## 静默安装/卸载（脚本部署用）

```
AstraForge-安装.exe --silent  --dir "D:\\Apps\\AstraForge"
AstraForge-卸载.exe --uninstall --silent
```

生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}
""", encoding='utf-8')

    print(f'\n✅ 发布目录：{OUT}')
    for p in sorted(OUT.rglob('*')):
        if p.is_file() and p.parent == OUT:
            print(f'   {p.name:28s} {p.stat().st_size/1024/1024:8.1f} MB')
    print(f'   {SETUP_CONTENTS}/  (运行时目录)')


if __name__ == '__main__':
    main()
