# RFC: 图层系统与文字工具重构（Layer System v2）

> 状态：草案（Draft），供 Codex 分阶段执行。
> 范围：`flower` 纯 Python Tkinter 桌面编辑器（`ui_app.py` + `models.py` + `text_*.py` + `renderer.py` + `desktop_export.py`）。
> 事实基准：本 RFC 全部结论引用 2026-06-25 当前代码真实符号；不虚构结构，推断处标注「假设」。
> 调查方法：8 路并行只读调查 + 人工复核关键交互代码（`_open_layer_geometry_dialog`、`_on_canvas_press/drag/release`、`_draw_selection_box`、`hit_test`）。
> 红线（来自 `PROJECT_INDEX.md` / `docs/ui_app_frontend_overview.md` 第 10 节）：**没有新字段的旧数据，导出字节必须不变**；**桌面是单一布局来源**（复用 `EngravingLayout` / `layout_defaults` / `_apply_canvas_fit`）；**不替换画布、渲染器、文字排版大脑、anchor 机制**。

---

## 0. 重要前置说明（读者必看）

1. **本仓库不存在 React / Fabric.js / TypeScript 编辑器。** `apps/`、`packages/`、`packages/design-core` 已在迁移时移除（见 `PROJECT_INDEX.md` 顶部），`flower/apps/**` 与 `flower/packages/**` 均无文件。任务描述中的 web 词汇（Store、pointer capture、modal portal、providerId、Scene Graph、requestAnimationFrame）是**通用架构语言**，本 RFC 一律映射到 Tkinter 真实机制（`tk.Toplevel` / `grab_set` / `bind` / `root.after` / `canvas.find_closest`）。

2. **`docs/LAYER_MODEL.md` 描述的是已删除的 TS 模型**（`schemaVersion`、`fontRef`、`assetRef`、`validateLayerDocument`），**不是当前 Python 实现**。但它是一份与本 RFC 目标几乎一致的**前期设计稿**（通用字段 + type 判别 + 资源引用），本 RFC 在资源模型一节将其作为蓝本引用，并明确区分「已实现」与「蓝本」。

3. **截图未随本轮上下文提供。** 任务提到「附带的文字悬浮工具栏截图」，但当前对话中无图像可读。**假设**：非模态属性栏的字段集 = 当前模态对话框已有字段（位置 X/Y、宽、高、字号）+ TextLayer 已有属性（字距 `letter_spacing`、行距 `line_spacing`、对齐 `align`、颜色 `color`）。视觉细节留待 Packet 1 与真实截图核对，不在本轮重做无关界面。

---

## 1. 背景与用户问题

`flower` 是「生日花卡」订单驱动的雕刻素材生成桌面工具：订单备注 → 解析字段 → 画板编辑（选层/移动/缩放/换素材/换字体）→ 导出 DXF/SVG/PNG 给 EzCad 雕刻。编辑器是**唯一生产编辑器**（`birth_flower_mvp.py` → `ui_app.py`，9101 行）。

当前一张卡 = 一个 `ImageLayer`（花素材 SVG）+ 一个 `TextLayer`（顾客名字），可选一个 `AnchoredHeartLayer`（名字末尾爱心）。

用户提出的 11 项问题，归并为 5 个真实痛点：

| # | 用户问题 | 真实痛点 |
|---|---|---|
| P1 | 右键「编辑属性」弹窗后无法继续操作画布 | 模态对话框 `grab_set()` 抢占输入 |
| P2 | 想要非模态悬浮属性栏，实时渲染，画布仍可拖/缩/选，双向同步 | 缺非模态 Inspector + 缺事务化实时预览 |
| P3 | 「+文字图层」「+图片图层」合并为「+添加图层」，且为未来内容类型（形状/二维码/SVG/滤镜）留扩展 | 添加入口分裂；类型分发靠散落 isinstance |
| P4 | 需要普通组合 + 自动布局组合，文本变长时素材↔文字间距不变 | 有 `GroupLayer`（未接 UI），无通用 auto-layout 引擎 |
| P5 | 文字工具为类 GIMP 高级能力留空间，但不一次实现 | 工具与内容数据未分层，字段硬编码进 UI |

---

## 2. 当前架构地图（全部引用真实符号）

### 2.1 数据模型 `models.py`

| 符号 | 行 | 说明 |
|---|---|---|
| `Document` | 376-383 | `canvas_width=1732`、`canvas_height=1280`、`layers: list[Layer]`、`selected_layer_id: str\|None`。**无 `to_dict`/`from_dict`、无 `schemaVersion`、无磁盘持久化**——只在会话内存活。 |
| `Layer`（基类） | 156-174 | `id`（`uuid4().hex`，`_new_layer_id` @140）、`name`、`type='base'`、`x/y/width/height`、`scale_x/scale_y`、`rotation`、`opacity`、`visible`、`locked`、`z_index`。**无 `parentId`、无 `blendMode`、无 `schemaVersion`。** |
| `ImageLayer` | 181-202 | `type='image'`；`path`、`preserve_svg`、`material_id`、`material_name`、`lock_aspect_ratio`、`library_id`、`material_key`、`production`。`__post_init__` 把旧 `material_id`→`material_key`。 |
| `AnchoredHeartLayer` | 204-223 | `type='anchored_heart'`，继承 ImageLayer；`anchor_layer_id`、`anchor_mode='text_end'`、`gap_mm`、`offset_y_mm`、`size_mm`、`fill_color`。**几何由 `anchor_resolve.resolve_anchored_hearts` 每帧重算**（关键：见 §13）。 |
| `TextLayer` | 225-303 | `type='text'`；`text`、`raw_text`、`original_text`、`render_text`、`glyph_overrides`、`font_path`、`font_size=120`、`color`、`fill_color`、`align='center'`、`vertical_align='middle'`、`line_spacing=1.2`、`tracking`、`letter_spacing`、`text_box_width=400`、`text_box_height=160`、`font_library_id`、`font_key`、`production`、`bold/underline/italic`、`bold_strength`、`ending_heart`、`ending_heart_detached`。 |
| `GlyphLayer` | 353-360 | `type='glyph'`；`codepoint`、`font_path`。保留未用。 |
| `GroupLayer` | 362-374 | `type='group'`；`children: list[Layer]`、`collapsed`。可见/锁定级联子孙。**Stage-1 模型已落地。** |
| 判别方式 | 162 + isinstance | 字符串 `type` 字段 + `isinstance` 双轨。 |
| `EngravingLayout` | 82-102 | frozen dataclass，画布 + 花/文字坐标 + `text_size=190` + 字体样式默认。**布局单一来源。** |
| `HistoryManager` | 457-483 | 快照式撤销：`push()` = `deepcopy(Document)`，`undo_stack`/`redo_stack`，上限 50。 |

图层操作函数（全在 `models.py`）：`add_image_layer`(486)、`add_text_layer`(529)、`move_layer`(626)、`delete_layer`(606)、`duplicate_layer`(797)、`reparent_layer`(735，含组循环检测)、`group_layers`(652)、`ungroup_layer`(674)、`make_combined_layer`(~698，把 material+text 包成 `GroupLayer`)、`hit_test`(716)、`normalize_z_indexes`(438)、`_flat_leaves`/`flat_render_layers`/`sorted_layers`。

> **关键发现**：`group_layers` / `ungroup_layer` / `make_combined_layer` **已实现且可用，但从未被 `ui_app.py` 调用**（仅 `_group_contains` @6746 用于拖拽防循环）。组合的「模型层」已就绪，缺的是「UI 层」。

### 2.2 添加图层 + 图层列表 `ui_app.py`

| 符号 | 行 | 说明 |
|---|---|---|
| `+ 文字图层` / `+ 图片图层` 按钮 | 3446-3450 | 分别调 `_add_text_layer_from_fields`(7713)、`_add_selected_flower_to_canvas`(7649)。 |
| `self.layers_tree` | 3401-3435 | `ttk.Treeview`，列 `(asset, visible, pin, delete)`，`show='tree headings'`，嵌套支持 GroupLayer。 |
| `_render_layers_tree` | 6497-6539 | `tree.delete(*get_children)` 后递归 insert；**全量重建 tree**（但行内 widget 复用见红线 #4）。 |
| `_open_layer_resource_picker` / `_add_resource_cascades` | 6987 / 6946 | 点 asset 列或右键 → `tk.Menu` 级联选素材/字体（**用原生 `tk.Menu` 避开 CustomTkinter 引用泄漏**）。 |
| `_on_layer_material_changed` / `_on_layer_font_changed` | 6784 / 6819 | 换素材/字体**保留几何**（不清 `production`）、push undo。 |
| 拖拽排序 | 6655/6688/6703/6721 | `_on_layers_tree_button_press/release`、`_tree_drop_position`（before/after/inside）、`_reparent_tree_layer`→`reparent_layer`。 |
| 隐藏全局选择器 | 1088/1160 | `flower_asset_var`/`font_asset_var`、`flower_label_map`/`font_label_map`——parse/扫描仍依赖，按计划最后才移除。 |

