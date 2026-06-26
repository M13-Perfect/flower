# AGENTS — automation/（店小秘 → Flower 自动取单）

> **2026-06-22 · 新增只读端点 `GET /inbox/orders/next`（给 flower「库驱动载单」取 FIFO 队首待生成单）✅测试183 / ⬜真机**
> flower 操作员端把「订单信息框」改成**库驱动载单**（每3s 轮询取最旧待生成订单载入、生成后自动前进），需要服务端能直接给「最旧的待生成单」。本轮在 inbox-service 加：`repository.oldest_pending_order(session)`（`WHERE deleted=False AND ai_status='pending' ORDER BY received_at ASC LIMIT 1`，eager-load items+mark_jobs；`ai_status` 列本有索引）+ 路由 `GET /inbox/orders/next` → `{"order": {...}|null}`（**声明在 `/inbox/orders/{order_id}` 之前**，否则 `next` 被当 order_id）。**复用既有「生成→recognized」机制**：flower 生成成功 `request_mark(mark_done)` 已让该单 `ai_status→recognized` + 入队店小秘「AI已处理」，故它自动掉出本端点的 pending 结果、不被重复取到（订单不删、仍在订单表带「AI已处理」标）。顺手删了 `repository.py` 一个既有 dead import `AI_STATUS_RECOGNIZED`。测试 `tests/test_next_pending_order.py` ×4；inbox-service 全量 **183 passed**，`ruff` clean。**契约文件 `contracts/order.schema.json` 未动**。flower 侧改动见 flower/AGENTS.md 同日「库驱动载单」块。**⬜ 真机**：起 8770 后 `GET /inbox/orders/next` 返回最旧 pending、生成后前进到下一条。

> **2026-06-22（最新）· 手动「→Flower」单笔【条件打标】重做（✅逻辑+测试 / ⬜真机）——取代下方「手动打标暂不开放」(本文件 P0 块) 与旧 `manual_mark` API 块**
> **背景/用户诉求**：之前的 P0 把手动打标整段关掉（`shouldMark` 恒 false、`manual_mark.ts` 沦为孤儿）。用户要「手动也打标」，但要**有条件**、且不破坏「自动批量仍走任务租约+order_in_scope」的防误标。逐条确认后定下决策表与 4 个决策点（见下）。
> **真实链路（务必先懂）**：手动按钮 `content.sendOrder` → `handleManualFlowerOrder`（决策编排）→ ① 上传经 SW `FLOWER_GRAB_ORDER`→`grabOrderIfNeeded`→`postOrder('/inbox/orders?manual=1')`；② 据数据库三态决定是否打标；③ 仅 CREATED_NEW 才 `runManualMarkOnce` 在店小秘 force 打「AI未识别」+回读校验。**自动批量路径（`runAutoCycle`/`/inbox/orders/batch`/`/inbox/mark/pending` 授权门控）完全没动。**
> **决策表（权威，用户确认）**：仅 `!ai_done && !ai_unrecognized && 上传成功 && databaseResult===CREATED_NEW` 才打「AI未识别」；其余一律不动标签。冲突(同时有两标签)/已 DONE → 不上传不动。各分支稳定 reasonCode（见 `worker/manual_mark.ts`）。
> **4 个决策点（用户拍板）**：① 新建信号=**复用 dedup 不够**（dedup 含软删=True、无法识别复活），故后端 `IngestResponse` 加**只读 `created`**（=新建 OR 软删复活）；扩展严格三态（缺/非布尔→UNKNOWN→不打标）。② 手动**纯页面打标、服务端不留痕**（`?manual=1` → `_ingest_one(enqueue_mark=False)` 跳过入队 mark_job；`runManualMarkOnce` 的 `postResult` 空操作）。③ 软删**复活单当新单打标**（`created=True`）。④「逻辑」标记=软删 `deleted` 列，无单独分支。
> **本次改动文件**：
> - 后端：`repository.upsert_order` 返回值加 `created`（4 元组，唯一调用方 `_ingest_one`）；`schemas.IngestResponse +created`；`routes._ingest_one(enqueue_mark=True)` + `ingest_order` 读 `?manual` → `enqueue_mark=not manual`。**批量端/定向重抓（不带 manual）行为不变。** 新测试 `test_dedup.py::test_created_flag_*` + `test_mark_jobs.py::test_manual_upload_skips_enqueue_even_in_scope`。
> - 扩展：`shared/contract.ts +DatabaseResult`；`client.postOrder` 严格三态 `databaseResult`（只认真布尔 created）+ `opts.manual` 走 `?manual=1`；`grabOrderIfNeeded` 透传 `databaseResult`、**删 `shouldMark`**；`worker/manual_mark.ts` **重写**为 `handleManualFlowerOrder`(DI 决策编排)+保留 `manualMarkQueue`（**删 `shouldManualMark`/`shouldRunMarkCycle`/旧 `ensureMarkUnrecognized` 调用**，`ensureMarkUnrecognized` 函数本身留着没删、现无生产调用方）；`content.ts` 重写 `sendOrder`（决策驱动 + 每单 in-flight 锁 + 按 reasonCode 出 toast/按钮态）、抽出共用 `buildPopoverClosures`、新增 `acquireMark/releaseMark/runManualMarkOnce`（与后台打标轮询共用 `markBusy` 互斥，`manualMarkWaiting` 让后台让位防饿死、超时 12s、早退仍重排轮询链）。
> **已知问题/待办**：① **真机未验**——店小秘真实页面的连点/新单/已存在单/校验失败四场景需用户实测（封号风险：每点一单都真写页面）。② 语义边界（已与用户确认、非 bug）：手动单恰落**活跃任务范围内**时，自动路径下一轮仍会按自己的 order_in_scope 给它打标（auto 的职责，手动这条已不留痕）。③ `ensureMarkUnrecognized`/旧 `dianxiaomi-mark` 注释里「P0 手动打标暂不开放」字样属历史，已被本块取代。
> **怎么测**：后端 `cd automation/inbox-service && .\.venv\Scripts\python.exe -m pytest -q`（**179 passed**）；扩展 `cd automation/extension && npx tsc --noEmit && npx vitest run && npx vite build`（**144 passed** + 构建通过；决策表 10 用例在 `manual_mark.test.ts`）。

> **2026-06-22 · 订单逻辑删除（软删）+ 生产库迁移 + 清空堆积 + 配置端筛选栏（全部落地、全绿）**
> **背景**：配置端「立即清理」用户反馈"点了没反应"。真因有二：① 它按「保留 N 天」只删 `received_at` 超 N 天的旧单，而库里多是当天抓的新单 → 永远 0 条；② 它原是**物理删除**且只删 DB 不碰收件夹文件。用户拍板：**清理范围仍是 B（只删超 N 天旧单，语义不改）**、**改为逻辑删除（可恢复）**、**不删收件夹 json 文件**、UI 不做回收站（误删靠「重新导入」找回）。
> **本次改动（inbox-service，全在软删语义下，已 176 passed）**：
> - `models.Order` 加 `deleted`(Bool,默认False,索引) + `deleted_at`；迁移 `0010_add_orders_soft_delete`（链：0009→**0010**→0011(ai_status，并行功能叠在其上，无冲突)）。
> - `repository`：`delete_order` / `purge_orders_older_than` 改**软删**（标记 deleted、**不删行/子表/文件**）；`upsert_order` 命中软删行时**复活**（deleted→False，即使 raw_json 逐字节一致也复活+重写文件）；`recent_orders`/`count_orders` 过滤已删。`get_order`(内部 getter)**仍能看到**软删行（复活/按-id 操作需要）。
> - **查询过滤软删的点（共 6 处，曾因编辑丢失静默回退过 → 已加 `tests/test_soft_delete_filters.py` 锁死）**：`scrape_planner.diff_manifest`（**关键**：软删单当「不存在」→ 判 REASON_NEW → 扩展重抓 → 触发复活，这是误删找回的链路）、`scheduler.select_due_orders`/`due_for_recheck`、`batch_exporter._pending_orders`、`routes.mark_pending`、`routes.get_order_status`(软删→404)。
> - 前端 [ui_app.py](../ui_app.py) 的「立即清理」按钮逻辑**未改**（仍调 `purge_orders`，B 语义）。
> **运维动作（本会话已执行）**：① **生产库已迁移**——库非 alembic 管理（无 `alembic_version`、是 `create_all` 建的，故**不能直接 `alembic upgrade head`**），用脚本动态对账（模型 vs 库）补齐 **10 列**（orders 的 deleted/deleted_at/ai_status + scrape_control 的 7 个 0009 任务租约列）+ 9 索引，已对齐当前模型（still_missing 空）；将来并行进程再加列，**同法（model 反射 ALTER）补**。② **现存堆积已清**：65 单全部软删（行保留可复活）、收件夹 137 个待处理 json 移到 `outputs/_inbox_cleared_20260622/`（移出 flower 监听、可恢复、未硬删）。③ 冒烟：新代码直连迁移后库，`/healthz`+`/inbox/orders`(count=0)+`/inbox/scrape/control`(含租约列) 全 200。服务**保持停**（用户要求暂停），起服务双击 `启动服务.bat`。
> **配置端筛选栏（flower [ui_app.py](../ui_app.py)，已落地）**：`_build_orders_table_panel` 加 4 维筛选行（付款时间范围 / 店铺下拉 / 订单状态下拉 / 搜索订单号·备注）+ AI·复核下拉（复用并行进程 `ai_status`：待识别/已识别/待复核=conflict）。**复核 toggle 不重做**（并行进程已建「只看复核」）、**不另加 AI 列**（AI 态已折进「标签」列）。前端即时过滤，复用 `_render_orders_rows`/`_on_orders_filter_changed` 管线（新增 `_order_passes_filters`+`_refresh_shop_filter_options`+`_on_orders_filter_reset`）。护栏 `tests/test_orders_filter.py`（6 passed）。**真机视觉待用户验**。
> **怎么测**：inbox-service `cd automation/inbox-service && .\.venv\Scripts\python.exe -m pytest -q`（176 passed；`test_refund_scheduler::test_pending_endpoint_drains_after_recheck` 是既有同秒计时 flake，单跑必过）。flower 筛选 `PYTHONPATH=".;services\api" .\.venv-win\Scripts\python.exe -m pytest tests/test_orders_filter.py -q`。⚠️ 本会话**并行进程一直在改 inbox-service（ai_status/复核中间件）**，改前先 `git status` 看最新。

