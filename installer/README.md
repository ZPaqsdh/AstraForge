# AstraForge 星铸 · 安装器（TODO-003 实现说明）

> 2026-10-16 深夜首版；**2026-10-17 修包结构与卸载器可见性**（发布包摊平 + 卸载器落安装目录根）。
> UI = 已定稿的 `installer/drafts/`（安装器 v3 七页 / 卸载器 v1 四状态），
> **草稿本体不改**，由 `build_ui.py` 在末尾注入 `ui/bridge.js` 变成真实程序。

## 组成

```
installer/
├── setup_main.py        ← 入口：PySide6 无边框窗口 + QtWebEngine 载 UI + QWebChannel 桥
├── setup_core.py        ← 全部逻辑（环境检测/安装/卸载/快捷方式/注册表/安全阀），纯标准库
├── ui/
│   ├── bridge.js        ← JS↔Python 桥 + 把"演示行为"换成真实行为（注入用）
│   ├── installer.html   ← 生成物（草稿 + 桥注入）
│   └── uninstaller.html ← 生成物
├── build_ui.py          ← 草稿 → ui/*.html（改 UI 只改草稿，然后重跑本脚本）
├── build_release.py     ← 打发布包：PyInstaller 出 exe（运行时目录 --contents-directory=_setup_internal）→ 摊平 → 压缩 payload.zip
├── selftest_core.py     ← 沙箱自测（不碰真实系统：注册表走测试键、快捷方式/目录在测试根下）
├── AstraForge.iss       ← 早期 Inno 方案（已弃用，留档）
└── 许可与免责声明.txt
```

## 身份与用法

| 命令 | 身份 |
|---|---|
| `AstraForge-Setup.exe` | 安装向导（七页：准备/自定义/许可/已安装/进度/失败/完成） |
| `AstraForge-Setup.exe --uninstall` | 卸载器（四状态：主页/确认/进度/完成） |
| `--silent [--dir <路径>]` | 静默安装（脚本部署） |
| `--silent --uninstall [--dir <路径>]` | 静默卸载 |
| `--test-root <目录>` | 沙箱：注册表/快捷方式/数据全落到测试位置 |
| `--snap <png> --snap-delay N` | 自检截图（与应用同一套做法） |

## 设计要点（为什么这么做）

1. **免管理员优先**：默认装到 `%LOCALAPPDATA%\Programs\AstraForge`；只在用户主动选
   `C:\Program Files\...` 时才需要 UAC。注册表只写 **HKCU**（"设置→应用"里能看见、能卸）。
2. **载荷外置**：`payload.zip` 与安装器同目录，安装时解压 → 改应用只需换 zip，不必重打安装器。
3. **卸载器 = 安装器自己（改名副本）**：`payload` 里放 `AstraForge-卸载.exe` + `_setup_internal/`
   （安装器 exe 与运行时副本），落在**安装目录根** → 用户打开安装目录就能看到卸载器；
   注册表 `UninstallString`、开始菜单「卸载」入口都指向它。同一 exe 双身份：
   `--uninstall` 或文件名含"卸载"（双击）即进卸载界面。卸载退出后由延迟清理
   删除自己与运行时（Windows 删不了运行中的文件）。代价：安装目录多约一份安装器体积。
4. **快捷方式走 PowerShell(WScript.Shell) + 读回校验**：
   原先用 pywin32 直连 COM，在受限环境里 `Save()` 会失败（实测 0x80004005）；
   现在统一用命令行生成并**读回目标校验**，失败就如实返回 False（不留"点了没反应"的图标）。
   注：曾试过"纯 Python 写 ShellLink"，实测 Windows 解析不正确（会落到父目录），已弃。
5. **安全阀**：卸载前校验目标目录确实像 AstraForge 安装（含 `AstraForge.exe` 或 `install.json`），
   否则拒绝删除；`扫描输出` 与 `data` 默认保留（可选一并删除）。
