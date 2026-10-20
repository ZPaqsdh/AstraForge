# -*- coding: utf-8 -*-
"""AstraForge 星铸 · 安装/卸载核心逻辑（纯标准库，GUI 与命令行共用）

设计要点
- **免管理员优先**：默认装到 `%LOCALAPPDATA%\\Programs\\AstraForge`（仅为我安装）；
  用户改到 `C:\\Program Files\\...` 时提示需要管理员（Windows 会自动弹 UAC）。
- **载荷**：安装器同目录的 `payload.zip`（= 发行版 AstraForge/ 整包），解压即装。
- **四项副作用**：桌面快捷方式 / 开始菜单 / 开机自启（可选）/ 卸载注册（HKCU，免管理员）。
- **安全**：只动自己创建的东西；卸载前校验目录确实是 AstraForge（含 AstraForge.exe 或 install.json）。
- **可回滚**：安装失败按"已创建清单"逆序清理。
- **可测试**：`Sandbox` 模式把注册表/快捷方式都改到测试位置，不污染真实系统。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

APP_NAME = 'AstraForge'
APP_CN = 'AstraForge 星铸'
APP_EXE = 'AstraForge.exe'
UNINST_EXE = 'AstraForge-卸载.exe'
SM_UNINST_NAME = f'卸载 {APP_CN}.lnk'      # 开始菜单里的「卸载」入口
PUBLISHER = 'AstraForge 项目'
URL = 'https://github.com/ZPaqsdh/AstraForge'
# 在线更新源（update.json，Release 资产，始终指向 latest）。留空 = 离线模式。
DEFAULT_UPDATE_URL = 'https://github.com/ZPaqsdh/AstraForge/releases/latest/download/update.json'
MIN_CPU = 2
MIN_RAM_GB = 4
MIN_DISK_GB = 3.0            # 程序本体 ~0.9GB，留余量

IS_WIN = sys.platform == 'win32'


# ---------------------------------------------------------------- 沙箱（测试用）
class Sandbox:
    """测试模式：注册表根键、快捷方式目录、数据目录全部改到测试位置。"""

    def __init__(self, root: Path | None = None):
        self.on = root is not None
        self.root = Path(root) if root else None
        if self.on:
            self.reg_root = r'Software\AstraForge-SetupTest'
            self.shortcut_dir = self.root / 'shortcuts'
            self.startup_dir = self.root / 'startup'
            self.data_dir = self.root / 'data'
        else:
            self.reg_root = rf'Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}'
            self.shortcut_dir = None
            self.startup_dir = None
            self.data_dir = None

    def prep(self):
        if self.on:
            for d in (self.root, self.shortcut_dir, self.startup_dir, self.data_dir):
                d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- 环境检测
def _cpu_count():
    return os.cpu_count() or 1


def _ram_gb():
    if not IS_WIN:
        return 0.0
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]

        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return round(m.ullTotalPhys / (1024 ** 3), 1)
    except Exception:
        return 0.0


def _gpu_name():
    """显卡名：读注册表显示适配器类（免 wmic）。"""
    if not IS_WIN:
        return ''
    try:
        import winreg
        key = r'SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
        names = []
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as sk:
                        d = dict(winreg.QueryValueEx(sk, 'DriverDesc')[0:2])
                    if isinstance(d, str) or d:
                        names.append(str(winreg.QueryValueEx(sk, 'DriverDesc')[0]))
                except OSError:
                    pass
        seen, out = set(), []
        for n in names:
            if n and n not in seen:
                seen.add(n)
                out.append(n)
        return ' / '.join(out[:2])
    except Exception:
        return ''


def _disk_free_gb(path: str):
    try:
        p = Path(path)
        while not p.exists() and p != p.parent:
            p = p.parent
        return round(shutil.disk_usage(str(p)).free / (1024 ** 3), 1)
    except Exception:
        return -1.0


def env_report() -> dict:
    cpu = _cpu_count()
    ram = _ram_gb()
    gpu = _gpu_name()
    return {
        'cpu': cpu, 'cpu_ok': cpu >= MIN_CPU,
        'ram': ram, 'ram_ok': ram >= MIN_RAM_GB,
        'gpu': gpu, 'gpu_cuda': 'nvidia' in gpu.lower(),
        'arch': os.environ.get('PROCESSOR_ARCHITECTURE', ''),
        'min_cpu': MIN_CPU, 'min_ram': MIN_RAM_GB, 'min_disk': MIN_DISK_GB,
        'admin': is_admin(),
    }


def is_admin() -> bool:
    if not IS_WIN:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def default_dir() -> str:
    """默认安装目录：管理员→Program Files；否则→LOCALAPPDATA\\Programs（免弹 UAC）。"""
    if is_admin():
        return rf'C:\Program Files\{APP_NAME}'
    base = os.environ.get('LOCALAPPDATA') or str(Path.home())
    return str(Path(base) / 'Programs' / APP_NAME)


# ---------------------------------------------------------------- 已安装检测
def find_installed(sb: Sandbox) -> dict | None:
    """读卸载注册项 → {dir, version, date}；没装过返回 None。"""
    if not IS_WIN:
        return None
    import winreg
    keys = [(winreg.HKEY_CURRENT_USER, sb.reg_root)]
    if not sb.on:
        keys.append((winreg.HKEY_LOCAL_MACHINE,
                     rf'Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}'))
        keys.append((winreg.HKEY_LOCAL_MACHINE,
                     rf'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}'))
    for hive, path in keys:
        try:
            with winreg.OpenKey(hive, path) as k:
                def g(n, dflt=''):
                    try:
                        return winreg.QueryValueEx(k, n)[0]
                    except OSError:
                        return dflt
                loc = str(g('InstallLocation', ''))
                if loc:
                    return {'dir': loc, 'version': str(g('DisplayVersion', '?')),
                            'date': str(g('InstallDate', '?')),
                            'hive': 'HKCU' if hive == winreg.HKEY_CURRENT_USER else 'HKLM',
                            'residual': not Path(loc).exists()}
        except OSError:
            continue
    return None


# ---------------------------------------------------------------- 版本 / 进程 / 相机与驱动检测
def cmp_version(a: str, b: str) -> int:
    """语义化版本比较（容忍 v 前缀与非数字段）：a<b → -1，相等 → 0，a>b → 1。"""
    def parts(s):
        out = []
        for p in str(s or '').strip().lstrip('vV').split('.'):
            d = ''.join(ch for ch in p if ch.isdigit())
            out.append(int(d) if d else 0)
        return out

    pa, pb = parts(a), parts(b)
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    return (pa > pb) - (pa < pb)


def is_app_running() -> bool:
    """只读判断 AstraForge 是否在运行（tasklist；失败按未运行处理）。"""
    if not IS_WIN:
        return False
    try:
        r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq AstraForge.exe', '/NH'],
                           capture_output=True, timeout=8)
        return b'astraforge.exe' in (r.stdout or b'').lower()
    except Exception:
        return False


def detect_cameras(timeout: int = 15) -> dict:
    """只读枚举奥比中光 USB 设备与驱动绑定（Get-PnpDevice，不动设备/驱动）。

    depth.state: ready=WinUSB 就绪 / conflict=obdrv* 等官方驱动（与 astra_raw 互斥）
                 / nodriver=无驱动 / other=未知驱动 / absent=未检测到
    """
    out = {'ok': False, 'depth': {'found': False, 'state': 'absent'}, 'color': {'found': False}}
    if not IS_WIN:
        return out
    ps = (
        "$d = Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB\\VID_2BC5*' }; "
        "foreach ($x in $d) { "
        "$s = (Get-PnpDeviceProperty -InstanceId $x.InstanceId -KeyName "
        "'DEVPKEY_Device_Service' -ErrorAction SilentlyContinue).Data; "
        "Write-Output ($x.InstanceId + '|' + $x.Status + '|' + $s) }"
    )
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                           capture_output=True, timeout=timeout)
        raw = r.stdout or b''
        try:
            txt = raw.decode('utf-8')
        except UnicodeDecodeError:
            txt = raw.decode('gbk', errors='replace')
    except Exception:
        return out
    for line in txt.splitlines():
        line = line.strip()
        if 'VID_2BC5' not in line:
            continue
        parts = line.split('|')
        if len(parts) < 3:
            continue
        iid, status, svc = parts[0].strip(), parts[1].strip(), parts[2].strip()
        import re as _re
        m = _re.search(r'PID_([0-9A-Fa-f]{4})', iid)
        pid = m.group(1).upper() if m else ''
        low = svc.lower()
        if 'winusb' in low:
            state = 'ready'
        elif low.startswith('obdrv') or 'orbbec' in low:
            state = 'conflict'
        elif not svc:
            state = 'nodriver'
        else:
            state = 'other'
        if pid == '0501':
            out['color'] = {'found': True, 'service': svc}
        elif pid:
            out['depth'] = {'found': True, 'state': state, 'service': svc,
                            'status': status, 'instance': iid, 'pid': pid,
                            'match': match_driver('2BC5', pid)}
    out['ok'] = True
    return out


def _remove_shortcuts(sb: Sandbox):
    """移除本应用的快捷方式（桌面/开始菜单/启动项）——安装、卸载、残留清理共用。"""
    names = [f'{APP_CN}.lnk', 'sm_' + f'{APP_CN}.lnk',
             SM_UNINST_NAME, 'sm_' + SM_UNINST_NAME]
    dirs = [sb.shortcut_dir] if sb.on else [_desktop_dir(), _startmenu_dir()]
    dirs += [sb.startup_dir] if sb.on else [_startup_dir()]
    for d in dirs:
        for n in names:
            try:
                p = d / n
                if p.exists():
                    p.unlink()
            except Exception:
                pass


def clean_residual(sb: Sandbox | None = None) -> dict:
    """清理"有卸载记录但目录已丢失"的残留：注册项 + 快捷方式/启动项。"""
    sb = sb or Sandbox()
    ok = _reg_delete(sb)
    _remove_shortcuts(sb)
    return {'ok': True, 'msg': '残留记录已清理', 'reg_removed': ok}


# ---------------------------------------------------------------- 快捷方式
# 纯 Python 写 .lnk（ShellLink 结构），**不依赖 pywin32/COM**：
#   COM 方案（WScript.Shell）在受限环境/沙箱里会被拦（实测 Save 报 0x80004005），
#   且冻结 exe 里还得多带一套 pywin32；自己写更稳、依赖更少。
_LNK_CLSID = bytes.fromhex('0114020000000000c000000000000046')


def _lnk_bytes(target: str, workdir: str, args: str = '', desc: str = '',
               icon: str = '') -> bytes:
    import struct
    from pathlib import PurePath

    def u32(v):
        return struct.pack('<I', v)

    def sdat(s):                     # 字符串数据段（u16 字符数 + UTF-16LE，含结尾 NUL）
        s = s + '\x00'
        return struct.pack('<H', len(s)) + s.encode('utf-16-le')

    # ---- 头部（76 字节）----
    flags = 0x00000002               # HasLinkInfo（不写 ItemIDList：空列表会被解析器误判）
    if desc:
        flags |= 0x00000004          # HasName
    if workdir:
        flags |= 0x00000008 | 0x00000010   # HasRelativePath | HasWorkingDir
    if args:
        flags |= 0x00000020
    if icon:
        flags |= 0x00000040
    flags |= 0x00000080              # IsUnicode
    header = u32(0x4C) + _LNK_CLSID + u32(flags)
    header += u32(0x00000020)                     # FileAttributes
    header += u32(0) + u32(0) + u32(0)            # 3 个时间戳
    header += u32(0) + u32(0)                     # 文件大小 / 图标索引
    header += u32(1)                              # ShowCommand = 正常窗口
    header += struct.pack('<H', 0) + struct.pack('<H', 0)

    idlist = b''

    # ---- LinkInfo：LocalBasePath = 目录，CommonPathSuffix = 文件名 ----
    p = PurePath(target)
    base_dir, name = str(p.parent), p.name
    try:
        ansi = lambda s: s.encode('mbcs')          # noqa: E731  （Windows ANSI 代码页）
    except Exception:
        ansi = lambda s: s.encode('utf-8')         # noqa: E731
    label = b'\x00'                                 # 空卷标（须是合法的空 ANSI 串）
    volid = struct.pack('<IIII', 16 + len(label), 3, 0, 16) + label   # FIXED 盘
    bpath = ansi(base_dir) + b'\x00'
    csuf = ansi(name) + b'\x00'
    vol_off = 0x1C
    base_off = vol_off + len(volid)
    suf_off = base_off + len(bpath)
    li = u32(0) + u32(0x1C) + u32(1) + u32(vol_off) + u32(base_off) + u32(0) + u32(suf_off)
    li = li + volid + bpath + csuf
    li = u32(len(li)) + li[4:]                     # 回填 LinkInfoSize

    # ---- StringData（顺序固定：NAME → RELATIVE_PATH → WORKING_DIR → ARGS → ICON）----
    body = idlist + li
    if desc:
        body += sdat(desc)
    if workdir:
        body += sdat(name)                                   # 相对路径 = 文件名
        body += sdat(workdir)
    if args:
        body += sdat(args)
    if icon:
        body += sdat(icon)
    return header + body


def _make_lnk(lnk_path: Path, target: Path, workdir: Path, icon: Path | None = None,
              args: str = '', desc: str = APP_CN) -> bool:
    """建快捷方式：① PowerShell/WScript.Shell（最可靠，Windows 自带）→ 读回校验；
    ② 失败则退到纯 Python 写 ShellLink。返回是否**建成且目标正确**。"""
    lnk_path = Path(lnk_path)
    try:
        lnk_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False
    tgt, wd = str(target), str(workdir)
    ps = (
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk_path}');"
        f"$s.TargetPath='{tgt}';"
        + (f"$s.WorkingDirectory='{wd}';" if wd else '')
        + (f"$s.Arguments='{args}';" if args else '')
        + (f"$s.Description='{desc}';" if desc else '')
        + (f"$s.IconLocation='{icon}',0;" if icon else '')
        + "$s.Save();"
        f"Write-Output ((New-Object -ComObject WScript.Shell).CreateShortcut('{lnk_path}').TargetPath)"
    )
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                           capture_output=True, timeout=40)
        raw = r.stdout or b''
        try:
            txt = raw.decode('utf-8')
        except UnicodeDecodeError:
            txt = raw.decode('gbk', errors='replace')
        got = txt.strip().splitlines()[-1].strip() if txt.strip() else ''
        if got and Path(got).name.lower() == Path(tgt).name.lower():
            return True
        _lnk_log(f'[lnk] PowerShell 结果不符：{lnk_path} 期望 {tgt} 得到 {got!r}')
    except Exception as e:
        _lnk_log(f'[lnk] PowerShell 失败 {lnk_path}: {type(e).__name__} {e}')

    # 不做"纯 Python 兜底"：实测自写的 .lnk Windows 解析不正确（会落到父目录）
    # → 如实返回 False，让安装流程能报告"快捷方式未建"，而不是留一个点了没反应的图标
    return False


def _lnk_log(msg: str):
    try:
        lp = Path(os.environ.get('TEMP', '.')) / 'AstraForge-setup.log'
        with lp.open('a', encoding='utf-8') as f:
            f.write(msg + '\n')
    except Exception:
        pass


def lnk_target(lnk_path: Path) -> str:
    """读回 .lnk 里的目标路径（自检用；COM 可用时优先用 COM，否则做简单扫描）。"""
    try:
        import win32com.client                     # noqa: PLC0415
        sh = win32com.client.Dispatch('WScript.Shell')
        return str(sh.CreateShortcut(str(lnk_path)).TargetPath)
    except Exception:
        pass
    try:
        raw = Path(lnk_path).read_bytes()
        txt = raw.decode('utf-16-le', errors='ignore')
        return txt.strip('\x00').split('\x00')[0]
    except Exception:
        return ''


def _desktop_dir() -> Path:
    return Path(os.environ.get('USERPROFILE', str(Path.home()))) / 'Desktop'


def _startmenu_dir() -> Path:
    return Path(os.environ.get('APPDATA', str(Path.home()))) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'


def _startup_dir() -> Path:
    return Path(os.environ.get('APPDATA', str(Path.home()))) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'


# ---------------------------------------------------------------- 注册卸载信息
def _reg_write(sb: Sandbox, install_dir: str, version: str, size_kb: int, uninst: str):
    if not IS_WIN:
        return
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, sb.reg_root, 0, winreg.KEY_WRITE) as k:
        exe = str(Path(install_dir) / APP_EXE)
        vals = {
            'DisplayName': f'{APP_CN}（{APP_NAME}）',
            'DisplayVersion': version,
            'Publisher': PUBLISHER,
            'InstallLocation': install_dir,
            'DisplayIcon': str(Path(install_dir) / '_internal' / 'icon.ico') if
            (Path(install_dir) / '_internal' / 'icon.ico').exists() else exe,
            # --dir 显式带上安装目录：注册表被清/目录被挪也能定位（定位链第①腿）
            'UninstallString': f'"{uninst}" --uninstall --dir "{install_dir}"',
            'QuietUninstallString': f'"{uninst}" --uninstall --silent --dir "{install_dir}"',
            'InstallDate': time.strftime('%Y%m%d'),
            'EstimatedSize': int(size_kb),
            'NoModify': 1, 'NoRepair': 1,
            'URLInfoAbout': URL,
        }
        for n, v in vals.items():
            winreg.SetValueEx(k, n, 0, winreg.REG_SZ if isinstance(v, str) else winreg.REG_DWORD, v)


def _reg_delete(sb: Sandbox) -> bool:
    if not IS_WIN:
        return False
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sb.reg_root)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- 安装
def _payload_path() -> Path | None:
    """载荷 zip：环境变量 AF_PAYLOAD → 安装器同目录 → _MEIPASS。"""
    cands = []
    env = os.environ.get('AF_PAYLOAD')
    if env:
        cands.append(Path(env))
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    cands += [base / 'payload.zip', Path(sys.executable).resolve().parent / 'payload.zip']
    cands += [Path(__file__).resolve().parent / 'payload.zip']
    # 兜底：构建时若载荷按版本名打入（AstraForge-x.y.z-payload.zip），也能找到
    try:
        if base.is_dir():
            cands += sorted(base.glob('AstraForge-*-payload.zip'))
    except Exception:
        pass
    for c in cands:
        if c.exists():
            return c
    return None


def _update_url() -> str:
    """在线更新源：环境变量 AF_UPDATE_URL 优先（测试用），否则内置 DEFAULT_UPDATE_URL。"""
    return (os.environ.get('AF_UPDATE_URL', '').strip() or DEFAULT_UPDATE_URL).strip()


def fetch_update(timeout: float = 4.0) -> dict:
    """拉 update.json；未配置/网络失败都返回 ok=False（安装器回退本地，不报错）。"""
    url = _update_url()
    if not url:
        return {'ok': False, 'reason': 'not_configured'}
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': 'AstraForge-Setup'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode('utf-8'))
        if not isinstance(data, dict) or not data.get('latest'):
            return {'ok': False, 'reason': 'bad_json'}
        return {
            'ok': True,
            'latest': str(data.get('latest')),
            'payload_url': str(data.get('payload_url') or ''),
            'payload_sha256': str(data.get('payload_sha256') or ''),
            'min_installer': str(data.get('min_installer') or ''),
            'notes_url': str(data.get('notes_url') or ''),
        }
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'reason': 'network', 'msg': f'{type(e).__name__}: {e}'}


def download_file(url: str, dest: Path, sha256: str = '', cb=None, cancel=None) -> Path:
    """流式下载到 dest（先写 .part，校验后改名）。支持 http(s)/file://。"""
    import hashlib
    import urllib.request

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cb = cb or (lambda p, s: None)
    cancel = cancel or (lambda: False)
    tmp = dest.with_name(dest.name + '.part')
    h = hashlib.sha256()
    total = 0
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'AstraForge-Setup'})
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, 'wb') as f:
            try:
                length = int(r.headers.get('Content-Length') or 0)
            except Exception:
                length = 0
            while True:
                if cancel():
                    raise KeyboardInterrupt
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                total += len(chunk)
                if length:
                    cb(min(99, int(total * 100 / max(length, 1))),
                       f'正在下载安装包… {total // 1048576} / {max(length // 1048576, 1)} MB')
                else:
                    cb(50, f'正在下载安装包… {total // 1048576} MB')
        if sha256 and h.hexdigest().lower() != sha256.lower():
            raise ValueError('SHA256 校验失败（下载文件不完整或被篡改）')
        tmp.replace(dest)
        return dest
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


