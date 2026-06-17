# 功能区重构：字段提取引擎（前端优先）

> 日期：2026-06-16　状态：设计已定稿，待开工
> 本文是开工基线与交接锚点。新对话接手先读本文 + `ui_app.py` 功能区代码。

## 1. 背景与目标

把当前功能区从"写死三字段（内容/月份/字体）"升级为**用户可自定义的「字段」提取引擎**：

- 操作员在订单信息框填订单文本。
- 管理员定义若干「字段」——每个字段是一条想让 AI 从订单里提取的信息 + 它的自然语言规则。
- AI 按字段定义动态提取，结果回填到字段结果区。
- 图层、文件名都用下拉**引用字段**，而不是存字面值。
- 「生成提示词」按钮把"字段规则 + 库目录 + 背景提示词 + 订单文本"拼成实际发给 GPT 的内容并回显（开发期校验用）。
- 除订单文本框外，全部配置可被**密码锁**锁定（管理员配置 / 操作员日常）。

「字段」是本次确定的术语（替代草图里的 "Area"），会出现在标题、图层下拉、文件名绑定等高频位置。

## 2. 现状（重构前）

功能区 = 三张竖叠卡片，`_build_function_panel`（`ui_app.py:1276`）：

- `订单与解析`（`ui_app.py:1359`）：订单备注框 + 导入/解析/清空 + 子卡「人工确认字段」（内容/素材月份/大小写/警告）。
- `生产参数 > 素材与字体`（`ui_app.py:1427`）：素材库/素材名/字体库/字体类型 4 下拉 + 添加素材/添加文本。
- `图层`（`ui_app.py:1297`）：listbox + 显隐/锁定/删除/层级 + 文本/字号/颜色 + 位置 XYWH + 加粗/下划线/字间距。

解析链是**写死 schema**：`build_order_remark_schema(material_keys, font_keys)`（`order_catalog.py:150`）固定 `text/material_key/font_key`；`ParseResult` 也是固定字段。→ 本次要改成动态。

## 3. 已锁定的关键决策

1. **完整动态引擎**：字段完全自定义，动态拼 JSON schema 发 GPT，返回以字段 key 为键的字典。
2. **术语 = 字段**。
3. **结果与定义合并为一个区域**（每字段一张卡，同时含提取规则 + 提取结果）。
   〔订正：早期定的"分两段"已被用户推翻，现为合并。〕
4. **图层支持拖动调序**（拖动行即改 z 序，复用 `_move_selected_layer` 逻辑，替代上移/下移/置顶/置底按钮）。
   图层区为**真实动态列表**：新增即出现可见、可编辑的行；类型只用小图标，不显示"文字/图片"块；
   图层内容默认绑定字段1/字段2，未手动匹配时**动态显示该字段的提取结果值**（如 `↓字段1 = Ammy`）。
5. **密码锁锁住除"订单备注文本"外的全部配置**——明确**包含 AI 提取结果区 与 背景提示词**。
6. **背景提示词置于订单信息正下方**（属锁定区/管理员配置）。
7. **前端优先**：甲方需要先看见、先定方案；后端识别最后接。

## 4. 核心数据模型（改动最大处）

- **字段定义**：`{key, name, type, instruction}`，按产品存配置/bundle。
  `type` ∈ `文本 | 素材 | 字体`，决定字段值怎么被消费（见第 7 节）。
  例：`{key:"field1", name:"字段1", type:"文本", instruction:"顾客定制文本，≤20字符，超过输出 error"}`。
- 解析时**由字段列表动态拼 JSON schema** → GPT 返回 `{field1:"Ammy", field2:"1月", field3:"Font5"}`。
- `ParseResult` 增加 `field_values: dict[str,str]`。
- **图层存字段引用，不存字面内容**：文字图层 `content_field="field1"`，渲染时解析字段值→文字；图片图层按字段值/手选挑素材。
- **文件名模板引用字段 key**（如订单号字段）。
- **锁**：配置存密码哈希；解锁前除订单文本框外全部配置控件只读。

