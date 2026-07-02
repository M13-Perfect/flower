# packaging/ — 统一运行时聚合打包层

把 **flower 桌面端**、**Ezcad 扫码导入端**、**inbox-service 后台服务** 聚合成**一个绿色免安装包**：
三端共用同一份 Python 3.12 运行时，双击一个总启动器即可后台拉起服务并打开两个界面。

> 设计与决策详见 `C:\Users\Administrator\.claude\plans\flower-...-wiggly-karp.md`。
> 不合并三个 git 仓库，本目录只是「聚合/打包」层，集中放 dispatcher、launcher、spec、构建脚本、模板与文档。

## 文件

| 文件 | 作用 |
|---|---|
| `app_dispatcher.py` | 统一入口。按 `argv[1]` 分 `launcher`(默认) / `flower` / `ezcad` / `serve` 四角色，各角色以**独立子进程**运行（隔离两个同名 `app` 包、CustomTkinter 全局主题、Tk root）。 |
| `launcher.py` | 总启动器 UI（CustomTkinter 深色）。算出统一数据根 `DATA_ROOT`、注入环境变量后台拉起 `serve`、轮询 `/healthz` 显示服务状态、两个按钮分别打开「开花桌面」「扫码导入」。 |
| `Workbench.spec` | PyInstaller 统一打包配置，产物 `dist/Workbench/app.exe`（onedir）。 |
| `build_release.ps1` | 一键构建：装依赖 → 跑三端测试 → 构建扩展 → PyInstaller → 组装绿色 zip。 |
| `templates/` | 配置模板（占位路径，门店首启后改）。 |
| `docs/` | 安装与使用、Chrome 扩展安装说明。 |

## Ezcad 源的获取方式（重要）

Ezcad 是**独立 git 仓**（`M13-Perfect/Ezcad2.7.6`，活跃分支 `claude/p0-p1`），代码在本机同级目录
`..\Ezcad2.7.6`。构建/运行时按以下顺序解析 Ezcad 源：

1. 环境变量 `EZCAD_SRC`（若设置）；
2. 否则用同级目录 `<flower 仓父目录>\Ezcad2.7.6`。

> **为何暂不用 git submodule**：当前本机 Ezcad 仓有未提交/未推送的生产改动（退款集成
> `inbox_client.py` 等）。submodule 只能锁远程已提交 commit，会丢掉这批本地代码。
> 待 Ezcad 这批改动提交并推送后，可平滑改为 submodule（`build_release.ps1` 只需把
> 源路径指向 submodule 检出目录，其余不变）。

## 源码模式快速验证（不打包，用 flower 的 .venv-win）

```powershell
# 后台服务
.\.venv-win\Scripts\python.exe packaging\app_dispatcher.py serve
# 开花桌面 / 扫码导入（各自开窗）
.\.venv-win\Scripts\python.exe packaging\app_dispatcher.py flower
.\.venv-win\Scripts\python.exe packaging\app_dispatcher.py ezcad
# 总启动器（默认角色）
.\.venv-win\Scripts\python.exe packaging\app_dispatcher.py
```
