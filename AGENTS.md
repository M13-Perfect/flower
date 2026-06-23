# AGENTS.md

> **2026-06-23 · 画布/图层/素材库改版 ✅核心实现+自动化测试 / ⬜真机 GUI 回归**  
> **背景**：生产现实仍是 Tkinter/CustomTkinter 桌面端（`ui_app.py` + `birth_flower_mvp.py`），不是 Web 改版；Document 不落盘，每单重建，跨单几何只能落产品级配置。  
> **本次改动**：按 `docs/superpowers/plans/2026-06-23-canvas-layer-library-redesign.md` 落地：`ProductConfig.defaults` 启动/切产品生效，布局设置保存写当前产品（产品0 同步旧 `layout_defaults`）；新增 `LayerPin` + `ProductConfig.layer_pins` + `with_product_layer_pins`，pin key 为 `image:{library_id}:{material_key}` / `path:{filename}` / `text:0`，快照用 `ProductionParams(x/y/width/height/rotation/font_size)`，插入 `_layer_effective_production` 的统一 resolve 链；`AnchoredHeartLayer` 不可独立 pin。图层卡改 `ttk.Treeview`（可见/📌/类型/删除列、右键、Delete、拖动排序），删除统一走 `_delete_selected_layer`，带二次确认、拒删 `layer.locked`、删文字时清锚定爱心并修正悬空选中。画布顶栏加实时尺寸；图层区下方复用真实 `image_library_dirs` / `font_library_dirs` 渲染资源库和添加入口；`HistoryManager` 补 `push/undo/redo/clear`，画布编辑动作压 Document 快照，配置/锁定/加库/切产品/换单清栈不入栈；文本输入焦点优先走控件自身撤销。  
> **测试/验证**：新增 `tests/test_canvas_layer_redesign.py`（10 passed）覆盖 pin 序列化/非法过滤/旧 defaults 迁移/产品隔离/HistoryManager/pin key/resolve 优先级/锁定持久化/Treeview 行状态/删文字清爱心/尺寸文本+焦点路由。`ruff check config_store.py models.py ui_app.py tests/test_canvas_layer_redesign.py` 通过；`py_compile` 通过；`pytest tests/test_canvas_layer_redesign.py tests/test_config_store.py tests/test_layer_material_fields.py tests/test_anchored_heart.py tests/test_text_wysiwyg_consistency.py -q` = 55 passed；完整 `pytest tests services/api/tests -q` = 522 passed / 54 skipped / 5 failed，5 个仍是修改前已存在的 preview zoom/pan/ruler headless drift。  
> **真机待验**：须完全关 App 重开后验证 Treeview 点击列命中（👁/📌/🗑）、拖动排序、Delete/右键删除确认、锁定层禁删提示、Ctrl+Z/Y 撤删除/移动/缩放/排序、备注/文件名输入框 Ctrl+Z 不误伤画布、切产品几何重载、锁花/贴纸含 rotation 后换单命中、添加空/重复/有效素材库和字体库即时刷新、实际导出 DXF/SVG/PNG rotation 与预览一致。  
> **已知/取舍**：同一产品内同一素材共享一条 pin（与设计 A8 一致，本轮不做同素材多实例各锁不同位置）；pin 存绝对 px，画布尺寸变更后必要时需重锁；`layers_rows_box` 旧 CTk 行实现仍保留为未挂载 fallback，真实 UI 走 `layers_tree`。

> **2026-06-23 · 设计文档 v2（未开工）：画布/图层/素材库改版 → `docs/superpowers/plans/2026-06-23-canvas-layer-library-redesign.md`**。Tkinter 桌面端，6 需求已定稿：①图层「锁定初始位置」=**逐图层、按素材身份**（`image:{library_id}:{material_key}`/`text:{slot}`）存 `ProductConfig.layer_pins`，**含旋转**，多图层各锁各的，经 `resolve_chain` 解析；②画布顶栏缩放同行加实时尺寸；③图层列表上 PS 风 `ttk.Treeview`（逐行 可见/📌锁/🗑删，补爱心清理+二次确认）；④图层区下方复用现有库系统挂资源库区（库名=文件夹名）；⑤接 `HistoryManager` 做 Ctrl+Z 撤销（A 画布编辑+B 输入框，配置/换单不进栈）；⑥切产品/启动**重载产品级几何**（激活休眠 `ProductConfig.defaults`+`with_product_defaults`），修「切产品复用旧参数」。**纠偏：无"全局锁定"功能（只有 `layer.locked`=禁拖/删）；Document 不落盘；rotation 全链路真用。** 任务清单 11 步、零回归红线见 §13/§14。**产品 CRUD（删除/重命名/字段级联/多产品验证）=另起会话**。代码未动。

> **2026-06-23 · 设计文档（未开工）：可引用字段系统 → `docs/superpowers/plans/2026-06-23-reference-field-system.md`**。把管理员端 info1/2/3 + 背景提示词升级为「稳定 ID + 不可变序号 + `/` 引用原位展开 + 双视图预览」。仅设计稿，§19 有 3 项待用户拍板（多模板/订单内联/字段类型可引用），代码未动。

> **2026-06-23 · Tk 桌面三列布局改可拖拽（PanedWindow）+ 列宽记忆 ✅逻辑+单测 / ⬜真机拖拽手测（新对话先读）**
> **背景/需求**：`ui_app.py` 主界面是横向三列——产品列(左) | 预览/订单画板(中) | 功能区(右)。旧布局=`product_rail.pack(side=left,固定宽)` + 一个 `body` 用 grid 两列（col0 画板 weight=1 minsize360、col1 功能区 weight=0 minsize300），三块边界都拖不动；产品列只能靠「收/展」按钮变宽。用户要：每列边框可拖拽拉宽缩窄、内容自动适应、列宽下次开还原。已与用户敲定：① 三层=横向三列；② 自适应只要「重排撑满」不缩字号；③ 收/展按钮与拖拽并存；④ 列宽要持久化。
> **本次改动（仅 `config_store.py` + `ui_app.py` + 新测试，未碰生产/解析/导出链）**：① 核心=把 `_build_layout` 里 `pack(左列)+grid(两列body)` 换成单个 `tk.PanedWindow(orient=horizontal)`，`add` 三个 pane（产品列 minsize=48 stretch=never / 中心容器 minsize=360 stretch=always / 功能区 minsize=300 stretch=never，都 sticky=nsew）——sash 自带拖拽，不写鼠标逻辑。**坑**：`CTkScrollableFrame`（功能区）是 frame→canvas→scrollableframe 复合体，其真身不是 paned 直接子节点，`paned.add(它)` 会抛 `can't add ...!ctkscrollableframe to ...!panedwindow` 启动崩溃；必须包一层普通 `ttk.Frame` 当 pane、功能区 pack 满它再 add（产品列=普通 CTkFrame、中列=ttk.Frame 可直接 add）。选 tk 版而非 ttk：每 pane 的 minsize 原生（ttk 只有 weight 得自己钳）。sash 压深色扁平（`bg=border, sashwidth=6, sashrelief=flat, bd=0, showhandle=False`）。② 中列新建 `center` 容器，预览/订单两块搬进去 grid 在同格、`grid_remove` 切换逻辑照搬（`_apply_center_for_view` 未改）。③ `_toggle_product_rail` 删掉旧的「整窗加宽 delta」逻辑，改成翻状态→存盘→`_render_product_rail`→`paned.sash_place(0,目标宽,0)` 吸附左 sash（中列吸收差值，与拖拽一致）。④ 列宽记忆：`config_store.AppConfig` 加 `pane_sash_fractions: tuple[float,...]`（存**占总宽比例**不是像素，换窗口大小/分辨率不串位）+ `_fractions_value` 解析(越界/非数→回落空)+load/save；`ui_app` 加 `_restore_pane_sashes`（`after_idle`，`total<=1` 未实化时 `after(50)` 重试一次再放弃）/ `_save_pane_sashes`（关窗在 `_on_app_close` 开头按比例存）。模块级纯函数 `_clamp_sashes(fractions,total,...)` 还原时钳三列 minsize + 保证 x0<x1。
> **怎么测**：用 `.venv-win` 跑。`pytest tests/test_pane_sash_clamp.py`=2 passed（越界比例仍守 minsize/顺序、合理比例原样保留）；config 存读往返 + 旧配置无字段回落 () 已验；`tk.PanedWindow` 的 `add(stretch/sticky/minsize)`+`sash_place/sash_coord` 本机 Tk 接受已验（无 mainloop 时 winfo_width 返回 1，正是 `_restore_pane_sashes` 的重试守卫场景）。
> **⬜ 真机待手测（须重开 App，无法 headless 验）**：① 拖两条 sash → 三列都能拉宽缩窄、内容跟着重排、画布缩放（画布 `<Configure>→_redraw_preview` 已有）；② 收/展按钮仍把左列吸附到 48/168 且之后还能拖；③ 拖好关 App 重开 → 列宽还原；④ sash 深色扁平观感是否要再调。
> **已知/取舍**：字号不随窗口缩放（按用户选择，只重排）；功能区里写死的 `wraplength`(290/460…) 不会随列变宽重新换行（小事，要再说）；旧的「收/展时整窗加宽不吃画板」行为被去掉，改由中列自然吸收（更简单、与拖拽一致）。

> **2026-06-23 · 可引用字段系统 Reference Field System ✅核心逻辑+配置/解析测试 / ⬜真机 UI**
> **背景/需求**：按 `docs/superpowers/plans/2026-06-23-reference-field-system.md` 落地 Tkinter 生产链路，不再让管理员字段依赖 `info1/info2/info3` 位置硬编码。当前实现仍以本地产品配置 JSON 为字段/模板权威存储，未把字段系统塞进 `automation/inbox-service` 订单 SQLite。
> **本次改动**：新增 `prompt_references.py`，统一管理 `ReferenceField`、固定序号、重复名校验、软删除冲突、`{{field:<uuid>}}` / `{{source:order_information}}` token 解析、模板友好视图和最终提示词解析。`config_store.py` 扩展 `ProductConfig.reference_fields/field_seq_max/prompt_template/template_version`，保留旧 `extraction_prompt/background_prompt` 并在加载旧 JSON 时兼容迁移；`save_config` 改为锁内临时文件原子替换。`ui_app.py` 字段卡显示不可修改 `#序号` + 可编辑名称 + 提示内容框 + 更多菜单(启用/停用/删除)，背景提示词框支持 `/` 候选并插入稳定 token；预览和真实解析都走同一 resolver，无效引用会阻止模型调用。`models.py`/`parse_pipeline.py`/`gpt_parser.py` 增加 `user_content` override 与 `reference_snapshot` trace，支持 `/订单信息` 被注入 system prompt 时不再重复塞 user 内容。
> **关键语义**：固定序号按 product scope 内 `field_seq_max + 1` 分配，删除后不重排、不复用；名称按 trim + casefold 去重，名称修改不影响已有 token；字段删除若当前模板仍引用会被阻止并返回引用数量；停用/删除/不存在/跨 scope/畸形 token 都会让 resolver 抛结构化错误并禁止模型调用；`/订单信息` 展开为 `<order_data>` 边界文本并做最大长度限制。
> **测试/验证**：新增 `tests/test_reference_field_system.py` 覆盖序号、并发文件级创建、旧数据迁移、重复名、跨 scope、停用/删除、不存在、畸形 token、重复引用、系统数据源和删除冲突；更新 `tests/test_orders_multi.py`/`tests/test_ui_app.py` 适配新解析链。验证命令：`py_compile` 通过；`ruff check prompt_references.py config_store.py models.py gpt_parser.py parse_pipeline.py ui_app.py tests/test_reference_field_system.py tests/test_orders_multi.py tests/test_ui_app.py` 通过；`pytest tests/test_config_store.py tests/test_reference_field_system.py tests/test_orders_multi.py tests/test_inbox_poller.py` = 62 passed；`pytest tests services/api/tests` = 510 passed / 54 skipped / 5 failed（5 个仍是既有 preview zoom/pan/ruler headless drift，非本轮字段系统）；`npm run lint --workspace @flower/desktop` 通过；`npm run build --workspace @flower/desktop` 通过且仅 Fabric bundle >500KB warning。
> **已知/后续**：当前 Tk 编辑器仍是 `CTkTextbox`，编辑框底层显示稳定 token，友好 `/名称` 主要在模板预览里渲染；若要做到编辑区内真正 chip 化，需要后续基于 Tk Text tag/浮层继续增强。当前环境无 Tk display，相关 UI 测试 skip，须真机重开 App 验证：字段名称 Enter 保存/Esc 取消、更多菜单停用/删除、`/` 候选键盘和鼠标选择、模板/最终预览、无效引用阻止解析。

> **2026-06-23 · `apps/desktop` 改成贴近 `ui_app.py` 的深色 Web 前端原型 ✅构建+浏览器验证 / ⬜后端实接**
> **背景/需求**：用户明确要求读取 `ui_app.py`，做一个样式一致、便于后续调整修改的网页版前端。当前生产现实仍是 Tkinter 桌面 App（`ui_app.py` + `birth_flower_mvp.py`），本次不是替代生产链路，而是把其界面信息架构迁到现有 React/Vite 渲染器，作为可调 Web 原型。
> **本次改动**：只改 `apps/desktop/src/renderer/App.tsx` 与 `apps/desktop/src/renderer/styles.css`。复用现有 `@flower/desktop`、`@flower/design-core`、`FabricCanvas` 和 Fabric 画布模型；将旧浅色三栏编辑器换成：① 启动“选择工作台”门厅（操作员端 hero + 配置端/管理员端小卡 + 状态 chips）；② 左侧可收起产品列；③ 中心区按端切换（操作员/管理员=实时画板，配置端=实时订单表）；④ 右侧功能区按 `ui_app.py` 的 `_VIEW_CARD_ORDER` 对齐：操作员=订单信息/解析结果/图层/输出设置，配置端=抓取订单/字体库素材库，管理员=订单信息/解析结果/图层/字段/背景提示词/本次提示词/输出设置；⑤ 深色 token 对齐 `APP_COLORS`/`ENTRY_COLORS`（`#1b1b1b`、`#242424`、`#2b2b2b`、`#3a7afe` 等）。
> **实现取舍**：这是前端可调原型，解析按钮先走本地预览解析（已修 `Name:` 正则只吃同一行，避免吞下一行 `Flower`），订单表用示例数据，抓取/库导入/生成按钮保留 UI 与本地状态反馈；真实 inbox-service、AI 解析、导出保存、店小秘打标尚未接入。Fabric 画布保留可选中/拖动图层，示例文档采用 1732×1280 白底画板、Rose SVG 和 Avery 文本层，方便调样式与布局。
> **怎么跑 / 怎么测**：`npm run dev --workspace @flower/desktop` 打开 `http://127.0.0.1:5173/`；构建/类型检查：`npm run lint --workspace @flower/desktop`、`npm run build --workspace @flower/desktop`。本次两条命令均通过；build 仅有既有 Fabric 相关 bundle >500KB warning。浏览器验证：门厅存在且无 console error/warn；点“操作员端”进入后遮罩关闭；点“解析”后解析结果/文件名/状态更新；切“操作员配置端”中心区变订单表且画布卸载；切“管理员端”显示 7 张卡和 IP badge；390×844 移动视口无横向溢出。
> **已知/后续**：若要从原型走向真实 Web 生产链路，下一步不是继续堆样式，而是把 `ui_app.py` 当前真实能力逐项接 API：库驱动载单、字段规则持久化、真实 parse/apply/export、inbox-service 订单表、输出保存与标记回写；同时需处理 Web 分支旧风险：SVG/PNG 不应长期只走前端 TS 渲染绕开 Python WYSIWYG。

> **2026-06-22 · 一单多件：文件名加「-k」后缀防覆盖（逐件手动生成）✅逻辑+测试 / ⬜真机（新对话先读）**
> **背景/需求**：`confirm_and_generate` 对一单的所有件用**同一文件名主干**（订单号），一单多件（共订单号，如截图「第 2/4 单·订单号 4094810918」）逐件点「生成」会**互相覆盖**。用户敲定：件数取**数据库 items[]**、文件名落盘用 `订单号-2`（Windows 不能含「/」，「2/4」只做界面显示）、**逐件手动生成**（沿用「上一笔/下一笔」，每件各出一个后缀文件）。
> **改动（全在 `ui_app.py` + 测试，最小增量，未碰 DB/契约/order_importer/inbox_service_client）**：① 新增纯函数 `target_box_piece_count(order)`=各 `is_target_box=True` 行 `quantity` 之和（每行至少 1，其他商品不计；items 缺失→0）。② `__init__` 加 `self._db_order_piece_count=0`；`_load_db_order` 载单时 `= target_box_piece_count(order)` 并在写完订单号后调 `_update_piece_filename()`。③ 新增 `_piece_index_total()`→(k,n)：n 优先取库件数（`db_trusted`=当前单号==库载入单号，或逐件解析把 order_number 留空时按库单号兜底）、回退解析队列长度；k=`_parsed_order_index+1`。`_with_piece_suffix(base)`：n>1 才返 `base-k`。`_update_piece_filename()`：把文件名框刷成 `订单号-k`，**仅当框还是自动值**（`re.fullmatch(rf"{base}(-\d+)?")`）才覆盖，操作员手改的名字保留。④ `_apply_parse_result` 末尾调 `_update_piece_filename()`（逐笔切换即换后缀）；`_resolve_output_basename` 的 order_no / db_order_no 兜底分支也包 `_with_piece_suffix`（文件名框被清空时仍防覆盖）。界面「2/4」沿用解析结果框现有「第 k/N 单」。
> **测试**：`tests/test_ui_app.py` 新增 6 个（`target_box_piece_count` 只计目标盒子/空/缺quantity；多件→`-k`、单件不加；无库件数回退队列长度；order_number 留空仍信库件数；自动值覆盖 vs 自定义保留）。改了 2 个既有桩工厂加 `_bind_piece_methods`（给 SimpleNamespace 绑新方法+默认单件属性）。`pytest tests/test_ui_app.py` = **103 passed / 8 failed**（8 = AGENTS 既记 headless 基线：preview zoom/pan/ruler×5 + birth_flower_app_initializes + case_toggle + field_instructions，与本次无关）；`py_compile`/`ruff` 我的源文件 clean。
> **⬜ 真机待验**（须关 App 重开）：库里有一单多件订单（items[] 多个目标盒子）→ 操作员端载入并解析 → 文件名框显 `订单号-1`、解析结果框显「第 1/N 单」→ 点「下一笔」切到第 2 件，文件名框变 `订单号-2` → 各点「生成」产出 `订单号-1.dxf`/`订单号-2.dxf` **不覆盖**；手把文件名改成别的字样后切件不被覆盖。
> **已知/取舍**：① k 来自**解析队列位置**，n 来自**库件数**——二者在三种买法下实测一致（队列每件一条）；若 GPT 拆件数 ≠ 库件数（边界真单），n 显库件数、k 显队列位，AGENTS 既有「拆件边界待真单调优」。② 没做「一键导出全部件」（用户选逐件）。③ 没碰 `_format_parse_result` 的 N（仍=队列长度），与文件名 n 在常态一致。

