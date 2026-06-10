# Birth Flower MVP

## 当前版本说明

- 主界面采用经典菜单栏：`文件 / 编辑 / 查看 / 帮助`。
- `文件 -> 设置...` 用于配置素材库、字体库、输出设置、AI 识别。
- 主界面采用 2 栏生产工作台：左侧实时画板，右侧功能区；底部保留生产输出栏；右侧底部新增 Photoshop 风格图层面板。
- 功能区保留高频动作：订单备注、导入、解析、素材/字体选择、人工确认生成；原常驻“布局参数”已移到 `编辑 -> 布局设置...`，释放右侧面板空间。
- `文件 -> 导入 -> 导入素材...` 会按选中文件后缀识别导入类型：TTF/OTF 导入为当前字体，SVG/PNG/JPG/JPEG/WEBP/BMP 会追加为新的 ImageLayer，不会覆盖已有素材图层。
- 素材扫描会生成通用 `asset_key` 和展示名，可按素材文件名匹配，不再只依赖固定月份与 `flower 1-2`。
- 实时画板使用多图层 Document 作为唯一画布数据源，并使用 SVG 预览缓存；素材文件和布局未变化时不会重复解析 SVG。
- `文件 -> 设置... -> 输出设置` 可配置输出格式、输出路径和输出分辨率（画布宽/画布高）；`编辑 -> 布局设置...` 可配置 flower/text 的全局默认位置和尺寸。
- 输出支持勾选 `PNG`、`SVG`、`DXF`，默认建议使用 `SVG` + `DXF`；当画布存在多图层 Document 时 PNG/SVG 会按图层顺序合成导出，位图素材导出 SVG 时会以图片嵌入并标注不是纯矢量，DXF 暂沿用旧版单设计导出且仅支持纯矢量 SVG 素材。
- Font 2 / Font 4 支持结尾字形映射；字形面板支持按文字位置手动绑定 glyph，预览和最终导出都会从原始 Personalization 重新计算 `render_text`。
- 所有最终文件仍必须点击 `人工确认并生成` 后才会输出，解析结果不会自动生成文件。


## 多图层文档模式

当前应用已从“单素材 + 单次绘制”升级为多图层 Document：

- `Document` 保存画布宽高、`layers` 和 `selected_layer_id`。
- `ImageLayer` 用于 PNG/JPG/SVG 素材；每次点击“添加素材为新图层”都会 append 一个新图层，并把当时的全局默认布局复制到该图层自己的 `x/y/width/height`。
- `TextLayer` 用于可编辑文本框；点击“添加文本”后文字、字体、字号、颜色、对齐、行距、字距和文本框尺寸都会保存在图层上，后续修改会重新渲染，不会画死到背景。
- `GlyphLayer` 已预留给未来 PUA 字形或装饰字形工作流。
- 图层面板可选择图层、显示/隐藏、锁定/解锁、删除、上移、下移、置顶、置底；右键素材图层或双击素材图层可打开“编辑素材...”，实时修改该图层名称、素材标识、位置、尺寸、锁定宽高比和锁定状态。锁定图层不可拖动、缩放或删除，素材编辑窗口也会禁用位置和尺寸输入。
- 画布点击会从顶层向底层做 hit test；拖拽只移动当前选中图层，右下角控制点支持基础缩放，Delete/Backspace 可删除当前未锁定图层，方向键可微调位置。
- Ctrl+Z / Ctrl+Y 已预留 HistoryManager 接入口，当前版本会提示历史功能待启用。
- PNG 导出按图层顺序合成所有可见图层；SVG 导出会尽量保留 SVG 图层引用和文本结构。复杂旋转文字、字距和部分 SVG transform 仍在代码中标注 TODO，生产准确性以 PNG 导出为准。
- 文本预览和 PNG 渲染使用 Pillow 的 ink bounding box 做真实视觉居中；复杂文字排版仍可能受 RAQM 支持影响。

### 全局布局默认值与图层独立编辑

