# AGENTS.md — flower（纯 Python 桌面版）

> 新对话先读本文件 + `PROJECT_INDEX.md` + `CURRENT_TASKS.md`。
> 最近一次实质改动：**2026-06-26 全局设置从固定花图/文字两槽升级为可扩展 `layout_slots`（多槽位）；图层面板🔒改为「写入/更新全局布局槽位」；解析订单时遍历全局槽位动态生成 N 个图层**（见下「本次改动」）。⚠️ 上一版「图层面板🔒=模板锁定（设 layer.locked + locked_by_template）」方向已被否决并纠偏，见「上次改动（已纠偏）」。
> 分支 `layer-system-v2-rest`，逐次提交。**未 merge 回 main、未 push。** Layer System v2 RFC 全文见 `docs/rfcs/layer-system-v2.md`。

## 背景 / 当前生产链路

- 唯一产品线 `birth-flower-card`（生日花卡：一朵花 + 一个名字）。
- 生产工具 = **纯 Python Tkinter 桌面 App**（入口 `birth_flower_mvp.py` → `ui_app.py`）。
  链路：订单备注 → 解析（`parse_pipeline`/`gpt_parser`，AI 可选）→ 人工确认字段 → 实时画板编辑（选层/移动/缩放/换素材）→ 导出 DXF/SVG/PNG。
- **导出权威在 `services/api`**（`app/domain/exports/dxf.py`/`svg.py`/`png.py`），桌面经 `desktop_export.py` in-process 调用；DXF = R2018 + SPLINE/POLYLINE + 单层色7，单次 Y 翻转在 `dxf.py`。所见即所得（预览==导出，`_apply_canvas_fit` 把 contain-fit 烘进导出）。
- 素材：花按 `BirthMonth flowers/` 下 `*.svg` 文件名扫；字体 `Front1-4.ttf`（index 从文件名数字推，全链路用 `"Font N"` 字符串作身份）。**无月份/序号映射**。
- **提示词存在 flower 内独立 SQLite 库 `prompts.db`**（与 `birth_flower_config.json` 同目录），**三表「定义/值分离」模型**（2026-06-26 重构，见下「本次改动」）：`field_definitions`（**全局唯一**：身份 uuid〔仅内部用、不显示〕+ 显示名 + 类型 + 全局默认内容）、`prompt_sets`（**一产品可多套**，`product_id` 归属）、`field_values`（**按套独立**：内容/序号/排序/启用）。产品配置只持 `prompt_set_id`（=该产品当前激活套）。token `{{field:uuid}}` 里 uuid=定义 id；`{{field:uuid@global}}`/`{{field:uuid@产品}}` 为跨作用域引用。对外仍以 `PromptSet`+`ReferenceField`（定义⨝值的视图）暴露，下游 `resolve_prompt_template`/UI 不感知拆表。
- **易混点（防走偏）**：① `automation/` 下的 **inbox-service**（2026-06-26 已迁回本仓 `automation/`）有自己的 SQLite，那是**订单状态机**，与提示词库无关；② `flower/services/api` 是**已暂缓的 web API**，与本次提示词重构无关。本次只动 flower 自身（桌面侧）。`prompts.db` ≠ inbox-service 的库，别混。

## 本次改动（2026-06-26）：全局设置升级为多槽位 `layout_slots` + 图层🔒写入全局槽位 + 解析遍历槽位生成 N 层

**目标（用户纠偏后的真实需求）**：全局设置 = `active_product(config).defaults`（`EngravingLayout`）原本被 frozen 字段 `flower_*`/`text_*` 写死成「一花图 + 一文字」两槽。本次打开这个限制：支持保存任意数量的图片/文字槽位；**图层面板🔒 的语义改成「把当前图层写入/更新为全局布局槽位 Global Layout Slot」（不是编辑锁、不设 `layer.locked`）**；解析订单时遍历全局槽位动态生成对应图层，不再只生成「花图+名字」两层。`layer.locked` 仅保留为右键编辑锁，且**不作为自动排版依据**——排版只看 `layout_slots`。

**与上一版的关系**：上一版把🔒做成 pin+`layer.locked=True`+`locked_by_template`（禁拖拽=模板锁），方向被否决。本次：删掉 `locked_by_template`/`locked_manual` 两字段、`_toggle_selected_layer_locked` 回退为纯 `layer.locked` 翻转、删掉 `_fill_template_*`/`_get_template_locked_layers`/`_template_group_scenes`/`_mm_to_px` 一整套模板回填代码，换成下面的全局槽位体系。（组内 3mm/右对齐联动降级为 P2，仅在 slot 里预留 `group_id/gap_mm/anchor` 字段。）

