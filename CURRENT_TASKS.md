# CURRENT_TASKS — flower

> 配 `PROJECT_INDEX.md` 一起读。导出/EzCad 细节看 `docs/superpowers/plans/2026-06-13-dxf-export-progress.md`。
> 更新：2026-06-15。

## 测试基线

`PYTHONPATH=".;services\api" .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q`
→ **358 passed, 0 failed**（2026-06-15 Phase 2 增量 1-5 全部完成后）。ruff clean。

## 本轮（2026-06-14）已完成：Phase 4 产品切换器（方案2 可收/展）

分支 `claude/phase4-product-switcher`（**未提交，待 review**；基于后端基线 `62556c0`）。详见 ExecPlan §8 Task 4。
- 左侧新增可收/展产品列（最左一列，原预览+功能区两栏不动）；列出 `config.products`、高亮激活、«/» 收展（状态持久化 `products_panel_collapsed`，默认收起）。
- 切换产品 = 持久化 `active_product_id` + 把该产品库目录灌进 `_scan_assets` 重扫；新建产品对话框（`unique_product_id` 去重 + `with_added_product` 追加）。
- 顺手修 BUG：`_save_settings_window` 改 `dataclasses.replace`，避免保存设置清空 products/active/收展态。
- ⚠️ **未完**：切产品**不会**让人工确认面板字段随产品级联（仍是旧 month/flower）——那属 Task 2（Phase 2）。多产品端到端验证也未做（生产配置仍只有 birth-flower 一个产品）。

## 本轮（2026-06-14）UI 换肤：CustomTkinter 深色（阶段 1-3 全部完成）

依赖 `customtkinter>=5.2`（已装 `.venv-win` + 登记 requirements）。同分支 `claude/phase4-product-switcher`，全量 341 passed，ruff clean。
- **阶段1**：全局深色（`ctk.set_appearance_mode` + `_configure_styles` 刷 ttk + `APP_COLORS` 翻深色）+ 产品列 CTk 圆角。
- **阶段2**：功能区 `CTkScrollableFrame`；五大面板 `_ctk_card` 圆角卡片；按钮/输入/备注/勾选/下拉全 CTk（素材下拉=CTkOptionMenu，command 取代 `<<ComboboxSelected>>`）。
- **阶段3**：弹窗全 `ctk.CTkToplevel` 深色；新建产品对话框全 CTk。**小尾巴**：设置/布局/素材弹窗内部控件仍 ttk-dark（未逐控件圆角化）。
- 画板**保持白底**（浅色木料，预览深灰线+黑墨，翻黑会看不见）。
- 修坑：PhotoImage 绑 `master=canvas`、`tests/conftest.py` 清 CTk tracker、`_widget_texts` 容错、context-menu 测试 `monkeypatch.undo`。
- **⚠️ 启动闪退回归（已修）**：顶层 `import customtkinter` 让非 `.venv-win` 解释器（MSYS `.venv`）启动即崩（早于 `_reexec`）。已改 `try/except ctk=None` + `set_appearance` 守卫 + `_reexec` 自检 customtkinter。`.venv` 启动现可正常 re-exec 运行。

## 本轮（2026-06-14）UI 续：Ezcad 同款顶部 + 产品列外推

参考 `Ezcad2.7.6`（= `ctk.CTk()` + 无原生菜单栏 + CTk 卡片圆角，非无边框/外框圆角）。全量 341 passed。
- 根窗 `main()` 改 `ctk.CTk()`（深色标题栏）；去原生菜单栏白条 → `_build_menubar` 顶栏 CTk 按钮 + `_popup_menu` tk_popup 弹深色菜单。
- 产品列展开改为窗口加宽（不挤画板，实测画板 694→694）。
- 标题栏深色（DWM 仅 tk.Tk 兜底）；**外框圆角未做**（Win10 直角，需 overrideredirect，用户暂未选）。
- 截图 `tmp_out/ui_ctk_top.png`。
- **收尾修复**：箭头方向纠正（收起`«`外/展开`»`内）；`glyph_panel.py` 换 CTkToplevel + 网格 canvas 深色（原唯一白窗）；菜单弹窗去白边（relief flat）；**修 ctk.CTk 致命坑**：`_toggle_product_rail` 原调 `root.minsize()` 无参 getter，CTk 上抛 TypeError → 真机点收/展即崩（tk.Tk 测试不报），改用常量 `MIN_WINDOW_WIDTH/HEIGHT`。
- **对话框白标题栏修复**（设置/布局/字形/字形说明）：CTkToplevel 自带深色标题栏不稳（采样仍白）。统一 `_themed_toplevel()`：DWM 设属性 + **1px 几何微调强制重绘**（`after(60)+after(350)` 兜复杂窗）。字形说明由 messagebox→CTk 窗口（文案→`GLYPH_HELP_TEXT`）。4 窗标题栏采样全 (0,0,0)。
- **下拉菜单改自绘 `CtkMenu`**（overrideredirect+CTk 行，无系统白边）：菜单数据驱动 `self._menus`；「导入」拍平为顶层两项。白角坑→Toplevel `bg=panel` 兜底（角像素 240→36）。右键上下文菜单仍 tk.Menu（未改）。**346 passed，ruff clean**。

