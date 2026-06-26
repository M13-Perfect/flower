# 标记回写店小秘（扩展模拟网页操作）—— ExecPlan + 冻结契约

> 2026-06-20 立项。目标：扩展给店小秘订单回写两个**自定义标记**：
> - 抓到一单（新单入库）→ 打「**AI未识别**」（= 待处理）。
> - flower 生成完该单素材 → 打「**AI已处理**」+ 同弹窗取消「AI未识别」。
>
> 店小秘**无开放 API** → 只能扩展**模拟网页操作**（打开「设置自定义标记」弹窗、勾/取消、点确定）。
> 复用退款定向重抓 option B 的"拉模式握手"骨架，但**队列改 DB 持久**（打标是异步的，扩展当时可能没开店小秘）。

## 一、已敲定决策（2026-06-20，用户拍板）

1. 待处理标记 = 现有「**AI未识别**」（酒红 `icon_brush_bill`，扩展原本就读它）；已处理 = 「**AI已处理**」（浅蓝 `icon_change_order`）。两个标记**店小秘里都已建好且启用**。
2. 打标时机：**统一入队异步打**（与 AI已处理 共用一套"标记回写队列"握手）。
3. 打 AI已处理 时：**同弹窗取消 AI未识别 + 勾 AI已处理 + 确定**。
4. 队列：**DB 表持久**（新建 `mark_jobs` 表 + 迁移 0007）。
5. 范围：**每个新单都自动打 AI未识别**（inbox-service 在新单入库时入队；幂等，已有不重打）。生成后清掉。

## 二、真实 DOM 勘查结论（2026-06-20，claude-in-chrome 只读勘查真实店小秘「待处理」页）

### 订单行上的"已打标记"
- 标记在**表头行** `tr[rowid="X_header"]` 的 `.orderBagInfo .bag-info-coustom` 里，每个 `.order-mark-block` = 一个已打标记。
- **识别某标记靠图标 class，不靠颜色**（酒红色 `rgb(226,36,127)` 被 AI未识别/加急运输/T21-worst **三个**标记共用，旧兜底选择器 `[style*="226,36,127"]` 会误命中——本次要修）：
  - AI未识别 → `.bag-info-coustom .order-mark-block i.icon_brush_bill`
  - AI已处理 → `.bag-info-coustom .order-mark-block i.icon_change_order`
- `.bag-info-coustom` 末尾有一个**空 `.order-mark-block`（无图标）= "添加标记"按钮**（点它开弹窗）。⚠️ 注意"无图标"≠"添加块"——有些标记（如 已排版-Designed）是纯色块无图标；添加块的精确判据（无背景色/"+"）**待真机校准**。

### 「设置自定义标记」弹窗（Ant Design Popover，全页单例复用）
- 容器：`.ant-popover.common-source-image-popover` → `.markPopover`（点某单的标记区即锚到该单）。
- 标记列表：`.markPopover .remark-item`，每行：
  - `.remark-item__icon.order-mark-block`（色块/图标）
  - `.remark-item__text`（**label 文字**，按文字精确匹配 `AI未识别` / `AI已处理`）
  - `.remark-item__action`：`停用`(`i.icon_block`) + `编辑`(`i.icon_edit2`)；**选中的行多一个对勾 `i`**（实测 class `icon_support`）。
- **选中判据**：`.remark-item__action` 内出现**除 `icon_block`/`icon_edit2` 之外的 `i`**（= 对勾）。已实测 `已选 2/10` ⟺ 恰好两行有该对勾。
- 确定：`.markPopover .markPopover__header button.ant-btn-primary`（span 文本「确定」）。
- 取消：`.markPopover .markPopover__header button.ant-btn-default`（span 文本「取消」）。
- 搜索过滤框：`.markPopover .markPopover__filter input.ant-input`（可输 label 过滤，缩小点击目标，可选用）。