> **2026-06-22 · Font 4 末尾爱心 → 独立图层·锚定文字（可单独选中/拖动/调 mm）✅逻辑+测试 / ⬜真机（新对话先读）**
> **背景/需求**：Font 4 名字末尾的实心爱心原是**死贴在文字墨迹后**（排版时按写死比例 `gap=0.12×字号`、`高=0.62×字号` 算位置，烘进 `textLayout.endingHeart`，三端各自消费），用户无法单独调它。用户要求把爱心**分离成图层面板里可单独选中的独立图层**，且仍**锚定文字、每单自动跟随**，并能**直接拖动**或按 mm 调（与文字间距 / 上下偏移 / 大小）。
> **方案（已落地）**：新增 `models.AnchoredHeartLayer(ImageLayer)`（字段 `anchor_layer_id` / `gap_mm` / `offset_y_mm` / `size_mm` / `fill_color`；gap/size=None→回落旧 ratio）+ `add_anchored_heart_layer` 工厂（**不抢占 selected**）。新建 **`anchor_resolve.py`**：`resolve_anchored_hearts(doc, physical_width_mm=)`（幂等纯函数——按锚定文字 fit 的末行墨迹右缘 + mm 偏移就地重算每个爱心层 x/y/width/height，并给被接管文字置 `TextLayer.ending_heart_detached`）；`ensure_anchored_hearts` / `ensure_anchored_heart_for` / `remove_anchored_heart_for`（迁移/选 Font4 自动建·切走移除）；共享 `compute_text_fit`（resolve 与导出同一套，杜绝漂移）。
> **关键设计**：① **零回归数学保证**——文字 fit **仍传 `ENDING_HEART_ADVANCE_RATIO`**（名字照常让位、位置不变），resolve 用同一份 fit 定位爱心；auto 默认下新独立爱心层与旧烘焙路径 **PNG/DXF 逐像素相等**（护栏 `tests/test_anchored_heart.py::test_anchored_heart_matches_legacy_baked_geometry` 锁死）。② **导出走 inlineSvg**——`desktop_export._anchored_heart_layer` 直接喂 `heart_symbol.heart_svg_markup()`（仅 M/C/Q/Z，DXF 安全），**绕开磁盘圆弧版 `assets/symbols/heart.svg`，零改 services/api**；resolve 已把几何设成爱心紧致盒、scale=1，viewBox=`0 0 W H` → 导出端 viewBox→框映射 1:1 重现。③ **三处统一 resolve 前置**：`desktop_export._document_to_layer_document` 顶部 / `renderer.render_document_png` 合成前 / `ui_app._redraw_preview` 绘制前（各端 `isinstance(AnchoredHeartLayer)` 必须**先于** `ImageLayer` 判，子类！）。④ **拖动**=改相对 mm：`ui_app._on_canvas_drag` 对爱心把位移折成 `gap_mm`/`offset_y_mm`（缩放手柄折成 `size_mm`），既能自由拖、又保持锚定跟随（`_effective_gap_mm` 先把 None 物化）。
> **改的文件**：`models.py`(子类+字段+工厂)、`anchor_resolve.py`(新)、`desktop_export.py`(分支+suppress+`_anchored_heart_layer`+共享 fit)、`renderer.py`(PNG resolve+`_composite_anchored_heart`)、`text_renderer.py`(detached 时不贴爱心、advance 不变)、`ui_app.py`(import+自动建/移除钩子在 `_apply_auto_glyph_rules_to_layer`、`_redraw_preview` resolve+`_draw_anchored_heart_preview`、右键/双击/拖动路由、`_open_heart_anchor_dialog` mm 框、♥ 图标)、`tests/test_anchored_heart.py`(新)。旧 `endingHeart` 烘焙 + 预览贴图 + svg/dxf 消费**全保留作兜底**（仅当文字确有锚定爱心层时才抑制）。
> **测试**：`pytest tests/test_anchored_heart.py tests/test_text_wysiwyg_consistency.py tests/test_ending_heart_vector.py tests/test_text_layout.py tests/test_heart_symbol.py` = **全绿**（含零回归等价/名字跟随/mm 生效/独立层导出/迁移/空名隐藏/拖动累加+改名仍跟随；脚本另验 drag +60,+30→精确位移、改名保留偏移）。用 `.venv-win` 跑。
> **⬜ 真机待验**（须重开 App）：选 Font 4 订单 → 图层面板出现独立「♥ 末尾爱心」层（可单独选中）→ **拖动爱心**自由移动（松手后位置保持、不被 resolve 拉回）→ 右键/双击开「爱心间距 / 大小…」调 mm → 导出 DXF 在 EzCad2 里爱心可单独选中、高=size_mm；换不同名字爱心仍自动跟随末行墨迹。
> **已知/取舍**：爱心 size_mm 调大时**名字不会额外缩小让位**（advance 仍用旧常量，保证 auto 默认零回归；放大爱心是用户显式行为，可自行拖/缩文本框）；`gap_mm`/`size_mm` 默认 None=自动(随字号)，用户一旦拖动或在 mm 框输入即转为显式 mm。规划文档 = `C:\Users\Administrator\.claude\plans\flower-4-svg-serene-quasar.md`。


> **2026-06-22 · 操作员端「订单信息框」改由库驱动载单（FIFO 最旧『待生成』先做），停用文件轮询 ✅逻辑+测试 / ⬜真机（新对话先读）**
> **背景/决策（用户拍板，跨 flower + automation）**：操作员端「订单信息」框原来源=**收件夹文件轮询**（`_poll_inbox_once` 扫 `outputs/inbox/*.json`）。改成**库驱动载单**：后台每 `DB_ORDER_POLL_INTERVAL_MS=3000ms` 轮询 inbox-service，取「**库中最旧的待生成订单**」（未软删 + `ai_status=pending`＝FIFO 队首）载入订单信息框+文件名框。① 触发=**持续轮询**、队首变了才覆盖（不每轮清空、不冲掉操作员正在编辑的单）；② 「队首」=**FIFO 最旧先做**（`received_at` 升序）；③ **文件轮询对订单信息框停用**，来源统一为库。
> **关键：生成后如何「放行下一单」（用户最终拍板）——不删除，打「AI已生成」标（DB+店小秘）**：生成成功**早已**走 `_enqueue_mark_done_after_generate → request_mark(mark_done)` → 服务端 routes.py `set_ai_status(RECOGNIZED)`（DB 权威态）+ 入队 mark_done（扩展给店小秘打「AI已处理」）。**本轮不加删除**：生成完的单 `ai_status→recognized` **自动掉出「待生成」队列**（仍留在订单表里带「AI已处理」标），队首前进到下一条 pending → 轮询 ≤3s 内载入它。recognized/conflict/locked/软删都不算待生成、不会被取到。
> **实现 A（automation/inbox-service，新增只读端点，非契约改动）**：`repository.oldest_pending_order(session)`（`WHERE deleted=False AND ai_status='pending' ORDER BY received_at ASC LIMIT 1`，eager-load items+mark_jobs；`ai_status` 列本有索引）；路由 `GET /inbox/orders/next` → `{"order": {...}|null}`，**必须声明在 `/{order_id}` 之前**否则 `next` 被当 order_id。顺手删了 repository.py 一个既有 dead import `AI_STATUS_RECOGNIZED`（ruff）。测试 `tests/test_next_pending_order.py` ×4（最旧 pending/跳过 recognized 前进/排除软删+conflict/无 pending 回 null）。inbox-service 全量 **183 passed**。
> **实现 B（flower）**：`inbox_service_client.fetch_next_pending_order()`（GET `/inbox/orders/next`，取 `{"order"}`，无单/不可达回 None；**取代**本会话早先写的 `fetch_oldest_order` 那套 count→offset，已删）。`order_importer.order_from_payload(dict)`：库订单 dict→`OrderImport(order_id, remark)`，**只看顶层键**（避免递归误命中 items/mark_jobs），顶层 `remark` 优先空则回退 `items[].personalization_raw`。`ui_app.py`：`__init__` 加 `_db_order_active_id`(队首守卫,reload-on-change)/`_db_order_after_id`；启动用 `_start_db_order_poller()` **取代** `_start_inbox_poller()`；`_on_app_close` 加 `_stop_db_order_poller()`；新增 `_poll_db_order_once`(work=`fetch_next_pending_order`)/`_schedule_next_db_poll`/`_load_db_order`。`_load_db_order` 对齐旧 `_auto_load_order`（订单号置顶第1行、写 `current_order_number`+文件名框、按 `inbox_autoparse` 决定是否自动解析、**绝不自动生成**）。`_render_fetch_status`「当前单」改取 `_db_order_active_id`；`_resolve_output_basename`/`_enqueue_mark_done_after_generate` 加 `_db_order_active_id` 兜底。**首轮 poll 延后一个间隔**（`_start` 调 `_schedule_next_db_poll` 而非同步 `_poll_once`）：不在构造期同步起后台线程，headless 测试不跑 mainloop 不泄漏线程。
> - 旧 `_start_inbox_poller`/`_poll_inbox_once`/`_auto_load_order`/`_advance_inbox_after_generate` 代码**保留但启动不再调**（`_inbox_active` 恒 None，相关兜底无害）；手动「导入备注」`import_remark_file` 未动。
> **测试（flower）**：client `fetch_next_pending_order` ×3、importer `order_from_payload` ×4、ui_app `_load_db_order` ×2 + 文件名优先级补 db_order 档。全量 `pytest tests services/api/tests` = **525 passed / 8 failed / 7 skipped**；8 failed 全是既有 baseline（6×预览 `<B2-Motion>`/zoom/pan/ruler + case_button + field_instructions，与本轮无关，`test_ui_app.py:447` 等）。`ruff`/`py_compile` 我的源文件 clean（test_ui_app.py 的 `SAFE_MARGIN_Y` F401 是既有 WIP，非本次）。
> **排序口径**：FIFO 按 `received_at`（入库到达顺序）升序，**非** `paid_at`（付款时间）。若要严格按付款时间排，改 `oldest_pending_order` 的 `order_by` 为 `paid_at`（注意 paid_at 可空，需 NULLS 处理）。
> **⬜ 真机待验**（须关 App 重开）：起 inbox-service(8770) + 库里有 pending 单 → 进操作员端，订单信息框自动载入最旧 pending（订单号置顶）、文件名框=订单号；点「生成」成功后约 3s 内**自动前进**到下一条 pending，且原单仍在订单表里、标签变「AI已处理」（DB ai_status=recognized + 店小秘打标经扩展回写）；服务未起/无 pending 时不报错、不清空当前内容。

