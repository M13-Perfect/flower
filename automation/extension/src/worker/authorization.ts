import type { RawOrder, ScrapeControl } from '../shared/contract'

// 扩展侧统一授权守卫（P0 2026-06-22）。
//
// 单一判据来源：服务端 GET /inbox/scrape/control 返回的 ScrapeControl.authorized（由 inbox-service
// 据任务租约 + 服务端时钟算出）。扩展所有副作用入口（自动抓取循环、翻页、推送、打标）都过这里，
// 任何一处都不另写判断、也绝不信任 chrome.storage / localStorage / 内存里残留的 enabled/running/旧任务。
//
// fail-closed：control 为空 / authorized 非 true / 缺时间范围 → 一律未授权；订单缺付款时间 / 越窗 → 不在范围。

export const MARK_ACTION = 'mark'
export const SCRAPE_ACTION = 'scrape'

/** 当前是否被授权执行（唯一判据）。旧服务无 authorized 字段 → undefined → false。 */
export function isAuthorized(control: ScrapeControl | null | undefined): boolean {
  return Boolean(control && control.authorized)
}

/** 某具体操作（scrape/mark）当前是否被授权：先要整体授权，再看它在 allowed_actions 里。 */
export function actionAllowed(control: ScrapeControl | null | undefined, action: string): boolean {
  if (!isAuthorized(control)) return false
  const csv = control?.allowed_actions ?? ''
  return csv
    .split(',')
    .map((a) => a.trim())
    .includes(action)
}

/**
 * 把墙钟时间串归一成可比较的数字 YYYYMMDDHHMMSS。
 * 同时吃店小秘付款时间「2026-06-19 02:25」与服务端 ISO「2026-06-19T00:00:00」——
 * 两者都是店小秘墙钟、同域比较即正确；用数字比避免「空格 0x20 < T 0x54」的字典序陷阱。
 */
export function toComparable(value: string | null | undefined): number | null {
  if (!value) return null
  const m = value.match(/(\d{4})\D(\d{1,2})\D(\d{1,2})\D(\d{1,2})\D(\d{2})(?:\D(\d{2}))?/)
  if (!m) return null
  const pad = (s: string) => s.padStart(2, '0')
  return Number(`${m[1]}${pad(m[2])}${pad(m[3])}${pad(m[4])}${pad(m[5])}${pad(m[6] ?? '00')}`)
}

/**
 * 订单是否落在当前任务的**付款时间范围** [scrape_from, scrape_to] 内。
 * fail-closed：未授权 / 无付款时间（无法按时间判定，防历史/未付款单混入）/ 越窗 → false。
 */
export function orderInScope(order: RawOrder, control: ScrapeControl | null | undefined): boolean {
  if (!isAuthorized(control)) return false
  const paid = toComparable(order.paid_at)
  if (paid === null) return false
  const from = toComparable(control?.scrape_from)
  if (from !== null && paid < from) return false
  const to = toComparable(control?.scrape_to)
  if (to !== null && paid > to) return false
  return true
}

/**
 * 本页是否已**整页越过时间窗下界**（所有带付款时间的单都早于 scrape_from）。
 * 店小秘列表按付款时间倒序 → 一旦整页都旧于下界，再往后翻只会是更早的历史单 → 应停止翻页（防回溯扫历史）。
 * 无下界 / 本页没有可判定付款时间的单 → 返回 false（不据此停，交给游标/末页/上限）。
 */
export function pageBelowWindowFloor(
  orders: RawOrder[],
  control: ScrapeControl | null | undefined,
): boolean {
  const from = toComparable(control?.scrape_from)
  if (from === null) return false
  const paids = orders
    .map((o) => toComparable(o.paid_at))
    .filter((n): n is number => n !== null)
  if (paids.length === 0) return false
  return paids.every((p) => p < from)
}
