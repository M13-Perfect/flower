# CURRENT_TASKS — flower（纯 Python 桌面版）

> 配 `PROJECT_INDEX.md` + `AGENTS.md` 一起读。导出/EzCad 细节看 `docs/superpowers/plans/2026-06-13-dxf-export-progress.md`。
> 更新：2026-06-26（提示词搬进 SQLite 共享库后）。

## 当前状态（2026-06-26）

- **提示词重构已提交（commit `81ab706`）+ 「全局共用一套」已落地**：提示词整套（字段/提取规则/模板/背景提示词）从内嵌 `birth_flower_config.json` 搬进 flower 内独立 SQLite 库 `prompts.db`，所有产品共指同一个 `prompt_set_id`（改一处=全产品生效）。新增 `prompts_db.py`（API：`load_prompt_set`/`list_prompt_sets`/`create_prompt_set`/`replace_prompt_set_fields`/`allocate_field_in_set`/`migrate_product_payload`）；`ProductConfig` 删 6 个内嵌提示词字段、改存 `prompt_set_id`；`load_config` 自动幂等迁移。详见 `AGENTS.md`「本次改动」。
- 分支 `layer-system-v2-rest`（未 merge/push）。
- **待办（提示词侧）**：① **提示词专门编辑页面**（用户要求、未做，当前编辑仍在「字段」卡 + 「提示词套」选择器里）；② **`prompts.db` 分发/导出机制**（库已 gitignore、是运行期产物；门店打包须随包带上 `prompts.db`，目前**无 seed/导出机制**，丢库即丢提示词）。详见下「待办」C 节。

## 测试基线

- 本次提示词重构关键测试（用 `C:/Users/Administrator/AppData/Local/Programs/Python/Python312/python.exe` 或 `.venv-win`）：`tests/test_prompts_db.py`、`test_config_store.py`、`test_reference_field_system.py`、`test_reference_field_ui_mapping.py`、`test_ui_app.py`（`test_ui_app` 较慢 ~3 分钟）。
- flower 全量（绕开缺 ezdxf 的两个模块）：`python -m pytest tests/ -q --ignore=tests/test_document_vector_export.py --ignore=tests/test_dxf_golden_lock.py`。
  - 既有失败（与本次无关）：`test_heart_symbol`×2、`test_layer_baseline`×2、`test_error_recovery_packet7` 导出 smoke = 环境缺 `fontTools`/`ezdxf`。直接跑全仓 `pytest` 会因 `services/api` 缺 `pydantic` 在收集阶段中断。
- 上次基线（2026-06-25 Layer System v2 全部 Packet 后）：`PYTHONPATH=".;services\api" .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q` → **622 passed / 0 failed / 33 skipped**（Windows 上加 `--basetemp .pytest-tmp-run` 避开 Temp 清理权限问题）。`ruff`、`py_compile` clean。

## 最近改动

- **2026-06-26 提示词搬进 flower 内 SQLite 共享库（全局共用一套）+ 修产品增删慢**（commit `81ab706`）：见上「当前状态」+ `AGENTS.md`「本次改动」。**顺带修掉了上一条记的 `_load_field_defs_into_self` 读 `product.reference_fields` 必崩 BUG**——该方法现读 `_active_prompt_set()`，`ProductConfig` 已无 `reference_fields` 字段（旧记录订正见下）。
- **2026-06-25 修末尾爱心：Font 4 双爱心/删层复活 + Font 2 末尾字符爱心映射失效**：
  - **根因（Font 4）**：同一爱心两个真源——文字自贴（`text_renderer._append_ending_heart`，`ending_heart` 驱动）与独立 `AnchoredHeartLayer`——靠每帧 `resolve_anchored_hearts` 写的 `ending_heart_detached` 去重，开关失同步即露馅（BUG①建层后那帧 detached=False → 双爱心；BUG②删独立层从不清 `ending_heart` → 下帧自贴复活，复活的心烘进文字图选不中、再按删误删整段文字）。
  - **落地（最小安全补丁，保留自贴兜底；曾一度全删自贴致 Font 4 偶发无心，已回退）**：① `anchor_resolve.ensure_anchored_heart_for` 建/取爱心层时**立即置 `text.ending_heart_detached=True`**，关掉「建层后~首次 resolve 前」那帧的双爱心窗口（resolve 每帧再幂等确认）；② `ui_app._delete_selected_layer` 新增 `AnchoredHeartLayer` 分支：删独立爱心层即清锚定文字 `ending_heart=False`（不复活、不误删、不导出自烘、重开不被 ensure 补回）。`text_renderer` 自贴爱心**保留为兜底**（`ending_heart=True` 且无独立层时仍贴，保证 Font 4 任何路径都有爱心）。
  - **Font 2 末尾字符爱心映射**：原指向 `E068–E081`，但 **Front2.ttf 只到 ~E04E、没有这些字形** → `apply_automatic_glyph_rules` 报 `missing-codepoint`、`applied=False`、末字不替换。经字体 cmap 轮廓数 + 目视（用户截图确认）：Front2.ttf 的「字母+爱心」花体在 **E034–E04D**（E030–E033 是无心的 w/x/y/z；与 Font 4 同码位），**已彻底根治**到 E034–E04D：① 单一真源常量 `glyph_service.FONT2_DEFAULT_ENDING_GLYPHS`（`0xE068`→`0xE034`，一改即同步 `default_glyph_rules_payload` / `default_glyph_bindings_payload` / `default_glyph_map_payload`）；② 三个 on-disk 文件 `glyph_maps/glyph_rules.json`、`glyph_maps.json`、`glyph_bindings.json` 的 Font 2 段 E068–E081→E034–E04D；③ `ui_app.GLYPH_HELP_TEXT` 帮助文案；④ 相关断言 `test_glyph_application.py` / `test_glyph_service.py` / `test_ui_app.py`（E068/E081/E075→E034/E04D/E041）。`apply` 现 `applied=True`、末字替换为带心花体，重置默认也不再回退。
  - 测试：glyph 全部用例 **33 passed**；自贴兜底已恢复。
