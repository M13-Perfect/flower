# flower 前端 `ui_app.py` 概览与现阶段交接（给 GPT 推导方案用）

> 用途：把 `ui_app.py`（桌面 GUI 主程序）的结构、当前进度、真/假边界一次讲清，
> 让一个**没读过代码的模型**也能据此推导下一步方案。
> 事实基准日：2026-06-17。配套权威文档：
> `docs/superpowers/plans/2026-06-16-field-engine-redesign.md`（功能区重构，含 P1–P5 路线与最新「回档」决策）、
> `CURRENT_TASKS.md`、`AGENTS.md`、`PROJECT_INDEX.md`。
> 若本文与代码冲突，以代码为准（本文已对照 `ui_app.py` 实际装配顺序校正过一次）。

---

## 0. 一句话

`ui_app.py` 是「出生花订单 → 雕刻图」桌面工具的前端：操作员把订单文本贴进来，（未来由）AI 提取字段，
界面把素材/字体/文字组织成**多图层文档**，实时画板所见即所得，最后「生成」导出 PNG/SVG/DXF 给激光雕刻（EzCad）。
当前正处在**功能区「字段提取引擎」重构**中——界面（P1）已成型，**AI 识别（P3）尚未接通，字段结果是写死的假数据**。

---

## 1. 项目背景与生产链路（防止被过时架构误导）

- **产品**：生日花卡片激光雕刻。一张卡 = 一朵「出生月花」素材 + 一段「定制文字」（顾客名字/祝福）。
- **真正的生产链路**：
  1. 订单文本（店小蜜/电商备注）→ 解析出 `text/month/font/flower` 等字段；
  2. 选月份对应花素材 + 字体；
  3. 排进**画布文档**（多图层：图片层 + 文字层）；
  4. 导出**矢量** DXF（净轮廓 SPLINE/POLYLINE，无 TEXT/HATCH，R2018）→ EzCad 导入 → 全选填充 → 雕刻。
- **三条产出口径必须字节稳定**（改前端时的红线）：
  - 桌面单单导出、Web/批量产出、金标（回归基线）三者共用同一套布局/导出逻辑；
  - 凡是没有新字段（`textLayout` 等）的旧数据，导出字节必须不变。
- **桌面是单一布局来源**：批量复用桌面 `layout_defaults`，不要在前端另造一套布局。

---

## 2. 运行方式（关键坑）

- 用装了 `customtkinter` 的 **`.venv-win`** 跑：`.\.venv-win\Scripts\python.exe ui_app.py`。
- 顶层 `import customtkinter` 用 `try/except` 容错（`ctk=None`）；若被无 ctk 的引导解释器（MSYS `.venv`）启动，
  文件末尾 `_reexec_with_complete_env()` 会**自动 re-exec 切到 `.venv-win`**，所以直接双击/任意解释器启动也能跑。
- 测试基线：`PYTHONPATH=".;services\api" .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q`。
- **每次改完务必完全关掉 App 重开再测**（旧进程缓存旧代码）。
- 改了导出/批量后，建议导一单真实输出，用 ezdxf 核实体类型（应为 R2018 + SPLINE/POLYLINE，无 LWPOLYLINE/TEXT/HATCH）。

---

## 3. 文件宏观结构（`ui_app.py`，约 5000 行）

分三层：**模块级纯函数**（可单测、无 Tk 依赖）→ **小部件/对话框辅助类** → **主类 `BirthFlowerApp`**。

### 3.1 模块级纯函数（便于测试，业务逻辑沉淀处）
- `build_design_from_values(...)`：把 UI 字段（text/month/font/flower + 素材/字体路径 + 布局 + 字形覆盖）
  转成最终生成参数 `BirthFlowerDesign`，含全部校验（月份 1–12、font 1–4、flower 1–2 等）。
- `build_readiness_parse_result_from_values(...)` + `_manual_parse_confidence/_manual_asset_confidence`：
  从当前 UI 值反推一个 `ParseResult` 并打「就绪度」分（解析/素材/布局/总体置信度）。