> **2026-06-22 · 统一打包聚合（flower+Ezcad+inbox-service → 一个绿色包，新对话先读）**
> 新增顶层 `packaging/`：把三端聚合成**一个 PyInstaller onedir 包**（产物 `dist/Workbench/app.exe`），双击=总启动器→后台拉起 inbox-service→两按钮开「开花桌面」「扫码导入」。**不合并 git 仓**，三端代码各自独立。
> **打包手法**：一方代码全部作 **loose data** 装入（`_internal/srcflower/`、`_internal/srcezcad/`），`app_dispatcher.py` 按角色（`launcher`/`flower`/`ezcad`/`serve`/`check`，缺省 launcher）运行时把对应目录插到 sys.path——两个同名 `app` 包（services/api 与 inbox-service）靠 **per-role sys.path + 子进程隔离**永不同进程共存。第三方依赖靠 `Workbench.spec` 的 `collect_submodules`/`collect_all`（**loose data 的依赖不会被 PyInstaller 自动分析，必须整树 collect**；曾漏 `fastapi.middleware.cors`）。inbox/services 收纳**只收 `app/` 子包**（排除两仓根的 `.venv`/`inbox.db*`(PII)/`.bak`/缓存）。
> **数据根契约（关键）**：launcher 算 `DATA_ROOT`（exe 同级 `data\`，不可写回落 `%APPDATA%\BirthFlower`），用 env 统一注入子进程：inbox 读 `FLOWER_INBOX_*`、flower 自身配置读 `BIRTHFLOWER_DATA_DIR`、**services/api 导出端读 `FLOWER_PROJECT_ROOT`（=DATA_ROOT，既是输出根又是资源根）**。launcher 首启把字体/花材（`Birthmonth_font.ttf`、`BirthMonth flowers/`）从 bundle **播种**到 DATA_ROOT，否则导出 `FONT_LOAD_FAILED`。`FLOWER_PROJECT_ROOT` 缺注入则报告落 `_internal`、与 inbox ReportWatcher（读 `FLOWER_REPORTS_DIR`）错位→状态回写断链（已修）。Ezcad 配置落 exe 同级 `config\settings.json`（自带 frozen-aware）。**升级=换 `Workbench\` 但保留 `data\`+`config\`**。
> **代码改动**：flower `config_store.py` 加 `_data_root()`/`_default_config_path()`/`_default_inbox_folder()`（env+frozen 分支；**源码态行为不变**）。Ezcad `ezcad_auto_layout/config.py` `load_settings` 加损坏容错（try/except + utf-8-sig）。其余全在 `packaging/`（app_dispatcher/launcher/Workbench.spec/build_release.ps1/templates/docs），不污染三仓现有结构。
> **构建**：`powershell -ExecutionPolicy Bypass -File packaging\build_release.ps1`（复用 `.venv-win`+补 sqlalchemy/alembic/pyinstaller；Ezcad 源默认同级 `..\Ezcad2.7.6`，可 `-EzcadSrc`/`EZCAD_SRC`；**暂用路径而非 git submodule**，因 Ezcad 有未提交 WIP，待其提交+推送后可平滑切 submodule）。**⚠️ 不带 `-SkipTests` 会被 8 个既有 headless UI 测试失败卡死 gate**（test_ui_app.py，AGENTS 本就记为既有失败）——出包前用 `-SkipTests` 或先修这 8 个。`build_release.ps1` **必须 UTF-8 BOM**（WinPS 5.1 否则按 GBK 乱码致解析失败；Edit 工具保存会去 BOM，改后须 `[System.IO.File]::WriteAllText(... new UTF8Encoding($true))` 重加）。
> **已验证**：冻结态四角色 `check` 全过、serve `/healthz` 通、总启动器自动起服务+播种、flower/ezcad 开窗、PII/.venv 已剔除、包体 ~123MB；inbox 130/Ezcad 124 测试全绿。**⬜ 真机待验**：完整批量生成（`.xlsx` 导入→DXF/SVG/PNG+report→inbox watcher 回写）需真实素材目录+EzCad 跑一单，确认产物落配置的输出目录、报告被 watcher 消费。
> **后续**：扩展现「随包 `extension-dist/` + Chrome 手动加载已解压」，注册 Google 开发者后切「未上架 Web Store」（代码不变只换渠道）。完整规划/取舍 = `C:\Users\Administrator\.claude\plans\flower-c-users-administrator-documents-wiggly-karp.md`；本次另有一份 5 维对抗审计（13 findings，blocker 已全修）。

> **2026-06-22 · 「自动识别」改由 GUI 显式控制（默认关，新对话先读）✅逻辑+测试 / ⬜真机**
> **背景/根因**：收件夹来单后是否自动 `parse_remark()` 由 `config.inbox_autoparse` 决定（`ui_app._auto_load_order`），原**默认 True 且无独立 GUI 开关**——容易在用户没要求时就自动解析。
> **改动**：① `config_store.AppConfig.inbox_autoparse` 默认改 **False**；新增 `inbox_autoparse_user_set`（bool）。`load_config` **安全迁移**：仅当 `inbox_autoparse_user_set=True`（用户经新版 GUI 显式设过）才采信存储的 `inbox_autoparse`，否则（旧配置遗留 True / 全新 / 缺字段）**一律回落 False**；`save_config` 同时持久化两键。② `ui_app._build_fetch_panel`「抓取订单」区在「自动抓取」旁加并列**「自动识别」开关**（纯本地、不发 HTTP，与自动抓取语义/状态完全独立），新 `_on_autoparse_switch_toggle` 拨动即 `dataclasses.replace`+`save_config`（记 user_set=True）并即时生效；`_auto_load_order` 仍读 `self.config.inbox_autoparse`，手动「解析」不受影响。
> **语义对照**：自动抓取＝是否从店小秘自动抓单（驱动 inbox-service `/scrape/control`，远程）；自动识别＝新订单进 GUI 后是否自动解析（本地 config，默认关）。两者独立。
> **测试**：`tests/test_config_store.py`（默认关 / 旧 True 回落 / 显式开关往返）、`tests/test_inbox_poller.py`（默认不解析 / 开则解析既有用例 + 新 toggle 持久化即时生效 + 与抓取控制互不影响）→ **31 passed**；`ruff` 干净。test_ui_app.py 的 8 个失败是既有 headless/重构期 drift（preview/ruler/zoom/`case_button`/`_on_canvas_pan_press`/AI prompt），与本改动无关。
> **⬜ 真机**：开 App→「操作员配置端·抓取订单」拨「自动识别」开/关，确认来单时分别自动解析 / 仅载入；重启后开关状态保持。
> **配套扩展侧修复（automation）**：同日修「自动抓取关闭时手动上传不打标」，建独立手动 force 打标路径——详见 `automation/AGENTS.md` 2026-06-22 块。

> ⚠️ **当前事实（2026-06-14，新对话先读这段）**：本文件下方「Architecture / Frontend / Test Commands(pnpm)」描述的是**暂缓的 Electron 目标架构，不是现状**。
> **生产现实**：用户实际在用的是 **Tkinter 桌面 App**（`birth_flower_mvp.py` + `ui_app.py`）+ **共享后端** `services/api`（桌面以 in-process import 调用，不走 HTTP）。包管理是 **npm 不是 pnpm**。
> **当前事实来源**：`PROJECT_INDEX.md` + `CURRENT_TASKS.md`（已校正本文件 Architecture 段）。导出/EzCad 细节见 `docs/superpowers/plans/2026-06-13-dxf-export-progress.md`。
>
> **2026-06-17 决策（新对话先读）**：继续开发**纯桌面端**（Tkinter），web 迁移**暂缓**（仅当出现**远程/多地操作员**才重启）。**操作员默认全权**（粘单/解析/画布编辑/加删图层/换素材/资源库/输出/新建产品/生成），**启动无登录页直接进操作员态**；**唯一上锁** = 「**提示词配置**」（背景词 + 提取/字段规则 + 校验规则，驱动 AI 识别那块），进它才要**管理员密码**。换素材**只在图层已绑定的变体内换**。复用现有配置锁机制（`self._locked_widgets`/`_ctk_card(locked=True)`/`config_locked`，原无密码=P4，本轮**只给「提示词配置」那张卡补密码存 hash**）。**红线：锁只盖提示词配置、不盖画布。** 设计/边界/已定项详见 `docs/superpowers/plans/2026-06-17-operator-admin-role-split.md`。
>
> **2026-06-18 决策（新对话先读，覆盖下方「追加（同会话…）」段里关于 `ORDERS_PROMPT_SCAFFOLD` 的旧描述）**：用户要求**解析层不携带任何本地业务规则**，提示词 **100% 来自前台**。本轮在 `gpt_parser.py` **真删除**了所有写死的业务规则提示词：① `ORDERS_PROMPT_SCAFFOLD`（角色/订单块格式/输出字段/warnings 规则脚手架）+ `DEFAULT_EXTRACTION_RULES` 兜底 → 删除；`build_orders_system_prompt(rules, background)` 改为**只拼接前台内容**（字段规则 + `【背景】`），空入参返回空串。② 单订单 OpenAI（`parse_order_remark_with_gpt`）删除业务规则 system 消息（输出靠 `ORDER_REMARK_SCHEMA`）。③ `_order_remark_system_prompt`（DeepSeek 单订单）删业务语义、仅留 I/O 字段约定。**机器 I/O 约定按用户要求保留**：OpenAI `ORDERS_SCHEMA`(json_schema strict) + DeepSeek `_parse_orders_with_deepseek` 的「顶层 orders+字段列表」提醒（line 261-263）原样不动，故解析不会坏。catalog 链（`order_catalog.build_catalog_system_prompt`）本轮**未动**（桌面主链路不走它）。测试：`test_orders_multi.py` 改导入(去 `DEFAULT_EXTRACTION_RULES`)+2 处断言（脚手架→「只含前台内容/空串」），解析层全绿。已知：`test_ui_app.py::test_field_instructions_drive_ai_system_prompt` 红，是**旧测试 vs 现默认字段**不符（默认字段已无 month/Narcissus 月→花表），**非本轮引入**，需后续对齐 `_default_field_defs` 与该测试。
>
> **web 分支暂挂(2026-06-17 体检后)**：`claude/web-editor`(worktree `.worktrees\web-editor`)脚手架完整(React19+**Fabric7**+真 FastAPI),但 `services/api` 引擎落后根目录几个月(无 `text_layout`/`material_library`/`order_catalog`/`config_store`/`gpt_parser`/`screenshot_parser`/`glyph_service`),且 **SVG/PNG 是前端 `exportPipeline.ts` TS 渲染、绕开 Python WYSIWYG**(只有 DXF 走 Python)。**复工第一步=引擎归一**(根模块搬进 services/api + 暴露 Python svg/png 接口 + 删 TS 渲染),不是堆 UI。详见该设计文档 §12。

> **2026-06-19 · 三端 UI 落地 + 操作员配置端订单表 + 定时抓取选择器（新对话先读）**：把「操作员配置端」从"资源库配置+强塞画板"重定位为**抓取调度+订单监控控制台**——中心区**画板换成实时订单表**（`_apply_center_for_view`；数据=`GET /inbox/orders`，inbox-service 接口本就存在，flower 加 `inbox_service_client.list_orders` + `_build_orders_table_panel`；件数/退款/其他商品由纯函数 `order_row_view` 从 `items[]`/`refund_status` 聚合，扩展暂只抓列表页时件数显「—」，文件数待 Phase 1），右侧功能区去掉图层卡（`_VIEW_CARD_ORDER[operator_config]=("fetch","library")`）。**「定时锁」改名「定时抓取」**、手填框换成 `datetime_picker.CTkDateTimePicker`（月历+时分；仍写回 `scrape_from_var`，restart_from 逻辑不变）。管理员端三张 IP 卡（字段/背景提示词/本次提示词）经 `_ctk_card(badge=)` 加「仅管理员·IP」标、切端控件管理员端染琥珀；**密码门不加（靠分端隔离）**。**搁置**：操作员端图层行图标/解析结果上色（避动 WYSIWYG/金标）、定时规则 A/B/C（Phase 2 调度器未建、不出 dead 控件）。单测全绿（`test_datetime_picker.py`、`test_ui_app.py` 的 view 映射/`order_row_view`/`_short_dt`、`test_inbox_service_client.py::test_list_orders_*`）。**真机手测待做（须重开 App）**。详见 `docs/superpowers/plans/2026-06-19-three-end-ui-and-orders-table.md`。
>
> **2026-06-20 · 订单数据源澄清 + 删除/保留功能（新对话先读）**：订单**持久化在 SQLite `automation/inbox-service/inbox.db`**（扩展抓单→inbox-service 写库行 + 落 `outputs/inbox/*.json` 临时交接文件；**删 JSON 不删库行**，这是用户踩过的困惑点）。新增订单删除/清理：后端 `DELETE /inbox/orders/{id}` + `POST /inbox/orders/purge {older_than_days>=1}` + `repository.delete_order`/`purge_orders_older_than`；**保留天数**=`ScrapeControl.retention_days`（迁移 `0006`，**0=关默认**），`RefundScheduler.tick_once` 每轮按它**无人值守删旧单**（纯按 `received_at` 年龄，会删未完成单，默认关+UI 强确认）。flower 客户端 `delete_order`/`purge_orders`/`put_scrape_control(retention_days=)` + 订单表行删除/清理栏。测试：服务端 `test_order_cleanup.py`（107 passed）、flower 客户端（10 passed）。详见同一计划文档 §7。
>
> **2026-06-20 · 订单表状态列修正 + 三套状态澄清（重要，新对话先读）**：① `Order.status`=内部流水线状态（当前库 173 单几乎全 WRITTEN_TO_INBOX，单一常量）；② **`Order.refund_status` 名为 refund 实为店小秘"订单状态"原文**（已审核/已发货/待打单(有货)/已退款/已忽略；扩展抓 `.orderState`），退款拦截 refund_gate 用它做关键词分类——**别当退款布尔**；③ 店小秘"自定义标记"(AI未识别/AI已处理/…)——扩展原只读「AI未识别」(→`extras.ai_unrecognized`)，**2026-06-20 已加「写标记」能力**（见下「标记回写」块）。订单表"状态"列已改为显示**店小秘状态(refund_status)**（`ui_app.py` `shop_status_style()` 上色）、**删掉"退款"列**、内部状态挪进详情；`order_row_view` 重构(status_label=店小秘状态, 新增 shop_status/internal_label, 去掉 refund 键)；测试 `test_shop_status_style_*`/`test_order_row_view_*`（86 passed）。**「标记回写店小秘」✅ 2026-06-20 已实现**（见下方「标记回写」块；店小秘无 API，扩展模拟网页操作）。

> **2026-06-20 · 标记回写店小秘（扩展打自定义标记）✅逻辑+测试 / ⬜真机（新对话先读）**
> 新单入库→扩展给店小秘订单打「**AI未识别**」(待处理)；flower 生成成功→打「**AI已处理**」+清「AI未识别」。
> 跨 flower/automation；**权威 = `automation/docs/2026-06-20-mark-writeback.md`（冻结契约 + 真实 DOM 勘查 + ExecPlan）**。
> **flower 侧改动**：`inbox_service_client.py`+`request_mark(order_id, action)`（POST /inbox/mark/request）；`ui_app.py` `confirm_and_generate` 成功 → `_enqueue_mark_done_after_generate`（run_background best-effort 入队 mark_done，**须在 _advance_inbox_after_generate 清 _inbox_active 前取订单号**=current_order_number→回退 inbox 文件名 stem；服务未起/手输无订单号则静默不入队、仅副提示行轻提示）。测试：`test_inbox_service_client.py`(+2)、`test_ui_app.py`(+3)。**pytest 395 passed**（8 既有 headless 失败不变）。
> **automation 侧**（扩展打标 DOM + inbox-service mark_jobs 队列 + 迁移 0007）见 `automation/AGENTS.md` 同名块。
> **2026-06-20 追加（标准1/标准2 + 标签列）**：① 上传门控=传 JSON 前看店小秘标记，AI已处理不传、否则查库 diff 才传（手动按钮 + 自动抓都遵守）；② 上传成功后打 AI未识别（除非已 AI已处理）、生成成功打 AI已处理+清未识别；③ **配置端实时订单表加「标签」列**（`ui_app.mark_status_style` 由订单 `mark_jobs` 摘要派生：AI未识别/AI已处理 + 待写/已写/失败），操作员据此核对回写是否生效。详见 `automation/docs/2026-06-20-mark-writeback.md` §八。
> **⬜ 真机待用户**：起 8770 + 扩展 dist 加载店小秘列表页 + 开启抓取开关 + 测试单走全链；3 个真机校准点（添加按钮选择器/click vs hover/点击即生效 vs 须确定）见计划文档。

> **2026-06-19 · 「订单自动化与排版系统」增量方案——flower 核心承担的切片（新对话先读）**
> 三仓大方案权威设计 = `C:\Users\Administrator\.claude\plans\ezcad2-7-6-flower-c-users-administrator-staged-wren.md`（基线 A=增量扩展现有代码，不重写）。**契约已冻结**：店小秘订单 JSON 现可带 `items[]`（多盒子/多件/其他商品，每项 is_target_box/quantity/personalization_raw）+ `refund_status`（见 `automation/contracts/order.schema.json`，automation 侧已落地，向后兼容）。
>
> **flower 核心待做**：① **解析消费多件**——`order_importer.py` / `models.py ParseResult` 读 `items[]`；"数量 vs 定制条数"三种买法（A 一条备注 N 名字 / B N 个行项目 / C ×N 同一定制）在 `gpt_parser.py`/`parse_pipeline.py` 做**语义拆分 + 件数校验**，不一致→人工审核（扩展只抓结构，**拆分在 flower GPT 层**，边界待真单调优）。② **多件→多文件生成**：一单两盒子出 `订单号-1`/`订单号-2` 不互相覆盖（命名/映射 = 计划 P0-6；**动 flower 生产关键路径，动手前先与用户敲定**）。③ **解析页可观测性**：点「解析」按序刷新 ①原始内容 ②本次提示词全文 ③结构化结果（提示词随本次操作自动刷新、不用再点一次）。④ **人工审核闭环**（查看原文/触发原因、改结构化数据、放行/驳回/转客服/重解析、审计；通过=**新版本不覆盖**原解析=计划 D2）。⑤ **编辑器组合图层**（Phase 5）：把"文字层/素材层"合成"一个图层内 文字+间距(px)+素材+文字"（现 `models.py` TextLayer/ImageLayer 分离，这是方案里**唯一允许的有限重构**；护栏 `tests/test_text_wysiwyg_consistency.py` 必须全绿才合并）。⑥ **文字 x-height/视觉中线精细对齐**（Phase 6，**阻塞**于用户手绘样例，先别硬猜算法，仅预留每图层上下偏移参数）。
>
> **已是现状、别重做**（需求文档曾误判为"待建"）：字体二(PUA 合体字形替末字母)/字体四(保留全名、末尾加独立爱心)已实现且预览/SVG/DXF 三端一致（`glyph_service.py`/`heart_symbol.py`/`text_layout.py`）；可见边界缩放 `visual_layout.fit_content_bbox_to_target_rect`；基线对齐 `text_layout.fit_text_box`；画布/图层 XY 配置。这些降级为「真机演示验收」。
> **纪律**：`automation/contracts/order.schema.json` 只走计划/协调线程改。

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

## 本会话改动（2026-06-22 · 素材库/字体库「统一导入」+ 修字体库选目录后要关窗口才能再选；改 ui_app.py/material_library.py + 测试）

**问题**：① 字体库在设置窗口里选目录后，要关窗口/程序才能再选（交互不合理）；② 素材库与字体库导入规则不统一。

**根因**：① 「字体库/素材库」卡片的「点击上传」按钮实为 `open_settings`（开模态设置窗口），而设置窗口里 `choose_font_source` 走「先弹选文件、取消再弹选文件夹」的嵌套对话框，在 `grab_set()` 模态窗口里会卡住→需关窗口。② 字体走 `choose_font_source`（文件或目录、嵌套对话框），素材走 `choose_flower_dir`（只目录），规则各异。

**与用户敲定（本轮拍板）**：入口位置不变、只改逻辑；选择方式=**只选文件夹**（库=文件夹）；重复/文件夹导入=**累加并入、按路径去重**。

**改动（统一流程：选路径 → 判断文件/文件夹 → 过滤有效 → 注册 → 刷新）**：
- `ui_app.py` 新增模块级纯函数 `collect_importable_files(root, suffixes, *, recursive=False)`：文件或文件夹统一展开成 `(受支持文件, 跳过的不支持文件)`；只看后缀、大小写不敏感、**永不因坏文件抛异常**。配套 `_paths_equal`（规范化路径去重）。
- `_build_library_panel` 改为稳定容器 + `_render_library_rows()`（字体库一行/素材库一行，各显文件数 + 「点击上传」），导入后就地刷新、不重建整卡。
- 新增 `upload_into_library(kind)`（卡片「点击上传」入口，`askdirectory` 选文件夹）+ `_add_library_folder(kind, folder)`：累加并入当前产品 `image_library_dirs`/`font_library_dirs`（去重）→ `with_product_library_dirs` 落盘 → `_scan_assets` 重扫 → 刷新；汇总「已导入 N / 跳过 M / 已在库中」。复用既有多库机制，天然持久化。导入数按「真正进入候选的增量」算。
- `choose_font_source`（设置窗口）去掉嵌套对话框，改纯 `askdirectory`，与素材目录 `choose_flower_dir` 口径统一、消除卡死源头。
- `material_library.py` `IMAGE_EXTENSIONS` 补 `.bmp`（与 `IMPORTABLE_ASSET_SUFFIXES` 口径一致，零配置文件夹扫描也收 bmp；向后兼容）。
- **未动**：菜单「导入素材...」单文件路径（`_import_asset_path`/`_import_font_file`/`_import_flower_file`，验收「单文件导入」仍走它）、DXF/SVG/PNG 导出链、现有单文件导入测试。

**验证**：`py_compile` + `ruff` 我的文件全 clean；新增 6 个测试（`collect_importable_files` ×3：单文件按后缀/文件夹分流+大小写+递归/不存在路径空；`_add_library_folder` ×3：素材文件夹批量并入+去重、字体文件夹导入+跳过不支持、空文件夹只提示不改配置）全过。`pytest tests/test_ui_app.py` = **92 passed / 8 failed**，8 失败 = AGENTS 既记的 headless 基线（6× preview 缩放/平移/标尺 + case_button + field_instructions），与本次无关；`test_material_library/order_catalog/product_switcher/screenshot_parser` = 37 passed。
**未真机点测**（需关 App 重开，进操作员配置端验）：① 字体库/素材库「点击上传」选文件夹即导入、下拉立刻出新字体/素材、卡片文件数刷新；② 连续多次选不同文件夹不用关窗口、累加去重；③ 含杂项文件的文件夹跳过不支持项不崩；④ 空文件夹给提示不改配置；⑤ DXF/SVG/PNG 导出仍正常。

## 本会话改动（2026-06-20 · 选端页门厅重做 + 管理员密码门 + line_icons 图标管线；改 ui_app/config_store + 新增 line_icons.py/assets/icons + 测试）

承「用 JTBD 做选端页设计」一路敲定到落代码（用户全程拍板）。**关键产品决策（新对话先读）**：① 后续要拓展**多产品**（生日花 / 眼镜 / 吉他拨片…），但**一人混处理多产品**（共享收件夹、订单混着来）→ **选端页门口只选角色、不选产品**；产品在操作员端内部走现有左侧产品栏（`product_rail`）随单切换。② 管理员端**真做密码门**（推翻 2026-06-19「现在不用账号」那条）。③ 图标走 **Tabler Icons（MIT）**，不装任何新 pip 依赖。

- **新增 `line_icons.py` + `assets/icons/`（14 个 Tabler outline SVG）**：图标染色（替 `currentColor`）→ **已装的 cairosvg→PIL** 栅格化 → `CTkImage`，同 `text_renderer._rasterize_heart` 管线。缺依赖时优雅返回 None（调用方退化为只显文字）。**零新依赖**（保真度审计结论：customtkinter 5.2.2 / Pillow 12.2.0 / cairosvg 2.9.0 现成就够，全程无新 pip 包、无运行时下载）。
- **`config_store.py` 加管理员密码**：`admin_password_hash` 字段（load/save 持久化，向后兼容旧配置）+ `hash_password/verify_password/has_admin_password/verify_admin_password/with_admin_password`（**PBKDF2-SHA256，纯标准库**，只存哈希）。
- **`ui_app.py` 选端页重写**（`_show_view_chooser` 一带，方向 = B「精炼深空」+ C 门口状态条）：门厅专属深色皮肤 `ENTRY_COLORS`（#101218/teal-blue-amber，比内部 `APP_COLORS` 更黑，**门厅↔内部有意色差**）+ `_blend_hex`（无 widget 透明度→预混不透明 hex，底色纯平时像素级一致）+ `ENTRY_ROLE_META`。布局：**操作员端=hero 大卡**（图标+标题+描述+待处理数+进入，整卡可点、回车直达）、**配置端/管理员端=两张次端小卡**、**门口实时状态条**（服务/抓取/积压，`_refresh_entry_status` 后台 best-effort 探活 inbox-service，没起则显未连/—，不阻塞不抛）、**多产品页脚**（取真实 `config.products` 名，眼镜/拨片等上线后自动出）。hover=描边/底色变（`_bind_card_hover` 用 winfo_containing 沿 master 链判离开，避免子控件误触发）。
- **管理员密码门**（`_show_admin_gate`）：scrim 暗幕（`_blend_hex("#08090c",bg,0.72)`）+ 居中模态卡；**首次进=设密码（双输入，≥4 位）**、之后=校验；`_admin_authed` 本次运行级，过一次后切端不再问。**门厅入口与顶部「切端」下拉两条路径都过同一把关**（`_enter_admin_view`）。
- **修了审查发现的真 bug**：`_on_switch_view` 切管理员端原用 `_needs_admin_gate()`（=有密码且未鉴权），**未设密码时会让下拉直接进管理员端、绕过设密码**；改为 `not self._admin_authed` 统一交 `_enter_admin_view`，堵住鉴权绕过。（审查另两条「CTkImage 没实例级强引用」「image=None 传参不一致」经核实是把 PhotoImage 常识误套到 CTkImage 上的**误报**：CTkImage 由 live CTkLabel 持有、image=None 是其默认值，未改。）

**验证**：`py_compile`+`ruff` 我的文件 clean（test_ui_app 里 `SAFE_MARGIN_Y` F401 是既有 WIP，非本次）；新增测试 **12+2 个全过**（config_store 密码 ×4 round-trip/持久化、line_icons ×3、门厅 `_blend_hex`/`ENTRY_ROLE_META`/gating ×5、下拉鉴权护栏 ×2）。`pytest tests/test_{config_store,line_icons,ui_app}.py` = **109 passed / 8 failed**（8 失败经 `git stash` 基线确认全是本分支既有 WIP：preview 缩放平移/`case_button`/`field_instructions` 旧字段断言/headless `__init__` 网络线程，**与本次无关**）。**门厅真渲染 headless 冒烟过**（`__new__` 绕开坏 `__init__` + 真 ctk root：overlay/chips/hero/密码门 开合/gating 全绿）。
**已知 / 未做（不许当已完成）**：① **未真机点测**（GUI 跑不了，须用户重开 App 验：门厅观感、hover、整卡可点、回车进操作员端、首次进管理员端设密码→重进校验、下拉切管理员端也要密码、状态条连上 inbox-service 后显真实积压/抓取态）。② 门厅是 B 配色、App 内部仍 `APP_COLORS` 深蓝，有「门厅 vs 内部」色差（本轮范围内有意取舍，若要统一是后续活）。③ 进入动效（淡出+缩放）、hover 2px 上浮未做（避免 grid 重排抖动，只做描边/底色变；都无依赖、属后续打磨）。④ 多产品（眼镜/拨片）目前只是页脚信号位 + 产品栏占位，真正接产品是另一条线（见 2026-06-14 素材库计划）。⑤ 密码门「忘记密码」无找回（改 `birth_flower_config.json` 清 `admin_password_hash` 即重置）。

## 本会话改动（2026-06-19 · 三端选端架构骨架 + 解析可观测性②③；改 models/gpt_parser/parse_pipeline/ui_app + 测试）

承「订单自动化与排版」增量方案 flower 核心待做 ③（解析页可观测性），与用户敲定后**演进 2026-06-17 单视图方案为「三端选端」**（用户拍板：照此拆 3 端、无账号、入口选端、顶部可切端；解析结果用只读常驻框、异常才弹）。

**① 后端：解析「实际发出的提示词」可回传（零漂移）**
- `models.py` 新增 `ParsePromptTrace`（可变 dataclass，作出参）：provider/model/system_prompt/user_content/filled。
- `gpt_parser.py`：抽常量 `DEEPSEEK_ORDERS_JSON_SUFFIX`（DeepSeek 的「顶层 orders+字段」JSON 约定后缀，原内联字符串）；`parse_orders_with_gpt`/`_parse_orders_with_deepseek` 加 `trace` 出参，把**真正发出的** system 全文（DeepSeek 含后缀）+ 用户内容 + 解析到的 provider/model 就地写回。**保证「界面显示的提示词 == 真发出的内容」逐字一致**。不传 trace 时行为零变化。
- `parse_pipeline.py`：`parse_orders_auto`/`_call_orders_gpt` 透传 trace；trace=None 时不放进 kwargs（对旧 fake 解析器零侵入）。
- 测试 `test_orders_multi.py` +4（openai/deepseek trace 逐字一致、不传 trace 零变化、管线透传）。

**② UI：三端选端骨架 + 删配置锁（仅 ui_app.py）**
- 模块级 `VIEW_OPERATOR/VIEW_OPERATOR_CONFIG/VIEW_ADMIN` + `view_cards_for_role(role)`（纯函数，端↔卡片映射，可单测）。端↔卡片（2026-06-19 用户二次拍板后）：**操作员端**=order/result/production/output；**操作员配置端**=production/library；**管理员端**=order/result/production/fields/background/prompt_obs/output。**「画布」(实时画板 + 图层面板 production) 对三端开放**（production 进三端、预览画布常驻右栏不随端隐藏）；**输出（输出设置+生成）在操作员+管理员两端都挂**（管理员调规则后可直接生成验证端到端）；订单信息/解析结果(①③)在操作员+管理员两端共用同一 widget。
- `_build_function_panel` 改为**所有卡片建一次存进 `self._function_cards`（key→widget）**，按端 `grid/grid_remove`（不重建、不丢状态）。新增 `_apply_view`/`_enter_view`/`_on_switch_view`/`_show_view_chooser`。
- 启动弹**选端遮罩页**（`place` 覆盖全窗，三端卡片任选其一进入，无账号）；菜单条右侧加**「切端」CTkOptionMenu** 随时切。
- **配置锁已整体删除**（用户 2026-06-19 拍板）：移除 `config_locked_var`/`lock_button`/`_locked_widgets` 状态、`_register_lock`/`_prune_locked`/`_toggle_config_lock` 方法、`_ctk_card` 的 `locked`/🔒 参数、订单信息卡上的 🔒 按钮，并把各处 `_register_lock(...)` 调用就地拆掉。**IP 隔离改由三端分离承担**（提示词配置/字段/背景词只在管理员端显示）。无控件再被禁用。这条**取代** 2026-06-17 的「仅提示词配置上锁」方案。

**③ UI：解析可观测性②③挂到对应端**
- **③ 结构化结果**：新增「解析结果」卡（`_build_parse_result_panel` + `parse_result_box` 只读框）。`_apply_parse_result` 末尾调 `_render_parse_result_box`，显示本单 ParseResult 人读摘要（订单号/数量/刻字/月/花(名)/字体/留言/置信度/⚠warnings）；`_format_parse_result` 用 getattr 容错（部分字段 stub 不崩）。**异常单仍走现有「需人工确认」弹窗**（量产不被每单弹窗打断）。
- **② 本次提示词全文**：原「生成的提示词（开发期）」面板改名「本次提示词（实际发出）」，**解析后随本次操作自动刷新**（`_refresh_prompt_obs_from_trace` 在 `_apply_parsed_orders` 调，显示 `[provider·model] [system]… [user]…`）；解析失败也刷（便于排错）。「预览」按钮保留（解析前按当前字段拼一版）。本卡只在管理员端显示。
- **① 原始内容** = 现有「订单信息」备注框本身，无需新控件。
- `parse_remark` 建空壳 trace 传入 `parse_orders_auto`、存 `self._last_parse_trace`。

**验证**：`py_compile`+`ruff` 我的 4 个源文件全 clean；全量 `pytest tests/` = **365 passed / 8 failed（全部预存：6×预览 zoom/pan/ruler 的 `<B2-Motion>` WIP、`case_button` WIP、`test_field_instructions…` 旧测试 vs 现默认字段，均与本轮无关，已 `git stash` 复验基线确认）/ 7 skip**。新增护栏测试 `test_view_cards_for_role_splits_three_ends`、`test_format_parse_result_renders_structured_summary` + 4 个 trace 测试。**headless 集成冒烟过**：构造真 App→切三端 grid 卡片正确→选端遮罩显隐→切端下拉→②trace 刷新→③结果框渲染，全绿。修了 2 个本轮自引入的回归（`_format_parse_result` 对 stub 用 getattr；`test_parse_remark…` 的 fake_parser 加 `trace=None`）。

**已知 / 未做（不许当已完成）**：
- **未真机点测**：需在 App 验①启动选端页能进三端、②顶部切端、③操作员端解析后看「解析结果」框、④管理员端解析后「本次提示词」自动刷新且==真发出内容、⑤异常单仍弹「需人工确认」。
- **未做文件拆分**（ui_app.py 仍单文件）：本轮用「按端 grid 现有卡片」实现端分离（最小风险），未抽 `operator_view.py/config_view.py/admin_view.py`。用户提过单文件臃肿，文件拆分留作后续**纯重构**（护栏绿后再合）。
- **管理员端密码门未加**（用户「现在不用账号」）：三端现可自由切换、无鉴权；日后若要把管理员端锁回，再加密码门（非本轮配置锁，那把锁已删）。
- **操作员配置端**（fetch + production + library）；**新建产品未按端 gating**（产品列 product_rail 仍各端常显）。
- **flower 核心待做 ① 多件解析消费 / ② 多件→多文件生成 未动**：① 待接（`order_importer`/`ParseResult` 读 `items[]` + GPT 层件数校验）；② 动生产关键路径，**动手前需与用户敲定命名/映射**（计划 P0-6）。⑥ 文字对齐阻塞于手绘样例。

## 本会话改动（2026-06-20 · 订单链路性能优化·分阶段：应对常态 600+/峰值 1700+(1h涌入)）

**权威计划 + 全程进度**：[.claude/plans/2026-06-20-order-pipeline-perf-staged.md](.claude/plans/2026-06-20-order-pipeline-perf-staged.md)。三层分治、决策（**保留 SQLite 加固、不换 Postgres**；顺序一→二→三）、红线、真机校准点都在里面。跨 flower + automation 两子系统。

- **阶段一·DB 地基（automation/inbox-service，✅测试 130 passed）**：`db.py` 开 WAL+synchronous=NORMAL+busy_timeout（写不堵读）；`models.py`+迁移 `0008` 补索引 received_at/refund_status/(status,received_at)；`list_orders` 消 N+1(eager-load)+分页(limit/offset)+真实总数 count；新增 `POST /inbox/orders/batch` 批量入库；retention 改批量 DELETE。
- **阶段二·抓取吞吐（✅安全部分已测；翻页待真机校准）**：`scrape_planner.diff_manifest` 逐条 get→一次 IN 查询；扩展 `auto_cycle` 逐单 await→批量 `pushOrders`(`/orders/batch`)；**自动翻页+游标「页面记录」**（`worker/paginate.ts` 纯逻辑+`extractor/dianxiaomi_pager.ts` DOM 胶水+`content.ts` 接线，游标存 `chrome.storage.local`，加了 storage 权限）——稳态只读第1页、洪峰翻到接上游标，绝不每轮全量重读。扩展 vitest 83 passed/tsc/build 通过。**真机校准点见计划文档**（翻页等待时长/虚拟滚动满页/风控）。打标保持「抓完立即打标」（用户要求，未动）。
- **阶段三·UI 虚拟列表（flower，✅）**：订单表 `CTkScrollableFrame` 逐行 → `ttk.Treeview`（原生虚拟化扛 1700+ 行；深色样式；整行按退款/风控着色；双击详情、选中+✕/Delete/右键删除、多选）。`list_orders` 拉 limit=2000 一次显示全量。**↓ 下面那条「实时订单表 Level1+2 增量 diff」的 CTk 逐行渲染已被本阶段的 Treeview 取代**（本地删行思路保留）。
- 测试：inbox-service 130、扩展 83、flower test_ui_app 80 passed（8 failed=本分支既有 preview/文字/字段 WIP，与本次无关）。
- **整体未真机点测**：起 inbox-service(8770)+扩展 dist+配置端，验吞吐(翻页/批量)+订单表(1700行秒开/删除/详情)。

## 本会话改动（2026-06-20 · 「实时订单」表删除/刷新从整表重建 → 增量 diff + 本地删行，仅改 ui_app.py + test_ui_app.py）

问题：删一条订单走 `_confirm_delete_order` → `_refresh_orders_table`（再 `health`+`list_orders`+`get_scrape_control` 三次 HTTP）→ `_render_orders_rows` 把整表 `winfo_children()` 全 destroy 后逐行重建。按 218 单算 ≈ 销毁+重建 ~1700 个 CTk 控件 + 3 次 HTTP，几秒卡死、压 CPU、延迟高。范式照搬本仓已有的 `_render_layers`（按 id 增量复用行）。用户拍板做 **Level 1+2**（Level 3 = 换 `ttk.Treeview`/虚拟列表**暂不做**，单量常态上几百再排）。

- **Level 2 增量渲染**：`_render_orders_rows` 改 diff——表头常驻复用（`_orders_header`）；按 `order_id` 删消失行 / 建新增行(`_build_order_row`) / 存活行原位更新(`_update_order_row`) / `grid_configure` 重排。状态由 `self._orders_rows: {order_id→控件dict}` 持有（`__init__` 初始化，旁边还有 `_orders_header`/`_orders_empty_hint`）。
- **Level 1 本地删行**：`_confirm_delete_order` 成功回调改调 `_remove_order_row_local(order_id)`——只 `pop`+`destroy` 那一行、状态行计数 −1、删空显占位；**不再调 `_refresh_orders_table`**（不触网、不整表重建）。详情弹窗「删除此单」同享此路径（`on_done=win.destroy`）。
- 删 `_orders_row`（整行重建用）+ `_bind_click_deep`（仅其用到）；点行看详情改走 `_open_order_detail_row` 读 `row['raw']`（增量更新时变，绑一次不叠加）。`order_row_view`/`_format_scrape_status` 等纯函数不动。
- 行内删除后剩余行 grid 行号留空（空行高 0、无视觉缝），下次整刷（点刷新/进配置端/立即清理）经 `grid_configure` 重排为连续。
- 测试：新增 `test_orders_table_renders_incrementally_and_deletes_one_row_locally`（验：建/删/复用同控件对象/状态原位更新/本地删行；需 Tk，否则 skip）。`pytest tests/test_ui_app.py` = **80 passed / 8 failed**（8 失败=本分支既有 preview 平移缩放/文字大小写/字段指令 WIP，与本次无关）；`ruff`/`py_compile` 我的改动 clean（test 里 line 2169 `SAFE_MARGIN_Y` F401 是既有 WIP，非本次）。
- **未真机点测**：起 inbox-service 后进配置端验：删一条**瞬时不卡**、刷新只动变化行、删到空显占位、点行看详情/详情里删除均 OK。

## 本会话改动（2026-06-20 · 「抓取订单」开始/停止两按钮 → 单个实时开关 CTkSwitch，仅改 ui_app.py + test_ui_app.py）

用户诉求：自动抓总开关要在**操作员配置端**实时开/关。它本就在该端（`_VIEW_CARD_ORDER[operator_config]=("fetch","library")`），但旧版是 `[开始][停止]` 两按钮——这次按用户拍板**换成一个实时开关**（更直观、可见当前真实态）。**下方 06-19 那节里写的「开始/停止两按钮」已被本次取代，语义不变（仍是 PUT `/inbox/scrape/control {enabled}`）。**

- `_build_fetch_panel`：`[开始][停止]` → 一个 `ctk.CTkSwitch`「自动抓取」（`fetch_switch`/`fetch_switch_var`，progress_color=accent）；`[设置][刷新]`、定时抓取栏、状态文案均不变。布局：开关靠左、设置/刷新靠右。
- **勾选态 = 服务真实 `enabled`**；进配置端（`_apply_view` 懒探，原样）/点刷新后**自动同步**，不用手点。
- **未连接/状态未知 → 开关置灰不可拨**；误触发会**回弹+提示**先起 inbox-service。拨动期间禁用防连点；PUT 失败**自动回弹**并显错。
- 关键：`variable.set()` 只刷视觉**不触发 command**（CTkSwitch 的 command 仅用户点击才发），故 `_render_fetch_status` 回填开关态无递归。
- 删 `_on_fetch_start`/`_on_fetch_stop` → `_on_fetch_switch_toggle`；新增纯函数 `_scrape_switch_state(probed,connected,control)->(checked,clickable)` + setter `_set_switch_state`。`_format_scrape_status` 不动（其护栏测试仍绿）。
- 测试：新增 `test_scrape_switch_state_maps_connection_to_clickable_and_checked`（5 例）。`pytest tests/test_ui_app.py` = **79 passed / 8 failed**，8 个失败全是本分支既有的 preview 平移缩放/文字大小写/字段指令 WIP（`<B2-Motion>` 等绑定断言），**与本次无关**（init 测试已构造完含开关的整个 App 才在 preview 断言失败）。
- **未真机点测**：需起 `uvicorn app.main:app --port 8770` + 进操作员配置端，验：连上后开关反映真实态、拨开/拨关即生效、未连接置灰、失败回弹。

## 本会话改动（2026-06-19 · 「抓取订单」面板接通 inbox-service 自动抓开关，新增 inbox_service_client.py + ui_app）

「抓取订单」面板（操作员配置端）从骨架**接通到 automation 真实接口**。背景：automation 已补齐「定时自动抓 + 缓存/完整性」**服务核心**并**专门给 flower 留了开关接口**——`GET/PUT /inbox/scrape/control`（automation/AGENTS.md 明记「flower 唯一要写的开关」`{enabled, interval_seconds, scrape_from}`，「从 T 重抓」= PUT `restart_from`）。拓扑：**flower → inbox-service（写开关）→ 扩展（读开关去抓）**，inbox-service 是唯一中转，flower 不直连扩展。

- **新增 `inbox_service_client.py`**（标准库 urllib，无新依赖）：`health()`（探活，不可达回 None）、`get_scrape_control()`、`put_scrape_control(enabled?/interval_seconds?/restart_from?/clear_restart_from?)`（部分更新）。base url 默认 `127.0.0.1:8770`，可被 env `FLOWER_INBOX_HOST/PORT` 覆盖以对齐服务端。HTTP 错误转可读消息。**注意：这是 automation 的 inbox-service（live 本地服务），不是暂缓的 web `services/api`**。测试 `tests/test_inbox_service_client.py`（6 条，注入 fake transport，不打真网络）。
- **`_build_fetch_panel` 接通**（映射全由契约定，用户已确认「照此接」）：**开始/停止** = `PUT enabled` true/false（自动抓总开关）；**设置**弹窗 = 抓取间隔 `interval_seconds`(PUT) + 服务地址(本地存 `self._inbox_service_url`) + 收件夹(只读显示)；**定时锁** = 从某付款时间 `restart_from`（应用=PUT restart_from / 清空=clear_restart_from）；**刷新** = 重新探活+读开关。状态行 = 服务连接(/healthz) + 自动抓态(enabled/间隔/scrape_from) + 收件夹当前单。
- **开始/停止语义已变**（上一版骨架里是控制本地收件夹监听，用户拍板改成自动抓开关）。收件夹消费（轮询载单进编辑器）照常后台跑、不在面板按钮里（`_stop_inbox_poller` + `_start_inbox_poller` 幂等守卫仍在，供内部用）。
- HTTP 全走 `run_background`（不卡 UI）；**懒探**：不在构造时探网，进入操作员配置端（`_apply_view` role==config）或点「刷新」才查，省得每次起 App / 每个无头测试都连一次（`_scrape_probed` 标志；warnings 从 47 回落到 5）。
- 纯函数 `_format_scrape_status(connected, base_url, control, active_name)` 可测；`_render_fetch_status` 纯渲染（`getattr` 容错部分实例）。
- 测试：`test_format_scrape_status_reflects_connection_and_switch`（替换原 `_format_fetch_status` 测试）+ 客户端 6 条。

**跨仓待做（automation/扩展侧，非 flower）**：flower 这半**已接通**（写开关）。**仍缺**：① **扩展的「读开关 → 按 scrape_from/间隔 抓新单 → POST /inbox/scrape/diff 拿 worklist → 逐单抓 → POST /inbox/orders」自动循环**（automation/AGENTS.md 记为 ⬜扩展循环，属扩展 + Chrome 真机活）；② inbox-service 真·起服务（`uvicorn app.main:app --port 8770`）才有得连——**flower 面板服务未起时显示「未连接」**（已优雅处理，不崩）。

**验证**：`ruff`/`py_compile` clean（我的源文件）；全量 `pytest tests/` = **372 passed / 8 failed（同前预存 WIP，与本轮无关）/ 7 skip / 5 warnings**；**headless 冒烟过**（注入 fake client + 同步 run_background：进配置端懒探→连上→开始 PUT enabled=True、定时锁 PUT restart_from、清空 PUT clear、停止 enabled=False，按钮态随开关切）。**未真机点测**（需起 inbox-service + 在 App 操作员配置端验：连接态、开始/停止、设置改间隔、定时锁从某时间重抓、刷新）。

## 本会话改动（2026-06-18 · 功能区锁范围调整 + info 结果框只读接 AI，仅改 ui_app.py）

承 2026-06-17「锁只盖提示词配置、不盖画布/操作员日常」红线，本轮两处 UI 调整，**只改 `ui_app.py`**：
- **「图层」卡 + 「字体库 / 素材库」卡移出配置锁定区**：两卡 `_ctk_card(..., locked=True)` 改回不带 `locked`（标题不再带 🔒）；`_build_production_panel` 的「+ 文字图层 / + 图片图层」与 `_build_library_panel` 的「点击上传」**不再 `_register_lock`**。效果：配置锁定态下操作员仍可增删/编辑图层、上传字体/素材。（动态图层行本来就没入锁。）
- **info「字段」卡右侧结果框改只读 + 接 AI 解析回填（混合语义匹配）**：`_render_fields` 里 `result` Entry 改 `state="readonly"` 且**移出 `_register_lock`**（本就不可手输，`readonly` 不挡程序 `set()`，锁开合都保持只读）。`_apply_parse_result` 末尾调 `_apply_results_to_fields(result)`：对每个字段用 `_field_result_target(instruction)` 决定它指向 `ParseResult` 的哪个字段——**① 先认显式「填 <schema字段>」声明**（默认提示词写法，取「填」到首个冒号/句号前声明区，正则 `(?<!\w)key(?!\w)`，按 `_RESULT_FILL_PRIORITY = flower_name>text>font>month>flower` 取一）；**② 没写「填X」则按 `_RESULT_SEMANTIC_KEYWORDS` 中文/英文语义关键词回退**（`花/花名/出生花→flower_name`、`字体/font→font`、`刻字/文本/文字/名字→text`、`月份/月→month`，元组顺序即优先级）。命中后 `_result_attr_display(key, result)` 取值（None→空串；**`font` 特判成 `font{N}` 格式**，如 4→`font4`，对齐用户提示词「font1/font2/font3」写法）写进 `result_var` + `field_results`。
- **为什么是混合而非纯「填X」**：用户**实际持久化的字段提示词是自然语言中文**（field1`提取花朵的名称`、field2`顾客想要的字体编号…font1;font2,font3`、field3`顾客需要定制的文本内容…超过20字符输出error`），**不含「填X」**，纯「填X」全部落空→框空。混合匹配后用户实测路由正确：**field1→`flower_name`、field2→`font`(显示`font4`)、field3→`text`**。注意 field1 name 叫「刻字内容」但 instruction 是「提取花名」（name 是旧标签，按 instruction 路由才对，与用户预期一致）。
- **架构澄清（易误解）**：框里显示的值 **100% 来自 AI 返回的 `ParseResult`**（`text/flower_name/font/...`，固定 schema 见 `models.py:14`）；本地代码只做「路由」=读提示词文字决定哪个 AI 字段进哪个框，**不映射本地内容**。
- **背景**：之前 info 结果框是**可编辑且从不被 AI 填充**的占位控件（`field_results` 只在 `__init__` 设过、`_apply_parse_result` 只写旧字段 `name_var/month_var/font_var/flower_var`）；本轮接成「只读显示 AI 解析值」。这些框仍**不参与生成**（生成走旧字段 + 图层），纯展示给操作员确认。
- **已知风险（未真机端到端验）**：路由按「AI 把花名填进 `flower_name`、刻字文本填进 `text`」假设；若某些自定义提示词导致 AI 把值塞进了别的 schema 字段（如花名进了 `text`），框会错位/空。用户已口头确认上面三字段路由对，但**未核对真实 API 原始返回**。语义关键词表是启发式，新字段措辞刁钻可能误命中，按需在 `_RESULT_SEMANTIC_KEYWORDS` 调词/优先级。真正稳的解法仍是方案 C（解析器按字段 key 返回，跨 `gpt_parser/parse_pipeline/models`，本轮未做）。
- **验证**：`py_compile` 过；混合匹配逻辑**对用户真实持久化的 3 个提示词**独立脚本验过（field1→flower_name、field2→font→`font4`、field3→text）。`pytest tests/test_ui_app.py` = **65 过 / 8 失**，8 失全是**本轮之前就存在**的失败：6× 预览画板 zoom/pan/ruler（根因是工作区既有 WIP `PREVIEW_ZOOM_STEP 1.25→0.05`，非本轮）、`test_text_case_toggle...`（`self.case_button` 未创建，WIP 改名未完）、`test_field_instructions_drive_ai_system_prompt`（本文件上方 2026-06-18 段已记为「旧测试 vs 现默认字段」非本轮引入）。**无法 git stash 复验基线**——分支 test 与 ui_app.py 是 WIP 纠缠（stash 单文件即触发 ImportError）。**未真机点测**（需用户在 App 里验：①锁定后图层/库卡仍可操作；②解析后 info1/2/3 框显示对应 AI 值[字体为 `font4`]、不可编辑）。

## 本会话改动（2026-06-18 · 「文件名」框接线：导出按订单号/手填名命名，仅改 ui_app.py + test）

「输出设置」卡里的「文件名」框（`filename_template_var`）**此前是死控件**——只在 `__init__`(851) 定义 + `_build_output_settings_panel`(1838) 绑定，**任何导出逻辑都不读它**；导出名一直只取「输出目录」`output_var` 路径的 stem，故用户填了不生效。本轮按用户拍板（语义：**纯文本所见即所得**；**留空→自动用订单号**）接线，**只动 `ui_app.py` + `tests/test_ui_app.py`**：
- 新增模块级 `sanitize_filename_stem(name)`：去 Windows 非法字符 `<>:"/\|?*`+控制符、首尾空格/点，保留设备名(CON/NUL/COM1…)前缀 `_` 避让，清空→`""`。
- 新增 `BirthFlowerApp._resolve_output_basename(base_output_path)`：优先级回退 **①「文件名」框（清洗后） → ②订单号（`current_order_number`，回退 `_inbox_active.stem`=inbox JSON 文件名） → ③`output_var` 原 stem（旧行为，名字永不为空）**。
- `confirm_and_generate`：`target_path` 由 `output_path_for_format(base,fmt)` 改 `base_output_path.with_name(f"{stem}.{fmt}")`（保留目录、不走 with_suffix，避免主干含点被截断）；`output_path_for_format` 函数保留（仍有单测）。
- 测试：`test_sanitize_filename_stem_*` + `test_resolve_output_basename_priority`（用 `SimpleNamespace` 当 fake self，免构整套 headless UI）共 2 条新增全过。
- 验证：`py_compile` 过；`pytest tests/test_ui_app.py tests/test_config_store.py` = **76 过 / 7 失**，7 失全是**本轮之前就存在**的 headless 画板/`case_button`/初始化菜单断言（已 `git stash` 基线复验确认与本轮无关）。**未真机点测**（需用户在 App 里验：填名/留空两种导出名）。

**仍未做（本轮只接文件名、没接 metadata）**：`desktop_export.py:119` 的 `metadata.orderId` 仍硬编码 `""`——「按订单号写 metadata」与本轮「按订单号命名文件」是两件事，后者已做、前者待接。
**~~已知 foot-gun（未处理）~~ → 已消除（2026-06-18，见下「收件夹订单号接线」会话）**：原问题=inbox 放行下一单时手填的文件名会沿用。现 `_auto_load_order` **每单载入都把 `filename_template_var` 设为当前 order_id**，旧值被覆盖，foot-gun 不再存在。

## 本会话改动（2026-06-18 · 收件夹订单号接线：order_id 进订单信息首行 + 文件名框）

需求：店小秘抓单 JSON（`outputs/inbox/`，形如 `{order_id}.json`，含 `order_id`+`remark`）自动载入时，除已实现的 `remark`→订单信息框外，**订单号也要进订单信息框第 1 行（订单号在前、备注在后），并写进「文件名」框**。
- `order_importer.py`：新增 `OrderImport(order_id, remark)` NamedTuple + `load_order_from_file()`（**同时取 order_id 与 remark**，JSON/CSV 按 `ORDER_ID_KEYS`/`REMARK_KEYS` 找，纯文本→order_id 空串）；`load_order_remark_from_file()` 保留并改为 `load_order_from_file().remark`（向后兼容，手动导入路径不变）。`_find_remark` 泛化为 `_find_value(value, keys)`。
- `ui_app.py` `_auto_load_order`：改用 `load_order_from_file`；订单信息框 = `f"{order_id}\n{remark}"`（订单号置顶，对齐解析器「订单块首行=订单号」约定），并 `self.filename_template_var.set(order_id)`。手动「导入备注」`import_remark_file` **未动**（仍走 `load_order_remark_from_file`，处理任意 txt/csv）。
- 测试：`test_order_importer.py` +2（JSON 取 order_id 而非 spec、txt 空 order_id）；`test_inbox_poller.py` fake app 加 `filename_template_var`、断言改「订单号\n备注」+ 文件名框=order_id。`pytest tests/ --ignore=test_document_vector_export.py` = **344 过 / 8 失 / 7 skip**，8 失全是本轮之前就有的 headless GUI 失败（与本轮无关）。**未真机点测**（需用户在 App 里验：自动载单后订单信息框首行=订单号、文件名框=订单号）。

## 本会话改动（2026-06-18 · 画布内联编辑：从中心展开 + 文本框随墨迹实时变动、不封顶）

**需求**：双击文本图层进画布内联编辑时，①内容从**文本框中心**展开（避免字号过大被编辑器窗口裁切显示不全）；②编辑过程中**固定字号，文本框随字体墨迹实时变大/变小**。用户拍板：顶到画布安全区也**不封顶、不缩字号**（框可越界，仅给非阻塞提示）；编辑器居中精度=**窗口锚框中心 + 文字水平居中**即可（不做多行精确垂直居中）。

**⚠️ 踩到的现实矛盾（已订正）**：动手时发现**工作区 `ui_app.py` 被回退成旧版**，下文 §「文本字号=真实大小」描述的 `_resize_text_box_to_font` 方法**整个不存在**，连 `from text_layout import text_box_size_for_font/SAFE_MARGIN_*/ENDING_HEART_ADVANCE_RATIO` 都没 import；而 `text_layout.py`（`text_box_size_for_font` 等）与本文档 §53-58 仍是新版 → 文档/排版层比工作区 ui_app 新。

**本会话改了 `ui_app.py`**（仅此一文件 + 两处测试）：
- **补回** `text_layout` 的 4 个导入 + 新增模块常量 `UNBOUNDED_BOX_SIZE=1e7`。
- **重建** `_resize_text_box_to_font(layer, *, clamp_to_safe_area=True)`：按字号+墨迹反推框（`text_box_size_for_font`）、同步 `text_box_width/height` 与 `width/height`、以原框中心为锚重定位防跳。`clamp_to_safe_area=True`(默认)=封顶画布安全区+返回 clamped；`=False`(内联编辑)=给 `UNBOUNDED_BOX_SIZE` 上限→永不封顶、字号守恒，返回「是否越出安全区」仅作提示。
- **内联编辑接线**：`_on_inline_text_modified` 每次输入→`_resize_text_box_to_font(layer, clamp_to_safe_area=False)`→`_place_inline_text_editor()`，越界则 status 提示「文本框已超出画布安全区，雕刻时可能被裁切」。`_place_inline_text_editor` 改为**锚框中心**(`anchor="center"`)+窗口贴合实时框(去掉 160/44 固定下限、留≥1 字高宽)+`tk.Text` 加 `center_layout` tag(`justify="center"`)水平居中。
- **Esc 取消还原框几何**：`_start_inline_text_edit` 快照 `inline_text_original_box`（x/y/width/height/text_box_w/h），`_cancel_inline_text_edit` 还原，`_destroy` 清空（编辑中框会随墨迹变动过，取消须连框一起回退）。
- 测试：`test_text_layout.py` +1（同字号、文字变长→框变宽）；`test_ui_app.py` +2（用「假 self+解绑方法」headless 测 resize：随墨迹变宽+中心不动；不封顶越界 vs 封顶到安全区）。**3 个新测试 + 16 个原 text_layout 全过**；`py_compile` 通过。`test_ui_app.py` 余 8-9 个失败=**预存环境性**（headless Tk「main thread is not in main loop」线程污染、缺 `pydantic`、控制台 GBK 对 CJK 乱码），与本轮无关（如 glyph_menu 单独跑即过）。

**§58 接线已按用户决定恢复**（回退后曾整体丢失）：用户拍板「**功能区图层属性面板**跟随字号/框变化；**左上角菜单栏全局设置不覆盖**」。本会话据此把 `_resize_text_box_to_font(layer)`（默认 `clamp_to_safe_area=True`=封顶画布安全区+告警）接回：
- `_apply_text_layer_properties`（图层属性面板改字号即生效、框随字号长大，clamped 时 status 提示「字号过大：已按画布安全区可雕刻范围封顶」）；
- `_add_text_layer_from_fields`（新建文字图层即按字号定框）。
- **刻意不接**：菜单栏全局设置（`layout_vars`，仅初始化新图层、不覆盖现有，护栏 `test_global_layout_defaults_only_initialize_new_layers`）；手动「宽/高」走 `_apply_layer_production`（生产参数，最后操作生效，不被字号覆盖）；字体下拉 `_add_selected_font_to_canvas`（只换 font_path、不重排，留作后续——换字体后需在面板再点应用才会按新字体重排）。

**已知 / 未做（不许当已完成）**：
- ① 编辑器垂直方向为近似居中（`tk.Text` 内容顶对齐于「锚中心、贴框高」的窗口），按用户决定未做多行精确垂直居中。
- ② 字体下拉换字体不会即时重排框（见上「刻意不接」），需面板再点一次「应用文本属性」。
- ③ **未真机点测**：需在 App 验证——（内联）双击打字框随墨迹实时变大/变小、内容居中不被裁、超大字号给越界提示、Esc 连框还原；（面板）改字号文字实时变大/变小且不消失、超大封顶提示；新建图层即按字号定框；导出尺寸与预览一致。

## 本会话改动（2026-06-18 · 文本字号=真实大小、文本框随字号长大）

**修的 bug**：「文本属性」改字号在编辑框/预览看不见。根因=`font_size` 原本只当**上限 cap**，真实字号由「自适应铺满文本框」算出（[text_layout.py](text_layout.py) `_fit_name_layout`/`_fit_name_font_size`，`text_renderer.py:112` 注释明示），所以改大无效、改小到一定程度墨迹塌成透明（`text_renderer.py` 返回透明图层）。
- 用户拍板：**字号=真实大小、所见即所得、文本框随字号长大**；断行=**宽高都长 + 保留自动断行（≤NAME_MAX_LINES=2）**；超出固定画布(1732×1280)安全区=**封顶 + 警告**。
- 方案（**`fit_text_box` 本体不动**，护栏零冲击）：`text_layout.py` 新增 `text_box_size_for_font(text, font_size, font_path, *, max_width, max_height, ending_advance_ratio, personalization_type)`——与自适应比例（NAME_HEIGHT_RATIO=0.62 / NAME_BLOCK_HEIGHT_RATIO=0.86 / NAME_SIDE_PAD_RATIO）**互逆**反推出文本框 (w,h,clamped)，框放大 `_BOX_FONT_SLACK=1.04` 使 `fit_text_box(box, font_size_cap=fs)` 渲染真实字号**恰等于 fs**（cap 精确封顶）；单行墨迹超 max_width 自动均衡断 2 行；任一维超上限则封顶到画布安全区并置 clamped。
- `ui_app.py`：新增 `_resize_text_box_to_font(layer)`（按字号反推框 + 同步 `text_box_width/height` 与 `width/height` + 以中心为锚重定位防跳 + 返回 clamped）；在 `_apply_text_layer_properties`（改字号即生效，clamped 时 status 提示「已按画布安全区可雕刻范围封顶」）与 `_add_text_layer_from_fields`（新建即按字号定框）调用。max=画布 − 2×SAFE_MARGIN(X120/Y70)=1492×1140。预览/导出共读 `text_box_width/height`，所见即所得。
- 测试：`test_text_layout.py` +4（**round-trip 真实字号==目标字号** fs∈{60,120,240,360}、随字号生长、超宽断行、超界封顶），全过。`pytest tests/ --ignore=test_document_vector_export.py` = **348 过 / 8 失 / 7 skip**，8 失同前（headless GUI，与本轮无关）；ruff clean。
- **已知/未做**：① 祝福语(message)路径字号本就硬封顶 160（`_fit_message_box`），helper 对 message 仅按行高堆框、未深做；② 重定位按 scale=1 近似（文本图层默认 scale 1）；③ **未真机点测**（需用户在 App 验：改字号文字实时变大/变小且不消失、超大字号封顶提示、导出尺寸与预览一致）。

## 本会话改动（2026-06-18 · Font 4 末尾改用「独立实心爱心符号」替换 PUA 合体字形）

**背景/动机**：旧逻辑里 Font 4 的“末尾爱心”是把名字**最后一个字母替换成字体 PUA 区（U+E034–E04D）的「字母+爱心」合体字形**（`glyph_service.apply_automatic_glyph_rules` 的 end_char_rules）。用户要求改成：末行末尾**追加一颗独立实心爱心**（用户提供的固定手绘形状），行内紧贴末字右侧、基线对齐、**大小随字号自适应**；**只 Font 4、自动加**；三端（PNG 预览 / SVG / DXF）一致，DXF 为闭合矢量让 EzCad 自填实心。设计/决策见 `~/.claude/plans/jazzy-twirling-thompson.md`。

**关键事实**：爱心源 SVG 的 path 全是 SVG 圆弧 `a` 命令，而矢量端 `_parse_path_objects` 只认 `M/L/H/V/Q/C/Z`（圆弧/`S`/`T` 都会抛 `SVG_UNSUPPORTED_PATH_COMMAND`）。故 author-time 用 `fontTools` 归一化成全贝塞尔 `M/C/Q/Z`、零基化，固化成常量（重生成脚本 `tmp_out/gen_heart.py`）。渲染/导出对“爱心”无字体感知——由 `TextLayer.ending_heart` 布尔标志驱动。

**改了哪些文件 / 为什么**：
- **新增** `heart_symbol.py`（几何唯一真源：`HEART_PATH_D`/`HEART_VIEW_W/H`/`HEART_ASPECT` + `heart_svg_markup(fill)` + `heart_path_d_transformed(x,y,scale)`）；**新增** `assets/symbols/heart.svg`（归档原始源文件）。
- `glyph_service.py`：加 `font_uses_symbol_heart(font_id)`（暂只 `Font 4`）；`apply_automatic_glyph_rules` 对 Font 4 **跳过 end_char 替换**、返回**新增第 5 个布尔** `wants_ending_heart`。
- `models.py`：`TextLayer` 加 `ending_heart: bool = False`。
- `text_layout.py`：常量 `ENDING_HEART_SIZE_RATIO=0.62`/`GAP_RATIO=0.12`/`ADVANCE_RATIO`；`place_ending_heart(fit, font_path)`（单一大脑算 box 本地 (x,y,scale)）；`fit_text_box(..., ending_advance_ratio=0.0)` 在**名字分支**预留爱心推进量（名字+爱心一起 contain-fit、末行整体居中）。**ratio=0 与原逻辑字节一致**（非 Font 4 零回归）。
- `text_renderer.py`：预览端把爱心 cairosvg 栅格化后**缀到最后一行图像右侧**（走现有 compose/居中，单行/多行都与导出末行整体居中一致）；cairosvg 失败只告警不崩。
- `desktop_export.py`：`_text_layer` 把爱心烘成 `textLayout.endingHeart={pathData(已 scale+translate 的 box 本地闭合 d), x,y,scale,...}`（不带爱心则**整 key 省略**，其它文字 schema 零变化）。
- `services/api/app/domain/exports/{svg,dxf}.py`：消费 `endingHeart` —— svg 追加一条实心 `<path>`；dxf 经 `_parse_path_objects` 出**闭合 SPLINE/POLYLINE，无 TEXT/无 HATCH**，EzCad 自填实心。
- 调用方：`ui_app._apply_auto_glyph_rules_to_layer` 解 5 元组并置 `layer.ending_heart`（非该字体清零）；`order_batch.py:108`（校验，丢弃结果）解包加宽。

**验证**：全量 `pytest` = **424 passed / 7 failed（全部预存，与本次无关）/ 1 skipped**；ruff clean。7 个失败均为 **2026-06-18 未提交的预览交互重做**遗留（`PREVIEW_ZOOM_STEP` 1.25→0.05、删中键/Shift+Alt 平移→`<B2-Motion>`/zoom/ruler/pan 测试未更新）+ 文档已记的 `case_button` 死代码；`git diff HEAD -- ui_app.py` 可见这些删除非本次所为。新增护栏：`tests/test_heart_symbol.py`（**守住“无圆弧命令”地基**）、`tests/test_ending_heart_vector.py`（svg 多 1 条实心 path / dxf 无 TEXT 无 HATCH、爱心闭合）、`tests/test_text_layout.py`（place_ending_heart + 预留不溢出 + ratio=0 字节一致）、`tests/test_text_wysiwyg_consistency.py`（预览 vs 矢量爱心右缘一致）、`tests/test_glyph_application.py`（Font 4 不再写 PUA、wants_heart=True）。**已视觉核对**：预览（Ammy/Lily/Emma/Sophia/Anna Marie）+ SVG 导出渲染与预览逐像素一致（`tmp_out/heart_preview_sheet.png`、`heart_export_svg.png`）。

**已知未解决 / 待办**：
- **真机手测仍待用户**：在 App 里把字体选成 Font 4 看预览爱心观感、导 DXF 进 EzCad 确认爱心闭合可填实心且位置紧贴字末、同名导 SVG/PNG 三端一致。
- **尺寸/间距是目测初值**（`text_layout.ENDING_HEART_SIZE_RATIO`/`ENDING_HEART_GAP_RATIO`），如真机偏大/偏小改这两个常量即可（一处改，三端同步）。
- 迁移：旧会话内已写入 PUA override 的 Font 4 图层，要重新套用字体规则（切字体/重解析）才会改成独立爱心；无磁盘文档持久化，重启即清。
- Font 4 = `BirthMonth flowers/AdoraBella.ttf`（字体编号 4；该家族现仅此 1 个 `.ttf`）。

### 追加（2026-06-18 · 字体编号映射订正，本次 `asset_resolver` 改动）

旧规则「每家族 2 个文件按大小分常规/带字形版」已废弃——用户清理后**每家族仅 1 个有效 `.ttf`**（`Malovely Script.ttf`、`AdoraBella.ttf`，旧 `.otf` 已删）。原 `asset_resolver._ordered_font_paths` 仍按「每家族 2 文件」编号，导致**只生成字体 1、3，字体 2/4 丢失**（`order_batch`/UI 按 `asset.index` 选字体会匹配失败）。

- **改法**：`_ordered_font_paths` 改为**同一文件产出常规(基准号)+带末尾装饰(基准+1)两个编号**：`Malovely Script.ttf`→字体 1/2，`AdoraBella.ttf`→字体 3/4。`scan_font_assets` 单文件分支也走同一逻辑。`has_ending_glyphs={2,4}` 不变。
- **末尾装饰来源（既有 `glyph_service` 逻辑已对，未动）**：字体 2=字体内 PUA 末尾合体字形（`glyph_rules` end_char_rules E068–E081）；字体 4=独立爱心 SVG 矢量（`SYMBOL_HEART_FONTS`，跳过字体字形，即上文本块逻辑）。
- **key 冲突非本次引入**：Font 1/2 同家族 → `material_library._scan_font_entries` 同 key，旧「4 文件」时代即如此；主选字体走 `resolve_font_by_tags(index=)` 按 index 匹配不受影响，故 `material_library` 未动。
- **验证**：`tests/test_asset_resolver.py` 已同步新规则（9 passed）；`test_material_library`/`test_order_catalog`/`test_ending_heart_vector`/`test_glyph_application` 全过。文档 `docs/ai-recognition-static-mapping.md §5.1/§5.2` 已订正。
- **文案 + 提示词同步订正（2026-06-18，已完成）**：
  - `ui_app.format_font_asset_label` 末尾后缀由「含字形/普通」两态改为「常规 / 末尾字形 / 末尾爱心」三态，用 `glyph_service.font_uses_symbol_heart(design)` 区分 Font 4（独立爱心 SVG，无字形映射）与 Font 2（字体内末尾字形）；测试 `tests/test_ui_app.py::test_format_font_asset_label_distinguishes_ending_decoration` 三态全锁。
  - 前台字体字段 `ui_app._default_field_defs` field3（=AI 提示词的字体规则唯一来源）同款订正：`4=AdoraBella 带结尾字形` → `4=AdoraBella 末尾爱心（非字体字形）`，并补「字体名/外观 → 编号」语义（让 AI 把「Malovely/带爱心」口语描述映射到编号）。
  - `gpt_parser` 两处 schema `font maximum 8→4` + 两处 `_bounded_int(font,1,4)`：**AI 路径**字体收紧到实际素材 1–4（越界裁 null）。注意**本地/legacy 解析仍留 1–8**（`parser.py._parse_font`/`_font_number_from_design`，给后期加字体留位；`test_parse_pipeline.py:43` 用「Font 8」走本地路径仍断言 font==8）——AI 严于本地是有意的。
  - 文档 `docs/ai-recognition-static-mapping.md §5.1/§5.2` 已同步。

### 追加（2026-06-18 · 全局 AI 对齐：编排层停用本地解析规则）

承接「多订单 `parse_orders_auto` 已 AI-only」，本次把**单订单 `parse_pipeline._resolve_order_remark` 也改成 AI-only**，至此本地解析在编排层全局停用：

- **改法**：`_resolve_order_remark` 始终走 GPT（不再看「AI 优先」开关），AI 异常直接上抛、AI 不完整返回低置信 + `["AI解析不完整：…"]`，**不回退本地**；旧的 prefer-AI 门控 + 本地回退、以及 `from local_order_parser import parse_order_remark_local` 都**注释保留可恢复**。`_local_orders/split_order_blocks/_should_prefer_ai/_combined_failure/_local_failure` 留作存档（`split_order_blocks` 仍被 `test_orders_multi` 直接测）。
- **不删本地模块**：`local_order_parser.py`/`parser.py`/`birth_flower_parser.py` 仍在、`test_local_order_parser.py` 仍跑（直接测模块）；只是编排层不再调用。
- **测试**：`tests/test_parse_pipeline.py` 里 7 个覆盖「本地/回退」的旧用例改 `@pytest.mark.skip(reason=本地停用…)` 保留可恢复，新增 3 个 AI-only 用例（始终调 GPT / 不完整→低置信不回退 / 异常上抛）；`tests/test_order_catalog.py` 两处 `local_parser=` 改 `gpt_parser=`。全量（除并发重构的 `test_ui_app.py`）**285 passed / 7 skipped**。
- **UI 收尾（已做）**：「AI 优先」开关此前已被换成 AI 识别页一行只读说明；本次按用户要求把该说明也**注释移除**（`ui_app._build_ai_settings_tab` 内，row 0 空行自动塌缩，保留可恢复）。`build_ai_parse_config` 的 `prefer_ai` 恒为 True。
- 文档 `docs/ai-recognition-static-mapping.md §0` 已加停用说明。

## 本会话改动（2026-06-18 · AI 提示词接进 API + 多订单识别接线）

承接用户需求「现在的 AI 提示词规则放在了前台，请把完善的提示词写好，使通过 API 提取正确参数传入后端」。**两个核对到的硬事实**：①前台 `extraction_prompt/background_prompt` 只存配置、**从不被 parse_pipeline/gpt_parser 读取**（真正发出去的是 `gpt_parser` 写死的系统提示词）；②旧 schema 一次只出**单条** `{text,month,font,flower}`，但真实订单一次粘贴含**多笔**（每块第一行=订单号 + 出生花/字体/Personalization[/GiftMessage]）。本轮把两条都接通。

- **模型**（`models.py`）：`ParseResult` 加 `order_number/quantity/gift_message`；`AIParseConfig` 加 `system_prompt/background_prompt`（均带默认值，旧调用零影响）。
- **解析层**（`gpt_parser.py`，**新增、不动旧单订单路径**）：`DEFAULT_EXTRACTION_PROMPT`（完善的提取提示词，**内置「月→花名→序号」「字体编号」对照表**，地面真相来自 `asset_resolver`）；`ORDER_ITEM_SCHEMA/ORDERS_SCHEMA`（多订单 strict json_schema）；`build_orders_system_prompt`（前台提取词为空→回落默认；背景词作【附加背景】附加）；`parse_orders_with_gpt`（OpenAI Responses + DeepSeek，返回 `list[ParseResult]`）；`parse_orders_payload`/`_parse_order_item`（越界数字裁 None、字符串去白、容错单条对象）。
- **管线**（`parse_pipeline.py`，新增）：`parse_orders_auto(remark,*,ai_config,bundle,...)`→`list[ParseResult]`。**全局只用 AI 解析（用户 2026-06-18 拍板）**：始终调多订单 GPT、不受「AI 优先」开关影响，**AI 失败直接抛错由 UI 提示、不再回退本地**。本地兜底（`_local_orders`/`split_order_blocks`/`_should_prefer_ai` 门控）**已注释停用、保留可恢复**（其单测仍在，函数仍可调）。传 bundle 时每条富化落素材/字体 key。`_call_orders_gpt` 把 `ai_config.system_prompt/background_prompt` 透传给 GPT（=接线关键）。
  - 注：legacy 单订单路径 `parse_order_remark_auto`/`_resolve_order_remark`（批量/旧测试用，桌面已不走）**未动**，仍保留本地规则。`split_order_blocks` 等本地兜底代码与单测保留，恢复只需取消 `parse_orders_auto` 里的注释。
- **前台**（`ui_app.py`）：`_current_ai_config` 注入「当前产品 extraction_prompt（空→默认）+ background_prompt」到 `AIParseConfig` → **提示词真正发给 API**；`parse_remark` 改调 `parse_orders_auto`；新增 `_apply_parsed_orders`（存队列、载入第 1 笔、状态「识别到 N 笔」）+ 队列导航 `‹上一笔/下一笔›`（单笔隐藏）；`_apply_parse_result` 记 `current_order_number`；新增**「提取提示词（发给 API）」管理员锁卡**（`_build_extract_prompt_panel`，seed=默认提示词，FocusOut 存盘；与默认一致则存空串=用默认）；`_persist_prompts/_load_prompts_into_widgets/_show_generated_prompt` 改为含提取词、预览=真实发送内容。**已移除「AI 优先」勾选框**（`ai_prefer_var` 连同 `_build_ai_settings_tab` 里的 Checkbutton 删除，改为一行只读说明；`_settings_ai_profile` 恒传 `prefer_ai=True`）——解析全局走 AI、开关已无意义。
- **测试**：新增 `tests/test_orders_multi.py`(12) 全过（schema/payload 校验、提示词回落+背景附加、OpenAI 路径 fake http 验 schema+prompt、自定义提示词、块切分+数量后缀、AI/本地两路 + 透传 system/background_prompt）；改 `tests/test_ui_app.py::test_parse_remark_reads_current_text_widget_content`（patch `parse_orders_auto`、返回列表）。全量 **424 过 / 7 失**，7 失全是**本轮之前就存在**的画板交互（`_on_canvas_pan_press`/滚轮 1.05vs1.25/刻度 5vs10/`<B2-Motion>`，皆 2026-06-18 画板未提交改动遗留的旧断言）+ `case_button` 死代码，与本轮无关。ruff clean。

**已知未做 / 待用户**：
- **order_number 部分接好**：「按订单号生成文件名」✅ **已接**（2026-06-18，见顶部「『文件名』框接线」会话，`_resolve_output_basename`）；但 **`desktop_export.py:119` 的 `metadata.orderId` 仍硬编码 `""` 未接**（写 metadata 与命名文件是两件事，后者已做、前者待接）。
- **多订单仍是「逐笔队列」不是一键批量**：操作员点「下一笔」逐笔确认+生成；一键批量生成 N 笔属后续。
- **真机未点测**：Tkinter 字段编辑/队列导航交互、真 key 下 GPT 多订单实际返回，需用户在 App 里验（改完 Python 务必关掉 App 重开）。

### 追加（同会话 · 用户拍板：提示词规则全部移到前台可编辑的「字段+背景」区，删「提取提示词」框）
用户澄清原意：提示词规则要**全在前台可编辑区域**（即「字段」卡的提取规则 + 背景提示词），不是单独的提示词框、更不是写死在 `gpt_parser`。本轮重构：
- **删** `_build_extract_prompt_panel` / `extract_prompt_text` / `_current_extraction_prompt`（连同卡片）。
- **gpt_parser**：`DEFAULT_EXTRACTION_PROMPT`（含月→花表/字体表的整段写死提示词）**删除**，拆成 `ORDERS_PROMPT_SCAFFOLD`（纯 I/O 契约：订单块格式 + 输出 JSON 字段，含 `{rules}` 占位）+ 极简兜底 `DEFAULT_EXTRACTION_RULES`。`build_orders_system_prompt(rules, background)` 改为**把 rules 填进脚手架**（rules 来自前台字段）。**业务规则（对照表/字体编号）不再写死在 gpt_parser**。
  - ⚠️ **已被 2026-06-18 决策取代（见顶部）**：`ORDERS_PROMPT_SCAFFOLD` 与 `DEFAULT_EXTRACTION_RULES` 已**彻底删除**，`build_orders_system_prompt` 现在**只拼前台内容、不再有脚手架**。本行保留仅作历史。
- **ui_app**：模块级 `_default_field_defs()` 持有完整默认规则（月→花对照表/字体编号表写在字段 instruction 里，前台可改）；`_assemble_field_rules()` 把各字段 `名称（类型）：规则` 拼成【提取规则】正文；`_current_ai_config` 的 `system_prompt = _assemble_field_rules()`（**提示词唯一规则来源=前台字段**）、`background_prompt=背景框`。
- **持久化**：字段定义按产品序列化成 JSON 存 `product.extraction_prompt`（`_serialize_field_defs`/`_load_field_defs_into_self`，非 JSON/空→回落默认，向后兼容旧文本）；字段 instruction 编辑器由单行 Entry 改**多行 CTkTextbox**（`<KeyRelease>` 同步进 `inst_var`、`<FocusOut>`/增删 `_on_field_changed` 落盘）。`_show_generated_prompt` 预览=真实发送内容（`build_orders_system_prompt(字段规则,背景)`+订单）。
- 卡片顺序：订单 → **字段（提取规则）** → 背景提示词 → 图层 → 库 → 生成预览 → 输出。
- **测试**：`test_orders_multi.py` 改 3 处（`DEFAULT_EXTRACTION_PROMPT`→`DEFAULT_EXTRACTION_RULES`、断言改「脚手架含 rules」）；`test_ui_app.py` 加 `test_field_instructions_drive_ai_system_prompt`（字段→system_prompt、编辑即生效）+ `test_field_defs_persist_and_reload`（序列化往返）。全量 **426 过 / 7 失**（7 失同前，皆画板交互/`case_button` 预存，与本轮无关）；ruff clean。
- 注：原「mock 字段卡 Info1/2/3」即此「字段」卡——现已成为**真正驱动 API 的提示词规则区**（不再是 mock，名称改 刻字内容/出生花/字体）；字段的 `result_var` 显示值仍是占位（P3 接 GPT 回填真实每字段结果）。

### 追加（同会话 · 规则适配：无效空格 + 可选字段不报警）
用户反馈解析弹出两条 warning（GiftMessage 缺失、Personalization 多余空格）。本轮按「连续无效空格忽略、不必要字段忽略」适配：
- **刻字文本去多余空格**（确定性兜底，无视模型是否照做）：`gpt_parser._parse_order_item` 把 `text` 由 `.strip()` 改 `" ".join(...split())` —— 去首尾 + 中间连续多空格/换行合并成单空格（`#1 Mom␣␣␣␣␣␣Kicking` → `#1 Mom Kicking`）。护栏 `test_parse_orders_payload_collapses_internal_spaces_in_text`。
- **可选字段缺失不报警**：`ORDERS_PROMPT_SCAFFOLD` 明确「warnings 只对必填 text/month/flower/font 缺失或不确定写；gift_message/quantity 等可选字段为空、或多余空格等不影响识别/生产的情况，一律不写 warning」。
- **前台字段同步**：`_default_field_defs` 的「刻字内容」instruction 加「中间连续多空格合并成一个、不为此写 warning」。
- 健壮性：空格合并 + 可选字段不报警分别落在 `_parse_order_item`（代码）和 scaffold（始终生效），**即便用户已持久化过旧字段规则也照样生效**（持久化只覆盖字段 instruction 文本，不覆盖 scaffold 与代码兜底）。全量 **427 过 / 7 失**（同前预存），ruff clean。

