# 2026-06-20 · 订单链路性能优化 · 分阶段方案（权威）

## 背景
常态 600+/小时、峰值 **1700+/小时（1 小时内涌入）**。1700/小时绝对量其实很低（均值约 0.5 单/秒），现在卡不是"量到极限"，而是三层各有具体、可修的低效点。三层分治，依赖关系：**DB 地基 → 抓取吞吐 → UI 承接**。

## 决策（2026-06-20 与用户敲定）
- **数据库：保留 SQLite + 加固**（WAL/pragmas + 补索引 + 批量端点 + 修查询），**不换 Postgres**。理由：单台 Windows 机器、全跑一台，WAL+索引 对 1700/小时绰绰有余且零运维；Postgres 行锁/MVCC 优势在单机单进程基本被 WAL 抹平，代价是多起一个服务。将来若分机器/再翻 10 倍再评估（换库成本低：纯 SQLAlchemy ORM + Alembic、<100 行、config 已支持环境变量切库）。
  - 注：旧 AGENTS/计划记过「SQLite 选定、真机验证」；本次仍用 SQLite，只是补上一直没做的并发/索引优化。
- **顺序：阶段一 → 二 → 三。**
- UI 引擎：阶段三时在 `ttk.Treeview`（推荐）vs 手写虚拟滚动 间再定。

## 红线（调查已确认，不可破坏）
- 订单契约冻结：`order_id` 唯一、`items[]`、`refund_status`、`paid_at`、`remark` 可选可空且下游须回退 `items[].personalization_raw`。
- `web services/api` 暂缓不启；只用 inbox-service 本地 HTTP（127.0.0.1:8770）。
- 标记回写每轮 ≤3 单（防店小秘封号）；抓取并发要节流防风控。
- 超时预算契约冻结（Ezcad 15s / 扩展拉取 1s / 搜索 6s），改抓取并发时不动它。

## 阶段一 · 数据库地基（inbox-service）—— ✅ 已完成（2026-06-20）
- [x] (1) DB pragmas：WAL + `synchronous=NORMAL` + `busy_timeout=5000`（`app/db.py` connect 事件，仅 SQLite）——写不堵读、洪峰少 `SQLITE_BUSY`。实测生效。
- [x] (2) 索引：`received_at`、`refund_status`、复合 `(status, received_at)`（`models.py` `index=True`/`__table_args__` + 迁移 `0008`）——原来只有 `paid_at` 有索引，调度每 60s 全表扫。`alembic upgrade head` 0001→0008 干净通过。
- [x] (3) `list_orders`：`recent_orders` 加 `selectinload(items, mark_jobs)` 消 N+1 + `offset`；路由加 `limit`(默认 100,≤5000)/`offset`，返回 `count`=真实总数 + `returned`。**保留 `to_dict()` 完整**（详情弹窗读同一份，不破坏）；裁字段=暂不做（非瓶颈，且会逼详情改成按需 fetch，留后）。flower 侧已对齐：`inbox_service_client.list_orders(limit/offset)` + 订单表状态行显示真实总数与「显示最近 N」。**默认 limit 仍 100**（虚拟列表未就位前不灌满 UI，阶段三放大）。
- [x] (4) `POST /inbox/orders/batch`：抽 `_ingest_one` 给单条/批量共用；一事务多单（少 fsync），单条 schema 不符/写失败只记进该单结果不连累整批。schema `IngestBatchRequest`(≤500/批)。
- [x] (5) retention `purge_orders_older_than` 改批量 `DELETE`（先删子表 items/refund_checks/mark_jobs 再删父表，不依赖 SQLite FK 级联），`synchronize_session=False`；不再逐行 ORM delete + 全量加载内存。
- 验证：inbox-service **130 passed**（+3 新测试）、`alembic upgrade head` 0001→0008 通过、pragmas 实测生效；flower **92 passed**（8 失败=既有 preview/文字/字段 WIP，与本次无关）。
- ⚠️ 未真机：起服务后建议造 ~2000 行压一压 list/ingest/purge 延迟。

## 阶段二 · 抓取吞吐（扩展 + inbox-service）—— 进行中
现状实测 600–1200 单/小时。**关键认知**：`pushOrder`/diff 都打**本地** service（非店小秘），所以"批量/并发回传"零封号风险、可单测；只有碰店小秘 DOM 的（翻页/打标/开详情）才需真机灰度。

**✅ 已做（安全·零店小秘风险·已测）：**
- [x] 批量 diff：`scrape_planner.diff_manifest` 逐条 `session.get` → 一次 `IN` 查询 + 一次退款检查集查询（O(N)→~3 次）。inbox-service 130 passed（含 scrape_planner 7）。
- [x] 批量回传：扩展 `auto_cycle` 逐单 `await pushOrder` → 收集后一次 `pushOrders`（`client.postOrdersBatch` → 阶段一 `POST /orders/batch`，服务端一事务提交）。`buildPayload` 单/批共用。typecheck clean + vitest 70 passed。

