# 把 flower 打包成 macOS .app（GitHub Actions 云端构建）

> **为什么走云端**：macOS 的 `.app` 必须在 macOS 上构建——PyInstaller 不支持跨平台编译，Windows 出不了 `.app`。
> 本仓库用 GitHub 的 macOS runner 自动打包，**你不需要一台 Mac**。

## 怎么触发构建

1. 把本分支（含 `flower-macos.spec`、`pyi_rthook_flower.py`、`.github/workflows/build-macos.yml` 和 4 处源码改动）push 到 GitHub。
2. GitHub → 仓库 → **Actions** → 左侧选 **build-macos** → 右上 **Run workflow**。
   （或推一个 `v*` tag，如 `git tag v1.0.0 && git push --tags`，自动触发。）
3. 等 runner 跑完（约 5–10 分钟），进这次 run 页面 → **Artifacts** → 下载 `BirthFlowerMVP-macos-arm64`（里面是 `BirthFlowerMVP.dmg`）。

## ⚠️ 首次使用必做：放入素材库与字体（云构建空壳模式）

花型设计（`BirthMonth flowers/`）和字体（`Birthmonth_font.ttf`、`Front1-4.ttf`）是**授权商业资产**，被 `.gitignore` 排除、**没有上传到公开仓库**，所以**云端打出的 `.app` 不含它们**。第一次用之前，必须手动把它们放到数据目录：

```bash
# 在 Mac 上，把这两样从你本机的 flower 项目复制进数据目录：
mkdir -p ~/Library/Application\ Support/BirthFlower
cp -R "/路径/到/flower/BirthMonth flowers" ~/Library/Application\ Support/BirthFlower/
cp    "/路径/到/flower/Birthmonth_font.ttf" ~/Library/Application\ Support/BirthFlower/
```

放好后目录应是：
```
~/Library/Application Support/BirthFlower/
├── BirthMonth flowers/   ← 28 个花型 .svg + Front1-4.ttf（你手动放）
├── Birthmonth_font.ttf   ← 默认字体（你手动放）
├── templates/            ← App 首启自动从包内铺好
└── assets/               ← 同上
```
App 启动时会从这里读素材；不放的话 App 能开但**素材库为空**。
（若哪天改走「本地全量构建」把资产随包，则无需此步——App 会自动用包内资产。）

## 怎么在 Mac 上安装/运行

1. 双击 `.dmg`，把 `BirthFlowerMVP.app` 拖进 `Applications`。
2. **先做上面「首次使用必做」那步放素材**（否则素材库空）。
3. **首次打开**：因为这个 `.app` **未做 Apple 签名+公证**，直接双击会被 Gatekeeper 拦（提示「无法打开/已损坏」）。绕过方式（任选其一）：
   - **右键点 App → 打开 → 在弹窗里再点「打开」**（只需第一次）。
   - macOS 15+：双击被拦后 → 系统设置 → 隐私与安全性 → 「仍要打开」。
   - 或终端执行：`xattr -dr com.apple.quarantine /Applications/BirthFlowerMVP.app`
4. 之后正常双击图标即可启动。

## 架构与签名说明

- 产物是 **arm64（Apple Silicon, M 系列）**。Intel Mac 需把 workflow 的 `runs-on` 换成 Intel runner（或加一条 `target_arch='x86_64'` 的并行构建）。当前默认只出 arm64。
- 要做到「拿给别人双击就开、不弹安全警告」，需 **Apple 开发者账号（$99/年）签名 + 公证**。需要的话我再在 workflow 里加 `codesign` + `notarytool` 步骤。

## 运行期数据落在哪

打包后由 `pyi_rthook_flower.py` 注入环境变量 + 首启铺底：

- **资产根** = `~/Library/Application Support/BirthFlower/`（云空壳模式；`FLOWER_PROJECT_ROOT` 指向它）。首启自动把包内 `templates/`、`assets/` 铺进去；你手动放的 `BirthMonth flowers/`、`Birthmonth_font.ttf` 也在这里。
  - （本地全量构建：资产随包时，资产根自动切回 `.app` 内的 `_MEIPASS`，无需手动放。）
- **可写数据**（配置、导出产物、收件夹）也写到该目录（`BIRTHFLOWER_DATA_DIR`）。卸载 App 不会自动删这里。
- `glyph_maps/` 随包在 `.app` 内只读；改字形映射不持久（不崩，首版接受）。

## 已知限制（首版）

- **PNG 预览/栅格化**依赖 `libcairo`，spec 已尝试把 brew 的 `libcairo.2.dylib` 随包；若目标机上仍 `dlopen` 失败，PNG 相关功能优雅降级（不崩，SVG/DXF 导出不受影响）。
- 「修改物理尺寸」会回写 `templates/products/*.json`，在只读的 `.app` 内不持久（重启复位）。首版接受；需持久化可把 templates 也重定向到 `BIRTHFLOWER_DATA_DIR`。
- 未签名（见上）。