> **2026-06-22 · P0 修复：自动采集/打标失控 → 任务租约 + 心跳 + 统一授权守卫（新对话先读）**
> **根因**：扩展是否执行原来只看 `ScrapeControl.enabled` 一个布尔，而它存在**独立常驻**的 inbox-service DB——
> flower 关掉后 `enabled=true` 永久留存，扩展每次开店小秘页（含浏览器重启）都误判「已授权」→ 自动全量抓取 + 翻最多 30 页 +
> 给历史订单打「AI未识别」。`enabled` 与 flower 实例无任何绑定、无过期、无心跳，残留缓存成了独立授权源。历史订单被纳入是因为
> 抓取循环无差别翻页、`scrape_from` 从未真正用于过滤/停翻页，且每个新单入库即自动入队打标。
>
> **修复 = 任务租约（Task Lease）+ 心跳（Heartbeat）+ 统一授权守卫（fail-closed）**。新控制边界：
> **flower 是唯一控制面**；扩展是受控执行端，只信服务端 GET `/inbox/scrape/control` 返回的 `authorized`（服务端时钟据租约算），
> **绝不信任 chrome.storage / localStorage / 内存里残留的 enabled/running/旧 taskId/旧游标**。
> - **授权判据**（服务端 `app/authorization.py`）：`enabled` 且 `task_id` 非空 且 `lease_expires_at` 未过期 且 `scrape_from` 有值（缺订单时间范围必拒）。
> - **inbox-service**：`ScrapeControl` 升级为租约（迁移 `0009`：+task_id/flower_instance_id/lease_expires_at/task_issued_at/scrape_to/allowed_actions/shop_scope，**全可空、对既有行=NULL=未授权=安全默认**）。
>   新端点 `POST /inbox/scrape/task/start|heartbeat|stop`（`app/repository.start/heartbeat/stop_scrape_task`）。GET control 加服务端算的 `authorized`。
>   **副作用端点加授权+范围闸**（不只拦前端）：`/inbox/orders/batch`（无授权 403、范围外单 `out_of_scope` 拦）、`/inbox/scrape/diff`（无授权 403、时间窗外条目不进 worklist）、`/inbox/mark/pending`（无授权/范围外 → 空，**顺带保护已积压旧打标队列**）、ingest 自动入队打标仅在订单 `order_in_scope` 时。单端 `/inbox/orders`（手动）保持开放。config +`scrape_lease_seconds`(默认 90s)。**pytest 155 passed**，迁移 0009 upgrade→downgrade→re-upgrade 可逆。
> - **扩展**：新 `worker/authorization.ts`（`isAuthorized`/`orderInScope`/`pageBelowWindowFloor`，唯一判据来源）。`content.ts` 自动循环/后台打标改为 `authorized` gate；翻页前按时间窗过滤 + 整页越下界即停（不回溯历史）；**任务变更清旧游标**（`flower_scrape_task`）。`auto_cycle.ts` SW 侧二次 `authorized`+范围过滤（双保险）。`FLOWER_GET_CONTROL` 返回完整租约视图、出错兜底未授权。**vitest 120 passed、tsc、build 全过**。
> - **手动「→Flower」按钮（用户拍板）**：保留单单上传（人主动、只发本地服务、不碰店小秘）；**其店小秘打标功能暂不开放**（需先正式实现再开）——已移除 `sendOrder` 触发的 `runManualMark`、`grabOrderIfNeeded` 简化为仅上传（不再 diff/ensureMark，shouldMark 恒 false）。`worker/manual_mark.ts` 保留备用。
> - **flower（唯一控制面落地）**：`inbox_service_client.py` +`start/heartbeat/stop_scrape_task`（心跳 409=`LeaseLostError`）。`ui_app.py`「自动抓取」开关：开=`task/start`（`scrape_from` 取「定时抓取·重抓起点」选值，**没选则默认=现在**=只抓此刻后的新单、绝不回溯历史）+ 起 `after` 心跳循环（每 30s 续约）；关=`task/stop` 释放；**关闭 App**（新增 `WM_DELETE_WINDOW`→`_on_app_close`）释放租约。`_flower_instance_id`=每次启动新 uuid（不持久化）。状态行加「授权 是/否」+订单范围。**flower pytest 429 passed**（8 既有无头失败不变）。
> - **未纳入本次（仍按各自机制）**：定向重抓（option B，Ezcad 确认导入前）是**另一控制面**（Ezcad 秒级内存队列驱动、按需触发），未挂 scrape 任务租约，故未改——它不是失控源（无队列项不动作）。
> - **⚠️ 部署必做**：生产 `inbox-service/inbox.db` 现停在 `0008`，新代码用到租约列 → **上线前先 `alembic upgrade head` 迁到 0009**（停服务时做），否则新代码查 ScrapeControl 会因缺列报错。
> - **⚠️ 历史误标清理**：本次**只修代码、不动线上已被误打标的订单**（按用户边界）。历史标签清理留作单独任务。
> - **验收覆盖**（测试）：场景 2（残留 enabled=true 无租约→未授权）/3（无任务拉不到打标）/5（范围外单入库前拦）/6（停止即未授权）/7（租约过期→未授权）/8（重启不恢复=新实例须重授权）/10（旧 backlog/游标不绕过）均有 inbox-service + 扩展测试覆盖。**真机自动链待用户验**（扩展 dist 重载 + flower 点「自动抓取」开 → 看扩展开始受控抓取；关 flower → 看扩展 ≤90s 内停）。

> **2026-06-19 · 并入「订单自动化与排版系统」增量方案（新对话先读）**
> 本 automation 现在是更大方案的一环。**权威设计 = `C:\Users\Administrator\.claude\plans\ezcad2-7-6-flower-c-users-administrator-staged-wren.md`**（跨 flower / flower/automation / Ezcad 三仓；基线 A=在现有代码上增量，不重写）。下方旧内容（方案 D 一期）仍是 automation 的真实地基、未过时。
>
> **已敲定决策**：① 退款/取消状态只能让扩展**重抓店小秘页面**取（API 不开放、状态回写也没实现）；② 多文件扫码 = **单订单号条码聚合**（"双码"作废）；③ 拆件接缝 = **扩展抓「结构 + 原始备注」、不拆语义；语义拆分（一条备注 N 名字→N 单元）交给 flower GPT 解析层**（边界待真单调优）；④ 三端 = 管理/操作/后台调度，**暂缓**。
> **纪律**：`contracts/order.schema.json` 是三仓唯一契约，**只走计划/协调线程改**，别在各执行线程各改各的。
>
> **契约已冻结并落地（2026-06-19，26 tests pass）**：`order.schema.json` + `schemas.py` 加可选 `items[]`（line_index/product_sku/is_target_box/quantity/personalization_raw/extras）+ `refund_status`，**全部可选、`schema_version` 仍 "1.0"、老扩展/老 JSON 零影响**；`models.py` 加 `OrderItem` 表 + `Order.refund_status` 列 + items 关系（delete-orphan，幂等整树替换）；`repository.upsert_order` 持久化 items；迁移 `app/migrations/versions/0002_add_order_items_and_refund_status.py`（临时库 upgrade/downgrade 验证可逆）；新测试 `tests/test_items.py`。
>
> **2026-06-20 · 重新入库「内容一致就不必覆盖」+ 退款状态不被 None 抹掉（127 tests pass）**：`POST /inbox/orders` 原来同 order_id 重发=**无条件覆盖**所有字段（含用 None 抹掉已知 `refund_status`）+ 重写收件夹文件（重触发 flower）。现加两道检测——① `upsert_order` 比对 `raw_json` **逐字节一致 → 整单 no-op**（仅刷新 `updated_at` 保「新鲜」、防每轮重推；其余字段/items/生命周期状态全不动），`routes.ingest_order` 据此（已成功落收件夹时）**跳过重写文件/标记入队**；② 内容有变但 `refund_status` 为空（列表页重抓常无此列）→ **不拿 None 覆盖**库里已知「已退款」。`upsert_order` 返回值改 3 元组 `(order, dedup, content_same)`（唯一调用方=routes）；`IngestResponse` 加 `unchanged` 字段。新测试 `tests/test_dedup.py` +3。**起因**：Ezcad 搜索/导入退款检测排障——列表页重抓的 None 会把已退款单状态抹回 None → 搜索时「最后已知」recheck 误放行（跨仓，见 Ezcad CURRENT_TASKS point 2）。
>
> **2026-06-20 · 订单删除/清理 + 保留天数自动删（107 tests pass）**：新增 `DELETE /inbox/orders/{id}`、`POST /inbox/orders/purge {older_than_days>=1}`（`repository.delete_order`/`purge_orders_older_than`，ORM 级联清子表）；`ScrapeControl` 加 `retention_days` 列（迁移 `0006`，**0=关默认**）；`RefundScheduler.tick_once` 每轮 `_purge_by_retention` **无人值守按年龄删旧单**（纯 `received_at`、会删未完成单，故默认关 + flower UI 强确认）。flower 订单表（操作员配置端）消费这些接口。新测试 `tests/test_order_cleanup.py`。⚠️ 订单权威存 `inbox.db`，`outputs/inbox/*.json` 仅临时交接、删它不删库行。
>
> **automation 本仓待做**（计划 Phase 1–2）：① ✅ **已完成（2026-06-19）** 扩展抓 `items[]`/`refund_status`——**列表页样例已确认足够，无需详情页**（见下「2026-06-19 扩展抓取扩展」块）。② ✅ **已完成（2026-06-19）** inbox-service 加 `RefundCheck` 表 + `POST /inbox/orders/{id}/recheck`（见下「2026-06-19 退款拦截闸门」块）。③ ✅ **已完成（2026-06-19）** scheduler：规则 A/B/C + 半开区间 + Checkpoint 断点续跑，**定位为「退款重抓调度」**（见下「2026-06-19 退款重抓调度」块）。④ ✅ **已完成（2026-06-19，服务侧）** 测试重置 vs 生产重试隔离——inbox-service 加运行模式（见下「2026-06-19 运行模式隔离」块）；SVG/DXF/PNG 版本/覆盖归 flower。
>
> **追加需求 · 定时自动抓取 + 缓存/完整性（2026-06-19）✅服务核心 / ⬜扩展循环+flower开关**：见下「2026-06-19 定时自动抓取」块。已敲定：扩展定时抓、新单+刷新都要、**完整=items[]且refund_status**、时间基准=**付款时间**（列表页 `.order-time-list` 的 `付款：` 可抓）、交互=**扩展上报清单/服务算差异**、付款时间走 **extras.paid_at**（不动契约）、与退款重抓**统一成一份 worklist**、flower 开关=开关+间隔+从T重抓。

