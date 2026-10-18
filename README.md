# AstraForge 星铸

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-0078D6.svg)](#)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB.svg)](requirements.txt)
[![Version](https://img.shields.io/badge/version-v0.2.10-2ea44f.svg)](CHANGELOG.md)
[![CI](https://github.com/ZPaqsdh/AstraForge/actions/workflows/ci.yml/badge.svg)](https://github.com/ZPaqsdh/AstraForge/actions/workflows/ci.yml)

**Orbbec Astra 深度相机 3D 扫描工作站**（Windows 桌面应用）
—— 实时预览 / 点云导出 / 转台多帧融合 / 3D 查看 / 测距 / 模块化热更新。

面向 **Astra S Pro**（USB `2BC5:0403` 深度 + `2BC5:0501` UVC 彩色）实测开发；
老 Astra 系同栈设备理论上兼容（见「设备支持」）。

[功能](#功能) · [设备支持](#设备支持) · [快速开始](#快速开始) · [架构](#架构) · [测试](#测试) · [已知限制](#已知限制) · [贡献](#贡献)

> 本项目为社区实现，与 Orbbec 无隶属关系。`Orbbec`、`Astra` 为其各自所有者的商标。

---

## 功能

| 模块 | 能力 |
|---|---|
| 采集 | RGB + 深度双画面、悬停测距、灰度/暂停、快照、点云导出、连续采集 |
| 采集质量 | 距离条三段色（近/最佳/远）、状态灯、6×8 覆盖质量色谱叠加 |
| 转台 | 串口控制器（WHO 握手 / ROT→READY）、自动扫描、多帧采集 |
| 融合 | 多帧点云融合 → 体素降采样 / ICP / 柱面展开 / 网格 → PLY / STL |
| 3D | 实时点云、ICP 记录、前/侧/俯三视图导出 |
| 测量 | 深度画布两点 3D 测距 |
| 标定 | S2D / 内参标定读写，热更新下发 |
| 设置 | 显示范围、RGB 曝光、分辨率、镜像、性能模式（重启还原） |
| 更新 | GitHub OTA：检查 / 下载 / SHA256 / 备份 / 热替换 / 回滚 |

## 设备支持

| 设备 | 状态 |
|---|---|
| **ASTRA S Pro**（`2BC5:0403` + UVC `0501`） | ✅ 全链路实测（Windows 10/11 x64） |
| Astra / Astra S / Astra Pro（同为 `0403`） | 🟡 同栈候选，未实测；标定与镜头差异需现场核 |
| Astra Mini / Mini S（`0404` / `0407`） | ⛔ 需新增 USB 后端（规划） |
| Astra 2 / Gemini / Dabai / Femto 等新一代 | ⛔ 协议栈不同，不适用 |

**驱动要求（重要）**：深度相机必须绑定 **WinUSB**（libusb 才能访问）。
若装过 Orbbec 官方 OpenNI 驱动（obdrv4），两者互斥，需要切换。
仓库不携带内核驱动；安装器会检测并在冲突时引导使用 [Zadig](https://zadig.akeo.ie/)（GPLv3，`installer/driver/` 自行放置，见该目录 README）。

## 下载

安装包与载荷发布在 [Releases](https://github.com/ZPaqsdh/AstraForge/releases)：

| 包 | 适用场景 | 说明 |
|---|---|---|
| `AstraForge-Setup-Online-v*.exe` | 有网络 | 单文件在线安装器，安装时拉取最新载荷 |
| `AstraForge-Setup-Offline-v*.exe` | 离线 / 内网 | 单文件完整包，自带本版本全部载荷 |

> 安装包约 259 MB（Online）/ 601 MB（Offline），均为单 exe，不依赖外挂文件。
> 首次启动需自解压 20–40 秒。安装后可获得启动器 `AstraForge.exe` 与卸载器。

## 快速开始（源码）

```bat
git clone https://github.com/ZPaqsdh/AstraForge.git
cd AstraForge

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python shell.py
```

- 环境：Windows 10/11 x64 · Python 3.10+（实测 3.14）· 相机独占（同一时间只能一个进程打开）
- 只开界面不连设备：`python shell.py --no-pipeline`
- 原生截图自检：`python shell.py --snap out.png`
- 经典 tkinter 版（保留）：`python main.py`

`ui-web/dist/` 已随仓库提供，**不装 Node 也能直接运行**。

## 构建

### 前端（修改 UI 时）

```bat
cd ui-web
npm install
npm run build        :: 输出到 ui-web/dist，被 shell.py 直接托管
```

### 单文件/目录版 exe

```bat
python build_exe.py
```

### 安装包

```bat
:: 先把 zadig.exe 放到 installer/driver/（不入库，见该目录 README）
python installer/build_release.py 0.2.10
```

产物：`发行/安装器/AstraForge-Setup-v0.2.10/`（入口 exe + 运行时 + `payload.zip`）。
安装器核心自测：`python installer/selftest_core.py`（沙箱，不触碰真实系统）。

## 架构

```
core/                 稳定层（契约 / 事件 / 管线 / 点云数学 / 主题 / 设置）
  contracts.py        DepthFrame / RgbFrame / PointCloud / Module 协议
  events.py           线程安全事件总线
  pipeline.py         importlib 外置加载 + 依赖拓扑装配
  cloudmath.py        反投影 / 体素 / ICP / 柱面 / PLY / STL；相机内参唯一源
  theme.py            主题色板 + 深度 LUT
  appsettings.py      设置持久化（原子写）

modules/              功能模块（目录 + module.json + module.py，可热替换）
  device  preview  recorder  fusion  viewer3d
  calib   measure  settings  updater  _smoke

shell.py              入口：本地 HTTP（UI + API）+ QtWebEngine 内置窗口 + 心跳收尾
main.py               经典 tkinter 入口（保留）
launcher.py           exe 引导器（PyInstaller 目标，跑外置 code/shell.py）
ui-web/               React 19 + Vite + Tailwind（src 源码 + dist 构建产物）
installer/            自研安装器（PySide6 + QtWebEngine + QWebChannel）
tests/                probe28~70 真机/离线验证探针
manifest.json         版本清单（OTA 比对源）
vendor/               随仓库提供的 astra_raw wheel
```

### 模块开发约定

1. 模块 = 目录 + `module.json`（name/version/entry/depends_on）+ `module.py`
2. 实现 `setup/start/stop`；只 import `core.*`，**禁止 import 其他模块**
3. 数据走事件总线（topic 见 `core/events.py`）或模块公开 API
4. 版本语义化；改动即升版本 —— OTA 按版本比对热替换该目录

### 实现要点

- **设备生命周期**：窗口关闭（心跳断）→ 停深度流 → 关激光 → 释放 USB；
  协议关闭失败走 USB reset 物理兜底
- **帧流**：服务端渲染 JPEG（渲染互斥合并 + 150ms 缓存 + 深度降采样 0.75x），
  前端链式加载（上一帧 onLoad 后再拉下一帧），窗口最小化自动暂停
- **内参唯一源**：`core/cloudmath.py` 的 `FX/FY/CX/CY` = 出厂标定
  （580.703 / 318.163 / 249.847，闪存 0x70000 实读）。
  反投影一律走 `cxcy_for_shape(shape, col0=...)`，不得硬编码主点
- **深度裁剪**：输出帧有垃圾带 + 幻影列，保存/导出/融合统一走
  `crop_for_output`；裁剪必须同步裁剪内参
- **融合并行**：标准/性能 = 核数−1，狂暴 = 全核（免责确认）

## 测试

`tests/` 下 45 个探针，文件头部写明验证项与预期。示例：

```bat
python tests/probe63_engine_intrinsics.py      :: 出厂内参（离线）
python tests/probe64_quality.py                :: 采集质量（离线）
python tests/probe60_principal_point.py        :: 主点补偿（离线）
python tests/probe58_ship_accept.py            :: 发行态验收（需真机）
```

**注意**：相机独占，跑探针前先关闭 AstraForge；探针结束会 `stop_all()` 关激光、释放设备。

## 已知限制

- **深度原始值是视差域，不是毫米**（BUG-017，阻塞级）：
  正确换算 `z_mm = A / (C − s)`，`A = 342098.34` 已从闪存读出，
  `C` 需一次已知距离标定后接入。**修复前绝对尺度不可信**（相对形状基本正确）。
  详见 `CHANGELOG.md`。
- 彩色-深度对齐（D2C）未实现：Astra Pro 的彩色是独立 UVC，只能软件重投影
- Astra Mini 系列尚未适配
- 仅 Windows（依赖 WinUSB / QtWebEngine / 串口）

## 贡献

欢迎提交 Issue 与 PR：

- 开始前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)（开发约定 / 提交规范 / 测试要求）
- 参与即表示同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 安全漏洞请走 [SECURITY.md](SECURITY.md) 的私密通道，不要公开提 Issue

## 第三方与许可

- 本项目：**Apache License 2.0**（见 `LICENSE`）
- `vendor/orbbec_astra_raw-0.2.2-py3-none-any.whl`：社区 USB 协议封装（随包分发）
- [Zadig](https://zadig.akeo.ie/)（libwdi，GPLv3）：仅作为驱动切换工具，**不随仓库分发**，
  `installer/driver/` 提供下载与放置说明
- Qt / PySide6（LGPL）、React（MIT）、Tailwind（MIT）等遵循各自许可

## 免责声明

本软件按「现状」提供，不附带任何担保。深度相机含 **Class 1 激光**，
请勿直视或改装光路；使用本软件造成的设备损坏、数据丢失或人身伤害，作者不承担责任。