- 全局布局默认值位于 `编辑 -> 布局设置...`，对话框提供“保存 / 应用 / 取消 / 恢复默认值”。
- 全局默认值只用于之后新增的素材图层和文本图层；保存或应用全局布局不会遍历覆盖已有图层的 `x/y/width/height`。
- 每个素材图层保存自己的 `layer.x`、`layer.y`、`layer.width`、`layer.height`、`material_id`、`material_name`、`lock_aspect_ratio` 和 `locked`。
- “编辑素材...”窗口中的位置和尺寸字段会实时刷新画布；点击“取消”会恢复打开窗口前的图层快照。

## AI 识别设置

程序支持在 `文件 -> 设置... -> AI 识别` 中配置 OpenAI 或 DeepSeek 解析。

- 默认仍读取 PowerShell 环境变量 `OPENAI_API_KEY`。
- UI 可以临时输入 API Key，但只在本次程序运行期间生效，不会写入 `birth_flower_config.json`。
- 配置文件只保存服务商、模型名、Base URL、环境变量名、Project/Org 环境变量名等非敏感字段。
- 程序默认先用本地规则解析；本地规则已经完整识别时不会调用 GPT。
- 未配置 API Key 时，程序会跳过 GPT 兜底解析。
- GPT 失败时不会自动生成最终文件。
- DeepSeek 使用 OpenAI 兼容的 Chat Completions，默认 Base URL 为 `https://api.deepseek.com`，默认模型为 `deepseek-v4-flash`，并关闭 thinking 以优先测试响应速度。

PowerShell 示例：

```powershell
$env:OPENAI_API_KEY="你的 OpenAI API Key"
$env:OPENAI_MODEL="gpt-5-nano"
$env:OPENAI_PROJECT="proj_xxx"
$env:OPENAI_ORG_ID="org_xxx"
.\.venv\bin\python.exe birth_flower_mvp.py
```

DeepSeek 速度/准确率测试示例：

```powershell
$env:DEEPSEEK_API_KEY="你的 DeepSeek API Key"
$env:DEEPSEEK_MODEL="deepseek-v4-flash"
$env:DEEPSEEK_BASE_URL="https://api.deepseek.com"
.\.venv\bin\python.exe birth_flower_mvp.py
```

启动后进入 `文件 -> 设置... -> AI 识别`：

- 勾选 `优先使用 AI 解析`
- `服务商` 选择 `deepseek`
- `模型` 使用 `deepseek-v4-flash`
- `Base URL` 使用 `https://api.deepseek.com`
- `API Key 环境变量` 使用 `DEEPSEEK_API_KEY`，或只在 `临时 API Key` 中输入本次测试用 Key
- 点击 `测试连接`

如果你的虚拟环境是 Windows 标准目录，也可以使用：

```powershell
.\.venv\Scripts\python.exe birth_flower_mvp.py
```

本地桌面 MVP：根据订单备注解析姓名、月份、font、flower，人工确认后生成 Birth Flower SVG。

## 功能范围