> **2026-06-20 · 标记回写店小秘（扩展模拟网页操作打自定义标记）✅逻辑+测试 / ⬜真机**
> 让扩展给店小秘订单回写自定义标记：**新单入库→打「AI未识别」(待处理)；flower 生成成功→打「AI已处理」+清「AI未识别」**。
> 店小秘无 API，只能扩展点「设置自定义标记」弹窗。**冻结契约 + 真实 DOM 勘查 + ExecPlan = `docs/2026-06-20-mark-writeback.md`（新对话先读）**。
> 复用退款 option B 的拉模式握手，但**队列改 DB 持久**（打标异步，扩展当时可能没开店小秘）。
> - **inbox-service**：新表 `mark_jobs`（迁移 `0007`，(order_id,action) 唯一、status/attempts/last_error、Order.mark_jobs delete-orphan 级联）；端点 `POST /inbox/mark/request`（flower 入队 mark_done）、`GET /inbox/mark/pending`（扩展拉，含 source_url）、`POST /inbox/mark/result`（ok→done / 失败 attempts+1 超 max→failed）、`GET /inbox/mark/jobs`（审计）；**ingest 新单(not dedup) 自动入队 mark_unrecognized**（config `mark_enqueue_unrecognized` 默认开）。config +`mark_max_attempts=5`/`mark_pending_limit=50`/`mark_enqueue_unrecognized`。改 `models/config/schemas/repository/routes` + 迁移 0007 + `tests/test_mark_jobs.py`。**pytest 120 passed**，迁移 0007 upgrade→downgrade→re-upgrade 可逆。**契约 order.schema.json 未动**。
> - **扩展**：`selectors.ts`（标记弹窗/标记区选择器 + `MARK_LABELS`+`MARK_ACTION_IGNORE_ICONS`；⚠️识别标记靠**图标 class** icon_brush_bill/icon_change_order，**不靠颜色**，酒红被 3 标记共用旧兜底会误命中）；新 `extractor/dianxiaomi_mark.ts`（DOM：定位订单标记区/开弹窗/读选中态/切换/确定/回读 + 纯逻辑 targetFor/satisfies/togglesFor）；新 `worker/mark_writeback.ts`（纯编排 runMarkJobs，DI 仿 rescrape：拉队列→不在本页跳过不耗 attempts→幂等已满足直接 ok→否则开弹窗按现态切换→确定→回读校验→回填）；`worker/client.ts`+`getMarkPending`/`postMarkResult`；`service-worker.ts`+`FLOWER_MARK_PULL`/`FLOWER_MARK_RESULT`/`FLOWER_GET_CONTROL`；`content.ts`+标记轮询循环（**受 /scrape/control enabled gate**、串行+每步延时+**每轮 limit=3 防封号**）；新 fixture `dianxiaomi-mark-popover.html` + 测试。**vitest 66 passed、tsc、build 全过**。
> - **✅ 对抗审查修复（2026-06-20，4-agent workflow，10 条确认全修/记录，详见计划文档 §七）**：防串单（弹窗选中态须==订单行现状，否则 deferred 留 pending）+ 表头缺失/回读 null 不当失败（修「成功当失败」）+ 确定按钮排除「创建标记」挑不到返回 null + mark_done 取代 pending mark_unrecognized（supersede）+ 选中判据改白名单 icon_support + 每轮限 3 单。
> - **✅ 上传门控（标准1）+ 标签列 + 打标时机（标准2）（2026-06-20，用户拍板，详见计划文档 §八）**：① 标准1=传 JSON 前看店小秘标记：AI已处理→不传（`buildManifest` 排除 `ai_done`；手动按钮走 `FLOWER_GRAB_ORDER`→`grabOrderIfNeeded` 单单 diff），否则查库 diff（不在库/不全/过旧才传）；扩展新读 `RawOrder.ai_done`(icon_change_order)。② 标准2=`ingest` 写成功后入队 mark_unrecognized（除非已有 active mark_done=`has_active_mark_done`）；生成成功入队 mark_done（supersede 未识别）。③ 配置端实时订单表加「标签」列，源=`Order.to_dict` 新增 `mark_jobs:[{action,status}]`（无迁移），flower `mark_status_style` 派生。
> - **✅ 打标耦合进抓取 + EzCad 导入检测（2026-06-20，用户反馈，详见计划文档 §十）**：① 自动抓一轮结束后**当轮立刻 `runMarkOnce()`** 在店小秘打 AI未识别（不等 8s 循环；`markBusy` 防并发抢弹窗；`confirm` 900ms）——「抓取就打店小秘、放缓抓取」。② `/recheck` 响应加 `ai_processed`（=有 AI已处理任务=已生成）；**EzCad** (`Ezcad2.7.6`) 导入闸门加 **WARN** 档：退款正常但**未生成→软警告可继续**（askokcancel），退款/查询失败仍硬拦，`ai_processed=None`(旧服务)不警告。**复跑：inbox-service 124 / Ezcad 124 / 扩展 70**。
> - **✅ 真机 DOM 验证（2026-06-20，claude-in-chrome，订单 4090627965/4093542955/4093587551，详见计划文档 §九）**：抓取时打 AI未识别、生成后打 AI已处理+清未识别，两条在真实店小秘页面实测通过；**3 校准点全解**（点任意 order-mark-block 开弹窗 / click 非 hover / 必须点确定）；**🔴 抓出并修致命 bug**：页面有多个 `.markPopover`（隐藏模板+可见），`getMarkPopover` 原取首个=隐藏的→守卫永远 abort→功能失效，已改取**可见**那个（`isDisplayed`）；`confirm` 延时→900ms。测后 3 单已还原。**仍待用户真机自动链**（扩展 dist 重载 + 开抓取开关 + flower 点生成）。**复跑：扩展 70 vitest / inbox-service 123 pytest / flower 398 pytest（8 既有失败不变）**。
> - **flower**：`inbox_service_client.py`+`request_mark(order_id, action)`；`ui_app.py` `confirm_and_generate` 成功→`_enqueue_mark_done_after_generate`（run_background best-effort，在 _advance 清 _inbox_active 前取订单号）。**pytest 395 passed**（8 既有 headless 失败不变）。
> - **⬜ 真机校准 3 点**（代码已按最可能假设实现 + 注释标注）：① 零标记单的「添加标记」按钮精确选择器；② 开弹窗 click vs hover；③ 勾选点击即生效 vs 必须点确定。真机：起 8770 + 扩展 dist 加载店小秘列表页 + 用一个测试单走 抓单→AI未识别、生成→AI已处理+清未识别。
>
> **2026-06-22 · 修复「自动抓取关闭时手动上传不打标」+ 手动 force 打标路径 ✅逻辑+测试 / ⬜真机**
> **根因**：手动「→Flower」(`sendOrder`→`FLOWER_GRAB_ORDER`→`grabOrderIfNeeded`) 自身从不触发打标，打标只在 `content.ts runMarkOnce()` 里发生，而它整段受 `/scrape/control enabled`（自动抓开关）gate（`content.ts` 关则退避）。所以**关掉自动抓后手动上传成功也永远不打标**——无独立的手动打标触发路径。
> **修法（不动后台定时打标的 gate，只为手动单独建路径，验收 #7）**：
> - **`worker/manual_mark.ts`（新，纯函数便于单测）**：`shouldManualMark`（上传成功/已存在但服务确认待打标→打；上传失败/无单号/无响应→不打，守 #6 不误标）、`shouldRunMarkCycle(force, enabled)`（force 恒跑、后台受 gate）、`manualMarkQueue(id)`（直接构造本单 mark_unrecognized，避开 backlog/limit）。
> - **`worker/client.ts`**：`grabOrderIfNeeded` 改返回 `shouldMark`；新 `ensureMarkUnrecognized(id)`（POST `/inbox/mark/request`，幂等确保 pending；404/已处理(skipped_done)/不可达→pending=false）。**只在上传成功或「已存在且完整」时**调 ensure，失败不调（不误标）。
> - **`content.ts`**：`runMarkOnce({force,onlyOrderId})`——force 跳过自动抓 gate 且**不重排后台定时器**（两路独立）；`onlyOrderId` 只处理本单。新 `runManualMark(id)`（markBusy 时短等重试，避免抢单例弹窗）；`sendOrder` 成功回调里 `shouldManualMark` 为真即 `runManualMark`。复用 `runMarkJobs` 原有幂等/身份/防串单（验收 #5）。
> - **inbox-service `routes.mark_request`**：给 `mark_unrecognized` 加 `has_active_mark_done` 护栏（与 `_ingest_one` 一致）→ 已/将「AI已处理」的单返回 `{status:"skipped_done"}`，不打回未识别。
> - **测试**：扩展 `manual_mark.test.ts`(13)+`client.test.ts`(6) → **vitest 102 passed、tsc 0**；inbox-service `test_mark_jobs.py` +4 → **pytest 133 passed**（refund_scheduler 偶发同秒计时 flake，与本改动无关，单跑/重跑皆过）。
> - **⬜ 真机**：扩展 dist 重载 + 关自动抓开关 + 店小秘列表页点「→Flower」→ 确认本单被打「AI未识别」；且后台定时打标在关开关时仍不主动写店小秘。
>
> **2026-06-19 · 扩展抓取扩展（items[] / refund_status）✅**
> **样例分析结论**：`Desktop\店小秘--全部订单.html` 等 4 份样例是**同一组 5 单**的不同视图（文件名只是场景提示）。「全部订单」列表页（vxe-table）每个订单行**已完整携带**所需四项，**不需要订单详情页 HTML**：
> - **行项目/其他商品**：订单明细单元格里每个 `.order-sku` 块 = 一件商品，同单可多块（混单/多盒子）。样例 5 单的行项目数 = `[1,4,2,2,1]`（4092270213 是 4 件混单）。**目标盒子 vs 其他商品的语义判定不在扩展做**（计划 §4：扩展只抓结构与原文，交给 Flower GPT 层）。
> - **数量**：`.order-sku__quantity`（`<span class="order-sku__symbol">x</span><span class="order-sku__quantity">N</span>`，可能缺省→按 1）。
> - **退款状态**：`.orderState` 首个 div 文本（**原文**），样例取值 `已审核 / 待打单（有货） / 已退款 / 已发货 / 风控中`。扩展抓原文，**映射（已退款/风控中/已取消→拦截）交给下游**。
>
> **改动文件**：`extension/src/extractor/selectors.ts`（+`skuBlock/skuQuantity/skuPrice/skuImage/orderState`）、`extractor.ts`（+`collectItems()` 枚举 `.order-sku`、`readOrderState()` 读状态；`buildRemark` 抽出 `regularizeAttrLines` 复用，整单 `remark` 行为不变向后兼容）、`shared/contract.ts`（+`RawOrderItem`，`RawOrder`/`OrderPayload` 加 `items?`/`refund_status?`）、`worker/client.ts`（payload 透传 `items`/`refund_status`，`JSON.stringify` 自动丢 undefined）。新增蒸馏夹具 `fixtures/dianxiaomi-order-multi.html`（混单+退款）。**契约 `order.schema.json` 未改**（items[]/refund_status 早已冻结落地）。
> **行项目 extras**：`{listing_url, price, thumbnail}` 进 `item.extras`，供「其他商品」配货提醒展示（计划 D5）。
> **验证**：`npx vitest run` **13 passed**（7 旧 + 6 新）、`tsc --noEmit` 通过、`vite build` 通过；**并用真实 4MB 列表页 `collectOrders` 实测**，5 单/行项目数/退款状态原文与人工核对**完全一致**。**待 Chrome 真机**在活动「全部订单」页加载 `dist/` 复核（vxe 重渲染/固定列）。

