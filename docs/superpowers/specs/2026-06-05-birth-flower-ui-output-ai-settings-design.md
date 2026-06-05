# Birth Flower MVP UI、输出与 AI 设置优化设计

## 结论

采用 A2 方案：经典菜单栏 + 设置弹窗 + 画板优先。

主界面只保留高频生产动作：订单备注输入、导入、解析、实时画板、布局参数、输出格式勾选、人工确认生成。低频配置全部移入 `文件 -> 设置...`。当前设置页实现素材库、字体库、AI 识别；后续可以扩展输出模板、默认布局、快捷键、帮助等分类。

## 当前依据

- `ui_app.py` 当前使用 Tkinter 单窗体，天然支持 `Menu`、`Toplevel`、`ttk.Notebook` 等经典桌面控件，不需要更换 UI 框架。
- `asset_resolver.py` 已有素材和字体扫描函数，适合迁入设置弹窗。
- `config_store.py` 当前保存素材目录、字体源、输出路径，可以扩展非敏感 AI 配置。
- `gpt_parser.py` 已支持 `api_key`、`model` 参数，默认从环境变量读取 `OPENAI_API_KEY`、`OPENAI_MODEL`，项目和组织从 `OPENAI_PROJECT`、`OPENAI_ORG_ID` 读取。
- `renderer.py` 已有 `render_svg`、`render_dxf`、`render_png`，UI 只缺少输出格式选择和路径分派。

## UI 架构

### 菜单栏

顶部菜单使用经典桌面结构：

- `文件`
  - `导入备注...`
  - `打开输出目录`
  - `设置...`
  - `退出`
- `编辑`
  - 预留，不在本轮实现具体功能。
- `查看`
  - 预留，不在本轮实现具体功能。
- `帮助`
  - 预留，不在本轮实现具体功能。

本轮必须实现 `文件 -> 设置...`。`导入备注...` 可以与主界面的导入按钮共用同一个函数。

### 主界面

主界面布局从上到下：

1. 菜单栏。
2. 订单备注行：左侧是备注输入框，右侧是 `导入`、`解析` 按钮。
3. 解析结果简区：显示并可编辑 `备注信息`、`素材名`、`字体类型`。
4. 实时画板区：画板占主空间；右侧窄栏放布局数值。
5. 输出区：`PNG`、`SVG`、`DXF` 三个复选框 + 输出路径 + `人工确认并生成`。
6. 状态区：显示短状态，例如 `可生成`、`已解析`、`素材缺失`。

### warnings 处理

不再常驻显示 warnings 文本框。

- 解析失败、素材缺失、字体缺失、输出路径不可写：弹窗提示。
- GPT 失败但本地规则成功：底部状态短提示，并允许继续人工确认。
- 普通状态不占画板空间。

## 设置弹窗

`文件 -> 设置...` 打开设置弹窗。建议用 `ttk.Notebook` 或左侧分类列表实现。

本轮分类：

- `素材库`
  - 素材目录选择。
  - 当前扫描结果列表。
  - `重新扫描`。
- `字体库`
  - 字体文件或字体目录选择。
  - 当前扫描结果列表。
  - `重新扫描`。
- `AI 识别`
  - 是否启用 AI 优先解析。
  - 当前 API 配置状态。
  - 模型名称。
  - Project ID。
  - Organization ID。
  - API Key 来源。
  - `测试连接`。

设置保存后刷新主界面当前素材、当前字体和解析行为。

## AI API 配置

可以在 UI 中直接编辑、添加、删除和使用 API 配置，但不能把 API Key 明文保存到 `birth_flower_config.json`。

### 推荐实现

增加 `AIProfile` 数据结构：

- `name`：配置名称，例如 `OpenAI default`。
- `provider`：当前只支持 `openai`。
- `model`：默认 `gpt-5-nano`。
- `api_key_env_var`：默认 `OPENAI_API_KEY`。
- `project_env_var`：默认 `OPENAI_PROJECT`。
- `org_env_var`：默认 `OPENAI_ORG_ID`。
- `active`：是否为当前使用配置。
- `enabled`：是否启用 AI 识别。

`birth_flower_config.json` 只保存 profile 的非敏感字段。API Key 读取顺序：

1. 当前进程内临时输入的 API Key。
2. profile 指定的环境变量，例如 `OPENAI_API_KEY`。
3. 未配置时禁用 GPT，直接走本地规则。

### UI 行为

`AI 识别` 设置页支持：

- `新增配置`：创建一个 OpenAI profile。
- `编辑配置`：修改模型、环境变量名、Project/Org 环境变量名。
- `删除配置`：删除非当前使用配置；删除当前配置前必须二次确认。
- `设为当前使用`：切换 active profile。
- `临时输入 API Key`：只在本次程序运行期间生效，不写入配置文件。
- `测试连接`：使用极短测试备注调用 Responses API，成功显示模型和 request 状态，失败显示 HTTP 类型、code、message、request_id。

### 后端接口

`gpt_parser.py` 应从只读环境变量升级为显式参数优先：

- `api_key`
- `model`
- `project`
- `organization`
- `timeout`

`parse_pipeline.py` 接收一个可选 AI 配置对象，由 UI 传入当前 profile。没有配置或测试失败时保留现有回退逻辑：GPT 失败后本地解析兜底。

### 成本判断