> 「空白叶子层」工作流（`CURRENT_TASKS.md` §C）**仅规划，未实现**。当前添加流程总是带默认值或从 picker 选值，不产生零尺寸隐形层。

### 2.3 选择 / 命中 / 变换 `ui_app.py`

| 符号 | 行 | 说明 |
|---|---|---|
| `_on_canvas_press` | 8862 | 命中：先 `canvas.find_closest` 查 `selected_layer_handle` tag（resize 手柄）；否则 `hit_test(document, doc_x, doc_y)` 查图层。空白 → `_drag_mode="pan"`。设 `selected_layer_id`。 |
| `_on_canvas_drag` | 8914 | 首帧 push 一次 undo（`_drag_history_pushed` @8929）；按 `_drag_mode` 与图层类型分发（AnchoredHeart→mm、Text→`CanvasTextItem.move_by/resize_by`、else→x/y/w/h）。 |
| `_on_canvas_release` | 8968 | 复位 `_drag_target/_drag_start/_drag_history_pushed`。 |
| `_on_canvas_double_click` | 8644 | 双击 TextLayer → `_start_inline_text_edit`。 |
| `hit_test` | models.py 716 | 自顶向下，仅可见+未锁定叶子的 AABB 包围盒。**忽略旋转。** |
| `_draw_selection_controls` / `_draw_selection_box` | 8597 / 8606 | 虚线矩形（`selected_layer_box`）+ **唯一右下角 8px resize 手柄**（`selected_layer_handle`）。**无四角手柄、无旋转手柄。** |
| `_preview_transform` | — | `(scale, offset_x, offset_y)`，screen↔doc 坐标；pan 仅改 `preview_pan_x/y`（视口，不动文档）。 |

> 旋转：`Layer.rotation` 字段存在，**UI 无旋转入口**。

### 2.4 文字编辑 + 属性弹窗 `ui_app.py` + `text_*.py` + `canvas_text_item.py`

| 符号 | 行 | 说明 |
|---|---|---|
| **`_open_layer_geometry_dialog`** | **7042-7066** | **「位置/尺寸」模态对话框 = P1 根因。** `ctk.CTkToplevel` + `transient` + **`win.grab_set()` @7066**。复用共享 var `layer_x/y/w/h_var`、`layer_font_size_var`，仅在「应用」按钮 → `_apply_layer_production` 提交。**编辑过程中画布不实时渲染**（输入完才应用）。 |
| `_open_heart_anchor_dialog` | 7068+ | 「末尾爱心」模态对话框（gap/offset/size mm），同样 CTkToplevel + grab。 |
| `_start_inline_text_edit` / `_commit_inline_text_edit` | 8659 / 8797 | 画布内联文字编辑，**非模态、无 grab**，经 `CanvasTextItem`/`FloatingTextEditor`（`canvas_text_item.py`）。 |
| `_apply_layer_production` | 7287-7318 | push history → 写 `x/y/width/height/font_size` + `layer.production`。 |
| `_sync_layer_properties` | — | layer → 共享 var（选层时调用）。 |
| `compute_text_fit` / `fit_text_box` | anchor_resolve 40-71 / `text_layout` | **文字排版大脑**：自适应字号、断行、基线 origins，预览==导出。`layer.font_size` 退化为字号上限 cap。 |
| `render_layer` / `_valid_font_path` / `_load_font` | text_renderer 72/168/177 | 同步 Pillow 加载，失败回退默认字体。 |

> 现有文字能力：box 布局（`text_box_width/height`）、align、vertical_align、line_spacing、tracking/letter_spacing、字号 cap、glyph_overrides（PUA 结尾字形）、ending_heart。**无显式 point-text / auto-width / auto-height / fixed-frame 模式切换；当前 layout `mode='box'` 单一。**
> 死代码：`_cycle_text_case`(5820) 引用 `self.case_button`(5825) **从未赋值**（调用即 AttributeError）。

### 2.5 字体 / 素材

- **字体身份** = 文件名数字 → `Font {index}`（`asset_resolver._font_asset` 84-93），**无月份映射**。TextLayer 经 `font_path`（主）+ `font_library_id`/`font_key`（新）引用。
- **素材** = `material_library.MaterialEntry`(40)，`key` slug；`MaterialLibrary`(80)；`LibraryBundle`(order_catalog 29)。`enrich_parse_result`(65-120) 解析 key→path，缺失记 warning。
- **资源丢失行为不对称**：缺字体 → 降级（warning + 默认字体，text_renderer 168/177）；**缺图片 → 导出时崩溃**（`desktop_export._image_layer` 152-170 抛 `ValueError("素材文件不存在")`）。**无占位符。**
- **无 resource-ref / revision / linked-vs-embedded 概念。** `_font_ref`(desktop_export 322) 仅导出 path 或回退 family `"Birthmonth"`。

### 2.6 渲染 / 布局

- `_redraw_preview`(7958-8011)：`canvas.delete('all')` → `resolve_anchored_hearts` 一次 → 遍历 `sorted_layers` 可见层 → `_draw_*_preview` → `create_line`/`create_image` → 标尺 + `_draw_selection_controls`。**每次变更全量重绘，无 dirty flag。**
- `_schedule_canvas_render`(8740)：打字时 25ms `root.after` 去抖（`inline_text_render_after_id` @1222）。
- `preview_cache.polylines`(8191)：缓存 SVG→polylines（按 path+mtime+layout）；文字/图片不缓存。
- `render_document_png`(renderer 197-235)：导出走 `flat_render_layers` + 同一 `resolve_anchored_hearts` → 保证 WYSIWYG。
- `visual_layout.fit_content_bbox_to_target_rect`(41-65)：contain/cover/stretch fit。
- **`anchor_resolve.resolve_anchored_hearts`(74-131)：幂等——每帧从 anchor TextLayer 度量 + `gap_mm`/`offset_y_mm` 重算爱心几何 → 这就是当前「文字变长素材间距不变」的实现。** 是一个**单用途锚定的概念验证**，可推广为通用 auto-layout（见 §13）。
- **无通用 auto-layout / group / constraint 引擎，所有定位为绝对坐标。**

### 2.7 序列化 / 迁移

- **Document 无序列化、无 `schemaVersion`、不落盘**——只导出为 services/api dict（`_document_to_layer_document` 99-149，`schemaVersion='1.0'` **仅在导出 dict 上**，不是文档模型）。
- config_store 成熟迁移范式可复用：未知键忽略 `_*_value` .get(607-623)；安全标志 `inbox_autoparse_user_set`(220-223)；`reference_fields_from_legacy`(651)；`ProductConfig.template_version`(135，int=1)。`ProductionParams.to_dict/from_mapping`(production 55-86) 是最小序列化模板。

### 2.8 测试

- `pytest.ini` 设 PYTHONPATH；`tests/conftest.py` `_cleanup_customtkinter_trackers`(autouse) 清 CustomTkinter 全局追踪器。
- `tests/test_ui_app.py`：Tk-display-required（headless `pytest.skip`）+ `*_without_display` 逻辑测试（`FakeRoot`/`_FakeVar`/`FakeCanvas` + `__new__` 跳过 `__init__`）。
- 9 个已知失败：① 无头 Tk（`root=tk.Tk()` 在 CI 失败）；② 缺实现——`_on_canvas_pan_press`（测试 @768 期望中键 pan，现实只有 `_on_canvas_press` 左键空白 pan）、`case_button`（@1340 期望 `.cget('text')`，从未赋值）。
- `test_config_store.py` / `test_product_config_migration.py`：round-trip + legacy 迁移测试（**迁移范式模板**）。
- `test_document_layers.py` / `test_document_vector_export.py` 存在，但**无 Document 级序列化 round-trip 测试**（因为还没有序列化）。

### 2.9 当前数据流图