## 5. 落地顺序（前端优先，标明真/假边界）

| 阶段 | 内容 | 真/假 |
|---|---|---|
| **P1 整页界面** | 订单信息卡、字段结果段、字段定义段、图层段、库、输出设置、背景提示词、生成提示词按钮 | 界面全真可点 |
| **P2 交互** | 字段增删、图层拖动调序、密码锁开合、**生成提示词实拼**（纯字符串拼装，不调 GPT） | 提示词真出内容；解析填值用假数据/占位 |
| **P3 后端接入** | 动态 schema + `error` 哨兵 + 让「解析」真去 GPT 填字段值 | 解析转真 |
| **P4 锁校验** | 密码真校验，锁除订单文本外全部配置 | 真 |
| **P5 验收** | 真机手测 + 写回 AGENTS.md | — |

> 演示注意：P1–P2 给甲方看时，「解析」填出的字段值是**假数据**，别让甲方误以为识别已可用。提示词预览与界面是真的，足以定稿设计。

## 6. 触及文件

- 前端：`ui_app.py` —— 重写 `_build_order_panel`/`_build_production_panel`/`_build_layers_panel`，新增字段编辑、图层拖序、密码锁、输出设置、背景词、生成提示词按钮&回显。
- 后端（P3）：`order_catalog.py`（动态 schema + 系统提示词拼装 + 解析字典 + `error` 哨兵）、`parse_pipeline.py`（透传字段定义 + 背景词）、`ParseResult` 模型、图层模型（`content_field`）。
- 配置：按产品存字段定义 + 密码哈希。

## 7. 细节决策（已定）

**字段类型 + 图层接线（细节 1+3 合并）= 混合：字段带类型 + 图层可覆盖**

- 字段定义带 `type`（文本/素材/字体）。图层**按字段类型自动接线**：
  - 文本型 → 文字图层的内容来源；
  - 素材型 → 图片图层的素材来源；
  - 字体型 → 文字图层的字体来源。
- 高级下图层仍可**手动覆盖**用哪个字段 / 哪个库。
- **映射机制（素材型/字体型统一）**：拿字段值去目标库的 items 按 `key/name/aliases`
  **不区分大小写**匹配；匹配不到 → 记 warning + 图层留占位。复用现有 bundle 查找。
- **自动 + 手选并存**：解析后按字段值自动选中，图层下拉仍可手改覆盖。
- ⚠️ 录入前提：库 item 的 key/别名要配成能被字段值命中（字体库配 `font1/font5…`，
  素材库别名含 `1月` 等），否则 GPT 返回的值查不到。属菜单栏库设置的录入要求。

**`error` 哨兵 = 红色高亮 + 禁用生成**

- 字段值 == `error`（不区分大小写）→ 该字段结果**标红**，「生成」按钮**禁用**，
  状态栏提示是哪个字段超限。防废品。

## 8. 怎么跑 / 怎么测

- 运行：用 `.venv-win`（装了 customtkinter 的环境）跑 `ui_app.py`；引导解释器没 ctk 会自动 re-exec 到 `.venv-win`。
- P2 提示词拼装、P3 动态 schema、`error` 哨兵都应有单测（参考既有 `tests/`）。
- 界面文案须用真实控件名（主输出按钮 = 「生成」）。

## 9.5 进度

- **P1 已完成（2026-06-16）**：`ui_app.py` 功能区按新布局重写并通过渲染冒烟。
  - 重写：`_build_function_panel`（新卡片装配）、`_build_order_panel`（→「订单信息」+ 锁按钮）、
    `_build_production_panel`（→「图层」卡，保留并复用原素材/字体四选择器与全部联动）。
  - 新增：字段模型 `self.field_defs` + `_render_fields_results`/`_render_fields_defs`（结果/定义两段，
    数据驱动，支持增删、类型下拉、error 标红）；`_build_library_panel`/`_build_output_settings_panel`/
    `_build_background_prompt_panel`/`_build_generate_prompt_panel`；`_toggle_config_lock`、`_show_generated_prompt`。
  - 旧「图层」listbox 面板 `_build_layers_panel` 仍定义但**不再装配**（`layers_listbox=None`，
    `_refresh_layers_panel` 自带 None 守卫退化为 no-op）；旧 `_cycle_text_case`/`case_button` 变为死代码（不再被调用）。
  - **P1 占位/待接**：字段结果是 mock（`Ammy/1月/Font5`），「解析」仍走旧固定解析、不写字段结果；
    生成提示词是初版本地拼装（未含库目录与真实发送格式）；锁只做视觉开合；图层↔字段下拉为示意（未真正驱动加图层）；
    输出设置与底部「生产输出」栏暂共用同一份 var、视觉上重复。