**本次实现（P0 + 部分 P1）**：
- **`models.py`**：新增 frozen `LayoutSlot`（`slot_id/slot_type(image|text)/source_field/slot_name/x/y/width/height/rotation/z_index/text_align/font_size/font_library_id/font_key/color/group_id/parent_id/gap_mm/anchor`）；`EngravingLayout` 加 `layout_slots: tuple[LayoutSlot,...] = ()`（空=回退旧两槽）。`Layer` 基类删 `locked_by_template/locked_manual`，新增 `bound_global_slot_id: str=""`（图层绑定到哪个全局槽位；与 `locked` 完全正交）。
- **`config_store.py`**：`_layout_to_payload`/`_layout_from_payload` 手写序列化里加 `layout_slots`（新增 `_slot_to_payload`/`_slot_from_payload`/`_slots_from_payload`，按 `fields(LayoutSlot)` 反射、忽略未知键、缺 `slot_id` 丢弃）。旧 JSON 无该键 → 空 tuple，**向后兼容、无需迁移脚本**。
- **`ui_app._toggle_layer_initial_pin`（面板🔒，列 #3）**：改为「写入/更新/移除全局槽位」——未绑定则 `_slot_from_layer` 快照出槽位（几何/类型/对齐/字体/`group_id`）写进 `product.defaults.layout_slots` 并设 `layer.bound_global_slot_id`；已绑定则从 `layout_slots` 移除该槽位并解绑。**全程不碰 `layer.locked`**。经 `with_product_defaults` + `save_config` 落盘。
- **`ui_app._toggle_selected_layer_locked`（右键锁）**：回退为纯 `layer.locked = not layer.locked`（编辑锁，禁拖拽/删除/微移，读点不变）。
- **解析主逻辑 `_replace_layers_from_parse_result`**：读 `_active_layout_slots()`；**有槽位**→`_clear_content_layers()`（递归清所有 Image/Text 含组合内、丢空组）+ `_build_layers_from_layout_slots`；**无槽位**→旧 fallback（清顶层 Image/Text + `_add_selected_flower_to_canvas`/`_add_text_layer_from_fields`）。
- **生成函数**：`_build_layers_from_layout_slots`（按 `z_index` 排序遍历）、`_build_image_layer_from_slot`（`_slot_image_asset`：`flower_image`=当前选中花素材；套 slot 的 x/y/w/h/rotation）、`_build_text_layer_from_slot`（`_slot_text_value` 按 `source_field` 路由：`name_text`=刻字内容、`blessing_text`=`result.gift_message`、`date_text`=`result.birth_month`；套 slot 几何 + `text_align`/`font_size`，复用 `_apply_auto_glyph_rules_to_layer` + `_resize_text_box_for_slot`〔真实字体测量重定框、右对齐以槽位右边界为锚〕）。`_slot_from_layer`/`_default_source_field`/`_group_id_of_layer`/`_layer_slot_state` 辅助。
- **UI 文案/指示**：图层行后缀 `[模板锁定]`→`[全局槽位]`；列 #3 图标 🔒/🔓 改读 `_layer_slot_state`（已绑定/可绑定）。**全局设置对话框**（`open_layout_settings`）新增槽位管理区：Treeview 列出当前 `layout_slots`（名称/类型/绑定字段/几何）+「删除选中槽位」+「应用字段」改 `source_field`（P1 最小：查看/删除/改绑定字段；新增/更新走图层🔒）。
- **兼容**：`_active_layout_defaults` 用 `dataclasses.replace(..., layout_slots=active_product(config).defaults.layout_slots)` 把槽位带过 11 字段 UI 往返，避免保存全局设置时丢槽位。LayerPin 读路径（`_pin_for`/`_layer_effective_production`，手动加层 seed 用）保留作旧兼容；新槽位**不再依赖** pin 的 `text:0` 共享 key。

**已知问题 / 未做（如实）**：
- **本轮按要求未写/未跑任何测试，未真机手测**。需手测：① 在画板加图片/文字、点面板🔒→行显示`[全局槽位]`、🔒 图标点亮、关 App 重开后 `birth_flower_config.json` 的 `products[].defaults.layout_slots` 里有该槽位；② 解析订单→按槽位生成图层（数量/位置=槽位），不再固定两层；③ 同类型加第 2 个槽位（如两个文字）→各自独立 `slot_id`，互不覆盖（已脱离旧 `text:0` 冲突）；④ 删光所有 `layout_slots` 后解析→回退旧「花图+名字」fallback；⑤ 右键锁定仍只禁拖拽/删除，与🔒槽位互不影响；⑥ 全局设置对话框槽位列表的删除/改绑定字段。
- **P0 已完成**：多槽位数据模型 + 序列化兼容 + 图层🔒写槽位 + 解析遍历槽位生成 N 层 + 无槽位 fallback。
- **P1 部分完成**：全局设置对话框有槽位列表（查看/删除/改 `source_field`）；图层🔒可更新已有槽位（`bound_global_slot_id` 复用同 id）；保留 `z_index`。**未做**：槽位的几何/对齐在对话框里直接编辑（目前只能改 `source_field`，几何更新靠在画板调好后再点🔒覆盖）、重命名槽位。
- **P2 仅预留结构未实现**：`LayoutSlot` 的 `group_id/parent_id/gap_mm/anchor` 字段已存但不消费；组合内 3mm/右对齐文字变长带动图片左移、多图片/多文本/自定义字段绑定 UI 均未做。
- **v1 数据源限制**：`flower_image`/`name_text`/`blessing_text`(=`gift_message`)/`date_text`(=`birth_month`) 可用；`custom_image_*`/`custom_text_*` 槽位结构支持但**暂无数据源 → 生成时跳过**（图片）或空文本。生成的文字层字体仍用解析选中的字体（非槽位冻结字体），与旧默认流程一致。槽位生成的图层目前是**扁平顶层**（不按 `group_id` 重建图组，P2）。第二道闸门 `flower_label_map.get(...) is None → return` 仍要求选中花素材，故「纯文字、无图片槽位」的产品在没选花时不会生成（v1 限制）。

