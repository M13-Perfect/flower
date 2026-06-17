# ExecPlan：文字撞花修复 + 全局字体样式（加粗/下划线/字间距）

> 出处：用户用 App 导出「Melanie Helen Margaret（水仙）」发现两点：①长名文字压到花的茎叶上（排版不合格）；②"布局设置"里需要字体样式（加粗、下划线等）。
> 已对齐决策（2026-06-15）：
> - **撞花**：两者都要——先全局几何分区救急，再上代码做稳健避让。
> - **字体样式归属**：全局默认 + 每图层可覆盖（贴合现有图层生产参数体系）。
> - **加粗实现**：轮廓外扩(offset)（脚本字体 AdoraBella/Malovely 无真粗体字重）。

## 根因（已读码确认，非推断）

- 撞花**不是排版算法 bug**：`text_layout._fit_name_layout` 把名字严格 clamp 在文字框内、绝不溢出（text_layout.py:245-249）。
- 真因 = **全局两个框几何重叠**：素材框 (310,40,1060,1060)=x[310,1370]/y[40,1100]；文字框 (780,830,804,260)=x[780,1584]/y[830,1090]。文字框左 73% + 整高都压在素材框里。短名窄、居中落右侧空白 → 不撞；长名填满框宽 → 左半落到茎叶 → 撞。
- 字体样式现状：`字间距(letter_spacing)` 已全链路实现（layer→预览→svg.py/dxf.py），但**未暴露到布局设置 UI**；`加粗/下划线/斜体` grep 零命中 → 完全没有，需新增。

## Stage 1 ✅ 几何分区（config，救急，零代码）—— 已落地（2026-06-15）

> 注：用户已先把画布升级到 **3036×2244**（≈1.753× 旧 1732×1280，同比例）。**桌面 App 活动布局读顶层 `layout_defaults`（已验证 ui_app.py:785），不读 `products[0].defaults`**；故 Stage 1 按 3036 scale 落地，并把 `products[0].defaults` 同步成一致（消除两块不一致）。

改 `layout_defaults` 与 `products[0].defaults`，**让文字框整体落到花的下方、与素材框垂直不重叠**：

| 字段 | 旧(3036) | 新 | 理由 |
|---|---|---|---|
| flower_height | 1858 | **1543** | 花占上段（底=70+1543=1613），腾出底部条带 |
| text_x | 1367 | **1227** | 仍偏右下（短名不破坏现有观感） |
| text_y | 1455 | **1736** | 文字顶 1736 > 花底 1613 → 垂直留空 ~123px |
| text_width | 1409 | **1543** | 给长名更多横向空间 |
| text_height | 456 | **421** | 文字 1736-2157，仍在画布 2244 内 |

其余（canvas 3036×2244、flower_x 543、flower_width 1858、flower_y 70、text_size 210）不动。
- 不变量：素材框 y[70,1613] 与 文字框 y[1736,2157] **无纵向交集** → 任意名字长度都不再压花。
- ⚠️ 风险：**全局生效，影响所有订单**；花略变矮。需开 App 在**短名(Lily)+长名(Melanie Helen Margaret)**各导一张核对。可随时回退。
- ⚠️ 单一全局框仍无法对所有花型完美——这是 Stage 2 代码避让的理由。

## Stage 2 ❎ 代码避让 + 长名断行 —— 已验证「无需做」（2026-06-15）

用真实 `fit_text_box` 在 Stage 1 新框（1543×421, cap 210）上实测，结论：**问题已被 Stage 1 解决，无需写避让代码。**

| 名字 | size | lines | did_fit |
|---|---|---|---|
| Melanie Helen Margaret | 210 | 1（墨迹 1301/1543） | OK |
| Christopher Alexander Montgomery | 178 | 2（自动断行） | OK |
| Genevieve Anastasia Konstantinopolous | 178 | 2（自动断行） | OK |
| 各短名 | 210 | 1 | OK |

- 现有 `_fit_name_layout`(NAME_MAX_LINES=2) 在新框里：长名满字号单行、超长名自动断 2 行、**无一溢出**。
- 「撞花」根因是旧框(804×260)又小又与花重叠；Stage 1 把框移到花下方(纵向不交)后，**contain-fit 保证花 ink≤y1613 < 文字 y1736**，结构上不可能再撞。
- 故**跳过 Stage 2**，避免为不存在的问题加复杂度。若日后改回「紧凑/花字共用纵向带」布局再议 ink 级避让。

## Stage 3 ✅ 字体样式数据层（models.py / config_store.py）—— 已落地

