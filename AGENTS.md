# AGENTS.md

> ⚠️ **当前事实（2026-06-14，新对话先读这段）**：本文件下方「Architecture / Frontend / Test Commands(pnpm)」描述的是**暂缓的 Electron 目标架构，不是现状**。
> **生产现实**：用户实际在用的是 **Tkinter 桌面 App**（`birth_flower_mvp.py` + `ui_app.py`）+ **共享后端** `services/api`（桌面以 in-process import 调用，不走 HTTP）。包管理是 **npm 不是 pnpm**。
> **当前事实来源**：`PROJECT_INDEX.md` + `CURRENT_TASKS.md`（已校正本文件 Architecture 段）。导出/EzCad 细节见 `docs/superpowers/plans/2026-06-13-dxf-export-progress.md`。

## 背景（这个项目在做什么）

把电商订单（淘宝/店小秘截图或 xlsx）→ 识别/解析 → 套产品模板 → 生成**可在 CAD/激光软件编辑的雕刻素材**（DXF/SVG/PNG）。当前唯一产品线 `birth-flower-card`：木盒盖上雕「一朵生日花 + 一个名字」（实物 16.5×9.5×4.5cm）。花朵素材固定（`BirthMonth flowers/` 27 个 SVG），名字是个性化文字。字体 2 家族×{otf,ttf}（Malovely Script、AdoraBella）。识别走 GPT/DeepSeek API（GPT 对国内延迟高，故加了 DeepSeek 测试；也在考虑 web 端把服务器放境外）。

## 怎么跑 / 怎么测（务必照做）

- 跑 App：`.\.venv-win\Scripts\python.exe birth_flower_mvp.py`（CPython 3.12，全依赖；任何解释器启动最终 re-exec 到 `.venv-win`）。
- 跑测试（**仓库根目录**）：`$env:PYTHONPATH=".;services\api"; .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q`
- **改完 Python 必须完全关掉 App 重开**（旧进程缓存旧模块，反复踩过的致命坑）。

## 整体目标 / 待办功能（路线图）

订单驱动的自动化雕刻素材生成 + 人工复审：
1. **识别**（店小秘截图/文字 → 大模型 API）：订单号、商品规格、数量、刻字内容、素材（哪朵花）、混合产品。**识别输出 schema 必须对齐后端订单/图层模型**（约束花/字体为枚举，先校验再映射）。
2. **自动拆单**：按 item×数量展开成单盒生产任务（确定性代码，非 AI）。
3. **自动排版文字**：✅ 第 1 步已完成（见下「2026-06-14 改动」）。
4. **按订单号生成文件**：导出文件名已含 orderId（`{templateId}_{orderId}_{exportedAt}`），桌面只需把识别到的订单号写进 `metadata.orderId`。
5. **人工复审工作台**：截图 + 可编辑字段 + 实时预览，对低置信/超框项人工介入。
6. 桌面文本输入框加**右键复制/粘贴**菜单。
> **2026-06-14 新需求（已出 ExecPlan，待实现）**：把「单产品 + 全局单素材库 + month/flower 定位 + 全局生产参数」演进为 **Product → 素材库 → 素材(key/别名/标签/默认参数) → 图层(可挂库+生产参数 override)**。素材/字体不再单一；月份字段→「素材库+素材」选择器；订单解析改为把库 catalog 注入 GPT、动态枚举校验 material_key（本地不写死）。演进兼容（birth-flower=产品0，month/flower 降为标签，金标/批量不破）；后期左侧加产品切换器（每窗口=一个产品）。**设计与分阶段计划见 `docs/superpowers/plans/2026-06-14-layer-material-library-system.md`**。本轮只出文档未改代码。

## 本会话改动（2026-06-15 · 审查并提交本线两提交）

- **审查 + 选择性提交本线工作**（用户拍板"审查+提交本线"）。先全量复跑 **348 passed / 19.46s**、ruff clean，再按概念分两提交（显式 path 暂存，**Electron 改动/dev-*.log/tmp_out/.claude 全排除在外**）：
  - `b5a939c` feat(ui): Phase 2 增量1-2 图层素材库接线（material_library.py + ui_app.py + 两测 + ExecPlan 进度）。
  - `89763cb` feat(parser): 订单截图视觉解析后端（screenshot_parser.py + test + 计划文档）。
