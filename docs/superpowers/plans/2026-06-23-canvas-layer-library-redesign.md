# 画布 / 图层 / 素材库功能改版方案（交付 Codex 实施）

> 立项 2026-06-23。目标平台 = **Tkinter 桌面端 `ui_app.py`**（CustomTkinter 深色，分支 `claude/desktop-tkinter`）。本文件是设计稿，**不含正式业务代码**。
> **已与用户拍板的决策（v2，本文以此为准）：**
> 1. 平台 = Tkinter 桌面端。
> 2. 需求1「锁定初始位置」= **逐图层锁**（一个产品挂多张图层、各自独立锁），按**素材稳定身份**存到 `ProductConfig.layer_pins`；**含旋转 rotation**（快照自带，零成本）。
> 3. 图层面板 = **直接做 PS 风 `ttk.Treeview` 重构**。
> 4. 资源库命名 = **沿用文件夹名**。
> 5. 新增**需求5 撤销/重做（Ctrl+Z/Ctrl+Y）**：两套范围——(A) 画布编辑（图层 + 画布名字文字），(B) 输入框（订单备注框、文件名框）。**只撤画布编辑类**；配置类（锁定初始位置 / 加库 / 切产品）不进撤销；**换单载入清空撤销栈**。
> 6. 新增**需求6（产品区 A 切片，并进本轮）**：切换产品 / 启动时**重载该产品的几何**（激活休眠的 `ProductConfig.defaults` + 应用 `layer_pins`），修掉"切产品复用旧参数"。产品**删除/重命名/字段级联/多产品验证**=另起会话（见 §14）；产品界面操作**不进撤销**（手动配置）。
>
> 所有「现状」结论均带 `文件:行号` 证据。无法确认处标「待确认」。

---

## 1. 需求理解

| # | 需求 | 一句话目标 |
|---|------|-----------|
| 1 | 逐图层「锁定解析初始位置」 | 把某图层当前几何按**素材身份**升级为产品级持久锁定，之后任何订单只要又用到该素材就自动落到锁定位置（含旋转）；多图层各锁各的 |
| 2 | 画布尺寸实时显示 | 画布顶部缩放百分比同一行，实时显示 `画布：{w} × {h} px` |
| 3 | 每图层删除按钮 | 图层行右侧删除入口 + 清理（选中态/渲染/锚定爱心/临时态），无撤销跨界→二次确认 |
| 4 | 素材库 / 字体库区域 | 图层区下方列出现有库（真实数据，库名=文件夹名）+「添加」入口，**复用现有库系统** |
| 5 | Ctrl+Z 撤销/重做 | (A) 画布编辑（图层增删/移动/缩放/旋转/排序/改素材/改名）+(B) 输入框（备注/文件名）；配置类不进撤销；换单清栈 |
| 6 | 产品区 A 切片 | 切产品/启动重载产品级几何（激活 `ProductConfig.defaults`+应用 `layer_pins`），修「切产品复用旧参数」 |

**核心纠偏（与原 prompt 模板前提冲突）：**
- 不是 React——是 Tkinter 桌面 App，状态在 `BirthFlowerApp` 实例属性，持久化走 `birth_flower_config.json`。无 Zustand/Redux/LocalStorage。
- **不存在"全局锁定图层位置"功能**。唯一的锁是 per-layer `layer.locked`（禁拖动+禁删除），是需求文档里说的「另一个概念」。需求1 是**新建**能力。
- **Document（画布+图层）不落盘**，每单清空重建——所以"锁定位置"必须落到**持久的产品级 + 按素材身份**才能跨单生效。

---

## 2. 当前实现分析

### 2.1 锁定现状
- **无全局锁定设置**。`open_layout_settings()`（`ui_app.py:4587-4741`）只编辑默认几何，注释「全局默认值只初始化新建图层，不覆盖已有图层」（`4671`）。`AppConfig`/`ProductConfig` 无 `lock_*` 字段。
- **per-layer `layer.locked`**（`models.py:175`，默认 False）：拖动拦截 `_on_canvas_drag`（`ui_app.py:8192`）、删除拦截 `delete_layer`（`models.py:590`）、命中跳过 `hit_test`（`models.py:673`）、切换 `_toggle_selected_layer_locked`（`ui_app.py:6771`）。⚠️ 它是「编辑保护」不是「位置锁」，且不阻止属性面板改几何。

### 2.2 几何 / 生产参数解析链（需求1 复用基础）
- `ProductionParams`（`production.py:20-34`）：`x,y,width,height,rotation,font_size,lock_aspect_ratio`（全 `|None`）。`merge_onto`（`36-48`）本层非 None 覆盖 base；`resolve_chain(*levels)`（`89-102`）低→高合并。
- `_layer_effective_production`（`ui_app.py:6725`）= `resolve_chain(self._slot_defaults(layer), library_defaults, entry_defaults, layer.production)` —— **几何 SSOT**。
- `_slot_defaults`（`6695-6709`）读 `layout_from_values(self.layout_vars)`，按 `isinstance(TextLayer)` 返回 text/flower 槽几何。
- `_apply_layer_production`（`6757`）把属性面板编辑写进 `layer.production`（per-layer 临时 override）。

