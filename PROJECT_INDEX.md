# PROJECT_INDEX — flower（订单驱动的雕刻素材生成器）

> ⚠️ **本副本 = 纯桌面+服务侧子集（2026-06-25 从 `Documents\flower`(claude/desktop-tkinter) 迁移而来）。**
> 仅保留：Tkinter 桌面（根目录 .py）+ 运行素材（BirthMonth flowers/、字体、templates/、glyph_maps/、assets/、birth_flower_config.json）+ `services/api` 后端 + tests + `tools/build_windows_exe.py`。
> **已移除（范围外）**：`apps/`(Electron)、`packages/`(TS)、`automation/`(店小秘扩展+inbox-service)、`editor*/`+`gimp_*/`+`vector_binding.py`+`preview_render.py`+`psd_probe*.py`(GIMP-VB 实验轨道)、`packaging/`、Node 工作区文件(package*.json/pnpm/tsconfig)。下文凡提及这些的段落仅作历史参考，本目录已无对应文件。
> **2026-06-25 GIMP 残留已全部移除**：原 GIMP 编辑/模板注册中心的死代码、`gimp_template_id` 配置字段、`docs/gimp/` 与相关 ADR/GPL 文档均已删除；旧 Tkinter 画板为唯一生产编辑器，无遗留报错入口。详见 `AGENTS.md`。
> **验收**：`PYTHONPATH=".;services\api" .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q` → 534 passed / 9 failed / 33 skipped；这 9 个失败全在 `tests/test_ui_app.py`，均为预存在的无头 Tkinter / 迁移期功能缺口（与本次移除无关）。
> 下面是迁移前原文，「两套 UI」中的 Electron 段已不适用本目录。

> 新对话先读这份 + `CURRENT_TASKS.md`。导出/EzCad 细节看 `docs/superpowers/plans/2026-06-13-dxf-export-progress.md`。
> 本文档对比并校正了 `AGENTS.md`（见下「重要：两套 UI」）。最后更新：2026-06-13。

## 1. 项目目标

把电商订单备注（淘宝/店小秘 xlsx 等）→ 解析 → 套产品模板 → 生成**可在 CAD/激光软件里编辑的雕刻素材**（DXF / SVG / PNG）。
当前唯一产品线：`birth-flower-card`（生日花卡：一朵花 + 一个名字）。

## 2. 重要：两套 UI（务必分清）

- **Tkinter 桌面 App = 用户实际在用的生产工具**（`ui_app.py` + `birth_flower_mvp.py`）。单单人工确认/拖拽 + xlsx 批量。**本轮所有改动都在这套 + 共享后端。**
- **Electron「新编辑器」= `AGENTS.md` 写的目标架构，但目前是半成品、用户没在用**（`apps/desktop`，React+Fabric.js）。
  - ⚠️ `AGENTS.md` 说「不要混用旧 Tkinter UI」并把 Electron 当主路线 —— **与现实相反**。生产跑的是 Tkinter。新对话别被 AGENTS.md 误导去动 Electron,除非用户明确要做 web 前端（ROI 见 CURRENT_TASKS）。

## 3. 技术栈

### Python（生产主力）
- **运行/打包**：CPython（见下「两个解释器」）。`pyinstaller`（`BirthFlowerMVP.spec`）。
- **GUI**：`tkinter`（标准库）。
- **图像**：`Pillow`（预览/PNG 栅格）。
- **字体→路径**：`fontTools`（字形轮廓）、`freetype-py`/`uharfbuzz`（字形/整形,glyph_service 用）。
- **DXF**：`ezdxf`（依赖 `numpy`）。**SVG 生成**：`svgwrite` + 手写。**SVG→PNG**：`cairosvg`（Windows 需原生 Cairo,常缺 → 批量 PNG 默认降级跳过,见 `workflow.PNG_SKIPPED_REASON`；桌面 PNG 用 Pillow 自渲染）。
- **后端**：`fastapi` + `uvicorn` + `pydantic v2`；`httpx`（测试）。
- **批量导入**：`openpyxl`（xlsx）。**AI 解析(可选)**：OpenAI（`gpt_parser.py`,默认关）。
- **质量**：`pytest`、`ruff`、`mypy`。

### Node / TypeScript（半成品 web 前端,非生产）
- 根 `package.json`：**npm workspaces**（`npm@11.9.0`,node≥20；注意仓库里还有个**过时的 `pnpm-workspace.yaml` + AGENTS 说 pnpm**,以根 package.json 的 npm 为准）。dev 编排：`node tools/dev.mjs`。
- `apps/desktop`（`@flower/desktop`）：Electron 39 + React 19 + **Fabric.js 7** + Vite 7 + Vitest 4 + TS 5.9。
- `packages/design-core`：共享 TS schema。

## 4. 架构与关键模块

**核心思想:导出权威在 `services/api`,被两条路复用 ——（a）桌面 `desktop_export.py` 桥接、（b）批量 `workflow.py`。所有 DXF/SVG 都走它,保证格式一致。**

