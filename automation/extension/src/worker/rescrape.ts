import type { RawOrder } from '../shared/contract'

// 定向重抓一轮的纯编排（option B）：依赖注入，可单测；DOM 搜索 + chrome 消息胶水在 content 注入。
// 流程：(在店小秘搜索页才跑) 拉队列 → 逐单在店小秘按单号搜索+抓取 → 找到则推送刷新 + 回填 done(带状态)，
//       搜不到则回填 not_found。不在搜索页 → 整轮跳过、把单留在队列（pending），等操作员到搜索页再处理。

export interface RescrapeDeps {
  /** 当前页是否能搜索（店小秘搜索页、有搜索框）。false → 本轮不处理，保留队列。 */
  canSearch: () => boolean
  /** 拉「该定向重抓」的 order_id 队列。 */
  getQueue: () => Promise<string[]>
  /** 在店小秘按订单号搜索并抓取该单；找到返回 RawOrder（含 refund_status），搜不到返回 null。 */
  searchAndExtract: (orderId: string) => Promise<RawOrder | null>
  /** 把抓到的整单推送回服务（刷新 refund_status + items[]）。 */
  pushOrder: (order: RawOrder) => Promise<{ ok: boolean }>
  /** 回填定向重抓结果（found=true 带回实时 refund_status；false=搜不到）。 */
  postResult: (orderId: string, found: boolean, refundStatus?: string) => Promise<void>
}

export interface RescrapeRunResult {
  skipped: boolean // 不在搜索页 → 整轮跳过
  processed: number
  found: number
  notFound: number
}

export async function runRescrapeJobs(deps: RescrapeDeps): Promise<RescrapeRunResult> {
  const result: RescrapeRunResult = { skipped: false, processed: 0, found: 0, notFound: 0 }
  if (!deps.canSearch()) {
    result.skipped = true
    return result // 不在搜索页：保留队列，等下一轮/操作员切到搜索页
  }
  let queue: string[]
  try {
    queue = await deps.getQueue()
  } catch {
    return result // 服务/SW 不可用 → 本轮不动队列
  }
  for (const orderId of queue) {
    result.processed++
    let order: RawOrder | null = null
    try {
      order = await deps.searchAndExtract(orderId)
    } catch {
      order = null
    }
    const status = order?.refund_status
    if (order && status) {
      await deps.pushOrder(order) // 刷新 items[]（其他商品提醒）+ refund_status
      await deps.postResult(orderId, true, status)
      result.found++
    } else {
      // 搜到了单但没抓到状态原文（罕见）也算 not_found：从严，让 Ezcad 按 D4 阻断而非误放行。
      await deps.postResult(orderId, false)
      result.notFound++
    }
  }
  return result
}