- **P1 修订（2026-06-16，按用户反馈）**：
  - 锁改为标题栏**一个小锁图标**（🔓/🔒，width=30，无文字）。
  - 取消独立「素材与字体」卡：**库 + 素材/字体下拉聚合进每个图层行**（文字行另含字号），
    `_layer_demo_row` 渲染文字/图片两示意行；位置/尺寸/对齐/显隐/删除走**右键/⋮ 菜单** `_layer_demo_menu`（P1 弹真实菜单，命令暂为状态提示）。
  - 原四个全局选择器（image_library/flower/font_library/font combo）**创建后不 grid（隐藏）**，
    保留 parse/扫描/选库全部联动；P2 把库/素材/字体选择真正做进每图层行后移除隐藏容器。
  - 库池模型确认：素材库1/2、字体库1/2 = 固定库池（设置里上传），图层挑库 + 字段自动填值 + 可手动覆盖；去掉"自动匹配"标注。
- **下一步 P2**：图层示意行 → 真实每图层绑定（内容字段/库/素材随 document.layers 动态渲染）+ 拖动调序 + 右键属性编辑接真逻辑；生成提示词实拼（接 `build_catalog_system_prompt` 风格 + 库目录）。

## 9.7 设计变更（2026-06-16 晚 · 用户拍板：多字段引擎 → 单「提取提示词」框）

> 🔁 **2026-06-16 又一次回档（最新事实，新对话以此为准）**：用户要求把「提取提示词」框**回档为多字段「字段」卡**——
> 即本节下面写的「字段卡 → 单提取框」UI 改造**已被撤销**。当前功能区第 3 槽又是多字段「字段」卡
> （`_build_fields_panel`/`_render_fields`/`_ensure_field_vars`/`_field_chip`/`_add_field`/`_delete_field`/`_on_field_changed`，
> `__init__` 有 `field_defs`/`field_results`/`field_seq`/`fields_body`，无 `extract_prompt_text`）。
> **仅回档这一块**：布局重排、单行图层行（§9.7 下面那段）、背景词持久化（P3-1）全保留。
> 与回档前旧版的差异：新图层行不显示字段 → **字段↔图层耦合不再恢复**（`_render_fields` 不碰图层、`_delete_field` 不清绑定，
> `_field_menu_values`/`_refresh_field_menus`/`_layer_field_label` 等未恢复）。`_show_generated_prompt` 拼
> `[字段提取规则]+[背景词]+[订单信息]`；`_persist_prompts`/`_load_prompts_into_widgets` 收窄为只管背景词，
> `config_store` 的 `extraction_prompt` 字段保留不动（供未来再用，单测仍绿）。下面 §9.7 原文保留作历史，**勿据其重建提取框**。

> ⚠️ （历史）覆盖 §1–§7 的"完整动态字段引擎"。用户决定**砍掉多字段 UI**，回归更简方案。**——此条已被上面的回档推翻。**

- **功能区「字段」卡 → 单个「提取提示词」框**（`_build_extract_prompt_panel`，CTkTextbox）：
  管理员写一整段自然语言指令，发给 API 让它从订单提取（素材 / 文字内容等）。属配置锁定区。
- **彻底移除**多字段引擎：`field_defs`/`field_results`/`_render_fields`/`_add_field`/`_delete_field`/
  `_on_field_changed`/`_field_*`/`_layer_field_bind` 全删（无外部依赖，纯 UI 侧）。