- **仍未提交在工作区**：仅 `apps/desktop/**` Electron 前端（非本线，D 项暂缓）+ `packages/design-core`/部分 TS 改动 + 噪音文件（dev-*.log、tmp_out/、.claude/）。下次若要清，建议把噪音加进 `.gitignore`。

## 本会话改动（2026-06-14 · Phase 2 增量1-2 + 截图后端 → 已于 2026-06-15 提交）

承接「图层素材库系统」（顶部新需求）。详见 `CURRENT_TASKS.md` 待办 0 / 0b 与 ExecPlan。
- **四条提交已 commit**（分支 `claude/phase4-product-switcher`）：`62556c0` 后端基线（Phase 1+3）、`0840631` UI 基线（Phase 4+CTk 换肤）、`b5a939c` Phase 2 增量1-2、`89763cb` 截图后端。
- **Phase 2 增量1-2（改 `ui_app.py`，已提交 `b5a939c`，348 passed）**：①`active_bundle`（产品库目录建，切产品跟随）+ `parse_remark(bundle=)`→解析落 material_key；②「添加素材/文本」给图层写 `library_id/material_key/font_*`。**增量3-5（素材库选择器/属性面板生产参数/设置管库）按 ROI 暂停**——单产品单库时视觉≈现状、且与现有 month/flower 选择逻辑深度交织高风险，等真加第二个素材库/产品再做。
- **截图视觉解析（`screenshot_parser.py`，已提交 `89763cb`，未接 UI）**：订单截图→视觉模型→ParseResult。**可行性未用真图+真 key 验过**；准了再给「导入」按钮接识图，不准就删。GPT 文本接入已能生效。
- **GPT 接入无 bug**：设置填 provider/key+勾「AI 优先」保存，「测试连接」验 key（解析失败静默回退本地）。

## 本会话改动（2026-06-14 · Phase 4）：产品切换器（方案2 可收/展）

分支 `claude/phase4-product-switcher`（基于后端基线 `62556c0`，**未提交，待 review**）。全量 **341 passed**，ruff clean。
- `ui_app.py`：最左新增可收/展产品列（`_render_product_rail`/`_build_product_button`/`_toggle_product_rail`/`_switch_product`/`_open_new_product_dialog`/`_create_product_from_dialog`）；模块级纯函数 `product_initial`/`product_rail_items` + 轻量 `_attach_tooltip`。原「预览 + 功能区」两栏布局**未动**（产品列是 pack `side="left"` 的新增列）。
- `config_store.py`：`AppConfig` 加 `products_panel_collapsed`（默认收起，持久化）；新增纯函数 `unique_product_id`/`with_added_product`/`_slugify`。
- 顺手修 BUG：`_save_settings_window` 改用 `dataclasses.replace`，否则保存设置会清空 `products`/`active_product_id`/收展态。
- `tests/test_product_switcher.py`(9) 纯逻辑单测；withdrawn-root 运行态冒烟过。
- ⚠️ **未完**（见 ExecPlan Task 4）：切产品不联动人工确认面板字段（属 Task 2/Phase 2）；多产品端到端未验证（生产仍单产品）。

## 本会话改动（2026-06-14 · UI 换肤）：CustomTkinter 深色迁移（阶段 1-3 完成）