**怎么跑**：桌面 App 入口 `python birth_flower_mvp.py`（在 `flower/`，用 `.venv-win`）。语法校验：`python -m py_compile ui_app.py models.py config_store.py`（本次已过）。

## 上次改动（已纠偏，2026-06-26）：图层面板🔒曾被做成「模板锁定」——方向已否决

> ⚠️ 本节是历史记录。该版把🔒做成 pin+`layer.locked=True`+`locked_by_template`（=禁拖动的「模板锁」），并新增 `_fill_template_*`/`_get_template_locked_layers`/`_template_group_scenes`/`_mm_to_px` 一套模板回填、以 `locked_by_template` 识别模板槽位。**用户判定方向错误**（核心需求是「全局设置多槽位 + 🔒写入全局槽位」，不是编辑锁），已在上面「本次改动」全部纠偏/删除。代码里这些字段/函数均已不存在，勿据本节找代码。

## 上次改动（2026-06-26）：提示词重构为「字段定义/值分离」三表模型

把原来「每套各持一份字段（定义+内容混在 `reference_fields` 一张表）」拆成 **全局唯一定义 + 按套独立值**，并补齐多套与跨作用域引用。用户拍板的 5 条规则：①字段定义全局唯一；②内容按产品独立；③序号按产品独立；④提示词套切换=编辑范围（一产品可多套）；⑤`/` 默认引用当前产品内容，也可选 `@global` 或 `@其他产品` 的绝对内容。**token/uuid 一律不展示给用户**（编辑器只显示 chip：`/名`、`/名 ·全局`、`/名 ·产品名`）。

- **`prompts_db.py`（整体重写）**：三表 `field_definitions`/`prompt_sets`(+`product_id`)/`field_values`。新 API：`load_prompt_set`(定义⨝值视图)、`list_sets_for_product`、`list_field_definitions`、`get_field_definition`、`create_product_set_with_all_fields`(新产品=给每个全局定义建空值)、`clone_prompt_set`(复制值、定义共享、不改 token)、`rename_prompt_set`/`delete_prompt_set`、`set_owner`/`assign_set_owner`。写路径约定见文件头 docstring（单字段 `allocate_field_in_set` 按名+类型 get-or-create canonical id；批量 `replace_prompt_set_fields` 只按 id upsert 定义、不按名去重；去重只在迁移做）。`_connect` 内置一次性 schema 迁移 `_migrate_legacy_reference_fields`：旧 `reference_fields` → 定义(按 归一化名+类型 去重、保最早 uuid)+值，并改写模板 token。
- **`prompt_references.py`**：token 值支持 `uuid@scope`；新 `split_field_value`/`scoped_field_token`/`GLOBAL_SCOPE`。`iter_template_segments` 加 `field_display` 回调（跨作用域 chip 显示定义名+徽标，绝不露 token）；`resolve_prompt_template` 加 `content_resolver` 回调（@global/@产品 内容）；`find_template_references` 去 `@scope` 后返回 bare id（删除保护可靠）。**当前套(无 scope)行为零变化**。
- **`config_store.py`**：`_migrate_prompt_sets` 给每产品一套独立 set + 回填 `product_id` 归属；共用同一 set 的产品 clone 拆独立。
- **`ui_app.py`**：新建产品走 `create_product_set_with_all_fields`（空内容、不复用旧套）；「提示词套」选择器改列**当前产品的套** + 新建/改名/删除（`_new_prompt_set_for_product`/`_rename_active_prompt_set`/`_delete_active_prompt_set`/`_switch_active_set`）；`/` 候选加 `@global`+其他产品字段（`_prompt_reference_candidates`）；chip 渲染/解析接 `_field_display`/`_scoped_content`（跨作用域在 UI 侧解析，`parse_pipeline` 不动——`resolve_prompt_template` 只在 ui_app 调用）。
- **测试**：`test_prompts_db` 加 clone 共享定义/独立值、新产品空值、全局唯一复用、旧表迁移去重等；`test_config_store` 拆分独立套；`test_reference_field_ui_mapping` 补 `_field_display` 桩。验证：`ruff`+`py_compile` 全绿；全量 `pytest tests/`(绕开缺 ezdxf 两文件) = **558 passed / 33 skipped / 0 fail，0 回归**。
- **真机手测待做**：①新建产品后字段结构全有、内容全空、与原产品互不影响；②同名字段在两产品复用同一定义、改名全产品生效；③`/` 选 `@全局`/`@其他产品` 插入 chip（显示名+徽标不露 token）、「预览」解析出对应内容；④提示词套 新建/改名/删除/切换；⑤改完**完全关掉 App 重开**再测。

## 上次改动（2026-06-26）：新建产品真正初始化 + 提示词改回「每产品一套独立」（已被本次的定义/值模型取代）