### 2.3 默认几何来源 + 产品切换（需求1/6 关键）
- `self.layout_vars`（`ui_app.py:1254-1266`）**从全局 `self.config.layout_defaults` 播种**（`1237`），**不是产品级**。
- `_active_layout_defaults`（`4747`）= layout_vars 几何 + 字体样式变量。`_save_current_config`（`7244-7255`）用 `replace` 写回**全局** `layout_defaults`。
- **`ProductConfig.defaults: EngravingLayout`（`config_store.py:116`）存在、会持久化（`_product_to_payload:618`/`_product_from_payload:601`），但休眠**：建产品写一次（`ui_app.py:4572`），无人回读；无 `with_product_defaults`（只有 `with_product_library_dirs:389`/`with_product_prompts:415`/`with_product_reference_fields:436`）。
- **`_switch_product`（`ui_app.py:1775-1791`）切产品时**：✅存 active_product_id、✅切素材/字体库重扫（`flower_dir_var`/`font_source_var`）、✅切提示词（`_load_prompts_into_widgets`）；❌**不重载几何**（`layout_vars` 不变）→ 这就是用户看到的「切产品复用旧参数」。`_render_product_rail`（`1665`）/ `_open_new_product_dialog`（`1793`）/ `with_added_product`（`config_store:380`）已有；**无删除/重命名产品**（无 `with_removed_product`/`with_renamed_product`/`_delete_product`）。
- `EngravingLayout`（`models.py:83-102`）：canvas 1732×1280、flower_x/y/w/h=310/40/1060/1060、text_x/y/w/h=808/830/804/260、text_size=190、bold/underline/italic、bold_strength、letter_spacing。**无 per-槽 rotation/scale**。
- **rotation 是真用的**（与"含旋转"决策直接相关）：`Layer.rotation`（`models.py:172`）在**预览**（`ui_app.py:7620-7627`）、**PNG**（`renderer.py:309/347`）、**SVG**（`svg.py:601`）、**DXF**（`dxf.py:1354`）、**批量**（`batch_generate.py:291`）全链路应用。生日花卡内容正放（=0），但贴纸/装饰可转。

### 2.4 画布工具栏 / 缩放 / 尺寸（需求2）
- `_build_preview_panel`（`ui_app.py:2859`）；缩放 % 在 `status_row`（`2864-2873`）`CTkLabel` 绑 `preview_zoom_status_var`（`1301`），刷新 `_update_preview_zoom_status`（`7765`）。
- `Document.canvas_width/height`（`models.py:380-384`，默认 1732×1280），`_redraw_preview` 每次同步（`ui_app.py:7326-7327`）。
- ⚠️ UI 唯一显尺寸处是 `_build_production_panel` 的**静态 Label**（`3422-3426`），永不更新。
- 改尺寸→重绘链路健全：layout_vars `trace_add` → `_redraw_preview`（`7266`）；`<Configure>`（`2906`）；`_reset_layout`（`7292`）。

### 2.5 图层列表 / 增删（需求3）
- **`tk.Listbox`**（`ui_app.py:2751`）+ 按钮组，`_build_layers_panel`（`2748-2808`）；**Treeview 重做未开工**。行文案 `_refresh_layers_panel`（`6651`）`"{👁/🚫}{🔒/🔓}{name}[{type}]"`。
- 选中 `document.selected_layer_id`（`models.py:386`）/`selected_layer()`（`450`）。事件：`<<ListboxSelect>>`→`_on_layer_list_select`（`6664`，反向索引）、`<Double-Button-1>`→`6016`、`<Button-3/2>`→`_show_layer_context_menu`（`5926`）。
- 删除 `_delete_selected_layer`（`6780`）→ `delete_layer`（`models.py:587-604`，锁定层拒删、自动选相邻、normalize_z）。**无系统层/不可删层**。
- ⚠️**缺陷**：删 `TextLayer` 不清其 `AnchoredHeartLayer`→孤儿（仅切走 Font4 时 `remove_anchored_heart_for`（`anchor_resolve.py:153-167`）才清）。
- ⚠️ `Listbox` 行内无法内嵌按钮 → 逐行操作必迁 `ttk.Treeview`。

### 2.6 素材库 / 字体库（需求4，大半已存在）
- 模型：`MaterialEntry`（`material_library.py:40-52`）、`MaterialLibrary`（`79-89`）、`library.json`（`_from_manifest:148-218`）、`LibraryBundle`（`order_catalog.py:29-65`）。
- 列表来源：`ProductConfig.image_library_dirs`/`font_library_dirs`（`config_store.py:114-115`，真实数据）。
- UI：`_build_library_panel`（`ui_app.py:3682-3726`，操作员配置端 `"library"` 卡）、`_render_library_rows`（`3699`，每种一行+「点击上传」）。
- 新增链路（已实现）：`upload_into_library`（`3728`）→`askdirectory`→`_add_library_folder`（`3739`）→`collect_importable_files`（`123-150`）→去重→`with_product_library_dirs`→`save_config`→`_scan_assets`（`6878`）→`_render_library_rows`。库=文件夹，名取 basename 或 library.json name。