依赖：`customtkinter>=5.2`（已装进 `.venv-win`，登记进 `requirements.txt`）。全量 **341 passed**，ruff clean。运行截图存 `tmp_out/stage*.png`。
- **阶段1 全局深色**：模块级 `ctk.set_appearance_mode("dark")`；`APP_COLORS` 翻深色 + `_configure_styles` 把 ttk(clam) 全控件（含 Notebook、Combobox 下拉）刷深色；产品列改 CTk 圆角。
- **阶段2 主窗口面板**：功能区改 `CTkScrollableFrame`（删手搓 canvas 滚动）；订单/生产/图层/预览/生产输出五块改 `_ctk_card` 圆角卡片；按钮→CTkButton(`_btn`)、输入→CTkEntry、备注→CTkTextbox、勾选→CTkCheckBox、素材/字体下拉→**CTkOptionMenu**（`<<ComboboxSelected>>` 改 `command=`）；`_add_row`/`_add_path_row` 也改 CTk。
- **阶段3 弹窗**：所有对话框 `tk.Toplevel`→`ctk.CTkToplevel`（深色）；新建产品对话框全 CTk。设置/布局/素材编辑弹窗内部沿用 ttk-dark（Notebook 等已刷深色），未逐控件 CTk 化（小尾巴）。
- **画板保持浅色**：`preview_canvas` 仍白底（代表浅色木料；预览是深灰折线+黑墨字，翻黑会看不见，要黑画板需反转 `renderer` 预览色，独立任务）。
- **修的坑**：① 预览 `ImageTk.PhotoImage(..., master=canvas)` 绑定到画板解释器（多 root 测试下原报 image doesn't exist，单 root 也更正确）；② 新增 `tests/conftest.py` autouse fixture 清 CTk 全局 tracker；③ `_widget_texts` 容错 `ValueError`；④ context-menu 测试先 `monkeypatch.undo()` 再 `root.destroy()`（CTkOptionMenu 的 DropdownMenu.destroy 会调 tkinter.Menu.destroy）。
- **⚠️ 启动崩溃回归（已修）**：`import customtkinter` 原是 `ui_app.py` 顶层硬依赖，用非 `.venv-win` 解释器（如 MSYS `.venv`）启动会在 `birth_flower_mvp.py:3 from ui_app import main` 处直接 `ModuleNotFoundError: customtkinter` 崩溃，早于 `_reexec_with_complete_env` 切换 → 窗口闪退。修法：顶层 `try/except ImportError: ctk=None` 容忍 + 模块级 `set_appearance` 加 `if ctk is not None` + `_reexec` 的依赖自检同时 `import customtkinter`（缺它也切 `.venv-win`）。验证：`.venv/bin/python.exe birth_flower_mvp.py` 现可正常 re-exec 到 `.venv-win` 运行。**教训：ui_app 顶层别加只装在 `.venv-win` 的硬依赖，否则破坏引导解释器 re-exec。**

## 本会话改动（2026-06-14 · UI 换肤续）：Ezcad 同款顶部 + 产品列外推