修两个真问题：① 新建产品不在 `prompts.db` 建任何数据，只抄当前产品的 `prompt_set_id`（全局共用的后遗症）；② 新建产品不初始化——布局/字体设置抄当前产品、画板（`self.document`）从不清空。

- **`prompts_db.py`**：新增 `clone_prompt_set(source_set_id, name=..., new_set_id=..., db_path=...)`——把一套复制成**独立**新套（新 `set_id` + 每个 field 重新分配 id + 同步改写 `prompt_template` 里的 `{{field:旧id}}`→新 id，否则模板引用全失效）。源套不存在抛 `KeyError`。
- **`config_store.py` `_migrate_prompt_sets`**：从「全局共用一套」改回**「每个产品一套独立 set」**。旧 config（无 `prompt_set_id`）按各自 payload 建套；历史共用同一 set 的产品——第一个保留原 set、其余 `clone_prompt_set` 各拆独立副本（不留孤儿）。幂等：每个产品都已唯一有效 set 时不动。
- **`ui_app.py`**：① `_create_product_from_dialog` 改 `defaults=EngravingLayout()`（空白默认布局）、`prompt_set_id=self._new_product_prompt_set(name)`（新增 helper：克隆当前套→独立新套，当前无套则建空套），结尾 `_switch_product(product_id, reset_document=True)`。② `_switch_product` 新增 `*, reset_document=False`；为 True 时 `self.document = Document(product.defaults.canvas_width, height)` 清空画板（普通切换仍保留画板）。
- **测试**：`tests/test_prompts_db.py` 加 `clone_prompt_set` 独立性/模板改写/缺源套 2 例；`tests/test_config_store.py` 把旧 `test_all_products_share_one_global_prompt_set` 改为 `test_products_get_independent_prompt_sets`（3 产品 3 套）+ 新增 `test_shared_prompt_set_is_split_into_independent_copies`（历史共用→自动拆分、保留原 set、幂等）。
- 验证：`ruff` clean；`pytest test_prompts_db / test_config_store / test_product_config_migration / test_reference_field_system / test_product_switcher / test_product_registry_config` = 全绿（59 + 17）。UI 两方法无无头测试覆盖（GUI 绑定），逻辑靠上述单测护栏；**真机手测待做**：新建产品后字段/布局/画板应全空、与原产品互不影响。

## 上次改动（2026-06-26，commit 81ab706）：提示词搬进 SQLite 共享库（全局共用一套）+ 修产品增删慢

把整套提示词从内嵌进 `birth_flower_config.json`（按产品各一份）搬进 flower 内独立 SQLite 库 `prompts.db`，并改成**所有产品共用同一套全局提示词**；顺带修产品新建/删除慢。

- **新增 `prompts_db.py`**（共享提示词库，SQLite）。对外 API：`load_prompt_set` / `list_prompt_sets` / `create_prompt_set` / `replace_prompt_set_fields` / `allocate_field_in_set` / `migrate_product_payload`。模型 = `PromptSet`（含 `reference_fields` / `field_seq_max` / `prompt_template` / `background_prompt` 等）。db 路径默认 = 主配置文件同目录的 `prompts.db`（`config_store.DEFAULT_CONFIG_PATH` 父目录）。`allocate_field_in_set` 用 `BEGIN IMMEDIATE` + 进程内锁**原子分配字段序号**。
- **`config_store.py`**：`ProductConfig` **删 6 个内嵌提示词字段**（`extraction_prompt` / `background_prompt` / `reference_fields` / `field_seq_max` / `prompt_template` / `template_version`），**新增 `prompt_set_id`**。`_migrate_prompt_sets` 改为「所有产品共用同一套全局提示词」（基线 = 当前激活产品那套；其余产品改指同一套）；`load_config` 时自动迁移并 `save` 一次，**幂等**（再次加载因已带 `prompt_set_id` 而跳过）。`with_product_reference_fields` / `with_product_prompts` / `create_product_reference_field_in_file` 转发到 `prompts_db` 按 `set_id` 操作（旧 `field_seq_max`/`template` 参数保留只为兼容签名）。
- **`ui_app.py`**：新增 `_active_prompt_set()` / `_active_reference_fields()` 从 db 取；`_persist_prompts` / `_add_field` / 字段增删改写 db；解析链路 `_current_ai_config` 用 `set.reference_fields`（`scope_id` 传 `set_id`）喂 `resolve_prompt_template`（下游 `gpt_parser`/`parse_pipeline` **未动**）；`_create_product_from_dialog` 新建产品直接带全局 `prompt_set_id`；新增「提示词套」选择器 `_render_prompt_set_selector`。**修复了 CURRENT_TASKS 上一条记的 `_load_field_defs_into_self` 读 `product.reference_fields` 必崩的 BUG**——现该方法（ui_app.py:4295）改读 `_active_prompt_set()`，`ProductConfig` 已无 `reference_fields` 字段。
- **性能（`asset_resolver.py` / `material_library.py` / `ui_app.py`）**：去掉资产主目录被扫两遍、合并重绘（`_suppress_redraw` + `_scan_assets` 加 `redraw` 参数）、库扫描按目录签名缓存、合并产品新建/删除的双 `save_config`、删除非激活产品不再触发全量重扫。
- **`tests/conftest.py`**：新增 autouse fixture `_isolate_prompt_store`，把测试用 config + `prompts.db` 重定向到临时目录（只作用于测试、`monkeypatch` 自动还原；生产用真实路径，不受影响）。
- 新增文件：`prompts_db.py`、`tests/test_prompts_db.py`（15 用例）。改：`config_store.py`、`ui_app.py`、`asset_resolver.py`、`material_library.py`、`tests/conftest.py` + 既有测试（`test_config_store` / `test_reference_field_system` / `test_reference_field_ui_mapping` / `test_ui_app`）。`.gitignore` 加 `prompts.db`（运行期产物，不入库）。

