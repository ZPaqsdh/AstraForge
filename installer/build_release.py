# -*- coding: utf-8 -*-
"""build_release.py — 打「单文件安装器」发布包

产物（<项目根>/发行/安装器/AstraForge-Setup-v<版本>/）：
    AstraForge-Setup-Online-v<版本>.exe     在线下载器（单文件，安装时拉最新载荷）
    AstraForge-Setup-Offline-v<版本>.exe    离线完整包（单文件，自带本版本载荷）
    AstraForge-<版本>-payload.zip           在线安装用的载荷（上传到 GitHub Release，用户无需下载）
    update.json                             版本清单（上传到 Release，供在线安装器读取）
    安装器说明.md                            本地说明（不随 exe 分发）

设计：
- 两个安装器都是 **PyInstaller onefile**：exe 内自带安装器运行时 + HTML UI + 驱动库；
  离线包额外内嵌 payload.zip。
- 卸载器单独打一个轻量 onefile（tkinter，约 20MB），装进 payload，安装后落在安装目录根。
- 不再有 `_setup_internal/`、外置 `payload.zip` 等挂载文件。

用法：
    python installer/build_release.py [版本号] [--only online|offline|uninstall]
"""
import hashlib
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
_args = sys.argv[1:]
VERSION = _args[0] if (_args and not _args[0].startswith('--')) else '0.3.0'
ONLY = _args[_args.index('--only') + 1] if '--only' in _args else ''
TS = time.strftime('%Y%m%d-%H%M%S')

OUT = OUT_ROOT / f'AstraForge-Setup-v{VERSION}'
if OUT.exists() and not ONLY:
    OUT = OUT_ROOT / f'AstraForge-Setup-v{VERSION}-{TS}'
WORK = OUT_ROOT / f'_build-{TS}'
DRIVER_PACK = INST / 'driver' / 'pack'
PAYLOAD_ITEMS = ['AstraForge.exe', '_internal', 'code', '使用说明.md', 'README.md']
ICON = SRC / 'assets' / 'icon.ico'


def run(cmd, **kw):
    print('$', ' '.join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], **kw)
    if r.returncode != 0:
        raise SystemExit(f'命令失败 rc={r.returncode}')


def step(msg):
    print(f'\n=== {msg} ({time.strftime("%H:%M:%S")})', flush=True)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def build_uninstaller() -> Path:
    step('① 打包轻量卸载器（onefile）')
    dist = WORK / 'dist-uninst'
    cmd = [PY, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
           '--name', 'AstraForge-Uninstall',
           '--distpath', str(dist), '--workpath', str(WORK / 'pyi-uninst'),
           '--specpath', str(WORK / 'spec-uninst')]
    if ICON.exists():
        cmd += ['--icon', str(ICON)]
    cmd.append(str(INST / 'uninstall_main.py'))
    run(cmd, cwd=str(INST))
    exe = dist / 'AstraForge-Uninstall.exe'
    if not exe.exists():
        raise SystemExit(f'卸载器产物缺失：{exe}')
    print(f'   → {exe}（{exe.stat().st_size/1024/1024:.1f} MB）')
    return exe


def stage_payload(uninst_exe: Path) -> Path:
    step('② 组装载荷（软件 + 驱动库 + 卸载器）')
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

    # 驱动库（装完后留在安装目录，可复查/重装驱动）
    if (DRIVER_PACK / 'manifest.json').exists():
        shutil.copytree(DRIVER_PACK, stage / '驱动工具',
                        ignore=shutil.ignore_patterns('__pycache__'))
        print('   + 驱动工具/（manifest + INF/CAT + Zadig）')

    # 轻量卸载器
    shutil.copy2(uninst_exe, stage / 'AstraForge-卸载.exe')
    print(f'   + AstraForge-卸载.exe（{uninst_exe.stat().st_size/1024/1024:.1f} MB）')

    lic = INST / '许可与免责声明.txt'
    if lic.exists():
        shutil.copy2(lic, stage / 'LICENSE-说明.txt')

    step('③ 压缩 payload.zip')
    zp = WORK / 'payload.zip'
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