### 2.7 状态 / 持久化 / 撤销（需求5/6）
- 内存态：`self.config`/`self.document`/`self.active_bundle`（`1231/1237/1239`）。
- **无撤销**：`HistoryManager`（`models.py:460-464`）空壳（带 `undo_stack/redo_stack: list[Document]`），`self.history_manager=None`（`1240`）。订单备注框 `self.remark_text: tk.Text`（`1281`，可开 `undo=True`），文件名框是 `tk.Entry`（无原生撤销）。
- 落盘：`save_config`（`config_store.py:233-260`，原子）只存 `AppConfig`，**零行写 Document**。路径：开发态 `flower/birth_flower_config.json`；冻结态 `<exe>/data/` 或 `%APPDATA%/BirthFlower/`（`_data_root:36-59`）。
- 迁移：`load_config`（`192-230`）逐字段容错；缺 products→`__post_init__`（`164-172`）合成产品0；保存统一 `dataclasses.replace`（`_save_current_config:7245` 注释了"整体重建会清空 products"坑）。
- **Document 不持久化**，每单 `_replace_layers_from_parse_result`（`~5297`）清 ImageLayer/TextLayer 重建。

---

## 3. 歧义与设计假设

| 编号 | 项 | 处理（v2 已定） |
|---|------|------|
| A1 | "全局锁定"不存在 | 需求1 新建，落 `ProductConfig.layer_pins`。 |
| A2 | 锁定属性集合 | 锁 `x/y/width/height + rotation`（TextLayer 另含 `font_size`）。pin 存 `ProductionParams` 快照，rotation 自带。 |
| A3 | 锁定粒度 | **逐图层**，按**素材稳定身份**键：image→`f"image:{library_id}:{material_key}"`（无 library/material 身份的临时导入素材回落 `f"path:{asset_path.name}"`）；text→`f"text:{slot}"`（当前单文本=`"text:0"`）。`AnchoredHeartLayer` 锚定文字、位置派生→**不可独立锁定**（pin 按钮禁用）。 |
| A4 | 锁定 vs 禁拖动 | 并存、不同图标：📌锁定初始位置（新）≠ 🔒`layer.locked`（旧=禁拖/删，留右键菜单）。 |
| A5 | 删除安全 | 无撤销跨界（删除属画布编辑、进撤销栈，但删除是重操作）→**仍二次确认**（双保险：确认 + 可 Ctrl+Z）。 |
| A6 | 资源库位置 | 操作员端图层卡下方新增资源库区，复用 `_render_library_rows`/`upload_into_library`。 |
| A7 | 库命名 | 文件夹名（取不到才回落 `素材库 {N}`）。 |
| A8 | 同一单两个相同素材 | 共用一条 pin（锁同处）。需"两份各锁不同位置"再按 `(material_key, 序号)` 细分——**当前不做**（用户未提此场景）。 |
| A9 | 撤销范围 | (A) Document 快照（图层+画布文字）+(B) 输入框原生；配置类（锁定/加库/切产品）不进；换单清栈。 |
| A10 | 产品几何归属 | 激活 `ProductConfig.defaults` 为**产品级基线几何**；切产品/启动 seed `layout_vars`；布局设置保存写产品 `defaults`（产品0 与全局等价，零回归）。 |
| A11 | web 并行 | 改 `config_store.py`/`models.py` 会被 services/api/web 共享序列化读到——动 git 前问用户（§14）。 |

---

## 4. 推荐方案摘要

1. **需求1（逐图层锁）**：新增 `LayerPin{key, production}` + `ProductConfig.layer_pins: tuple[LayerPin,...]`。新增 `config_store.with_product_layer_pins(...)`。`_pin_key(layer)` 算素材身份键；`_layer_effective_production` 的 resolve 链插入 pin（在 entry_defaults 与 layer.production 之间）。📌按钮→`_lock_layer_initial_position`（取当前几何快照 upsert pin + save）/`_unlock_layer_initial_position`（删 pin）。
2. **需求2**：`status_row` 加 `CTkLabel` 绑 `preview_canvas_size_var`，`_redraw_preview` 内刷新；删静态 Label（`3422-3426`）。
3. **需求3 + 面板**：`Listbox`→`ttk.Treeview`（行 👁/📌/名/类型/🗑 + 列命中 `return "break"` + Delete 键 + 拖动排序 + 嵌套组）；删除复用 `_delete_selected_layer`，补爱心清理 + 二次确认 + 锁定层禁删。
4. **需求4**：操作员端图层卡下挂资源库区，`_render_library_rows`→「每库一行+添加行」，复用 `upload_into_library`。
5. **需求5（撤销）**：接 `HistoryManager`，画布编辑前 `deepcopy(self.document)` 压栈，`<Control-z>`/`<Control-y>` 还原/重做 + 刷新面板；换单 `_load_*`/`_replace_layers_from_parse_result` 清栈；备注框 `tk.Text(undo=True)`、文件名 `tk.Entry` 补小助手。
6. **需求6（产品几何重载）**：激活 `ProductConfig.defaults`；`_switch_product`/启动 seed `layout_vars`（+ 同步画布尺寸/重绘）；布局设置保存改写产品 `defaults`（新 `with_product_defaults`）。
7. **SSOT 原则**：几何只走 `resolve_chain`（含 pin）；产品基线只走 `active_product(config).defaults`；库只走 `*_library_dirs`→`active_bundle`。

---