```
用户操作（点击 / 拖动 / 双击 / 右键 / 键入）
  │
  ▼ UI 事件
  _on_canvas_press / _on_canvas_drag / _on_canvas_release / _on_canvas_double_click
  layers_tree 事件（select / button_press / drag / release）
  _open_layer_geometry_dialog（CTkToplevel + grab_set）  ← 模态，阻塞画布
  │
  ▼ 状态更新
  document.selected_layer_id；layer.x/y/width/height/font_size；layer.production
  共享 var：layer_x_var / layer_y_var / layer_w_var / layer_h_var / layer_font_size_var
  │
  ▼ 图层数据（models.Document.layers）
  Layer / TextLayer / ImageLayer / GroupLayer / AnchoredHeartLayer
  │
  ▼ 布局计算
  resolve_anchored_hearts（爱心几何，幂等重算）
  compute_text_fit / fit_text_box（字号自适应 + 断行 + 基线）
  fit_content_bbox_to_target_rect（SVG contain-fit）
  │
  ▼ 画布渲染
  _redraw_preview：canvas.delete('all') → _draw_*_preview → create_line / create_image
  → _draw_selection_controls（虚线框 + 单一右下角手柄）
  （打字时 _schedule_canvas_render 25ms after 去抖）
  │
  ▼ 撤销记录
  HistoryManager.push = deepcopy(Document)，上限 50
  拖动经 _drag_history_pushed 合并为一条；对话框「应用」一条；换素材/字体一条
```

---

## 3. 当前问题的真实根因

| 问题 | 真实根因（代码级） |
|---|---|
| **P1 弹窗后无法操作画布** | `_open_layer_geometry_dialog`（ui_app.py:7042）创建 `ctk.CTkToplevel` 并在 **7066 行 `win.grab_set()`**。`grab_set` 把全部指针/键盘事件重定向到对话框，`preview_canvas` 的 `_on_canvas_press/drag` 在对话框关闭前完全收不到事件。`_open_heart_anchor_dialog` 同理。**不是 overlay / focus trap / portal，就是 Tk 的 `grab_set` 输入捕获。** |
| **P2 缺实时渲染 + 双向同步** | 对话框只在「应用」按钮 → `_apply_layer_production` 提交一次；编辑过程中**不触发** `_redraw_preview`。同步是单向的（选层时 `_sync_layer_properties` 把 layer→var，但 var 改动不实时回写 layer 也不重绘）。 |
| **P3 添加入口分裂 + 类型散落** | 两个独立按钮（3446-3450）各调独立方法。类型分发靠 `isinstance` 散落在 `desktop_export`(_image_layer/_text_layer/_anchored_heart_layer)、`_redraw_preview`(_draw_*_preview)、命令系统多处。新增内容类型要改 N 处。 |
| **P4 无 auto-layout** | `GroupLayer` 仅普通容器，无方向/间距/对齐。唯一「间距不变」能力是 `AnchoredHeartLayer` 的单用途锚定（`resolve_anchored_hearts`），不通用。`group_layers`/`ungroup_layer` 已实现但未接 UI。 |
| **P5 工具与数据耦合** | 文字字段（字号/字距/行距/对齐/颜色）直接绑在 `ui_app` 的共享 var 与对话框上，没有「内容能力声明 → UI 自动生成」的注册机制。加竖排/沿路径/富文本要改 UI 组件本身。 |

---

## 4. 方案 A / B / C 对比

### 方案 A：最小改动
保留独立 `TextLayer`/`ImageLayer`，仅统一添加按钮 + 把模态对话框改非模态。

### 方案 B：渐进式 Content Provider（推荐）
**复用现有** `Layer` 基类 + `type` 判别 + `GroupLayer`，引入 `ContentProvider` 注册表把现有散落的 `isinstance` 分发**形式化**（不替换 dataclass）。新增 `AutoLayoutGroupLayer` 子类 + 推广 `resolve_anchored_hearts` 的幂等重算为通用 layout pass。

### 方案 C：完整 Scene Graph 重写
重建场景图、渲染、交互系统。

### 对比表

| 维度 | A 最小改动 | **B 渐进 Provider** | C 完整重写 |
|---|---|---|---|
| 开发风险 | 低 | **中低**（基类/Group/group_layers 已存在，多为"接线"） | 极高 |
| 旧文档兼容 | 高（不动模型） | **高**（适配器包旧 dataclass，导出字节不变） | 低（需全量迁移，易破坏字节稳定红线） |
| 渲染改动范围 | 极小 | **小**（`_draw_*` 收敛为 `provider.render`，保留 `_redraw_preview` 全量重绘） | 全部重写 |
| 撤销/重做影响 | 无 | **小**（`HistoryManager` 快照式不变，新增 transaction 封装） | 推倒重来 |
| 扩展能力（形状/二维码/SVG/滤镜） | **差**（每类仍改 N 处） | **强**（注册一个 provider 即可） | 强（但成本不成比例） |
| 满足 auto-layout 需求 | **不满足** | **满足**（新增子类 + layout pass） | 满足 |
| 测试成本 | 低 | **中**（新增 provider 契约测试 + 迁移 round-trip） | 极高 |
| 性能风险 | 无 | **低**（仍全量重绘 + 25ms 去抖；auto-layout 为 O(子节点)） | 高（新渲染路径未经生产验证） |
| 回滚难度 | 易 | **易**（每 Packet 独立，feature flag 可关 auto-layout） | 几乎不可回滚 |

### 4.1 为什么不是 C（代码层面理由）

C 会丢弃三样**已被生产验证、且是红线的资产**：
1. **WYSIWYG 导出管线**：`desktop_export._apply_canvas_fit` + `render_document_png` 共享 `resolve_anchored_hearts` 与 `fit_text_box`，保证「预览==PNG==DXF」、桌面四路定位偏差 <0.05mm。重写渲染必然动这条链，威胁「旧数据导出字节不变」红线。
2. **文字排版大脑** `compute_text_fit`/`fit_text_box`：自适应字号 + 断行 + PUA 字形，是多次踩坑沉淀的单一来源。
3. **anchor 机制**：`resolve_anchored_hearts` 已经是「间距不变」的可用实现。
C 用极高风险换取零生产收益，否决。

### 4.2 为什么不是 A

A 无法满足需求 7（为形状/二维码/SVG/滤镜留扩展）和需求 8/9（auto-layout 组合）。A 下每加一种内容类型仍要改 `desktop_export` + `_redraw_preview` + 命令系统多处。但 A 的两个动作（统一添加按钮、非模态化对话框）**本身是对的**，已被吸收为 B 的 Packet 1/2。

### 4.3 为什么是 B（且是「懒版 B」）

代码现状决定 B 几乎是「接线」而非「重写」：
- `Layer` 基类 + `type` 判别 + 6 个子类 **已存在**。
- `GroupLayer`（Stage-1）+ `group_layers`/`ungroup_layer`/`make_combined_layer` **已实现，仅未接 UI**。
- `desktop_export` 已经按类型 `isinstance` 分发——Provider 注册表只是把它收敛为查表。
- 导出 dict 已用 `schemaVersion='1.0'`，`docs/LAYER_MODEL.md` 已设计好近似的资源引用形状。
- `resolve_anchored_hearts` 已证明「幂等重算 = 间距不变」。
- 共享 var（`layer_x_var` 等）+ `_sync_layer_properties` + `_apply_layer_production` + `HistoryManager` + `_drag_history_pushed` **已提供非模态 Inspector 与事务所需的全部底座**。

> **核心判断（ponytail）**：不要重写——把已存在的东西注册/接线/推广即可。新增抽象限定为：`ContentProvider` 协议（薄）、`begin/commit/rollback` 事务（约 30 行加在 `HistoryManager` 上）、`AutoLayoutGroupLayer` 子类 + 一个 layout pass。

**推荐：方案 B。**

---

## 5. 推荐方案与架构决策记录（ADR）

### ADR-001：采用渐进式 Content Provider，不重写场景图
- **决策**：保留 `models.py` 的 dataclass 模型与 `_redraw_preview` 全量重绘，引入 `ContentProvider` 注册表收敛类型分发。
- **理由**：见 §4.1–4.3。模型骨架已就绪，重写威胁红线。
- **后果**：短期多一层注册表间接；长期新增内容类型成本从「改 N 处」降为「注册 1 个 provider」。

### ADR-002：非模态 Inspector 复用现有共享 var 与命令，不引入独立数据副本
- **决策**：用非 grab 的 `tk.Frame`/`CTkFrame` overlay 替换 `CTkToplevel`，绑定**现有** `layer_x_var` 等，经**现有** `_apply_layer_production`/`_sync_layer_properties` 双向同步。
- **理由**：任务明确「不允许属性栏私自维护与画布不同步的数据副本」。现有共享 var 就是同一份事实源。
- **后果**：删除/不再调用 `_open_layer_geometry_dialog` 的 `grab_set`。