## 本会话改动（2026-06-18 · 画板交互：滚轮缩放修复 + 平移改左键，仅改 ui_app.py）

预览画板 `preview_canvas` 三处交互调整：
1. **滚轮只缩放，且改线性 5% 步进**。`PREVIEW_ZOOM_STEP` 由乘除 `1.25` 改为**加减 `0.05`**（`_on_canvas_mousewheel` 里 `new_zoom = old_zoom + direction * STEP`），上滚 +5%、下滚 -5%，刻度整齐（100→105→110）。乘除步进做不到等百分点（`1.10×1.05≠1.15`、`÷1.05=-4.76%`），故改线性。
2. **删掉滚轮的横向平移分支**（原 Shift/Alt+滚轮平移）。该分支靠 `event.state` 位判断修饰键，在 Windows 上**误判后会 `return "break"` 把缩放整段吞掉**——这是「滚轮变左右平移、缩放失效」的根因。连带删除死代码 `_wheel_horizontal_pan_requested`、常量 `PREVIEW_WHEEL_PAN_STEP`。
3. **平移从中键改到左键空白处拖动**。`_on_canvas_press`：命中图层→移动/缩放图层（不变）；**空白处→ `_drag_mode="pan"`** 左键拖动平移视图。**移除中键（Button-2）平移**绑定与 `_on_canvas_pan_press` 方法（画布上 Button-2 不再绑定；图层列表/控件/内联编辑器的 Button-2 右键菜单与此无关，保留）。平移落地仍走 `_on_canvas_drag` 的 `pan` 分支 → `_pan_preview_by`，释放复位光标。

