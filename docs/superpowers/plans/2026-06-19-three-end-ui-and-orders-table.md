# 三端 UI 精修 + 操作员配置端订单表 + 定时抓取时间选择器（2026-06-19）

> 状态：配置端核心 + 管理员端 IP 标识**已实现并单测通过**；操作员端细微视觉（图层行图标/解析结果上色）**已搁置**（避动 WYSIWYG/金标核心路径）。真机手测待做（需重开 App）。
> 配 `AGENTS.md` 顶部「当前事实」一起读。是对 `2026-06-17-operator-admin-role-split.md` 三端拆分的**界面落地 + 配置端重定位**。

## 0. 背景与触发

用户在「操作员配置端」发现：①「定时锁」语义误导（实为 restart_from，不是锁）；②方框是手填文本、应为时间选择器；③配置端不该显示画板/图层；④需要"订单状态可视图"。据此把**配置端从"资源库配置 + 强塞画板"重定位为"抓取调度 + 订单监控控制台"**，并把三端统一成同一套深色精修视觉。

## 1. 三端定位（落地后）

| 端 | 中心区 | 右侧功能区 | 切端标识 |
|---|---|---|---|
| 操作员端 | 实时画板（编辑器） | 订单信息·解析结果·图层·输出设置 | 中性 |
| 操作员配置端 | **实时订单表**（替代画板） | 抓取订单·**定时抓取**·字体/素材库 | 中性 |
| 管理员端 | 实时画板（同操作员端，能力零差异） | 操作员端卡 **+ 字段·背景提示词·本次提示词（IP）** | **琥珀**（含 IP 提示） |

- 配置端**不编辑、只监控**，故中心区换订单表、去掉 `production`（图层）卡与画板。
- 密码门**不加**（用户 2026-06-19 拍板，靠分端隔离；与代码现状一致，日后可加）。

## 2. 已实现（本轮）

### 配置端
- **中心区按端切换**：`_apply_view`/`_apply_center_for_view`——配置端隐藏画板、显示订单表，其余端反之（`ui_app.py`）。
- **实时订单表**：`_build_orders_table_panel` + `_refresh_orders_table` + `_render_orders_rows`/`_orders_row` + 点行 `_show_order_detail`。数据 = `GET /inbox/orders`（**接口本就存在**，inbox-service `routes.py:105`）；flower 新增客户端 `inbox_service_client.list_orders`。
  - 列（轻量）：订单号 / 付款时间 / 状态（彩色药丸）/ 件数（×N，>1 红）/ 退款。其他商品/行项目/原文 **点行看详情**。
  - 聚合纯函数 `order_row_view`：件数=各行 `quantity` 之和（§9.4）、其他商品=有 `is_target_box=False` 的行（§8.3）、状态中文药丸 `ORDER_STATUS_STYLE`、`_short_dt` 紧凑时间。
  - 未连接/空态有引导文案。
- **定时锁 → 定时抓取**：`_build_fetch_panel` 标题改「定时抓取 · 重抓起点」、说明改写；手填 `CTkEntry` → **时间选择器** `datetime_picker.CTkDateTimePicker`（月历 + 时分，复用 `_themed_toplevel` 深色标题栏）。**仍写回 `scrape_from_var`，上层「应用/清空」=`restart_from` 逻辑零改动**。
- 卡序：`_VIEW_CARD_ORDER[operator_config] = ("fetch","library")`（去掉 `production`）。

### 管理员端
- 三张 IP 卡（字段/背景提示词/本次提示词）经 `_ctk_card(..., badge=...)` 加琥珀小标「仅管理员 · IP」/「解析可观测②」。
- 切端控件 `_view_switch_menu` 在管理员端染琥珀（视觉提示，非锁）。
- 顺手把「字段」卡标题从占位 `"info"` 改为 `"字段"`。

### 新控件
- `datetime_picker.py`：`CTkDateTimePicker`（widget）+ 纯函数 `parse_dt`/`format_dt`/`month_weeks`（stdlib `calendar`，无新依赖）。未来 Phase 2 调度起止区间可复用。