### 真机校准的 3 点 ✅ 已解（2026-06-20 claude-in-chrome 在真实页面对 3 单实测，详见 §九）
1. **触发**：点 `.bag-info-coustom` 里任意 `.order-mark-block` 即开弹窗（部分单有空添加块=无图标无背景、部分单没有→用末块）。`findMarkTrigger`「空块优先、否则末块、再否则标记区」全覆盖。✅
2. **click（非 hover）** 触发：`mouseenter + click` 打开。✅
3. **必须点确定才提交**（toggle 是本地态、Vue 异步更新需延时；确定才写店小秘 + 触发行重渲染）。✅
4. **🔴 真机抓出关键 bug 并修**：页面有**多个 `.markPopover`**（隐藏模板 display:none + 当前可见锚定弹窗）；原 `getMarkPopover`=`querySelector` 取首个=隐藏的→选中态恒空→一致性守卫永远 abort→**功能失效**。已改为取**可见**那个（`isDisplayed` 排除 display:none；单实例 jsdom 夹具直接返回）。`confirm` 延时 500→900ms（留店小秘保存+vxe 行重渲染，回读校验才看到新标记）。新增回归测试 `getMarkPopover 取可见弹窗`。

## 三、冻结契约（改一处必同步三处；只走本文档/协调线程改）

### inbox-service（DB 持久队列；端点前缀 `/inbox/mark/`，仿 rescrape 风格）
表 `mark_jobs`（迁移 0007）：
| 列 | 类型 | 说明 |
|---|---|---|
| id | int pk autoinc | |
| order_id | str(120) FK orders.order_id ondelete CASCADE, index | |
| action | str(32) | `mark_unrecognized` / `mark_done` |
| status | str(16) | `pending` / `done` / `failed`，默认 pending |
| attempts | int | 失败重试计数，默认 0 |
| last_error | Text null | 最后一次失败原因 |
| created_at / updated_at | DateTime | |
- 唯一约束 `(order_id, action)`：每个 (单, 动作) 一行；重入队 = upsert 重置为 pending、attempts 归零。
- `Order.mark_jobs` 关系（delete-orphan，删单级联清），仿 `refund_checks`。

动作常量与语义：
- `mark_unrecognized`：确保订单打上「AI未识别」。
- `mark_done`：确保打上「AI已处理」**且**取消「AI未识别」。

端点：
- `POST /inbox/mark/request` body `{order_id, action}` → upsert pending → 返回 job dict。**flower 生成成功后调它入队 mark_done。**
- `GET  /inbox/mark/pending?limit=` → `{jobs:[{order_id, action, source_url}], count}`，pending 且 attempts<max，按 created_at 升序。
- `POST /inbox/mark/result` body `{order_id, action, ok, detail?}` → ok→done；否则 attempts+1、超 max→failed 否则留 pending。返回 job dict。
- `GET  /inbox/mark/jobs?order_id=`（可选，审计/可观测）。

自动入队：`POST /inbox/orders` 内 `upsert_order` 返回 `dedup=False`（新单）时，若 `settings.mark_enqueue_unrecognized`（默认 True）→ `enqueue_mark_job(order_id, mark_unrecognized)`。

配置（`Settings` + env）：`mark_max_attempts=5`(`FLOWER_MARK_MAX_ATTEMPTS`)、`mark_pending_limit=50`(`FLOWER_MARK_PENDING_LIMIT`)、`mark_enqueue_unrecognized=True`(`FLOWER_MARK_ENQUEUE_UNRECOGNIZED`)。
**契约 `contracts/order.schema.json` 不动**（这是服务内部 API，同 rescrape）。

