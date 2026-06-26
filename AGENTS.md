# AGENTS.md — flower（纯 Python 桌面版）

> 新对话先读本文件 + `PROJECT_INDEX.md` + `CURRENT_TASKS.md`。
> 最近一次实质改动：**2026-06-26 提示词整套搬进 flower 内 SQLite 共享库 `prompts.db`（全局共用一套）+ 修产品增删慢**（commit `81ab706`，见下「本次改动」）。
> 分支 `layer-system-v2-rest`，逐次提交。**未 merge 回 main、未 push。** Layer System v2 RFC 全文见 `docs/rfcs/layer-system-v2.md`。

## 背景 / 当前生产链路

- 唯一产品线 `birth-flower-card`（生日花卡：一朵花 + 一个名字）。
- 生产工具 = **纯 Python Tkinter 桌面 App**（入口 `birth_flower_mvp.py` → `ui_app.py`）。
  链路：订单备注 → 解析（`parse_pipeline`/`gpt_parser`，AI 可选）→ 人工确认字段 → 实时画板编辑（选层/移动/缩放/换素材）→ 导出 DXF/SVG/PNG。
- **导出权威在 `services/api`**（`app/domain/exports/dxf.py`/`svg.py`/`png.py`），桌面经 `desktop_export.py` in-process 调用；DXF = R2018 + SPLINE/POLYLINE + 单层色7，单次 Y 翻转在 `dxf.py`。所见即所得（预览==导出，`_apply_canvas_fit` 把 contain-fit 烘进导出）。
- 素材：花按 `BirthMonth flowers/` 下 `*.svg` 文件名扫；字体 `Front1-4.ttf`（index 从文件名数字推，全链路用 `"Font N"` 字符串作身份）。**无月份/序号映射**。
- **提示词（字段/提取规则/模板/背景提示词）现存在 flower 内独立 SQLite 库 `prompts.db`**（与 `birth_flower_config.json` 同目录），**全局共用一套**：所有产品共指同一个 `prompt_set_id`，改一处=全产品生效。产品配置里**只剩 `prompt_set_id` 引用**，不再内嵌提示词。详见下「本次改动」。
- **易混点（防走偏）**：① `automation/` 下的 **inbox-service**（仓库外）有自己的 SQLite，那是**订单状态机**，与提示词库无关；② `flower/services/api` 是**已暂缓的 web API**，与本次提示词重构无关。本次只动 flower 自身（桌面侧）。`prompts.db` ≠ inbox-service 的库，别混。

## 本次改动（2026-06-26，commit 81ab706）：提示词搬进 SQLite 共享库（全局共用一套）+ 修产品增删慢

把整套提示词从内嵌进 `birth_flower_config.json`（按产品各一份）搬进 flower 内独立 SQLite 库 `prompts.db`，并改成**所有产品共用同一套全局提示词**；顺带修产品新建/删除慢。