**✅ 自动翻页 + 游标「页面记录」（已实现·待真机校准）：**
- [x] 翻页器 DOM：用户提供真实 `vxe-pager`（mini，仅 上/下一页 + 总数/区间，每页 100、虚拟滚动、末页 `is--disabled`）。选择器进 `selectors.ts`（`pagerNextBtn/pagerPrevBtn/pagerTotal/pagerRange/tableBodyWrapper` + `PAGER_DISABLED_CLASS`）；DOM 胶水 `extractor/dianxiaomi_pager.ts`（next/prev/disabled/scrollToBottom，多 pager 取可见）。
- [x] 游标逻辑：`worker/paginate.ts`（纯·DI 可测）。游标=高水位 `paid_at`（字符串字典序=时间序）；`runPagedSweep` 从第1页起逐页抓，碰「本页含 paid_at≤游标」/末页/上限即停，结束推进游标。稳态只读1页；洪峰翻到接上游标。**绝不每轮全量重读所有页**（用户要的"页面记录"）。游标存 `chrome.storage.local`（加了 `storage` 权限），丢了不影响正确性（diff 兜底）。
- [x] `content.ts` 接线：开关关→绝不翻页/滚动；开→`runPagedSweep`（回第1页→滚到底读满本页→每页交 SW 跑 diff+批量推送+退款闭环→翻页）；`sweepRunning` 防重入；抓完仍**立刻打标**（用户要求保留，未动）。
- 测试：扩展 vitest **83 passed**（新增 paginate 9 + dianxiaomi_pager 4）；`tsc` 干净；`vite build` 通过。
- **⚠️ 真机校准点（必须用户在真店小秘验）**：① 翻页/滚动后重渲染等待时长 `PAGE_SETTLE_MS=1200`/`SCROLL_SETTLE_MS=400`（太短会漏行）；② 虚拟滚动滚到底是否真渲满 100 行（漏行则需多滚几次/调容器选择器）；③ 回第1页是连点上一页（backlog 后较慢）是否可接受；④ 翻页频率会不会触发风控/验证码（先小范围观察）。

**⬜ 仍待（真机定）：** 间隔 `DEFAULT_POLL_SECONDS=60` 视风控可调；`vxe-pager--sizes` 若能把每页调大（>100）可进一步减翻页。
- 注：标记回写时机——用户决定**保持"抓完立即打标"**，不挪出主循环。估算翻页+批量后可达 3000–6000 单/小时（远超 1700）。

## 阶段三 · UI 虚拟列表（flower）—— ✅ 完成
用户拍板**方案 A · ttk.Treeview**（原生虚拟化，扛 1700+ 行；与 app 已有 ttk 深色样式一致）。仅改 `ui_app.py` + `inbox_service_client.py` + `test_ui_app.py`，不动后端/契约。
- [x] 订单表 `CTkScrollableFrame` 逐行控件 → `ttk.Treeview`（`show="headings"`，列=订单号/付款时间/状态/标签/件数，iid=order_id）+ `ttk.Scrollbar`。深色样式进主题方法（`Treeview`/`Treeview.Heading` + 选中态）。
- [x] 交互改版：**双击**看详情（`_on_orders_tree_open_detail`）；**选中后 ✕删除选中按钮 / Delete 键 / 右键菜单**删除（`selectmode="extended"` 多选，`_on_delete_selected_orders` 确认一次→后台逐单删→本地移除）；右键用深色 `tk.Menu`（同图层菜单）。
- [x] 整行着色（Treeview 只能按行）：退款/取消=红、风控/含其他商品=琥珀（`_orders_tree_tags` 由 `status_bg` 反推）；详情/删除仍走 `order_row_view` + `_show_order_detail`（未动）。
- [x] 增量渲染 `_render_orders_rows`：按 order_id diff（删消失/建新增/`tree.item` 原位更新/`tree.move` 重排），保留滚动位置与选中。删 `_orders_rows/orders_scroll/_build_order_row/_update_order_row/_build_orders_header/_open_order_detail_row/_show_orders_empty_hint/_ORDERS_COL_MIN`（旧 CTk 行系统）。
- [x] `inbox_service_client.list_orders` + `_refresh_orders_table` 拉 `limit=2000`（虚拟化后可一次显示全量，覆盖洪峰 1700+；超出状态行提示「显示最近 N」）。
- 测试：重写 `test_orders_table_renders_incrementally_and_deletes_one_row_locally`（Treeview iid/原位更新/着色 tag/本地删行）。`pytest tests/test_ui_app.py` = **80 passed / 8 failed**（8=本分支既有 preview/文字/字段 WIP，与本次无关）；`py_compile` OK。
- **未真机点测**：起服务进配置端验：1700 行秒开、滚动流畅、双击详情、选中删除（单/多）、退款单整行红。

## 现状基线（调查 2026-06-20，详见各仓 AGENTS）
- DB：SQLite + SQLAlchemy ORM + Alembic（0001–0007），无 pragma；仅 `paid_at` 有索引；`list_orders` limit 100 全表扫 + `to_dict()` N+1；retention 逐行 ORM delete + 全加载内存。换库可行性高（ORM 零改）。
- 抓取：`content.ts` 60s 定时 → 收集本页 → `POST /scrape/diff`（后端逐条 `session.get` 比对）→ worklist 逐单 `await` `POST /orders` → 抓完 `runMarkOnce()`。无并发、无翻页、一单一 POST。
- 契约/计划基准：`automation/AGENTS.md`、`.claude/plans/*staged-wren*`、`automation/contracts/order.schema.json`。
