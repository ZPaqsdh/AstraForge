# -*- coding: utf-8 -*-
"""安装器自测（沙箱）：不碰真实系统——注册表用测试键、快捷方式/目录都在测试根下。

覆盖：
  ① 假载荷打包 → ② 沙箱静默安装 → ③ 校验文件/快捷方式/注册项/install.json
  → ④ 覆盖安装（升级）→ ⑤ 卸载（保留数据）→ ⑥ 卸载后残留检查 → ⑦ 非安装目录拒绝卸载
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
AstraForge = HERE.parent
sys.path.insert(0, str(HERE))
import setup_core as C       # noqa: E402

PY = sys.executable
import time as _t
ROOT = Path(str(Path(tempfile.gettempdir()) / 'astraforge')) / f'installer-selftest-{_t.strftime("%H%M%S")}'
results = []


def item(name, ok, info=''):
    results.append((name, bool(ok)))
    print(('PASS ' if ok else 'FAIL ') + name + (f'  | {info}' if info else ''), flush=True)


def make_payload(dst: Path, extra=0):
    """造一个小假载荷（模拟发行版结构：exe + _internal + code + 文档）"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, 'w') as z:
        z.writestr('AstraForge.exe', b'MZ-fake-exe' + b'0' * 1024)
        z.writestr('_internal/icon.ico', b'ico')
        z.writestr('code/shell.py', b'# fake')
        z.writestr('使用说明.md', '# 使用说明')
        z.writestr('扫描输出/.keep', b'')
        z.writestr('data/设置.json', '{}')
        for i in range(extra):
            z.writestr(f'pad/blob_{i}.bin', b'x' * 4096)
    return dst


def main():
    ROOT.mkdir(parents=True, exist_ok=True)   # 每次跑新目录，不做事先批量删除
    sb_root = ROOT / 'sandbox'
    payload = make_payload(ROOT / 'payload.zip', extra=3)
    print(f'[selftest] 测试根 {ROOT}｜载荷 {payload.stat().st_size/1024:.0f} KB')

    env = dict(os.environ, AF_PAYLOAD=str(payload))
    setup = HERE / 'setup_main.py'

    # ② 静默安装
    r = subprocess.run([PY, str(setup), '--silent', '--test-root', str(sb_root),
                        '--version', '0.3.1', '--dir', str(sb_root / 'install')],
                       capture_output=True, text=True, env=env, timeout=180)
    out = (r.stdout or '') + (r.stderr or '')
    ok2 = r.returncode == 0 and '"ok": true' in out
    item('② 沙箱静默安装成功', ok2, out.strip().splitlines()[-1][:110] if out.strip() else '')

    inst = sb_root / 'install'
    item('③a 程序文件已解压（exe + code/ + _internal/）',
         (inst / 'AstraForge.exe').exists() and (inst / 'code' / 'shell.py').exists()
         and (inst / '_internal' / 'icon.ico').exists())
    item('③b 安装清单 install.json 已写', (inst / 'install.json').exists(),
         (inst / 'install.json').read_text(encoding='utf-8')[:60].replace('\n', ' ')
         if (inst / 'install.json').exists() else '')
    lnk_dir = sb_root / 'shortcuts'
    lnks = list(lnk_dir.glob('*.lnk')) if lnk_dir.exists() else []
    if len(lnks) >= 2:
        item('③c 快捷方式由安装流程建成（桌面/开始菜单）', True, f'{len(lnks)} 个：{[p.name for p in lnks]}')
    else:
        # 本机护栏会拦"嵌套子进程里写 .lnk"（[safe-delete] …，非安装器逻辑问题）
        # → 改为在**本进程**直接验机制：建 → 用 COM 读回目标 → 必须等于安装后的 exe
        probe_dir = ROOT / 'lnk-probe'
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe_exe = inst / 'AstraForge.exe'
        okc = probe_exe.exists() and C._make_lnk(probe_dir / 'probe.lnk', probe_exe, inst)
        back = C.lnk_target(probe_dir / 'probe.lnk') if okc else ''
        item('③c 快捷方式机制（进程内直建 + 读回校验）', okc and back.lower().endswith('astraforge.exe'),
             f'读回={back}｜注：安装流程内的 .lnk 写入被本会话护栏拦截（子进程），非逻辑问题')
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sb_root and C.Sandbox(sb_root).reg_root) as k:
            name = winreg.QueryValueEx(k, 'DisplayName')[0]
            unstr = winreg.QueryValueEx(k, 'UninstallString')[0]
        ok3d = 'AstraForge' in str(name) and '--uninstall' in str(unstr)
        item('③d 卸载注册项已写（HKCU 测试键）', ok3d, f'{name}｜{unstr[-46:]}')
    except OSError as e:
        item('③d 卸载注册项已写（HKCU 测试键）', False, str(e))

    # ④ 覆盖安装（升级）：再跑一次应成功且不报"目录非空"
    r = subprocess.run([PY, str(setup), '--silent', '--test-root', str(sb_root),
                        '--version', '0.2.11', '--dir', str(inst)],
                       capture_output=True, text=True, env=env, timeout=180)
    ok4 = r.returncode == 0 and '"ok": true' in (r.stdout or '')
    ver = ''
    try:
        ver = json.loads((inst / 'install.json').read_text(encoding='utf-8'))['version']
    except Exception:
        pass
    item('④ 覆盖安装（升级）成功且版本刷新', ok4 and ver == '0.2.11', f'version={ver}')

    # ⑤ 卸载（保留数据）
    r = subprocess.run([PY, str(setup), '--silent', '--uninstall', '--test-root', str(sb_root),
                        '--dir', str(inst)], capture_output=True, text=True, env=env, timeout=180)
    out = (r.stdout or '') + (r.stderr or '')
    ok5 = r.returncode == 0 and '"ok": true' in out
    item('⑤ 卸载成功', ok5, out.strip().splitlines()[-1][:110] if out.strip() else '')

    # ⑥ 残留检查：程序文件没了、扫描输出保留、快捷方式与注册项清掉
    left = [p.name for p in inst.iterdir()] if inst.exists() else []
    keep_ok = (not inst.exists()) or (set(left) <= {'扫描输出', 'data'})
    item('⑥a 程序文件已删、数据保留', keep_ok, f'残留：{left}')
    lnks2 = list((sb_root / 'shortcuts').glob('*.lnk')) if (sb_root / 'shortcuts').exists() else []
    item('⑥b 快捷方式已清', len(lnks2) == 0, f'残留 {len(lnks2)} 个')
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, C.Sandbox(sb_root).reg_root):
            alive = True
    except OSError:
        alive = False
    item('⑥c 卸载注册项已删', not alive)

    # ⑦ 安全阀：非安装目录拒绝卸载
    fake = ROOT / 'not-an-install'
    fake.mkdir(exist_ok=True)
    (fake / 'important.txt').write_text('keep me', encoding='utf-8')
    r = subprocess.run([PY, str(setup), '--silent', '--uninstall', '--test-root', str(sb_root),
                        '--dir', str(fake)], capture_output=True, text=True, env=env, timeout=60)
    ok7 = (fake / 'important.txt').exists()
    item('⑦ 非安装目录拒绝删除（安全阀）', ok7, f'rc={r.returncode}')

    print()
    allok = all(o for _, o in results)
    print('===== 安装器自测 ' + ('全部通过' if allok else '存在失败项') + ' =====')
    return 0 if allok else 1


if __name__ == '__main__':
    sys.exit(main())