# ---------------------------------------------------------------- 驱动库
def driver_pack_dir() -> Path | None:
    """驱动库目录：onefile 的 _MEIPASS/driver_pack → 源码 installer/driver/pack
    → 安装根 `驱动工具/`（BUG-024：装完长期保留的那份）。"""
    cands = [
        Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'driver_pack',
        Path(__file__).resolve().parent / 'driver' / 'pack',
        Path(sys.executable).resolve().parent / 'driver_pack',
        Path(sys.executable).resolve().parent / '驱动工具',
    ]
    for c in cands:
        try:
            if (c / 'manifest.json').exists():
                return c
        except Exception:
            pass
    return None


def load_driver_manifest() -> dict:
    d = driver_pack_dir()
    if not d:
        return {}
    try:
        return json.loads((d / 'manifest.json').read_text(encoding='utf-8'))
    except Exception:
        return {}


def match_driver(vid: str, pid: str) -> dict | None:
    """按 VID/PID 匹配驱动条目。"""
    vid, pid = (vid or '').upper(), (pid or '').upper()
    for drv in load_driver_manifest().get('drivers', []):
        mt = drv.get('match') or {}
        if str(mt.get('vid', '')).upper() != vid:
            continue
        pids = [str(x).upper() for x in (mt.get('pid') or [])]
        if pid in pids:
            return drv
    return None


