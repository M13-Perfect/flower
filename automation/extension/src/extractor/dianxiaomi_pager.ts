// 店小秘列表页 vxe-pager 翻页 DOM 胶水（仅本文件碰翻页器选择器，改版只动这里 + selectors.ts）。
// 自动翻页用：上一页/下一页按钮 + 滚到底加载满本页（vxe 虚拟滚动，不滚只渲染可见行）。
// 页面可能有多张 vxe 表（左固定/主/右固定）→ 多个 pager；取「可见且未禁用」的那个操作。

import { PAGER_DISABLED_CLASS, SELECTORS } from './selectors'

function isVisible(el: HTMLElement): boolean {
  return el.offsetParent !== null || el.getClientRects().length > 0
}

/** 取可见的翻页按钮（多 pager 时优先可见的；都不可见回退第一个）。 */
function pagerButton(doc: Document, selector: string): HTMLButtonElement | null {
  const btns = Array.from(doc.querySelectorAll<HTMLButtonElement>(selector))
  return btns.find(isVisible) ?? btns[0] ?? null
}

function isDisabled(btn: HTMLButtonElement | null): boolean {
  return !btn || btn.disabled || btn.classList.contains(PAGER_DISABLED_CLASS)
}

/** 页面上是否存在翻页器（不在列表页 / 无分页则 false）。 */
export function hasPager(doc: Document): boolean {
  return pagerButton(doc, SELECTORS.pagerNextBtn) !== null
}

/** 已是最后一页（下一页按钮禁用或不存在）。 */
export function isNextDisabled(doc: Document): boolean {
  return isDisabled(pagerButton(doc, SELECTORS.pagerNextBtn))
}

/** 已是第一页（上一页按钮禁用或不存在）。 */
export function isPrevDisabled(doc: Document): boolean {
  return isDisabled(pagerButton(doc, SELECTORS.pagerPrevBtn))
}

/** 点「下一页」；已是末页返回 false（不点）。 */
export function clickNextPage(doc: Document): boolean {
  const btn = pagerButton(doc, SELECTORS.pagerNextBtn)
  if (isDisabled(btn)) return false
  btn!.click()
  return true
}

/** 点「上一页」；已是首页返回 false（不点）。 */
export function clickPrevPage(doc: Document): boolean {
  const btn = pagerButton(doc, SELECTORS.pagerPrevBtn)
  if (isDisabled(btn)) return false
  btn!.click()
  return true
}

/** 当前区间文本（「第101-165条，」），调试/可观测用；无则空串。 */
export function readRangeText(doc: Document): string {
  return (doc.querySelector(SELECTORS.pagerRange)?.textContent ?? '').trim()
}

/** 把所有 vxe 表体滚动容器滚到底，触发虚拟滚动渲染满本页（拿全 100 行）。 */
export function scrollTableToBottom(doc: Document): void {
  for (const w of Array.from(doc.querySelectorAll<HTMLElement>(SELECTORS.tableBodyWrapper))) {
    w.scrollTop = w.scrollHeight
  }
}