- `layout_from_values(values)`：把布局 StringVar 字典转 `EngravingLayout`，带正数校验。
- `build_ai_parse_config / build_ai_profile_from_settings`：AI 设置（OpenAI / DeepSeek provider、模型、base_url、env 变量名、prefer_ai）的纯函数装配。
- `validate_output_formats / output_path_for_format / dxf_path_for_svg`：输出格式校验与路径派生。
- `format_*`：就绪度、字形详情、字体标签、文件大小等展示格式化。
- `product_initial / product_rail_items / parse_missing_field_hints`：产品切换列与解析失败提示的纯数据。
- `import_dianxiaomi_xlsx_batch / summarize_xlsx_batch_result / load_template_physical_size`：
  经 `services/api` 调批量导入 / 物理尺寸模板（物理尺寸的唯一数据源是模板文件，UI 只读写不另存）。
- `run_background(root, work, on_success, on_error)`：耗时任务放后台线程，所有 Tk 更新经 `root.after` 回主线程。

### 3.2 辅助类 / 对话框
- `CtkMenu`：**自绘深色下拉菜单**（overrideredirect Toplevel + CTk 行），替代原生 `tk.Menu` 的系统白边。顶部菜单条用它。
- `_enable_dark_titlebar` / `_themed_toplevel`：Windows DWM 深色标题栏 + 1px 几何微调强制重绘（复杂对话框靠这个才真正变深）。
- `show_xlsx_batch_import_summary` / `open_report_file` / `batch_import_error_message`：批量导入结果弹窗。
- `CanvasTextItem / FloatingTextEditor`（来自 `canvas_text_item`）：画布上文字的双击内联编辑。

### 3.3 主类 `BirthFlowerApp`
`__init__` 建一大批 `tk.*Var` 状态 + 加载配置 + 扫描素材，然后
`_build_menu → _build_layout → _scan_assets → _bind_preview_updates → _redraw_preview`。
方法可按职责分组（见第 5 节）。

---

## 4. 界面整体布局

主窗口（`_build_layout`）从左到右三块：

1. **产品切换列 `product_rail`**（最左，可收/展，方案2）：列出 `config.products`，高亮激活产品，
   切产品=持久化 `active_product_id` + 用该产品库目录重扫素材。收/展状态持久化（`products_panel_collapsed`）。
2. **实时画板 `preview_panel`**（中，权重大）：白底 `tk.Canvas`（代表浅色木料），
   绑定点击/双击/右键/拖动/缩放重绘。**所见即所得**：画布几何就是导出几何。
3. **功能区 `function_panel`**（右，`CTkScrollableFrame` 单列滚动）：本次重构主战场，见第 6 节。

外观：CustomTkinter 深色主题（`APP_COLORS` 是唯一调色源，要改全局色改这里）；ttk 经 `clam` 主题刷深色；
画板**保持白底**不跟随深色。

---

## 5. 主类方法分组速查（按职责）