- **新增 `prompts_db.py`**（共享提示词库，SQLite）。对外 API：`load_prompt_set` / `list_prompt_sets` / `create_prompt_set` / `replace_prompt_set_fields` / `allocate_field_in_set` / `migrate_product_payload`。模型 = `PromptSet`（含 `reference_fields` / `field_seq_max` / `prompt_template` / `background_prompt` 等）。db 路径默认 = 主配置文件同目录的 `prompts.db`（`config_store.DEFAULT_CONFIG_PATH` 父目录）。`allocate_field_in_set` 用 `BEGIN IMMEDIATE` + 进程内锁**原子分配字段序号**。
- **`config_store.py`**：`ProductConfig` **删 6 个内嵌提示词字段**（`extraction_prompt` / `background_prompt` / `reference_fields` / `field_seq_max` / `prompt_template` / `template_version`），**新增 `prompt_set_id`**。`_migrate_prompt_sets` 改为「所有产品共用同一套全局提示词」（基线 = 当前激活产品那套；其余产品改指同一套）；`load_config` 时自动迁移并 `save` 一次，**幂等**（再次加载因已带 `prompt_set_id` 而跳过）。`with_product_reference_fields` / `with_product_prompts` / `create_product_reference_field_in_file` 转发到 `prompts_db` 按 `set_id` 操作（旧 `field_seq_max`/`template` 参数保留只为兼容签名）。
- **`ui_app.py`**：新增 `_active_prompt_set()` / `_active_reference_fields()` 从 db 取；`_persist_prompts` / `_add_field` / 字段增删改写 db；解析链路 `_current_ai_config` 用 `set.reference_fields`（`scope_id` 传 `set_id`）喂 `resolve_prompt_template`（下游 `gpt_parser`/`parse_pipeline` **未动**）；`_create_product_from_dialog` 新建产品直接带全局 `prompt_set_id`；新增「提示词套」选择器 `_render_prompt_set_selector`。**修复了 CURRENT_TASKS 上一条记的 `_load_field_defs_into_self` 读 `product.reference_fields` 必崩的 BUG**——现该方法（ui_app.py:4295）改读 `_active_prompt_set()`，`ProductConfig` 已无 `reference_fields` 字段。
- **性能（`asset_resolver.py` / `material_library.py` / `ui_app.py`）**：去掉资产主目录被扫两遍、合并重绘（`_suppress_redraw` + `_scan_assets` 加 `redraw` 参数）、库扫描按目录签名缓存、合并产品新建/删除的双 `save_config`、删除非激活产品不再触发全量重扫。
- **`tests/conftest.py`**：新增 autouse fixture `_isolate_prompt_store`，把测试用 config + `prompts.db` 重定向到临时目录（只作用于测试、`monkeypatch` 自动还原；生产用真实路径，不受影响）。
- 新增文件：`prompts_db.py`、`tests/test_prompts_db.py`（15 用例）。改：`config_store.py`、`ui_app.py`、`asset_resolver.py`、`material_library.py`、`tests/conftest.py` + 既有测试（`test_config_store` / `test_reference_field_system` / `test_reference_field_ui_mapping` / `test_ui_app`）。`.gitignore` 加 `prompts.db`（运行期产物，不入库）。

## 上次改动（2026-06-25）：Layer System v2 完成剩余全部 Packet

按 `docs/rfcs/layer-system-v2.md` 落地 Packet 0/1/2/3/4/6/7（Packet 5 由 codex 先行，见「上次改动」）。逐 Packet 子代理实现 + 逐 Packet 提交，每包跑 ruff/py_compile + 全量回归零退化。**核心红线全程守住：导出字节稳定（Packet 0 门禁）、桌面单一布局来源、未替换画布/渲染器/文字排版大脑/anchor。**