## 5. 页面布局与线框图

> 对话中已附深色 mockup（`flower_canvas_layer_library_redesign`）。下为 ASCII 线框（操作员端右侧功能区 + 画布顶栏）。

```
画布顶栏（_build_preview_panel / status_row）────────────────────────────
┌──────────────────────────────────────────────────────────────┐
│  画布：1732 × 1280 px   ｜   缩放：100%                         │  ← 需求2，同一行
└──────────────────────────────────────────────────────────────┘
                          （画布区域，白底木料，不变）

图层卡（_build_layers_panel → ttk.Treeview）──────────────────────────
┌ 图层 ─────────────────────────────────────────────────────────┐
│ 👁  📌  🌹 花朵 · Rose          [已锁定]                     🗑 │ ← 📌琥珀=已锁(按素材身份)
│ 👁  📌  ✿ 贴纸 · Heart         [已锁定]                     🗑 │ ← 多图层各锁各的
│ 👁  📍  🅰 文字 · Avery         继承产品默认                  🗑 │ ← 📍灰=未锁
│ 👁  ·   ♥ 末尾爱心（锚定文字·自动跟随）                     🗑 │ ← 不可独立锁定(无📌)
│ 🚫  🔒  ▦ 底板 · 已锁定图层                                 ⊘ │ ← layer.locked→禁删
│ ───────────────────────────────────────────────────────────  │
│ 📌 锁定初始位置=按素材身份升级产品级持久锁(含旋转)            │
│ 🔒 锁定图层=禁拖/删(右键)   Ctrl+Z 撤销画布编辑              │
└───────────────────────────────────────────────────────────────┘

资源库区（图层卡下方，复用 _render_library_rows）──────────────────────
┌ 素材库 ───────────────────────────────────────────────────────┐
│ 📁 BirthMonth flowers                              27 个       │
│ 📁 贴纸库                                           8 个       │
│ [ + 添加素材库 ]                                              │
├ 字体库 ───────────────────────────────────────────────────────┤
│ 📁 Birthmonth 字体                                  2 个       │
│ [ + 添加字体库 ]                                             │
└───────────────────────────────────────────────────────────────┘

空状态：素材库→「暂无素材库」+[+添加]   选中态：Treeview 行高亮、属性面板联动
禁用态：layer.locked 行🗑→⊘ 灰+提示「图层已锁定，先在右键菜单解锁」
```

图标（走 `line_icons.py` Tabler/MIT，零新依赖）：📌`ti-pin`（未锁灰/已锁琥珀）、🗑`ti-trash`、👁`ti-eye`/`ti-eye-off`。

---

## 6. 详细交互规则

### 需求1 逐图层锁定初始位置
- **📌（未锁→锁）**：算该图层 `_pin_key(layer)` → 取当前几何快照 `ProductionParams(x,y,width,height,rotation[,font_size])` → `with_product_layer_pins` upsert 进 `active_product.layer_pins` → `save_config` → 刷新行/重绘。可选清 `layer.production` 临时态（已烘进 pin）。
- **📌（锁→未锁）**：按 key 删 pin → save。该图层回落「产品基线 defaults → 全局 → 系统」。
- **优先级（resolve 低→高）**：系统 `EngravingLayout()` → 全局 `layout_defaults` → 产品基线 `ProductConfig.defaults`（槽位）→ library/entry 默认 → **`layer_pins`（按素材，持久）** → `layer.production`（会话拖拽临时）。对应「图层级 > 全局 > 默认」：layer_pins=图层级锁定结果。
- **状态展示**：行 📌 颜色 + chip「已锁定」，由 `_pin_key(layer) in {p.key for p in active_product.layer_pins}` 派生。`AnchoredHeartLayer` 不显 📌。
- **各事件**：重新解析/切单→新层按 `_pin_key` 命中 pin 自动落锁定几何 ✔；画布尺寸变→pin 存绝对 px 不缩放（可能偏移，提示重锁）；产品/模板切换→读该产品自己的 layer_pins ✔；项目重开→pin 持久化恢复 ✔；图层复制→同素材共用 pin；图层删除→不动 pin（重新加同素材再次命中）；撤销→锁定是配置保存，**不进 Ctrl+Z**。

### 需求2 画布尺寸
- 文案 `画布：{w} × {h} px`，缩放左侧、`｜` 分隔；`_redraw_preview` 内统一刷（已被所有改尺寸操作触发）；占位 `画布：— px`（任一维≤0）；`columnconfigure` 让两项不抖、不换行。

### 需求3 删除
- 触发：行尾 🗑（Treeview `<Button-1>` 命中 trash 列 `return "break"`）+ 底部按钮 + 右键 + `Delete` 键。
- 二次确认：`askyesno("删除图层", f"确定删除「{name}」？")`（锁定层不弹、提示「先解锁」）。
- 清理：`delete_layer`（自动选相邻/置空+normalize_z）→ 被删是 `TextLayer` 调 `remove_anchored_heart_for` → 清 `selected_preview_item`/拖拽态 → 刷新+重绘；`inline_text_entry` 编辑中禁删。删除本身**进撤销栈**（Ctrl+Z 可恢复）。