> **2026-06-19 · 退款拦截闸门（RefundCheck + /recheck）✅**
> **职责边界**：inbox-service **自身不抓店小秘**（无浏览器/无登录）。实时状态靠扩展重抓后**推送**（走 `POST /inbox/orders` 的 `refund_status`，upsert 已刷新）。`/recheck` 是**生产阶段闸门**：读订单「最后已知状态」+ 阶段 → 判定 → 落审计。
> **接口**：`POST /inbox/orders/{id}/recheck` body `{stage: typesetting|engraving|shipping, refund_status?, operator?}`（`refund_status` 传入则先刷新 `Order.refund_status` 再判定，供扩展刚重抓的新值落地）→ 返回 `{blocked, action(allow/warn/block), queried_status, stage_label, reason, check_id, checked_at}`。`GET /inbox/orders/{id}/refund-checks` 返回审计历史。
> **判定（`app/refund_gate.py`，关键词集可调）**：`已退款/取消/refund/cancel…`→**block（所有阶段）**；`风控/冻结` 或 状态缺失/unknown→**caution**，按 **D4**：排版前=warn 可继续、雕刻/发货前=block；其它真实状态→allow。⚠️ **两处判断按保守默认实现、待用户确认**：(a) 关键词集仅据现有样例归纳；(b)「风控中」当 caution（排版前放行、雕刻/发货前阻断），未当无条件 block。
> **改动文件**：新增 `app/refund_gate.py`、`tests/test_refund.py`、迁移 `app/migrations/versions/0003_add_refund_checks.py`；`app/models.py`（+`RefundCheck` 表 + `Order.refund_checks` 关系，delete-orphan 但**重发不清**审计）、`repository.py`（+`record_refund_check`/`recent_refund_checks`）、`schemas.py`（+`RecheckRequest`/`RecheckResponse`）、`routes.py`（+两端点）。**契约未改**（服务内部 API，非订单 JSON 契约）。
> **验证**：`.venv\Scripts\python.exe -m pytest -q` **48 passed**（26 旧 + 22 新）；迁移 0003 在临时库 upgrade→downgrade→re-upgrade 验证可逆。
> **跨仓待接**：flower 排版前生成入口调 `/recheck?stage=typesetting`（按 D4 仅警告）；Ezcad 雕刻前调 `/recheck?stage=engraving`（阻断）——属各自仓，本仓只提供接口。

> **2026-06-19 · 退款重抓调度（scheduler + Checkpoint）✅**
> **用户拍板「调度=重抓退款状态」**（非自动抓新单）：服务不抓店小秘，scheduler 只**按时间窗 + Checkpoint 圈出「该轮要让扩展重抓退款状态的在产订单清单」**，扫完推进游标、断点续跑不漏不重；实际重抓由扩展逐单做、回 `/recheck`。
> **规则（`app/scheduler.py`，窗口对齐订单 `received_at`，半开 `[start,end)`）**：A 当前窗口 `[now-window, now)`；B 从上次成功续 `[checkpoint.cursor, now)`（无 checkpoint=从头）；C 固定区间 `[start,end)`。`active_only` 默认排除 `STATUS_DONE`。
> **接口**：`POST /inbox/refund/scan` body `{rule:A|B|C, scope?, window_seconds?, start?, end?, active_only?, advance?}` → `{window, due:[{order_id,refund_status,status,received_at}], count, checkpoint_advanced}`。`advance=true` 把 checkpoint 推进到窗口 end（规则 B 续跑）。**纯查询不改订单**，同窗重复扫描无副作用。
> **改动文件**：新增 `app/scheduler.py`、`tests/test_scheduler.py`、迁移 `0004_add_checkpoints.py`；`app/models.py`（+`Checkpoint` 表）、`schemas.py`（+`ScanRequest`）、`routes.py`（+`/inbox/refund/scan`）。**契约未改**。
> **验证**：`pytest -q` **60 passed**（48→60，+12）；迁移 0004 临时库 upgrade→downgrade→re-upgrade 可逆；含「12:30 断、14:00 恢复，规则 B 不漏 12:30–14:00、不重 12:00」用例。

> **2026-06-19 · 退款重抓触发器 + 后台线程 ✅**
> 补齐 ③ 的两个延伸（用户指定）：**触发器（拉模式端点）+ 后台线程（仿 report_watcher）**。
> **两种 due 模型并存、各司其职**：
> - **新鲜度模型**（`scheduler.due_for_recheck`）：在产单(非 DONE) 中「从没查过 / 上次查距今超过 `recheck_interval`」= 该重抓。回了 `/recheck` 即自动掉出（限频自清，防风控）。→ **live 重抓队列**。
> - **时间窗模型**（已有 `scheduler.select_due_orders` + 规则 A/B/C + Checkpoint）：按 `received_at` 窗口 + 断点续跑。→ 显式/回补。
> **触发器（拉模式）**：`GET /inbox/refund/pending?limit&recheck_interval&active_only` → 在产待重抓清单（含 `source_url` 便于扩展定位）。扩展拉清单 → 逐单重抓 → 回 `POST /recheck`（带新状态）。**闭环不丢单**（不靠推进游标）。
> **后台线程** `app/refund_scheduler.py::RefundScheduler`（仿 `report_watcher`：factory 只造对象，main.py 起 daemon 线程）：周期 `tick_once` 刷新 due 快照 + 记日志 + 可选 `driver(ids)` 钩子（默认 None=拉模式；未来接 Playwright 自动抓取器就传 driver）。端点 `GET /inbox/refund/status`(快照)、`POST /inbox/refund/tick`(按需手动跑一轮，不依赖线程)。
> **配置**（`Settings` + 环境变量）：`FLOWER_REFUND_SCAN_INTERVAL`(线程 tick 间隔, 默认 60s)、`FLOWER_REFUND_RECHECK_INTERVAL`(重抓最小间隔, 默认 600s)、`FLOWER_REFUND_SCAN_LIMIT`(单轮上限, 默认 200)。
> **改动文件**：新增 `app/refund_scheduler.py`、`tests/test_refund_scheduler.py`；`config.py`(+3 配置)、`scheduler.py`(+`due_for_recheck`)、`factory.py`(+`app.state.refund_scheduler`)、`main.py`(+起线程)、`routes.py`(+`/pending`/`/status`/`/tick`)。**无新迁移**（未加表）。
> **验证**：`pytest -q` **67 passed**（60→67，+7）；**并跑生产入口冒烟**（temp DB）：`import app.main` 起双线程 → `/healthz`、ingest→`/pending` 列出、`/recheck?stage=engraving` 对「已退款」返回 block、`/refund/scan` rule C、后台线程 0.2s 间隔实测 tick 过、clean stop，全通过。
> **仍缺（扩展侧，非本仓）**：扩展的「定时拉 `/pending` → 逐单重抓 → 回 `/recheck`」自动循环（现仍是操作员手动 →Flower）；属扩展 + 真机活，是把本服务能力接通的最后一环。