### ADR-003：实时预览经 transaction 合并为单条撤销
- **决策**：在 `HistoryManager` 上加 `begin_transaction/commit/rollback`，推广现有 `_drag_history_pushed` 的「首帧 push 一次」模式到 Inspector 编辑。
- **理由**：避免连续拖动/按住 +/- 产生几十条撤销。
- **后果**：画布变换与 Inspector 编辑共用同一事务语义。

### ADR-004：auto-layout 推广 anchor 机制，作为渲染前的幂等 layout pass
- **决策**：新增 `AutoLayoutGroupLayer(GroupLayer)` + `resolve_auto_layout(document)`，在 `_redraw_preview` 与导出前调用（与 `resolve_anchored_hearts` 并列）。
- **理由**：`resolve_anchored_hearts` 已证明此模式可行且与导出对齐。
- **后果**：「文字变长间距不变」由通用 layout pass 保证；子图层几何为「派生值」，每帧重算。

### ADR-005：Document 引入 `schema_version` + 加载时迁移 + 适配器，旧 dataclass 不删
- **决策**：见 §15。
- **理由**：红线「旧数据导出字节不变」+ 任务「优先适配器渐进迁移」。

---

## 6. 数据模型（设计，不实现）

评估目标结构与现有 `Layer` 的差异，**最小化字段新增**：

```
LayerNode（= 现有 models.Layer，新增 3 个可选字段）
  现有：id, name, type, x, y, width, height, scale_x, scale_y,
        rotation, opacity, visible, locked, z_index
  新增：parent_id: str | None = None        # 便于 O(1) 反查父；当前靠遍历，可后补
       schema_version: int = 2              # 仅 Document 持久化时写；运行时默认
       provider_id: str = ""                # 内容层填 'text'/'image'/'shape'/...；
                                            # group/auto-layout-group 留空
```

> **假设**：`parent_id` 非必须——现有 `reparent_layer` 已用「列表序为唯一事实源 + `normalize_z_indexes`」工作，`parent_id` 只是加速反查与校验。可在 Packet 5 再加，或先不加。**懒版：先不加 `parent_id`，用现有 `_flat_leaves`/容器查找。**

节点三分类（**已基本就绪**）：
- **content**：`TextLayer`/`ImageLayer`/`GlyphLayer`/（未来 ShapeLayer/QRLayer/SvgLayer/FilterLayer）。内容能力经 `provider_id` 识别。
- **group**：`GroupLayer`（已存在）。
- **auto-layout-group**：`AutoLayoutGroupLayer`（新增，见 §13）。

`blendMode`：**暂不引入**（导出是单色净轮廓 DXF，混合模式对雕刻无意义；§20 列为暂不实现）。`opacity` 字段已存在但导出忽略，保留即可。

> **收敛原则**：渲染器/属性栏/命令系统**不得**再散落 `if layer.type == 'text'`。统一经 `provider = registry.get(layer.provider_id or layer.type)` 查表，调 `provider.render(...)` / `provider.inspector_sections(...)` 等。现有 `desktop_export` 的 isinstance 分发是首批被收敛的对象。

---

## 7. Content Provider 接口（设计，不实现）

`ContentProvider` 是**薄协议**，包住每种内容层"创建/校验/迁移/渲染/测量/属性/能力/资源/序列化"的差异。现有逻辑搬进对应 provider，不新写算法。

```python
# 假设接口（Python Protocol / ABC），落地时 text/image 各一个实现
class ContentProvider(Protocol):
    provider_id: str                      # 'text' | 'image' | 'shape' | ...

    def create_default(self, document, **kw) -> Layer: ...
        # text → 复用 models.add_text_layer；image → models.add_image_layer

    def validate(self, layer) -> list[str]: ...
        # 返回错误列表（空=OK）；缺资源/非法尺寸在此报告，不崩溃

    def migrate(self, raw: dict, from_version: int) -> dict: ...
        # 旧字段 → 新字段；复用现有 __post_init__ 迁移逻辑

    def render_preview(self, layer, canvas, ctx) -> None: ...
        # 搬现有 _draw_text_layer_preview / _draw_image_layer_preview

    def render_export(self, layer, ctx) -> dict: ...
        # 搬现有 desktop_export._text_layer / _image_layer

    def measure(self, layer) -> Bounds: ...
        # text → compute_text_fit 的 bbox；image → viewBox/intrinsic
        # auto-layout 用它取子节点尺寸做重排

    def inspector_sections(self, layer) -> list[InspectorSection]: ...
        # 声明该层在属性栏显示哪些字段（见 §10）

    def capabilities(self) -> set[str]: ...
        # {'resize','rotate','editable_text','wrap',...}，UI 据此显隐手柄/入口

    def resource_dependencies(self, layer) -> list[ResourceRef]: ...
        # text → 字体；image → 素材 SVG（见 §8）

    def serialize(self, layer) -> dict / deserialize(self, dict) -> Layer: ...
        # 文档落盘用（§15）；复用 ProductionParams.to_dict 范式
```

注册表（**懒版：一个模块级 dict**）：
```python
PROVIDERS: dict[str, ContentProvider] = {}
def register_provider(p): PROVIDERS[p.provider_id] = p
def get_provider(layer) -> ContentProvider | None:
    return PROVIDERS.get(getattr(layer, 'provider_id', '') or layer.type)
```

> **不要**为单实现造工厂/插件加载器。Packet 3 只注册 `TextProvider` + `ImageProvider`，把现有函数搬进去。`AnchoredHeartLayer` 暂仍走专用路径（或注册为 image 的变体），不强行通用化。

---

## 8. 资源模型（设计，不实现）

**字体不是文字内容本身，是文字引用的资源。** 现状：`TextLayer.font_path`（主）+ `font_library_id`/`font_key`；`ImageLayer.path`（主）+ `library_id`/`material_key`。已有「库 + key」雏形，缺统一的 ref 结构与失效处理。

目标（蓝本 = `docs/LAYER_MODEL.md` 的 `fontRef`/`assetRef`，按 Python 落地）：

```
ResourceRef（统一字体/素材引用）
  kind: 'font' | 'image' | 'svg'
  library_id: str            # 复用现有 font_library_id / library_id
  item_key: str              # 复用现有 font_key / material_key
  path: Path | None          # 当前主引用，保留作 linked 解析结果
  revision: str = ""         # 假设：素材改版标识，暂可空
  link_mode: 'linked' | 'embedded' = 'linked'   # 当前全是 linked
  fallback_snapshot: dict | None = None          # 失效时的占位/降级信息
```

**失效行为（修复当前不对称崩溃）**：
- 字体异步/同步加载失败 → 现有 `_load_font` 已回退默认字体 + warning（**保留**）。
- **素材丢失/改名/删除 → 当前 `_image_layer` 抛 `ValueError` 崩溃（2.5）。改为**：渲染显示占位框（虚线 + 「素材缺失: {key}」），导出时按策略——默认**跳过该层 + 记 warning**，不让整文档导不出。
- 未知 `provider_id` → 占位层（见 §16），不崩溃。

**linked vs embedded**：当前全 linked（只存路径/key）。embedded（把 SVG/字体内联进文档）**暂不实现**，但 `link_mode` 字段预留，使未来跨机器分发文档成为可能。

**复制/粘贴/跨文档**：
- 同文档 duplicate（现 `duplicate_layer` 797）：ref 直接深拷贝，library/key 不变。
- 跨文档粘贴（未来）：若目标文档无该 library_id → 用 `fallback_snapshot` 占位 + warning，提示用户重新绑定；**不静默丢失**。

> **不过度设计**：`revision`/`embedded`/`fallback_snapshot` 字段先**声明不填**，仅 §16 的失效处理是必须落地的。

---

## 9. 工具（Tool）注册机制（设计，不实现）

**工具 ≠ 内容提供器**（任务 §7 硬要求）：
- **ContentProvider**：数据、测量、渲染、属性定义（§7）。
- **Tool**：指针、键盘、光标、选区、画布交互。

现状工具是隐式的：`_drag_mode` ∈ {"move","resize","pan"} 内联在 `_on_canvas_*`；文字编辑是 `_start_inline_text_edit`。目标是把它们显式化为可注册工具，但**不重写交互**：

```
Tool（假设协议）
  tool_id: str                 # 'select' | 'text' | 'pan' | ...
  def on_press/on_drag/on_release(event, ctx): ...   # 搬现有 _on_canvas_*
  def on_double_click(event, ctx): ...
  def cursor() -> str
  def activates_for(layer) -> bool   # text 工具仅对 TextLayer 激活内联编辑
```