### 需求4 资源库
- 「+添加素材库/字体库」= 直接 `askdirectory`（沿用 `upload_into_library`），非弹窗填名、非建空库；导入后即时入列表 + `_scan_assets` 纳入候选 + `_refresh_library_choices` 刷下拉。每库一行（名+文件数）。

### 需求5 撤销/重做
- **(A) 画布编辑**：每个会改 `self.document` 的动作（加层/删层/拖动移动/缩放/旋转/排序/改素材/改文字内容/切 layer.locked）**执行前** `self.history_manager.push(deepcopy(self.document))`；`<Control-z>` = 当前压 redo、弹 undo 还原 `self.document` + `_refresh_layers_panel`+`_redraw_preview`；`<Control-y>`/`<Control-Shift-z>` 反向。栈深上限（如 50）防内存膨胀。
- **(B) 输入框**：备注框 `tk.Text` 加 `undo=True`（原生逐字撤销，绑 `<Control-z>` 时**焦点在 Text 内**优先走 Text 自身）；文件名 `tk.Entry` 加最小 undo 助手（记录每次变更值的小栈）或仅依赖系统行为。焦点路由：先判焦点控件是否输入框，是→走 (B)，否→走 (A)。
- **边界**：配置类（锁定初始位置 / 加库 / 切产品 / 改设置）**不**入 (A) 栈；`_load_db_order`/`_replace_layers_from_parse_result` 等**换单/重建**入口**清空** undo/redo 栈（不跨订单）。

### 需求6 产品几何重载
- 启动：`layout_vars` 改从 `active_product(config).defaults` seed（回落全局 `layout_defaults`）。
- `_switch_product` 末尾追加：从新产品 `defaults` 重灌 `layout_vars`（11 个 set）+ 同步 `document.canvas_*` + `_redraw_preview` + 清撤销栈。
- 布局设置保存：`_save_current_config`/`_save_settings_window` 几何写 `active_product.defaults`（新 `with_product_defaults`）而非全局（产品0 等价，零回归）。
- 产品**界面操作（切换/新建）不进撤销**（手动配置类）。

---

## 7. 状态与数据模型

```python
# config_store.py 增量
from production import ProductionParams   # 叶子模块，无循环

@dataclass(frozen=True)
class LayerPin:
    key: str                         # image:{library_id}:{material_key} | text:{slot} | path:{name}
    production: ProductionParams     # 锁定几何快照 x/y/w/h/rotation(/font_size)

@dataclass(frozen=True)
class ProductConfig:
    ...
    defaults: EngravingLayout = EngravingLayout()   # 已存在：激活为「产品级基线几何」
    layer_pins: tuple[LayerPin, ...] = ()           # 新增：逐图层(按素材身份)位置锁
    ...

def with_product_layer_pins(config, layer_pins, *, product_id=None) -> AppConfig: ...   # 仿 with_product_library_dirs
def with_product_defaults(config, defaults, *, product_id=None) -> AppConfig: ...        # 需求6：写产品基线几何
# 序列化：_product_to/from_payload 加 "defaults"(已有)+"layer_pins"；_pin_from/to_payload；非法项过滤
```

```python
# ui_app.py 运行态
self.preview_canvas_size_var: tk.StringVar       # 需求2
self.layers_tree: ttk.Treeview                   # 取代 layers_listbox
self.history_manager = HistoryManager()          # 需求5：接上空壳(models.py:460)

# 需求1 pin 解析（新）
def _pin_key(self, layer) -> str | None:         # AnchoredHeartLayer→None(不可锁)
    if isinstance(layer, TextLayer): return "text:0"
    lib = getattr(layer, "library_id", "") or ""; key = getattr(layer, "material_key", "") or ""
    if key: return f"image:{lib}:{key}"
    return f"path:{Path(layer.path).name}" if getattr(layer, "path", None) else None
def _pin_for(self, layer) -> ProductionParams | None:
    k = self._pin_key(layer)
    return next((p.production for p in active_product(self.config).layer_pins if p.key == k), None) if k else None
# _layer_effective_production 改：
#   resolve_chain(_slot_defaults(layer), library_defaults, entry_defaults, _pin_for(layer), layer.production)
```

> **不新增**：`ProductionParams`/`Layer`/`Document` 结构不动（pin 复用 ProductionParams 快照）。`Document` 仍不落盘。`HistoryManager` 用已存在的空壳，补 `push/undo/redo` 方法。

---

## 8. 组件和文件改动

| 文件 | 改动 |
|------|------|
| `config_store.py` | 加 `LayerPin`、`ProductConfig.layer_pins`、`with_product_layer_pins`、`with_product_defaults`；`_product_from/to_payload` 加 `layer_pins`；`_pin_from/to_payload`+校验 |
| `models.py` | `HistoryManager` 补 `push(doc, *, limit=50)`/`undo(current)->doc?`/`redo(current)->doc?`/`clear()`（纯逻辑、可单测）；结构不改 |
| `production.py` | 不改（rotation 已在） |
| `ui_app.py` | ①`_pin_key`/`_pin_for` + 改 `_layer_effective_production`；②`_lock_/_unlock_layer_initial_position`；③需求2 尺寸 Label + `_update_preview_canvas_size_status` + 删静态 Label；④`_build_layers_panel`→Treeview（行控件/列命中/Delete/拖序/嵌套组），改 refresh/select/context-menu/`_delete_selected_layer`（补爱心清理+确认）；⑤资源库区挂操作员端 + `_render_library_rows` 每库一行；⑥需求5 撤销（`history_manager`、mutation 前 push、Ctrl+Z/Y 绑定+焦点路由、换单清栈、Text undo=True、Entry 助手）；⑦需求6 `_switch_product`/启动 seed `layout_vars`、布局保存写产品 defaults |
| `line_icons.py` | 补 `ti-pin`/`ti-trash`/`ti-eye(-off)`（如缺） |
| `tests/` | 见 §12 |