## 后续 UI 待办（下次对话继续；本轮 UI 已收尾）

> 分支 `claude/phase4-product-switcher` 整轮 UI 改动（产品切换器 + 深色换肤 + Ezcad 同款顶部 + 启动/崩溃修复 + 对话框/下拉去白边）**尚未提交**，待 review/commit。
- **右键上下文菜单仍是原生 `tk.Menu`**（画板右键 `_show_canvas_context_menu` / 图层右键 `_show_layer_context_menu`），可能仍有系统白边 → 用同一个 `CtkMenu` 改（已预留"禁用项"`enabled` 支持；上下文菜单有动态项 + 测试用 `FakeMenu`，改时要同步更新 `test_canvas_context_menu...`）。
- **设置/布局/素材编辑等弹窗的内部控件**仍是 ttk-dark（已深色但非 CTk 圆角）：`ttk.Notebook` 无干净 CTk 等价物，如要统一圆角风需逐控件换 CTk（工作量中、收益低）。
- **外框圆角（真无边框窗口）未做**：Win10 需 `overrideredirect` 自绘标题栏（丢系统贴边/最大化），已评估，用户暂未选。
- 复用约定：新对话框一律用 `BirthFlowerApp._themed_toplevel()`（自动深色标题栏）；下拉/弹出菜单用 `CtkMenu`；颜色取 `APP_COLORS`（后续"全局背景色设置"只需改这里）。
- 运行截图：`tmp_out/stage1_*.png`、`stage2_main.png`、`stage3_settings.png`、`stage3_newproduct.png`。

## 本轮（2026-06-14）已完成：文字自动排版引擎统一

详见记忆 `flower-text-layout-unified.md` 与 `AGENTS.md` 顶部。核心：文字排版**算一次、等比不拉伸、预览==导出**。
1. 新增 `text_layout.fit_text_box`（单一大脑：自适应字号 + 断行 + 每行 anchor='ls' 基线 origins，box 本地像素）。
2. `text_renderer._place_text_in_box`：墨迹**等比居中贴框**（删旧的非等比 `_fill_text_box_with_ink` 拉伸）。预览/PNG 同时修好。
3. `desktop_export._text_layer`：把 fit 烘进 `schema["textLayout"]={fontSize,lines,origins}`；render_text 用 `rebuild_render_text` 同源现算。
4. `services/api/.../dxf.py::_resolve_text_line_specs`（svg.py 复用）：有 `textLayout` 就按烘好的 origins 落字，否则旧逻辑（**web 批量/金标无此字段 → 字节不变**）。
5. 名字等比墨迹居中：高 = 框高×`NAME_HEIGHT_RATIO=0.62`，太宽缩到框宽，**`layer.font_size` 变为字号上限 cap**。
6. 对抗审查后又修：origins↔lines 一一对应（零墨迹行占位）、letter_spacing≠0 居中补偿、message 分支接 cap。
- 实测：预览 PNG 墨迹中心 vs DXF 几何中心残差 ~6px/1732px。护栏 `tests/test_text_wysiwyg_consistency.py`。
- ⚠️ 行为变化：名字字号现由文本框自适应（cap=旧 font_size），要更满/更松调 `text_layout.NAME_HEIGHT_RATIO`。

## 本轮（2026-06-13）已完成

1. **DXF 文字 = 方案 B（净轮廓）**：`dxf.py` 文字只输出闭合 SPLINE/POLYLINE 轮廓，无 LINE/HATCH。
   （中途做过扫描线 LINE 自填充=方案 A，用户在 EzCad 验证 HATCH 不被渲染后改选 B，A 已撤销。）
