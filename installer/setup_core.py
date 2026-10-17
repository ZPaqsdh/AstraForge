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
import time
import zipfile
from pathlib import Path

APP_NAME = 'AstraForge'
APP_CN = 'AstraForge 星铸'
APP_EXE = 'AstraForge.exe'
UNINST_EXE = 'AstraForge-卸载.exe'
SM_UNINST_NAME = f'卸载 {APP_CN}.lnk'      # 开始菜单里的「卸载」入口
PUBLISHER = 'AstraForge 项目'
URL = 'https://github.com/'          # TODO-002 建仓后填
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
        if 'PID_0403' in iid:
            low = svc.lower()
            if 'winusb' in low:
                state = 'ready'
            elif low.startswith('obdrv') or 'orbbec' in low:
                state = 'conflict'
            elif not svc:
                state = 'nodriver'
            else:
                state = 'other'
            out['depth'] = {'found': True, 'state': state, 'service': svc,
                            'status': status, 'instance': iid}
        elif 'PID_0501' in iid:
            out['color'] = {'found': True, 'service': svc}
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
            'UninstallString': f'"{uninst}" --uninstall',
            'QuietUninstallString': f'"{uninst}" --uninstall --silent',
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
    for c in cands:
        if c.exists():
            return c
    return None


def driver_tool_path() -> str:
    """驱动工具（Zadig）：安装包根 `驱动工具\\zadig.exe`；源码布局回退 installer/driver。"""
    exe_dir = Path(sys.executable).resolve().parent
    meipass = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    cands = [
        exe_dir / '驱动工具' / 'zadig.exe',
        meipass / '驱动工具' / 'zadig.exe',
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

    # 0) 校验
    step(3, '正在校验安装包…')
    payload = _payload_path()
    if payload is None:
        return {'ok': False, 'msg': '找不到载荷 payload.zip（安装包不完整）', 'created': created}
    version = str(opts.get('version') or '0.0.0')

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
    except KeyboardInterrupt:
        _rollback(created, target)
        return {'ok': False, 'msg': '已取消（回滚完成）', 'created': created}
    except Exception as e:
        _rollback(created, target)
        return {'ok': False, 'msg': f'解压失败：{e}', 'created': created}

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
            'options': {k: opts.get(k) for k in ('desktop', 'startmenu', 'autostart')},
            'payload': payload.name}, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass
    cb(100, '安装完成')
    return {'ok': True, 'msg': '安装完成', 'dir': str(target), 'version': version,
            'created': created}


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
def stop_running():
    """停掉正在运行的主程序（避免占用文件）。"""
    if not IS_WIN:
        return
    for exe in (APP_EXE, 'AstraForge.exe'):
        try:
            subprocess.run(['taskkill', '/IM', exe, '/F'], capture_output=True, timeout=8)
        except Exception:
            pass


def uninstall(install_dir: str, keep_data: bool = True, cb=None, sb: Sandbox | None = None) -> dict:
    """卸载：删程序文件 + 快捷方式 + 启动项 + 注册项。keep_data=False 时连数据一起删。"""
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

    cb(20, '正在移除快捷方式与启动项…')
    _remove_shortcuts(sb)

    cb(35, '正在删除程序文件…')
    keep = {'扫描输出', 'data'}
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
    for item in sorted(target.iterdir(), key=lambda p: (p.is_dir(), p.name)):
        try:
            if item.resolve() == self_path:
                continue                     # 自己（卸载器）留到退出后删
            if keep_data and item.name in keep:
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)   # 运行时目录里被锁的文件删不掉，由 cleanup 兜底
            else:
                removed_bytes += item.stat().st_size
                item.unlink()
        except Exception:
            pass

    cb(75, '正在清理注册信息…')
    _reg_delete(sb)

    cb(90, '正在收尾…')
    if not keep_data:
        for n in keep:
            shutil.rmtree(target / n, ignore_errors=True)

    cb(100, '卸载完成')
    return {'ok': True, 'msg': '卸载完成', 'dir': str(target),
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