- **图层行 = 单行·灰字缩写（最新，2026-06-16 晚第 3 版，用户先选预览再定）**：
  `拖柄 ⠿ + 类型小图标 + 状态 + 提取内容(主) + 右侧灰字库缩写`。**信息熵拉高、图标回归**（曾一度全删图标/内容，用户反馈太空）。
  - 图标：蓝底 `T`=文本 / 绿底 `▣`=素材（`_layer_icon_spec`）。
  - 提取内容（主，吃余宽）：文本层=识别到的文字（`original_text/text/render_text`），素材层=文件名（`layer.name`/`path.stem`）；
    **空文本层→灰色 `info`** 占位（`_layer_main_text`）。P3 由 API 写回图层后这里即显真值。
  - 右侧灰字（缩写）：文本层=`字体·字号`，素材层=`素材库缩写`（`_layer_dim_text` + `_abbrev` 截断）。
  - 状态：隐藏=🚫、锁定=🔒（`_layer_status_text`，正常为空）。
  - **行内不再放下拉**：改库/素材/字体走**右键菜单**新增级联 `素材库`/`素材`（图片层）、`字体库`/`字体`（文本层）（复用 `_on_layer_*_changed`）；字号走「位置/尺寸…」对话框。
  - **拖动动画=插入指示线**（用户从 4 个预览里选定）：拖柄按住→被拖行调暗「抬起」(fg→panel+蓝边)，
    `layers_rows_box` 上 `place` 一条蓝色落点线随指针上下移动指示插入位（`_ensure_drop_indicator`/`_layer_drag_motion`），
    松手 `_reorder_layer_to_index` 按显示索引重排（列表是 reversed=下→上，落点索引需换算）。不挤动其它行，CTk 里最稳。
  - 修了旧 bug：旧版把「左键选中」也绑到拖柄上，覆盖了拖动的 `ButtonPress-1` → 拖动其实不生效；现在**拖柄只管拖动**，选中绑在其余控件。
  - **右键整行弹功能菜单**（`_bind_layer_menu` 递归绑 Button-3/2 到 card 及所有子控件，含 CTkOptionMenu 内部 canvas）——像桌面右键图标，此处图标换成一行图层。⋮ 已删，右键是唯一入口。
  - 删除：`_build_image_sources`/`_build_text_sources`（行内下拉）、`_text_layer_has_content`、旧 `_reorder_layer`/`_layer_id_at_y`、`self._layer_content`/`_layer_content_text`。识别结果不在行内复述，P3 由 API 写回图层、画布呈现。
- **生成提示词预览**改为拼：`[提取提示词] + [背景提示词] + [订单信息]`。
- 验证：`py_compile` 过、冒烟过、`pytest` 388 过 / 2 预存失败（与本变更无关）。
- **遗留/P3**：API 未接；接好后由识别结果写 `self._layer_content`（+ 真正映射素材/字体库）。
  「提取提示词」文本如何随产品存配置、如何拼进真实 system prompt，留 P3。

### P3-1 已接（2026-06-16 晚）：提取/背景提示词随产品持久化
- `config_store.ProductConfig` 加 `extraction_prompt` / `background_prompt`（+ `_product_to_payload`/`_product_from_payload`
  序列化 + 新助手 `with_product_prompts(config, *, extraction_prompt, background_prompt, product_id=None)`）。
- `ui_app`：两个文本框构建时载入当前产品已存值；`<FocusOut>` → `_persist_prompts()`（无变化不写盘）；
  `_switch_product` 切走前 `_persist_prompts()`、切来后 `_load_prompts_into_widgets()`。
- 测试：`tests/test_config_store.py` 加提示词往返 + 空值用例（11 过）。
- ⚠️ 教训：`save_config` 默认路径在 import 时绑定，测试里改 `config_store.DEFAULT_CONFIG_PATH` 不生效；
  测 `_persist_prompts` 必须 patch `ui_app.save_config` 或传显式路径，否则会写到真实 `birth_flower_config.json`。
