# 驱动库（安装器内置）

安装器从这里读取 `manifest.json`，按设备的 VID/PID 匹配驱动。

| 目录 | 内容 |
|---|---|
| `astra_s_pro/` | ASTRA S Pro（2BC5:0403）WinUSB INF + CAT（libwdi 生成，LGPL） |
| `zadig/` | Zadig 2.9（GPLv3，兜底驱动切换工具） |

新增设备/社区驱动：在 `manifest.json` 的 `drivers` 里加一条（id / match / version / method / files / sha256），
把文件放进对应子目录即可；安装器会按 id+version 做「只升不降」的版本闸门。