- `EngravingLayout` 加全局默认 `bold/underline/italic/bold_strength`（**bold_strength = 外扩量占字号比例**，默认 0.016；预览 px 与矢量设计单位一致，免 mm 换算）。
- `TextLayer` 加同名 `|None` override；`resolve_text_style(layer,layout)`（override 优先，bold=False 时强度归零）；`layer_text_style(layer)` 供渲染端按图层读（None→关，强度缺省 `DEFAULT_BOLD_STRENGTH`）。
- `config_store` round-trip + 旧配置回落默认。护栏 `tests/test_text_style.py`。

## Stage 4 ✅ 预览渲染（text_renderer.py）—— 已落地·已可视化验证

- 全部预览/PNG 文字都走 `TextRenderer.render_layer`（`canvas_text_item` + `renderer` 均调它），只改它即覆盖**实时画布 + PNG 导出**。
- 加粗：Pillow `text(..., stroke_width=round(strength*font_size), stroke_fill=fill)`；下划线：行墨迹下方画矩形（粗细/间隙占字号比例 `UNDERLINE_*_RATIO`）。
- stroke=0/underline=False 时**逐像素同旧渲染（零回归）**。默认强度 **0.016** 经预览扫值实测选定（0.028 起字怀糊）。斜体暂未做（后置）。
- 验证图：`tmp_out/font_style_final.png`。

## Stage 5 ✅ 矢量导出（svg.py + dxf.py）—— 已落地·已可视化验证

- 装 `pyclipper>=1.4`（用户拍板，登记 requirements.txt）。新增 `dxf.offset_glyph_polygons`：nonzero union 统一定向 + `ET_CLOSEDPOLYGON` 偏移，把字形外圈+内孔**整组**外扩（外圈扩、内孔缩）→ 加粗且保持镂空。svg+dxf 共用。
- SVG：bold 时把 `_glyph_shapes` 扁平多边形 offset 后发同一 `<path>`（nonzero 镂空）；DXF：box 本地扁平→offset→经 matrix 发 POLYLINE（`_polygon_ezpath`）。下划线=基线下闭合矩形。
- `desktop_export` 把 `layer_text_style` 烘进 `schema['style']`(bold/underline/boldStrength)，svg/dxf 消费。
- **验证**：① offset 核心单测（方块外扩 / 带孔外扩内缩 / 零负 no-op）；② 端到端导出 + cairosvg **草书字怀保持镂空**(`tmp_out/vec_bold_underline.png`)；③ DXF 实体只 SPLINE/POLYLINE，**无 TEXT/MTEXT/HATCH**，bold→POLYLINE。护栏 `services/api/tests/test_glyph_bold.py`(3) + `tests/test_vector_font_style.py`(2)。**默认关 → 金标零变化**。

## Stage 6 ✅ UI（ui_app.py）—— 已落地（真机 Tkinter 交互待用户验）

- 布局设置加「字体样式默认」区：加粗/下划线勾选 + 加粗强度输入（独立 `font_bold_var/font_underline_var/bold_strength_var`，不混进 layout_vars 的「全 StringVar+str()」统一处理）。
- 新增 `_active_layout_defaults()`：几何(layout_vars)+样式(独立变量)合并，**两条保存路径共用** → 保存不丢样式；建新文本图层时把全局样式默认**烘进图层**(`_add_text_layer_from_fields`)，渲染端只读图层自身样式。
- 护栏 `tests/test_font_style_ui.py`（真 app 实例验合并/烘焙/覆盖）。
- ✅ **尾巴已接**：字间距=`EngravingLayout.letter_spacing` 全局默认（布局设置输入）+ 建层烘焙；图层级「样式覆盖」面板=文本属性区 加粗/下划线/字间距，「应用文本属性」写回选中图层，`_sync_layer_properties` 回显。可视化验证 `tmp_out/letter_spacing_check.png`。

---
**全部 Stage + 尾巴完成。全量 389 passed, ruff clean。待用户真机验：Stage 1 几何（短名+长名）、预览与设置/属性面板开关、导出件在 EzCad 的加粗/下划线/字间距观感。**
后续可选：加粗强度 per-layer、斜体。

## 怎么测

- `$env:PYTHONPATH=".;services\api"; .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q`
- 每 Stage 先测后提交；改完 Python **完全关 App 重开**再真机手测（旧进程缓存旧模块）。

## 已知未决 / 风险

- Stage 1 全局几何变更影响所有订单，须真机核对短名+长名。
- 加粗 offset 对极细字形可能粘连，需限幅。
- 斜体优先级最低，可砍。
