# CURRENT_TASKS — flower（纯 Python 桌面版）

> 配 `PROJECT_INDEX.md` + `AGENTS.md` 一起读。导出/EzCad 细节看 `docs/superpowers/plans/2026-06-13-dxf-export-progress.md`。
> 更新：2026-06-25（移除 GIMP 轨道后）。

## 测试基线（2026-06-25，Layer System v2 全部 Packet 完成后）

`PYTHONPATH=".;services\api" .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q`
→ **622 passed / 0 failed / 33 skipped**（Windows 上加 `--basetemp .pytest-tmp-run` 避开 Temp 清理权限问题）。迁移期遗留的 7 个 `test_ui_app.py` 失败已在 Packet 7 全部修复/订正。`ruff`、`py_compile` clean。分支 `layer-system-v2-rest`（未 merge/push）。

## 最近改动

- **2026-06-25 Layer System v2 Packet 5：普通组合 + 自动布局组合**：`models.py` 新增 `AutoLayoutGroupLayer` / `resolve_auto_layout` / 创建与转换函数；`ui_app.py` 右键菜单接组合、自动布局组合、转自动布局、解组，预览改 `flat_render_layers()` 并在锚定爱心前跑自动布局；`desktop_export.py`、`renderer.py` 导出前共用同一 layout pass；inline 文本编辑首次修改只压一条 history，Esc 取消弹掉预览快照。新增 `tests/test_layer_auto_layout.py`，并补 `test_canvas_layer_redesign.py` 的 inline undo 边界测试。
- **2026-06-25 移除全部 GIMP 残留**：见 `AGENTS.md`「本次改动」。旧 Tkinter 画板为唯一编辑器。
- **2026-06-25「+ 图片图层」按钮静默失效已修**：`_refresh_flower_choices` 末尾补默认选中（`flower_asset_var` 不在 `flower_label_map` 时回落第一个素材），恢复「永远有默认选中」不变量；解析路径仍优先 `_select_flower_by_parse_result`。
- **2026-06-25 库/素材选择做进图层行（Option C 弹层）**：图层面板 `ttk.Treeview` 加「资源」列，点单元格弹原生 `tk.Menu` 选素材/字体（`_open_layer_resource_picker`/`_add_resource_cascades`，右键菜单共用）；换素材/字体**保留手动几何**、仍可 Ctrl+Z。

## 待办 / 剩余功能

### A. EzCad 端闭环（最高优先，核心生产链路）——在独立的 Ezcad 自动导入项目做（非本仓库）
- 模拟键鼠把 DXF 导入 EzCad，加两步宏：① 全选 → EzCad 原生「填充」（净轮廓文字变实心）；② 全选 → 点黑色色块（变黑）。
- 先切到该仓库读它的 `CURRENT_TASKS.md` 与导入自动化实现，再落地。

### B. EzCad 复验 flower 净轮廓能否被原生填充（等用户实测）
- 导入 `outputs/outline_test.dxf` → 全选 → 填充，看文字能否填实。
- 若填不上：flower 端把文字每条轮廓导成**一条闭合 POLYLINE**（`add_polyline2d(pts, close=True)` + `path.flattening`），让 EzCad 识别闭合区域。

### C. flower 端杂项
- **图层系统 Layer System v2：全部 Packet 已落地**（Packet 0/1/2/3/4/5/6/7，分支 `layer-system-v2-rest`）。**剩真机手测 + 增量收尾**（详见 `AGENTS.md`「已知问题」）：①非模态栏/添加菜单/缺素材占位/中键平移等需关 App 重开实测；②悬浮栏字距/行距/对齐/颜色/字体已声明未接 write-back（增量）；③Document v2 序列化已可用但无存盘 UI（待接按钮）；④内联编辑 history 未并入新事务 API。验证通过后再决定合回 main。
- **导出朝向「文字在上、花在下」**（2026-06-14 用户 EzCad 实测仍反，合成测试未复现）——待用户给具体导出按钮 + 哪朵花 + 实际文档再定位。
- **订单截图视觉解析** `screenshot_parser.py`（后端已做、UI 未接、未用真图+真 key 验）：准了再给「导入」按钮接识图（小改 `ui_app`），不准就删，零成本。
- ~~修迁移期遗留的 `test_ui_app.py` 失败~~ **已在 Packet 7 完成**：补 `_on_canvas_pan_press`（中键平移）、订正 preview 标尺/缩放/滚轮 without_display 断言、`case_button` 孤儿防御。全量 0 失败。

### D. Electron「新编辑器」（`apps/desktop`）—— 已暂缓
- 半成品，对无头批量量产几乎无加成。仅多人/远程/更强交互编辑器时才值得做。用户当前不用。

## 每次改完务必
- **完全关掉 Tkinter App 重开**再测（旧进程缓存旧代码）。
- 跑测试在仓库根；改了导出/批量后导一单真实输出用 ezdxf 核实体类型（应 R2018 + SPLINE/POLYLINE，无 LWPOLYLINE/TEXT/HATCH）。