def install_driver(driver_id: str) -> dict:
    """安装驱动：签名 INF 走 pnputil（必要时 UAC），无签名走 Zadig 引导。"""
    pack = driver_pack_dir()
    entry = next((d for d in load_driver_manifest().get('drivers', [])
                  if d.get('id') == driver_id), None)
    if not pack or not entry:
        return {'ok': False, 'msg': f'驱动条目不存在：{driver_id}'}
    method = str(entry.get('method') or '')
    files = entry.get('files') or []

    if method == 'pnputil-inf':
        inf = pack / str(files[0]) if files else None
        if not inf or not inf.exists():
            return {'ok': False, 'msg': f'驱动文件缺失：{inf}'}
        if is_admin():
            try:
                r = subprocess.run(['pnputil', '/add-driver', str(inf), '/install'],
                                   capture_output=True, timeout=180)
                out = (r.stdout or b'').decode('gbk', errors='replace')
                ok = r.returncode == 0
                return {'ok': ok, 'msg': '驱动已安装' if ok else '驱动安装失败（见安装日志）',
                        'output': out[-800:]}
            except Exception as e:  # noqa: BLE001
                return {'ok': False, 'msg': f'pnputil 调用失败：{e}'}
        # 非管理员：单独提权（只弹 UAC，不开第二个应用窗口）
        ps = ("Start-Process -FilePath pnputil.exe -ArgumentList "
              f"'/add-driver','\"{inf}\"','/install' -Verb RunAs -Wait -WindowStyle Hidden")
        try:
            subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                           capture_output=True, timeout=180)
            return {'ok': True, 'elevated': True,
                    'msg': '已请求管理员权限；请在系统弹窗确认，完成后点「重新检测」'}
        except Exception as e:  # noqa: BLE001
            return {'ok': False, 'msg': f'提权失败：{e}'}

    if method == 'zadig-guided':
        return {'ok': False, 'guided': True,
                'msg': '该驱动无签名，请用随包驱动工具按向导安装'}

    return {'ok': False, 'msg': f'未知驱动安装方式：{method}'}


