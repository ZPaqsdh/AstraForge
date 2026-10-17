# 驱动工具（Zadig）说明

本目录随安装包分发 **Zadig 2.9**，用于把深度相机的驱动切换为 **WinUSB**（AstraForge 依赖 astra_raw/libusb，
必须绑定 WinUSB 才能访问设备）。

| 项 | 值 |
|---|---|
| 文件 | `zadig.exe` |
| 版本 | 2.9（libwdi v1.5.1 发布） |
| 来源 | https://github.com/pbatard/libwdi/releases/download/v1.5.1/zadig-2.9.exe （官方站点 zadig.akeo.ie 指向的同一地址） |
| 许可 | GPLv3（Zadig / libwdi by Pete Batard；源码见上述仓库） |
| 大小 | 5,334,088 字节 |
| SHA-256 | `4ecaa95df3da3621486a043aef8b3050b8bafe7c901402871e816229ef82039b` |

## 用法（三步）

1. 插好相机（USB 直连）；
2. 打开 `zadig.exe` → Options → List All Devices → 选中 **ASTRA S Pro**（或 Astra）
   → 右侧目标驱动选 **WinUSB** → 点 **Replace Driver**；
3. 回到安装器点「重新检测」，显示「✓ 深度相机：就绪 —— 驱动 WinUSB」即完成。

## 注意

- 官方 Orbbec OpenNI 驱动（obdrv4）与本软件**互斥**：切到 WinUSB 后官方 OpenNI 工具将暂时不可用
  （可随时用同法切回 obdrv4）。
- 彩色相机是标准 UVC，**不要**动它的驱动。
- Zadig 内部会发起 UAC；仅在你确认要对本机相机操作时执行。
