import type { RawOrder } from '../shared/contract'
import { collectOrders } from './extractor'
import { SEARCH_SUBMIT_TEXT, SELECTORS } from './selectors'

// 店小秘「搜索订单」页交互（定向重抓 option B）：
// 搜索表单是 Ant Design（受控输入，须走原生 value setter + input 事件，直接赋 .value 框架收不到）；
// 搜索结果表仍是 vxe-table → 复用 collectOrders 解析。

export function findSearchInput(root: ParentNode): HTMLInputElement | null {
  // 用选择器直接定位 <input>，不做 instanceof（跨 JSDOM realm 会误判 false，且现有提取器也走鸭子类型）。
  const el = root.querySelector(SELECTORS.searchInput) ?? root.querySelector(SELECTORS.searchInputFallback)
  return (el as HTMLInputElement | null) ?? null
}

/**
 * 当前页是否可处理定向重抓 = 有订单号搜索框（搜索订单页）**或**当前页已有订单行（列表页可直接读可见单）。
 * 操作员常待在「已退款/全部订单」等列表页而非专门搜索页，故两者都算可处理。
 */
export function canSearch(root: ParentNode): boolean {
  return findSearchInput(root) !== null || collectOrders(root).length > 0
}

function setNativeValue(input: HTMLInputElement, value: string): void {
  // 受控输入：用原型链上的原生 value setter 赋值，再派发 input/change，框架(v-model)才会接收。
  // 事件构造器取元素自身窗口（跨 realm 安全），不用全局 Event。
  const win = (input.ownerDocument?.defaultView ?? globalThis) as Window & typeof globalThis
  const proto = Object.getPrototypeOf(input) as object
  const setter =
    Object.getOwnPropertyDescriptor(proto, 'value')?.set ??
    Object.getOwnPropertyDescriptor(win.HTMLInputElement?.prototype ?? {}, 'value')?.set
  if (setter) setter.call(input, value)
  else input.value = value
  // 优先 InputEvent(更贴近真实键入,部分 antd/受控实现只认它);realm 无 InputEvent 时回退 Event。
  const InputEvt = (win as unknown as { InputEvent?: typeof InputEvent }).InputEvent ?? win.Event
  input.dispatchEvent(new InputEvt('input', { bubbles: true }))
  input.dispatchEvent(new win.Event('change', { bubbles: true }))
}

function findSearchButton(root: ParentNode): HTMLButtonElement | null {
  // 只认文本精确为「搜索」的主按钮；找不到就返回 null → 走回车提交兜底，
  // 绝不回退到 buttons[0]（店小秘改版/文案变时可能误点批量/导出等别的主按钮）。
  const buttons = Array.from(root.querySelectorAll(SELECTORS.searchSubmit))
  const byText = buttons.find((b) => (b.textContent ?? '').trim() === SEARCH_SUBMIT_TEXT)
  return (byText as HTMLButtonElement | undefined) ?? null
}

/** 在搜索框填订单号并提交（优先点「搜索」按钮，找不到则输入框回车）。返回是否成功发起。 */
export function fillSearchAndSubmit(root: ParentNode, orderId: string): boolean {
  const input = findSearchInput(root)
  if (!input) return false
  input.focus?.()
  setNativeValue(input, orderId.trim())
  const btn = findSearchButton(root)
  if (btn) {
    btn.click()
    return true
  }
  const win = (input.ownerDocument?.defaultView ?? globalThis) as Window & typeof globalThis
  input.dispatchEvent(
    new win.KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true }),
  )
  return true
}

/** 在搜索结果（vxe-table，复用 collectOrders）里找指定订单号的整单；找不到返回 null。 */
export function findOrderInResults(root: ParentNode, orderId: string): RawOrder | null {
  const target = orderId.trim()
  for (const hit of collectOrders(root)) {
    if (hit.order.order_id === target) return hit.order
  }
  return null
}