- 支持英文、中文、泰语、越南语、印尼语月份识别。
- 支持 Unicode 数字归一化，例如全角数字、泰语数字、阿拉伯数字。
- 支持 `font 1-4`、`flower 1-2` 识别。
- 支持按花名识别 `flower 1-2`，例如 `Cherry Blossom` 会匹配 3 月第 2 朵，`Daisy` 会匹配 4 月第 1 朵。
- 支持 `Name`、`Text`、`姓名`、`ชื่อ`、`tên`、`nama` 字段提取文字。
- 解析结果带 `warnings` 和 `confidence`。
- UI 会显示解析结果和 warnings，用户可手工修改。
- UI 支持从 `.txt`、`.json`、`.csv` 导入订单备注；后续店小秘 API 可接入同一导入层。
- UI 只有一个 `解析备注` 按钮；默认先用本地规则解析，本地结果不完整时才调用 GPT 兜底，本地和 GPT 都失败才提示无法解析。
- UI 可选择花朵 SVG 目录，并按月份显示 `flower 1-2` 对应素材。
- UI 可选择单个字体文件，也可选择字体目录，后期可扩展到 3-8 种字体。
- UI 会保存上次选择的花朵目录、字体源和输出路径到 `birth_flower_config.json`。
- UI 有实时画板，会渲染当前花朵 SVG 轮廓和文字预览；点击花朵或文字后显示虚线选择框，可拖动、缩放或用 Delete/Backspace 清除选中内容。
- 花朵素材会按布局参数中的花宽/花高形成方框，素材本体在方框内等比居中适配，直到宽或高触达方框边界；实时画板、SVG、DXF 使用同一套缩放规则。
- `文件 -> 设置... -> 输出设置` 可设置画布宽高；例如设置为 `1372 x 1280` 时，最终导出的 SVG/DXF/PNG 都使用同一画布比例。
- 右侧 `布局参数` 可设置字宽/字高；单行姓名会按真实墨迹 bbox 非等比铺满该方框，使文字墨迹上下左右贴合边框，字号由方框自动推导，主界面暂不显示独立字号输入。
- 主界面素材与字体区只保留下拉选择；导入新素材或字体统一通过 `文件 -> 导入 -> 导入素材...` 完成。
- 双击画布内已有文字会进入画布覆盖式 inline text editing：编辑器贴近当前 TextLayer 边界框，输入内容会实时写回该图层并仅重绘预览；Enter / Ctrl+Enter / 点击画布提交，Esc 取消并恢复编辑前文本，不会新增文本图层。
- 人工确认字段中的 `内容` 支持 `区分大小写` 勾选；取消勾选时最终预览和导出统一转为小写。
- `编辑 -> 字形...` 会集中显示字形状态、识别字母、字形码位、应用方式和人工确认提醒。
- 最终文件只会在用户点击“人工确认并生成 SVG+DXF”后生成。

## 安装与运行

```powershell
python -m venv .venv
.\.venv\bin\python.exe -m pip install -r requirements.txt
.\.venv\bin\python.exe birth_flower_mvp.py
```

字形面板启动时会检测当前应用进程的 Python 环境，并在 UI 中显示当前 `sys.executable`、缺失包名和建议安装命令：

```powershell
.\.venv\bin\python.exe -m pip install fonttools pillow freetype-py uharfbuzz svgwrite ezdxf
```

`fonttools` 用于读取 TTF/OTF 的 glyph 表和 Unicode cmap；`Pillow` 用于渲染 Unicode/PUA glyph 缩略图和 PNG 输出；`freetype-py` 用于按 glyph index 渲染没有 Unicode 映射的 glyph。`uharfbuzz`、`svgwrite`、`ezdxf` 先作为后续文字轮廓化和矢量导出的扩展依赖保留。

Windows 直接运行 `birth_flower_mvp.py` 时会经过 Python Launcher；入口文件已使用 `#!/usr/bin/env python`，用于避免系统没有默认 Python 时闪退。

如果你的 Python venv 生成的是 Windows 标准目录，用这个入口：

```powershell
.\.venv\Scripts\python.exe birth_flower_mvp.py
```

如果当前环境是 MSYS/Mingw 风格的 Python 3.14（路径通常是 `.\.venv\bin\python.exe`），`pip install pillow` 可能会从源码编译并要求 zlib headers。此时建议改用标准 Windows Python 创建 `.venv\Scripts` 虚拟环境，或先安装对应编译依赖后再安装 Pillow。


## Windows exe 打包与验收