## 3. 已搁置 / 未做（如实记录）

- **操作员端图层行类型图标 + 解析结果字段上色**：触碰 `_render_layers`/解析结果渲染（WYSIWYG/金标护栏路径），**风险高于收益、且未真机验证**，本轮不做。操作员端布局本就匹配 mockup。
- **定时抓取规则 A/B/C（当前窗口/断点续跑/固定区间）**：Phase 2 调度器未建，**本轮不出 dead 控件**；现仅 `开始/停止`(总开关) + `间隔`(设置里) + `重抓起点`(restart_from) 为真实功能。
- **订单表的 文件数 / 件数 / 其他商品 真实值**：依赖 Phase 1 的扩展详情页抓取 + `OrderItem` 落库。`order.to_dict()` 已含 `items[]`/`refund_status`/`paid_at`，故**数据通路就绪**；扩展暂只抓列表页 → `items` 多为空 → 件数显「—」、文件数列未做。文件数(-1/-2)需 Phase 1+ 的 `ProductionFile`。

## 4. 测试

- 新增/改动单测（`.venv-win` 全绿）：
  - `tests/test_inbox_service_client.py::test_list_orders_hits_right_endpoint`
  - `tests/test_ui_app.py`：`test_view_cards_for_role_splits_three_ends`（改：config=`["fetch","library"]`、production 仅 operator/admin）、`test_short_dt_*`、`test_order_row_view_*`（件数合计/其他商品/退款/未知状态/付款时间回退）
  - `tests/test_datetime_picker.py`：parse/format/month_weeks
- 既有失败（**非本轮引入**，基线同样红）：`test_ui_app.py` 的 preview mousewheel/pan/middle、`_ruler_interval_mm`、`case_button`、`test_field_instructions_drive_ai_system_prompt`(OpenAI 401)——属 headless/无 API key 环境问题。

## 5. 真机手测（待做，须重开 App）

`.\.venv-win\Scripts\python.exe birth_flower_mvp.py`（改完 Python 必须**完全关掉重开**）：
1. 启动 → 选「操作员配置端」：中间是**实时订单表**（非画板）；右侧功能区 = 抓取订单 / 定时抓取 / 字体素材库（**无图层卡**）。
2. 点「定时抓取」选择器 → 弹月历+时分 → 选定 → 框显示 `YYYY-MM-DD HH:MM` → 「应用」走 restart_from。
3. inbox-service 在跑时订单表列出已入库单、点行看详情；未连接显示引导。
4. 切「操作员端」→ 画板回来、右侧四卡；切「管理员端」→ 画板 + 字段/背景/本次提示词三张带「仅管理员·IP」标、切端控件变琥珀。

## 6. 关键文件

- `ui_app.py`：`_VIEW_CARD_ORDER`、`order_row_view`/`_short_dt`/`ORDER_STATUS_STYLE`、`_apply_view`/`_apply_center_for_view`、`_build_orders_table_panel` 等、`_build_fetch_panel`、`_ctk_card(badge=)`、`_build_fields/background/generate_prompt_panel`。
- `datetime_picker.py`（新）、`inbox_service_client.py`（+`list_orders`）。
- inbox-service 侧 `GET /inbox/orders` 已存在（订单表初版未改服务端）。

## 7. 订单删除 + 保留天数自动清理（2026-06-20 追加）

**起因**：用户发现"删了 `outputs/inbox/` 的 JSON、应用里订单还在"——因为订单**持久化在 SQLite `automation/inbox-service/inbox.db`**（13 单），JSON 只是收件夹临时交接文件。两者不同源。用户要"订单表删除功能 + 可设置保留 N 天自动删"，并选定**服务端后台无人值守删**。

**后端（inbox-service）**
- `repository.delete_order`（ORM 级联清 items/退款检查）、`purge_orders_older_than(days)`（删 `received_at` 早于 now−N 天；days<=0 不删）。
- 路由：`DELETE /inbox/orders/{id}`、`POST /inbox/orders/purge {older_than_days>=1}`（不提供"删全部"危险路径）。
- 保留设置：`ScrapeControl` 加 `retention_days` 列（**0=关，默认**）+ 迁移 `0006_add_retention_days.py`；`schemas.ScrapeControlUpdate`/`upsert_scrape_control`/PUT 路由带 `retention_days`。
- 后台自动清理：`RefundScheduler.tick_once` 每轮顺手 `_purge_by_retention`（读 retention_days，>0 才删；异常不杀线程；**无人值守、flower 关着也删**）。

