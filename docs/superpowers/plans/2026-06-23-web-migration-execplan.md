# Web 迁移 ExecPlan（前后端完整搬移）

> 立项 2026-06-23。用户拍板 **①+②+③ 完整搬移**（web 端要能完全替代桌面端跑生产）。
> 分支：当前活分支 = `claude/desktop-tkinter`（**桌面引擎 + web 前端 apps/desktop + services/api 都在这条分支上**；用户正在此并行做前端 `e339031 "Revamp desktop web prototype to match ui_app layout"`）。
> ⚠️ `.worktrees\web-editor`(85f172e) 是旧基线，已过时，别拿它当事实来源。

## ⚠️ 2026-06-23 重大订正（推翻 §12 旧体检的核心假设）

旧 plan §12 说"services/api 引擎落后根目录几个月、web 弃自己引擎改调根"。**对矢量导出这条路是错的，方向相反。** 实测（`claude/desktop-tkinter`）：

- **DXF/SVG 矢量导出引擎早已在 `services/api` 上归一**：`services/api/app/domain/exports/{dxf,svg,png}.py` 是权威引擎。**桌面端反过来调它**——`desktop_export.render_document_dxf/render_document_vector_svg` 把根 `Document` 经 `_document_to_layer_document` 翻成 web `document` JSON（schemaVersion 1.0），lazy import `app.domain.exports.export_dxf/export_svg` 来导出（`desktop_export.py:58-65`/`83-90`；还在 `sys.path` 插了 services/api）。docstring 明写：为修 EzCad2"可选中改不动尺寸"才把桌面改成复用 web/批量端引擎。
- 即：桌面与 web **喂同一个 `document` schema、同一个 services/api 引擎**。所谓"web→根 models.Document 桥接 + 删 services/api 3000 行平行引擎"**不存在、也不该做**——会把权威引擎删掉。
- 旧 `renderer.render_dxf(design: BirthFlowerDesign)` 是 legacy 单设计路径（TEXT 实体/R12），仍被 `ui_app.py:5427` 调用于无图层/legacy 场景；不是多图层矢量主链路。

**教训**：动手前必须确认在 `claude/desktop-tkinter` 分支（不是 main）。main(df201a5) 上没有 desktop_export.py / fit_text_box，看到的是旧引擎。

## 范围与排序

完整搬移 = ①+②+③，按 ①→②→③ 分阶段，每阶段独立可用。

| 阶段 | 内容 | 修正后估时 |
|---|---|---|
| **① 后端归一（剩余）** | 矢量导出已归一；**只剩**：A) 暴露 `/exports/svg`+`/exports/png` 路由；B) 解析侧归一（order_catalog/material_library/production/gpt_parser/screenshot_parser/config_store 接进 services/api，`/orders/parse` 改走它） | A ~0.5 天；B ~1–1.5 周 |
| **② 批量量产上 web** | 无头批量（粘单→复核表格→生成→下载 zip），无画布 | ~1 周 |
| **③ 交互画布编辑器上 web** | apps/desktop(React19+Fabric7)补齐 + 对齐桌面行为（用户正在做前端） | 3–5 周 |

① 比旧估（2–3 周）大幅缩水：矢量导出归一这块**本就不用做**。

## ① 剩余工作 step-by-step

### A. 暴露 SVG/PNG 导出路由（最小增量，纯加不删）—— 先做这个
- `services/api/app/main.py` 仿 `/exports/dxf`（:128）加 `@app.post("/exports/svg")`、`/exports/png`，调已存在的 `app.domain.exports.export_svg/export_png`。
- 补对应 Pydantic request/response schema（仿 `schemas/exports.py` 的 DxfExportRequest/Response）。
- 验证：起 services/api，对一个 fixture document POST /exports/svg、/exports/png，确认产物。**纯增量，删 0 行。**
- 之后 web 前端弃 `apps/desktop/.../exportPipeline.ts` 的 TS 渲染，改调这两个端点 → 关掉 §12 #1 的 WYSIWYG 偏差（前端侧，用户在做）。

### B. 解析侧归一（真正的后端缺口）
- services/api `domain/` 缺：order_catalog / material_library / production / gpt_parser / screenshot_parser / config_store。桌面端在用根目录这几份。
- 懒接法（同 desktop_export 已用的模式）：services/api 已把仓库根可加进 sys.path → 让 `/orders/parse` 改走根 `parse_pipeline`(+`order_catalog` bundle / `gpt_parser`)，而非现在的旧本地 `domain/orders/parser.py`。
- 决策待定：是"services/api import 根模块"（最省、与 desktop_export 一致）还是"把模块搬进 services/api"。**默认走 import 根**（lazy，已有先例）。
- 验证：`/orders/parse` 对带素材库枚举的真单返回 material_key，对齐桌面解析结果。

## ② 批量量产 web（① 后）
无头批量已在 services/api（`domain/orders/batch_*`、`workflow`）。web UI = CRUD：粘单 → `/orders/parse` 批量 → 复核表格（可改字段）→ 生成 → 下载 report.xlsx + zip。无 Fabric。

## ③ 交互编辑器 web（用户正在做前端）
apps/desktop 已有半成品（FabricCanvas/canvasConstraints/canvasViewport/layerFabricModel/editorActions/orderWorkflow/exportPipeline）。用户 `e339031` 正在"对齐 ui_app 布局"。要补：PS 风图层树、三端角色 + 提示词配置密码门、导出改调后端（§A 的 SVG/PNG 路由）。

## 并行工作协调（重要）
- 用户在 `claude/desktop-tkinter` 主工作树上**并行改前端**（apps/desktop）。我若改后端（services/api/main.py、schemas），文件不撞，但**同分支未提交状态会互相牵连**（对方切分支/提交时会带上我的未提交改动）。
- 约定：动 git（switch/commit/reset）前先问用户；改文件集中在 services/api 后端，避开 apps/desktop。

## 已知风险 / 关卡
- **分支陷阱**：必须在 `claude/desktop-tkinter`。main 上引擎是旧的，会误导（本轮已踩过：工作树被切到 main 导致 desktop_export.py"消失"、root 映射读了旧引擎而作废）。
- **不要删 services/api 的导出引擎**：它是权威，桌面也依赖。
- SVG/PNG 路由要复用现有 export_svg/export_png 的真实签名（先读签名再写 schema）。

## 进度
- 2026-06-23：立项 + 范围（①+②+③）。**订正**：矢量导出引擎已在 services/api 归一（桌面委托调用），原"web→根桥接/删平行"方向作废。核实剩余缺口 = SVG/PNG 路由 + 解析侧归一。
- 工作树曾被切到 main（用户并行操作），已切回 `claude/desktop-tkinter`，引擎文件复原。
- ✅ **①-A 之 SVG 路由已落地**（纯增量）：`schemas/exports.py` 加 `SvgExportRequest/SvgExportResponse`；`main.py` 加 `@app.post("/exports/svg")` 调既有 `export_svg`。冒烟 `tmp_out/smoke_svg_route.py` 引擎+路由(TestClient 200)双过；services/api 全量 **78 passed**。未提交、未切分支。
- 下一步：①-A 之 PNG 路由（`/exports/png` 走 `rasterize_svg_to_png`，需 cairosvg + 临时文件 + 按 canvas×png.scale 推宽高），然后 ①-B 解析侧归一。
