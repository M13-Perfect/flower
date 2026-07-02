import type {
  ManifestEntry,
  PendingItem,
  RawOrder,
  RecheckResult,
  ScrapeControl,
  WorkItem,
} from '../shared/contract'
import { isAuthorized, orderInScope } from './authorization'

// 自动抓取一轮的纯编排逻辑（依赖注入，可单测；chrome/fetch 胶水在 service-worker.ts 注入真实实现）。
// 流程：读开关 → 关则跳过；开则
//   ① 上报清单(manifest) → 服务 diff 得 worklist → 逐单全量推送（抓新单 / 补不全 / 刷退款）；
//   ② 退款重抓闭环：拉 /refund/pending → 对本页可见的在产单，把实时退款状态回 /recheck（把服务能力接通的最后一环）。
// 服务不抓店小秘，两步都只处理「本页可见」的单；不在本页的（更早页）本轮跳过（翻页是后续增强）。

const DEFAULT_INTERVAL = 60

export interface CycleDeps {
  getControl: () => Promise<ScrapeControl>
  postDiff: (manifest: ManifestEntry[]) => Promise<WorkItem[]>
  /** 批量回传 worklist 命中本页、非空的单（一次 /orders/batch；全 POST 本地 service、无封号风险）。返回逐单结果。 */
  pushOrders: (orders: RawOrder[]) => Promise<Array<{ order_id: string; ok: boolean; error?: string }>>
  /** 退款重抓闭环：拉「该重抓退款状态」的在产单清单。 */
  getPending: () => Promise<PendingItem[]>
  /** 退款重抓闭环：把本页实时退款状态回写并判定。 */
  postRecheck: (orderId: string, refundStatus: string | null) => Promise<RecheckResult>
}

export interface CycleResult {
  enabled: boolean
  intervalSeconds: number
  manifestCount: number
  worklistCount: number
  pushed: number
  failed: number
  skipped: number
  /** 退款重抓闭环：本轮回了 /recheck 的单数。 */
  rechecked: number
  /** 其中被判定 block（确认退款/取消）的单数 —— 供操作员告警。 */
  recheckBlocked: number
}

/** 把本页订单投影成轻清单（order_id + 付款时间）上报给服务。
 * 标准1：已打「AI已处理」的单**排除**（不抓不传）；其余交服务 diff 判 new/incomplete/stale。 */
export function buildManifest(orders: RawOrder[]): ManifestEntry[] {
  return orders
    .filter((order) => order.order_id)
    .filter((order) => !order.ai_done)
    .map((order) => ({ order_id: order.order_id, paid_at: order.paid_at }))
}

/** 真正空单：既无备注又无行项目 → 推了也是 incomplete（无 items）会每轮反复重推，不如本页就跳过。 */
function isEmptyOrder(order: RawOrder): boolean {
  return !order.remark && !(order.items && order.items.length > 0)
}

export async function runAutoCycle(orders: RawOrder[], deps: CycleDeps): Promise<CycleResult> {
  const control = await deps.getControl()
  const intervalSeconds = control.interval_seconds || DEFAULT_INTERVAL
  const base: CycleResult = {
    enabled: control.enabled,
    intervalSeconds,
    manifestCount: 0,
    worklistCount: 0,
    pushed: 0,
    failed: 0,
    skipped: 0,
    rechecked: 0,
    recheckBlocked: 0,
  }
  // ⚠️ P0：唯一执行判据是任务租约授权（非 enabled）。未授权 → 整轮 no-op（SW 侧 fail-closed，
  // 与 content 侧 gate 双保险；即便 content 误调本消息，无授权也绝不产生副作用）。
  if (!isAuthorized(control)) return base

  // 范围闸：只处理落在任务时间窗内的订单（防把历史/范围外单纳入抓取与打标）。
  const scoped = orders.filter((order) => orderInScope(order, control))
  const byId = new Map(scoped.map((order) => [order.order_id, order]))

  // ① 抓取：上报清单 → diff → 批量推送（worklist 命中本页、非空的单，一次 /orders/batch）。
  const manifest = buildManifest(scoped)
  base.manifestCount = manifest.length
  const worklist = await deps.postDiff(manifest)
  base.worklistCount = worklist.length
  const toPush: RawOrder[] = []
  for (const item of worklist) {
    const order = byId.get(item.order_id)
    if (!order) {
      base.skipped++ // worklist 项不在本页可见集 → 本轮无法抓，跳过（翻页能力是后续增强）
      continue
    }
    if (isEmptyOrder(order)) {
      base.skipped++ // 既无备注又无行项目 → 跳过，避免反复推不全单（D-1 防御）
      continue
    }
    toPush.push(order)
  }
  if (toPush.length > 0) {
    const results = await deps.pushOrders(toPush)
    const okIds = new Set(results.filter((r) => r.ok).map((r) => r.order_id))
    for (const order of toPush) {
      if (okIds.has(order.order_id)) base.pushed++
      else base.failed++
    }
  }

  // ② 退款重抓闭环：拉在产待重抓清单，对本页可见单把实时退款状态回 /recheck。
  // 不在本页的单本轮跳过（不计 skipped，避免与抓取统计混淆）；回了 /recheck 即在 interval 内掉出 pending。
  await runRefundRecheck(byId, deps, base)

  return base
}

async function runRefundRecheck(
  byId: Map<string, RawOrder>,
  deps: CycleDeps,
  base: CycleResult,
): Promise<void> {
  let pending: PendingItem[]
  try {
    pending = await deps.getPending()
  } catch {
    return // 触发器端点不可用（旧服务/网络）→ 本轮跳过退款闭环，不影响抓取结果
  }
  for (const item of pending) {
    const order = byId.get(item.order_id)
    if (!order) continue // 在产单不在本页 → 翻页能力是后续增强
    if (!order.refund_status) continue // 本页没抓到实时状态（罕见）→ 不回 /recheck，留待下轮
    const result = await deps.postRecheck(item.order_id, order.refund_status)
    if (!result.ok) continue
    base.rechecked++
    if (result.blocked) base.recheckBlocked++
  }
}