- **Packet 0**（`tests/test_layer_baseline.py` + golden）：内存构造生产形态 Document，连导两次 DXF/矢量 SVG 规整元数据（ezdxf GUID、`@ISO` 戳、`$TD*` 儒略日时间戳）后逐字节一致 + 导出 dict 结构金标。作为后续所有 Packet 的字节门禁。
- **Packet 1**（修 P1/P2，`models.py`/`ui_app.py`）：`HistoryManager` 加 `begin/commit/rollback_transaction`（幂等，cap 50）；新增**非模态属性栏 overlay**（`_open_inspector_overlay`，`CTkFrame` 不 `grab_set`/不 `wait_window`），绑现有共享 var，var trace→实时重绘，进入编辑 begin、失焦/回车/松手 commit、Esc rollback，位置夹紧视口；`_open_layer_geometry_dialog`/`_open_heart_anchor_dialog` 去 `grab_set`。flag `INSPECTOR_OVERLAY`（env=0 回退旧对话框）。
- **Packet 2**（修 P3，`ui_app.py`/`desktop_export.py`）：两个添加按钮合并为单一「+ 添加图层」→ 原生 `tk.Menu`（文字/图片素材/空白内容层/普通组合/自动布局组合，组合两项复用 codex Packet 5 处理器、<2 选中置灰）；空白内容层 = 未绑 `ImageLayer`，非零占位 + 虚线占位渲染；`_image_layer` 对从未绑过的空白层导出跳过+warning（不再崩）。
- **Packet 3**（ADR-001，新增 `providers.py`）：薄 `ContentProvider` + 模块级 `PROVIDERS` 注册表 + `get_provider`；`TextProvider`/`ImageProvider` 的 `render_export`/`render_preview` **委托既有函数**（算法零改动）；`models.Layer` 加 `provider_id`（不进导出 dict）；`_document_to_layer_document`/`_redraw_preview` 改查表分发；AnchoredHeart 保留专用路径。其余 §7 方法留 stub。
- **Packet 4**（§8/§15/§16，`models.py`/`providers.py`/`desktop_export.py`/`ui_app.py`）：**修复资源缺失崩溃**——已绑但磁盘缺失的素材导出跳过+warning、预览画「素材缺失」红框；`Document.schema_version` + `serialize`/`deserialize_document`（provider seam + `dataclasses.fields` 通用编解码、组递归）；`migrate_v1_to_v2`（复用 `__post_init__`）；未知 provider_id/构造失败 → `UnknownLayer` 持原始 dict 无损保留；最小 `ResourceRef`（未重构现有 font/material 字段）；flag `DOC_SCHEMA_V2`。
- **Packet 6**（§9/§10/§14，新增 `tools.py`）：`SelectTool`/`TextTool` 委托既有 `_on_canvas_*`/内联编辑（thin-registry，画布绑定不变，零回归）；provider 声明 `inspector_sections`/`capabilities`，悬浮栏改 `_inspector_rows_from_provider` 数据驱动；`TextLayer` 加 `layout_mode="box"`（= 当前行为不分支）+ `runs=None`（声明不填）。
- **Packet 7**（§16/§17，`providers.py`/`ui_app.py`）：填 `ContentProvider.validate`（有限正数尺寸 / 字号 / 缺素材）+ Inspector 写回 `math.isfinite` 拒绝 NaN/inf/负值；新增 `_on_canvas_pan_press`（中键平移）+ 绑定；**修复全部 7 个迁移期基线失败**（3 个真实缺口改实现：中键平移×2、`case_button` 孤儿；4 个陈旧期望订正：标尺 `target_px` 72→40、缩放步进 0.25→0.05、滚轮改纯缩放，均带注释）。

- 新增文件：`providers.py`、`tools.py`、`tests/test_{layer_baseline,inspector_packet1,add_layer_menu_packet2,providers_packet3,doc_serialize_packet4,tools_inspector_packet6,error_recovery_packet7}.py` + `tests/fixtures/layer_baseline_doc.json`。
- 验证：`ruff`/`py_compile` 全绿；全量 `pytest tests services/api/tests` = **622 passed / 0 failed / 33 skipped**（基线 547→599→622，**0 回归**，迁移期 7 失败全清）。

## 上次改动（2026-06-25，codex）：Layer System v2 Packet 5 自动布局组合

- `models.py`：新增 `AutoLayoutGroupLayer`、`auto_layout_group_layers()`、`convert_group_to_auto_layout()`、`resolve_auto_layout()`。自动布局为重绘/导出前的幂等 pass，支持 horizontal/vertical、gap、padding、align、justify、hug/fixed；隐藏子层不占位，坏尺寸压到 1px，循环/过深转 warning。普通组创建时也记录子层 union bounds。
- `ui_app.py`：图层 Treeview 改 `selectmode="extended"`；右键菜单新增「组合所选」「自动布局组合所选」「转换为自动布局组合」「解除组合」。预览前先 `resolve_auto_layout()` 再 `resolve_anchored_hearts()`，改用 `flat_render_layers()` 画叶子层。inline 文本编辑首次实改只压一次 history，Esc 取消弹掉该快照。
- `desktop_export.py` / `renderer.py`：矢量/PNG/SVG 导出前走同一 `resolve_auto_layout()` pass；未改 `_apply_canvas_fit`、文字排版大脑或导出服务算法。
- 测试：`tests/test_layer_auto_layout.py` + `tests/test_canvas_layer_redesign.py` inline 撤销边界。