> **2026-06-19 · 定时自动抓取 + 缓存/完整性（✅服务核心 / ⬜扩展循环+flower开关）**
> **架构硬约束**：服务**没法自己枚举店小秘新单**（页面上有哪些单只有扩展看得到）→ 增量抓发起点必在扩展；服务也不抓店小秘。
> **缓存机制本体 = manifest-diff**（用户原话「抓取前缓存+完整性验证，不全就覆盖、完整就从该时间往后」）：**缓存=DB**，**完整性校验=diff**。
>   1. 扩展定时抓列表 → 把 `(order_id + 付款时间)` 轻清单 `POST /inbox/scrape/diff`。
>   2. 服务比对 DB 回**统一 worklist**：`new`(没在库) / `incomplete`(在库但缺 items[] 或 refund_status→重抓覆盖) / `refund_refresh`(完整但退款状态过期)；**完整且新鲜的单不进清单=命中缓存、跳过=从该时间往后**。
>   3. 扩展按 worklist 逐单全量抓 → `POST /inbox/orders`（付款时间随 `extras.paid_at`）。
> **完整判据**（`scrape_planner.is_order_complete`）：`items[]` 非空 **且** `refund_status` 有值。
> **付款时间**：扩展放 `extras.paid_at`（**不动冻结契约**，用 schema 自带 extras 兜底）→ 服务 `upsert_order` 解析存 `Order.paid_at` 列（店小秘墙钟、非 UTC；`scrape_planner.parse_paid_at` 容错解析 `2026-06-19 02:25` / ISO）。
> **flower 开关**（`ScrapeControl` 表，flower 唯一要写的）：`GET/PUT /inbox/scrape/control` = `{enabled, interval_seconds, scrape_from}`；「从 T 重新开始」= PUT `restart_from` 设 `scrape_from=T`（部分更新，缺字段不动）。**flower 只写这一个开关**，扩展读它决定跑不跑/往回翻到几时。
> **拓扑**：flower → inbox-service（写开关）→ 扩展（读开关 + 拉 worklist + 抓 + 回传）。inbox-service 是唯一中转点（flower 与扩展不直接通信）。
> **改动文件**：新增 `app/scrape_planner.py`、`tests/test_scrape_planner.py`、迁移 `0005_add_paid_at_and_scrape_control.py`；`models.py`(+`Order.paid_at` 列、`ScrapeControl` 表)、`repository.py`(upsert 取 paid_at、+`get/upsert_scrape_control`)、`schemas.py`(+`ManifestEntryPayload`/`ScrapeDiffRequest`/`ScrapeControlUpdate`)、`routes.py`(+`/scrape/control` GET/PUT、`/scrape/diff`)。**契约 `order.schema.json` 未改**。
> **验证**：`pytest -q` **74 passed**（67→74，+7）；迁移 0005 临时库 upgrade→downgrade→re-upgrade 可逆；**端到端冒烟**（temp DB）跑通 `new→入库(付款时间落地)→refund_refresh→/recheck→命中缓存掉出` 全循环。
> **仍缺（要接通这条链）**：① ✅ **已完成（2026-06-19）扩展自动循环**（见下「2026-06-19 扩展自动抓取循环」块）。② **flower**：一个「自动抓取开关（开/关+间隔）+ 从某付款时间重新开始」UI，写 `PUT /inbox/scrape/control`（**未做**）。③ 「从 T 往后」目前只作扩展翻页下界用，服务端**未按 paid_at 过滤/自动推进游标**（diff 每轮全量比对即保证完整性，足够正确；自动推进是后续优化）。④ 扩展只抓**当前可见页**、未做翻列表回 `scrape_from` 的分页（v1 增量靠新单出现在首页；回补历史需翻页，属增强）。

> **2026-06-19 · 扩展自动抓取循环 ✅（逻辑已测 / chrome 胶水待真机）**
> **MV3 架构约束**：内容脚本能读 DOM 但其 `fetch` 用店小秘源 → 被服务 CORS 挡；故**抓取在内容脚本、HTTP 全经 service worker**（沿用 `client.ts`）。定时器放内容脚本（自重排 `setTimeout`，页面在就跑、刷新自重启）。
> **一轮流程**：内容脚本 `collectOrders(document)`（含 `paid_at`）→ 消息 `FLOWER_AUTO_CYCLE` 给 SW → SW 跑 `runAutoCycle`：读 `/scrape/control`（关则跳过、按返回间隔回探）→ 上报 manifest `POST /scrape/diff` → 对 worklist 命中本页的单逐个 `POST /inbox/orders`（`paid_at` 进 `extras.paid_at`）→ 回 `{enabled,intervalSeconds,pushed,failed,skipped}` → 内容脚本据 `intervalSeconds` 排下一轮、有推送弹 toast。
> **付款时间抓取**：时间轴 `.order-time-list` 里「付款：<time>」那项 → `RawOrder.paid_at`（`extractor.readPaidAt` + 选择器 `orderTimeItem`/`PAID_LABEL`）。**真实 4MB 页实测**：5 单中 4 单抓到付款时间、第 5 单（4002659188 风控中）**只有「下单」无「付款」→ paid_at 合理为空**（未付款单天然如此，下游按缺省处理）。
> **改动文件**：扩展 `src/extractor/selectors.ts`(+`orderTimeItem`/`PAID_LABEL`)、`extractor.ts`(+`readPaidAt`、order 带 `paid_at`)、`shared/contract.ts`(+`RawOrder.paid_at`/`ScrapeControl`/`WorkItem`/`ManifestEntry`)、`worker/client.ts`(+`getScrapeControl`/`postScrapeDiff`、`postOrder` 把 `paid_at` 塞 `extras`)、新增 `worker/auto_cycle.ts`(纯编排 `runAutoCycle`/`buildManifest`)、`worker/service-worker.ts`(+`FLOWER_AUTO_CYCLE` 处理)、`content/content.ts`(+自重排循环)；夹具 `fixtures/dianxiaomi-order-multi.html` 加时间轴；新测试 `worker/auto_cycle.test.ts`。**契约未改**。
> **验证**：`npx vitest run` **18 passed**、`tsc --noEmit` 通过、`vite build` 通过；纯逻辑（buildManifest/runAutoCycle 开关关-跳过/命中推送-计数/离页跳过）已单测覆盖。
> **✅ 真机已验（2026-06-19）**：在真实店小秘「全部订单」页加载 `dist/` + 隔离验证服务实例（8770，临时 DB + sandbox 目录 + test_reset，生产 inbox.db/outputs 全程不碰）跑通**整条链**：内容脚本抓本页 → SW `/scrape/diff` → 逐单 `POST /inbox/orders` → **99 真实单**落 `_verify/sandbox/inbox`，每单含 `items[]`（product_sku/quantity/personalization_raw/extras{listing_url,price,thumbnail}）、`refund_status`（**字节级核对 = 已审核 等，UTF-8 正确**，先前 console 花屏是 cp936 误读）、`extras.paid_at`（真实付款时间）；后台 refund 调度也 tick 过。验完已停实例、删 `_verify`、8770 释放。
> **真机发现（调优项，非阻塞）**：
> 1. ✅ **已修复**：~~complete 单每轮被重推~~。`diff` 现在把 `Order.updated_at` 也算进新鲜度（`scrape_planner._ingested_within`）——自动循环重抓入库一单即视为「退款状态已刷新」，`recheck_interval` 内不再 `refund_refresh` 重推；超期才再推一次刷新。改 `app/scrape_planner.py::diff_manifest` + `tests/test_scrape_planner.py`（83 passed）。
> 2. **thumbnail 抓到的是懒加载占位图**（`data:image/gif;base64,...` 1×1），非真实 CDN 图——「其他商品」展示要真图得在元素进视口后再抓（或抓 `data-src`）。
> 3. **`shop` 在「全部订单」页抓到 null**（`col_115` 选择器是按「待处理」页校准的，全部订单页表头列位可能不同）——shop 可选、不阻塞，要用得在全部订单页补校准。
> **仍属真机待观察**：长时间运行的推送节奏对店小秘风控的影响（发现①已修，再视情况调 `FLOWER_REFUND_RECHECK_INTERVAL`）。
>
> **生产 DB 迁移 + 服务现状（2026-06-19）**：生产 `inbox-service/inbox.db` 原停在最早 schema（仅 orders、12 单、无 alembic_version；另被某次 create_all 建了 4 个空新表但 orders 没补列）。已：删 4 个空表 → `alembic stamp 0001 && upgrade head` 干净迁到 **0005**（orders 补 refund_status/paid_at、4 表重建、**12 单保留**），备份在 `inbox.db.bak-20260619`。当前 8770 跑**当前代码**（`production_retry`、生产目录、**自动抓默认关 enabled=false**，等 flower UI 开）。⚠️ 服务由本会话后台起，会话结束可能停——持久运行用 `启动服务.bat`（同一份当前代码 + 已迁移 DB）。
> ⚠️ **注意 create_all vs 迁移漂移**：服务 `init_db` 用 `create_all`（建缺失表、**不 ALTER 既有表**），而新列（refund_status/paid_at）只有迁移会加。对**已存在**的旧 DB，必须跑迁移补列，否则 create_all 起来也会因缺列报错。新库 create_all 直接全 OK。

> **2026-06-19 · 真机测试一版（报告：`docs/real-machine-test-2026-06-19.md`）**
> 隔离实例真机跑通：**99 单**全带 `items[]/refund_status/paid_at` 落 sandbox；**「重推」修复已验证消除**（72s/多周期 `pushed_last22s=0`、99 单 `updated_at` 全在 0.7s 窗、库内清单重放 diff `worklist=0`）；`5xx=0`。
> **⚠️ 待修缺陷 D-1（下次迭代）**：**空 `remark` 单被服务 422 拒收**（111 次 POST 里 12 次 422，`remark` `min_length=1`）。根因=列表页无定制备注的单 `buildRemark` 返回 `''`，而**自动循环 `runAutoCycle→pushOrder` 没像手动 `sendOrder` 那样守卫空 remark**，照发 → 422。修复选项见报告（倾向：扩展侧过滤空 remark，或走协调线把 `remark` 改可选——`items[]` 已能独立承载）。次：纯空白 remark 能过校验（min_length 不 strip）。
> **测试收尾**：隔离实例已停、`_verify2` 已删；生产服务以当前代码 + 已迁移 DB + 安全默认（`production_retry`、自动抓 `enabled=false`）重启在 8770（本会话后台起，持久请用 `启动服务.bat`）。