### 扩展（contract.ts 类型）
```ts
export type MarkAction = 'mark_unrecognized' | 'mark_done'
export interface MarkJob { order_id: string; action: MarkAction; source_url: string | null }
```
- `client.ts`：`getMarkPending(): Promise<MarkJob[]>`、`postMarkResult(orderId, action, ok, detail?): Promise<void>`。
- `service-worker.ts`：消息 `FLOWER_MARK_PULL`（→getMarkPending）、`FLOWER_MARK_RESULT`（→postMarkResult）。
- `selectors.ts`：新增弹窗/标记区选择器 + `MARK_LABELS={unrecognized:'AI未识别', done:'AI已处理'}` + `MARK_ACTION_IGNORE_ICONS=['icon_block','icon_edit2']`。
- `dianxiaomi_mark.ts`（新，DOM 交互，真机校准面）：定位订单标记区、开弹窗、读弹窗选中态、设/清某标记、点确定、回读订单行标记。
- `mark_writeback.ts`（新，纯编排，DI 可单测，仿 rescrape.ts）：`runMarkJobs(deps)`：拉队列→逐单定位→开弹窗→按 action 设目标态（幂等：先读现状再 toggle）→确定→回读校验→回填 result。
- `content.ts`：加一个标记回写轮询循环（仿定向重抓轮询；间隔较慢、串行、限频，**防封号**）。受 `/scrape/control` enabled gate（与抓取/退款闭环同一开关）。

### flower
- `inbox_service_client.py`：`request_mark(order_id, action)` → POST `/inbox/mark/request`。
- `ui_app.py`：`confirm_and_generate` 成功路径 → `run_background` 调 `request_mark(current_order_number, 'mark_done')`（best-effort，不卡 UI、失败不影响生成）。

## 四、幂等 / 防封号
- inbox-service：`(order_id, action)` 唯一；result ok→done 自动掉出 pending。
- 扩展：打标前回读订单行现状，已是目标态就跳过 toggle、直接回 ok。
- 扩展：每轮只处理少量、串行、带间隔；失败计 attempts，超 max 终止。**所有写操作只在 enabled 时跑。**

## 五、测试
- 扩展：`cd flower/automation/extension && npx vitest run` + `npx tsc --noEmit` + `npx vite build`（纯逻辑：定位/选中检测/幂等/清未识别/失败计数；用新 fixture `dianxiaomi-mark-popover.html`）。
- inbox-service：`cd flower/automation/inbox-service && .\.venv\Scripts\python -m pytest -q`（队列表/端点/自动入队/迁移 0007 upgrade→downgrade→re-upgrade 可逆）。
- flower：仓库根 `$env:PYTHONPATH=".;services\api"; .\.venv-win\Scripts\python -m pytest tests -q`（生成成功入队 mark_done、客户端 request_mark）。
- 真机手测：起 8770 + 扩展 dist 加载店小秘列表页 + 用一个测试单走 抓单→AI未识别、flower 生成→AI已处理+清未识别。**改完 Python 完全关 App 重开。**

## 八、上传门控（标准1）+ 配置端标签列 + 打标时机（标准2）（2026-06-20 追加，用户拍板）

**标准1（上传门控，手动「→Flower」按钮 + 自动抓都遵守）**：浏览器传 JSON 到 DB 前先看订单行的店小秘 AI 标记——
- 已打「AI已处理」→ **不上传**（`buildManifest` 排除 `ai_done`；手动按钮 content 先拦 + `grabOrderIfNeeded` 再兜一层）。
- 否则（AI未识别/无标记）→ **查库 diff 决定**（不在库/items 不全/退款状态过旧才传；命中缓存则跳过）= 复用 `/inbox/scrape/diff`。手动按钮经新消息 `FLOWER_GRAB_ORDER`→`grabOrderIfNeeded`（diff 单单），diff 端点不可用则回退直接上传。
- 扩展新读 `RawOrder.ai_done`（表头行 `i.icon_change_order`）。

**标准2（打标时机）**：
- 上传成功后 → 确保「AI未识别」：`ingest` 在**写收件夹成功**后入队 `mark_unrecognized`，**除非该单已有 active `mark_done`**（`has_active_mark_done`，对应「若已有 AI已处理则不变」）。
- 操作员生成素材并确定输出后 → 打「AI已处理」+ 清「AI未识别」：`ui_app.confirm_and_generate` 成功入队 `mark_done`（已实现）；服务端 `mark_done` 入队顺带 `supersede` 同单 pending 的 `mark_unrecognized`。