| 组 | 代表方法 | 作用 |
|---|---|---|
| 装配 | `_build_layout` / `_build_function_panel` / `_build_*_panel` / `_ctk_card` / `_btn` | 搭界面 |
| 菜单 | `_build_menu` / `_build_menubar` / `_open_dropdown` / `CtkMenu` | 顶部菜单 + 右键菜单 |
| 产品 | `_render_product_rail` / `_switch_product` / `_open_new_product_dialog` | 多产品切换 |
| 设置 | `open_settings` / `_build_*_settings_tab` / `_save_settings_window` / `open_layout_settings` | 设置/布局/AI/库目录 |
| 导入 | `import_remark_file` / `_import_xlsx_batch_file` / `import_asset_file` / `_import_font_file` | 订单/批量/素材导入 |
| 解析 | `parse_remark` / `_apply_parse_result` / `_show_parse_warning_dialog` / `_replace_layers_from_parse_result` | 订单→ParseResult→图层 |
| 字段（重构） | `_build_fields_panel` / `_render_fields` / `_add_field` / `_delete_field` / `_on_field_changed` | 自定义「字段」卡（**结果当前是 mock**） |
| 图层 | `_render_layers` / `_build_layer_row` / `_layer_drag_*` / `_reorder_layer_to_index` / `_layer_menu` | 真实动态图层行（增量渲染 + 拖序 + 右键菜单） |
| 图层属性 | `_apply_text_layer_properties` / `_apply_layer_production` / `_sync_layer_properties` / `_nudge_selected_layer` | 文本属性 / 几何（写回 `layer.production`） |
| 字形 | `open_glyph_panel` / `set_position_glyph_override` / `apply_glyph_variant_to_current_text` / `_resolve_current_glyph` | PUA 结尾字形替换 |
| 锁 | `_register_lock` / `_prune_locked` / `_toggle_config_lock` | 配置密码锁（**当前仅视觉 disable，无密码**） |
| 提示词 | `_build_background_prompt_panel` / `_build_generate_prompt_panel` / `_show_generated_prompt` / `_persist_prompts` | 背景词 + 拼「发给 GPT 的提示词」预览 |
| 生成 | `confirm_and_generate` / `_selected_output_formats` / `_set_readiness_display` | 校验 + 后台导出 PNG/SVG/DXF |
| 画板 | `_redraw_preview` / `_draw_*_preview` / `_on_canvas_press/drag/release` / `_start_inline_text_edit` | 渲染 + 交互 |

---

## 6. 功能区当前结构（**现阶段重点**）

`_build_function_panel` 里卡片**实际装配顺序**（代码 `ui_app.py:1350` 起，已对照过）：

1. **订单信息**（`_build_order_panel`）：订单备注文本框 + `导入 / 解析 / 清空` + 标题栏右上**锁图标**（🔓/🔒）。
   订单文本框是**唯一不被锁**的控件。
2. **背景提示词**（`_build_background_prompt_panel`）：管理员写一段背景/全局指令，随产品持久化（P3-1 已接），属锁定区。
3. **字段**（`_build_fields_panel` / `_render_fields`）：**多字段引擎**，一字段一张子卡：
   `字段名 chip + 类型 OptionMenu(文本/素材/字体) + 结果值(Entry) + ✕`，下行 `提取规则 Entry`；底部「添加字段 +」。
   - 数据模型：`self.field_defs = [{key,name,type,instruction, *_var}]`，`self.field_results`（**写死 mock：`Ammy / 1月 / Font5`**）。
   - `error` 哨兵：结果值 == `error`（不区分大小写）→ 该 Entry 标红。（**「禁用生成」联动留到 P3 接真值时做。**）
   - 属锁定区。
4. **图层**（`_build_production_panel` → 标题「图层」）：**真实动态行**，由 `_render_layers()` 按 `self.document.layers` **增量**渲染。
   - 单行：`拖柄 ⠿ + 类型小图标(蓝 T=文本 / 绿 ▣=素材) + 状态(🚫隐藏/🔒锁定) + 提取内容(主,吃余宽) + 右侧灰字库缩写`。
   - **行内不放下拉**；改库/素材/字体走**右键菜单**级联（`_layer_menu` + `_on_layer_*_changed`），字号走「位置/尺寸」对话框。
   - **拖柄拖动 = 蓝色插入指示线**动画，松手 `_reorder_layer_to_index` 重排 `document.layers` + `normalize_z_indexes`。
   - 底部按钮：`+ 文字图层`（`_add_text_layer_from_fields`）、`+ 图片图层`（`_add_selected_flower_to_canvas`）。
   - **隐藏的全局选择器**：原四个 combo（image_library/flower/font_library/font）创建后**不 grid**，
     但 parse/扫描/选库联动仍依赖它们 → **改图层逻辑时别误删**，按计划是逐图层迁移后最后才移除。