2. **画布位置即输出（WYSIWYG）**：`desktop_export._apply_canvas_fit` 让 DXF/SVG 导出复用预览的视觉 bbox + contain-fit + 居中。实测桌面四路定位偏差 <0.05mm。
3. **批量复用桌面布局（单一来源）**：桌面把 `layout_defaults` 传进批量；`workflow._apply_layout_overrides` 覆盖画布/花朵/文字框/字号 + 去 heightMm 派生，再 contain-fit。批量产出与桌面一致。
4. **UI**：「人工确认并生成」→「生成」；「添加素材为新图层」→「添加素材」；布局说明精简；
   「区分大小写」复选框 → **三态切换按钮（默认/大写/小写）**；全部 `command=self.*` 绑定静态校验无错绑；删了已无意义的「文字实心」勾选框、「编辑素材」里冗余的「是否锁定」。

## 待办 / 剩余功能（新对话从这里继续）

### 0. 图层素材库系统（2026-06-14 新需求，Phase 1 后端已落地）
- **设计文档**：`docs/superpowers/plans/2026-06-14-layer-material-library-system.md`（含分 4 阶段 Task by Task + 进度勾选）。
- 一句话：Product→素材库→素材(key/别名/标签/默认生产参数)→图层(可挂不同库+生产参数随图层 override)；月份字段→「素材库+素材」选择器；订单解析把库 catalog 注入 GPT、动态枚举校验 material_key（本地零硬编码）。演进兼容 birth-flower（month/flower 降为标签，金标/批量字节不破）；后期左侧产品切换器。
- **Task 1（Phase 1 后端）✅ 完成**：新增 `production.py`(ProductionParams+回落链)、`material_library.py`(文件夹/library.json 清单/catalog)；`models.py` 图层加 `library_id/material_key/font_library_id/font_key/production`+迁移；`config_store.py` 加 `ProductConfig`+`products`+零感知迁移「产品0」。全量 317 passed, ruff clean，**未碰 `ui_app.py`**。
- **Task 3（Phase 3 解析对接）✅ 完成**：新增 `order_catalog.py`（`LibraryBundle`/`build_prompt_catalog`/动态枚举 `build_order_remark_schema`/`parse_catalog_payload`/`enrich_parse_result`/`parse_order_remark_with_gpt_catalog`）；`models.ParseResult` 加 `material_library_id/material_key/font_library_id/font_key`；`parse_pipeline` 加可选 `bundle` 富化。**演进兼容：`gpt_parser.py`/`local_order_parser.py`/`orders.py`/`ui_app.py` 全未改**，靠 enrich 桥接旧 month/flower。全量 329 passed, ruff clean。把订单文本→具体 material_key/素材路径的能力做成纯后端可测，GPT 真实接入留待配 key。
- **Task 2（UI，改 `ui_app.py`）✅ 增量 1-5 全部完成**（2026-06-15，用户拍板「完成 345」并选「完整重构」）。分支 `claude/phase4-product-switcher`，全量 **358 passed, ruff clean**。接线契约见 ExecPlan Task 2「🔌 后端接线契约」。
  - **增量1（解析对接）✅ `b5a939c`**：`self.active_bundle`（`_scan_assets` 建，切产品跟随）+ `parse_remark(bundle=)` → enrich 落 material_key。
  - **增量2（每图层挂库）✅ `b5a939c`**：加素材/文本写 `library_id/material_key/font_*`。
  - **增量4（属性面板生产参数随图层）✅ `e723e82`**：图层面板加 X/Y/宽/高 编辑；`_apply_layer_production` 写回画布几何（不旁路 `_apply_canvas_fit`）+ 记 `layer.production`；`_layer_effective_production`=§5 resolve_chain。
  - **增量5（设置管库）✅ `72ea927`**：`config_store.with_product_library_dirs`（纯函数）+ 设置素材库/字体库 tab 目录列表编辑器；`_scan_assets` 主库(单目录入口)+附加库→多库 bundle。**顺手修潜伏 BUG**：`_save_current_config` 整体重建 AppConfig 会清空 products，改 `dataclasses.replace`。
  - **增量3（人工确认面板重构，完整版）✅ `4ff0706`**：去手填月份 Spinbox→只读月份 chip；生产区加 素材库/字体库 选择器（数据驱动 active_bundle，选库过滤候选）；附加库 entries 并入候选（单库空操作）。**安全红线**：`month_var/flower_var/font_var` 保留内部派生态（随选中素材/字体程序化设置）→ 导出/金标/批量/导入零行为变化，仅 UI 不再手填。
  - ⚠️ **真机手测仍待用户做**：本轮只过了自动化测试 + 真 Tk root 构造冒烟，没在真实窗口里点完整链路（选库切换、调几何、加不同库素材、导一单核 ezdxf 实体类型不变）。**改完务必完全关掉 App 重开再测。**