### 根级 Python（Tkinter 桌面）
- `birth_flower_mvp.py` — 入口（`ui_app.main()`）。
- `ui_app.py` — Tkinter 主界面（~3100 行）：解析/确认字段、实时画板（拖拽/缩放图层）、生产参数、批量导入、布局设置、字形面板。
- `models.py` — `Document`/`Layer`(Image/Text/Glyph)/`EngravingLayout`（布局默认值）。
- `renderer.py` — 画板预览折线（`flower_preview_polylines`,**视觉 bbox + contain-fit**）、`render_document_png`、旧版 `render_svg/render_dxf`(legacy,无图层时兜底)。
- `desktop_export.py` — 桌面 `Document` → services/api 图层文档 dict → 真实 `export_dxf/export_svg`；**`_apply_canvas_fit`** 把预览的 contain-fit 烘焙进导出（所见即所得）。
- `visual_layout.py` — `fit_content_bbox_to_target_rect`（contain/cover/stretch + 居中）。
- `glyph_service.py`/`glyph_panel.py`/`text_renderer.py`/`text_layout.py`/`canvas_text_item.py` — PUA 字形规则、文本渲染、画板文本项。
- `asset_resolver.py` — 花朵/字体素材扫描匹配。`config_store.py` — `birth_flower_config.json` 读写（含 `layout_defaults`）。
- `parse_pipeline.py`/`gpt_parser.py`/`local_order_parser.py`/`order_importer.py` — 订单备注解析。`order_batch.py` — 早期批量模型,**仅测试用**。

### services/api（FastAPI 后端 + 域逻辑;桌面以 in-process import 调用,不走 HTTP）
- `app/domain/exports/dxf.py` — **DXF 导出权威**（R2018 + SPLINE/POLYLINE + 单层"图层 1"色7 + 文字净轮廓 + `apply_svg_contain_fit`）。`svg.py`/`png.py` 同级。
- `app/domain/orders/workflow.py` — `generate_batch_outputs`（批量,调真实 export_dxf）、`_apply_layout_overrides`（批量套桌面布局）。`batch_generate.py`/`batch_import.py`/`batch_store.py`/`review*.py`/`parser.py`。
- `app/domain/templates/engine.py`（`apply_template`）、`physical.py`（物理尺寸,唯一来源是模板文件）。
- `app/main.py` — FastAPI app（web/CLI 用）。

### 数据/配置
- `birth_flower_config.json` — 桌面配置 + **`layout_defaults`（布局单一来源:画布 1732×1280、花朵 1060²@310,40、文字 804×260@700,830、字号 190）**。
- `templates/products/birth-flower-card.json` — 批量模板（画布 3000×3000;批量运行时被桌面 `layout_defaults` 覆盖）。
- `glyph_maps/*.json` — PUA 字形绑定/规则。`BirthMonth flowers/` + `Birthmonth_font.ttf` — 素材/字体。

## 5. 怎么跑 / 怎么测（务必照做）

- **两个 Python 解释器**：
  - `.venv-win`（CPython 3.12,**全依赖,跑 App/测试用这个**）。
  - `.venv`（MSYS Python 3.14,**缺 numpy/pydantic**）。`ui_app._reexec_with_complete_env()` 会在缺 numpy 时自动重启到 `.venv-win`,所以随便哪个启动最终都切到 .venv-win。
- **跑 App**：`.\.venv-win\Scripts\python.exe birth_flower_mvp.py`
- **跑测试（必须在仓库根目录）**：
  `PYTHONPATH=".;services\api"  .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q`
  - lint：`.\.venv-win\Scripts\python.exe -m ruff check <file>`
- **前端（半成品,一般不用）**：`npm run dev`（= `node tools/dev.mjs`）。

## 6. 致命坑（反复踩过）

1. **改完 Python 代码必须完全关掉 App 重开** —— 旧进程把旧模块缓存在内存,改源码不生效。本会话「文字不实心 / 批量没生效」全是这个根因。
2. **EzCad 行为**：① 不渲染 DXF **HATCH**（实心填充别指望 HATCH）；② **LWPOLYLINE 选中改不动**（必须 R2018 + SPLINE/POLYLINE）；③ 颜色/填充在**独立的 Ezcad 自动导入项目**里用 EzCad 原生功能做。
3. **flower 文字 = 方案 B：只出闭合净轮廓,不在 DXF 内填充**；实心由 EzCad 导入后「填充」完成。变黑同理（点黑色块）。
4. **WYSIWYG 坑**：`dxf.py/svg.py` 的 `_svg_view_box` 优先用内联 SVG 自带 viewBox,会忽略 layer.viewBox → contain-fit 要把 fit 折进 layer 的 x/y/w/h（`layer_origin=fit.draw+fit.scale*viewBox_origin`）。
5. **批量布局**：批量必须用桌面 `layout_defaults`（单一来源,已接）；模板自带的 3000×3000 只在 `layout=None`(金标/CLI) 时用。
6. 跑 pytest 必须 CWD=仓库根（部分测试用相对路径）。
