import type { RawOrder, RawOrderItem } from '../shared/contract'
import { PAID_LABEL, SELECTORS } from './selectors'

// 纯函数提取器：输入 DOM 根，按 vxe 行结构 + rowid 配对收集订单。无 chrome.* / 全局依赖，可单测。

export interface OrderHit {
  order: RawOrder
  rowid: string
  /** 注入「→Flower」按钮的锚点（订单号单元格）。 */
  anchorEl: Element
}

function clean(text: string | null | undefined): string {
  return (text ?? '').replace(/\s+/g, ' ').trim()
}

function firstText(rows: Element[], selector: string): string {
  for (const row of rows) {
    const value = clean(row.querySelector(selector)?.textContent)
    if (value) return value
  }
  return ''
}

/** 把某范围内的定制项各行（Label  ：Value）规整成单行 "Label: Value / Label: Value …"。 */
function regularizeAttrLines(scope: ParentNode): string {
  const lines = Array.from(scope.querySelectorAll(SELECTORS.attrLines))
    .map((el) => clean(el.textContent))
    .filter(Boolean)
  return lines.map((line) => clean(line.replace(/\s*：\s*/, ': '))).join(' / ')
}

/** 把定制项各行规整成单行，作为发给 Flower 的整单备注（多件订单天然拼接各块，保持旧单件行为）。 */
function buildRemark(detailRows: Element[]): string {
  for (const row of detailRows) {
    const text = regularizeAttrLines(row)
    if (text) return text
  }
  return ''
}

/**
 * 枚举订单的行项目：每个 `.order-sku` 块 = 一件商品。只抓结构与原文，不判定目标盒子 / 不拆语义。
 * vxe 固定列不会重复商品列，故跨 detailRows 收集即真实块、无重复。
 */
function collectItems(detailRows: Element[]): RawOrderItem[] {
  const items: RawOrderItem[] = []
  for (const row of detailRows) {
    for (const block of Array.from(row.querySelectorAll(SELECTORS.skuBlock))) {
      const item: RawOrderItem = { line_index: items.length }
      const sku = clean(block.querySelector(SELECTORS.skuName)?.textContent)
      if (sku) item.product_sku = sku
      const qtyRaw = clean(block.querySelector(SELECTORS.skuQuantity)?.textContent)
      if (/^\d+$/.test(qtyRaw)) {
        const qty = Number(qtyRaw)
        if (qty >= 1) item.quantity = qty
      }
      const personalization = regularizeAttrLines(block)
      if (personalization) item.personalization_raw = personalization
      const extras = collectItemExtras(block)
      if (extras) item.extras = extras
      items.push(item)
    }
  }
  return items
}

/** 行项目兜底字段：listing 链接 / 单价 / 缩略图，便于「其他商品」配货提醒展示（计划 D5）。 */
function collectItemExtras(block: Element): Record<string, unknown> | undefined {
  const extras: Record<string, unknown> = {}
  const href = block.querySelector(SELECTORS.skuName)?.getAttribute('href')
  if (href) extras.listing_url = href
  const price = clean(block.querySelector(SELECTORS.skuPrice)?.textContent)
  if (price) extras.price = price
  const img = block.querySelector(SELECTORS.skuImage)?.getAttribute('src')
  if (img) extras.thumbnail = img
  return Object.keys(extras).length ? extras : undefined
}

/** 订单实时状态原文（`.orderState` 首个 div），如「已退款 / 风控中 / 已发货」；退款拦截用。 */
function readOrderState(detailRows: Element[]): string {
  for (const row of detailRows) {
    const cell = row.querySelector(SELECTORS.orderState)
    if (!cell) continue
    const value = clean(cell.querySelector('div')?.textContent ?? cell.textContent)
    if (value) return value
  }
  return ''
}

/** 付款时间原文（时间轴里「付款：<time>」那项的时间）；自动抓取的时间基准。 */
function readPaidAt(detailRows: Element[]): string {
  for (const row of detailRows) {
    for (const item of Array.from(row.querySelectorAll(SELECTORS.orderTimeItem))) {
      const text = clean(item.textContent)
      if (!text.startsWith(PAID_LABEL)) continue
      const span = clean(item.querySelector('span')?.textContent)
      if (span) return span
      const match = text.match(/付款[：:]\s*(.+)$/)
      if (match) return clean(match[1])
    }
  }
  return ''
}

function hasAiMark(headerRows: Element[]): boolean {
  return headerRows.some(
    (row) => row.querySelector(SELECTORS.aiMarkIcon) !== null || row.querySelector(SELECTORS.aiMarkBlock) !== null,
  )
}

/** 该订单是否已打「AI已处理」标记（表头行含 icon_change_order）；标准1 用它跳过已处理单。 */
function hasAiDone(headerRows: Element[]): boolean {
  return headerRows.some((row) => row.querySelector(SELECTORS.appliedDoneIcon) !== null)
}

export function collectOrders(root: ParentNode): OrderHit[] {
  const hits: OrderHit[] = []
  const seen = new Set<string>()
  for (const anchor of Array.from(root.querySelectorAll(SELECTORS.orderCodeCell))) {
    const span = anchor.querySelector('span.pointer') ?? anchor.querySelector('span')
    const orderId = clean(span?.textContent)
    if (!/^\d{6,}$/.test(orderId)) continue
    const row = anchor.closest('tr')
    const rowid = row?.getAttribute('rowid') ?? ''
    const key = rowid || orderId
    if (seen.has(key)) continue
    seen.add(key)

    // 按 rowid 跨子表收齐明细行 / 表头行（vxe 固定列会产生同 rowid 的重复行）。
    const numericRowid = /^\d+$/.test(rowid)
    const detailRows = numericRowid
      ? Array.from(root.querySelectorAll(`tr[rowid="${rowid}"]`))
      : row
        ? [row]
        : []
    const headerRows = numericRowid ? Array.from(root.querySelectorAll(`tr[rowid="${rowid}_header"]`)) : []
    const effectiveDetail = detailRows.length ? detailRows : row ? [row] : []

    const items = collectItems(effectiveDetail)
    const refundStatus = readOrderState(effectiveDetail)
    const paidAt = readPaidAt(effectiveDetail)
    const order: RawOrder = {
      order_id: orderId,
      remark: buildRemark(effectiveDetail),
      shop: firstText(headerRows, SELECTORS.shopCell) || undefined,
      spec: firstText(effectiveDetail, SELECTORS.skuName) || undefined,
      ai_unrecognized: hasAiMark(headerRows),
      ai_done: hasAiDone(headerRows),
      items: items.length ? items : undefined,
      refund_status: refundStatus || undefined,
      paid_at: paidAt || undefined,
    }
    hits.push({ order, rowid: key, anchorEl: anchor })
  }
  return hits
}

/** 便利封装：取第一个订单（详情页或只有一单时用）。列表页请用 collectOrders。 */
export function extractOrder(root: ParentNode): RawOrder {
  return collectOrders(root)[0]?.order ?? { order_id: '', remark: '' }
}