## 上次改动（2026-06-25）：移除全部 GIMP 残留

本副本是「纯净 Python 桌面版」。GIMP-VB 实验轨道的模块（`gimp_editor/`、`gimp_bridge/`、`preview_render.py` 等）此前迁移时已删，仅剩死代码/配置/文档残留。本轮全部清掉：

- `ui_app.py`：删后端切换辅助（`_gimp_editor_enabled`/`_production_editor_backend`/`_legacy_editor_is_production_default`）→ 旧 Tkinter 画板成**唯一**生产编辑器（预览卡恒「实时画板」、画布尺寸编辑恢复可用）；删订单卡「在 GIMP 中编辑」整组 + 全部 `_*gimp*` 方法 + `_current_order_for_gimp` + `_order_seed_content_fields`；删产品右键的模板项（编辑/编译/配置内容/生成预览/发布/查看版本）+ 对应 `_product_*` 方法 + `_templates_dir`/`_create_template_draft`；「新建产品」对话框删模板来源（空白/复制/导入 XCF）。**保留产品 CRUD**（新建/启用/停用/删除）。
- `config_store.py`：删 `gimp_template_id` 字段 + `effective_template_id` 属性 + 序列化两处 + 死代码 `with_product_template`（旧配置含该键时加载侧自动忽略，向后兼容）。
- 删 `docs/gimp/`、`docs/adr/flower-image-engine-integration.md`、`docs/licenses/flower-editor-gpl-compliance.md`；`.gitignore` 去 GIMP 行；`dxf.py` 注释去 GIMP 字样。
- 测试：删 `tests/test_order_seed_fields.py`；改 `tests/test_product_registry_config.py`（去 GIMP 字段断言，留 status 迁移 + 未知键忽略）。
- 验证：`py_compile` + `ruff` clean；全量 `pytest tests services/api/tests` = **534 passed / 9 failed / 33 skipped**，9 个失败全是预存在的无头 Tkinter / 未实现功能缺口（见「已知问题」），**0 个由本次移除引入**（已逐条核对失败原因均与 GIMP/本次改动无关）。

## 目标 / 需求

- 保持纯 Python 桌面生产链稳定：解析 → 确认 → 画板编辑 → DXF/SVG/PNG 导出，预览==导出。
- EzCad 端闭环（导入 DXF + 填充/变黑宏）在**独立的 Ezcad 自动导入项目**做，非本仓库。详见 `CURRENT_TASKS.md`。

## 已知问题 / 未解决（诚实）

### 提示词搬进 SQLite 库（本次，commit 81ab706）的遗留风险

- **`prompts.db` 定为「运行期产物」、已加进 `.gitignore`、不做版本管理**。首次迁移后 `birth_flower_config.json` 不再含提示词（只剩 `prompt_set_id`）。**因此 `prompts.db` 一旦丢失或未随包发布，提示词即丢失。** 门店分发（`package-workbench` 打包）**必须把 `prompts.db` 一起带上**；目前**尚无导出/seed 机制**——这是待办风险。
- **「提示词专门编辑页面」是用户要求的后续工作，未做**。当前编辑仍在每个产品的「字段」卡 + 「提示词套」选择器（`_render_prompt_set_selector`）里。
- **「背景提示词」面板与 `prompt_template` 现写成同一值**（原 `background_prompt` 在解析链路本就恒空）；需后续确认是否要拆开。
- **`birth_flower_config.json` 被 gitignore、不在 git 历史**；首次用新版在真实 config 上跑前**建议先手工备份它**（迁移会就地改写它）。

### Layer System v2 / 其他遗留