**配置端「标签」列**：操作员配置端实时订单表新增一列，数据源 = **订单 `mark_jobs` 摘要**（`Order.to_dict` 新增 `mark_jobs:[{action,status}]`，无新列/迁移）。`ui_app.mark_status_style(mark_jobs)` 派生标签：AI已处理✓/·待写/·失败、AI未识别/·待写/·失败、`—`。`order_row_view` 加 `mark_label/bg/fg`；`_orders_row` 加列、`_ORDERS_COL_MIN=(0,116,96,56,38)`。**操作员可据此列核对回写是否生效**（done=已成功写店小秘）。

**测试复跑**：扩展 68 vitest（+buildManifest 排除 ai_done、提取器 ai_done）、inbox-service 123 pytest（+标准2 守卫/list_orders mark_jobs/restamp）、flower 398 pytest（+mark_status_style/order_row_view 标签；8 既有 headless 失败不变）。

## 七、对抗审查修复（2026-06-20，4-agent workflow + 逐条对抗验证，10 条确认全修/记录）

- **#1 (medium)** `findOrderHeaderRows`：数字 rowid 但表头行此刻查不到 → 返回空（`readOrderRowMarks`→null=「读不到」），**不再回退明细行**（否则误读成「未打标」→ mark_done 校验把成功当失败）。
- **#2 (medium)** 防串单：① `runMarkJobs` 开弹窗后校验**弹窗选中态须 == 刚读的订单行现状**，不一致→取消+`deferred`+留 pending（弹窗未锚定本单）；② `content.openPopover` 先关残留单例弹窗再点、轮询等弹窗出现。
- **#1+#2 衍生** `runMarkJobs`：确定后回读为 null（vxe 重渲染瞬间）→ `deferred`+留 pending（下轮幂等复核），**不当失败耗 attempts**。
- **#3 (medium)** `markConfirmButton`：排除「创建标记」(`created-mark`/含「创建」)、去全空白比对、**挑不到「确定」返回 null**（不再回退 `btns[0]` 误点）。
- **#4 (medium)** 每轮限条数：`content` 拉队列传 `limit=MARK_BATCH_LIMIT=3`（`getMarkPending(limit)`→`/inbox/mark/pending?limit=`），剩余留下轮（契约「每轮只处理少量」防封号）。
- **#5 (low)** `mark_done` 入队时 `supersede_mark_job` 作废同单仍 pending 的 `mark_unrecognized`（避免「已处理又被打回未识别」回退窗口 + 省一次多余写）。
- **#6 (low)** 选中判据改**白名单** `MARK_SELECTED_ICONS=['icon_support']`（替黑名单，避免操作区新增无关图标被误判已选）。
- **#10 (low)** `delete_order` 注释补 `mark_jobs` 级联。
- **#9 (low)** 迁移 0007 可逆性已**手动验证**（命令行 upgrade→downgrade(0006)→re-upgrade，临时库；见会话记录），未加自动化测试（与仓库既有迁移惯例一致）。
- **#7/#8 (low)** 添加按钮/对勾容器仍是真机校准点（保留启发式 + 注释标注）；误点后果已被 #2 的「开弹窗校验+回读校验」兜住=不会产生错误写、最坏失败重试。
- 回归测试：扩展 +5（表头缺失→null、确定按钮兜底/容错、防串单、回读 null deferred）；inbox-service supersede 断言更新。**复跑全绿：扩展 66 vitest / tsc / build；inbox-service 120 pytest；flower 395 pytest 不变。**

## 十、打标耦合进抓取 + EzCad 导入检测（2026-06-20 追加，用户反馈）

> 用户反馈：自动打标要**真打到店小秘**（不只是 DB 记录），抓取时就打、可放缓抓取；EzCad 导入也要检测订单状态。
> **根因澄清**：之前没打到店小秘 = §二.4 的 `getMarkPopover` 取到隐藏弹窗 bug（已修），旧 dist 是坏的。

