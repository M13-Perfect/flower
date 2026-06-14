# DXF/导出对齐 — 进度交接(2026-06-13)

> 配套规格:`docs/superpowers/plans/2026-06-13-align-to-standard-dxf.md`
> 本文件记录该规格的实际落地进度,供新对话接续。**只列本轮改动**,仓库里其它未提交改动是分支既有的,与本轮无关。

## 当前状态总览(已全部跑通,289 测试绿)

桌面「人工确认并生成」按钮已接到 services/api 的真实矢量导出;DXF 在 EzCad2 里可编辑、单层、朝向正确、文字可见。

## 关键运行方式

- **跑 App**:`.\.venv-win\Scripts\python.exe birth_flower_mvp.py`
  - 重要:旧的 MSYS `.venv`(Python 3.14)缺 `numpy`(→ezdxf 用不了)和 `pydantic`(→物理尺寸读取失败)。
  - `ui_app.py` 的 `main()` 开头加了 `_reexec_with_complete_env()`:当前解释器缺 numpy 时自动用 `.venv-win` 重启自己(guard 环境变量 `FLOWER_PY_REEXEC` 防死循环,frozen 时跳过)。所以**任何方式启动都会自动切到 .venv-win**。
- **跑测试**(必须在仓库根目录,否则 4 个 windows 打包测试因相对路径找不到文件而误报):
  ```
  cd C:\Users\Administrator\Documents\flower
  PYTHONPATH=".;services\api"  .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q
  ```