红线：以上全是**视图层**变换，不动 Document/导出坐标。`python -c ast.parse` 语法校验通过；**未真机点测**（Tkinter 交互需用户在 App 里验滚轮缩放方向/左键平移/中键已失效）。

**4. 刻度尺密度**：`_ruler_interval_mm` 的 `target_px` 由 72→**40**（主刻度目标屏幕间距，越小越密）。原逻辑本就随 zoom 自适应（`px_per_mm` 越小选越大 mm 间隔），用户反馈「缩小看全板时刻度太稀」——本 App **zoom=1.0 即适配铺满(看全板)**，调小 target 后该区间主刻度翻倍变密（800mm 板：fit 时 100→50mm、0.5x 时 200→100mm），放大区(2x+)本就够细、间隔不变，方向不反转。`minor=major/5` 未动。

## 本会话改动（2026-06-16 · 功能区「字段引擎」第 10 节 A+B：布局重排 + 图层变真实，仅改 ui_app.py）

按 `docs/superpowers/plans/2026-06-16-field-engine-redesign.md` 第 10 节顺序做完 **A（布局重排）+ B（图层变真实，B1–B6 全做）**；后端 P3 未碰。详细进度记在该设计文档 §9.6（权威 handoff）。
- **A**：`_build_function_panel` 卡片重排（订单→背景词→字段→图层→库→输出→生成）；字段两段合并成 `_build_fields_panel`/`_render_fields`（一字段一卡，删旧四个 fields 方法）；配置锁真禁用（`self._locked_widgets`+`_register_lock`/`_prune_locked`+`_ctk_card(locked=True)` 卡头🔒，订单备注框不入锁）；删静态 `_layer_demo_row/_menu`。
- **B**：`_render_layers()` **增量**渲染（复用存活行、只增删变化行、原位更新）——**关键**：反复 destroy/recreate `CTkOptionMenu` 会在 customtkinter `AppearanceModeTracker` 留悬挂引用而崩溃，故必须增量 + `_refresh_layers_panel` 用 `_schedule_render_layers()`（after_idle 去重，不在画布右键/重绘同步流程里现场建控件）。内容字段绑定走 UI 态 `self._layer_field_bind`（未进模型，留 P3）；逐层库/素材/字体下拉接 `active_bundle` 写回图层，**保留隐藏全局 combo 作 fallback**（parse/扫描联动不断）；拖柄拖序 + `_layer_menu` 右键真菜单（位置尺寸对话框/对齐/显隐锁/调层级/删除，复用既有 `_apply_layer_production`/`_delete_selected_layer`/`_move_selected_layer` 等）。
- **验证**：`.\.venv-win\Scripts\python.exe -m py_compile ui_app.py` 过；渲染冒烟过；`pytest` **388 过 / 2 失**。2 失**与本轮无关、本轮之前就存在**：`test_text_case_*`（旧 `_cycle_text_case`/`case_button` 死代码，prior P1 已删按钮、方法/测试遗留）、`test_birth_flower_app_initializes_*`（菜单栏「设置」label 断言，菜单栏代码本轮未碰）。
- **遗留/待真机**：字段↔图层绑定仅 UI 态（P3 进 `content_field`）；hidden combo 未删；锁仅 disable 无密码（P4）；解析仍旧固定链、字段结果 mock（P3）。手测见设计文档 §10「验证」。
- **追加（同会话）：图层行精简为单行 + 右键整行弹菜单**（用户反馈）。行 = `拖柄 + 状态标 + 库下拉 + 素材/字体下拉(+字号)`；删类型图标/内容文案/⋮ 按钮。状态标：正常空、隐藏🚫、锁定🔒、**空文本图层=`info`**（`_layer_status_text`）。**右键**整行（`_bind_layer_menu` 递归绑 Button-3/2 到 card 及全部子控件，含 CTkOptionMenu 内部 canvas）→ `_layer_menu`，像桌面右键图标；⋮ 已删。识别结果不再在行内复述（删了 `_layer_content`/`_layer_content_text`），P3 由 API 写回图层、画布呈现。详见设计文档 §9.7。
- **追加（同会话）：提取/背景提示词随产品持久化（P3-1）**。`config_store.ProductConfig` 加 `extraction_prompt`/`background_prompt`（+ 序列化 + 助手 `with_product_prompts`）；`ui_app` 两个文本框构建即载入当前产品值、`<FocusOut>` 存盘、切产品先存后载（`_persist_prompts`/`_load_prompts_into_widgets`）。`tests/test_config_store.py` 加往返用例。⚠️ **坑**：`save_config` 默认路径在 import 时绑定，测试改 `DEFAULT_CONFIG_PATH` 不生效——必须 patch `ui_app.save_config` 或传显式路径，否则写穿到真实 `birth_flower_config.json`（本会话踩过、已恢复为默认）。详见设计文档 §9.7 / P3-1。
- **追加（同会话）：多字段引擎 → 单「提取提示词」框**（用户拍板，覆盖原设计 §1–7）。功能区「字段」卡换成一个 `_build_extract_prompt_panel`（CTkTextbox「提取提示词」，整段自然语言发给 API）；**彻底删** `field_defs`/`_render_fields`/`_add_field` 等全部多字段 helper（纯 UI 侧、无外部依赖）。图层行「内容」由「字段下拉」改为**只读显示**「内容：Info」，待 API 返回由 `self._layer_content[layer.id]` 填真值（文字层=文字内容、图片层=素材名）。`_show_generated_prompt` 改拼 `[提取提示词]+[背景提示词]+[订单信息]`。详见设计文档 §9.7。
- **追加（同会话）：删底部「生产输出」栏**。该栏的 格式/目录/选择 早已重复在「输出设置」卡；唯二不重复的 **「生成」按钮 + 状态文字** 已移入「输出设置」卡（`_build_output_settings_panel`），并把该卡移到功能区**最底部**。删 `_build_production_bar` + `_build_layout` 里的创建/pack + `section_frames["production_bar"]`；腾出的底部空间由 body 自动 fill（画布更高、功能区更长）。**「生成」是操作动作、不入配置锁**（`config_locked` 时操作员仍可生成，已冒烟验证 `confirm_button.state=="normal"`）。同步删了 `tests/test_ui_app.py` 里 section_frames 对 `production_bar` 的断言（该元素已按设计移除）。
- **追加（同会话）：图层行重做「单行·灰字缩写」+ 拖动落点线动画**（用户拍板，先给 ASCII 预览选定再写代码）。行 = `拖柄⠿ + 类型小图标 + 状态 + 提取内容(主) + 右侧灰字库缩写`：**图标回归**（蓝底`T`=文本 / 绿底`▣`=素材，`_layer_icon_spec`）；**内容**=文本层识别文字 / 素材层文件名，空文本层显示灰色 `info`（`_layer_main_text`）；**右灰字**=文本「字体·字号」/ 素材「素材库缩写」（`_layer_dim_text`+`_abbrev` 截断）。**行内不再放下拉**——改库/素材/字体统一收进**右键菜单**新加的 `素材库`/`素材`（图片层）、`字体库`/`字体`（文本层）级联（复用既有 `_on_layer_*_changed`）；字号仍走「位置/尺寸…」对话框。**拖动动画=插入指示线**：拖柄按住→被拖行调暗「抬起」(fg→panel+蓝边)、`layers_rows_box` 上 `place` 一条蓝色落点线指示插入位（`_ensure_drop_indicator`/`_layer_drag_motion` 按指针越过哪行中线算落点），松手 `_reorder_layer_to_index` 按显示索引重排（列表是 reversed=下→上，注意换算）。**修了旧 bug**：旧版把左键选中也绑到拖柄上、会覆盖拖动的 ButtonPress——现在拖柄只管拖动，选中绑在其余控件。删 `_build_image_sources`/`_build_text_sources`/`_text_layer_has_content`/旧 `_reorder_layer`/`_layer_id_at_y`。验证：`py_compile` 过；隔离冒烟过（图标/内容/灰字、拖动重排、落点线显隐、右键级联齐全、`save_config` 被拦截零写盘）；`pytest` 390 过 / 2 预存失败（同前）。详见设计文档 §9.7。
- **追加（同会话）：「提取提示词」框回档为多字段「字段」卡**（用户拍板，撤销上面那条「多字段→单提取框」的 UI 改造，**只动这块**，布局重排 / 单行图层行 / 背景词持久化 全保留）。因这些都是未提交的工作树改动、git 无法择块还原，从本会话 transcript 还原了删掉的精确代码：`__init__` 恢复 `field_results`(mock Ammy/1月/Font5)+`field_defs`(3 条)+`field_seq`+`fields_body`，删 `extract_prompt_text`；`_build_extract_prompt_panel` → `_build_fields_panel`/`_render_fields`/`_ensure_field_vars`/`_field_chip`/`_add_field`/`_delete_field`/`_on_field_changed`（一字段一卡、error 标红、属配置锁定区）；卡片列表第 3 槽换回 `_build_fields_panel`。**与旧版的区别**：新图层行已不显示字段，故**去掉了字段↔图层耦合**——`_render_fields` 不再 `_render_layers`，`_delete_field` 不再清 `_layer_field_bind`，未恢复 `_field_menu_values`/`_refresh_field_menus`/`_layer_field_label` 等耦合 helper。`_show_generated_prompt` 回到拼 `[字段提取规则]+[背景词]+[订单信息]`。`_persist_prompts`/`_load_prompts_into_widgets` **收窄为只管背景词**（`product.extraction_prompt` 原样保留不动，不再读已删的 `extract_prompt_text`）；`config_store` 的 `extraction_prompt`/`background_prompt` 字段与 `with_product_prompts` **不动**（其单测仍绿）。验证：`py_compile` 过；隔离冒烟过（字段卡回归、无 `extract_prompt_text`、增删/生成预览正常、`save_config` 被 patch 拦截→真实配置零写入）；`pytest` **390 过 / 2 失**（同前两条预存失败：`case_button`、初始化菜单断言，皆与本块无关）。
  - **再调（同会话）**：字段卡每个 chip 内的**显示名** `字段1/字段2/字段3` → `Info1/Info2/Info3`（仅改 `field_defs[*]["name"]`，其余不动）。结果值仍是 mock `Ammy/1月/Font5`、类型下拉**保留三个** `文本/素材/字体`（用户确认订单备注里有时会点名字体，故不砍）。澄清（用户问"砍成 2 个是否省资源"）：下拉选项是本地 UI 控件、不入网络/不进提示词正文，砍它**不省内存/CPU/网络**；真正影响提示词强壮性的是"schema 是否含订单里根本没有的类型"——此处字体确实在订单里，保留正确。

