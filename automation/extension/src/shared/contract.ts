// 与 automation/contracts/order.schema.json 对齐的类型（手写镜像；后续可由 schema 生成替换）。

export const SCHEMA_VERSION = '1.0'

/**
 * 订单行项目（一单多件）。与 order.schema.json 的 items[] 对齐。
 * 扩展只抓「结构 + 原文」，不做语义拆分 / 不判定 is_target_box（交给 Flower GPT 解析层）。
 */
export interface RawOrderItem {
  /** 订单内行项目序号，从 0 起。 */
  line_index: number
  /** 该行 listing id / SKU（`.order-sku__name` 文本）。 */
  product_sku?: string
  /** 该行件数（店小秘 ×N）；缺省按 1。 */
  quantity?: number
  /** 该行原始定制备注（规整成单行）。 */
  personalization_raw?: string
  /** 该行兜底字段（listing_url / price / thumbnail，便于「其他商品」展示）。 */
  extras?: Record<string, unknown>
}

/** 发往本地服务的订单报文（snake_case，与服务端 Pydantic OrderPayload 一致）。 */
export interface OrderPayload {
  schema_version: string
  order_id: string
  /** 2026-06-19 起可选（D-1）：标品/无定制单 remark 为空时不带，服务默认空串，数据走 items[]。 */
  remark?: string
  shop?: string
  spec?: string
  source_url?: string
  scraped_at?: string
  /** 店小秘订单实时状态（退款拦截用），首抓时写入原始状态文本。 */
  refund_status?: string
  /** 行项目（一单多件）；缺省=按 remark 走旧单件逻辑。 */
  items?: RawOrderItem[]
  extras?: Record<string, unknown>
}

/**
 * 上传入库后数据库侧结果（手动「→Flower」条件打标用，2026-06-22）：
 * - ``CREATED_NEW``：库里原本没有该（活跃）订单、本次新建**或复活软删行**（服务端 IngestResponse.created=true）。
 * - ``ALREADY_EXISTS``：库里已存在该活跃订单（created=false）。
 * - ``UNKNOWN``：上传成功但拿不到可信的 created 布尔（字段缺失/非布尔）→ 一律按未知处理、不打标。
 */
export type DatabaseResult = 'CREATED_NEW' | 'ALREADY_EXISTS' | 'UNKNOWN'

/** 提取器从页面抓到的原始字段（未补 schema_version / scraped_at）。 */
export interface RawOrder {
  order_id: string
  remark: string
  shop?: string
  spec?: string
  /** 该订单是否带「AI未识别」标记（icon_brush_bill）；随 extras 上报。 */
  ai_unrecognized?: boolean
  /** 该订单是否带「AI已处理」标记（icon_change_order）；标准1：已处理单不再抓取/上传。 */
  ai_done?: boolean
  /** 行项目（一单多件）；单件订单为长度 1 的数组。 */
  items?: RawOrderItem[]
  /** 店小秘订单实时状态原文（如「已退款 / 风控中 / 已发货」）；退款拦截用。 */
  refund_status?: string
  /** 店小秘付款时间原文（如「2026-06-19 02:25」）；自动抓取时间基准，随 extras.paid_at 上报。 */
  paid_at?: string
}

/**
 * 自动抓取**任务租约**（服务 GET /inbox/scrape/control 返回）。
 *
 * ⚠️ P0（2026-06-22）：扩展只信 ``authorized``（服务端时钟据任务租约算出）决定是否执行——
 * 不再用 ``enabled`` 单独判，也绝不信任 chrome.storage / localStorage 里残留的 enabled/running。
 * 无任务 / 租约过期 / 缺时间范围 → authorized=false → 扩展零采集/零翻页/零打标。
 */
export interface ScrapeControl {
  /** 服务端权威授权位：唯一的执行判据。旧服务无此字段 → undefined → 视为未授权（fail-closed）。 */
  authorized?: boolean
  enabled: boolean
  interval_seconds: number
  /** 订单时间范围下界（付款时间，墙钟）。授权时必有值。 */
  scrape_from: string | null
  /** 订单时间范围上界（付款时间，墙钟）；null=无上界。 */
  scrape_to?: string | null
  /** 当前任务 id；null=无任务。任务变更时扩展据它清掉旧翻页游标（不恢复历史扫描）。 */
  task_id?: string | null
  /** 允许操作 csv，如 "scrape,mark"。 */
  allowed_actions?: string | null
}

/** 服务 diff 返回的待重抓项（POST /inbox/scrape/diff）。 */
export interface WorkItem {
  order_id: string
  reason: 'new' | 'incomplete' | 'refund_refresh'
  paid_at: string | null
}

/** 扩展上报给服务的轻清单条目（order_id + 付款时间）。 */
export interface ManifestEntry {
  order_id: string
  paid_at?: string
}

/** 生产阶段（退款拦截闸门）。后台刷新闭环用 typesetting（最宽松，非不可逆阶段）。 */
export type RefundStage = 'typesetting' | 'engraving' | 'shipping'

/** 服务 GET /inbox/refund/pending 返回的「该重抓退款状态」的在产订单。 */
export interface PendingItem {
  order_id: string
  /** 库里最后已知状态（可能过期）；扩展据本页实时状态覆盖。 */
  refund_status: string | null
  status: string
  /** 订单页 URL，便于扩展定位（翻页能力是后续增强）。 */
  source_url: string | null
  received_at: string | null
}

/** POST /inbox/orders/{id}/recheck 的结果（退款重抓闭环回传新状态后服务判定）。 */
export interface RecheckResult {
  ok: boolean
  /** allow / warn / block（block=确认退款/取消，已拦截）。 */
  action?: string
  blocked?: boolean
  error?: string
}

/** 标记回写动作（服务 /inbox/mark/*）。unrecognized=打「AI未识别」；done=打「AI已处理」+清「AI未识别」。 */
export type MarkAction = 'mark_unrecognized' | 'mark_done'

/** 服务 GET /inbox/mark/pending 返回的一条待打标任务。 */
export interface MarkJob {
  order_id: string
  action: MarkAction
  /** 订单页 URL（便于定位/翻页，后续增强用）。 */
  source_url: string | null
}

/** AI 识别状态（DB 权威；与 inbox-service AI_STATUS_* 对齐）。 */
export type AiStatus = 'pending' | 'recognized' | 'conflict' | 'locked'

/** 对账后扩展应把页面同步成的目标标记：
 * pending=确保唯一「AI未识别」；recognized=「AI已处理」（清未识别）；none=不动标签（复核冻结/未授权）。 */
export type DesiredTag = 'pending' | 'recognized' | 'none'

/** 服务 POST /inbox/ai/reconcile 返回：以 DB ai_status 为唯一权威的对账判定。 */
export interface ReconcileDecision {
  desired_tag: DesiredTag
  ai_status: AiStatus | null
  conflict: boolean
  created: boolean
  /** 未授权/总开关关时为 false（此时 desired_tag 恒为 none）。 */
  authorized?: boolean
}