- 「编辑模式 vs 变换模式切换」= 当前「双击进 `_start_inline_text_edit` / 单击选中变换」。Tool 层把它显式化：`SelectTool`（move/resize/pan）+ `TextTool`（内联编辑、光标、选区）。
- 悬浮属性栏与右侧属性面板**复用同一命令接口**（§12），不各写一套。

> **懒版**：Packet 6 只把现有交互**收口**为 `SelectTool` + `TextTool` 两个对象，不新增工具，不改交互手感。新工具（沿路径文字等）未来再注册。

---

## 10. Inspector（属性栏）注册机制（设计，不实现）

属性栏内容**由 ContentProvider 声明，不硬编码进悬浮栏组件**（任务 §7 硬要求）。

```
InspectorSection（假设）
  title: str                   # '位置/尺寸' | '文字' | '字体' | ...
  fields: list[InspectorField]
InspectorField
  key: str                     # 绑定的 var / layer 属性，如 'font_size'
  label: str                   # '字号'
  widget: 'number'|'slider'|'select'|'color'|'toggle'|'segmented'
  var: tk.Variable             # 复用现有共享 var（layer_font_size_var 等）
  step / min / max / unit      # 数值控件参数
  command_key: str             # 提交时调用的命令（§12）
```

- 通用 section（位置 X/Y、宽、高、opacity、visible、locked）对所有层显示——直接搬 `_open_layer_geometry_dialog` 的 4 行 + 现有 toggle。
- TextProvider 追加：字号、字距(`letter_spacing`)、行距(`line_spacing`)、对齐(`align`)、颜色(`color`)、字体(`font_key` picker)。
- ImageProvider 追加：素材(`material_key` picker)、`lock_aspect_ratio`。
- AutoLayoutGroup 追加：方向、gap、padding、对齐、justify（§13）。
- 未来 provider 追加自己的 section——**悬浮栏组件只渲染 section 列表，不认识具体字段**。

> **懒版**：先用「现有共享 var + InspectorSection 列表」驱动一个简单的 `CTkFrame` 垂直布局，不做拖拽/折叠等花活。

---

## 11. 非模态属性栏状态机（设计，不实现）

替换 `_open_layer_geometry_dialog` 的 `CTkToplevel + grab_set` 为**非模态 overlay frame**。

**关键：只拦截自身范围内的指针事件。** Tkinter 中，一个普通 `CTkFrame`（不 `grab_set`）放在主窗内，只有指针落在它的子控件上时才消费事件；落在 `preview_canvas` 上的事件照常进 `_on_canvas_*`。**不需要也不要用 `grab_set`/`wait_window`。**

状态机：

```
[关闭] --选中图层--> [打开/空闲 Idle]
[Idle] --指针进入栏内控件--> [栏内交互]（画布事件不受影响）
[Idle] --画布拖/缩/选其他层--> [Idle]（栏内容经 _sync_layer_properties 跟随刷新）
[Idle] --数值控件 focus + 首次改值--> [编辑事务 Editing]
   进入：begin_transaction()（push 一次快照）
   每次改值 / 拖 slider / 按住 +/- ：preview（直接写 layer + _redraw_preview，不再 push）
[Editing] --失焦 / 回车 / 松开--> commit_transaction() --> [Idle]
[Editing] --Escape--> rollback_transaction()（恢复进入前快照）--> [Idle]
[任意] --取消选中 / 删除该层--> [关闭]
```

落地要点（全部有现成底座）：
- **不超出视口**：overlay frame 定位用 `min(max(...))` 夹紧在主窗内（纯坐标计算）。
- **栏位置变化不改图层位置**：栏只读写 `layer_*_var`，绝不写 `preview_pan_x/y` 或栏自身坐标到 layer。
- **输入框 focus 时不误触画布快捷键**：复用现有 `_focus_is_text_input`(4917)——Ctrl+Z/Delete 已对 Entry/Text 让路，扩展到栏内 Entry 即可。
- **双向同步**：var trace → preview 写 layer + 重绘；选层/画布拖动 → `_sync_layer_properties` 刷新栏。同一份 var，天然同步。
- **实时渲染**：var 改动直接调 `_redraw_preview`（或 25ms 去抖版），复用现有全量重绘。

---

## 12. 命令事务与 Undo/Redo 语义（设计，不实现）

现状：`HistoryManager`(457) 快照式 deepcopy；`_push_document_history`(4903) 是唯一 push 点；拖动经 `_drag_history_pushed`(8929) 合并为一条。**缺的只是显式 begin/commit/rollback。**

在 `HistoryManager` 上增加（约 30 行）：
```python
def begin_transaction(self, document):
    if self._txn_active: return
    self.push(document)          # 进入即快照一次（= 现有 _drag_history_pushed 首帧逻辑）
    self._txn_active = True
    self._txn_snapshot = deepcopy(document)   # 供 rollback
def commit_transaction(self):
    self._txn_active = False; self._txn_snapshot = None   # 快照已在栈里，无需再 push
def rollback_transaction(self, app):
    if self._txn_active:
        self.undo_stack.pop()                  # 丢弃进入时的快照
        app._restore_document_snapshot(self._txn_snapshot)
        self._txn_active = False
```

语义要求映射：
- **一次鼠标拖动 = 一条**：现有 `_drag_history_pushed` 已满足；改造为调 `begin/commit`。
- **一次连续字号调整 = 一条**：Inspector 进入 Editing 时 `begin`，松手/失焦 `commit`。
- **连续按住 +/- 或连续输入 = 一条**：同一事务内多次 preview，不重复 push。
- **文字输入按编辑会话合并**：内联编辑进入时 `begin`，提交时 `commit`（修复现状 `_commit_inline_text_edit` @8797 **不 push** 的缺陷——文字编辑当前根本没进撤销）。
- **画布变换与 Inspector 编辑同一套语义**：都走 `begin → preview* → commit/rollback`。
- **Escape 取消未提交**：`rollback_transaction`。

> **不引入命令对象/命令栈**：现有快照式撤销够用，重写为 command-based 是过度工程。事务只是给快照式加「成批」边界。

---

## 13. 普通组合与自动布局组合（设计，不实现）

### 13.1 普通组合（GroupLayer，已存在，仅接 UI）

`GroupLayer`(362)、`group_layers`(652)、`ungroup_layer`(674)、`make_combined_layer`(698)、`reparent_layer`(735，含循环检测) **已实现**。Packet 5 只需：
- 右键菜单加「组合 / 解除组合」→ 调 `group_layers`/`ungroup_layer`（push 一条 undo）。
- 拖拽进/出组：现有 `_reparent_tree_layer` 已支持 inside。
- 解除组合保持视觉位置：`ungroup_layer` 已在原位插回 children（普通组不改子坐标，天然保持）。

### 13.2 自动布局组合（AutoLayoutGroupLayer，新增）

```
AutoLayoutGroupLayer(GroupLayer)   # type='auto_layout_group'
  direction: 'horizontal' | 'vertical' = 'horizontal'
  gap: float = 16
  padding: (top,right,bottom,left) = (0,0,0,0)
  align: 'start'|'center'|'end' = 'center'        # 交叉轴
  justify: 'start'|'center'|'end' = 'start'       # 主轴（hug 时无意义）
  sizing: 'hug' | 'fixed' = 'hug'                 # hug content / 固定尺寸
  # fill available space：后续能力，先不做
```

**布局算法 = 新 layout pass `resolve_auto_layout(document)`**，与 `resolve_anchored_hearts` 并列，在 `_redraw_preview` 与导出前调用：
1. 后序遍历（子组先布局，支持嵌套）。
2. 对每个 `AutoLayoutGroupLayer`：取 children 各自 `measure()` 尺寸（text 经 `compute_text_fit`，image 经 viewBox），按 direction 顺序累加 gap，按 align 在交叉轴对齐，加 padding。
3. 写回每个 child 的 `x/y`（**派生值，每帧重算**）；hug 模式同时回写组的 `width/height`。
4. 子图层 `x/y` 是计算结果，不是用户绝对值——这就是「文字变长间距不变」的机制（与爱心同源）。