- §10 开放项已按用户「按默认走」拍板（库挂产品下 / 字体同期泛化 / per-素材默认写库清单）。

### 0b. 订单截图视觉解析（screenshot_parser，后端已做，UI 未接，待验证）
- **新增 `screenshot_parser.py`**（已于 2026-06-15 提交 `89763cb`）+ `tests/test_screenshot_parser.py`(5 passed) + 接线契约 `docs/superpowers/plans/2026-06-14-screenshot-vision-parse.md`。把订单截图→视觉模型→ParseResult（不传 bundle 走旧 schema、传 bundle 走 catalog）。复用 gpt_parser 辅助，**未改 gpt_parser/ui_app**。
- **可行性未验证**：没用真图+真 key 跑过；视觉模型必须支持视觉（默认 `gpt-4o-mini`，别用 `gpt-5-nano`）。用户测法见该文档末尾 snippet。**准了再给「导入」按钮接识图（小改 ui_app）；不准就删 `screenshot_parser.py` 零成本**。
- GPT 文本接入本身**已能生效**（设置填 provider/key + 勾「AI 优先」保存；「测试连接」验 key；注意解析失败会静默回退本地）。


### A. EzCad 端闭环（最高优先,核心生产链路）—— 在**独立的 Ezcad 自动导入项目**做（不是本仓库）
- 见记忆 `[[ezcad-runtime-and-p0p1]]`，活跃分支 `claude/p0-p1`。模拟鼠标键盘把 DXF 导入 EzCad。
- 要加两步宏：**① 全选 → EzCad 原生「填充」**（让净轮廓文字变实心）；**② 全选 → 点黑色色块**（变黑）。
- 先切到该仓库、读它的 `CURRENT_TASKS.md` 和导入自动化实现，再落地。

### B. EzCad 复验 flower 的净轮廓能否被原生填充（**等用户实测**）
- 用户导入 `outputs/outline_test.dxf` → 全选 → 填充，看文字能否填实。
- **若填不上**：flower 端备选改法 —— 文字每条轮廓导出为**一条闭合 POLYLINE**（`add_polyline2d(pts, close=True)` + `path.flattening`），
  让 EzCad 直接识别闭合区域。原因：当前 `render_splines_and_polylines` 会把一条字形轮廓切成多段开口曲线（端点相接），EzCad hatch 不一定能自动连。

### C. 杂项 flower 端
- **导出朝向「文字在上、花在下」未解决**（2026-06-14 用户 EzCad 实测仍反；合成测试未复现）。待用户给：哪个导出按钮 + 哪朵花 + 实际文档，再定位（图层位置 / 素材 viewBox / 哪条导出路径）。详见 `AGENTS.md` 已知问题。
- `test_physical_size` 那个红（见上，待用户点头）。
- Stage 3：花左上/名右下的**对角默认布局**（调 `birth_flower_config.json` layout_defaults / `models.EngravingLayout`）。
- 批量管线健壮性（资产解析兜底/审核闭环报错可读性）—— **用户确认现有兜底已够**（失败项进批量报告 + 原因），暂不动。

### D. Electron「新编辑器」（`apps/desktop`）—— **按 ROI 已暂缓**
- 半成品。对"批量量产"几乎无加成（批量是无头的）。只有当需要多人/远程/更好的交互编辑器时才值得做。用户当前不用。

## 每次改完务必
- **完全关掉 Tkinter App 重开**再测（旧进程缓存旧代码）。
- 跑测试在仓库根；改了导出/批量后，建议导一单真实输出用 ezdxf 核一眼实体类型（应 R2018+SPLINE/POLYLINE，无 LWPOLYLINE/TEXT/HATCH）。
