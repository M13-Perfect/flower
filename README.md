# Birth Flower MVP

## 当前版本说明

- 主界面采用经典菜单栏：`文件 / 编辑 / 查看 / 帮助`。
- `文件 -> 设置...` 用于配置素材库、字体库、AI 识别。
- 主界面采用 2 栏生产工作台：左侧实时画板，右侧功能区；底部保留生产输出栏。
- 功能区保留高频动作：订单备注、导入、解析、素材/字体、布局参数、输出格式、人工确认生成。
- 素材扫描会生成通用 `asset_key` 和展示名，可按素材文件名匹配，不再只依赖固定月份与 `flower 1-2`。
- 实时画板使用 SVG 预览缓存；素材文件和布局未变化时不会重复解析 SVG。
- 输出支持勾选 `PNG`、`SVG`、`DXF`，默认建议使用 `SVG` + `DXF`。
- Font 2 / Font 4 支持结尾字形映射；字形面板支持按文字位置手动绑定 glyph，预览和最终导出都会从原始 Personalization 重新计算 `render_text`。
- 所有最终文件仍必须点击 `人工确认并生成` 后才会输出，解析结果不会自动生成文件。

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
- 右侧 `布局参数` 可设置画布宽高；例如设置为 `1372 x 1280` 时，最终导出的 SVG/DXF/PNG 都使用同一画布比例。
- 右侧 `布局参数` 可设置字宽/字高；文字本体会在该方框内等比居中适配，字号由方框自动推导，主界面暂不显示独立字号输入。
- 主界面素材与字体区使用 `添加` 按钮把当前下拉选择放入画板；素材/字体库重新扫描放在设置窗口中。
- 双击画布内文字可直接编辑内容，回车或失焦后实时更新预览。
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
- 文字布局使用 Pillow `ImageDraw.textbbox()` 测量真实 ink bbox，并用二分搜索选择能放入 `text_width/text_height` 的最大字号；空文本、空格文本和字体加载失败会降级处理，不会让应用崩溃。
- 调试开关为 `renderer.DEBUG_VISUAL_BBOX`，默认关闭。开启后预览会画出 target rect、layout/viewBox bbox、visual/ink bbox，便于排查偏移来源。

## GitHub 低风险仓库

为便于 Web Codex 编辑源码，同时避免上传本地业务素材，仓库默认不跟踪以下文件：

- `BirthMonth flowers/` 中的 SVG 和字体素材
- `user/` 中的参考图、DXF、PSD 等客户/生产素材
- `*.jpg`、`*.png`、`*.psd`、`*.dxf`、`*.ttf`、`*.otf`

源码、测试、README、配置结构和文档仍会上传。缺少私有字体时，相关字体细节测试会自动跳过；运行桌面应用时需要在本地设置窗口重新选择花朵素材目录和字体来源。