5. **字体库 / 素材库**（`_build_library_panel`）：库池展示（素材库1/2、字体库1/2，设置里上传），属锁定区。
6. **生成提示词**（`_build_generate_prompt_panel` / `_show_generated_prompt`）：把
   `[字段提取规则] + [背景提示词] + [订单信息]` 拼成「实际要发给 GPT 的内容」并回显（开发期校验，**纯字符串拼装，不调 GPT**）。
7. **输出设置（含「生成」按钮）**（`_build_output_settings_panel`）：格式勾选(PNG/SVG/DXF) + 输出目录 + **主操作「生成」**。
   （底部「生产输出」栏已删，主按钮落在此卡最底。）

> ⚠️ 历史包袱：旧「图层」listbox 面板 `_build_layers_panel` 仍定义但**不再装配**（`layers_listbox=None`，相关刷新方法自带 None 守卫退化为 no-op）；
> 旧 `_cycle_text_case`/`case_button` 是死代码。重构期遗留，勿被误导。

---

## 7. 核心数据流

```
订单文本 (remark_text)
   │  parse_remark()  ← 当前走【旧固定解析链】(parse_pipeline / gpt_parser，可选 active_bundle 富化)
   ▼
ParseResult (text/month/font/flower + material_key/font_key + 置信度/warnings)
   │  _apply_parse_result() / _replace_layers_from_parse_result()
   ▼
Document（多图层：ImageLayer 花素材 + TextLayer 文字；每层带 library_id/material_key/font_*/production）
   │  _render_layers()（功能区图层行）  +  _redraw_preview()（画板）
   ▼
confirm_and_generate()  →  build_design_from_values()  →  导出 PNG / SVG / DXF（desktop_export / renderer）
```

- **画布即输出（WYSIWYG）**：导出复用预览的视觉 bbox + contain-fit + 居中（`desktop_export._apply_canvas_fit`），桌面四路定位偏差 <0.05mm。
- **文字排版单一大脑**：`text_layout.fit_text_box`（自适应字号 + 断行 + 基线 origins），预览==PNG==DXF；
  名字字号由文本框自适应，`layer.font_size` 退化为字号上限 cap。
- **字形**：Font 2 内置 a–z 的 PUA 结尾字形，可自动/人工替换最后一个字母（`glyph_service`）。

---

## 8. 现阶段「真 / 假」边界（推导方案前务必看清）

重构路线（见 field-engine-redesign.md 第 5 节）：**P1 整页界面 → P2 交互 → P3 后端接入 → P4 锁校验 → P5 验收**。

**当前位置 ≈ P1 完成 + P2 大部分完成，P3/P4 未做。** 具体：

| 能力 | 状态 |
|---|---|
| 功能区整页界面、卡片布局 | ✅ 真，可点 |
| 字段卡增删 / 类型切换 / error 标红 | ✅ 真（UI 层） |
| 图层真实动态行 / 拖动调序 / 右键菜单 / 增删即可见 | ✅ 真 |
| 背景词 + 提取规则随产品持久化 | ✅ 真（P3-1 已接 `config_store.ProductConfig.extraction_prompt/background_prompt`） |
| 「生成提示词」预览 | ✅ 真（本地拼字符串，**不调 GPT**） |
| **字段结果值（Ammy/1月/Font5）** | ❌ **假数据 mock**，`self.field_results` 写死 |
| 「解析」真正按字段动态提取 | ❌ 仍走**旧固定解析链**，不写字段结果 |
| 字段值 → 自动映射素材库/字体库 → 写回图层 | ❌ 未接（`content_field` 未进模型，绑定仅 UI 态 `_layer_field_bind`） |
| `error` 哨兵真正禁用「生成」 | ❌ 仅标红，未禁用 |
| 配置密码锁 | ❌ 仅视觉 `configure(state=disabled)`，**无密码校验**（P4） |
| 导出 PNG/SVG/DXF | ✅ 真（这条链一直可用） |

