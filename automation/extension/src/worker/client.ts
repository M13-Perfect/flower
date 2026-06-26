import {
  type DatabaseResult,
  type ManifestEntry,
  type MarkAction,
  type MarkJob,
  type OrderPayload,
  type PendingItem,
  type RawOrder,
  type RecheckResult,
  type ReconcileDecision,
  type RefundStage,
  SCHEMA_VERSION,
  type ScrapeControl,
  type WorkItem,
} from '../shared/contract'

const SERVICE_BASE = 'http://127.0.0.1:8770'

export interface SendResult {
  ok: boolean
  status?: string
  dedup?: boolean
  /** 数据库侧结果（严格三态）：上传成功时据响应 created 推导；缺失/非布尔 → UNKNOWN。失败时为 undefined。 */
  databaseResult?: DatabaseResult
  error?: string
}

/** RawOrder → 上传契约 OrderPayload（单条/批量共用，保证两条路径字段一致）。
 * remark 可选（D-1）：空则不带、服务默认空串；付款时间走 extras 兜底（不动冻结契约）。 */
function buildPayload(raw: RawOrder, sourceUrl?: string): OrderPayload {
  const extras: Record<string, unknown> = {}
  if (raw.ai_unrecognized) extras.ai_unrecognized = true
  if (raw.paid_at) extras.paid_at = raw.paid_at
  return {
    schema_version: SCHEMA_VERSION,
    order_id: raw.order_id,
    remark: raw.remark ? raw.remark : undefined,
    shop: raw.shop,
    spec: raw.spec,
    source_url: sourceUrl,
    scraped_at: new Date().toISOString(),
    refund_status: raw.refund_status,
    items: raw.items,
    extras: Object.keys(extras).length ? extras : undefined,
  }
}

export async function postOrder(
  raw: RawOrder,
  sourceUrl?: string,
  opts?: { manual?: boolean },
): Promise<SendResult> {
  const payload = buildPayload(raw, sourceUrl)
  // ?manual=1：手动「→Flower」专用——服务端不入队 mark_job（不留打标痕迹）；打标由 content 按条件纯页面完成。
  const url = opts?.manual ? `${SERVICE_BASE}/inbox/orders?manual=1` : `${SERVICE_BASE}/inbox/orders`
  // JSON.stringify 自动丢弃值为 undefined 的可选字段。
  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (resp.ok) {
      const data = await resp.json()
      // 严格三态：只有 created 是**真布尔**才下结论；否则 UNKNOWN（绝不把缺字段当新建 → 防误打标）。
      const databaseResult: DatabaseResult =
        typeof data?.created === 'boolean'
          ? data.created
            ? 'CREATED_NEW'
            : 'ALREADY_EXISTS'
          : 'UNKNOWN'
      return { ok: true, status: data.status, dedup: Boolean(data.dedup), databaseResult }
    }
    if (resp.status === 422) {
      const data = await resp.json().catch(() => ({}))
      const detail = typeof data.detail === 'string' ? data.detail : '字段校验未通过'
      return { ok: false, error: detail }
    }
    return { ok: false, error: `服务返回 ${resp.status}` }
  } catch {
    return { ok: false, error: '无法连接本地服务（是否已在 8770 启动？）' }
  }
}

export interface BatchItemResult {
  order_id: string
  ok: boolean
  error?: string
}

/** 批量回传：一次 POST /inbox/orders/batch 投递多单（阶段二吞吐：少网络往返 + 服务端一事务提交）。
 * 全部 POST 到**本地** service（非店小秘），无封号风险。返回逐单 {order_id, ok}；整体失败时全标 ok:false。 */