def build_installer(mode: str, payload: Path | None) -> Path:
    """mode: online / offline。online 不塞载荷；offline 塞 payload.zip。"""
    step(f'④ 打包{"在线下载器" if mode == "online" else "离线完整包"}（onefile）')
    name = 'AstraForge-Setup-Online' if mode == 'online' else 'AstraForge-Setup-Offline'
    dist = WORK / f'dist-{mode}'
    cmd = [PY, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
           '--name', name,
           '--distpath', str(dist), '--workpath', str(WORK / f'pyi-{mode}'),
           '--specpath', str(WORK / f'spec-{mode}'),
           '--add-data', f'{INST / "ui"}{os.pathsep}ui',
           '--add-data', f'{DRIVER_PACK}{os.pathsep}driver_pack',
           '--collect-all', 'PySide6']
    if ICON.exists():
        cmd += ['--icon', str(ICON)]
    if mode == 'offline':
        if not payload or not payload.exists():
            raise SystemExit('离线包缺少 payload.zip')
        cmd += ['--add-data', f'{payload}{os.pathsep}.']
    cmd.append(str(INST / 'setup_main.py'))
    run(cmd, cwd=str(INST))
    exe = dist / f'{name}.exe'
    if not exe.exists():
        raise SystemExit(f'安装器产物缺失：{exe}')
    print(f'   → {exe}（{exe.stat().st_size/1024/1024:.0f} MB）')
    return exe


def write_meta(payload: Path):
    step('⑤ 写 update.json / 说明')
    digest = sha256(payload)
    upd = OUT / 'update.json'
    upd.write_text(f"""{{
  "app": "AstraForge",
  "latest": "{VERSION}",
  "min_installer": "{VERSION}",
  "payload_url": "https://github.com/ZPaqsdh/AstraForge/releases/download/v{VERSION}/AstraForge-{VERSION}-payload.zip",
  "payload_sha256": "{digest}",
  "notes_url": "https://github.com/ZPaqsdh/AstraForge/releases/tag/v{VERSION}"
}}
""", encoding='utf-8')
    (OUT / '安装器说明.md').write_text(f"""# AstraForge 星铸 · 安装器 v{VERSION}

本目录是构建产物（上传 GitHub Release 用）：

| 文件 | 用途 |
|---|---|
| `AstraForge-Setup-Online-v{VERSION}.exe` | **在线下载器**（主推）：单文件，安装时联网拉最新载荷 |
| `AstraForge-Setup-Offline-v{VERSION}.exe` | **离线完整包**：单文件，自带本版本载荷 |
| `AstraForge-{VERSION}-payload.zip` | 在线安装用的载荷资产（用户不需要手动下载） |
| `update.json` | 版本清单（已填实际仓库 URL；上传到 Release） |

## 上传顺序（GitHub Release）

1. 新建 tag `v{VERSION}` 的 Release；
2. 上传 `AstraForge-{VERSION}-payload.zip` 与两个安装器 exe；
3. 上传 `update.json`（在线安装器读 `releases/latest/download/update.json`，恒定入口）；
4. `DEFAULT_UPDATE_URL` 已内置实际仓库地址，无需再改。

## 用户下载哪个？

- 正常用户：`AstraForge-Setup-Online-v{VERSION}.exe`（几百 MB，联网安装最新版）
- 没网/内网：`AstraForge-Setup-Offline-v{VERSION}.exe`（约 1 GB，自带完整载荷）

生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}
载荷 SHA-256：`{digest}`
""", encoding='utf-8')
    print(f'   → {upd}')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)

    uninst = build_uninstaller()
    payload = stage_payload(uninst)

    built = []
    if ONLY in ('', 'offline'):
        exe = build_installer('offline', payload)
        dst = OUT / f'AstraForge-Setup-Offline-v{VERSION}.exe'
        shutil.copy2(exe, dst)
        built.append(dst)
    if ONLY in ('', 'online'):
        exe = build_installer('online', None)
        dst = OUT / f'AstraForge-Setup-Online-v{VERSION}.exe'
        shutil.copy2(exe, dst)
        built.append(dst)

    # payload 资产（online 安装器需要）
    pz = OUT / f'AstraForge-{VERSION}-payload.zip'
    shutil.copy2(payload, pz)
    write_meta(pz)

    print('\n✅ 产物目录：', OUT)
    for p in sorted(OUT.iterdir()):
        if p.is_file():
            print(f'   {p.name:<48} {p.stat().st_size/1024/1024:8.1f} MB  '
                  f'sha256={sha256(p)[:16]}…')


if __name__ == '__main__':
    main()