## 上次改动（2026-06-25）：Layer System v2 完成剩余全部 Packet

按 `docs/rfcs/layer-system-v2.md` 落地 Packet 0/1/2/3/4/6/7（Packet 5 由 codex 先行，见「上次改动」）。逐 Packet 子代理实现 + 逐 Packet 提交，每包跑 ruff/py_compile + 全量回归零退化。**核心红线全程守住：导出字节稳定（Packet 0 门禁）、桌面单一布局来源、未替换画布/渲染器/文字排版大脑/anchor。**

- **Packet 0**（`tests/test_layer_baseline.py` + golden）：内存构造生产形态 Document，连导两次 DXF/矢量 SVG 规整元数据（ezdxf GUID、`@ISO` 戳、`$TD*` 儒略日时间戳）后逐字节一致 + 导出 dict 结构金标。作为后续所有 Packet 的字节门禁。
- **Packet 1**（修 P1/P2，`models.py`/`ui_app.py`）：`HistoryManager` 加 `begin/commit/rollback_transaction`（幂等，cap 50）；新增**非模态属性栏 overlay**（`_open_inspector_overlay`，`CTkFrame` 不 `grab_set`/不 `wait_window`），绑现有共享 var，var trace→实时重绘，进入编辑 begin、失焦/回车/松手 commit、Esc rollback，位置夹紧视口；`_open_layer_geometry_dialog`/`_open_heart_anchor_dialog` 去 `grab_set`。flag `INSPECTOR_OVERLAY`（env=0 回退旧对话框）。
- **Packet 2**（修 P3，`ui_app.py`/`desktop_export.py`）：两个添加按钮合并为单一「+ 添加图层」→ 原生 `tk.Menu`（文字/图片素材/空白内容层/普通组合/自动布局组合，组合两项复用 codex Packet 5 处理器、<2 选中置灰）；空白内容层 = 未绑 `ImageLayer`，非零占位 + 虚线占位渲染；`_image_layer` 对从未绑过的空白层导出跳过+warning（不再崩）。
- **Packet 3**（ADR-001，新增 `providers.py`）：薄 `ContentProvider` + 模块级 `PROVIDERS` 注册表 + `get_provider`；`TextProvider`/`ImageProvider` 的 `render_export`/`render_preview` **委托既有函数**（算法零改动）；`models.Layer` 加 `provider_id`（不进导出 dict）；`_document_to_layer_document`/`_redraw_preview` 改查表分发；AnchoredHeart 保留专用路径。其余 §7 方法留 stub。
- **Packet 4**（§8/§15/§16，`models.py`/`providers.py`/`desktop_export.py`/`ui_app.py`）：**修复资源缺失崩溃**——已绑但磁盘缺失的素材导出跳过+warning、预览画「素材缺失」红框；`Document.schema_version` + `serialize`/`deserialize_document`（provider seam + `dataclasses.fields` 通用编解码、组递归）；`migrate_v1_to_v2`（复用 `__post_init__`）；未知 provider_id/构造失败 → `UnknownLayer` 持原始 dict 无损保留；最小 `ResourceRef`（未重构现有 font/material 字段）；flag `DOC_SCHEMA_V2`。
- **Packet 6**（§9/§10/§14，新增 `tools.py`）：`SelectTool`/`TextTool` 委托既有 `_on_canvas_*`/内联编辑（thin-registry，画布绑定不变，零回归）；provider 声明 `inspector_sections`/`capabilities`，悬浮栏改 `_inspector_rows_from_provider` 数据驱动；`TextLayer` 加 `layout_mode="box"`（= 当前行为不分支）+ `runs=None`（声明不填）。
- **Packet 7**（§16/§17，`providers.py`/`ui_app.py`）：填 `ContentProvider.validate`（有限正数尺寸 / 字号 / 缺素材）+ Inspector 写回 `math.isfinite` 拒绝 NaN/inf/负值；新增 `_on_canvas_pan_press`（中键平移）+ 绑定；**修复全部 7 个迁移期基线失败**（3 个真实缺口改实现：中键平移×2、`case_button` 孤儿；4 个陈旧期望订正：标尺 `target_px` 72→40、缩放步进 0.25→0.05、滚轮改纯缩放，均带注释）。

