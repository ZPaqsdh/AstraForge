# 贡献指南

感谢你愿意改进 AstraForge 星铸。本文说明本地开发、提交与合并的基本约定，目标是让改动**可复现、可验证、可回滚**。

## 一、开始之前

- 平台：Windows 10/11 x64（本项目强依赖 WinUSB、QtWebEngine 与串口）
- Python 3.10+（实测 3.13 / 3.14）
- 一台 Astra 系深度相机（非必需，但涉及采集、标定、D2C 的改动必须真机验证）

```bat
git clone https://github.com/ZPaqsdh/AstraForge.git
cd AstraForge
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python shell.py            :: 或在无设备时 python shell.py --no-pipeline
```

前端源码在 `ui-web/`，`ui-web/dist/` 已入库，改前端后需重新构建：

```bat
cd ui-web
npm install
npm run build
```

## 二、代码约定

### 分层

- `core/` 是稳定层：契约、事件总线、管线、点云数学、主题、设置。**接口改动需谨慎**，一旦发布，OTA 不会替换该层。
- `modules/` 是可热替换的功能模块：目录 + `module.json` + `module.py`。
- `shell.py` 只做装配与本地 HTTP 服务，不承载业务算法。

### 模块规则

1. 实现 `setup / start / stop` 生命周期。
2. **只允许 import `core.*`**，禁止模块之间横向 import；跨模块协作走事件总线或公开 API。
3. 通过 `module.json` 声明 `name / version / entry / depends_on`，改代码即升版本。
4. 新增事件 topic 统一登记在 `core/events.py`。

### 几何与深度

- 相机内参唯一源是 `core/cloudmath.py` 的 `FX / FY / CX / CY`，反投影必须走 `cxcy_for_shape()`，**不允许在别处硬编码主点**。
- 输出帧（保存 / 导出 / 融合）统一走 `crop_for_output()`，裁剪时必须同步裁剪内参。
- 深度原始值是视差域（见 README「已知限制」），任何尺度换算集中在一处，禁止散落魔法系数。

### 风格

- Python 4 空格缩进；前端 2 空格。
- 命名清晰优先于简短；公开函数写类型标注。
- 不提交调试用的 `print` 洪水、临时路径、真实设备序列号。
- 注释解释「为什么」，不复述「做了什么」。

## 三、提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/)：

```
<type>(<scope>): <subject>

<body 可选>
```

常用 type：`feat` / `fix` / `docs` / `refactor` / `perf` / `test` / `build` / `chore`。
scope 例：`device`、`fusion`、`installer`、`ui`、`core`。

示例：

```
fix(installer): 在线包解压遇到文件占用时重试
feat(quality): 采集质量面板增加覆盖色谱叠加
```

一次提交只做一件事；格式化改动与逻辑改动分开。

## 四、测试与验证

- 纯逻辑改动：至少跑相关 `tests/probeXX_*.py`，并在 PR 中贴命令与结果。
- 涉及真机：先关闭其他占用相机的程序（**相机独占**），跑完探针会 `stop_all()` 关激光并释放设备。
- 安装器改动：`python installer/selftest_core.py`（沙箱）＋ `python _tools/installer_v4_e2e.py <产物目录>`（在线装→卸 / 离线装→卸）。
- 新增修复建议附一个最小复现探针，编号顺延 `tests/probeNN_*.py`，文件头写「验证项 / 预期」。

## 五、Pull Request

1. Fork 并从 `main` 切分支：`fix/xxx`、`feat/xxx`。
2. 填写 PR 模板：变更说明、验证方式、影响范围。
3. 确保 CI（语法检查）通过。
4. 涉及用户可见行为的改动，同步更新 `README.md` / `CHANGELOG.md`。
5. 维护者可能会要求补测试或拆分提交；合并方式以 squash 为主。

## 六、报告问题

- 缺陷与需求请使用 Issue 模板，附版本、系统、设备 PID、驱动状态（WinUSB / obdrv）与日志。
- 安全相关问题**不要**公开提 Issue，见 [SECURITY.md](SECURITY.md)。

## 七、许可

提交即表示你同意以 [Apache License 2.0](LICENSE) 授权你的贡献，并确认拥有相应权利。