## 本会话改动（2026-06-16 · 输出设置加 PNG 镂空/正常切换 + 说明文案对齐真实按钮）

承接用户两点要求：①「文件-设置-输出设置」要能选 PNG 导出 **镂空(透明底,当前样式)** 还是 **正常(白色实心底)**；②设置页说明文案必须与真实 UI 控件逐字对应（原文案写"人工确认按钮",但主界面真实按钮叫「生成」）。
- **配置**（`config_store.py`）：加全局字段 `AppConfig.png_background`（`transparent`=默认/镂空 | `white`=正常白底）；加 `normalize_png_background`（None/旧配置/非法值回落 `transparent`）；`load_config`/`save_config` 读写。
- **渲染**（`renderer.py`）：`render_document_png(document, path, *, background="transparent")` —— `white`→不透明白底 `(255,255,255,255)`，否则镂空 `(0,0,0,0)`。**默认透明,旧调用/金标/批量行为零变化**。仅作用于多图层 PNG 主路径；legacy `render_png`（无图层、米色 `#FFF8F0` 底）未动。
- **UI**（`ui_app.py`）：init 加 `self.png_background_var`(初值读 config)；`_build_output_settings_tab` 加「PNG 背景」单选组(镂空/正常)；`_save_settings_window` 经 `dataclasses.replace` 持久化；生成流程改 `render_document_png(..., background=self.png_background_var.get())`。**说明文案改为**「识别结果不会自动生成最终文件；确认字段后需在主界面点击「生成」按钮才会输出。」（主按钮真实 label=`生成`，见 `_btn(body, "生成", ...)`）。
- **测试**：`tests/test_document_layers.py` 加 `test_render_document_png_background_option`（透明四角 alpha=0 / 白底四角=255）。已过 `test_document_layers`+`test_config_store`+`test_renderer`(38) 与 `test_ui_app`(55)。
- **全局约定**：用户把"说明文案须与真实 UI 控件一致"定为前端开发全局规则（已记入记忆 `ui-copy-must-match-actual-controls`）。
- **待用户真机**：设置页单选交互 + 导出实际底色（已自动验渲染像素，Tkinter 单选点击未自动验）。