- 新增文件：`providers.py`、`tools.py`、`tests/test_{layer_baseline,inspector_packet1,add_layer_menu_packet2,providers_packet3,doc_serialize_packet4,tools_inspector_packet6,error_recovery_packet7}.py` + `tests/fixtures/layer_baseline_doc.json`。
- 验证：`ruff`/`py_compile` 全绿；全量 `pytest tests services/api/tests` = **622 passed / 0 failed / 33 skipped**（基线 547→599→622，**0 回归**，迁移期 7 失败全清）。

## 上次改动（2026-06-25，codex）：Layer System v2 Packet 5 自动布局组合

- `models.py`：新增 `AutoLayoutGroupLayer`、`auto_layout_group_layers()`、`convert_group_to_auto_layout()`、`resolve_auto_layout()`。自动布局为重绘/导出前的幂等 pass，支持 horizontal/vertical、gap、padding、align、justify、hug/fixed；隐藏子层不占位，坏尺寸压到 1px，循环/过深转 warning。普通组创建时也记录子层 union bounds。
- `ui_app.py`：图层 Treeview 改 `selectmode="extended"`；右键菜单新增「组合所选」「自动布局组合所选」「转换为自动布局组合」「解除组合」。预览前先 `resolve_auto_layout()` 再 `resolve_anchored_hearts()`，改用 `flat_render_layers()` 画叶子层。inline 文本编辑首次实改只压一次 history，Esc 取消弹掉该快照。
- `desktop_export.py` / `renderer.py`：矢量/PNG/SVG 导出前走同一 `resolve_auto_layout()` pass；未改 `_apply_canvas_fit`、文字排版大脑或导出服务算法。
- 测试：`tests/test_layer_auto_layout.py` + `tests/test_canvas_layer_redesign.py` inline 撤销边界。

## 上次改动（2026-06-25）：移除全部 GIMP 残留

本副本是「纯净 Python 桌面版」。GIMP-VB 实验轨道的模块（`gimp_editor/`、`gimp_bridge/`、`preview_render.py` 等）此前迁移时已删，仅剩死代码/配置/文档残留。本轮全部清掉：

- `ui_app.py`：删后端切换辅助（`_gimp_editor_enabled`/`_production_editor_backend`/`_legacy_editor_is_production_default`）→ 旧 Tkinter 画板成**唯一**生产编辑器（预览卡恒「实时画板」、画布尺寸编辑恢复可用）；删订单卡「在 GIMP 中编辑」整组 + 全部 `_*gimp*` 方法 + `_current_order_for_gimp` + `_order_seed_content_fields`；删产品右键的模板项（编辑/编译/配置内容/生成预览/发布/查看版本）+ 对应 `_product_*` 方法 + `_templates_dir`/`_create_template_draft`；「新建产品」对话框删模板来源（空白/复制/导入 XCF）。**保留产品 CRUD**（新建/启用/停用/删除）。
- `config_store.py`：删 `gimp_template_id` 字段 + `effective_template_id` 属性 + 序列化两处 + 死代码 `with_product_template`（旧配置含该键时加载侧自动忽略，向后兼容）。
- 删 `docs/gimp/`、`docs/adr/flower-image-engine-integration.md`、`docs/licenses/flower-editor-gpl-compliance.md`；`.gitignore` 去 GIMP 行；`dxf.py` 注释去 GIMP 字样。
- 测试：删 `tests/test_order_seed_fields.py`；改 `tests/test_product_registry_config.py`（去 GIMP 字段断言，留 status 迁移 + 未知键忽略）。
- 验证：`py_compile` + `ruff` clean；全量 `pytest tests services/api/tests` = **534 passed / 9 failed / 33 skipped**，9 个失败全是预存在的无头 Tkinter / 未实现功能缺口（见「已知问题」），**0 个由本次移除引入**（已逐条核对失败原因均与 GIMP/本次改动无关）。

## 目标 / 需求

- 保持纯 Python 桌面生产链稳定：解析 → 确认 → 画板编辑 → DXF/SVG/PNG 导出，预览==导出。
- EzCad 端闭环（导入 DXF + 填充/变黑宏）在**独立的 Ezcad 自动导入项目**做，非本仓库。详见 `CURRENT_TASKS.md`。

## 已知问题 / 未解决（诚实）

### 提示词搬进 SQLite 库（本次，commit 81ab706）的遗留风险

- **`prompts.db` 定为「运行期产物」、已加进 `.gitignore`、不做版本管理**。首次迁移后 `birth_flower_config.json` 不再含提示词（只剩 `prompt_set_id`）。**因此 `prompts.db` 一旦丢失或未随包发布，提示词即丢失。** 门店分发（`package-workbench` 打包）**必须把 `prompts.db` 一起带上**；目前**尚无导出/seed 机制**——这是待办风险。
- **「提示词专门编辑页面」是用户要求的后续工作，未做**。当前编辑仍在每个产品的「字段」卡 + 「提示词套」选择器（`_render_prompt_set_selector`）里。
- **「背景提示词」面板与 `prompt_template` 现写成同一值**（原 `background_prompt` 在解析链路本就恒空）；需后续确认是否要拆开。
- **`birth_flower_config.json` 被 gitignore、不在 git 历史**；首次用新版在真实 config 上跑前**建议先手工备份它**（迁移会就地改写它）。

### Layer System v2 / 其他遗留