def driver_tool_path() -> str:
    """驱动工具（Zadig）绝对路径。

    BUG-024（2026-10-20）：随包布局是 `驱动工具/zadig/zadig.exe`（**多一层 `zadig/`**），
    旧实现只找 `驱动工具/zadig.exe` → 永远找不到 → 「打开驱动工具」只弹"未找到"。
    现在优先读 `manifest.json` 的 `tools.zadig`，其余候选只为老包兼容；
    候选顺序与 `core/driverpack.py` 保持一致（probe74 强制校验）。
    """
    pack = driver_pack_dir()
    if pack:
        try:
            man = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))
            rel = str((man.get('tools') or {}).get('zadig') or '').strip()
            if rel:
                p = (pack / rel).resolve()
                if p.exists():
                    return str(p)
        except Exception:
            pass
    exe_dir = Path(sys.executable).resolve().parent
    meipass = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    cands = [
        exe_dir / '驱动工具' / 'zadig' / 'zadig.exe',      # 安装根（真实布局）
        exe_dir / '驱动工具' / 'zadig.exe',                # 老布局兼容
        exe_dir / '驱动工具' / 'zadig' / 'x64' / 'zadig.exe',
        meipass / '驱动工具' / 'zadig' / 'zadig.exe',
        meipass / '驱动工具' / 'zadig.exe',
        meipass / 'driver_pack' / 'zadig' / 'zadig.exe',
        meipass / 'driver_pack' / 'zadig.exe',
        Path(__file__).resolve().parent / 'driver' / 'pack' / 'zadig' / 'zadig.exe',
        Path(__file__).resolve().parent / 'driver' / 'zadig.exe',
        exe_dir / 'driver' / 'zadig.exe',
    ]
    for c in cands:
        try:
            if c.exists():
                return str(c)
        except Exception:
            pass
    return ''