**明确行为**：
- **文本框变宽/变高 → 触发布局**：layout pass 每帧跑，自动反映。
- **字体加载完成致尺寸变化 → 重布局**：字体异步加载后触发一次 `_redraw_preview` → layout pass 重算（**假设**：当前字体同步加载，此点为未来异步预留）。
- **拖动 auto-layout 子图层**：默认**调整顺序**（reorder），不变绝对定位；若拖出组边界则 reparent 出组变绝对。
- **子图层旋转后边界**：按 AABB（现有 `Layer.bounds` 忽略旋转）；旋转子节点在 auto-layout 中用其 AABB 参与排布。**假设**：旋转 + auto-layout 是边缘场景，先用 AABB，标注为已知近似。
- **解除组合保持视觉位置**：ungroup 前把每个 child 的派生 `x/y` **固化为绝对值**再解组（auto-layout 专属逻辑，普通组不需要）。
- **普通组 → auto-layout 组转换顺序**：按 children 现有列表序（= z 序）作为主轴顺序。
- **禁止父子循环**：复用 `reparent_layer` 的 `_iter_subtree`(727) + `_group_contains`(6746) 检测。
- **组自身旋转/缩放坐标规则**：组的 transform 作用于「布局后的子节点整体」；**假设**：先支持组级 scale，旋转留后续（与渲染器旋转支持一致）。
- **最大宽度/换行影响组尺寸**：TextLayer 的 `text_box_width` + wrap 决定其 measure 高度，layout pass 据此撑开组——已有 `fit_text_box` 支持 box 内换行。

### 13.3 核心验收场景（必须通过）

素材 + 文字组成横向 auto-layout，gap=16：
1. 文字「生日快乐」→ 较长文本。
2. `compute_text_fit` 重算文本框尺寸/换行。
3. `resolve_auto_layout` 重算组边界与素材 x（= 文本右边界 + 16）。
4. 素材↔文本仍 16px，用户无需手动移动。
5. 整个修改在一个事务内（文字编辑会话），**撤销一次复原**。

---

## 14. 文字工具扩展方案（设计，不实现）

**当前最低能力**（落地优先级，多数已存在）：
| 能力 | 现状 |
|---|---|
| 点文字 / auto-width | **缺模式切换**；当前仅 box。需加 `TextLayer.layout_mode: 'point'\|'auto_width'\|'auto_height'\|'fixed_frame'` |
| auto-height | 同上 |
| 固定文本框 | = 当前 box（`text_box_width/height`） |
| 最大宽度 + 自动换行 | `fit_text_box` 已支持 box 内换行；`text_box_width` 即 max width |
| 字体 / 字号 / 单位 | `font_path`/`font_key`、`font_size`(cap)；单位假设 px（与画布一致） |
| 字距 / 行距 | `letter_spacing`/`tracking`、`line_spacing` ✅ |
| 段落对齐 / 文本颜色 | `align`/`vertical_align`、`color` ✅ |
| 画布内直接编辑 | `_start_inline_text_edit` ✅（非模态） |
| 文字框缩放 | `CanvasTextItem.resize_by` ✅ |
| 编辑/变换模式切换 | 双击进编辑 / 单击变换 ✅（Tool 层显式化见 §9） |

**未来扩展空间**（数据模型 + UI 注册预留，**本轮不实现**）：富文本片段、多字体、可变字体轴、OpenType 特性、竖排、沿路径、段前段后间距、基线偏移、字符级颜色、描边/阴影。

**预留方式（不硬编码进悬浮栏）**：
- 数据：`TextLayer` 增 `runs: list[TextRun] | None = None`（None = 纯文本，向后兼容）。富文本时 `runs` 携带每段字体/颜色/特性；导出/测量遍历 runs。**本轮只声明字段，不填。**
- UI：高级能力 = TextProvider 多声明几个 `InspectorSection`（§10），悬浮栏自动渲染，**不改栏组件代码**。
- 工具：沿路径/竖排 = 新注册 Tool（§9），不动现有 `TextTool`。

> 任务硬要求达成：内容提供器负责数据/测量/渲染/属性；工具负责交互；悬浮栏与右侧面板复用同一命令接口；未来字段不硬编码进当前悬浮栏组件。

---

## 15. 文档迁移方案（设计，不实现）

现状：Document **无序列化、无版本、不落盘**（2.7）。本 RFC 需从零加 Document 持久化 + 版本，**复用 config_store 迁移范式**。

- **`Document.schema_version: int`**：legacy（无版本/无序列化）视为 v1；新结构 = v2。
- **加载时迁移（推荐）**：`load_document(dict) → 检测 version → migrate_v1_to_v2 → Document`。每个 ContentProvider 的 `migrate()` 处理自己的字段（复用现有 `__post_init__` 迁移：`material_id→material_key`、`font_key` 从 stem 推导等）。
- **保存时用 v2**。
- **legacy TextLayer/ImageLayer → ContentLayer 迁移**：不改 dataclass，加 `provider_id`（'text'/'image'）+ 包适配器。旧 dataclass **不删**。
- **迁移失败错误处理**：单层迁移失败 → 占位层 + warning，不中断整文档加载。
- **未知 `provider_id`**：占位层（§16），保留原始 dict 以便升级后恢复。
- **往返序列化测试**：v2 doc → serialize → deserialize → 深度相等；legacy fixture → load → 导出字节与迁移前**逐字节一致**（红线）。
- **旧文档 fixture 测试**：Packet 0 先建 legacy fixture（当前生产形态：1 image + 1 text [+ heart]）。
- **回滚策略**：feature flag `DOC_SCHEMA_V2`（env 或 config）；关闭则不写 v2、仍走内存态。
- **feature flag**：是。auto-layout、非模态栏、v2 序列化各自可独立 flag，便于灰度/回滚。

> **重要**：当前根本没有「打开文档」工作流（每次启动空白画布）。本 RFC 的序列化是**新增能力**，因此 Packet 0 的「旧文档 fixture」实为「当前内存 Document → 导出 dict」的快照，作为字节稳定基线；真正的 `.flower` 文档存盘是 Packet 4 才引入的新功能，旧用户无存量文档，迁移风险低。

---

## 16. 错误处理（设计，不实现）

| 失效场景 | 行为 |
|---|---|
| Provider 注册失败 / 未知 provider_id | 占位层（虚线框 + 「未知内容: {id}」），保留原始 dict，不崩溃 |
| 资源（素材）加载失败 | **修复现状崩溃**：渲染占位框，导出跳过 + warning（见 §8） |
| 字体加载失败 | 现有 `_load_font` 回退默认字体 + warning（保留） |
| 损坏文档数据 | 单层 try/except → 占位层 + warning；整文档不失败 |
| 非法父子关系（循环） | `reparent_layer` + `_iter_subtree` 已拦截；auto-layout 同样校验 |
| 空图层边界 | measure 返回最小占位 bbox（如 1×1），不除零 |
| 组合嵌套过深 | 设上限（假设 16 层）+ warning；`resolve_auto_layout` 后序遍历加深度计数 |
| 数值非法（NaN/负尺寸） | provider.validate 报告；Inspector 拒绝提交 + 标红（复用 `error` 哨兵范式） |

---

## 17. 性能策略（设计，不实现）

- **文字输入是否触发整画布重绘**：是（`_redraw_preview` 全量）。**已有 25ms `root.after` 去抖**（`_schedule_canvas_render` 8740）缓解。保留，不改架构。
- **字体测量同步/异步**：当前同步（Pillow truetype）。**保留同步**；`AutoLayoutGroupLayer` 与 anchor 已假设同步度量。异步加载列为未来（§13 已预留重布局触发点）。
- **auto-layout 触发范围**：仅含 `AutoLayoutGroupLayer` 的子树，O(子节点数)，后序一次。普通文档（1 image + 1 text）成本可忽略。
- **dirty flag**：**暂不引入**。当前全量重绘 + 去抖在生产规模（个位数图层）下足够；dirty flag 是过度优化。§20 列为暂不实现，留升级路径。
- **rAF 合并**：Tkinter 无 rAF；`root.after` 去抖即等价物，已有。
- **大量图层性能**：当前生产每文档图层数为个位数，非瓶颈。若未来批量场景出现，再引入 dirty flag / 增量重绘（升级路径明确）。
- **不无依据引入新依赖**：本 RFC 不新增任何第三方依赖（全部基于 stdlib `tkinter`/`copy`/`uuid` + 现有 `Pillow`/`fontTools`）。

---

## 18. 测试方案（设计，不实现）

复用现有 `pytest` + `without_display` 范式（2.8）：

| 层级 | 测试 |
|---|---|
| 模型 | provider `create_default/validate/migrate/measure/serialize` 契约测试；`group_layers`/`ungroup_layer`/`reparent_layer` 已有可补；`resolve_auto_layout` 间距不变断言 |
| 序列化 | v2 round-trip 深度相等；**legacy fixture 导出字节稳定**（红线门禁） |
| 事务 | `begin/preview*/commit` = 1 条 undo；`rollback` 复原；连续拖动 1 条 |
| 非模态栏 | `without_display` 用 `FakeVar` 测 var↔layer 双向同步、夹紧视口坐标、Escape 回滚 |
| 命中/变换 | `hit_test` AABB、resize 手柄、pan（修 `_on_canvas_pan_press` 缺口） |
| auto-layout | 核心验收场景（§13.3）：文字变长后 gap 仍 16px、撤销一次复原 |
| 错误恢复 | 缺素材占位不崩、未知 provider 占位、循环拒绝 |
| 回归 | 全量 `pytest tests services/api/tests`，基线 534 passed（不退化），修复 2 个缺口测试 |