- **真机 Tkinter 手测全部待做**（无头测不到，逐 Packet 的子代理报告里有详细清单）。关键项：①非模态属性栏开时画布仍可拖/缩/选其他层、改值实时重绘、连续改值一次 Ctrl+Z 复原、Esc 回滚；②「+添加图层」菜单五项 + 空白内容层占位 + 可后绑素材；③缺素材时画红色「素材缺失」占位框且导出不崩；④中键平移（`_on_canvas_pan_press`）；⑤改完务必**完全关掉 App 重开**再测（旧进程缓存旧模块）。
- **Inspector 悬浮栏目前只渲染 x/y/w/h/font_size**（= 旧「位置/尺寸」对话框字段集，手感一致）。字距/行距/对齐/颜色/字体已由 `TextProvider.inspector_sections` **声明**，但悬浮栏 write-back 白名单未接这些 key，故暂不在栏内显示（仍走右键 picker/内联编辑）。Packet 6 边界——给 `_write_inspector_vars_to_layer` 接新 key + 加进白名单即可显示，无需改 overlay 渲染循环（§14 扩展点已就绪）。
- **内联文字编辑仍走 codex Packet 5 的即兴 history 机制**（`inline_text_history_pushed` + 弹快照），未并入 Packet 1 的 `HistoryManager` 事务 API；两者不同入口、互不冲突。若要统一，把 `_start/_commit/_cancel_inline_text_edit` 改调 `begin/commit/rollback_transaction`。
- **AnchoredHeart 仍走专用导出/预览路径**，未 provider 化（设计如此，§20 保留）。
- **Document v2 序列化是新增能力但尚无「打开/保存文档」UI**（每次启动仍空白画布）。`serialize`/`deserialize_document` 已可用且有 round-trip 测试，待后续接存盘按钮（`DOC_SCHEMA_V2` flag 默认 ON）。
- **分支未 merge/push**：`layer-system-v2-rest`，逐 Packet 提交，待真机验证后再决定合回 main。基线 snapshot 提交把迁移期既有未提交工作（含 codex Packet 5）一并固化。
- `birth_flower_config.json` 历史上有明文 OpenAI key 误填风险；若仍在，建议改环境变量并轮换。

## 怎么跑 / 怎么测

- Python 解释器（本机）：`C:/Users/Administrator/AppData/Local/Programs/Python/Python312/python.exe`。或用 `.venv-win`（= CPython 3.12 全依赖；缺 numpy 时其它解释器会自动 re-exec 到它）。
- 跑 App：`.\.venv-win\Scripts\python.exe birth_flower_mvp.py`。
- 跑测试（**CWD = 仓库根**）：`PYTHONPATH=".;services\api" .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q`
  - 当前 Windows Temp 权限偶发阻断 pytest 清理时，可临时加：`--basetemp .pytest-tmp-run -o cache_dir=.pytest-cache-run`，跑完删除这两个目录。
- **本次提示词重构的关键测试**：`tests/test_prompts_db.py`、`tests/test_config_store.py`、`tests/test_reference_field_system.py`、`tests/test_reference_field_ui_mapping.py`、`tests/test_ui_app.py`（`test_ui_app` 较慢 ~3 分钟）。
- **flower 全量（绕开缺 ezdxf 的两个模块）**：`python -m pytest tests/ -q --ignore=tests/test_document_vector_export.py --ignore=tests/test_dxf_golden_lock.py`。
  - 既有失败（与本次无关）：`test_heart_symbol`×2、`test_layer_baseline`×2、`test_error_recovery_packet7` 的导出 smoke = 环境缺 `fontTools`/`ezdxf`；**直接跑全仓 `pytest` 会因 `services/api` 缺 `pydantic` 在收集阶段中断**。
- lint：`.\.venv-win\Scripts\python.exe -m ruff check <file>`。
- 致命坑：改完 Python 必须完全关掉 App 重开（旧进程缓存旧模块）；pytest 必须在仓库根跑（部分测试用相对路径）；首次在真实 config 跑前先备份 `birth_flower_config.json`（迁移就地改写）。

## automation 中间层（2026-06-26 从 `Documents\flower` 迁回）

**这是什么**：店小秘订单 → flower 的自动取单子系统，HTTP 解耦三段式：

```
flower 桌面App ──写采集任务/租约(8770)──▶ inbox-service(本地FastAPI服务) ◀──读授权去抓+回传── Chrome扩展(店小秘页)
   └ inbox_service_client.py(根目录,客户端,已在)      └ automation/inbox-service       └ automation/extension
```

- **inbox-service**（`automation/inbox-service`，FastAPI+SQLAlchemy+Alembic，独立 `.venv`、独立 `inbox.db`）：订单状态机 + 退款闸 + 批量导出 + **task-lease 任务租约**。租约是「多子代理」的核心——多个 flower 实例/扩展 worker 靠 `start/heartbeat/stop` 抢同一份采集授权，`is_authorized` = enabled且租约未过期且有 scrape_from（**fail-closed**，授权唯一判据见 `app/authorization.py`）。
- **extension**（`automation/extension`，Chrome MV3 + TS + Vite）：worker 子代理 paginate/rescrape/mark_writeback/ai_reconcile/auto_cycle，读 `GET /inbox/scrape/control.authorized` 决定跑不跑。
- flower 这边**只动 `inbox_service_client.py` 那一个客户端**（写采集开关/租约 + 读状态），不直连扩展。契约 9 端点已与服务端逐条对齐。