## 进行中（2026-06-15 · 图层系统重做成 PS 风格 —— Stage 1 已落地，UI 待续）

用户要求把图层系统重做成 PS 同款（**已拍板：7 个按钮全删走纯 PS 风、完整嵌套图组、一次性全做**）。因体量大 + 改动生产导出链路，按内部 Stage 安全推进、逐 Stage 提交。
- **Stage 1 ✅ 模型基础层（导出安全）** `51bd8cf`（`models.py`/`renderer.py`/`desktop_export.py`）：新增 `GroupLayer(children/collapsed)`；`Document` 加 `iter_all_layers`/`flat_render_layers`/`_flat_leaves`/`container_of`；`normalize_z_indexes`/`layer_by_id`/`delete_layer`/`move_layer`/`hit_test` 全改图组递归·容器感知；新增 `group_layers`/`ungroup_layer`。**渲染/导出统一改走 `flat_render_layers()`（3 处调用点）；关键不变量=无图组时 flat==sorted_layers() 对象顺序一致 → 金标/批量/WYSIWYG 字节零变化（370 passed 验证）**。图组 visible/locked 向下级联。护栏 `tests/test_layer_groups.py`(7)。
- **Stage 2/3 ⏳ 未做（UI 面板重写，`ui_app.py`，大）**：当前 `_build_layers_panel` 是 `tk.Listbox`+7 按钮——需重写为支持「嵌套图组 + 逐层眼睛/锁图标 + 拖动排序 + 多选」的控件（`ttk.Treeview` 最合适：原生层级/折叠/多选，按 `identify_region/column` 做图标点击与右键命中）。要做：① 删 7 个按钮（显隐/锁→逐层图标，排序→拖动，其余→右键）；② 右键图层菜单（置顶/置底/编辑素材·字体/组合为图组(多选)/解组/删除）+ 右键空白菜单（添加图层/全选/展开折叠）；③ 空白图层工作流（删生产参数区「添加素材/添加文本」按钮 → 「添加图层」建空白叶子层，选中后再选素材/字体填充）；④ 组合/解组接 `group_layers/ungroup_layer`。**UI 需用户真机测**（Tkinter 拖放/图标命中无法纯自动化验）。
- ✅ **「`&` 无法显示」已查清并修复（`fix(export)`，用户给了 outputs/ 三个文件定位）**：`&` 本身一直正常；真正坏的是**周围平滑字形（尤其草书大写 A）在矢量端被压成实心黑块**。两根因：① `dxf._quadratic_segments` 把多控制点 TrueType `qCurveTo` 塌缩成单段 → 平滑曲线扭曲（已改为按隐含中点正确展开多段，SVG+DXF 共用 `_glyph_contours` 都受益）；② `svg._render_text_layer` 逐 contour 各发一个 `<path fill>` → 内层 counter/环各自填实（已改为一字形全 contour 合进同一 `<path>`，nonzero 缠绕成镂空孔；DXF 是净轮廓不受影响，EzCad 自己做 region 填充）。预览(Pillow 真字体)一直对，故只坏矢量端、难发现。cairosvg 渲染验证全字清晰、A 成细环、`&` 正常。金标 `real_note_a/b.svg` 重生成（结构断言仍过）。护栏 `services/api/tests/test_glyph_vector_fidelity.py`(3)。`♡`=Font 4 自动结尾爱心字形（非 bug）。

## 本会话改动（2026-06-15 · 文字撞花修复 + 全局字体样式 Stage 1/3）

