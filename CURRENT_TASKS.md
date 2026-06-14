# CURRENT_TASKS — flower

> 配 `PROJECT_INDEX.md` 一起读。导出/EzCad 细节看 `docs/superpowers/plans/2026-06-13-dxf-export-progress.md`。
> 更新：2026-06-14。

## 测试基线

`PYTHONPATH=".;services\api" .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q`
→ **293 passed, 1 failed**（2026-06-14 文字排版统一后；新增 `tests/test_text_wysiwyg_consistency.py` 等护栏）。唯一失败 = `test_physical_size.py::test_get_physical_size_derives_height_from_canvas_ratio`，
**与本轮无关**：分支早先给 `templates/products/birth-flower-card.json` 加了 `"heightMm": 80`（使 `height_derived=False`，
测试期望 True）。一行可修（删掉那个冗余 heightMm 让高度派生），但那是别人未提交改动，**未经用户同意没动**（已挂独立 task）。

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
- **Task 2（UI，改 `ui_app.py`）未开始——建议直接交给正在改 UI 的那条对话接手（ROI 最高，它独占 ui_app.py = 零冲突，后端已在同工作区可直接 import）**。后端胶水 + **接线契约**已就绪：见 ExecPlan Task 2 顶部「🔌 后端接线契约」（6 个缝：建 bundle / 素材库·素材选择器 / `add_image_layer`·`add_text_layer` 新字段 / 属性面板 `resolve_chain` / `parse_order_remark_auto(bundle=)` 落图层 / 设置窗口管库）。`models.add_image_layer/add_text_layer` 已支持 `library_id/material_key/font_*/production`；`LibraryBundle.from_dirs(image_dirs, font_dirs)` 一行建库。全量 332 passed。Phase 3 Step 4（ParseResult→Document）并入此处第 5 缝。
- §10 开放项已按用户「按默认走」拍板（库挂产品下 / 字体同期泛化 / per-素材默认写库清单）。


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