- **仍未做（P3 主体）**：真正调 API（用 `parse_order_remark_with_gpt_catalog` 那条链，但现在是单提示词、
  响应 schema 待定）、把识别结果写 `self._layer_content` 并映射素材/字体库、`error` 哨兵禁用「生成」、P4 密码锁。

## 9.6 进度（2026-06-16 · VS Code 接手：第 10 节 A+B 全部落地，仅改 ui_app.py）

按第 10 节顺序做完 **A（布局重排）+ B（图层变真实，B1–B6 全做）**，后端 P3 未碰。

- **A1 卡片顺序**：`_build_function_panel` → 订单信息 → 背景提示词 → 字段(合并) → 图层 → 库 → 输出 → 生成提示词。
- **A2 字段合并**：新 `_build_fields_panel`/`_render_fields`（一字段一卡：类型 OptionMenu + 结果值 error 标红 + 规则 Entry + ✕）；
  删 `_build_fields_results_panel`/`_render_fields_results`/`_build_fields_defs_panel`/`_render_fields_defs`。
- **A3 锁范围**：`self._locked_widgets` + `_register_lock`/`_prune_locked`；`_ctk_card(..., locked=True)` 卡头加 🔒；
  `_toggle_config_lock` 对登记控件真 `configure(state=...)`。锁定区=背景词/字段/图层/库/输出/生成；订单备注框不入列表。
- **A4**：删 `_layer_demo_row`/`_layer_demo_menu`；`_build_production_panel` 建 `self.layers_rows_box` 并调 `_render_layers()`；
  `_refresh_field_menus` 改为重渲染图层行。
- **B 真实图层行**：`_render_layers()` **增量**渲染（复用存活行、只增删变化行、原位更新值）——
  这是关键设计：反复 destroy/recreate `CTkOptionMenu` 会在 customtkinter `AppearanceModeTracker` 留悬挂引用而崩溃，故必须增量。
  钩子：`_refresh_layers_panel` 顶部 `_schedule_render_layers()`（**after_idle 去重**，不在画布右键/重绘等同步流程里现场建控件）。
  - B2 内容字段下拉：`self._layer_field_bind`（UI 态，缺省按字段类型绑文本/素材型），显示 `↓字段 = 结果值`。
  - B3 新增即可见：`add_text_layer`/`add_image_layer` 已置 `selected_layer_id`，经钩子自动出现选中行。
  - B4 拖柄 `<B1>` 拖动落点重排 `document.layers` + `normalize_z_indexes`；⋮ 菜单另有上移/下移/置顶/置底兜底。
  - B5 `_layer_menu`：位置/尺寸小对话框（复用 `_sync_layer_properties`+`_apply_layer_production`）、对齐、显隐/锁定、调层级、删除。
  - B6 逐层库/素材/字体下拉接 `active_bundle` 写回图层；**保留隐藏全局 combo 作 fallback**（parse/扫描/选库联动不断）。
- **验证**：`python -m py_compile ui_app.py` 过；渲染冒烟过；`pytest` **388 过 / 2 失**。
  2 失为**本轮之前就存在**、与 A→B 无关：`test_text_case_*`（旧 `_cycle_text_case`/`case_button` 死代码，P1 已删按钮）、
  `test_birth_flower_app_initializes_*`（菜单栏「设置」label 断言，菜单栏代码本轮未碰）。
- **已知遗留**：字段↔图层绑定仅 UI 态（未进模型 `content_field`，留 P3）；hidden 全局 combo 未删（按决定保留）；
  锁仅控件 disable 无密码校验（P4）；解析仍旧固定链、字段结果 mock（P3）。
  另：测试 teardown 偶现 `invalid command name ..._run_scheduled_render_layers`（无 mainloop 时 root 销毁前有挂起 after_idle），
  纯测试态噪音、不影响结果，真实运行无碍。

## 10. 本轮代码实施步骤（VS Code 接手，最新设计）

