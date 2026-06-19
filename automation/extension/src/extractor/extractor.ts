import type { RawOrder } from '../shared/contract'
import { SELECTORS } from './selectors'

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

/** 把定制项各行（Label  ：Value）规整成单行 "Label: Value / Label: Value …"，作为发给 Flower 的备注。 */
function buildRemark(detailRows: Element[]): string {
  for (const row of detailRows) {
    const lines = Array.from(row.querySelectorAll(SELECTORS.attrLines))
      .map((el) => clean(el.textContent))
      .filter(Boolean)
    if (lines.length) {
      return lines.map((line) => clean(line.replace(/\s*：\s*/, ': '))).join(' / ')
    }
  }
  return ''
}

function hasAiMark(headerRows: Element[]): boolean {
  return headerRows.some(
    (row) => row.querySelector(SELECTORS.aiMarkIcon) !== null || row.querySelector(SELECTORS.aiMarkBlock) !== null,
  )
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

    const order: RawOrder = {
      order_id: orderId,
      remark: buildRemark(effectiveDetail),
      shop: firstText(headerRows, SELECTORS.shopCell) || undefined,
      spec: firstText(effectiveDetail, SELECTORS.skuName) || undefined,
      ai_unrecognized: hasAiMark(headerRows),
    }
    hits.push({ order, rowid: key, anchorEl: anchor })
  }
  return hits
}

/** 便利封装：取第一个订单（详情页或只有一单时用）。列表页请用 collectOrders。 */
export function extractOrder(root: ParentNode): RawOrder {
  return collectOrders(root)[0]?.order ?? { order_id: '', remark: '' }
}