6. **失败可回滚**：安装中途失败按"已创建清单"逆序清理（快捷方式 + 未完成目录）。
7. **版本三态流转**（10-17 凌晨）：读注册表已装版本与本包版本比对 —— 旧版→「立即更新」、
   同版→「修复安装」、更新版→「降级」提示、记录残留（目录已丢失）→「清理残留并安装」；
   更新前检测 `AstraForge.exe` 是否在运行（tasklist），在运行则弹「关闭并继续」（taskkill 后延时续跑）。
   数据保留口径：`扫描输出` 与 `data` 天然不被 payload 覆盖；`install.json` 记 `updated_from`。
8. **相机与驱动体检**（10-17 凌晨）：启动异步枚举 `USB\VID_2BC5*`（PowerShell Get-PnpDevice，只读）——
   深度相机驱动绑定判定：`WinUSB`=就绪；`obdrv*`=与 astra_raw 互斥需切换；无驱动=需安装；
   彩色 UVC 免管。中文系统输出按 UTF-8→GBK 双重解码。
   ⚠️ 实现坑：检测在**子线程**跑，结果必须经 Qt 信号回主线程再送 JS ——**不能**在子线程直接
   `runJavaScript`（实测整个进程静默崩、rc=3，无任何 Python 堆栈）。

## 自测（不污染真实系统）

```bash
python installer/selftest_core.py          # 沙箱：装→升级→卸→残留→安全阀
python installer/build_ui.py               # 改了草稿后重新生成 UI
python installer/build_release.py 0.2.10   # 出发布包
```

## 已知限制（v1）

- 卸载器与安装器共用一套 QtWebEngine 运行时 → 安装目录多占约 0.4GB（v2 可换轻量原生界面）。
- 安装过程不做数字签名/校验（内部使用没问题；对外发布前应加 SignPath/自签 + SHA256 校验）。

## 修订记录

- **2026-10-17 上午（v2 第二批：P4 驱动向导）**：随包 **Zadig 2.9**（`driver/zadig.exe` + 来源/许可/SHA-256 说明，
  来源 = libwdi v1.5.1 官方 release）；体检卡在"驱动不兼容/无驱动"时出现「打开驱动处理向导」→ 三步图文 +
  [打开 Zadig 工具]（`setup_core.driver_tool_path` 定位随包素材）+ [重新检测]。发布包根与安装目录各放一份
  `驱动工具/`。另加 `--snap-js`（自检：截图前注入 JS，UI 弹层可回归）。**驱动切换的可回滚演练仍待做**
  （需相机空档 + 人在场）。加固：**解压失败自动重试**（`_extract_retry`）——覆盖升级时杀软/索引器
  可能正在扫描刚写入的大文件（实测 E2E 升级用例偶发一次 `cv2.pyd Permission denied`），重试数轮即过。
- **2026-10-17 凌晨（v2 第一批：P1+P2+P3）**：
  P1 断线清理——删「示例扫描数据/任务栏」占位；「创建桌面快捷方式 / 开机自启」从完成页
  迁到安装前（自定义页）并接线（此前永远勾不到）；「USB 驱动素材」占位并入后续驱动向导。
  P2 已安装三态（更新/修复/降级/残留清理）+ 运行前「软件运行中」拦截 + **失败页接通**
  （此前安装失败也会显示"安装完成"）。
  P3 相机/驱动体检（只读，含「重新检测」）。`build_ui.py` 防重注判定改为只认注入标记
  （此前草稿注释里出现"bridge.js"字样会被误判"已注入"而跳过）。
- **2026-10-17**：发布包摊平——入口 `AstraForge-安装.exe` 与 `_setup_internal/` 同级
  （此前嵌套布局导致双击报 "Failed to load Python DLL ... _internal ..."，PyInstaller onedir 硬规则）；
  卸载器改落安装目录根 `AstraForge-卸载.exe`；开始菜单加「卸载」入口；
  卸载后延迟清理（ping 延迟 + `del`/`rd`）自删 exe 与被锁的运行时目录。
- `--silent` 下不弹 UAC：装到 Program Files 会因权限失败并明确报错（提示改用默认目录）。