**flower**
- 客户端：`inbox_service_client.delete_order`/`purge_orders` + `put_scrape_control(retention_days=)`。
- 订单表：每行尾「✕」删除（确认）；详情弹窗「删除此单」；顶部清理栏「保留最近 [N] 天 + 立即清理(手动) + 自动删(勾选→PUT retention_days，开启时二次确认其无人值守+含未完成单)」；进端/刷新时从服务端回填保留设置。

**⚠️ 安全**：自动删是**纯按 `received_at` 年龄**删，会删"很老但未完成/人工审核"的单；默认关、开启有强确认、UI 文案标黄/红警示。

**测试**：inbox-service `tests/test_order_cleanup.py`（删除/级联/按龄 purge/scheduler 按 retention 清理/0=不删/PUT 持久化 retention，8 项）全绿（服务端 107 passed）；flower `test_inbox_service_client.py` 加 delete/purge/retention 3 项（10 passed）。

**关键文件（本节）**：inbox-service `models.py`/`repository.py`/`routes.py`/`schemas.py`/`refund_scheduler.py` + `migrations/versions/0006_*.py`；flower `inbox_service_client.py` + `ui_app.py`（`_build_orders_table_panel` 清理栏、`_orders_row` 行删除、`_show_order_detail` 删除按钮、`_confirm_delete_order`/`_on_purge_orders_now`/`_on_apply_retention`/`_populate_retention`）。

## 8. 订单表状态列修正 + 数据模型真相（2026-06-20）

用户真机发现订单表"状态/退款"两列不对。5-agent 调查 + 真实库值（173 单）核实出**三套正交"状态"**（大方案 §5，别混）：
- **内部处理状态机** `Order.status`（RECEIVED→WRITTEN_TO_INBOX→…→DONE/CANNOT_AUTOGEN）——本地流水线；当前库里**几乎全是 WRITTEN_TO_INBOX**（单一常量，做主状态列没意义）。
- `Order.refund_status`——**名字叫 refund 但实际装店小秘"订单状态"原文**（已审核109/已发货38/待打单(有货)24/已退款1/已忽略1；扩展抓订单行 `.orderState` 原文），用于退款拦截 refund_gate 关键词分类。
- 店小秘"自定义标记"（AI未识别/AI已处理/已排版/取消不发货…）——**扩展只读「AI未识别」**(酒红 rgb(226,36,127)+i.icon_brush_bill→布尔 `extras.ai_unrecognized`，且**没进 to_dict**)，其它不抓、**无任何写标记能力**。

**改动（已落地）**：订单表"状态"列改为**显示店小秘订单状态**（`refund_status` 原文，新 `shop_status_style()` 按退款/取消=红、风控=黄、已审核/已发货/待打单=绿、已忽略/未抓到=灰上色）；**删掉"退款"列**（它原本就是店小秘状态）；内部处理状态挪进**订单详情**（`internal_label`）。`order_row_view` 重构：`status_label`=店小秘状态、新增 `shop_status`/`internal_status`/`internal_label`、移除 `refund` 键。测试 `test_ui_app.py`：`test_shop_status_style_*`、`test_order_row_view_status_is_shop_status_not_internal`、`test_order_row_view_refunded_shop_status_and_empty_items`（86 passed）。

**AI 标记回写另立项**：用户要"抓到标 AI未处理、生成素材标 AI已处理"。但店小秘无 API、回写须扩展模拟网页操作（设计上一直标为未来）。已用 spawn_task 拆成独立会话任务「实现店小秘 AI未处理/AI已处理 标记回写（扩展网页操作）」——建议复用退款定向重抓 option B 握手（rescrape_queue + worker/auto_cycle）。