- **打标耦合进抓取（content.ts）**：自动抓一轮结束（上传成功，服务端已入队 mark_unrecognized）后，**当轮立刻 `runMarkOnce()`** 在店小秘给本页可见单打 AI未识别——不等后台 8s 循环。加 `markBusy` 守卫防「抓取触发」与「8s 定时器」并发抢同一单例弹窗。受 `/scrape/control enabled` gate。两条打标驱动并存：8s 定时器（持续清队列，每轮 ≤3 单防封号）+ 抓取触发（新单及时打）。`confirm` 延时 900ms。
- **EzCad 导入检测订单状态（Ezcad2.7.6）**：`/recheck` 响应加 `ai_processed`（= 是否已有 AI已处理任务 pending/done = 已生成）。Ezcad `inbox_client`：`RecheckResult.ai_processed`、`_parse` 读取、`GateAction` 加 **WARN**、`evaluate_engrave_gate` 对「退款正常但未生成(ai_processed=False)」返回 WARN；`ai_processed=None`(旧服务)→不警告（向后兼容）。`app.py` 确认导入：BLOCK→硬拦（退款/查询失败）、**WARN→askokcancel「未生成，确认继续？」可继续**（标准·EzCad「未处理只警告」）、ALLOW→放行。退款拦截优先级高于未生成警告。
- **测试**：inbox-service +1（recheck 带 ai_processed）=124；Ezcad +5（WARN/processed/None 兼容/退款优先/解析）=124；扩展 70（content 耦合不增单测，tsc/build 过）。

## 九、真机验证（2026-06-20，claude-in-chrome 在真实店小秘页面，订单 4090627965 / 4093542955 / 4093587551）

只读勘查 + 实测 DOM 打标交互（用户授权测这 3 单），**全链路打标机制验通**：
- **读取**：3 单的 `ai_unrecognized`/`ai_done` 经「靠图标 class」逻辑读对（rowid 是 17 位长数字，`/^\d+$/` 正确配对表头行）。
- **抓取时标记（mark_unrecognized）**：4090627965（原无 AI 标记）→ 开弹窗→勾 AI未识别→确定 → 行变 **AI未识别** ✅。
- **生成后标记（mark_done）**：4093542955（原 AI未识别）→ 勾 AI已处理 + 取消 AI未识别 → 确定 → 行变 **AI已处理、未识别已清** ✅。
- **抓出并修复** `getMarkPopover` 取到隐藏模板的致命 bug（见 §二.4）。
- 测后**已把 3 单还原到测试前状态**（4090627965 无标记 / 4093542955、4093587551 AI未识别），不留脏数据。
- **仍待用户真机**：整条**自动链**（inbox-service 起 + 扩展 dist 重新加载 + 开抓取开关 + flower 点生成）——我只验证了 DOM 打标机制本身，扩展自动循环 + flower 生成触发需在用户机跑。

**测试复跑（最终）**：扩展 **70 vitest** / tsc / build；inbox-service **123 pytest**；flower **398 pytest**（8 既有 headless 失败不变）。

## 六、状态
- [x] 立项 + 真实 DOM 勘查（claude-in-chrome 只读勘查真实店小秘弹窗，2026-06-20）
- [x] inbox-service 实现 + 测试（**pytest 120 passed**；迁移 0007 upgrade→downgrade→re-upgrade 可逆）
- [x] 扩展实现 + 测试（**vitest 61 passed**、tsc clean、vite build OK）
- [x] flower 实现 + 测试（**pytest 395 passed**，8 既有 headless 失败不变）
- [x] 对抗审查（4 维度并行 + 逐条对抗验证）
- [x] 真机 DOM 打标机制验证（3 单实测，§九；解 3 校准点 + 修 getMarkPopover 致命 bug；测后已还原）
- [ ] 真机**自动链**手测（用户）：起 8770 + 扩展 dist 重新加载 + 开抓取开关 + flower 点生成，走完整 抓单→AI未识别 / 生成→AI已处理
