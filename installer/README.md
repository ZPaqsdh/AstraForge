# AstraForge 星铸 · 安装器（v4：单文件双形态）

> 2026-10-18 · 按老大定稿：**单 exe、单窗口、零外挂文件、本地优先、可选在线更新、带驱动识别**。
> 安装界面 = `installer/drafts/` 的 HTML 七页（`build_ui.py` 注入 `ui/bridge.js` 变活）。

## 一、产物

| 文件 | 说明 | 体积（实测） |
|---|---|---:|
| `AstraForge-Setup-Online-v0.3.0.exe` | **在线下载器**（主推）：安装时从上游拉最新载荷 | 259 MB |
| `AstraForge-Setup-Offline-v0.3.0.exe` | **离线完整包**：自带 0.3.0 全部载荷 | 600 MB |
| `AstraForge-0.3.0-payload.zip` | 在线安装用的载荷资产（上传 Release，用户无需手动下载） | 344 MB |
| `update.json` | 版本清单模板（填仓库 URL / SHA256 后上传） | <1 KB |

两个安装器都是 **PyInstaller onefile**：运行时、HTML UI、驱动库全在 exe 内，
**不再有 `_setup_internal/`、外置 `payload.zip`**。

## 二、运行逻辑

```
双击安装器
  → onefile 自解压到 %TEMP%\_MEIxxxx（首次 20–40 秒）
  → 单窗口打开（780×600）：环境检测 + 设备/驱动检测 + 版本提示
  → 主按钮「安装」= 装本包版本（离线包直接解压；在线包先下载）
  → 若 update.json 有更高版本：旁边显示「发现新版本 vX [下载并安装]」（可选，不点就装本地）
  → 装完：启动器 AstraForge.exe + 运行时 + code + 轻量卸载器 + 驱动工具
```

- **单窗口**：页面切换、确认框、下载/驱动进度都在同一窗口；不弹第二个应用窗口
- **唯一系统弹窗**：驱动安装的 UAC 提权（Windows 强制）
- **安装器自身不自我更新**：在线版只下载「载荷」，不改自己

## 三、文件结构

```
installer/
├── setup_main.py       入口：PySide6 + QtWebEngine + QWebChannel（安装器）
├── setup_core.py       核心：环境/目录/解压/快捷方式/注册表/在线下载/驱动匹配
├── uninstall_main.py   轻量卸载器（tkinter，onefile ≈ 14 MB）
├── build_ui.py         草稿 + bridge.js → ui/installer.html
├── build_release.py    打 Online / Offline / Uninstaller / payload / update.json
├── ui/
│   ├── installer.html      生成物（勿手改）
│   ├── uninstaller.html    生成物（仅 HTML 卸载器备用）
│   └── bridge.js           JS ↔ Python 接线（真实行为层）
├── drafts/
│   ├── AstraForge安装器_UI草稿_v3.html   ← 设计唯一源
│   └── AstraForge卸载器_UI草稿_v1.html
└── driver/
    ├── pack/
    │   ├── manifest.json          驱动目录（VID/PID → driver id）
    │   ├── astra_s_pro/           WinUSB INF + CAT（libwdi，LGPL）
    │   └── zadig/                 Zadig 2.9（GPLv3，兜底）
    └── zadig.exe                  本地副本（不入库）
```

## 四、在线更新（可选）

`setup_core.DEFAULT_UPDATE_URL` 已填为 Release 恒定入口：

```python
DEFAULT_UPDATE_URL = 'https://github.com/ZPaqsdh/AstraForge/releases/latest/download/update.json'
```

因此 `update.json` 必须作为 **Release 资产**上传（`releases/latest/download/update.json` 始终指向最新版）。
测试时可用 `--update-url <url>` 或环境变量 `AF_UPDATE_URL` 覆盖（支持 `file://`）。

`update.json`：

```json
{
  "app": "AstraForge",
  "latest": "0.3.0",
  "min_installer": "0.3.0",
  "payload_url": "https://github.com/ZPaqsdh/AstraForge/releases/download/v0.3.0/AstraForge-0.3.0-payload.zip",
  "payload_sha256": "…",
  "notes_url": "https://github.com/ZPaqsdh/AstraForge/releases/tag/v0.3.0"
}
```

## 五、驱动库

- 安装器启动时枚举 `USB\VID_2BC5*`，读 PID + 当前驱动 Service
- 按 `manifest.json` 匹配 `driver id`
- **签名 INF**（当前 ASTRA S Pro 0403）：`pnputil /add-driver … /install`（UAC）
- **无签名/社区驱动**：`method: zadig-guided`，窗口内引导
- 彩色 0501：标准 UVC，显示「无需处理」
- 已装驱动 `id + version` 写入 `install.json`；只升不降

新增设备：在 `driver/pack/manifest.json` 加条目 + 放文件即可。

## 六、构建

```bat
python installer/build_ui.py                 :: 生成 ui/installer.html
python installer/build_release.py 0.3.0     :: 打 Online + Offline + 卸载器 + payload
python installer/build_release.py 0.3.0 --only online     :: 只打在线版（调试用）
python installer/build_release.py 0.3.0 --only offline    :: 只打离线版
```

构建时间约 7 分钟（两版 + 载荷）；输出到 `发行/安装器/AstraForge-Setup-v<版本>[-时间戳]/`。

## 七、自测

```bat
python installer/selftest_core.py                          :: 核心逻辑（沙箱）
python _tools/installer_v4_e2e.py <产物目录>               :: 在线装→卸 + 离线装→卸
python _tools/_dragtest.py <安装器.exe>                    :: 窗口拖动（注入位移）
```

## 八、已知限制

- **单文件启动慢**：每次双击都要自解压 ~260 MB（在线）/ ~600 MB（离线），首次 20–40 秒；后续可做「解压缓存」优化
- 安装器运行时包含 QtWebEngine（约 260 MB 压缩后）；若要几十 MB 级下载器，需换 WebView2/原生界面（B 案）
- 驱动自动安装仅覆盖「签名 INF」；无签名驱动需要 Zadig 引导（会打开第三方小窗口）
- 在线模式需要网络；断网时请使用离线完整包
