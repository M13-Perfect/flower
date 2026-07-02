import type { RawOrder } from '../shared/contract'

// 翻页扫描 + 游标（「页面记录」）的纯编排逻辑（依赖注入，可单测；DOM 翻页/滚动胶水在 content.ts 注入）。
//
// 游标 = 高水位付款时间：语义「paid_at 比游标新的单都已抓全」。店小秘列表按付款时间倒序、新单进第 1 页。
// 每轮从第 1 页起逐页抓，碰到「本页含 paid_at <= 游标 的单」（= 接上已抓全区域）或末页或翻页上限即停；
// 完成后把游标推进到本轮见过的最新 paid_at。
//   稳态（没积压）：第 1 页就含旧单 → 立刻触及游标 → 只读一页。
//   洪峰（涌入 > 1 页）：往后翻到接上游标为止 → 不每轮全量重读所有页（用户要的「页面记录」）。
// 游标只是「少翻几页」的优化：丢了也不影响正确性（服务端 diff 兜底去重），最多多翻一轮。
//
// paid_at 用店小秘原文字符串「YYYY-MM-DD HH:MM」比较：字典序 == 时间序，无需解析日期。

export interface PagedSweepDeps {
  /** 回到第 1 页（最新）。稳态下应是廉价 no-op（已在首页）。 */
  gotoFirstPage: () => Promise<void>
  /** 读当前页订单（含滚到底加载满本页）。 */
  readPage: () => Promise<RawOrder[]>
  /** 对一页订单跑一轮抓取（diff + 批量推送 + 退款闭环）。 */
  runCycle: (orders: RawOrder[]) => Promise<void>
  /** 翻到下一页；已是最后一页返回 false。 */
  gotoNextPage: () => Promise<boolean>
  /** 读游标（上次抓全到的最新 paid_at）；无则 null。 */
  getCursor: () => Promise<string | null>
  /** 写游标。 */
  setCursor: (cursor: string) => Promise<void>
  /** 安全上限：一轮最多翻几页（防超大 backlog 一次扫爆 / 选择器击穿时死循环）。默认 30。 */
  maxPages?: number
  /**
   * P0：本页是否已越过任务时间窗下界（整页都旧于 scrape_from）。返回 true → 停止翻页，
   * 不再往历史方向翻（防回溯扫描历史订单）。缺省=不据此停（交给游标/末页/上限）。
   */
  reachedFloor?: (orders: RawOrder[]) => boolean
}

export interface SweepResult {
  pages: number
  ordersSeen: number
  reachedCursor: boolean
  cursorBefore: string | null
  cursorAfter: string | null
}

/** 本页是否已触及游标（含 paid_at <= 游标 的单 = 接上已抓全区域）。
 * 游标为 null（首次）→ 永不触及，须翻到末页 / 上限（首轮全量建库）。 */
export function pageReachedCursor(orders: RawOrder[], cursor: string | null): boolean {
  if (!cursor) return false
  return orders.some((order) => !!order.paid_at && order.paid_at <= cursor)
}

/** 取一批单里最新的 paid_at（无 paid_at 的忽略）；都没有则返回 fallback。 */
export function maxPaidAt(orders: RawOrder[], fallback: string | null): string | null {
  let max = fallback
  for (const order of orders) {
    if (order.paid_at && (max === null || order.paid_at > max)) max = order.paid_at
  }
  return max
}

/** 翻页扫描一轮：第 1 页起逐页抓，碰游标 / 末页 / 上限即停，结束推进游标。 */
export async function runPagedSweep(deps: PagedSweepDeps): Promise<SweepResult> {
  const maxPages = deps.maxPages ?? 30
  await deps.gotoFirstPage()
  const cursorBefore = await deps.getCursor()
  let cursorAfter = cursorBefore
  let pages = 0
  let ordersSeen = 0
  let reachedCursor = false
  while (pages < maxPages) {
    const orders = await deps.readPage()
    pages++
    ordersSeen += orders.length
    await deps.runCycle(orders)
    cursorAfter = maxPaidAt(orders, cursorAfter)
    if (pageReachedCursor(orders, cursorBefore)) {
      reachedCursor = true
      break
    }
    // P0：整页越过时间窗下界 → 停止（再往后翻都是更早的历史单）。
    if (deps.reachedFloor && deps.reachedFloor(orders)) break
    if (!(await deps.gotoNextPage())) break
  }
  if (cursorAfter && cursorAfter !== cursorBefore) await deps.setCursor(cursorAfter)
  return { pages, ordersSeen, reachedCursor, cursorBefore, cursorAfter }
}