参考用户指定的 `C:\Users\Administrator\Documents\Ezcad2.7.6`（其做法 = `ctk.CTk()` 根窗 + 无原生菜单栏 + CTk 卡片 `corner_radius`，**并非**无边框/外框圆角）。据此改 flower（全量 341 passed，ruff clean）：
- **根窗** `main()` `tk.Tk()`→`ctk.CTk()`（自带深色标题栏；探针实测 ctk.CTk 的 configure/menu/geometry/bind 全可用）。
- **去原生菜单栏**（系统菜单条无法染色=白条，已实测）：菜单迁到 `_build_menubar` 顶栏 CTk 按钮 + `_popup_menu` 用 `tk_popup` 弹出原菜单（深色，菜单存 `self._menus`）。
- **`_enable_dark_titlebar`(DWM)** 仅当回退 `tk.Tk`（测试/缺 ctk）时兜底；`ctk.CTk` 自带不再调。
- **产品列展开 = 窗口加宽**（`_toggle_product_rail` 按 `delta=120` 改 geometry），实测画板宽度 694→694 不变（往外推、不挤画板）。
- **未做**：外框圆角（Win10 直角，Ezcad 也无；真圆角需 `overrideredirect` 自绘，用户暂未选）。
- 测试：`test_birth_flower_app_initializes` 的菜单断言改读 `app._menus`（不再有原生 menubar）。截图 `tmp_out/ui_ctk_top.png`、`ui_expanded.png`。
- **收尾修复（按用户反馈）**：① 收/展箭头方向纠正——收起 `«`(外，下次展开)、展开 `»`(内，下次收起)；② `glyph_panel.py` 也换 `ctk.CTkToplevel` + 玻璃网格 `tk.Canvas` 加 `bg="#242424"`（原是唯一没改的白窗）；③ 菜单 `tk.Menu` 加 `relief="flat"/activeborderwidth=0` 去弹窗白边；④ **`ctk.CTk` 致命坑**：`root.minsize()` 无参 getter 在 CTk 上抛 `TypeError`（`int < None`），`_toggle_product_rail` 原用它读回最小宽 → 真机点收/展即崩（tk.Tk 测试不报）。改用常量 `MIN_WINDOW_WIDTH/HEIGHT`。**教训：ctk.CTk 上别调无参 minsize/maxsize getter；ctk.CTk 专属 bug 用 tk.Tk 测试抓不到，须用 ctk.CTk 冒烟。**
- **对话框白标题栏修复（设置/布局/字形/字形说明）**：`CTkToplevel` 自带深色标题栏**实测不稳**（标题栏仍白；像素采样 (255,255,255)）。统一走 `BirthFlowerApp._themed_toplevel()`：建 CTkToplevel 后 `after(60)+after(350)` 调 `_enable_dark_titlebar`（DWM 设属性 + **1px 几何微调强制重绘**——光 DwmSetWindowAttribute rc=0 也不会重绘标题栏，复杂对话框靠几何微调才变深）。`glyph_panel.py` 同法。`show_glyph_help` 由原生 `messagebox`（白底不可染）改成 CTk 窗口，文案抽到 `GLYPH_HELP_TEXT` 常量（测试断言改读它）。**验证：4 个对话框标题栏像素采样全 (0,0,0)。** 教训：DWM 深色属性设上后必须触发重绘（几何微调）才生效。
- **下拉菜单改自绘 `CtkMenu`**（替代原生 `tk.Menu` 白边弹窗）：模块级 `CtkMenu` = overrideredirect Toplevel + CTk 行；菜单改**数据驱动** `self._menus`（list[(label, items)]，item={label,command} 或 {type:separator}），`_build_menubar` 点按钮→`_open_dropdown`→`CtkMenu.popup`。「导入」子菜单拍平为顶层两项（CtkMenu 不做嵌套）。**白角坑**：圆角 CTkFrame 四角露出 Toplevel 默认浅底→给 Toplevel `configure(bg=panel)` 兜底（角像素 (240)→(36)）。关闭：选中/FocusOut/Esc。`test_birth_flower_app_initializes` 菜单断言改读数据结构。**右键上下文菜单仍是 tk.Menu（未改，如需也可同法改 CtkMenu）**。

## 本会话改动（2026-06-14）：文字自动排版引擎统一

详见记忆 `flower-text-layout-unified.md`。一句话：文字排版改为**算一次、等比不拉伸、预览==导出**。
- 新增 `text_layout.fit_text_box`（单一大脑，返回 font_size/lines/每行基线 origins）；`text_renderer` 墨迹**居中贴框**（删非等比拉伸 `_fill_text_box_with_ink`）；`desktop_export._text_layer` 把排版烘进 `schema["textLayout"]={lines,origins}`；`dxf.py/svg.py` 新增 `_resolve_text_line_specs` 消费它（无 textLayout 则走旧逻辑，**web 批量/金标字节不变**）。
- 名字等比墨迹居中：墨迹高 = 框高×`NAME_HEIGHT_RATIO=0.62`，太宽等比缩到框宽，**`layer.font_size` 从固定字号变为字号上限 cap**（自适应统一各订单名字大小）。
- 实测预览 PNG 墨迹中心 vs DXF 几何中心残差 ~6px/1732px。护栏：`tests/test_text_wysiwyg_consistency.py`。全量 **293 passed, 1 failed**（仅 1 个既有无关红，见下）。

## 已知未解决问题（如实记录，勿当已完成）

- **SVG/DXF 导出朝向「文字在上、花在下」仍存在**：用户 2026-06-14 在 EzCad 实测，导出件是名字在花**上方**（期望花在上/名字右下，对齐样品木盒）。合成测试（自设图层位置）**未复现**，说明问题出在**用户实际文档的图层位置 / 某花朵素材自身 viewBox 朝向 / 某条具体导出按钮路径**之一，尚未定位。导出件里还看到一条飞向左上的离散点线（疑似某素材有离群点）。**待用户提供：哪个导出按钮 + 哪朵花 + 实际文档/截图**再精准定位。当前管线有 3 条 SVG 路径（`desktop_export.render_document_vector_svg` 纯矢量 / `renderer.render_document_svg` 栅格内嵌 / legacy `render_svg` 单图兜底）+ DXF 走 `dxf.py`（已加 Y 翻转）。
- `services/api/tests/test_physical_size.py::test_get_physical_size_derives_height_from_canvas_ratio` 红：模板 `templates/products/birth-flower-card.json` 多写了冗余 `"heightMm": 80`（使 `height_derived=False`，测试期望 True）。删掉即可派生（未经用户确认未动，已挂独立 task）。