Windows 可直接双击运行的 exe 需要在 Windows Python 环境中构建；PyInstaller 不支持从当前 Linux/macOS 环境直接交叉编译 Windows exe。推荐流程：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools\build_windows_exe.py
```

脚本会先执行可运行性检查：

- `python -m py_compile` 编译全部源码。
- `pytest -q` 跑完整自动化测试。
- 导入 `tkinter` / `ttk`，确认当前 Python 带有 Tk/Tcl 桌面 UI 支持。
- 调用 `PyInstaller` 根据 `BirthFlowerMVP.spec` 打包。

通过后会生成：

```text
dist\BirthFlowerMVP\BirthFlowerMVP.exe
```

将整个 `dist\BirthFlowerMVP` 文件夹复制到目标 Windows 电脑后，双击 `BirthFlowerMVP.exe` 即可启动。项目不会内置或下载商业字体；用户仍需在设置中选择自己的字体和素材目录。若只想在非 Windows 环境执行编译与测试检查，可运行：

```bash
python tools/build_windows_exe.py --allow-non-windows-checks
```

该模式不会生成 Windows exe，只用于验证当前代码是否能通过基础可运行性检查。

## GPT 兜底解析

设置环境变量后，点击 UI 中的 `解析备注`；只有本地规则无法完整识别时才会请求 GPT：

```powershell
$env:OPENAI_API_KEY="你的 OpenAI API Key"
.\.venv\bin\python.exe birth_flower_mvp.py
```

OpenAI 默认模型为低成本测试用的 `gpt-5-nano`。OpenAI API 没有可绕过账单额度的免费 Responses 模型；如果返回 `insufficient_quota`，需要先处理项目余额/预算。模型可覆盖：

```powershell
$env:OPENAI_MODEL="gpt-5-nano"
```

OpenAI 解析使用 Responses API 的 Structured Outputs；DeepSeek 解析使用 Chat Completions 的 JSON Output。两者最终都会校验固定 JSON 字段：`text`、`month`、`font`、`flower`、`warnings`、`confidence`。解析成功不弹提示；最终生成仍必须人工确认。
API Key 只从 `OPENAI_API_KEY` 环境变量读取，不要写入源码。
DeepSeek API Key 只从 `DEEPSEEK_API_KEY` 环境变量或本次 UI 临时输入读取，不要写入源码。
如果账号有多个项目或组织，可额外设置：

```powershell
$env:OPENAI_PROJECT="proj_xxx"
$env:OPENAI_ORG_ID="org_xxx"
```

如果 OpenAI 返回 429，UI 会显示响应体中的 `type`、`code`、`message` 和 `request_id`，用于区分真实限流、额度不足、项目路由错误。

## 测试

```powershell
.\.venv\bin\python.exe -m pytest
```

## 结尾字形配置

字形配置文件位于 `glyph_maps/glyph_maps.json`。文件不存在时程序会自动创建；JSON 损坏时会备份为 `glyph_maps.json.bak` 并重建默认配置。

默认只启用 `Font 2` 和 `Font 4`，默认应用方式为 `replace_last_letter`：例如 `Jazmin` 会渲染为 `Jazmi + n字形`，不会渲染为 `Jazmin + n字形`。也支持 `append_suffix` 和 `manual_per_character`。

配置 Font 4 的 `n` 字形示例：

```json
{
  "Font 4": {
    "enabled": true,
    "apply_mode": "replace_last_letter",
    "description": "Font 4 ending swash glyphs",
    "letters": {
      "n": { "codepoint": "U+E014", "label": "n ending glyph" }
    }
  }
}
```

也可以在 UI 中维护：

- `编辑 -> 字形...`：打开类似 Photoshop 的字形窗口，选择字体、切换完整字体/PUA 字形网格，并把选中的字形应用到当前订单。

字形窗口支持：

- 真实 glyph 缩略图网格，不再只显示 a-z 文本按钮。
- 搜索字符、glyph name 或 codepoint，例如 `a`、`swash`、`E014`。
- 筛选 `All glyphs`、`Unicode mapped`、`PUA only`、`Unmapped glyphs`。
- 分页加载 glyph，避免大字体一次性渲染导致 UI 卡顿。
- 按文字位置绑定：例如 `Jazmin` 会显示 `[0:J] [1:a] [2:z] [3:m] [4:i] [5:n]`，先点位置，再点 glyph。
- 清除当前字符绑定和清除全部绑定。
- 手动输入 `U+E014` 这类 codepoint，也支持按 a-z 顺序批量粘贴 26 个字形字符。

按位置绑定的内存结构示例：

```python
glyph_overrides = {
    2: {"original_char": "z", "glyph_name": "z.swash", "glyph_id": 184, "codepoint": None},
    5: {"original_char": "n", "glyph_name": "n.alt", "glyph_id": 203, "codepoint": "U+E04A"},
}
```

## 字体目录扫描

`文件 -> 设置... -> 字体库 -> 选择字体` 支持两种来源：

- 选择单个 `.ttf/.otf`：只使用该字体。
- 选择字体目录：扫描目录下所有 `.ttf/.otf`。

本项目内置业务编号规则：

- `Malovely Script` 小文件 = `Font 1`
- `Malovely Script` 大文件 = `Font 2`，标记为 `含字形`
- `AdoraBella` 小文件 = `Font 3`
- `AdoraBella` 大文件 = `Font 4`，标记为 `含字形`

如果 4 个字体放在 `BirthMonth flowers` 目录，进入 `文件 -> 设置... -> 字体库 -> 选择字体`，选择该目录并重新扫描即可。主界面的字体下拉会显示 `Font 2 - Malovely Script - 文件名 - 大小 - 含字形` 这类标签，方便直接选中。

## 说明

- 当前 MVP 使用标准库生成 SVG 和 DXF，不引入复杂依赖。
- 如果选择 `BirthMonth flowers` 里的 SVG，输出会嵌入该 SVG 的矢量内容；不会嵌入 PNG/JPG。
- DXF 会把花朵 SVG path 近似转换为 `POLYLINE`，姓名先用 DXF `TEXT` 实体保留。
- 默认花朵目录：`BirthMonth flowers`。
- 默认字体文件：`Birthmonth_font.ttf`。
- 默认输出文件：程序同目录下的 `outputs/birth_flower.svg`，DXF 会同名输出到同一目录。
- 本地配置文件：`birth_flower_config.json`，已加入 `.gitignore`。
- 参考 `user/1.jpg` 到 `user/5.jpg` 的布局：横向画布，花朵放大为主视觉，姓名位于右下方。
- 实时画板中的花朵和文字只用于预览；右侧布局参数、添加按钮和画板拖拽用于定位和比例调整，预览不会自动生成最终文件。
- PNG 渲染会优先使用用户选择的字体文件；当前环境如果没有可用 Pillow，会给出友好错误。
- 不内置商业字体，不下载字体；SVG 可引用用户选择的本地字体文件，最终显示取决于查看/加工软件是否能访问该字体路径。
- 当前 SVG 的姓名仍是 `<text>`，DXF 的姓名仍是 `TEXT` 实体，都不是字体转曲线。若使用 PUA 字符，输出依赖字体文件和当前环境，换环境或雕刻软件可能显示异常；需要稳定雕刻时，下一轮应增加文字轮廓化。
- 没有 Unicode codepoint 的 unmapped glyph 当前可通过 `freetype-py` 做 PNG 预览；SVG/DXF 会明确标记“可预览但暂不支持导出”，后续应通过 `fontTools` 的 `SVGPathPen` 转 outline，再由 `svgwrite` / `ezdxf` 输出 path、polyline 或 spline。
- 如果后续启用 Pillow PNG 复杂文字排版，需要确认 Pillow RAQM 支持。
- 文件缺失、路径不可写等常见错误会在 UI 中弹窗提示。

## ripgrep

`rg` 是 ripgrep，一个高速搜索工具。Windows 可安装：

```powershell
winget install BurntSushi.ripgrep.MSVC
```

或：

```powershell
choco install ripgrep
```

安装后重开终端即可，不需要本项目额外配置。
## Visual bbox layout

- SVG 素材默认启用 `USE_VISUAL_BBOX_FOR_SVG=True`：预览、SVG viewBox 嵌入和 DXF polyline 映射都会优先使用真实 path/stroke 可见包围盒，而不是原始 viewBox 的透明留白。
- 通用适配函数位于 `visual_layout.py`：`fit_content_bbox_to_target_rect(content_bbox, target_rect, mode="contain", align=(0.5, 0.5))` 会扣除 `content_bbox.x/y` 后再缩放和居中，支持 `contain`、`cover`、`stretch`。
- 文字布局先使用 Pillow `ImageDraw.textbbox()` 获取初始范围，再把文字绘制到透明蒙版并按实际非透明像素计算黑色字形 ink bbox；单行姓名会把该 ink bbox 的四边映射到 `text_width/text_height` 方框四边，预览、SVG、PNG 使用同一裁剪拉伸规则。DXF 仍以 `TEXT` 实体输出，会用文字高度和宽度因子近似该缩放；要做到雕刻软件内绝对一致，需要后续文字转路径。空文本、空格文本和字体加载失败会降级处理，不会让应用崩溃。
- 调试开关为 `renderer.DEBUG_VISUAL_BBOX`，默认关闭。开启后预览会画出 target rect、layout/viewBox bbox、visual/ink bbox，便于排查偏移来源。

## GitHub 低风险仓库

为便于 Web Codex 编辑源码，同时避免上传本地业务素材，仓库默认不跟踪以下文件：

- `BirthMonth flowers/` 中的 SVG 和字体素材
- `user/` 中的参考图、DXF、PSD 等客户/生产素材
- `*.jpg`、`*.png`、`*.psd`、`*.dxf`、`*.ttf`、`*.otf`

源码、测试、README、配置结构和文档仍会上传。缺少私有字体时，相关字体细节测试会自动跳过；运行桌面应用时需要在本地设置窗口重新选择花朵素材目录和字体来源。

## Glyph 应用系统

新版字形系统把字体浏览器扩展为可应用的 Glyph 面板：

- `TextLayer` 同时保存 `original_text`、`render_text` 和 `glyph_overrides`。
  - `original_text` 是订单/用户输入的原始文字，用于 UI 可读展示。
  - `render_text` 由 `original_text + glyph_overrides` 计算得到，用于预览和导出。
  - `glyph_overrides` 按字符 index 保存 base 字符、替换字符、codepoint、glyph name、font id、usage 和 source，便于恢复和重新渲染。
- Glyph 面板支持“推荐字形”和“全部字形”两种模式：
  - 推荐字形只展示当前选中字符的人工绑定、命名字形或明确可归属变体。
  - 无法判断归属的 PUA 字形不会被强行推荐，只在全部字形中显示。
- 用户先选择文本图层中的字符位置，再点击 glyph，即可把该字形应用到当前字符；画布会立即重建 `render_text` 并刷新预览。
- “恢复普通字符”会删除对应 index 的 override，并让 `render_text` 回到 `original_text` 对应字符。
- 如果用户修改了文本内容，当前实现采用稳妥方案：清空该 TextLayer 上已有 glyph overrides，并提示需要重新应用，避免 index 错位后替换到错误字符。

### glyph_bindings.json

人工绑定配置位于 `glyph_maps/glyph_bindings.json`，结构示例：

```json
{
  "fonts": {
    "Font 4": {
      "font_path": "...",
      "bindings": {
        "E123": {
          "base_char": "n",
          "usage": "end",
          "display_name": "n 尾花",
          "glyph_name": "uniE123"
        }
      }
    }
  }
}
```

配置损坏时会自动备份为 `glyph_bindings.broken.YYYYMMDD_HHMMSS.json` 并重建空配置；保存使用临时文件原子替换，避免写入中断造成损坏。

### glyph_rules.json

自动字形规则位于 `glyph_maps/glyph_rules.json`，用于 Font 2 / Font 4 等明确配置过的字体自动替换首尾字符：

```json
{
  "enabled": true,
  "fonts": {
    "Font 4": {
      "end_char_rules": {
        "n": "E123"
      },
      "start_char_rules": {}
    }
  }
}
```

规则只处理明确配置过的 codepoint，不猜测未知字母。用户手动 override 优先级高于自动规则；规则失败只产生 warning，不阻塞订单渲染。

## 批量订单识别预留模型

`order_batch.py` 新增 `ParsedOrderResult`、本地校验和批量渲染报告结构，为后续 AI 一次返回多个订单结果预留接口。AI 结果只作为结构化输入；本地程序继续负责素材匹配、字体校验、自动字形应用和最终渲染。批量渲染时单个订单失败会记录为 `failed`，不会中断其他订单。
