# AGENTS.md — flower（纯 Python 桌面版）

> 新对话先读本文件 + `PROJECT_INDEX.md` + `CURRENT_TASKS.md`。
> 最近一次实质改动：**2026-06-25 Layer System v2 Packet 5：普通组合与自动布局组合**（见下「本次改动」）。未 commit。

## 背景 / 当前生产链路

- 唯一产品线 `birth-flower-card`（生日花卡：一朵花 + 一个名字）。
- 生产工具 = **纯 Python Tkinter 桌面 App**（入口 `birth_flower_mvp.py` → `ui_app.py`）。
  链路：订单备注 → 解析（`parse_pipeline`/`gpt_parser`，AI 可选）→ 人工确认字段 → 实时画板编辑（选层/移动/缩放/换素材）→ 导出 DXF/SVG/PNG。
- **导出权威在 `services/api`**（`app/domain/exports/dxf.py`/`svg.py`/`png.py`），桌面经 `desktop_export.py` in-process 调用；DXF = R2018 + SPLINE/POLYLINE + 单层色7，单次 Y 翻转在 `dxf.py`。所见即所得（预览==导出，`_apply_canvas_fit` 把 contain-fit 烘进导出）。
- 素材：花按 `BirthMonth flowers/` 下 `*.svg` 文件名扫；字体 `Front1-4.ttf`（index 从文件名数字推，全链路用 `"Font N"` 字符串作身份）。**无月份/序号映射**。

## 本次改动（2026-06-25）：Layer System v2 Packet 5 自动布局组合

本轮按 `docs/rfcs/layer-system-v2.md` 的 Packet 5 落地，因任务消息里的 `{{PACKET_NUMBER}}` / `{{PACKET_NAME}}` 未替换，依据用户给的「横向自动布局组合」精确验收场景映射为 Packet 5；未补做 Packet 3/4/6/7。

- `models.py`：新增 `AutoLayoutGroupLayer`、`auto_layout_group_layers()`、`convert_group_to_auto_layout()`、`resolve_auto_layout()`。自动布局为重绘/导出前的幂等 pass，支持 horizontal/vertical、gap、padding、align、justify、hug/fixed；隐藏子层不占位，坏尺寸压到 1px，循环/过深转 warning。普通组创建时也记录子层 union bounds，选框不再落默认 100x100。
- `ui_app.py`：图层 Treeview 改 `selectmode="extended"`；右键菜单新增「组合所选」「自动布局组合所选」「转换为自动布局组合」「解除组合」。预览前先 `resolve_auto_layout()` 再 `resolve_anchored_hearts()`，并改用 `flat_render_layers()` 画叶子层。inline 文本编辑首次实际修改时只压一次 history，Esc 取消会弹掉该快照，保证长文本编辑可一次 Ctrl+Z 回退。
- `desktop_export.py` / `renderer.py`：矢量导出、PNG/SVG 导出前走同一 `resolve_auto_layout()` pass，避免预览与导出布局漂移；未改 `_apply_canvas_fit`、文字排版大脑或导出服务算法。
- 测试：新增 `tests/test_layer_auto_layout.py` 覆盖横向 gap、纵向 padding/align、长文本尺寸变化、隐藏/删除子层、嵌套、解组保持视觉位置、复制、单快照撤销；在既有 `tests/test_canvas_layer_redesign.py` 追加 inline 编辑撤销边界测试。
- 验证：相关测试 `36 passed`；`ruff` clean；`py_compile` clean；限定 `mypy --follow-imports=skip` clean。全量 `pytest tests services/api/tests` = **499 passed / 5 failed / 80 skipped**；5 个失败均是预存在的 `tests/test_ui_app.py` 预览标尺/缩放断言与缺 `_on_canvas_pan_press`，与本轮自动布局无关。

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

- `tests/test_ui_app.py` 当前 5 个失败均**预存在、与本轮无关**：preview 标尺/缩放 `without_display` 数值断言，以及测试期望 `_on_canvas_pan_press`（当前只有 `_on_canvas_press`）。需单独修迁移期预览交互测试/实现。
- `case_button` 迁移期死引用仍未专项处理；本轮全量测试未命中，但 `CURRENT_TASKS.md` 仍保留待办。
- 真机手测仍待做：Tkinter 改动无法纯自动化，改完务必**完全关掉 App 重开**再测。
- `birth_flower_config.json` 历史上有明文 OpenAI key 误填风险；若仍在，建议改环境变量并轮换。

## 怎么跑 / 怎么测

- 跑 App：`.\.venv-win\Scripts\python.exe birth_flower_mvp.py`（`.venv-win` = CPython 3.12 全依赖；缺 numpy 时其它解释器会自动 re-exec 到它）。
- 跑测试（**CWD = 仓库根**）：`PYTHONPATH=".;services\api" .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q`
  - 当前 Windows Temp 权限偶发阻断 pytest 清理时，可临时加：`--basetemp .pytest-tmp-run -o cache_dir=.pytest-cache-run`，跑完删除这两个目录。
- lint：`.\.venv-win\Scripts\python.exe -m ruff check <file>`
- 致命坑：改完 Python 必须完全关掉 App 重开（旧进程缓存旧模块）；pytest 必须在仓库根跑（部分测试用相对路径）。