export async function postOrdersBatch(orders: RawOrder[], sourceUrl?: string): Promise<BatchItemResult[]> {
  if (orders.length === 0) return []
  const payload = { orders: orders.map((raw) => buildPayload(raw, sourceUrl)) }
  try {
    const resp = await fetch(`${SERVICE_BASE}/inbox/orders/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (resp.ok) {
      const data = await resp.json()
      const results = (data.results ?? []) as Array<{ order_id: string; error?: string }>
      return results.map((r) => ({ order_id: r.order_id, ok: !r.error, error: r.error }))
    }
    return orders.map((o) => ({ order_id: o.order_id, ok: false, error: `服务返回 ${resp.status}` }))
  } catch {
    return orders.map((o) => ({ order_id: o.order_id, ok: false, error: '无法连接本地服务（是否已在 8770 启动？）' }))
  }
}

export interface GrabResult {
  uploaded: boolean
  /** 数据库侧结果（严格三态）；仅 uploaded=true 时有值。content 据此判 CREATED_NEW 决定是否打标。 */
  databaseResult?: DatabaseResult
  reason?: string
  error?: string
}

/**
 * 手动「→Flower」单单上传（用户主动点一单）。
 *
 * 只负责**上传到本地服务**并把数据库侧结果（CREATED_NEW/ALREADY_EXISTS/UNKNOWN）透传回去；
 * 是否打店小秘标签由 content 侧 `handleManualFlowerOrder` 按条件决策表判定（手动条件打标，2026-06-22）。
 * 手动单单上传始终允许、不受任务租约约束（服务端 /inbox/orders 不要求授权）。
 * AI已处理的单仍跳过（content 已先拦，这里兜一层）。
 */
export async function grabOrderIfNeeded(raw: RawOrder, sourceUrl?: string): Promise<GrabResult> {
  if (raw.ai_done) return { uploaded: false, reason: '已标记 AI已处理' }
  // manual=true：服务端不入队 mark_job（不留痕）；打标由 content 按条件决策表纯页面完成。
  const res = await postOrder(raw, sourceUrl, { manual: true })
  if (!res.ok) return { uploaded: false, reason: res.error, error: res.error }
  return { uploaded: true, databaseResult: res.databaseResult ?? 'UNKNOWN' }
}

export interface EnsureMarkResult {
  /** 服务是否确认请求成功（订单存在、未报错）。 */
  ensured: boolean
  /** 现在是否存在该单 pending 的「AI未识别」任务（false=订单不存在/已 AI已处理/服务不可达）。 */
  pending: boolean
  error?: string
}

/**
 * 确保某单存在 pending 的「AI未识别」打标任务（幂等，POST /inbox/mark/request）。
 * - 订单不存在 → 服务 404 → pending=false（订单身份校验，绝不误标）。
 * - 已/将「AI已处理」→ 服务回 status=skipped_done → pending=false（不把已处理单打回未识别）。
 * - 服务不可达 → pending=false（不误标）。
 */
export async function ensureMarkUnrecognized(orderId: string): Promise<EnsureMarkResult> {
  try {
    const resp = await fetch(`${SERVICE_BASE}/inbox/mark/request`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ order_id: orderId, action: 'mark_unrecognized' }),
    })
    if (resp.ok) {
      const data = await resp.json().catch(() => ({}))
      return { ensured: true, pending: data?.status === 'pending' }
    }
    return { ensured: false, pending: false, error: `服务返回 ${resp.status}` }
  } catch {
    return { ensured: false, pending: false, error: '无法连接本地服务（是否已在 8770 启动？）' }
  }
}

/** 读自动抓取任务租约（flower 下发、扩展据 authorized 决定是否执行 + 据时间范围过滤）。 */
export async function getScrapeControl(): Promise<ScrapeControl> {
  const resp = await fetch(`${SERVICE_BASE}/inbox/scrape/control`)
  if (!resp.ok) throw new Error(`scrape/control 返回 ${resp.status}`)
  const data = await resp.json()
  return {
    authorized: Boolean(data.authorized),
    enabled: Boolean(data.enabled),
    interval_seconds: Number(data.interval_seconds) || 60,
    scrape_from: data.scrape_from ?? null,
    scrape_to: data.scrape_to ?? null,
    task_id: data.task_id ?? null,
    allowed_actions: data.allowed_actions ?? null,
  }
}

/** 上报本页订单轻清单，拿回该重抓的统一 worklist。 */
export async function postScrapeDiff(manifest: ManifestEntry[]): Promise<WorkItem[]> {
  const resp = await fetch(`${SERVICE_BASE}/inbox/scrape/diff`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ orders: manifest }),
  })
  if (!resp.ok) throw new Error(`scrape/diff 返回 ${resp.status}`)
  const data = await resp.json()
  return (data.worklist ?? []) as WorkItem[]
}

/** 拉「现在该重抓退款状态」的在产订单清单（退款重抓闭环触发器，拉模式）。 */
export async function getRefundPending(): Promise<PendingItem[]> {
  const resp = await fetch(`${SERVICE_BASE}/inbox/refund/pending`)
  if (!resp.ok) throw new Error(`refund/pending 返回 ${resp.status}`)
  const data = await resp.json()
  return (data.pending ?? []) as PendingItem[]
}

/**
 * 把本页重抓到的实时退款状态回 /recheck（刷新 Order.refund_status + 落审计 → 该单在 interval 内掉出 pending）。
 * 后台刷新闭环用 stage=typesetting（最宽松）、operator=auto-recheck（审计里区分于真人产线闸门检查）。
 */
export async function postRecheck(
  orderId: string,
  refundStatus: string | null,
  stage: RefundStage = 'typesetting',
): Promise<RecheckResult> {
  const body: Record<string, unknown> = { stage, operator: 'auto-recheck' }
  if (refundStatus) body.refund_status = refundStatus
  try {
    const resp = await fetch(`${SERVICE_BASE}/inbox/orders/${encodeURIComponent(orderId)}/recheck`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (resp.ok) {
      const data = await resp.json()
      return { ok: true, action: data.action, blocked: Boolean(data.blocked) }
    }
    return { ok: false, error: `服务返回 ${resp.status}` }
  } catch {
    return { ok: false, error: '无法连接本地服务（是否已在 8770 启动？）' }
  }
}

/** 定向重抓握手（option B）：拉「该去店小秘搜索并重抓」的 order_id 队列。 */
export async function getRescrapeQueue(): Promise<string[]> {
  const resp = await fetch(`${SERVICE_BASE}/inbox/refund/rescrape/queue`)
  if (!resp.ok) throw new Error(`rescrape/queue 返回 ${resp.status}`)
  const data = await resp.json()
  return (data.order_ids ?? []) as string[]
}

/** 定向重抓握手：回填某单结果（found=false=店小秘搜不到；found=true 带回实时 refund_status）。 */
export async function postRescrapeResult(
  orderId: string,
  found: boolean,
  refundStatus?: string,
): Promise<void> {
  const body: Record<string, unknown> = { order_id: orderId, found }
  if (found && refundStatus) body.refund_status = refundStatus
  try {
    await fetch(`${SERVICE_BASE}/inbox/refund/rescrape/result`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    /* 回填失败不致命：Ezcad 侧轮询会超时→按 D4 从严阻断 */
  }
}

/** 标记回写：拉「待给店小秘打标」的任务队列（limit=每轮上限，串行写防封号）。 */
export async function getMarkPending(limit?: number): Promise<MarkJob[]> {
  const url = limit
    ? `${SERVICE_BASE}/inbox/mark/pending?limit=${encodeURIComponent(limit)}`
    : `${SERVICE_BASE}/inbox/mark/pending`
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`mark/pending 返回 ${resp.status}`)
  const data = await resp.json()
  return (data.jobs ?? []) as MarkJob[]
}

/** 标记回写：回填某任务结果（ok=已打标成功；失败=记 attempts，超上限服务端置 failed）。 */
export async function postMarkResult(
  orderId: string,
  action: MarkAction,
  ok: boolean,
  detail?: string,
): Promise<void> {
  const body: Record<string, unknown> = { order_id: orderId, action, ok }
  if (detail) body.detail = detail
  try {
    await fetch(`${SERVICE_BASE}/inbox/mark/result`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    /* 回填失败不致命：该单若没 done 仍在 pending，下轮重试（打标幂等，重试无害） */
  }
}

/**
 * AI 识别状态对账：上报某订单页面是否带「AI已处理」/「AI未识别」标记，服务以 DB ai_status
 * 为唯一权威做原子 get-or-create + 判定，返回 desired_tag（扩展据此同步页面标记）。
 *
 * ⚠️ 查询失败（网络/服务不可达/非 2xx）→ **返回 null**（调用方据此跳过、绝不改标签——
 * 对应需求「数据库查询失败时不得修改标签」）。
 */
export async function reconcileAiStatus(
  orderId: string,
  aiDone: boolean,
  aiUnrecognized: boolean,
): Promise<ReconcileDecision | null> {
  try {
    const resp = await fetch(`${SERVICE_BASE}/inbox/ai/reconcile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        order_id: orderId,
        ai_done: aiDone,
        ai_unrecognized: aiUnrecognized,
      }),
    })
    if (!resp.ok) return null
    const data = await resp.json()
    if (!data || typeof data.desired_tag !== 'string') return null
    return data as ReconcileDecision
  } catch {
    return null // 查库失败 → 不改标签
  }
}

export async function checkHealth(): Promise<boolean> {
  try {
    const resp = await fetch(`${SERVICE_BASE}/healthz`)
    return resp.ok
  } catch {
    return false
  }
}