> ✅ 本节 A+B 已于 2026-06-16 全部完成，详见 §9.6。以下保留为设计/对照。

> 现状：`ui_app.py` 已是「P1 修订」状态（见 9.5）。本轮把布局按最终设计再调一次 +
> 把图层做成真实动态列表。按顺序做，每块做完先跑渲染冒烟再继续。

**A. 布局重排（轻量）**
- A1 `_build_function_panel`：卡片顺序改为 订单信息 → 背景提示词 → 字段(合并) → 图层 → 库 → 输出 → 生成提示词。
  （把 `_build_background_prompt_panel` 提到第 2 位。）
- A2 字段两段合并：新建 `_build_fields_panel` + `_render_fields`——每字段一张卡：
  上行 `字段名 chip + 类型 OptionMenu + 结果值(error 标红) + ✕`，下行 `规则 Entry`。
  删除 `_build_fields_results_panel`/`_render_fields_results`/`_build_fields_defs_panel`/`_render_fields_defs`；
  `_on_field_changed` 改为只调 `_render_fields` + `_refresh_field_menus`。
- A3 锁范围：背景词/字段/图层/库/输出/生成 = 锁定区。维护 `self._locked_widgets` 列表，
  `_toggle_config_lock` 统一对其 `configure(state=...)`；各锁定卡头加 🔒 标。（订单备注框不入列表。）
- A4 删除图层卡里的静态"文字/图片"块：`_layer_demo_row`/`_layer_demo_menu` 由真实渲染（B）取代。

**B. 图层变真实（本轮重点，P2 级）**
- B1 `_render_layers()`：清空 `rows_box` → 遍历 `self.document.layers` 每层渲染一行
  （`ti/⠿` 拖柄 + 类型图标 + 内容字段 OptionMenu + 库 OptionMenu + 素材/字体 OptionMenu + 字号[仅文字] + ⋮）。
  类型只用图标，不显示"文字/图片"文字块。在 `_build_production_panel` 末尾调用。
- B2 内容字段下拉：值 = 字段名列表；默认按图层序绑 字段1/字段2；显示 `↓字段N = <结果值>`
  （结果取 `self.field_results` / 字段 `result_var`）。选择写回该图层的内容来源（先用 `self._layer_field_bind={layer.id: field_key}` UI 态，P3 再进模型 `content_field`）。
- B3 添加图层即可见可编辑：`_add_text_layer_from_fields`/`_add_selected_flower_to_canvas` 末尾
  调 `_render_layers()` + 选中新层。**修掉"新增看不见/不能改"**。
- B4 拖动调序：行 `<B1-Motion>` 拖拽 → 落点重排 `document.layers` → `normalize_z_indexes()` + `_render_layers()` + `_redraw_preview()`。
- B5 右键/⋮ 真菜单：接真实操作——位置/尺寸/对齐弹小对话框写 `layer.production`；显隐/锁定 toggle；
  删除走 `_delete_selected_layer`。复用 `_sync_layer_properties`/`_apply_layer_production`/`_toggle_selected_layer_visible` 等既有逻辑。
- B6 素材/字体下拉接 `active_bundle`：选择写回图层；逐图层接好后**移除隐藏的全局 combo 容器**。
  ⚠️ 移除前先理清 `_refresh_flower_choices`/`_on_*_combo_selected`/`_configure_library_combo` 的依赖，
  建议保留隐藏 combo 作 fallback、逐步迁移，最后再删，避免打断 parse/扫描联动。

**验证**
- 每块后：`python -m py_compile ui_app.py` + 渲染冒烟（建 `BirthFlowerApp(ctk.CTk())` → `root.update()` 无异常）。
- 手测：加文字图层→出现可编辑行；改内容字段→画布文字变；拖两行→顺序变；右键删除→行+画布同步消失；点锁→锁定区只读。

## 9. 设计预览

界面布局见会话中的 `flower_area_engine_redesign` 预览图（把图中 "Area" 读作「字段」）。分两栏只为一次看全，实际是单列滚动功能区。