**抽公共函数**：`_pin_key`/`_pin_for`/`_slot_defaults`（几何 SSOT）、`_layer_row_view(layer)`（行派生，纯函数仿 `order_row_view`）、`HistoryManager` 方法（纯逻辑）。

---

## 9. 数据流与持久化

| 数据 | 持久化 | 落点 | 迁移 |
|------|-----|------|------|
| 逐图层锁定（key+几何） | ✅ | `ProductConfig.layer_pins` → JSON | 缺→`()`，旧档零回归 |
| 产品基线几何（含画布尺寸） | ✅ | `ProductConfig.defaults`（激活休眠字段） | 缺→`EngravingLayout()`；产品0=全局快照 |
| 素材库/字体库 | ✅ | `ProductConfig.*_library_dirs`（已有） | 已有容错 |
| 图层本身/`layer.locked`/拖拽临时几何 | ❌ | 仅内存（每单重建） | — |
| 撤销栈 | ❌ | 仅内存、换单清空 | — |

- 旧版兼容：旧 JSON 无 `layer_pins`→`()`→不锁→行为同今日（零回归）。
- 一致性：`_redraw_preview` 是几何/尺寸刷新汇聚点；锁定/解锁/切产品后显式调它 + `save_config`。

---

## 10. 边界情况与错误处理

| 场景 | 处理 |
|------|------|
| 锁定时几何非法 | 锁前 `try/float` 校验；非法→状态栏提示、不写盘 |
| 无素材身份的临时导入素材 | pin 回落 `path:{name}` 键（弱稳定，文档化） |
| 同一单两个相同素材 | 共用一条 pin（A8）；状态栏提示「该素材已有锁定，已更新」 |
| 锁后改画布尺寸 | 绝对 px 不缩放→提示「画布尺寸已变，必要时重锁」 |
| 删最后/当前选中层 | `delete_layer` 置空/自动选相邻 |
| 删锁定层(layer.locked) | 🗑 禁用+提示，不弹确认 |
| 删带爱心文字层 | 连带 `remove_anchored_heart_for`，无孤儿 |
| 撤销跨订单 | 换单入口 `clear()` 栈，Ctrl+Z 不回上一单 |
| 撤销栈过深 | `push(limit=50)` 丢最旧 |
| 输入框 vs 画布 Ctrl+Z 冲突 | 按焦点路由：焦点在 Text/Entry→走原生(B)，否则→Document(A) |
| 资源库空/失败/重复/扫描错 | 空→空状态行；无有效文件→「未发现可导入文件」不改配置；路径重复→「已在库中」；扫描错→库区显错误行不崩 |
| 切产品 | seed 新产品 defaults + 清撤销栈；新产品 defaults 为系统默认时回落全局 |
| 快速连点 | 删除有确认防抖；添加 askdirectory 模态串行；锁定幂等（toggle）；全在 Tk 主线程无竞态 |

---

## 11. 验收标准（Given / When / Then）

1. **逐图层锁定** — Given 选中花朵层(material_key=rose)位置调到(400,120,转10°)；When 点📌；Then `active_product.layer_pins` 含 `image:...:rose` 且几何含 x400/y120/rotation10、配置已写、行显「已锁定」。
2. **多图层各锁各的** — Given 花朵(rose)+贴纸(heart)各锁不同位置；When 切下一单两素材都在；Then 花朵落 rose 锁定位、贴纸落 heart 锁定位，互不干扰。
3. **取消锁定继承默认** — Given rose 已锁；When 再点📌；Then pin 移除、下一单 rose 落产品 defaults。
4. **锁定 vs 全局冲突** — Given rose 锁=(400,120)、产品 defaults flower=310/40；When 新单建 rose 层；Then 落(400,120)。
5. **含旋转** — Given 贴纸转15°后锁；When 新单该贴纸重建；Then rotation=15°（预览+导出一致）。
6. **改画布尺寸实时显示** — Given 顶栏「1732 × 1280 px」；When 改宽 2000；Then 即时「2000 × 1280 px」、画布同步、无抖动。
7. **删普通图层** — When 删无爱心文字层确认后；Then 层消失、自动选相邻、剩余正确。
8. **删当前选中层** — Given 选中 B(A/B/C)；When 删 B；Then 选中跳 C（或 A）、属性面板联动。
9. **删最后一层** — When 删仅剩的层；Then `selected_layer_id=None`、列表空、属性面板「未选择图层」、无报错。
10. **删不可删层** — Given layer.locked=True；When 点🗑；Then 禁用+提示、层仍在。
11. **新增素材库** — When +添加选含 5 svg 文件夹；Then 列表新增该库行(名+5)、`image_library_dirs` 追加、素材下拉含新素材。
12. **新增字体库 / 失败** — +添加 2 ttf→字体库新增行；选空文件夹→「未发现可导入文件」、配置不变。
13. **撤销画布编辑** — Given 删了一层；When Ctrl+Z；Then 该层恢复、选中/预览还原；Ctrl+Y 再删。
14. **撤销不跨配置/订单** — Given 刚锁定一图层（或切了产品）；When Ctrl+Z；Then 锁定/产品**不**被撤；换单后 Ctrl+Z 无效（栈已清）。
15. **输入框撤销** — Given 备注框输入若干字；When 焦点在备注框 Ctrl+Z；Then 逐字回退，不影响画布图层。
16. **切产品重载几何** — Given 产品 P1 花朵 defaults=(310,40)、P2=(500,200)；When 切到 P2；Then `layout_vars`/画布按 P2 几何刷新（不再复用 P1）。
17. **刷新后恢复** — When 锁了素材、加了库、设了产品几何后完全关 App 重开；Then 全恢复、新单素材落锁定位。
18. **旧档无新字段** — Given 旧 JSON 无 `layer_pins`；When 启动；Then 不报错、`layer_pins=()`、零回归。
19. **快速连点新增/删除** — 不重复入库、不重复删、状态一致。