- **标准样件**:`C:\Users\Administrator\Desktop\3~4076779088.dxf`(R2018/AC1032,INSUNITS=4,59 SPLINE + 12 HATCH,单内容层"图层 1"色7)。
- **QA 工具**(仓库外):`C:\Users\Administrator\Documents\asset-qa\` — `render_dxf.py`(DXF→SVG)、`check_assets.py`(体检)、`analyze_reference.py`(解剖)。

## 本轮改了哪些文件 + 为什么

### `services/api/app/domain/exports/dxf.py`(导出权威)
- **R12→R2018**,保留 `$INSUNITS`;几何管线改产 `ezdxf.path.Path`,用 `render_splines_and_polylines` 输出 **SPLINE**(曲线)/POLYLINE(直线),**不再扁平化**。
- **单内容层** `_ENGRAVE_LAYER = "图层 1"`,**实体显式 ACI 色 7**(`dxfattribs={"layer","color":7}`)——之前 BYLAYER(256)在 EzCad 显示成红色,显式 7 才稳定为黑。
- **`g1_tol = _SPLINE_JOIN_G1_TOL = 1e9`**:把一条轮廓的连续贝塞尔合并成一条 SPLINE(尖角靠节点重数精确保留),实体数大降、贴近样件。
- **解耦字形走查**:`_glyph_contours`(中性轮廓,字体单位空间,qCurveTo 沿用旧近似以保证 SVG 金标不变)→ `_glyph_shapes`(点集,SVG/PNG 用,不依赖 ezdxf)/ `_glyph_paths`(Path,DXF 用)。`_parse_path_objects`(Path)与 `_parse_path_shapes`(点集,PNG 预览用)并存。`_svg_layer_paths`/`_svg_layer_shapes` 共用 `_svg_path_leaves`。
- **实心/空心(Stage 2)**:`_LayerPath(path, fill)`,文字图层 `fill=True`。`_write_dxf`:
  - **文字始终输出闭合 SPLINE/POLYLINE 轮廓**(EzCad 不渲染 DXF HATCH 实体,只给 HATCH 会导致"文字不显示"——这是上一轮的 BUG,已修);
  - **实心模式额外叠加 HATCH SOLID**(支持的软件直接实心;EzCad 忽略,不影响)。
  - `_text_fill_mode` 读 `exportSettings.text.fill`(默认 `solid`)。
- **`_resolve_font_path`** 加显式 `fontRef.path`(项目内相对路径,经 `_safe_project_path` 校验)入口,让桌面所选字体文件驱动导出。

### `desktop_export.py`(新文件 — 桌面 Document → 导出桥)
- `render_document_dxf` / `render_document_vector_svg`:桌面 `Document`(models.py)→ services/api 图层文档 dict → 真实 `export_dxf`/`export_svg`,写文件。
- 模块顶把 `services/api` 插入 `sys.path`(惰性 import app.* 一定可用)。导出层 `DomainError`→`ValueError`(UI 友好提示)。
- 参数:`physical_width_mm`(None→默认 80mm)、`text_fill`("solid"/"outline")。SVG 素材内联、viewBox 解析、glyphOverrides(base_char/replacement_char/codepoint 直接对接导出端)。

### `ui_app.py`(Tkinter 桌面)
- `confirm_and_generate`:有图层时 DXF/SVG 走 `render_document_dxf`/`render_document_vector_svg`(真实矢量);PNG 走 `render_document_png`。传 `physical_width_mm`(从模板读)和 `text_fill`。
- `_template_physical_width_mm()`:读产品模板 `exportSettings.physical.widthMm`(布局设置同一数据源)。
- `_reexec_with_complete_env()`(见上)。
- 生产输出栏加「**文字实心**」勾选框 `self.fill_solid_var`(默认勾上=solid)。
- import 加 `from desktop_export import render_document_dxf, render_document_vector_svg`,去掉对 `render_document_svg`(旧位图内嵌)的 import。

### `renderer.py`
- `render_document_png` 背景从米色 `(255,248,240,255)` → **透明 `(0,0,0,0)`**:激光按明暗下刀,实心背景会把整块底刻出;透明底只留墨迹。
- 旧 `render_dxf(design)`/`render_document_svg`(位图内嵌)仍在,作为无图层时的 legacy 兜底 + glyph 单测,**按钮有图层时不再走它们**。

### `README.md`
- 启动命令 `.venv\bin\python.exe` → `.venv-win\Scripts\python.exe`,并注释原因。

### 测试
- `services/api/tests/test_dxf_export.py`:改用真实 ezdxf 回读;新增实心(HATCH+可见轮廓)/空心(POLYLINE)用例。
- `tests/test_document_vector_export.py`(新):Document→render_document_dxf 回读断言 R2018/SPLINE/单层色7/物理宽度;纯矢量 SVG;DomainError→ValueError。

## 用户已确认/已验证
- DXF 能导出(re-exec 生效)、花朵黑色线稿、朝向花上名下、单层、可编辑。
- 上一轮"文字消失"BUG已修(EzCad 忽略 HATCH;现在文字有可见闭合轮廓)。

## 待用户验证 / 待办(新对话从这里继续)
1. **EzCad 里确认**:① DXF 颜色现在是不是黑(ACI 7);② 实心文字 — 文字现在是**闭合轮廓**,EzCad 里要做实心雕刻需选中文字用 EzCad 自带"填充(Hatch)"功能(EzCad 不认 DXF HATCH 实体);③ PNG 透明底雕刻是否 OK。
2. 若 ACI 7 在该 EzCad 仍非黑:改真彩 RGB(0,0,0) 或指定笔号。
3. **Stage 3 布局**:用户要"花左上/名字右下"对角默认。当前默认已是"花在上、名字在下"(config layout_defaults: flower_y=40 < text_y=830),但非严格对角;如需精调默认坐标在 `birth_flower_config.json` layout_defaults / `models.py` EngravingLayout。
4. SVG 空心模式未接(export_svg 文字恒填充;默认实心正合用户要求)。
5. 批量管线 `generate_batch_outputs` 的 DXF 是占位桩(测试 mock fake_dxf),真实导出未接到批量(本轮聚焦桌面按钮)。
6. Stage 2 文档侧:若要花朵某些区域也实心,需按 SVG path 的 fill 属性区分填充/描边(当前 SVG 一律描边 SPLINE)。

## 易踩坑
- 跑 pytest 必须 CWD=仓库根(test_entrypoint/test_windows_packaging 用相对路径)。
- 两个解释器:`.venv-win`(CPython 3.12,完整依赖,跑 App/测试用这个)、`.venv`(MSYS 3.14,缺 numpy/pydantic,会触发 re-exec)。
- SVG 在 CAD 里看会上下翻转(SVG Y 向下、CAD Y 向上)且按组分层 —— 这是格式特性,**CAD 用 DXF,不要用 SVG 判断朝向**。

---

## 2026-06-13 续(本次会话:文字实心 + 画布位置即输出 + 删除锁定)

用户在 EzCad 实测反馈后,本轮改了 3 件(全绿 288;另 1 个 `test_physical_size` 失败是分支把
`templates/products/birth-flower-card.json` 加了 `heightMm` 所致,**与本轮无关**)。

1. **文字实心 = 方案 B:flower 只出净轮廓,填充交给 EzCad 原生「填充」**(经 Ezcad 自动导入项目)。
   - 决策过程:先做了扫描线 LINE 自填充(方案 A),但用户用带 HATCH 的测试件在 EzCad 验证后确认
     **EzCad 确实不认 DXF HATCH**(只显示空心轮廓);又因为已在做 EzCad 鼠标键盘自动导入,
     最终选 B —— flower DXF **不做任何填充几何**,导入后由自动化「全选→EzCad 原生填充」一步完成
     (与点黑色块同一宏)。**扫描线方案 A 已全部撤销**。
   - `dxf.py` 现状:文字 `_text_layer_paths` 只返回闭合字形轮廓;`_write_dxf` 只 `render_splines_and_polylines`,
     无 LINE、无 HATCH;`_LayerPath.fill` 仅作信息标记。`_glyph_fill_lines`/`_scanline_*`/`_text_fill_*`/填充常量已删。
   - `ui_app` 的「文字实心」勾选框已删除(填充不再由 flower 控制)。
   - **待 EzCad 复验**:当前轮廓经 `render_splines_and_polylines` 会把一条字形轮廓切成多段开口 SPLINE/POLYLINE
     (曲线段与直线段分家),端点相接。EzCad hatch 一般能自动连接相接曲线成闭合区域并填充;**若实测填不上**,
     备选改法:文字每条轮廓导出为**一条闭合 POLYLINE**(`add_polyline2d(pts, close=True)`,`path.flattening` 展平),
     让 EzCad 直接识别闭合区域(代价:文字轮廓由样条变折线,边缘 0.05mm 容差仍平滑)。

2. **画布位置即输出(WYSIWYG)**。`desktop_export.py` 新增 `_apply_canvas_fit`:让 SVG 素材导出复用预览/PNG 的
   contain-fit(`renderer._svg_geometry().visual_bbox` + `visual_layout.fit_content_bbox_to_target_rect`,居中)。
   - **关键坑**:导出端 `dxf.py/svg.py` 的 `_svg_view_box` 优先用内联 SVG **自带的 viewBox**,会忽略 layer.viewBox。
     所以不能只改 layer.viewBox,而是把 fit 折进 layer 的 x/y/width/height:
     `layer_size=fit.scale*声明viewBox尺寸`、`layer_origin=fit.draw + fit.scale*声明viewBox原点`,viewBox 保持声明值。
   - 效果:DXF/矢量SVG/PNG/画布预览四者定位一致(实测偏差 <0.05mm)。文本位置本就随 layer.x/y,未动。

3. **删除「编辑素材」对话框的「是否锁定」**(`ui_app.open_material_editor`),保留「锁定宽高比」;
   几何输入框恒可编辑;图层整体锁定仍由右键图层菜单「锁定/解锁」负责。

### 颜色"变黑":移交 Ezcad 自动导入项目(本轮未做)
原待办「ACI 7 仍非黑 → 改真彩」**已与用户商定不在 flower 改**。flower 维持单层 ACI 7。
改由独立的 **Ezcad 自动导入项目**(模拟鼠标键盘,分支 `claude/p0-p1`)在 DXF 导入 EzCad 后
执行「全选 + 点黑色色块」把图形变黑。需切到该仓库、读其 `CURRENT_TASKS.md` 与导入自动化实现后再落地。

### 仍待办
- **EzCad 复验填充**:导入 `outputs/outline_test.dxf`,「全选→填充」看文字能否被 EzCad 原生填实;
  填不上则走上面的"一条闭合 POLYLINE/轮廓"备选改法。
- 颜色变黑 + 填充:都在 Ezcad 自动导入项目里做(导入后自动「全选→填充」「全选→点黑色块」)。
- 用户在 EzCad 复验:拖动后位置与画布是否一致(WYSIWYG)。
- Stage 3 对角默认布局。

## 2026-06-13 续2(前端文案/按钮 + 批量 contain-fit)

- **批量导出接上 contain-fit**:之前以为是桩,实际 `workflow.generate_batch_outputs→_save_document_outputs→export_dxf`
  早已走真实导出,但花朵 SVG 用 `engine._flower_layer` 写死的 1200×1400 框被**非等比拉伸变形**。
  现在 `_save_document_outputs` 在导出前调 `dxf.apply_svg_contain_fit(document)`(新函数,services/api 自带,
  用自己的 SVG parser 算真实墨迹 bbox,做等比 contain-fit+居中+裁留白,折进图层 x/y/w/h、保留声明 viewBox),
  与桌面 `desktop_export._apply_canvas_fit` 同一套数学、同结果。批量金标 `real_note_*.svg` 已更新
  (`scale(120 140)`拉伸→`scale(120 120)`等比)。**注**:桌面与批量目前是两份 contain-fit 实现(桌面用 renderer 的
  bbox 以精确贴预览,批量用 services/api parser),结果一致;如需彻底 DRY 可后续合一。
- **UI**:「人工确认并生成」→「生成」;「添加素材为新图层」→「添加素材」;布局说明文字精简;
  「区分大小写」复选框 → 三态切换按钮(默认/大写/小写,`text_case_var`+`_cycle_text_case`,影响 `_content_text_for_render`)。
  全部 `command=self.*` 绑定静态校验无错绑。

## 2026-06-13 续3(批量复用桌面布局 — 单一来源)

- **问题**:批量产出虽是新格式(R2018/SPLINE/净轮廓/contain-fit),但**布局是模板那套**(画布 3000×3000 方图、
  花朵框 1200×1400、字号 180),和桌面满意的 `birth_flower_config.json` `layout_defaults`(1732×1280、花朵 1060×1060、
  文字 700/830/804/260、字号 190)完全不同 → 批量花朵偏小、方形卡片,用户视为"失败"。
- **修法(单一布局来源)**:桌面 App 把当前 `layout_defaults`(`layout_from_values(self.layout_vars)` → `dataclasses.asdict`)
  传进 `import_dianxiaomi_xlsx_batch(path, layout=) → generate_batch(layout=) → generate_batch_outputs(layout=)`;
  新增 `workflow._apply_layout_overrides(document, layout)` 覆盖画布 + 花朵/文字框 + 字号,并 `physical.pop("heightMm")`
  让高度按新画布比例派生(等比不变形),随后照常 contain-fit + `export_dxf`。以后改桌面布局,批量自动跟随。
- **注**:`generate_batch_outputs(layout=None)` 时(如金标测试/CLI)仍用模板默认布局,故 `real_note_*` 金标不变。
  实测失败单 4087958577 套桌面布局后:画布 1732×1280(80×59mm)、设计宽 19.7→31.4mm,与桌面一致。
- **改完批量代码同样要重开 App**(旧进程内存里是旧代码,这是之前几次"看着没生效"的根因)。