承接用户用 App 导出「Melanie Helen Margaret（水仙）」反馈两点：①长名文字压到花茎叶（排版不合格）；②"布局设置"需加字体样式（加粗/下划线等）。设计与分阶段见 `docs/superpowers/plans/2026-06-15-text-collision-and-font-style.md`。决策：撞花=几何分区+(本验证证明无需)代码避让；字体样式=全局默认+每层覆盖；加粗=轮廓外扩(offset)。
- **关键事实（已验证）**：桌面 App 活动布局读**顶层 `layout_defaults`**，不读 `products[0].defaults`（`ui_app.py:785`）。用户已把 `layout_defaults` 升到 **3036×2244**（≈1.753× 旧 1732×1280，同比例）；`products[0].defaults` 原停在 1732×1280，已同步一致。
- **Stage 1 ✅ 几何分区（只改 `birth_flower_config.json` 两块 layout）**：文字框移到花正下方、纵向不重叠（花 y[70,1613] / 文字 y[1736,2157]）。值：flower_height 1858→1543、text_x→1227、text_y→1736、text_width→1543、text_height→421。⚠️ 全局生效，**待用户真机核对短名+长名**。
- **Stage 2 ❎ 已验证无需做**：真实 `fit_text_box` 实测——新框(1543×421,cap210)里长名满字号210单行、超长名自动断2行、无一溢出。撞花根因是旧框又小又叠花上，Stage 1 已结构性解决（contain-fit 保证花 ink≤1613<1736）。
- **Stage 3 ✅ 字体样式数据层**：`models.EngravingLayout` 加全局默认 `bold/underline/italic/bold_strength`（=外扩量占字号比例，默认0.016）；`TextLayer` 加同名 `|None` override；`ResolvedTextStyle` + `resolve_text_style(layer,layout)`（override优先，bold=False归零）+ `layer_text_style(layer)`(渲染端按图层读,None→关)；`config_store` round-trip。**默认全 False/归零 → 现有导出零行为变化**。
- **Stage 4 ✅ 预览加粗/下划线（text_renderer.py）**：全部预览/PNG 文字都走 `TextRenderer.render_layer`，只改它即覆盖实时画布+PNG。加粗=Pillow `stroke_width=round(strength*font_size)`；下划线=行墨迹下画矩形。stroke=0/underline=False 逐像素同旧（零回归）。默认强度 0.016 经预览扫值实测选定。**已可视化验证**(`tmp_out/font_style_final.png`)。护栏 `tests/test_text_style.py`(8)。全量 **381 passed, ruff clean**。
- **Stage 5 ✅ 矢量导出加粗/下划线（svg.py + dxf.py）**：装 `pyclipper>=1.4`。`dxf.offset_glyph_polygons`(nonzero union 定向 + ET_CLOSEDPOLYGON 偏移) 把字形外圈+内孔整组外扩→加粗保镂空，svg+dxf 共用；下划线=基线下闭合矩形；`desktop_export` 把样式烘进 `schema['style']`。**端到端验证：cairosvg 实测草书字怀保持镂空；DXF 只 SPLINE/POLYLINE 无 TEXT/HATCH，bold→POLYLINE**。护栏 `test_glyph_bold.py`(3)+`test_vector_font_style.py`(2)。默认关→金标零变化。
- **Stage 6 ✅ UI（ui_app.py）**：布局设置加「字体样式默认」区(加粗/下划线/强度，独立 `font_bold_var/font_underline_var/bold_strength_var`)；`_active_layout_defaults()` 合并几何+样式、**两条保存路径共用**(保存不丢样式)；建文本图层时烘全局默认进图层。护栏 `test_font_style_ui.py`(2)。**全量 388 passed, ruff clean**。
- **尾巴已接（同日续）**：① 字间距=`EngravingLayout.letter_spacing` 全局默认（布局设置加输入）+ 建层烘焙；② 图层级「样式覆盖」面板=文本属性区加 加粗/下划线/字间距 勾选/输入，「应用文本属性」写回选中图层（`bold/underline/letter_spacing+tracking`）。`_sync_layer_properties` 选层时回显。护栏 `test_font_style_ui.py`(4) + `test_text_style.py`(letter_spacing round-trip)。**全量 389 passed, ruff clean**。可视化验证 `tmp_out/letter_spacing_check.png`。
- **仅剩待用户真机验**：布局设置/属性面板开关交互 + 预览观感 + EzCad 导出件加粗/下划线/字间距观感。（加粗强度=全局，per-layer 未单列；斜体未做——如需再加。）
- **Stage 6 ⏳ UI**：布局设置字体样式区 + 图层属性覆盖；建层时 `resolve_text_style` 烘全局默认进图层；`letter_spacing` 字间距已全链路实现，只需接 UI。

## 本会话改动（2026-06-15 · 两个 UX 升级：文字排版 + 解析失败弹窗）

承接 Phase 2 收尾后，用户反馈两点（均看 mockup 定方案后实现）：
- **图1 文字自动排版升级（全套）** `629e21a`（`text_layout.py`）：`fit_text_box` 名字分支由「永远单行」改为 `_fit_name_layout`——长名(多词)在 1..`NAME_MAX_LINES`(=2) 行里挑能放最大字号的均衡断行(`_balanced_wrap` 按真实墨迹宽最小化最宽行、单词不拆)；多一行需比单行大 `NAME_WRAP_GAIN`(8%) 才换行(短名零回归)；两侧留 `NAME_SIDE_PAD_RATIO`(4%) 边距；多行墨迹块占框高 `NAME_BLOCK_HEIGHT_RATIO`(0.86)；最终 `_lines_fit` clamp 不溢出。**仍走同一 fit_text_box → 预览==导出不变；高度受限的普通名字结果不变(无 WYSIWYG 回归)**。
- **图2 解析失败弹窗重做** `d1ac530`（`ui_app.py`）：`_apply_parse_result` 里的原生 `messagebox.showwarning("无法解析")` 换成 `_show_parse_warning_dialog`(主题化 `_themed_toplevel`)——顶部「需人工确认 N 个字段」，中间按 `parse_missing_field_hints`(None 字段=内容/月份/字体/花材) 生成醒目字段卡，AI/本地原文折到「识别详情」只读框，按钮「复制原文 / 知道了去确认」。
- 全量 **363 passed, ruff clean**。⚠️ 两项均**待用户真机手测**（看长名实际断行效果、弹窗实际观感）。

## 本会话改动（2026-06-15 · Phase 2 增量 3-4-5 全部落地）

承接上一会话（已提交本线两提交）。用户拍板「完成剩下的 345」，且增量3 选「完整重构」。按风险从低到高 4→5→3 实现，每增量先测后提交，全量 **358 passed, ruff clean**。
- **增量4（属性面板生产参数随图层）** `e723e82`：图层面板加 位置X/Y/宽/高 编辑；`_apply_layer_production` 写回画布几何（与拖拽同路径，不旁路 `_apply_canvas_fit`）+ 记 `layer.production`；新增 `_slot_defaults/_layer_library_entry_defaults/_layer_effective_production`（§5 resolve_chain：产品默认→库默认→素材默认→override）。
- **增量5（设置窗口管库目录）** `72ea927`：`config_store.with_product_library_dirs`（纯函数，只改激活产品 + 首目录回写顶层迁移入口）；设置「素材库/字体库」tab 改目录列表编辑器（Listbox+增删）；`_scan_assets` bundle = 主库(单目录入口即时生效)+产品配置附加库 → 多库。**顺手修潜伏 BUG**：`_save_current_config` 原整体重建 AppConfig 会清空 products/active/收展态（与 `_save_settings_window` 同坑），改 `dataclasses.replace`。
- **增量3（人工确认面板重构，完整版）** `4ff0706`：订单面板去掉手填「月份」Spinbox → 只读「素材月份」chip；生产参数区在 素材/字体 下拉上方加「素材库/字体库」选择器（数据驱动 `active_bundle`，选库 → `_assets_for_selected_*_library` 按 `path.name` 过滤候选）；`_merge_additional_library_assets` 把首库之外的库 entries 转 FlowerAsset/FontAsset 并入候选（**单库时空操作 → 当前生产零行为变化**）。**关键安全设计**：`month_var/flower_var/font_var` 保留为**内部派生态**（随选中素材/字体程序化设置），导出/金标/批量/导入全走旧路径不变，仅 UI 不再手填。
- ⚠️ **真机手测仍待用户做**：只过了自动化测试 + 真 Tk root 构造冒烟，没在真实窗口里点完整链路。改完 Python **务必完全关掉 App 重开再测**（选库切换、调几何、加不同库素材、导一单核 ezdxf 实体类型应仍 R2018+SPLINE/POLYLINE 无 TEXT/HATCH）。
- 设计/接线契约与逐 Step 勾选见 `docs/superpowers/plans/2026-06-14-layer-material-library-system.md` Task 2。

## 本会话改动（2026-06-15 · 审查并提交本线两提交）

- **审查 + 选择性提交本线工作**（用户拍板"审查+提交本线"）。先全量复跑 **348 passed / 19.46s**、ruff clean，再按概念分两提交（显式 path 暂存，**Electron 改动/dev-*.log/tmp_out/.claude 全排除在外**）：
  - `b5a939c` feat(ui): Phase 2 增量1-2 图层素材库接线（material_library.py + ui_app.py + 两测 + ExecPlan 进度）。
  - `89763cb` feat(parser): 订单截图视觉解析后端（screenshot_parser.py + test + 计划文档）。
- **仍未提交在工作区**：仅 `apps/desktop/**` Electron 前端（非本线，D 项暂缓）+ `packages/design-core`/部分 TS 改动 + 噪音文件（dev-*.log、tmp_out/、.claude/）。下次若要清，建议把噪音加进 `.gitignore`。

## 本会话改动（2026-06-14 · Phase 2 增量1-2 + 截图后端 → 已于 2026-06-15 提交）

承接「图层素材库系统」（顶部新需求）。详见 `CURRENT_TASKS.md` 待办 0 / 0b 与 ExecPlan。
- **四条提交已 commit**（分支 `claude/phase4-product-switcher`）：`62556c0` 后端基线（Phase 1+3）、`0840631` UI 基线（Phase 4+CTk 换肤）、`b5a939c` Phase 2 增量1-2、`89763cb` 截图后端。
- **Phase 2 增量1-2（改 `ui_app.py`，已提交 `b5a939c`，348 passed）**：①`active_bundle`（产品库目录建，切产品跟随）+ `parse_remark(bundle=)`→解析落 material_key；②「添加素材/文本」给图层写 `library_id/material_key/font_*`。**增量3-5（素材库选择器/属性面板生产参数/设置管库）按 ROI 暂停**——单产品单库时视觉≈现状、且与现有 month/flower 选择逻辑深度交织高风险，等真加第二个素材库/产品再做。
- **截图视觉解析（`screenshot_parser.py`，已提交 `89763cb`，未接 UI）**：订单截图→视觉模型→ParseResult。**可行性未用真图+真 key 验过**；准了再给「导入」按钮接识图，不准就删。GPT 文本接入已能生效。
- **GPT 接入无 bug**：设置填 provider/key+勾「AI 优先」保存，「测试连接」验 key（解析失败静默回退本地）。

## 本会话改动（2026-06-14 · Phase 4）：产品切换器（方案2 可收/展）

分支 `claude/phase4-product-switcher`（基于后端基线 `62556c0`，**未提交，待 review**）。全量 **341 passed**，ruff clean。
- `ui_app.py`：最左新增可收/展产品列（`_render_product_rail`/`_build_product_button`/`_toggle_product_rail`/`_switch_product`/`_open_new_product_dialog`/`_create_product_from_dialog`）；模块级纯函数 `product_initial`/`product_rail_items` + 轻量 `_attach_tooltip`。原「预览 + 功能区」两栏布局**未动**（产品列是 pack `side="left"` 的新增列）。
- `config_store.py`：`AppConfig` 加 `products_panel_collapsed`（默认收起，持久化）；新增纯函数 `unique_product_id`/`with_added_product`/`_slugify`。
- 顺手修 BUG：`_save_settings_window` 改用 `dataclasses.replace`，否则保存设置会清空 `products`/`active_product_id`/收展态。
- `tests/test_product_switcher.py`(9) 纯逻辑单测；withdrawn-root 运行态冒烟过。
- ⚠️ **未完**（见 ExecPlan Task 4）：切产品不联动人工确认面板字段（属 Task 2/Phase 2）；多产品端到端未验证（生产仍单产品）。

## 本会话改动（2026-06-14 · UI 换肤）：CustomTkinter 深色迁移（阶段 1-3 完成）

依赖：`customtkinter>=5.2`（已装进 `.venv-win`，登记进 `requirements.txt`）。全量 **341 passed**，ruff clean。运行截图存 `tmp_out/stage*.png`。
- **阶段1 全局深色**：模块级 `ctk.set_appearance_mode("dark")`；`APP_COLORS` 翻深色 + `_configure_styles` 把 ttk(clam) 全控件（含 Notebook、Combobox 下拉）刷深色；产品列改 CTk 圆角。
- **阶段2 主窗口面板**：功能区改 `CTkScrollableFrame`（删手搓 canvas 滚动）；订单/生产/图层/预览/生产输出五块改 `_ctk_card` 圆角卡片；按钮→CTkButton(`_btn`)、输入→CTkEntry、备注→CTkTextbox、勾选→CTkCheckBox、素材/字体下拉→**CTkOptionMenu**（`<<ComboboxSelected>>` 改 `command=`）；`_add_row`/`_add_path_row` 也改 CTk。
- **阶段3 弹窗**：所有对话框 `tk.Toplevel`→`ctk.CTkToplevel`（深色）；新建产品对话框全 CTk。设置/布局/素材编辑弹窗内部沿用 ttk-dark（Notebook 等已刷深色），未逐控件 CTk 化（小尾巴）。
- **画板保持浅色**：`preview_canvas` 仍白底（代表浅色木料；预览是深灰折线+黑墨字，翻黑会看不见，要黑画板需反转 `renderer` 预览色，独立任务）。
- **修的坑**：① 预览 `ImageTk.PhotoImage(..., master=canvas)` 绑定到画板解释器（多 root 测试下原报 image doesn't exist，单 root 也更正确）；② 新增 `tests/conftest.py` autouse fixture 清 CTk 全局 tracker；③ `_widget_texts` 容错 `ValueError`；④ context-menu 测试先 `monkeypatch.undo()` 再 `root.destroy()`（CTkOptionMenu 的 DropdownMenu.destroy 会调 tkinter.Menu.destroy）。
- **⚠️ 启动崩溃回归（已修）**：`import customtkinter` 原是 `ui_app.py` 顶层硬依赖，用非 `.venv-win` 解释器（如 MSYS `.venv`）启动会在 `birth_flower_mvp.py:3 from ui_app import main` 处直接 `ModuleNotFoundError: customtkinter` 崩溃，早于 `_reexec_with_complete_env` 切换 → 窗口闪退。修法：顶层 `try/except ImportError: ctk=None` 容忍 + 模块级 `set_appearance` 加 `if ctk is not None` + `_reexec` 的依赖自检同时 `import customtkinter`（缺它也切 `.venv-win`）。验证：`.venv/bin/python.exe birth_flower_mvp.py` 现可正常 re-exec 到 `.venv-win` 运行。**教训：ui_app 顶层别加只装在 `.venv-win` 的硬依赖，否则破坏引导解释器 re-exec。**

## 本会话改动（2026-06-14 · UI 换肤续）：Ezcad 同款顶部 + 产品列外推

参考用户指定的 `C:\Users\Administrator\Documents\Ezcad2.7.6`（其做法 = `ctk.CTk()` 根窗 + 无原生菜单栏 + CTk 卡片 `corner_radius`，**并非**无边框/外框圆角）。据此改 flower（全量 341 passed，ruff clean）：
- **根窗** `main()` `tk.Tk()`→`ctk.CTk()`（自带深色标题栏；探针实测 ctk.CTk 的 configure/menu/geometry/bind 全可用）。
- **去原生菜单栏**（系统菜单条无法染色=白条，已实测）：菜单迁到 `_build_menubar` 顶栏 CTk 按钮 + `_popup_menu` 用 `tk_popup` 弹出原菜单（深色，菜单存 `self._menus`）。
- **`_enable_dark_titlebar`(DWM)** 仅当回退 `tk.Tk`（测试/缺 ctk）时兜底；`ctk.CTk` 自带不再调。
- **产品列展开 = 窗口加宽**（`_toggle_product_rail` 按 `delta=120` 改 geometry），实测画板宽度 694→694 不变（往外推、不挤画板）。
- **未做**：外框圆角（Win10 直角，Ezcad 也无；真圆角需 `overrideredirect` 自绘，用户暂未选）。
- 测试：`test_birth_flower_app_initializes` 的菜单断言改读 `app._menus`（不再有原生 menubar）。截图 `tmp_out/ui_ctk_top.png`、`ui_expanded.png`。
- **收尾修复（按用户反馈）**：① 收/展箭头方向纠正——收起 `«`(外，下次展开)、展开 `»`(内，下次收起)；② `glyph_panel.py` 也换 `ctk.CTkToplevel` + 玻璃网格 `tk.Canvas` 加 `bg="#242424"`（原是唯一没改的白窗）；③ 菜单 `tk.Menu` 加 `relief="flat"/activeborderwidth=0` 去弹窗白边；④ **`ctk.CTk` 致命坑**：`root.minsize()` 无参 getter 在 CTk 上抛 `TypeError`（`int < None`），`_toggle_product_rail` 原用它读回最小宽 → 真机点收/展即崩（tk.Tk 测试不报）。改用常量 `MIN_WINDOW_WIDTH/HEIGHT`。**教训：ctk.CTk 上别调无参 minsize/maxsize getter；ctk.CTk 专属 bug 用 tk.Tk 测试抓不到，须用 ctk.CTk 冒烟。**
- **对话框白标题栏修复（设置/布局/字形/字形说明）**：`CTkToplevel` 自带深色标题栏**实测不稳**（标题栏仍白；像素采样 (255,255,255)）。统一走 `BirthFlowerApp._themed_toplevel()`：建 CTkToplevel 后 `after(60)+after(350)` 调 `_enable_dark_titlebar`（DWM 设属性 + **1px 几何微调强制重绘**——光 DwmSetWindowAttribute rc=0 也不会重绘标题栏，复杂对话框靠几何微调才变深）。`glyph_panel.py` 同法。`show_glyph_help` 由原生 `messagebox`（白底不可染）改成 CTk 窗口，文案抽到 `GLYPH_HELP_TEXT` 常量（测试断言改读它）。**验证：4 个对话框标题栏像素采样全 (0,0,0)。** 教训：DWM 深色属性设上后必须触发重绘（几何微调）才生效。
- **下拉菜单改自绘 `CtkMenu`**（替代原生 `tk.Menu` 白边弹窗）：模块级 `CtkMenu` = overrideredirect Toplevel + CTk 行；菜单改**数据驱动** `self._menus`（list[(label, items)]，item={label,command} 或 {type:separator}），`_build_menubar` 点按钮→`_open_dropdown`→`CtkMenu.popup`。「导入」子菜单拍平为顶层两项（CtkMenu 不做嵌套）。**白角坑**：圆角 CTkFrame 四角露出 Toplevel 默认浅底→给 Toplevel `configure(bg=panel)` 兜底（角像素 (240)→(36)）。关闭：选中/FocusOut/Esc。`test_birth_flower_app_initializes` 菜单断言改读数据结构。**右键上下文菜单仍是 tk.Menu（未改，如需也可同法改 CtkMenu）**。

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