---

## 12. 测试方案

**单元（纯函数，`.venv-win`）**
- `config_store`：`with_product_layer_pins`/`with_product_defaults` 写对目标产品；`layer_pins` 序列化往返；旧档缺字段→`()`；非法 pin/槽名过滤。
- `HistoryManager`（models.py）：push/undo/redo/clear 序列正确、limit 丢最旧、空栈安全。
- `_pin_key`：image 有/无 material_key、text、AnchoredHeart→None、临时导入→path 键。
- `_layer_row_view`：visible/locked/pinned/deletable 派生（locked→deletable False、AnchoredHeart→pinnable False）。

**组件（Tk root，多数 headless skip）**
- `status_row` 含尺寸 Label，改 `document.canvas_*`+`_redraw_preview` 后更新。
- `_build_layers_panel`(Treeview)：行数=层数、列含 👁/📌/名/类型/🗑、locked 行🗑禁用、AnchoredHeart 无📌。
- `_render_library_rows`：N 库→N 行+添加行；空→空状态。

**集成**
- 锁定→`save_config`+`load_config`→`_pin_for` 返回锁定值（含 rotation）。
- 删带爱心 TextLayer→无孤儿 AnchoredHeartLayer。
- 切产品→`layout_vars` 变为新产品 defaults + 撤销栈清空。
- 加库→`_scan_assets`→`active_bundle` 含新素材。
- 撤销：删层→Ctrl+Z→document 还原；换单→栈空。

**端到端（真机重开 App）**
- 真单：花/贴纸各锁不同位（含转角）→切下一单各自命中；切产品几何切换；改画布尺寸顶栏实时；逐行删/锁定层禁删；Ctrl+Z 撤删/撤移动；加库即时可选并导一单核 DXF 实体类型不变（R2018+SPLINE/POLYLINE）+ rotation 正确。
- 备注框/文件名框 Ctrl+Z 不误伤画布。

**手工回归**
- 未锁产品金标/批量字节零变化；预览==导出 `fit_text_box` 不破；`pytest tests services/api/tests`（历史 358 passed，8 既有 headless 失败：preview zoom/pan/ruler×6+case_button+field_instructions——Treeview 重写会再动 `test_ui_app.py`，需同步更新这批）。

---

## 13. Codex 实施任务清单（按依赖顺序）