**怎么跑 / 怎么测**：
- inbox-service：`cd automation/inbox-service` → `.venv\Scripts\python -m alembic upgrade head`（建空库）→ `python -m uvicorn app.main:app --port 8770`（或 `automation\启动服务.bat`）。测试：`.venv\Scripts\python -m pytest -q`。
- 扩展：`cd automation/extension` → `npm install` → `npm run build`（产物 `dist/`，Chrome 加载已解压扩展）→ `npx vitest run`。

**已知 / 待验证**：
- 迁回时修了 `test_task_lease.py` 两个**时间炸弹测试**（`order_in_scope`/`paid_in_time_window` 缺 `now` 注入、写死 6/22 租约，过期后必红）：给两函数加可选 `now=None`（默认真实墙钟、**生产行为零变化**），测试改注入 `now=NOW`。这是源仓库就存在的红，非迁移引入。
- **真实抓单未端到端验证**：需本机 Chrome 装扩展 + 登录店小秘，本会话只验到「构建通过 + 单测通过 + 活体 healthz 链路通」。真机联调前请按 `automation/docs/real-machine-test-2026-06-19.md` / `inbox-smoke.md` 走。
- 验收快照（2026-06-26）：inbox-service pytest **190 passed**；扩展 vitest **144 passed**；flower 客户端契约（test_inbox_service_client/poller/config_store）**52 passed**；起服务后真实客户端 health/get_scrape_control/list_orders 全通。

## macOS 打包（.app/.dmg，GitHub Actions 云构建，2026-06-26）

**硬约束**：macOS `.app` 必须在 macOS 上构建（PyInstaller 不跨平台编译），Windows 出不了包。故走 GitHub Actions 的 `macos-latest`(arm64) runner 云端打包，产物为 `.dmg` artifact。完整操作见 `docs/macos-build.md`。

**新增文件**：
- `flower-macos.spec`：PyInstaller spec。datas 把只读素材（`BirthMonth flowers/`、`Birthmonth_font.ttf`、`glyph_maps/`、`assets/`、`templates/`）铺到 `_MEIPASS` 根；`services/api` 的 `app` 包靠 `collect_submodules('app')` 进 PYZ（spec 顶部把 `services/api` 加进 sys.path/pathex）；cairosvg 的 `libcairo` 等 brew dylib 显式收进 binaries；`upx=False`（Mac 必关）；`BUNDLE` 出 `.app`。
- `pyi_rthook_flower.py`：PyInstaller runtime hook（spec 的 `runtime_hooks`）。冻结态注入 `FLOWER_PROJECT_ROOT=_MEIPASS`（domain 层 `_project_root()` 命中随包资源）、`BIRTHFLOWER_DATA_DIR=~/Library/Application Support/BirthFlower`（可写数据根）、`FLOWER_PY_REEXEC=1`，并 `chdir(_MEIPASS)` 让默认相对素材路径在双击启动(CWD=/)时命中。**这是关键粘合层**。
- `.github/workflows/build-macos.yml`：`brew install cairo …` + `setup-python@3.12`(自带 Tcl/Tk) + `pip install -r requirements.txt` + `pyinstaller flower-macos.spec` + `hdiutil` 打 dmg + 上传 artifact。
- `docs/macos-build.md`：触发/安装/绕过 Gatekeeper（未签名）/已知限制。

**源码改动（4 处，全部向后兼容：env 未设时取值与改前完全一致，开发态零影响）**：
- `ui_app.py` `ensure_services_api_import_path()`：冻结态提前 `return`（原本找不到 `services/api` 目录会 `raise`，而 `_MEIPASS` 下无此目录、`app.*` 已在 PYZ）。
- `services/api/app/domain/fonts/scanner.py:13`、`fonts/options.py:13`、`orders/batch_store.py:18`：模块级常量 `PROJECT_ROOT` 改为优先读 `FLOWER_PROJECT_ROOT`（这 3 个是常量、import 时固化，runtime hook 的 env 救不了，必须改源码；其余 domain 层 `_project_root()` 是函数且本就读 env，hook 即可覆盖）。

**已知限制 / 待验证**：
- **本会话在 Windows 无法实跑 macOS 构建**——spec/hook/yaml 语法、YAML 结构、4 处改动向后兼容（services/api 相关测试 65 passed + 双向 env 验证）均已在 Windows 验过；但 PyInstaller 真打 `.app`、App 能否启动/导出，只能在 runner 上验，首次构建可能需 1–2 轮修 bundling（最可能：cairo dylib dlopen、customtkinter 主题数据、导出找不到模板——对策已写进 spec/hook）。
- `.app` **未签名公证**，首次打开需右键→打开或 `xattr -dr com.apple.quarantine`。
- 「改物理尺寸」回写 `templates/products/*.json` 在只读 `.app` 内不持久（首版接受）。
- 默认只出 **arm64**；Intel Mac 需另配 runner。