直接让 UI 永久保存 API Key 的短期便利高，但安全成本和跨平台成本高。使用环境变量 + 会话临时 Key 的成本最低，兼容当前 PowerShell 测试方式，也不新增依赖。

## 解析结果字段调整

当前解析结果展示为 `文字`、`月份 1-12`、`font 1-4`、`flower 1-2`。这会把业务长期锁死在 birth flower 和月份模型。

本轮改为：

- `备注信息`：最终雕刻文字或人工确认后的备注摘要。
- `素材名`：当前选中的素材显示名。
- `字体类型`：当前选中的字体显示名。

内部仍可保留 `month`、`flower`、`font` 编号作为兼容字段，但 UI 不再把它们作为核心标签。素材扫描后根据解析结果匹配实际素材，并把匹配到的素材名展示给用户人工确认。

## 素材识别与实时渲染后端

后端优化不只包含 AI API。素材库扩大后，真正的瓶颈会变成“如何从订单备注和素材文件名中稳定匹配素材”，以及“素材变化后如何快速、友好地实时渲染到画板”。

### 素材文件名识别

当前 `asset_resolver.py` 依赖月份英文和固定 `flower 1-2` 顺序。下一阶段需要保留兼容逻辑，同时增加通用素材识别字段：

- `asset_key`：文件名规整后的稳定 key，例如 `jun-rose`、`rose`、`cherry-blossom`。
- `display_name`：展示给用户的素材名，例如 `Rose`。
- `category`：可选分类，当前默认 `birth_flower`，后续可扩展为动物、星座、图案等。
- `source_path`：素材原始路径。
- `is_vector_safe`：SVG 是否只包含矢量元素。
- `embedded_raster_warnings`：SVG 中是否引用 PNG/JPG。

匹配顺序：

1. AI 或本地解析明确返回素材名时，先按 `asset_key` 和 `display_name` 模糊匹配。
2. 如果仍是旧 birth flower 备注，继续按 `month + flower` 兼容匹配。
3. 如果多个素材命中，UI 显示候选列表，用户人工确认。
4. 如果没有命中，保留解析文字并提示用户手动选素材。

### 实时画板渲染

实时画板后端应保留现在的 SVG path 转 polyline 能力，但加缓存和错误分类：

- 素材路径未变化、布局未变化时，不重复解析 SVG。
- SVG 解析失败时不影响整个 UI，只在状态区提示。
- SVG 中嵌入 PNG/JPG 时，画板可以尝试预览，但生成前必须提示“这不是纯矢量”。
- 渲染预览只用于人工确认，不触发最终文件生成。

需要新增一个轻量 `PreviewCache` 或等价缓存结构，缓存 key 使用 `素材路径 + 文件修改时间 + 布局尺寸`，避免频繁拖拽布局时重复读文件。

## 输出格式

输出不再强制 SVG + DXF。

主界面提供三个复选框：

- `PNG`
- `SVG`
- `DXF`

默认选中 `SVG`、`DXF`，不默认选中 `PNG`，因为 PNG 依赖 Pillow 可用性和 RAQM 风险提示。

生成规则：

- 未选择任何格式时阻止生成并弹窗。
- 选择 `SVG` 调用 `render_svg`。
- 选择 `DXF` 调用 `render_dxf`。
- 选择 `PNG` 调用 `render_png`，Pillow 不可用时只阻止 PNG，并提示 SVG/DXF 是否继续生成。
- 所有最终文件仍必须通过 `人工确认并生成` 按钮触发。

## 错误处理

- 素材目录不存在：设置页和生成时都提示。
- 字体文件不存在：设置页和生成时都提示。
- GPT 配置缺失：状态区提示 `AI 未配置，使用本地规则`。
- GPT HTTP 429：展示 `type`、`code`、`message`、`request_id`。
- 输出路径不可写：弹窗提示并阻止生成。
- SVG 中嵌入 PNG/JPG 时：生成前提示这不是纯矢量。
- PNG 复杂文字：继续提示 RAQM 支持风险。

## 测试范围

新增或更新 pytest：

- `config_store`：保存和读取非敏感 AI profile，不保存明文 API Key。
- `gpt_parser`：显式参数优先于环境变量，Project/Org header 正确生成。
- `parse_pipeline`：AI 禁用时走本地规则；AI 失败时本地规则兜底。
- `ui_app`：输出格式选择生成正确文件路径；未选格式时拒绝生成。
- `ui_app`：设置弹窗保存素材库和字体库后刷新扫描结果。
- `ui_app`：warnings 不再依赖常驻 Text 控件。
- `renderer`：PNG/SVG/DXF 分别可独立调用。

## 非目标

- 不更换 Tkinter。
- 不新增商业字体。
- 不下载字体。
- 不让识别结果自动生成最终文件。
- 不把 API Key 明文写进源码或配置文件。
- 不在本轮实现多供应商大模型接入；结构预留 provider，但只实现 OpenAI。

## 实施顺序建议

1. 扩展配置模型，加入输出格式和 AI profile 的非敏感字段。
2. 改造 `gpt_parser.py` 和 `parse_pipeline.py`，支持显式 AI 配置。
3. 重构 `ui_app.py` 布局：菜单栏、设置弹窗、主界面画板优先。
4. 接入 PNG/SVG/DXF 复选输出。
5. 更新 README 和测试。
6. 运行 pytest。