| # | 任务 | 目标 | 涉及文件 | 前置 | 完成条件 | 风险 |
|---|------|------|---------|------|---------|------|
| 1 | 产品级几何基线（需求6 半） | 启动+`_switch_product` seed `layout_vars` 自 `active_product.defaults`；布局保存写产品 defaults（`with_product_defaults`）。**先不引入 pin** | `config_store.py`,`ui_app.py` | — | 切产品几何切换（验收16）、产品0 零回归 | 布局保存改产品级误伤全局→产品0 等价测试守 |
| 2 | 扩数据模型 pin | `LayerPin`+`ProductConfig.layer_pins`+`with_product_layer_pins`+序列化/迁移/校验 | `config_store.py`,`production.py(import)` | — | 往返+旧档迁移单测 | 迁移非法值→`_pin_from_payload` 守卫 |
| 3 | 逐图层锁定逻辑 | `_pin_key`/`_pin_for`+改 `_layer_effective_production`；`_lock_/_unlock_layer_initial_position`；resolve 链插 pin | `ui_app.py` | 1,2 | 验收1-5、17 | pin 键不稳→AnchoredHeart/临时素材回落规则测 |
| 4 | 画布尺寸显示 | status_row 加 Label+`_update_preview_canvas_size_status`；删静态 Label | `ui_app.py` | — | 验收6 | 与缩放抢列→columnconfigure |
| 5 | 图层面板 Treeview 重构 | Listbox→Treeview：行 👁/📌/名/类型/🗑+列命中`break`+Delete+拖序+嵌套组（接 `group_layers/ungroup_layer`）；改 refresh/select/context-menu | `ui_app.py` | 1,3 | 行/选中/拖序/右键可用（真机） | **工作量最大**；冲掉 listbox 测试需重写；真机拖放手测 |
| 6 | 删除+清理 | 行🗑+按钮+右键+Delete→`_delete_selected_layer` 补爱心清理+二次确认+锁定层禁删 | `ui_app.py`,`models.py?` | 5 | 验收7-10 | 列命中`break`防误选 |
| 7 | 资源库区 | 操作员端图层卡下挂；`_render_library_rows`→每库一行+添加行；复用 upload | `ui_app.py` | — | 验收11-12 | 勿动 `_add_library_folder` 数据逻辑 |
| 8 | 撤销/重做（需求5） | `HistoryManager` 补方法；mutation 前 push；Ctrl+Z/Y 绑定+焦点路由；换单清栈；Text undo=True+Entry 助手 | `models.py`,`ui_app.py` | 5,6 | 验收13-15 | **mutation 点易漏**→列清单逐个插；与 Treeview 编辑交互测 |
| 9 | 持久化+图标 | 串 1/2/3/6 保存读取；补 `line_icons.py` | `config_store.py`,`ui_app.py`,`line_icons.py` | 1-3 | 验收17-18 | — |
| 10 | 测试 | 补 §12 单元/组件/集成；更新被 Treeview 改的既有测试 | `tests/` | 1-9 | 直接相关全绿、基线不退 | headless skip 边界 |
| 11 | 完整回归 | 真机重开跑 e2e+导一单核 DXF；金标/批量字节核对 | — | 1-10 | §12 e2e 全过、零回归 | 须真机；改完**必须完全关 App 重开** |

> 1、2、4、7 可并行；3 依赖 1+2；5/6 依赖 3；8 依赖 5+6；9 依赖 1-3；10/11 收尾。

---

## 14. 风险与待确认事项

**已定（不再议）**：平台=Tkinter；逐图层按素材身份锁、含旋转；库名=文件夹名；撤销 A+B、配置不进、换单清栈；产品几何重载(A)并入本轮。

**另起会话的后续项（产品区 B，本轮不做）**
1. **删除产品**（含兜底：不能删最后一个/删当前激活先切走/连带其 layer_pins+库引用清理）。
2. **重命名产品**（id 稳定、name 可改；注意 layer_pins 的 key 含 library_id 不含 product，重命名不影响 key）。
3. **人工确认面板字段随产品级联**、每产品输出设置、**多产品端到端验证**。
> 建议在本轮 `layer_pins`/`defaults` 数据模型落地**之后**做 B，否则删除/切换产品还要回头处理 pin。

**待确认（影响后续，非阻塞本轮）**
- A8：是否会出现"同一单两个相同素材各锁不同位置"？是→pin 键需加序号。当前按单素材身份。

**风险**
- **R1 Treeview + 撤销波及面大**：`test_ui_app.py` 多个 listbox 用例 + 8 既有 headless 失败需重写；撤销的 mutation 插点易漏；真机拖放/Ctrl+Z 依赖手测。
- **R2 web 前端并行**：用户在同分支改 `apps/desktop`；本方案改 `config_store.py`/`models.py`（`layer_pins`/`HistoryManager`）会被 services/api/web 共享序列化读到——动 git（commit/switch）前先对齐。
- **R3 激活休眠 `ProductConfig.defaults`**：建产品时写过旧快照（`ui_app.py:4572`）。任务1 seed/保存必须保证产品0 与全局 `layout_defaults` 等价（测试守），否则旧快照污染。
- **R4 撤销内存**：`deepcopy(document)` × 栈深；limit=50 + 换单清栈控制。
- **R5 改完不重开 App**：模块缓存旧码；e2e 前完全关闭重开。

---

## 15. Codex 执行摘要

> 一句话：Tkinter 桌面端 `ui_app.py` 上——①把图层「锁定初始位置」做成**按素材身份**的产品级持久锁（`ProductConfig.layer_pins`，含旋转，多图层各锁各的，经 `resolve_chain` 解析）；②画布顶栏缩放同行加实时尺寸；③图层列表升级 PS 风 `ttk.Treeview`（逐行 可见/锁/删除）并补删除清理与二次确认；④图层区下方复用现有库系统挂资源库区；⑤接 `HistoryManager` 做 Ctrl+Z 撤销（画布编辑 A + 输入框 B，配置/换单不进）；⑥切产品/启动重载产品级几何（激活 `ProductConfig.defaults`）。**不新建资源系统、不大改无关链路、不加第三方依赖、Document 仍不落盘、产品 CRUD 另起会话。**

**起手三件事**：① 确认在分支 `claude/desktop-tkinter`（main 引擎旧）；② 跑基线 `$env:PYTHONPATH=".;services\api"; .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q`（记 8 既有失败）；③ 从任务1（产品级几何基线，先不引 pin）起，每步改完**完全关 App 重开**再验。

**红线**：未锁产品零回归（金标/批量字节不变、产品0 与全局几何等价）；预览==导出 `fit_text_box` 不破；pin 键稳定（AnchoredHeart 不锁、临时素材回落 path）；撤销不碰配置/不跨订单；动 git 前问用户（web 前端并行同分支）。
</content>
</invoke>
