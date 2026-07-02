# 真机测试报告 · 扩展自动抓取链路（2026-06-19）

> 一次真机测试的完整记录（用户授权）。**结论：链路打通、上一版修的「重推」已确认消除；发现 1 个待修缺陷（空 remark 单被服务 422 拒收）。** 供下次迭代修复。

## 测试设置（隔离、绝不碰生产）
- 服务：当前代码 `app.main:app` 起在 8770，**隔离实例**——`FLOWER_INBOX_DB=_verify2/verify.db`、`FLOWER_*_DIR=_verify2/*`、`FLOWER_REFUND_RECHECK_INTERVAL=600`、`--log-level info`。
- 运行模式 `test_reset`（落 `_verify2/sandbox/inbox`），`/inbox/scrape/control` `enabled=true, interval=20s`。
- 被测对象：真实 Chrome 里加载的扩展 `dist/`，在真实店小秘「全部订单」页自动循环（内容脚本抓 → SW `/scrape/diff` → 逐单 `POST /inbox/orders`）。
- 生产 `inbox.db`（已迁移、12 单）与 `outputs/` 全程未碰。

## ✅ 通过项
1. **链路打通**：扩展在真实页自动循环，**99 单**落 `_verify2/sandbox/inbox`。
2. **字段完整**：99/99 单都带 `items[]` + `refund_status` + `extras.paid_at`（前次已字节级核对 UTF-8 正确，如 `已审核`、🤓 emoji、付款时间）。
3. **「重推」已修并验证消除**（上一版 `scrape_planner._ingested_within`）：
   - 72s 观测窗（3–4 个 20s 周期）内 `pushed_last22s` 恒为 **0**。
   - 99 单 `updated_at` 全落在 **0.7s 窗口**（09:29:17.38–18.11）→ 一次推完、之后再没重推。
   - 用库内 99 单的清单重放 `POST /inbox/scrape/diff` → **worklist count = 0**（全部命中缓存）。
4. **无服务端错误**：日志 `5xx = 0`。请求量：`POST /inbox/orders` 111、`POST /scrape/diff` 13、`GET /scrape/control` 12。

## ⚠️ 发现的缺陷（待下次迭代修）

> **✅ 已修复（2026-06-19 同日迭代）**：用户拍板「进系统、改契约」——remark 改为可选/可空串、strip 归一（D-1+D-2 一并修）。详见 `AGENTS.md` 顶部「D-1/D-2 修复」块。⚠️ 遗留：flower `order_importer` 须改成空 remark 不崩（属 flower 线程）。

### D-1（主）：空 `remark` 的订单被服务 422 拒收，自动循环不拦
- **现象**：111 次 `POST /inbox/orders` 里 **12 次 422**（`string_too_short`，`loc=body.remark`，`min_length=1`）。即 99 入库成功、**12 单被拒**。
- **根因**：这些单在列表页**没有任何定制备注**（`.order-sku__attr` 为空）→ `extractor.buildRemark` 返回 `''`。手动「→Flower」按钮在 `content.ts sendOrder` 里有 `if (!order.order_id || !order.remark) return` 拦截；**但自动循环 `runAutoCycle → pushOrder → client.postOrder` 这条路没有同样的空 remark 守卫**，照发 `remark:""` → 命中 `schemas.OrderPayload.remark` 的 `min_length=1` → 422。
- **复现**：`POST /inbox/orders {schema_version:"1.0",order_id:"X",remark:""}` → 422；`remark:"   "` → 200（见下 D-2）。
- **影响**：这类单（无定制/纯标品/某些「其他商品」）永远进不了库，且因不在库会被后续每轮 diff 当 `new` 反复重发、反复 422（噪音）。
- **修复选项（择一，下次迭代定）**：
  1. **扩展侧**：`runAutoCycle`/`buildManifest` 过滤掉 `!order.remark` 的单（与手动路径一致）——最小、不动契约；代价是这类单不进系统（需确认是否本来就该忽略）。
  2. **契约侧**：把 `remark` 改成可选/`min_length=0`（`order.schema.json` + `schemas.py`，**走协调线程**）——因为现在 `items[]` 已能独立承载每行数据，整单 remark 未必必填。语义更顺，但是契约变更。
  3. 折中：扩展在 remark 空时用 `spec`/首个 `items[].personalization_raw` 兜底填 remark。
- **倾向**：1（快、安全）或 2（更正确），建议下次迭代和「空 remark 单到底要不要进系统」一起拍。

### D-2（次）：纯空白 `remark`（`"   "`）能通过校验
- `min_length=1` 只看长度不 strip，`"   "` 长度 3 → 200 入库，留下无意义 remark。建议 D-1 修复时一并对 remark 做 strip 后再判空（扩展侧 `clean()` 其实已 trim，所以纯空白单实际不会出现；属防御性）。

### 其它（前次已记，未变）
- thumbnail 抓到的是懒加载占位图（`data:image/gif;base64` 1×1），非真实 CDN 图。
- `shop` 在「全部订单」页为 null（`col_115` 选择器按「待处理」页校准）。
- 本轮 99 单**都有付款时间**；注意存在「只有下单、无付款」的未付款单（如 风控中），其 `paid_at` 合理为空。

## 怎么复跑这版测试
1. 停生产服务（释放 8770）。
2. 隔离起：`cd automation/inbox-service` → 设 `FLOWER_INBOX_DB`/`FLOWER_*_DIR` 到临时目录 + `FLOWER_REFUND_RECHECK_INTERVAL=600` → `uvicorn app.main:app --port 8770 --log-level info`。
3. `PUT /inbox/run-mode {mode:"test_reset"}` + `PUT /inbox/scrape/control {enabled:true,interval_seconds:20}`。
4. 真实店小秘「全部订单」页开着、扩展 `dist/` 已加载 → 观测 sandbox 落单 + 日志 `grep -c ' 422 '`。
5. 验「重推」：库内清单重放 `POST /inbox/scrape/diff` 应得 `worklist count=0`。
6. 收尾：停隔离实例、删临时目录、重启生产服务（`production_retry`、自动抓默认关）。

## 测试结束时的处置
- 隔离实例已停、`_verify2` 已删；生产服务以当前代码 + 已迁移 DB + 安全默认（自动抓关）重启在 8770。