def ensure_depth_driver(auto_install: bool = True) -> dict:
    """安装流程"驱动准备"步：设备在但驱动不对 → 当场装（失败不阻塞主安装）。

    返回 {ok, skipped?, already?, guided?, driver_id?, msg, ...install_driver 结果}
    """
    if not IS_WIN:
        return {'ok': False, 'skipped': True, 'msg': '非 Windows，跳过驱动准备'}
    try:
        info = detect_cameras()
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'msg': f'设备枚举失败：{e}'}
    depth = (info or {}).get('depth') or {}
    if not depth.get('found'):
        return {'ok': False, 'skipped': True,
                'msg': '未检测到深度相机；装好后插上，可在软件「关于与更新」里一键安装驱动'}
    if depth.get('state') == 'ready':
        return {'ok': True, 'skipped': True, 'already': True,
                'msg': f"驱动已就绪（{depth.get('service') or 'WinUSB'}）"}
    pid = str(depth.get('pid') or '')
    entry = match_driver('2BC5', pid)
    if not entry:
        return {'ok': False, 'msg': f'驱动库没有匹配 2BC5:{pid} 的条目'}
    did = str(entry.get('id') or '')
    method = str(entry.get('method') or '')
    state = str(depth.get('state') or '')
    if method == 'zadig-guided' or state == 'conflict':
        return {'ok': False, 'guided': True, 'driver_id': did,
                'zadig': driver_tool_path(),
                'msg': '该设备需要用驱动向导（Zadig）切换驱动'}
    if not auto_install:
        return {'ok': False, 'pending': True, 'driver_id': did,
                'msg': '检测到设备，已跳过自动安装（可在软件内安装）'}
    r = install_driver(did)
    r['driver_id'] = did
    return r


def _extract_retry(z: zipfile.ZipFile, name: str, target: Path, tries: int = 4, delay: float = 0.6):
    """解压单个条目；PermissionError 自动重试。

    场景：覆盖升级时，杀软/索引器可能正在扫描刚写入的大文件（如 cv2.pyd），
    瞬时占用会让 extract 抛 PermissionError（实测 E2E 升级用例偶发一次）。重试数轮即可。
    """
    last = None
    for k in range(tries):
        try:
            return z.extract(name, str(target))
        except PermissionError as e:
            last = e
            time.sleep(delay * (k + 1))
    raise last


