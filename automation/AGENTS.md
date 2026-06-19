# AGENTS — automation/（店小秘 → Flower 自动取单）

> **2026-06-19 · 并入「订单自动化与排版系统」增量方案（新对话先读）**
> 本 automation 现在是更大方案的一环。**权威设计 = `C:\Users\Administrator\.claude\plans\ezcad2-7-6-flower-c-users-administrator-staged-wren.md`**（跨 flower / flower/automation / Ezcad 三仓；基线 A=在现有代码上增量，不重写）。下方旧内容（方案 D 一期）仍是 automation 的真实地基、未过时。
>
> **已敲定决策**：① 退款/取消状态只能让扩展**重抓店小秘页面**取（API 不开放、状态回写也没实现）；② 多文件扫码 = **单订单号条码聚合**（"双码"作废）；③ 拆件接缝 = **扩展抓「结构 + 原始备注」、不拆语义；语义拆分（一条备注 N 名字→N 单元）交给 flower GPT 解析层**（边界待真单调优）；④ 三端 = 管理/操作/后台调度，**暂缓**。
> **纪律**：`contracts/order.schema.json` 是三仓唯一契约，**只走计划/协调线程改**，别在各执行线程各改各的。
>
> **契约已冻结并落地（2026-06-19，26 tests pass）**：`order.schema.json` + `schemas.py` 加可选 `items[]`（line_index/product_sku/is_target_box/quantity/personalization_raw/extras）+ `refund_status`，**全部可选、`schema_version` 仍 "1.0"、老扩展/老 JSON 零影响**；`models.py` 加 `OrderItem` 表 + `Order.refund_status` 列 + items 关系（delete-orphan，幂等整树替换）；`repository.upsert_order` 持久化 items；迁移 `app/migrations/versions/0002_add_order_items_and_refund_status.py`（临时库 upgrade/downgrade 验证可逆）；新测试 `tests/test_items.py`。
>
> **automation 本仓待做**（计划 Phase 1–2）：① 扩展进店小秘**列表/详情页**抓 `items[]`（行项目/数量/原始备注/是否目标盒子）、其他商品、`refund_status`——**全新抓取工作**（现仅列表页抓 订单号+规格）。用户已给样例 `C:\Users\Administrator\Desktop\店小秘--全部订单.html`（⚠️ 是「全部订单」**列表页**、非单订单详情页；先确认它是否已含 行项目/数量/退款/其他商品，不够再要详情页）。② inbox-service 加 `RefundCheck` 表 + `POST /inbox/orders/{id}/recheck` 重抓接口。③ 新增 scheduler：规则 A(当前窗口)/B(从上次成功位置续)/C(固定区间) + 半开区间 `[start,end)` + Checkpoint 断点续跑。④ 测试重置 vs 生产重试隔离。
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
- `inbox-service/` — 独立小服务 FastAPI + SQLite + SQLAlchemy + Alembic。✅ M3+M4，**26 tests pass**（2026-06-19 加 items/refund_status 后，见顶部块）。
  独立 venv：`automation/inbox-service/.venv`（py3.12）。
  - 端点：`POST /inbox/orders`（校验+去重 upsert+原子写收件夹）、`GET /inbox/orders[/{id}]`、
    `POST /inbox/batch/export`（把池中订单导出店小秘格式 xlsx）、`POST /inbox/batch/sync`（读 report.xlsx 回写状态）、`GET /healthz`。
  - `report_watcher` 后台线程（`main.py` 启）轮询 `outputs/reports/*-report.xlsx`，
    EXPORTED→`DONE(已完成)`，BLOCKED/NEEDS_REVIEW/FAILED/需人工→`CANNOT_AUTOGEN(无法自动生成)+原因`。
  - 状态机：RECEIVED→VALIDATED→WRITTEN_TO_INBOX→QUEUED_FOR_BATCH→DONE / CANNOT_AUTOGEN。
- **Flower 侧**（仓库根 `config_store.py` / `ui_app.py`）✅ M2，`tests/test_inbox_poller.py` + `test_config_store.py` pass：
  - config 加 `inbox_folder` / `inbox_autoparse`（空=功能关，旧配置零感知）。
  - `ui_app` 收件夹轮询 `_start_inbox_poller` / `_poll_inbox_once` / `_auto_load_order` / `_move_inbox_file_to_processed`：
    自动载入备注 → 自动解析 → **停在生成前**，处理过的文件移入 `inbox/processed/`。绝不自动生成。
