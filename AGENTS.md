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