> 演示给甲方时：界面与提示词预览是真的，足以定稿设计；但字段「解析」出来的值是假的，别让人误以为识别已可用。

---

## 9. 已知遗留 / 待办（按优先级，供推导下一步）

1. **P3 后端接入（最大缺口）**：
   - 让「解析」真去 GPT：用 `order_catalog.parse_order_remark_with_gpt_catalog` 那条链，
     但当前设计是「单段提取提示词 + 多字段」混合，**响应 schema 待定**——需要先定「动态 schema 怎么由 `field_defs` 拼出 / 返回什么结构」。
   - 把识别结果写回：字段结果区 + 按字段类型映射到素材库/字体库（`key/name/aliases` 不区分大小写匹配，匹配不到记 warning + 图层占位）+ 写图层 `content_field`。
   - `error` 哨兵：值 == error → 标红 + **禁用「生成」** + 状态栏指出哪个字段超限。
2. **P4 密码锁**：配置存密码哈希；解锁前除订单文本框外全部锁定区控件只读。
3. **图层模型固化**：字段↔图层绑定从 UI 态 `_layer_field_bind` 进模型 `content_field`；隐藏全局 combo 最终移除（先保留作 fallback，逐步迁移）。
4. **PS 风图层系统 Stage 2/3**（另一条并行需求，见 CURRENT_TASKS §0c）：`tk.Listbox` → `ttk.Treeview`（嵌套图组 + 逐层眼睛/锁 + 多选），空白图层工作流。Stage 1 模型（`GroupLayer`）已落地。
5. **导出朝向「文字在上、花在下」**：用户 EzCad 实测仍反，合成测试未复现，待用户给具体单子定位。
6. 真机手测：拖放 / 图标命中 / 完整链路无法纯自动化，**改完必须真窗口点一遍**。

---

## 10. 给 GPT 的硬约束（生成方案时必须遵守）

1. **界面文案 = 真实控件名**：主输出按钮叫「生成」（不是「生成图片」「确认并生成」）；说明里引用的控件必须是界面真存在的 label。
2. **导出/批量/金标字节稳定**：动前端不得改变没有新字段的旧数据导出字节；新字段（如 `textLayout`）只在存在时生效。
3. **桌面是单一布局来源**：不要在前端新造布局逻辑，复用 `layout_defaults` / `EngravingLayout` / `_apply_canvas_fit`。
4. **`CTkOptionMenu` 不要反复 destroy/recreate**：会在 customtkinter `AppearanceModeTracker` 留悬挂引用而崩溃 →
   图层行必须**增量渲染**（复用存活行，只增删变化行），这是 `_render_layers` 的关键设计，别改回全量重建。
5. **新对话框用 `_themed_toplevel()`，弹出菜单用 `CtkMenu`，颜色取 `APP_COLORS`**。
6. **程序化更新要置 `_is_programmatic_update` / `_with_programmatic_update`**，避免控件事件回灌业务写入。
7. **每块改动**：`python -m py_compile ui_app.py` + 渲染冒烟（建 `BirthFlowerApp(ctk.CTk())` → `root.update()` 无异常）+ 跑 pytest；收尾把背景/改动/已知问题折回 `AGENTS.md`。

---

## 11. 推导方案时建议的切入问题

- P3 的「动态 schema + 响应结构」要先定：字段定义如何拼成发给 GPT 的 JSON schema？返回 `{field_key: value}` 还是带 type 的结构？
- 字段类型（文本/素材/字体）→ 图层接线的**映射规则**：自动按类型绑 + 允许手动覆盖，匹配不到如何降级？
- `error` 哨兵的判定时机（解析回填时 vs 生成前校验）与 UI 联动（标红 + 禁用 + 状态栏）。
- 密码锁（P4）的存储（产品级哈希）与解锁交互。
- 是否同时推进 PS 风图层 Stage 2/3，还是先把 P3 识别闭环打通——两者都动 `_render_layers` 区域，需排序避免互相打架。
</content>
</invoke>