> **2026-06-19 · 定向重抓握手 + 扩展店小秘搜索（option B，Ezcad 确认导入前现搜现抓）✅服务+扩展逻辑 / ⬜Ezcad GUI 接线 / ⬜真机**
> 用户拍板 option B：Ezcad 确认导入前要某单**新鲜**退款状态 → 让扩展去店小秘**按订单号搜索并重抓该单**（扩展原来纯被动只读当前页，无搜索能力）。
> - **服务**：内存定向重抓队列 `app/rescrape_queue.py`（秒级 TTL，不建表/无迁移）+ 4 端点 `POST /inbox/refund/rescrape/request`、`GET …/queue`、`POST …/result`、`GET …/status/{id}`；result 带 refund_status 时顺手刷 `Order.refund_status`。`config.refund_rescrape_ttl`（env `FLOWER_REFUND_RESCRAPE_TTL`，默认 60s）。`pytest` **98 passed**（+10）。
> - **扩展**：`extractor/dianxiaomi_search.ts`（搜索页交互：`#orderSearchInput` 填值走原生 setter+input 事件、点「搜索」按钮 `button.ant-btn-primary[type=submit]`；**搜索结果仍是 vxe-table → 复用 collectOrders**）；`worker/rescrape.ts::runRescrapeJobs`（纯编排：不在搜索页→skip 保留队列；找到+有状态→pushOrder 刷新+回填 done；搜不到/无状态→从严 not_found）；`worker/client.ts`+`getRescrapeQueue`/`postRescrapeResult`；`service-worker.ts`+两消息；`content.ts`+3s 轮询（仅搜索页实际处理）。选择器按**真实样例 `Desktop\店小秘--搜索订单.txt`** 校准（搜索框是 antd、结果是 vxe）。`vitest` **39 passed**（+14）、tsc/build 通过。
> - **拓扑**：Ezcad 入队 → 扩展（在店小秘搜索页）拉 `/queue` 逐单搜+抓 → `/inbox/orders` 刷新 + `/result` 回填 → Ezcad 轮询 `/status/{id}` 拿 done/not_found/expired。**扩展必须开着店小秘搜索页 + 登录态**；不在搜索页则单留 pending、Ezcad 超时按 D4 阻断。
> - **✅ Ezcad 全链已接（2026-06-19）**：`inbox_client` 加 `request_rescrape`/`rescrape_status`/`recheck_fresh`（现搜现抓→轮询 done 才 recheck，超时/not_found/expired/入队失败一律从严 ok=False→阻断）；`app.py` 确认导入闸门改后台线程跑 recheck_fresh + 「正在核对店小秘退款状态…」进度弹窗（用户拍板），**只确认导入前用 fresh**，扫码后即核对保持 last-known。Ezcad 全量 **119 绿**。详见 Ezcad `CURRENT_TASKS.md`。
> - **⬜ 仅剩真机**：起 8770 + 扩展 dist 加载到店小秘搜索页 + Ezcad 开退款检查，验证整链。
> - **⚠️ 真机校准**：搜索选择器据单份静态样例定，店小秘改版/AB 测易失效；搜索会**劫持操作员的店小秘页**（确认导入瞬间，店小秘在后台尚可接受）；长期搜索频率对风控影响待观察。
> - **✅ 对抗审查修复(2026-06-19,workflow 5 维裁决)**：🔴**超时预算契约(冻结,改一仓必同步另两仓)**=Ezcad recheck_fresh timeout **15s** / 扩展 `content.ts RESCRAPE_POLL_SECONDS` **3→1s** / searchAndExtract deadline 6s——否则正常单假阴性阻断；服务 `rescrape_queue.resolve` found+空状态→降级 not_found（done⟺有状态硬不变量）；扩展搜索按钮只精确匹「搜索」否则回车兜底、`setNativeValue` 用 InputEvent、不在搜索页一次性 console.warn。`pytest 98 / vitest 39 / tsc / build` 全绿。
> - **✅ 真机点验(Ezcad 侧)**：8770 原服务挂死(=最初 Ezcad「连接失败:timed out」根因)已重启修；源码 Ezcad 点导入走 recheck_fresh 后台线程+进度弹窗(不冻 GUI)、15s 超时 fail-safe 阻断+清晰排查文案。
> - **✅✅ happy-path 真机全链路验通(2026-06-19,真单 4090728276=已退款)**：Ezcad 确认导入 → recheck_fresh 入队 → 扩展在店小秘「已退款」页**可见单直接读**到 4090728276=已退款 → 回填(state=done) → /recheck → Ezcad 判 REFUNDED → **硬阻断「订单 4090728276 已退款」**。
>   - **🔴 真机抓出并修了一个会放行退款单的致命契约 bug**：服务 `/recheck` 响应原只有 `queried_status`、**无 `refund_status`/`items`**；而 Ezcad `inbox_client._parse` 读 `refund_status`→拿到 None→`from_raw(None)=NONE`→**误放行**。单测假夹具恰好用了 `refund_status` 键(=应有的样子)故没暴露，**真机第一次点就误放行了**。修：`RecheckResponse` + `recheck_order` 加 `refund_status`(=queried_status 别名) + `items`(订单行项目)。新增护栏 `test_recheck_response_carries_refund_status_and_items`，`pytest 99`。
>   - **扩展改进(真机驱动)**：操作员常待列表页而非搜索页 → `searchAndExtract` 改**先读当前页可见单、不可见再用搜索框**；`canSearch` 放宽为「有搜索框 或 有订单行」。`vitest 40`。
>   - **✅ 正常单放行也真机验通(真单 4095138255=已审核)**：脚本驱动 recheck_fresh(扩展 0.5s 内从店小秘读到)→ refund_status=已审核 → `/recheck(engraving)` action=**allow**、blocked=False、reason「订单状态『已审核』正常，放行」;扩展正确抓定制(`Jun-Rose/Font2/Chrissi❤️`)。**两条路全通：退款单拦、正常单放。**(注:正常单脚本驱动了协议链；Ezcad GUI 那层 4090728276 已点验，故未再点 GUI。)
>   - **测试残留(可忽略/可清)**：生产 DB 多 4090728276(已退款)/4095138255(已审核) 两条,benign;两者收件夹 json 已删。

> **2026-06-19 · D-1/D-2 修复（契约放宽 remark）+ 退款重抓闭环接通 ✅（逻辑已测 / chrome 胶水 + 真机待跑）**
> **用户拍板**：① 范围=接通退款重抓闭环（含 D-1/D-2）；② D-1 修法=**进系统、改契约**（remark 改可选，数据由 items[] 承载）。
>
> **D-1/D-2（契约变更，用户授权走此线）**：remark 从必填改为**可选、可空串、永不为 None**。
> - 契约 `contracts/order.schema.json`：`required` 去掉 `remark`；`remark.minLength` 1→0；**`schema_version` 仍 1.0**（放宽必填、向后兼容：带 remark 的老 JSON 照常通过）。
> - 服务 `app/schemas.py::OrderPayload`：`remark: str = Field(default="", max_length=5000)` + `@field_validator(mode="before")` 把 None/缺省→`""`、字符串 strip（**一并修 D-2**：纯空白不再当有效备注）。
> - **无 DB 迁移**：`Order.remark` 仍 `Text NOT NULL`，空单存 `""`（不破 NOT NULL）；`batch_exporter` 写空串无碍。
> - 测试：新增 `tests/test_remark_optional.py`（5 例：空 remark+items / 完全不带 remark / 纯空白归一 / strip / 回归）；旧 `test_ingest_rejects_missing_remark` 改为 `test_ingest_accepts_missing_remark`（缺 remark→200）。`pytest -q` **88 passed**（83→88）。
>
> **✅ 跨仓 flower 侧已改（2026-06-19 同会话，用户授权直接在 flower 仓做）**：`flower/order_importer.py::_load_order_from_json` 空 remark 不再 `raise`——回退 `items[].personalization_raw` 拼备注（多盒子按行 " / " 连接）；标品/无定制单 items 无定制原文则 remark 仍空但**照常载入**（订单进系统，操作员据此判断无需生成），仅「既无 remark 又无 items」的真空文件才报错（沿用老约定挪走、不堵队列）。下游 `_auto_load_order` 对空 remark 安全（`run_background`+`on_error` 兜异常、空解析结果有「未识别到订单」兜底）。新增 4 测试（`flower/tests/test_order_importer.py`，**10 pass**）。权威计划已记契约变更（见 staged-wren.md「契约变更记录 2026-06-19」）。
> **遗留观察（非阻塞）**：标品单空 remark 若 `inbox_autoparse=on` 会触发一次「无收获」GPT 解析（显示「未识别到订单」），浪费一次 API 调用但无害；可选优化=空 remark 跳过 autoparse（属 flower UI，未做）。
>
> **退款重抓闭环（扩展，AGENTS 多处记的「最后一环」）**：服务侧端点早已就绪（`GET /inbox/refund/pending` + `POST /recheck`），本次把**扩展自动循环**接上。
> - `worker/auto_cycle.ts::runAutoCycle` 在 worklist 推送后追加 `runRefundRecheck`：拉 `/refund/pending` → 对**本页可见**的在产单，把本页实时 `refund_status` 回 `POST /recheck`（`stage=typesetting`、`operator=auto-recheck`）→ 该单记一条 RefundCheck，`recheck_interval` 内自动掉出 pending（自清、不重刷）。`CycleResult` 加 `rechecked`/`recheckBlocked`。
> - **设计取舍（已定、可调）**：(a) 闭环用 `stage=typesetting`（最宽松、非不可逆阶段）+ `operator=auto-recheck`（审计里区分真人产线闸门）；真正的产线闸门仍由 flower/Ezcad 在各自阶段调 `/recheck`。(b) 仅对**本页可见**的在产单重抓，不在本页的本轮跳过（翻页是后续增强，与 scrape 一致）。(c) 本页没抓到实时状态的单不回 `/recheck`（留待下轮）。(d) **闭环受 `/scrape/control` 同一开关 gate**（关则不跑）。(e) recheck 全是**本地 POST（127.0.0.1:8770）**，不增加店小秘 facing 流量（无新风控风险）。
> - `worker/client.ts` 加 `getRefundPending`/`postRecheck`、`postOrder` 空 remark 不带（走 undefined）；`service-worker.ts` 接线两 dep；`content/content.ts` 放宽手动「→Flower」守卫（`order_id && (remark || items)`）+ 检测到退款 block 弹红色告警。
> - 测试：`worker/auto_cycle.test.ts` 加 7 例（空 remark+items 推送 / 真空单跳过 / 闭环回真实状态 / block 计数 / 不在本页或无状态不回 / 关时不跑 / pending 抛错不影响抓取）。`npx vitest run` **25 passed**（18→25）、`tsc --noEmit` 通过、`vite build` 通过。
>
> **仍待真机（未做）**：① 真实店小秘页加载新 `dist/` 复核闭环（pending→recheck、block toast、空 remark 标品单不再 422）。**flower order_importer 空 remark 回退已改完（见上 ✅）**，故开自动抓不再会让 flower 对标品单报错；生产服务/DB 现状未变（仍 0005、自动抓默认关）。
>
> **⚠️ 订正（2026-06-19）：flower 自动抓开关 UI 其实「已做好」**（之前本文件多处误记「未做」）——是根 AGENTS 提到的「他人未提交改动」里已落地的：`flower/inbox_service_client.py`（urllib HTTP 客户端，6 测试）+ `ui_app.py::_build_fetch_panel`「抓取订单」面板（挂**操作员配置端**：开始/停止=PUT enabled、设置=间隔+服务地址、定时锁=restart_from 应用/清空、刷新、状态行=healthz+control+当前单）+ `test_ui_app.py` 状态文案测试。**均为未提交改动**（`git log` 查无 inbox_service_client 历史）。
> **本会话已真机验证（只验不改码，用户指定）**：隔离实例（临时 DB/目录 + 8771）+ flower 真实 `inbox_service_client` 跑通完整序列——health / GET 默认 off / 开始(PUT enabled=True) / 设置(interval) / 定时锁应用(restart_from) / 清空 / 非法时间→422 可读 / 停止(enabled=False)，8/8 通过，生产未碰、实例已拆。**✅ 真机 GUI 也已点验（2026-06-19，computer-use）**：隔离实例（系统 python + FLOWER_INBOX_PORT=8771）下进「操作员配置端→抓取订单」实际点按——开始(关→开)/定时锁应用(scrape_from=2026-06-19T02:25:00)/停止(开→关)/清空(→—)全部实时写通隔离服务，状态行全程「已连接 8771」；验完隔离实例/服务停、config 还原、生产收件夹 4 文件未动。
> **✅ 小缺口已修（2026-06-19）：服务地址持久化**。原先「抓取设置」改服务地址只存内存、重启回落默认 8770；现加 `AppConfig.inbox_service_url`（config_store load/save）+ ui_app 启动读它、设置保存时 `save_config` 写回。空=回落客户端默认 127.0.0.1:8770，旧配置零感知。测试：`tests/test_config_store.py` +2 例（31 passed）。