def install(opts: dict, cb=None, cancel=None, sb: Sandbox | None = None) -> dict:
    """执行安装。opts: {dir, desktop, startmenu, autostart, drivers, version}
    cb(pct:int, stage:str)；cancel() -> bool。返回 {ok, msg, dir, created:[...]}"""
    sb = sb or Sandbox()
    sb.prep()
    cb = cb or (lambda p, s: None)
    cancel = cancel or (lambda: False)
    created: list[str] = []
    target = Path(opts['dir'])
    prev_version = ''
    try:
        _ij = target / 'install.json'
        if _ij.exists():
            prev_version = str(json.loads(_ij.read_text(encoding='utf-8')).get('version', ''))
    except Exception:
        prev_version = ''

    def step(pct, text):
        cb(pct, text)
        time.sleep(0.15)          # 让 UI 有机会渲染（本地操作很快）

    # 0) 校验 / 下载
    step(3, '正在校验安装包…')
    version = str(opts.get('version') or '0.0.0')
    downloaded = False
    if opts.get('payload_url'):
        version = str(opts.get('latest_version') or version)
        dest = Path(tempfile.gettempdir()) / 'AstraForge' / f'payload-{version}.zip'
        step(5, '正在连接更新源…')
        try:
            payload = download_file(
                str(opts['payload_url']), dest,
                sha256=str(opts.get('payload_sha256') or ''),
                cb=lambda p, s: cb(5 + int(p * 0.10), s),
                cancel=cancel)
            downloaded = True
        except KeyboardInterrupt:
            return {'ok': False, 'msg': '已取消下载', 'created': created}
        except Exception as e:  # noqa: BLE001
            return {'ok': False, 'msg': f'下载安装包失败：{e}', 'created': created}
        step(15, '下载完成，正在校验…')
    else:
        payload = _payload_path()
    if payload is None:
        return {'ok': False,
                'msg': '本安装包为在线下载器：需要联网获取安装包，或改用离线完整包',
                'created': created}

    # 1) 目录准备（必须是空目录或已有 AstraForge 安装）
    step(8, '正在准备安装位置…')
    try:
        if target.exists() and any(target.iterdir()):
            looks_installed = (target / APP_EXE).exists() or (target / 'install.json').exists()
            if not looks_installed:
                return {'ok': False, 'created': created,
                        'msg': f'目标目录非空且不像 AstraForge 安装目录：{target}'}
        target.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return {'ok': False, 'created': created,
                'msg': f'没有写入权限：{target}（装到 Program Files 需要管理员权限，'
                       f'建议改用默认的「仅为我安装」目录）'}
    except OSError as e:
        return {'ok': False, 'created': created, 'msg': f'目录不可用：{e}'}

    # 2) 解压
    step(15, '正在解压程序文件…')
    try:
        with zipfile.ZipFile(payload) as z:
            names = z.namelist()
            total = max(len(names), 1)
            for i, n in enumerate(names):
                if cancel():
                    raise KeyboardInterrupt
                _extract_retry(z, n, target)
                if i % 40 == 0:
                    cb(15 + int(60 * i / total), '正在解压程序文件…')
        cb(75, '正在写入运行时组件…')
        if downloaded:
            try:
                payload.unlink(missing_ok=True)     # 临时下载包用完即删，省空间
            except Exception:
                pass
    except KeyboardInterrupt:
        _rollback(created, target)
        return {'ok': False, 'msg': '已取消（回滚完成）', 'created': created}
    except Exception as e:
        _rollback(created, target)
        return {'ok': False, 'msg': f'解压失败：{e}', 'created': created}

    # 2.5) 驱动准备（BUG-024：老大口径"安装时没驱动就装上"）
    #      失败/跳过都**不阻塞主安装**，事后可在软件「关于与更新」里一键修复。
    driver_result = None
    if opts.get('drivers', True) and not getattr(sb, 'on', False):
        step(76, '正在检查深度相机驱动…')
        try:
            driver_result = ensure_depth_driver(auto_install=True)
        except Exception as e:  # noqa: BLE001
            driver_result = {'ok': False, 'msg': f'驱动检查异常：{e}'}
        try:
            msg = str(driver_result.get('msg') or '')
            if driver_result.get('guided'):
                msg = '驱动需要 Zadig 向导（安装完成后可在软件内打开）'
            step(78, msg or '驱动稍后可安装')
        except Exception:
            pass

    # 3) 快捷方式
    exe = target / APP_EXE
    lnk_name = f'{APP_CN}.lnk'
    if opts.get('desktop', True):
        cb(80, '正在创建桌面快捷方式…')
        lnk = (sb.shortcut_dir / lnk_name) if sb.on else (_desktop_dir() / lnk_name)
        if _make_lnk(lnk, exe, target):
            created.append(f'lnk:{lnk}')
    if opts.get('startmenu', True):
        cb(84, '正在创建开始菜单项…')
        lnk = (sb.shortcut_dir / ('sm_' + lnk_name)) if sb.on else (_startmenu_dir() / lnk_name)
        if _make_lnk(lnk, exe, target):
            created.append(f'lnk:{lnk}')
        # 开始菜单里再放一个「卸载」入口（普通用户不必进安装目录找卸载器）
        un = target / UNINST_EXE
        if un.exists():
            lnk = (sb.shortcut_dir / ('sm_' + SM_UNINST_NAME)) if sb.on else (_startmenu_dir() / SM_UNINST_NAME)
            if _make_lnk(lnk, un, target, args='--uninstall', desc=f'卸载 {APP_CN}'):
                created.append(f'lnk:{lnk}')

    # 4) 开机自启（可选）
    if opts.get('autostart'):
        cb(87, '正在设置开机自启…')
        lnk = (sb.startup_dir / lnk_name) if sb.on else (_startup_dir() / lnk_name)
        if _make_lnk(lnk, exe, target, desc=f'{APP_CN}（开机自启）'):
            created.append(f'lnk:{lnk}')

    # 5) 卸载注册
    cb(90, '正在注册卸载信息…')
    # 卸载器：优先用安装目录根的 AstraForge-卸载.exe（新版布局）；
    # 旧版（_setup/ 子目录）兼容；都没有（源码方式安装/沙箱）就退回当前正在跑的安装器 exe
    bundled = target / UNINST_EXE
    if not bundled.exists():
        bundled = target / '_setup' / UNINST_EXE
    if not bundled.exists():
        bundled = target / '_setup' / 'AstraForge-Setup.exe'
    if not bundled.exists():
        bundled = Path(sys.executable)
    try:
        size_kb = sum(f.stat().st_size for f in target.rglob('*') if f.is_file()) // 1024
    except Exception:
        size_kb = 0
    _reg_write(sb, str(target), version, size_kb, str(bundled))

    # 6) 安装清单
    cb(95, '正在收尾…')
    try:
        (target / 'install.json').write_text(json.dumps({
            'app': APP_NAME, 'version': version, 'dir': str(target),
            'installed_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_from': prev_version if prev_version and prev_version != version else '',
            'options': {k: opts.get(k) for k in ('desktop', 'startmenu', 'autostart', 'drivers')},
            'payload': payload.name}, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass
    cb(100, '安装完成')
    return {'ok': True, 'msg': '安装完成', 'dir': str(target), 'version': version,
            'created': created, 'driver': driver_result}


def _rollback(created: list[str], target: Path):
    """逆序清理已创建项（快捷方式）+ 删除已解压文件。"""
    for item in reversed(created):
        try:
            if item.startswith('lnk:'):
                p = Path(item[4:])
                if p.exists():
                    p.unlink()
        except Exception:
            pass
    try:
        if target.exists() and not (target / 'install.json').exists():
            shutil.rmtree(target, ignore_errors=True)
    except Exception:
        pass


# ---------------------------------------------------------------- 卸载
def stop_running(grace_s: float = 10.0):
    """停掉正在运行的主程序（避免占用文件）。

    先温和请求退出（taskkill 不带 /F = 发 WM_CLOSE），等最多 grace_s 秒；
    仍在运行才强杀——正在扫描没保存就丢了（2026-10-20 拍板）。
    """
    if not IS_WIN or not is_app_running():
        return
    for exe in (APP_EXE, 'AstraForge.exe'):
        try:
            subprocess.run(['taskkill', '/IM', exe], capture_output=True, timeout=8)
        except Exception:
            pass
    t0 = time.time()
    while time.time() - t0 < grace_s:
        if not is_app_running():
            return
        time.sleep(0.5)
    for exe in (APP_EXE, 'AstraForge.exe'):
        try:
            subprocess.run(['taskkill', '/IM', exe, '/F'], capture_output=True, timeout=8)
        except Exception:
            pass


# ---------------------------------------------------------------- 驱动卸载（卸载器勾选用）
def list_oem_drivers() -> list[dict]:
    """pnputil /enum-drivers → 全部已发布驱动包（发布名/原始名/提供程序）。"""
    if not IS_WIN:
        return []
    try:
        r = subprocess.run(['pnputil', '/enum-drivers'], capture_output=True, timeout=25,
                           creationflags=0x08000000)
        out = (r.stdout or b'').decode('gbk', errors='replace')
    except Exception:
        return []
    drivers, cur = [], {}

    def _flush():
        if cur.get('oem_name'):
            drivers.append(dict(cur))

    for line in out.splitlines():
        s = line.strip()
        low = s.lower()
        if ('发布名称' in s) or low.startswith('published name'):
            _flush()
            cur = {'oem_name': s.split(':', 1)[-1].strip()}
        elif ('原始名称' in s) or low.startswith('original name'):
            cur['orig_name'] = s.split(':', 1)[-1].strip()
        elif ('提供程序名称' in s) or low.startswith('provider name'):
            cur['provider'] = s.split(':', 1)[-1].strip()
    _flush()
    return drivers


def uninstall_drivers() -> dict:
    """卸载 Orbbec/Astra 相机驱动（pnputil /delete-driver /uninstall /force）。

    非管理员自动提权（UAC 弹窗）；提权后无法可靠拿退出码，如实标注"已请求"。
    """
    hits = [d for d in list_oem_drivers()
            if any(k in json.dumps(d, ensure_ascii=False).lower()
                   for k in ('orbbec', 'astra'))]
    if not hits:
        return {'ok': True, 'removed': [], 'msg': '未找到 Orbbec/Astra 驱动包（可能未安装）'}
    removed, errs = [], []
    for d in hits:
        oem = str(d.get('oem_name') or '')
        if not oem.lower().endswith('.inf'):
            continue
        if is_admin():
            try:
                r = subprocess.run(['pnputil', '/delete-driver', oem, '/uninstall', '/force'],
                                   capture_output=True, timeout=60, creationflags=0x08000000)
                (removed if r.returncode == 0 else errs).append(oem)
            except Exception:
                errs.append(oem)
        else:
            ps = ("Start-Process -FilePath pnputil.exe -ArgumentList "
                  f"'/delete-driver','\"{oem}\"','/uninstall','/force' "
                  "-Verb RunAs -Wait -WindowStyle Hidden")
            try:
                subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                               capture_output=True, timeout=90, creationflags=0x08000000)
                removed.append(oem + '（已请求管理员执行）')
            except Exception:
                errs.append(oem)
    if removed:
        return {'ok': True, 'removed': removed, 'errors': errs,
                'msg': '驱动已卸载：' + '、'.join(removed)}
    return {'ok': False, 'removed': [], 'errors': errs, 'msg': '驱动卸载失败：' + '、'.join(errs)}


def uninstall(install_dir: str, keep_data: bool = True, cb=None,
              sb: Sandbox | None = None, remove_driver: bool = False) -> dict:
    """卸载：删程序文件 + 快捷方式 + 启动项 + 注册项。keep_data=False 时连数据一起删。

    保留（keep_data=True，2026-10-20 拍板/修 BUG）：
    - 扫描输出/（顶层用户数据）
    - code/data/（设置.json + 标定.json）——旧名单写顶层 data/ 是错的，实际在 code/data/，
      删 code/ 时会连锅端，「保留设置」是空头支票。现在 code/ 只删 data/ 以外的内容。
    logs/ 会话日志随软件删（拍板）。
    """
    sb = sb or Sandbox()
    cb = cb or (lambda p, s: None)
    target = Path(install_dir)
    if not target.exists():
        return {'ok': False, 'msg': f'安装目录不存在：{target}'}
    if not ((target / APP_EXE).exists() or (target / 'install.json').exists()):
        return {'ok': False, 'msg': f'该目录不像 AstraForge 安装目录，已拒绝删除：{target}'}

    cb(5, '正在停止运行中的程序…')
    stop_running()
    time.sleep(0.4)

    cb(18, '正在移除快捷方式与启动项…')
    _remove_shortcuts(sb)

    cb(32, '正在删除程序文件…')
    keep = {'扫描输出', 'data'}          # 顶层保留名
    kept: list[str] = []
    removed_bytes = 0
    self_path = Path(sys.executable).resolve()
    # 运行中的卸载器 exe / 它被锁住的运行时目录（_setup_internal）删不干净 →
    # 记下来，交给进程退出后的延迟清理（schedule_final_cleanup）
    cleanup_paths: list[str] = []
    if self_path.parent == target:
        cleanup_paths.append(str(self_path))
        mp = getattr(sys, '_MEIPASS', None)
        if mp:
            mp = Path(mp).resolve()
            if mp.parent == target and mp != self_path.parent and mp.is_dir():
                cleanup_paths.append(str(mp))

    def _del_dir(d: Path):
        """删目录；keep_data 时 code/data（设置+标定）整体保留。"""
        if keep_data and d.name == 'code' and (d / 'data').is_dir():
            for sub in d.iterdir():
                if sub.name == 'data':
                    continue
                if sub.is_dir():
                    shutil.rmtree(sub, ignore_errors=True)
                else:
                    try:
                        removed_bytes_local = sub.stat().st_size
                        sub.unlink()
                    except Exception:
                        pass
            kept.append('code/data（设置与标定）')
            return
        shutil.rmtree(d, ignore_errors=True)   # 被锁文件删不掉，由 cleanup 兜底

    for item in sorted(target.iterdir(), key=lambda p: (p.is_dir(), p.name)):
        try:
            if item.resolve() == self_path:
                continue                     # 自己（卸载器）留到退出后删
            if keep_data and item.name in keep:
                kept.append(item.name)
                continue
            if item.is_dir():
                _del_dir(item)
            else:
                removed_bytes += item.stat().st_size
                item.unlink()
        except Exception:
            pass

    cb(62, '正在清理注册信息…')
    _reg_delete(sb)

    cb(72, '正在收尾…')
    if not keep_data:
        for n in keep:
            shutil.rmtree(target / n, ignore_errors=True)
        kept = []
    else:
        # code/data 没走到 keep 分支也要报保留（目录本身可能不存在，如实）
        if not any('code/data' in k for k in kept) and (target / 'code' / 'data').exists():
            kept.append('code/data（设置与标定）')

    drv = {'ok': True, 'msg': '未勾选卸载驱动', 'removed': []}
    if remove_driver:
        cb(84, '正在卸载相机驱动…')
        drv = uninstall_drivers()

    cb(100, '卸载完成')
    return {'ok': True, 'msg': '卸载完成', 'dir': str(target),
            'kept': kept, 'driver': drv,
            'cleanup_paths': cleanup_paths}


def schedule_final_cleanup(paths: list[str]):
    """退出后延迟清理：Windows 删不掉运行中的 exe / 被进程锁住的运行时目录
    → 脱离进程，等约 2 秒（ping 延迟）再删残余。"""
    if not IS_WIN or not paths:
        return
    try:
        cmds = []
        for p in paths:
            q = f'"{p}"'
            cmds.append(f'rd /s /q {q}' if Path(p).is_dir() else f'del /f /q {q}')
        cmd = 'cmd /c ping -n 3 127.0.0.1 >nul & ' + ' & '.join(cmds)
        subprocess.Popen(cmd, shell=True, creationflags=0x00000008 | 0x00000200)  # DETACHED|NEW_PROCESS_GROUP
    except Exception:
        pass


# ---------------------------------------------------------------- 目录浏览（供安装器 UI）
def list_dir(path: str) -> dict:
    p = Path(path)
    out = {'path': str(p), 'dirs': [], 'drives': []}
    if IS_WIN:
        for d in 'CDEFGHIJKLMNOPQRSTUVWXYZ':
            root = Path(d + ':\\')
            if root.exists():
                out['drives'].append(d + ':')
    try:
        for c in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            if c.is_dir() and not c.name.startswith('$'):
                out['dirs'].append(c.name)
    except Exception:
        pass
    return out


def mkdir(path: str) -> dict:
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'msg': str(e)}