- `extension/` — ✅ M5 已建（Chrome MV3 + TS + Vite/@crxjs + Vitest）。**Vitest 7 passed + `npm run build` 产出 dist/ + typecheck 通过**。
  selectors **已按真实「待处理」列表页校准**（vxe-table：一单两行 `<tr>`，rowid 配对；订单号 `.orderCode span.pointer`；
  备注=买家定制项 `.order-sku__attr > div` 规整成单行；店铺 header `td[colid="col_115"]`；
  「AI未识别」= header 行 `i.icon_brush_bill`/酒红标记块）。content 给每个订单行注入「→Flower」按钮（AI未识别标红），
  点哪单发哪单（MutationObserver 重注以抗 vxe 重渲染；带控制台诊断 `[Flower` + 就绪 toast）。夹具用了真实 3 单数据。
  ✅ 2026-06-18 真机：扩展按钮已在真实「待处理」页出现并成功发送（→服务→收件夹写出 {order_id}.json）。`p.ele-p` 卖家备注恒空，故备注取买家定制项。

## 怎么跑 / 怎么测
- 服务：`cd automation/inbox-service`；起服务 `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8770`；
  测试 `.\.venv\Scripts\python.exe -m pytest -q`。环境变量可覆盖 `FLOWER_INBOX_DIR/FLOWER_REPORTS_DIR/FLOWER_BATCHES_DIR/FLOWER_INBOX_DB/FLOWER_INBOX_PORT`。
- Flower 单单链：`birth_flower_config.json` 的 `inbox_folder` 必须填**绝对路径**（如 `C:\\Users\\Administrator\\Documents\\flower\\outputs\\inbox`），启动 `birth_flower_mvp.py`。
  ⚠️ **坑（2026-06-18 踩过）**：默认 `Path("")` 存盘会变成 `"."`，而代码把 `""`/`"."` 当「功能关」→ 必须显式填绝对路径，否则 Flower 不监听。
  行为：**一次只载一单**（`_inbox_active` 挂起），自动解析、停在生成前；点「生成」成功后 `_advance_inbox_after_generate` 把该单移入 `processed/` 并自动放行下一单。**改完务必完全关 App 重开再测。**
- Flower 测试（仓库根）：`PYTHONPATH=".;services\api" .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q`。
  注：7 个 `test_ui_app.py` 无头失败是**分支既有问题**（`case_button` 无头未建 / 控制台中文乱码），与本工作无关。

## 待办 / 已知问题
- **扩展 selectors 已按真实 vxe 列表页校准**（用户 2026-06-18 提供 `店小秘--待处理.html`，含 3 个「AI未识别」单 4093542955/4093587551/4093606621）；7 个 Vitest 夹具断言通过。**待 Chrome 真机加载 `dist/` 在活动页验证**（vxe 重渲染、固定列重复已用 MutationObserver + rowid 去重应对，仍需真机确认）。
- ⚠️ 这些是「AI未识别」单，Flower 端 GPT/本地解析器能否把 `Choose Your Birth Flower: Jun - Honeysuckle / Font Design: Font 3 / Personalization: Esther` 正确解析出 月/花/字体/名字，需真机看（属 Flower 解析质量，非扩展职责）。
- ⚠️ **批量引擎落后风险**（plan 风险①）：批量走 `services/api` 引擎，可能与桌面单单出件不一致 → 冒烟时**用真单核对**。
- 「无法自动生成」失败表只来自**批量路径**；单单路径只有解析提醒弹窗。
- 端到端冒烟 `docs/inbox-smoke.md` 已写；服务**真·起服务冒烟通过**（起 uvicorn → POST → 文件落地 → 列表）；Flower GUI + Chrome 全链待用户真机跑。
- 「哪个店小秘单号当 order_id」未定（订单号/平台单号/系统单号），其余进 `extras` 便回退。

## 注意
- 根 `AGENTS.md` / `CURRENT_TASKS.md` 当前有**他人未提交改动**，本次自动化工作**未碰**它们；automation 的交接全在此文件。