> **2026-06-19 · 运行模式隔离（④ / D3，服务侧）✅**
> 用户定的范围：inbox-service 加运行模式，**只管服务自己写的输出**（收件夹 `{order_id}.json` + 批量 `xlsx`）；SVG/DXF/PNG 的版本/覆盖归 flower。
> **两模式**（`app/run_mode.py`，存 `app.state.run_mode`，**重启回落默认=安全**、不持久化以防误留测试态）：
> - `production_retry`（默认）：写生产目录；批量 xlsx 时间戳命名、同秒同名追加 `-vN` **不覆盖**；收件夹 json 幂等覆盖。
> - `test_reset`：写 **sandbox 目录**（`Settings.sandbox_dir`，默认 `inbox-service/sandbox`，env `FLOWER_SANDBOX_DIR`）、进入时清旧；**生产 `outputs/` 一个文件都不碰**（计划 §8 的核心诉求）。
> **⚠️ 设计约束（非猜测、已在代码注释）**：inbox `{order_id}.json` 文件名是 Flower 轮询的键，**不能版本化改名**（否则破坏 *.json 取单约定）→「版本递增」只落批量 xlsx 与 flower 的生成产物；收件夹 json 在两种生产模式下都保持幂等覆盖。
> **端点**：`GET /inbox/run-mode`（当前模式 + 生效目录）、`PUT /inbox/run-mode {mode, reset_sandbox?}`（切模式；test_reset/reset_sandbox 清 sandbox 旧文件）。ingest 与 batch/export 均按 `run_mode` 路由到生效目录。
> **改动文件**：新增 `app/run_mode.py`、`tests/test_run_mode.py`；`config.py`(+`sandbox_dir`+两 property+env)、`batch_exporter.py`(同名 `-vN` 不覆盖)、`factory.py`(默认 `run_mode`)、`routes.py`(+两端点、ingest/export 走生效目录)、`schemas.py`(+`RunModeUpdate`)、`tests/conftest.py`(测试 settings 加 tmp `sandbox_dir`)。**无迁移**（运行模式是运行态，sandbox 是配置）。
> **验证**：`pytest -q` **83 passed**（74→83，+9）；含「test_reset 写 sandbox、生产收件夹零文件」「切回生产不漏测试单」「同秒同名 xlsx 不覆盖出 -v2」等护栏。
> ⚠️ 逐单进详情页比列表页更慢、选择器更易随店小秘改版失效、访问量大易触发风控——需限频/串行/失败降级，详情页选择器单独维护一套。

## 背景
把店小秘网页订单自动喂进 flower 桌面端（CustomTkinter）生成 SVG/DXF/PNG。**方案 D 分阶段**，一期 =
Chrome 扩展 + 本地服务 + Flower 收件夹监听 + 接 Flower 现有批量生成。二期（Playwright 全店批量）未开工。
完整设计：`C:\Users\Administrator\.claude\plans\majestic-pondering-liskov.md`。

**两道校验**：闸1=入库（服务 Pydantic 校验）；闸2=生成（Flower 现有 `generate_batch` 出 `report.xlsx`，
把无法自动生成的标记进表）。
⚠️ `services/api` 的 **HTTP 服务**是已暂缓 web 分支的（**别启它**）；但其 `app.domain.orders.*`（批量/报告）
被桌面端当**库** in-process 调用，是 live 的——批量路径就复用这套。

## 组件 & 状态
- `contracts/order.schema.json` — 三方合同（`schema_version`/`order_id`/`remark` 必填）。✅ M1
- `inbox-service/` — 独立小服务 FastAPI + SQLite + SQLAlchemy + Alembic。✅ M3+M4，**88 tests pass**（2026-06-19 加 items/refund_status + 退款拦截闸门 + 退款重抓调度 + 触发器/后台线程 + 定时自动抓取缓存核心 + 运行模式隔离 + D-1/D-2 remark 可选后，见顶部块）。
  独立 venv：`automation/inbox-service/.venv`（py3.12）。
  - 端点：`POST /inbox/orders`（校验+去重 upsert+原子写收件夹）、`GET /inbox/orders[/{id}]`、
    `POST /inbox/orders/{id}/recheck`（生产阶段退款拦截闸门）、`GET /inbox/orders/{id}/refund-checks`（审计历史）、
    `POST /inbox/scrape/diff`（自动抓取缓存/完整性核心：清单→统一 worklist）、`GET/PUT /inbox/scrape/control`（flower 自动抓开关）、
    `GET/PUT /inbox/run-mode`（D3 运行模式：test_reset sandbox / production_retry）、
    `POST /inbox/refund/scan`（时间窗调度：规则 A/B/C + Checkpoint）、`GET /inbox/refund/pending`（触发器：拉 live 重抓队列）、
    `GET /inbox/refund/status`（后台线程快照）、`POST /inbox/refund/tick`（按需手动跑一轮）、
    `POST /inbox/batch/export`（把池中订单导出店小秘格式 xlsx）、`POST /inbox/batch/sync`（读 report.xlsx 回写状态）、`GET /healthz`。
  - `report_watcher` 后台线程（`main.py` 启）轮询 `outputs/reports/*-report.xlsx`，
    EXPORTED→`DONE(已完成)`，BLOCKED/NEEDS_REVIEW/FAILED/需人工→`CANNOT_AUTOGEN(无法自动生成)+原因`。
  - `refund_scheduler` 后台线程（`main.py` 启）周期算「该重抓退款状态」的在产单，刷新 due 快照供 `/refund/status`；扩展拉 `/refund/pending` 逐单重抓回 `/recheck`。
  - 状态机：RECEIVED→VALIDATED→WRITTEN_TO_INBOX→QUEUED_FOR_BATCH→DONE / CANNOT_AUTOGEN。
- **Flower 侧**（仓库根 `config_store.py` / `ui_app.py`）✅ M2，`tests/test_inbox_poller.py` + `test_config_store.py` pass：
  - config 加 `inbox_folder` / `inbox_autoparse`（空=功能关，旧配置零感知）。
  - `ui_app` 收件夹轮询 `_start_inbox_poller` / `_poll_inbox_once` / `_auto_load_order` / `_move_inbox_file_to_processed`：
    自动载入备注 → 自动解析 → **停在生成前**，处理过的文件移入 `inbox/processed/`。绝不自动生成。
- `extension/` — ✅ M5 已建（Chrome MV3 + TS + Vite/@crxjs + Vitest）。**Vitest 25 passed（含 2026-06-19 items[]/refund_status/付款时间 + 自动抓取循环 + D-1 空 remark + 退款重抓闭环逻辑）+ `npm run build` 产出 dist/ + typecheck 通过**。
  手动「→Flower」单发仍在（守卫已放宽：有订单号且 remark 或 items 即可发）；**自动抓取循环**（内容脚本定时 → SW `/scrape/diff` + 逐单推送）+ **退款重抓闭环**（拉 `/refund/pending` → 本页可见在产单回 `/recheck`）——均由 `/scrape/control` 开关 gate、逻辑已测、chrome 胶水待真机（见顶部对应块）。
  selectors **已按真实「待处理」列表页校准**（vxe-table：一单两行 `<tr>`，rowid 配对；订单号 `.orderCode span.pointer`；
  备注=买家定制项 `.order-sku__attr > div` 规整成单行；店铺 header `td[colid="col_115"]`；
  「AI未识别」= header 行 `i.icon_brush_bill`/酒红标记块）。content 给每个订单行注入「→Flower」按钮（AI未识别标红），
  点哪单发哪单（MutationObserver 重注以抗 vxe 重渲染；带控制台诊断 `[Flower` + 就绪 toast）。夹具用了真实 3 单数据。
  ✅ 2026-06-18 真机：扩展按钮已在真实「待处理」页出现并成功发送（→服务→收件夹写出 {order_id}.json）。`p.ele-p` 卖家备注恒空，故备注取买家定制项。