---

## 19. 风险与回滚策略

| 风险 | 缓解 / 回滚 |
|---|---|
| 改渲染破坏 WYSIWYG 字节稳定 | Packet 0 建字节基线门禁；provider.render_export 搬代码不改算法；CI 比对导出字节 |
| 非模态栏漏拦/误拦事件 | 不用 grab；逐项手测「栏开时拖/缩/选其他层」；feature flag 可退回旧对话框 |
| 事务漏 commit 致脏快照 | 复用现有「失败 pop 孤儿快照」范式（6734/7368）；事务在 release/失焦/Escape 三处兜底 commit/rollback |
| auto-layout 与导出不一致 | layout pass 在预览与导出**共用同一函数**（学 `resolve_anchored_hearts`） |
| 迁移破坏旧数据 | 旧 dataclass 不删；加载时迁移 + 字节稳定测试；`DOC_SCHEMA_V2` flag 可关 |
| 9 个已知失败混入新失败 | Packet 0 锁基线，每 Packet 跑全量对比 |

**逐 Packet 独立回滚**：每个 Packet 改不同核心文件区，可单独 revert；feature flag 让 auto-layout / 非模态栏 / v2 序列化在生产可热关。

---

## 20. 暂不实现的内容（明确边界）

- `blendMode` / opacity 混合（雕刻单色无意义）。
- embedded 资源（仅 linked）；`revision` 实际比对。
- dirty flag / 增量重绘（保留全量 + 去抖）。
- 字体异步加载（保留同步）。
- 富文本 runs、多字体、可变字体轴、OpenType、竖排、沿路径、字符级颜色、描边/阴影（仅预留字段/注册点）。
- auto-layout 的 `fill available space`、旋转子节点精确边界（先 AABB）、组级旋转。
- 旋转手柄、四角缩放手柄（保留单一右下角手柄，除非截图明确要求）。
- AnchoredHeartLayer 强行通用化（保留专用路径，与 auto-layout 并存）。
- 重做截图之外的任何无关界面。

---

## 21. Codex 执行包（Execution Packets）

> 原则：每个 Packet 解决一个连贯问题、独立审查与回滚，尽量不让多个 Packet 同时改同一批核心文件。

### Packet 0：基线测试与旧文档 fixture
- **Goal**：锁定导出字节基线 + 当前生产 Document fixture，建回归门禁。
- **Context**：Document 无序列化但导出 dict 稳定（`_document_to_layer_document` 99）；测试基线 534 passed / 9 failed。
- **真实文件/符号**：新增 `tests/test_layer_baseline.py`；引用 `desktop_export._document_to_layer_document`、`render_document_dxf/svg`、`models.add_image_layer`/`add_text_layer`、`AnchoredHeartLayer`。
- **不修改**：任何生产代码（纯加测试 + fixture）。
- **实现步骤**：① 构造生产形态 Document（1 image + 1 text + 可选 heart）；② 导出 dict/DXF/SVG 存为 golden fixture；③ 断言后续运行逐字节一致。
- **数据迁移影响**：无。
- **测试用例**：golden round-trip；记录当前 9 failed 清单为已知基线。
- **手工验证**：跑全量 pytest，确认 534 passed 不变。
- **Done when**：字节基线测试通过且纳入 CI；9 个已知失败清单文档化。
- **回滚**：删测试文件。
- **后续依赖**：所有 Packet 的字节稳定门禁。

### Packet 1：非模态属性栏与实时预览事务
- **Goal**：消除 P1/P2——去 `grab_set`，做非模态栏 + 事务化实时预览。
- **Context**：根因 `_open_layer_geometry_dialog` @7066 `grab_set`；共享 var + `_apply_layer_production`/`_sync_layer_properties` 已就绪。
- **真实文件/符号**：`ui_app.py` `_open_layer_geometry_dialog`(7042)、`_apply_layer_production`(7287)、`_sync_layer_properties`、`layer_x/y/w/h_var`、`layer_font_size_var`、`_focus_is_text_input`(4917)、`_redraw_preview`、`_schedule_canvas_render`(8740)；`models.HistoryManager`(457)、`_push_document_history`(4903)、`_drag_history_pushed`(8929)。
- **不修改**：渲染算法、导出、数据模型字段、auto-layout（尚不存在）。
- **实现步骤**：① 在 `HistoryManager` 加 `begin/commit/rollback_transaction`（§12）；② 新建非模态 `CTkFrame` overlay（不 grab），字段绑现有共享 var，视口夹紧；③ var trace → preview 写 layer + `_redraw_preview`；④ 进入编辑 `begin`、失焦/回车/松手 `commit`、Escape `rollback`；⑤ 选层/画布拖动经 `_sync_layer_properties` 刷新栏；⑥ 保留 `_open_layer_geometry_dialog` 但改为不 grab 或由 flag 切换（回滚用）。
- **数据迁移影响**：无。
- **测试用例**：`without_display` 测 var↔layer 双向同步、Escape 回滚、连续改值=1 条 undo、`_focus_is_text_input` 拦快捷键。
- **手工验证**：开栏后在画布拖/缩/选其他层正常；改字号实时重绘；Ctrl+Z 一次复原一次会话。
- **Done when**：栏开时画布可操作、实时渲染、单次撤销、Escape 取消。
- **回滚**：flag 切回旧 `grab_set` 对话框。
- **后续依赖**：Packet 5（auto-layout 编辑复用事务）、Packet 6（工具复用命令）。

### Packet 2：统一「添加图层」入口
- **Goal**：合并两个按钮为「+添加图层」菜单。
- **Context**：现 `+文字图层`(3446)/`+图片图层`(3447) 各调 `_add_text_layer_from_fields`(7713)/`_add_selected_flower_to_canvas`(7649)；代码已惯用 `tk.Menu`(6946)。
- **真实文件/符号**：`ui_app.py` 上述按钮与方法；`models.add_text_layer`/`add_image_layer`/`make_combined_layer`(698)/`group_layers`(652)。
- **不修改**：模型字段、渲染、Inspector（Packet 1）。
- **实现步骤**：① 用单个「+ 添加图层」按钮 + `tk.Menu`（文字/图片素材/空白内容层/普通组合/自动布局组合）；② 各项调现有 add_* / group_layers；③ **默认不创建零尺寸隐形空白层**——「空白内容层」需走 §3 定义（默认占位框尺寸、列表显示、画布占位提示、选中后绑素材/字体、未绑导出跳过+warning、未绑命中走占位 bbox、删除/撤销正常）。
- **数据迁移影响**：无。
- **测试用例**：菜单各项创建正确 type；空白层占位尺寸非零；未绑层导出跳过。
- **手工验证**：点菜单各项画布出现对应层；空白层可后绑。
- **Done when**：单入口、可扩展、不堆隐形空白层。
- **回滚**：恢复两按钮。
- **后续依赖**：Packet 3（新内容类型注册后追加菜单项）、Packet 5（组合菜单项）。

### Packet 3：公共 LayerNode 与 Content Provider 适配层
- **Goal**：把散落 isinstance 收敛为 provider 注册表，**不改 dataclass**。
- **Context**：`desktop_export` 已 isinstance 分发（`_image_layer`/`_text_layer`/`_anchored_heart_layer`）；`_redraw_preview` 的 `_draw_*_preview` 同理。
- **真实文件/符号**：新增 `providers.py`（`ContentProvider`、`register_provider`、`get_provider`、`TextProvider`、`ImageProvider`）；改 `desktop_export._document_to_layer_document`(99) 用 `get_provider(layer).render_export`；`ui_app._redraw_preview`(7958) 用 `provider.render_preview`；`models.Layer` 加可选 `provider_id`。
- **不修改**：导出字节（render_export 搬代码不改算法，Packet 0 门禁）、Inspector、auto-layout。
- **实现步骤**：① 定义协议 + dict 注册表（§7）；② TextProvider/ImageProvider 把现有 `_text_layer`/`_image_layer`/`_draw_*` **搬入**（不改逻辑）；③ 调用点改查表；④ AnchoredHeart 暂保留专用路径或注册为 image 变体。
- **数据迁移影响**：`provider_id` 默认空（运行时回退 `layer.type`），旧内存态兼容。
- **测试用例**：provider 契约测试；导出字节基线（Packet 0）不变。
- **手工验证**：预览/导出与改前像素/字节一致。
- **Done when**：渲染与导出走 provider，字节稳定，新增类型只需注册。
- **回滚**：调用点切回 isinstance。
- **后续依赖**：Packet 4（serialize）、Packet 6（inspector_sections/tool）。