---

> 以下为**早期/暂缓的 Electron 目标架构**描述，保留作长期愿景；当前生产现实见顶部「当前事实」。其中 Core Rules / Export Rules / Do Not Do 仍适用，Architecture / Frontend / Test Commands(pnpm) 已被现状取代。

## Project Goal

This project is an order-driven material generation editor.

The goal is to build a lightweight design editor for custom product assets:
- Parse customer order notes.
- Apply product templates.
- Create editable layer-based designs.
- Let the user manually confirm and adjust.
- Export PNG, SVG, and later DXF.

## Architecture

Use the following architecture:

- `apps/desktop`: Electron desktop shell.
- `apps/desktop/src/renderer`: React + TypeScript frontend.
- `apps/desktop/src/renderer/canvas`: Fabric.js canvas editor.
- `services/api`: Python FastAPI backend.
- `services/api/app/domain`: business logic.
- `packages/design-core`: shared TypeScript schemas for templates and layer models.
- `templates`: JSON product templates.
- `assets`: local fonts, flowers, sample files.
- `docs`: architecture, export pipeline, font handling, and refactor notes.

## Core Rules

- Preserve editability. Do not rasterize text, SVG, or layers during editing.
- Save designs as JSON layer documents.
- Separate editor UI state from export state.
- Selection boxes, guides, debug rectangles, and handles must never appear in exported files.
- Keep parsing logic, template logic, font logic, and export logic separated.
- Prefer deterministic code over AI guessing for production export.
- Add full error handling for file I/O, font loading, SVG parsing, and export failures.
- Add Chinese comments for non-obvious business logic.
- Avoid global mutable state unless there is a clear reason.
- Do not introduce new production dependencies without explaining why.

## Frontend Conventions

- Use React + TypeScript.
- Use Fabric.js only inside canvas-related modules.
- Keep React component state separate from Fabric canvas object state.
- Use typed API clients for backend calls.
- Store editor document data in a serializable JSON model.
- Add boundary handling for empty canvas, missing fonts, missing assets, invalid templates, and failed API calls.

## Backend Conventions

- Use Python 3.11+.
- Use FastAPI for HTTP APIs.
- Use Pydantic models for request and response validation.
- Keep route handlers thin.
- Put business logic under `app/domain`.
- All file operations must validate paths and avoid path traversal.
- Return structured errors with clear error codes.
- Add pytest tests for parser, template engine, font scanner, and exporters.

## Export Rules

- PNG export must not include editor-only UI elements.
- SVG export should preserve vector paths whenever possible.
- DXF export should only use path-like geometry; convert text to paths before DXF export.
- Export outputs must include metadata: template id, order id, timestamp, app version.
- Add golden image or snapshot tests for critical templates when possible.

## Test Commands

Frontend:
- `pnpm lint`
- `pnpm test`
- `pnpm build`

Backend:
- `pytest`
- `ruff check .`
- `mypy app`

Desktop:
- `pnpm --filter desktop dev`
- `pnpm --filter desktop build`

## Definition of Done

A task is done only when:
- The feature works through the UI or API.
- Relevant tests are added or updated.
- Lint and type checks pass.
- Edge cases are handled.
- The implementation is documented if behavior changed.
- The final response includes changed files, test results, and known limitations.

## Do Not Do

- Do not rewrite unrelated modules.
- Do not mix old Tkinter UI code with the new editor.
- Do not hardcode absolute local paths.
- Do not silently ignore export errors.
- Do not assume fonts contain normal Unicode characters only.
- Do not store customer order data in logs unless explicitly needed for debugging.

## ExecPlan Rule

For complex features, migrations, or architectural refactors, create or update an execution plan under `docs/` before implementation.