## AI 识别状态对账（2026-06-22，本次迭代）

**背景/动机**：用户要扩展「读到订单号后做判断」——以 DB 为唯一权威对账店小秘的 AI 标记，带防自动降级 + 冲突检测。
此前 AI 状态只由 `mark_jobs` 队列推导、无单一权威字段，也没有「人工锁定/复核」态。

**核心设计（用户拍板）**：
- 词汇映射：`待AI识别`=店小秘标记「AI未识别」(icon_brush_bill)；`AI已识别`=「AI已处理」(icon_change_order)。
- 新增 **`orders.ai_status` 权威列**（`pending`/`recognized`/`conflict`/`locked`），`mark_jobs` 退化为「把权威态写回店小秘」的执行队列。`locked`(人工锁定) 本期**不设触发**，是保留态（语义同 recognized 不降级）。
- 复核(`conflict`) = DB 标态 + flower 配置端「只看复核」筛选 + 提示 + 人工裁决；其间扩展冻结该单标记。

**对账判定（`repository.reconcile_ai_status`，原子 get-or-create + 判定）**：
- 查库失败 → **不改标签**（端点 fail-closed 返回 desired=none；扩展 client 非2xx 返回 null→跳过）。
- 存在 recognized/locked → desired=recognized（**绝不降级**回未识别）；存在 conflict → desired=none（冻结）。
- 存在 pending + 页面已带「AI已处理」→ 判 conflict（边缘A，不降级）；否则 desired=pending。
- 不存在 + 页面已带「AI已处理」→ 原子建 conflict（边缘B，不直接改未识别）；否则原子建 pending 桩单。
- **软删单不自动复活**（desired=none 冻结，恢复需重新上传走 upsert）。
- 不变式：「AI未识别」与「AI已处理」不得共存（扩展 `targetForDesired` 强制互斥 + 防降级守卫）。

**本次改动（三仓）**：
- inbox-service：`models.py`(ai_status 列+常量+to_dict)、迁移 `0011`(加列+回填 active mark_done→recognized+索引，**已验证可逆**)、`repository.py`(`reconcile_ai_status`/`set_ai_status`/upsert 新单置 pending)、`routes.py`(`POST /inbox/ai/reconcile`，并发 IntegrityError 重试+异常 fail-closed；`mark_done`→`set_ai_status recognized`)、`schemas.py`(`AiReconcileBody`)、`config.py`(`ai_reconcile_enabled`/`FLOWER_AI_RECONCILE_ENABLED` 总开关)。端点受 `action_allowed(ACTION_MARK)` + 总开关 gate（fail-closed，不创建桩单）。
- extension：`contract.ts`(AiStatus/DesiredTag/ReconcileDecision)、`client.ts`(`reconcileAiStatus`，查库失败返回 null)、`service-worker.ts`(`FLOWER_AI_RECONCILE`)、新 `worker/ai_reconcile.ts`(`runReconcile`+`targetForDesired`，纯编排可单测)、`content.ts`(runMarkOnce 内 mark 队列回写后跑对账，**共用单例弹窗 + markBusy 守卫**，每轮 writeLimit=3/queryLimit=25)。
- flower：`ui_app.py` `ai_status_style`(复核/人工锁定标签)、`order_row_view` 消费 ai_status(recognized/pending 无 mark 历史时权威态兜底显示)、配置端订单表「只看复核」筛选 + 复核提示行 + 复核行专用橙 tag。

**契约/落点**：与 `docs/2026-06-20-mark-writeback.md` 的标记回写共用同一套弹窗机制；本特性新增的 `/inbox/ai/reconcile` + `ai_status` 列是其「上游权威源」。改判定逻辑只动 `repository.reconcile_ai_status`（有 `tests/test_ai_reconcile.py` 护栏）。

**测试状态**：inbox-service `tests/test_ai_reconcile.py` 16 条 + 全套 **176 passed**（1 个**既有** flaky `test_refund_scheduler.py::test_pending_endpoint_drains_after_recheck` 退款调度 timing，与本次无关，偶发，建议后续修）；extension **138 vitest / tsc / build** 全过；flower 相关纯函数 9 条 + `test_ui_app.py` **96 passed**（8 个既有 headless GUI 失败不变）。经 4-agent 对抗审查并修复 6 项（并发原子性/端点 fail-closed/软删不复活/flower 权威态显示/复核 tag 区分/set_ai_status 文档）。

**已知/待办**：① **真机手测待用户**：起 8770 + 重载扩展 dist + 开采集任务 → 看新单建 pending 并打「AI未识别」、生成→recognized 同步「AI已处理」、人造冲突单进复核且配置端「只看复核」能筛出。② reconcile 会给授权任务窗内每个可见单建 pending 桩单（remark 空，真实上传时 upsert 补全）——配置端会多出薄行，可按 ai_status/空 remark 区分（决策 D，用户已认可）。③ 人工裁决解冲突目前靠 `set_ai_status`（无 UI 按钮），flower 复核列只「看+筛」，**裁决动作 UI 待后续**。

## 怎么跑 / 怎么测
- 服务：`cd automation/inbox-service`；起服务 `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8770`；
  测试 `.\.venv\Scripts\python.exe -m pytest -q`。环境变量可覆盖 `FLOWER_INBOX_DIR/FLOWER_REPORTS_DIR/FLOWER_BATCHES_DIR/FLOWER_INBOX_DB/FLOWER_INBOX_PORT`。
  - 门店一键起：双击 `automation\启动服务.bat`（用 inbox-service 的 `.venv` 跑同一份代码，窗口保持打开=服务在跑，关窗即停）。
    ⚠️ **坑（2026-06-22 修过）**：① 旧版重复双击会撞端口报 `WinError 10048`（8770 已被上次没关的实例占着）——脚本现已在启动前自动 `taskkill` 占用 8770 的旧 PID，可放心重复点。② 旧版 echo 里 `->` 的 `>` 被 cmd 当重定向，开窗时打印 `The filename ... syntax is incorrect`（无害纯显示）——已转义成 `-^>`。若服务“启动不了”先确认不是又有一个实例在跑（`netstat -ano | findstr :8770`）。
- Flower 单单链：`birth_flower_config.json` 的 `inbox_folder` 必须填**绝对路径**（如 `C:\\Users\\Administrator\\Documents\\flower\\outputs\\inbox`），启动 `birth_flower_mvp.py`。
  ⚠️ **坑（2026-06-18 踩过）**：默认 `Path("")` 存盘会变成 `"."`，而代码把 `""`/`"."` 当「功能关」→ 必须显式填绝对路径，否则 Flower 不监听。
  行为：**一次只载一单**（`_inbox_active` 挂起），自动解析、停在生成前；点「生成」成功后 `_advance_inbox_after_generate` 把该单移入 `processed/` 并自动放行下一单。**改完务必完全关 App 重开再测。**
- Flower 测试（仓库根）：`PYTHONPATH=".;services\api" .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q`。
  注：7 个 `test_ui_app.py` 无头失败是**分支既有问题**（`case_button` 无头未建 / 控制台中文乱码），与本工作无关。

## 待办 / 已知问题
- ✅ **D-1/D-2 已修复（2026-06-19，本次迭代）**：用户拍板「进系统、改契约」——remark 改可选/可空串、strip 归一。详见上方「D-1/D-2 修复」块。**跨仓 flower `order_importer` 空 remark 回退 items[] 也已改完**（同会话、用户授权直接在 flower 仓做，10 测试 pass）；故开自动抓不再会让 flower 对标品单报错。生产仍维持自动抓 `enabled=false`（flower 自动抓开关 UI 已存在且本会话已真机验证链路，见上「订正」块；开不开由操作员在「操作员配置端→抓取订单」点）。
- ✅ **退款重抓闭环已接通（2026-06-19，本次迭代，逻辑已测/真机待跑）**：扩展 `/refund/pending`→逐单回 `/recheck` 自动循环已在 `auto_cycle.ts` 落地。详见上方「退款重抓闭环」块。
- **扩展 selectors 已按真实 vxe 列表页校准**（用户 2026-06-18 提供 `店小秘--待处理.html`，含 3 个「AI未识别」单 4093542955/4093587551/4093606621）；7 个 Vitest 夹具断言通过。✅ **2026-06-19 真机已验**：`dist/` 在真实「全部订单」页自动循环跑通、99 单落库（见 `docs/real-machine-test-2026-06-19.md`）。
- ⚠️ 这些是「AI未识别」单，Flower 端 GPT/本地解析器能否把 `Choose Your Birth Flower: Jun - Honeysuckle / Font Design: Font 3 / Personalization: Esther` 正确解析出 月/花/字体/名字，需真机看（属 Flower 解析质量，非扩展职责）。
- ⚠️ **批量引擎落后风险**（plan 风险①）：批量走 `services/api` 引擎，可能与桌面单单出件不一致 → 冒烟时**用真单核对**。
- 「无法自动生成」失败表只来自**批量路径**；单单路径只有解析提醒弹窗。
- 端到端冒烟 `docs/inbox-smoke.md` 已写；服务**真·起服务冒烟通过**（起 uvicorn → POST → 文件落地 → 列表）；Flower GUI + Chrome 全链待用户真机跑。
- 「哪个店小秘单号当 order_id」未定（订单号/平台单号/系统单号），其余进 `extras` 便回退。

## 注意
- 根 `AGENTS.md` / `CURRENT_TASKS.md` 当前有**他人未提交改动**，本次自动化工作**未碰**它们；automation 的交接全在此文件。