### Packet 4：资源引用与文档迁移
- **Goal**：统一 ResourceRef + 资源失效不崩 + Document v2 序列化与加载时迁移。
- **Context**：字体/素材已有「库+key」雏形；缺素材导出崩溃（`_image_layer` 155）；Document 无序列化；config_store 有迁移范式。
- **真实文件/符号**：`models.py`（ResourceRef、`TextLayer.font_*`/`ImageLayer.material_*`、`Document.schema_version`、新增 `Document.serialize/deserialize` + provider.serialize）；`desktop_export._image_layer`(152) 资源缺失改占位；复用 `production.ProductionParams.to_dict/from_mapping`(55-86)、config_store `_*_value`(607) 未知键忽略范式。
- **不修改**：导出字节（旧数据路径）、渲染算法。
- **实现步骤**：① 加 `schema_version` + `serialize/deserialize`（经 provider）；② 加载时 `migrate_v1_to_v2`（复用 `__post_init__` 迁移）；③ 资源缺失 → 占位 + 导出跳过+warning（§8/§16）；④ 未知 provider_id → 占位层保留原 dict；⑤ feature flag `DOC_SCHEMA_V2`。
- **数据迁移影响**：legacy → v2 加载时迁移；旧数据导出字节不变（门禁）。
- **测试用例**：v2 round-trip 深度相等；legacy fixture 字节稳定；缺素材占位不崩；未知 provider 占位。
- **手工验证**：删一个素材文件后文档仍可打开/导出（跳过该层 + warning）。
- **Done when**：可存/读 v2 文档、旧数据无损、资源失效不致命。
- **回滚**：关 `DOC_SCHEMA_V2`，回内存态。
- **后续依赖**：Packet 5（组/auto-layout 序列化）。

### Packet 5：普通组合与自动布局组合
- **Goal**：接 UI 的普通组合 + 新增 AutoLayoutGroupLayer + layout pass。
- **Context**：`GroupLayer`/`group_layers`/`ungroup_layer`/`reparent_layer` 已实现未接 UI；`resolve_anchored_hearts` 是间距不变的同源范例。
- **真实文件/符号**：`models.py`（新增 `AutoLayoutGroupLayer`、`resolve_auto_layout`；复用 `group_layers`(652)/`ungroup_layer`(674)/`reparent_layer`(735)/`_iter_subtree`(727)）；`anchor_resolve` 旁新增 layout pass；`ui_app._redraw_preview`(7958) 与 `desktop_export`/`renderer.render_document_png` 调用 layout pass；右键菜单加组合/解组/转 auto-layout；`provider.measure`（Packet 3）。
- **不修改**：anchor 专用路径、文字排版大脑、导出字节（无 auto-layout 的旧数据）。
- **实现步骤**：① 右键「组合/解除组合」接 `group_layers`/`ungroup_layer`（push 1 undo）；② 新增 `AutoLayoutGroupLayer` + `resolve_auto_layout`（§13.2，后序、measure、写回派生 x/y、hug 撑组）；③ 预览与导出共用 layout pass；④ 拖子节点=reorder，拖出=reparent；⑤ ungroup 前固化派生坐标；⑥ Inspector（Packet 1/6）加方向/gap/padding/align/justify；⑦ feature flag `AUTO_LAYOUT`。
- **数据迁移影响**：新 type 经 Packet 4 序列化；旧数据无此类型，字节不变。
- **测试用例**：§13.3 核心验收（文字变长 gap 仍 16、撤销一次复原）；嵌套；解组保持视觉位置；循环拒绝。
- **手工验证**：素材+文字横向组 gap=16，改长文字素材自动让位，撤销一次回退。
- **Done when**：组合可建/解/复制粘贴/隐藏锁定/撤销；auto-layout 间距不变。
- **回滚**：关 `AUTO_LAYOUT` flag；组合菜单项可隐。
- **后续依赖**：Packet 6（auto-layout 的 inspector/tool）。

### Packet 6：文字工具扩展接口
- **Goal**：工具与内容提供器分离 + Inspector section 注册 + 文字模式字段预留。
- **Context**：交互内联在 `_on_canvas_*`/`_start_inline_text_edit`；属性硬编码在对话框/共享 var。
- **真实文件/符号**：新增 `tools.py`（`SelectTool`/`TextTool`，搬 `_on_canvas_press/drag/release`(8862-8974)/`_start_inline_text_edit`(8659)）；`providers.TextProvider.inspector_sections`/`capabilities`（§10/§7）；`models.TextLayer` 加 `layout_mode`(默认现 box 行为) + `runs=None`（预留）。
- **不修改**：交互手感、渲染、导出字节（`layout_mode` 默认值 = 现行为）。
- **实现步骤**：① 把现有交互收口为 SelectTool/TextTool（不改手感）；② TextProvider 声明 inspector_sections（字号/字距/行距/对齐/颜色/字体）；③ 悬浮栏（Packet 1）改为渲染 provider 的 section 列表；④ 加 `layout_mode` 枚举（point/auto_width/auto_height/fixed_frame），默认映射现 box；⑤ `runs` 字段声明不填。
- **数据迁移影响**：`layout_mode` 默认值保证旧数据导出字节不变；`runs=None` 兼容。
- **测试用例**：section 驱动栏渲染；`layout_mode` 默认=box 字节稳定；工具 press/drag 行为不变。
- **手工验证**：文字编辑/变换切换如常；栏字段来自 provider。
- **Done when**：工具/内容/Inspector 三分离；未来字段不改栏组件。
- **回滚**：恢复内联交互与硬编码栏。
- **后续依赖**：无（扩展点交付）。

### Packet 7：性能、错误恢复与完整回归
- **Goal**：固化错误恢复 + 性能验证 + 全量回归。
- **Context**：全量重绘 + 25ms 去抖；错误处理散落。
- **真实文件/符号**：`ui_app._schedule_canvas_render`(8740)、`_redraw_preview`(7958)；`providers.validate`；§16 各失效点；修 `_on_canvas_pan_press`/`case_button` 两个缺口测试。
- **不修改**：不引入 dirty flag / 异步字体（§20）、不加新依赖。
- **实现步骤**：① 统一错误恢复（占位层、缺资源、循环、深度上限、NaN 校验）；② 验证去抖在多图层下不卡；③ 修复 `_on_canvas_pan_press`（或更新测试）与 `case_button` 死代码；④ 全量回归对比基线。
- **数据迁移影响**：无。
- **测试用例**：错误恢复全覆盖；性能冒烟；2 个缺口测试转 pass；全量不退化。
- **手工验证**：损坏/缺资源文档可打开；大文档拖动流畅。
- **Done when**：错误不致命、性能达标、回归通过（≥534 passed，修复 2 缺口）。
- **回滚**：逐项 revert。
- **后续依赖**：依赖 Packet 0–6 完成。

---

## 最终验收标准核对

| 验收项 | 由哪个 Packet 保证 |
|---|---|
| 属性栏打开时可继续拖动/缩放 | Packet 1（去 grab_set，非模态 overlay） |
| 所有属性修改实时显示 | Packet 1（var trace → `_redraw_preview`） |
| 一次连续操作只产生一次撤销 | Packet 1（transaction）+ 现有 `_drag_history_pushed` |
| 旧文档无损打开 | Packet 0 字节门禁 + Packet 4 加载时迁移 + 旧 dataclass 不删 |
| 「添加图层」可扩展新内容类型 | Packet 2（菜单）+ Packet 3（provider 注册） |
| 不默认堆积隐形空白层 | Packet 2（空白层需显式占位定义） |
| 资源失效不致整文档打不开 | Packet 4（占位 + 跳过 + warning） |
| 文本变长后 auto-layout 间距不变 | Packet 5（`resolve_auto_layout`，同源 anchor 范式） |
| auto-layout 可撤销/解组/复制粘贴 | Packet 5（复用 group_layers/ungroup/duplicate_layer + 事务） |
| 高级文字能力未来无需重写核心模型 | Packet 6（工具/内容/Inspector 分离 + 字段预留） |
| 不重做无关界面 | 全程：仅动属性弹窗/添加按钮/图层系统/文字工具相关代码 |
