# 端到端冒烟 runbook（automation 一期）

手动验证整条链路。涉及 Flower 桌面 GUI 与 Chrome，需在真机上做。

## 前置
- 本地服务：`automation/inbox-service`，已建 `.venv`（见其 README）。
- Flower：仓库根 `.venv-win`；`birth_flower_config.json` 加 `"inbox_folder": "outputs/inbox"`（或在设置里填）。

## A. 启动本地服务
```powershell
cd automation\inbox-service
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8770
```
另开一个终端验证：`curl http://127.0.0.1:8770/healthz` → 应回 `status: ok` 及收件夹/DB 路径。

## B. 单单路径（开发期逐单测试）
1. 不用扩展，直接 POST 一单：
   ```powershell
   curl -X POST http://127.0.0.1:8770/inbox/orders -H "Content-Type: application/json" `
     -d '{"schema_version":"1.0","order_id":"SMOKE-1","remark":"name Amy May font 1 flower 2"}'
   ```
   → `outputs/inbox/SMOKE-1.json` 出现；`GET /inbox/orders/SMOKE-1` 状态 `WRITTEN_TO_INBOX`。
2. 启动 Flower：`.\.venv-win\Scripts\python.exe birth_flower_mvp.py`（已配 `inbox_folder`）。
   → 备注自动载入文本框、状态栏显「📥 新订单已载入：SMOKE-1」、自动解析填字段、文件移入 `outputs/inbox/processed/`。
3. 操作员复核字段 → 点「生成」→ `outputs/` 出 SVG/DXF/PNG。**改完 Flower 代码务必完全关 App 重开再测。**

## C. 批量路径（生产 + 失败表）
1. POST 多单（重复上面，换 order_id：SMOKE-2/3…，故意造一单 remark 残缺让它无法自动生成）。
2. 让服务导出批次 xlsx：
   ```powershell
   curl -X POST http://127.0.0.1:8770/inbox/batch/export
   ```
   → 返回 `outputs/inbox-batches/pooled-*.xlsx` 路径，池中订单转 `QUEUED_FOR_BATCH`。
   - 注意：单单路径已被 Flower 载入并移走的，不在此批次（避免重复）；批量适合「攒一批一起跑」。
3. Flower 里「导入」该 xlsx（现有批量入口）→ 跑批量生成 → 出 `outputs/reports/{batch_id}-report.xlsx`（订单号/状态/是否需人工核验/原因汇总）+ `{batch_id}-review.csv`。
4. 服务回写状态：
   ```powershell
   curl -X POST http://127.0.0.1:8770/inbox/batch/sync
   ```
   （或服务常驻的 report_watcher 后台线程自动回写）→ `GET /inbox/orders`：成功的 `DONE`，无法自动生成的 `CANNOT_AUTOGEN` + 原因。
5. 无法自动生成的单：操作员按 `{batch_id}-review.csv` 补字段后重跑批量（现有机制）。

## D. 浏览器扩展
1. `cd automation\extension; npm install; npm run build`。
2. Chrome → 扩展程序 → 开发者模式 →「加载已解压的扩展程序」→ 选 `automation/extension/dist`。
3. 打开店小秘订单详情页 → 右下角「发送到 Flower」→ 走 B/C 链路。popup 有服务健康灯。

## ⚠️ 必须核对的两件事
- **选择器**：扩展 `selectors.ts` 是启发式占位。把真实店小秘订单页另存 HTML 放进 `extension/src/fixtures/`，校准 selectors + 补真实夹具断言，否则抓取不准。
- **批量出件一致性**（plan 风险①）：批量走 `services/api` 引擎，可能比桌面单单旧。用同一单分别走「单单生成」与「批量生成」，核对 DXF/SVG 几何与文字是否一致；不一致需先引擎归一。