- **真机 Tkinter 手测全部待做**（无头测不到，逐 Packet 的子代理报告里有详细清单）。关键项：①非模态属性栏开时画布仍可拖/缩/选其他层、改值实时重绘、连续改值一次 Ctrl+Z 复原、Esc 回滚；②「+添加图层」菜单五项 + 空白内容层占位 + 可后绑素材；③缺素材时画红色「素材缺失」占位框且导出不崩；④中键平移（`_on_canvas_pan_press`）；⑤改完务必**完全关掉 App 重开**再测（旧进程缓存旧模块）。
- **Inspector 悬浮栏目前只渲染 x/y/w/h/font_size**（= 旧「位置/尺寸」对话框字段集，手感一致）。字距/行距/对齐/颜色/字体已由 `TextProvider.inspector_sections` **声明**，但悬浮栏 write-back 白名单未接这些 key，故暂不在栏内显示（仍走右键 picker/内联编辑）。Packet 6 边界——给 `_write_inspector_vars_to_layer` 接新 key + 加进白名单即可显示，无需改 overlay 渲染循环（§14 扩展点已就绪）。
- **内联文字编辑仍走 codex Packet 5 的即兴 history 机制**（`inline_text_history_pushed` + 弹快照），未并入 Packet 1 的 `HistoryManager` 事务 API；两者不同入口、互不冲突。若要统一，把 `_start/_commit/_cancel_inline_text_edit` 改调 `begin/commit/rollback_transaction`。
- **AnchoredHeart 仍走专用导出/预览路径**，未 provider 化（设计如此，§20 保留）。
- **Document v2 序列化是新增能力但尚无「打开/保存文档」UI**（每次启动仍空白画布）。`serialize`/`deserialize_document` 已可用且有 round-trip 测试，待后续接存盘按钮（`DOC_SCHEMA_V2` flag 默认 ON）。
- **分支未 merge/push**：`layer-system-v2-rest`，逐 Packet 提交，待真机验证后再决定合回 main。基线 snapshot 提交把迁移期既有未提交工作（含 codex Packet 5）一并固化。
- `birth_flower_config.json` 历史上有明文 OpenAI key 误填风险；若仍在，建议改环境变量并轮换。

## 怎么跑 / 怎么测

- Python 解释器（本机）：`C:/Users/Administrator/AppData/Local/Programs/Python/Python312/python.exe`。或用 `.venv-win`（= CPython 3.12 全依赖；缺 numpy 时其它解释器会自动 re-exec 到它）。
- 跑 App：`.\.venv-win\Scripts\python.exe birth_flower_mvp.py`。
- 跑测试（**CWD = 仓库根**）：`PYTHONPATH=".;services\api" .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q`
  - 当前 Windows Temp 权限偶发阻断 pytest 清理时，可临时加：`--basetemp .pytest-tmp-run -o cache_dir=.pytest-cache-run`，跑完删除这两个目录。
- **本次提示词重构的关键测试**：`tests/test_prompts_db.py`、`tests/test_config_store.py`、`tests/test_reference_field_system.py`、`tests/test_reference_field_ui_mapping.py`、`tests/test_ui_app.py`（`test_ui_app` 较慢 ~3 分钟）。
- **flower 全量（绕开缺 ezdxf 的两个模块）**：`python -m pytest tests/ -q --ignore=tests/test_document_vector_export.py --ignore=tests/test_dxf_golden_lock.py`。
  - 既有失败（与本次无关）：`test_heart_symbol`×2、`test_layer_baseline`×2、`test_error_recovery_packet7` 的导出 smoke = 环境缺 `fontTools`/`ezdxf`；**直接跑全仓 `pytest` 会因 `services/api` 缺 `pydantic` 在收集阶段中断**。
- lint：`.\.venv-win\Scripts\python.exe -m ruff check <file>`。
- 致命坑：改完 Python 必须完全关掉 App 重开（旧进程缓存旧模块）；pytest 必须在仓库根跑（部分测试用相对路径）；首次在真实 config 跑前先备份 `birth_flower_config.json`（迁移就地改写）。