- **~~⚠️ 既有 BUG：`_load_field_defs_into_self` 读 `product.reference_fields` 必崩~~ 已在 2026-06-26 提示词重构（commit `81ab706`）中修复**：该方法（现 ui_app.py:4295）已改读 `_active_prompt_set()`，`ProductConfig` 也不再有 `reference_fields` 字段（已搬进 `prompts.db`）。`tests/conftest.py` 新增 `_isolate_prompt_store` fixture 把测试用 config + `prompts.db` 隔离到 tmp，`test_ui_app` 不再因真实 config/db 失败。
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
- **提示词专门编辑页面（用户要求，未做）**：当前提示词编辑仍散在每个产品的「字段」卡 + 「提示词套」选择器（`_render_prompt_set_selector`）里；用户要一个集中的提示词编辑页面。提示词已统一在 `prompts.db`（`prompts_db.py` API 齐全），做页面只需接 UI。
- **`prompts.db` 分发 / 导出机制（待办风险，未做）**：`prompts.db` 是运行期产物、已 gitignore、不入库。首次迁移后 `birth_flower_config.json` 只剩 `prompt_set_id`，**库丢=提示词丢**。门店分发（`package-workbench` 打包）须把 `prompts.db` 一起带上；目前**无 seed/导出机制**，需补「导出一套提示词 / 随包 seed」能力。另：「背景提示词」面板与 `prompt_template` 现写成同一值，待确认是否拆开。
- **图层系统 Layer System v2：全部 Packet 已落地**（Packet 0/1/2/3/4/5/6/7，分支 `layer-system-v2-rest`）。**剩真机手测 + 增量收尾**（详见 `AGENTS.md`「已知问题」）：①非模态栏/添加菜单/缺素材占位/中键平移等需关 App 重开实测；②悬浮栏字距/行距/对齐/颜色/字体已声明未接 write-back（增量）；③Document v2 序列化已可用但无存盘 UI（待接按钮）；④内联编辑 history 未并入新事务 API。验证通过后再决定合回 main。
- **导出朝向「文字在上、花在下」**（2026-06-14 用户 EzCad 实测仍反，合成测试未复现）——待用户给具体导出按钮 + 哪朵花 + 实际文档再定位。
- **订单截图视觉解析** `screenshot_parser.py`（后端已做、UI 未接、未用真图+真 key 验）：准了再给「导入」按钮接识图（小改 `ui_app`），不准就删，零成本。
- ~~修迁移期遗留的 `test_ui_app.py` 失败~~ **已在 Packet 7 完成**：补 `_on_canvas_pan_press`（中键平移）、订正 preview 标尺/缩放/滚轮 without_display 断言、`case_button` 孤儿防御。全量 0 失败。

### D. Electron「新编辑器」（`apps/desktop`）—— 已暂缓
- 半成品，对无头批量量产几乎无加成。仅多人/远程/更强交互编辑器时才值得做。用户当前不用。

## 每次改完务必
- **完全关掉 Tkinter App 重开**再测（旧进程缓存旧代码）。
- 跑测试在仓库根；改了导出/批量后导一单真实输出用 ezdxf 核实体类型（应 R2018 + SPLINE/POLYLINE，无 LWPOLYLINE/TEXT/HATCH）。
