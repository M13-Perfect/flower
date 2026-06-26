import type { MarkAction } from '../shared/contract'
import { MARK_CONFIRM_TEXT, MARK_LABELS, MARK_SELECTED_ICONS, SELECTORS } from './selectors'

// 店小秘「设置自定义标记」弹窗交互（标记回写）：定位订单标记区、开弹窗、读选中态、按 label 切换、确定。
// 真实 DOM（2026-06-20 只读勘查）：
//   订单行标记在表头行 tr[rowid="X_header"] 的 .bag-info-coustom；识别标记靠图标 class（颜色不唯一）。
//   弹窗 .markPopover（Ant Popover，全页单例）：.remark-item × N（.remark-item__text=label，
//   .remark-item__action 选中行多一个对勾 i），.markPopover__header 里 确定/取消。
// 纯 DOM 函数（无 chrome.*），可用 jsdom fixture 单测；真实点击/异步时序在 content.ts 注入。

/** 两个目标标记的键。 */
export type MarkLabelKey = 'unrecognized' | 'done'
/** 订单（或弹窗）上两个目标标记的当前态。 */
export interface MarkState {
  unrecognized: boolean
  done: boolean
}

const KEY_LABEL: Record<MarkLabelKey, string> = {
  unrecognized: MARK_LABELS.unrecognized,
  done: MARK_LABELS.done,
}

function clean(text: string | null | undefined): string {
  return (text ?? '').replace(/\s+/g, ' ').trim()
}

// ── 纯逻辑（幂等核心，与 DOM 无关，重点单测）──

/** 某动作要达成的目标态（mark_done 顺带清掉 AI未识别）。 */
export function targetFor(action: MarkAction): Partial<MarkState> {
  return action === 'mark_done' ? { done: true, unrecognized: false } : { unrecognized: true }
}

/** 当前态是否已满足目标（只看目标里声明的键）。 */
export function satisfies(current: MarkState, target: Partial<MarkState>): boolean {
  return (Object.keys(target) as MarkLabelKey[]).every((k) => current[k] === target[k])
}

/** 为达目标需要点击切换的标记键（仅当前态与目标不符的）。 */
export function togglesFor(current: MarkState, target: Partial<MarkState>): MarkLabelKey[] {
  return (Object.keys(target) as MarkLabelKey[]).filter((k) => current[k] !== target[k])
}

// ── 订单行（读已打标记 + 找触发控件）──

/** 找某订单的表头行（标记区所在）：订单号单元格 → rowid → tr[rowid="X_header"]（仿 extractor 行配对）。 */
export function findOrderHeaderRows(root: ParentNode, orderId: string): Element[] {
  const target = orderId.trim()
  for (const anchor of Array.from(root.querySelectorAll(SELECTORS.orderCodeCell))) {
    const span = anchor.querySelector('span.pointer') ?? anchor.querySelector('span')
    if (clean(span?.textContent) !== target) continue
    const row = anchor.closest('tr')
    const rowid = row?.getAttribute('rowid') ?? ''
    if (/^\d+$/.test(rowid)) {
      // 数字 rowid：标记区只在表头行。表头行此刻查不到（vxe 重渲染/卸载）→ 返回空 = 「读不到」，
      // **不回退到明细行**（明细行无标记区，会被误读成「未打标」→ mark_done 校验把成功当失败）。
      return Array.from(root.querySelectorAll(`tr[rowid="${rowid}_header"]`))
    }
    return row ? [row] : [] // 仅非数字 rowid（详情页等无表头结构）兜底用本行
  }
  return []
}

/** 读订单行已打的两个目标标记（靠图标 class，不靠颜色）。订单不在本页 → null。 */
export function readOrderRowMarks(root: ParentNode, orderId: string): MarkState | null {
  const headers = findOrderHeaderRows(root, orderId)
  if (!headers.length) return null
  let unrecognized = false
  let done = false
  for (const header of headers) {
    const area = header.querySelector(SELECTORS.orderMarkArea) ?? header
    if (area.querySelector(SELECTORS.appliedUnrecognizedIcon)) unrecognized = true
    if (area.querySelector(SELECTORS.appliedDoneIcon)) done = true
  }
  return { unrecognized, done }
}

/**
 * 找订单标记区里的「添加标记」按钮（空 .order-mark-block：无 i、无内联背景色）。
 * ⚠️ 真机校准点：纯色标记块（如 已排版-Designed）也无 i 但有 background → 用「无 background」排除；
 * 兜底取末块 / 标记区本身。
 */
export function findMarkTrigger(root: ParentNode, orderId: string): HTMLElement | null {
  for (const header of findOrderHeaderRows(root, orderId)) {
    const area = header.querySelector(SELECTORS.orderMarkArea)
    if (!area) continue
    const blocks = Array.from(area.querySelectorAll(SELECTORS.orderMarkBlock)) as HTMLElement[]
    const addBlock = blocks.find(
      (b) => !b.querySelector('i') && !/background/i.test(b.getAttribute('style') ?? ''),
    )
    if (addBlock) return addBlock
    if (blocks.length) return blocks[blocks.length - 1]
    return area as HTMLElement
  }
  return null
}

/** 点订单标记区的添加按钮以打开弹窗（click + 兜底 mouseenter，应对 hover 触发）。返回是否找到触发元素。 */
export function clickMarkTrigger(root: ParentNode, orderId: string): boolean {
  const trigger = findMarkTrigger(root, orderId)
  if (!trigger) return false
  const win = (trigger.ownerDocument?.defaultView ?? globalThis) as Window & typeof globalThis
  trigger.dispatchEvent(new win.MouseEvent('mouseenter', { bubbles: true }))
  trigger.click()
  return true
}

// ── 弹窗（读选中态 + 切换 + 确定/取消）──

/** 元素及其祖先是否都非 display:none（可见性判据，真机用；jsdom 默认非 none）。 */
function isDisplayed(el: Element): boolean {
  let cur: Element | null = el
  while (cur) {
    const win = cur.ownerDocument?.defaultView
    if (win && win.getComputedStyle(cur).display === 'none') return false
    cur = cur.parentElement
  }
  return true
}

/**
 * 取当前弹窗。⚠️ 真机：店小秘页面常有**多个 `.markPopover`**——隐藏模板(display:none) + 当前锚定的可见弹窗；
 * 直接 querySelector 会取到隐藏那个（选中态恒空）→ 一致性守卫永远判不一致 → 功能失效。故取**可见**的那个。
 * 单实例（jsdom 夹具）直接返回，避免对无布局环境做可见性判定。
 */
export function getMarkPopover(root: ParentNode): Element | null {
  const pops = Array.from(root.querySelectorAll(SELECTORS.markPopover))
  if (pops.length <= 1) return pops[0] ?? null
  return pops.find((p) => isDisplayed(p)) ?? pops[pops.length - 1] ?? null
}

/** 标记行是否选中：操作区出现已知对勾图标（白名单 MARK_SELECTED_ICONS，实测 icon_support）。 */
export function isMarkItemSelected(item: Element): boolean {
  const action = item.querySelector(SELECTORS.markRemarkAction)
  if (!action) return false
  return MARK_SELECTED_ICONS.some((cls) => action.querySelector(`i.${cls}`) !== null)
}

/** 按 label 文字找弹窗里的标记行。 */
export function findMarkItem(popover: ParentNode, label: string): Element | null {
  for (const item of Array.from(popover.querySelectorAll(SELECTORS.markRemarkItem))) {
    if (clean(item.querySelector(SELECTORS.markRemarkText)?.textContent) === label) return item
  }
  return null
}

/** 读弹窗里两个目标标记的当前选中态（弹窗为空 → 全 false）。 */
export function readPopoverSelection(popover: ParentNode | null): MarkState {
  if (!popover) return { unrecognized: false, done: false }
  const u = findMarkItem(popover, MARK_LABELS.unrecognized)
  const d = findMarkItem(popover, MARK_LABELS.done)
  return {
    unrecognized: u ? isMarkItemSelected(u) : false,
    done: d ? isMarkItemSelected(d) : false,
  }
}

/** 点击弹窗里某目标标记行以切换选中（点 .remark-item__text，避开右侧 停用/编辑 图标）。返回是否点到。 */
export function clickMarkItem(popover: ParentNode | null, key: MarkLabelKey): boolean {
  if (!popover) return false
  const item = findMarkItem(popover, KEY_LABEL[key])
  if (!item) return false
  const target =
    (item.querySelector(SELECTORS.markRemarkText) as HTMLElement | null) ?? (item as HTMLElement)
  target.click()
  return true
}

/**
 * 弹窗「确定」按钮。`.markPopover__header button.ant-btn-primary` 会同时命中「创建标记」与「确定」，
 * 故：① 先排除「创建标记」(created-mark / 含「创建」)，绝不误点开新建标记流程；② 去全部空白后按「确定」匹配
 * （抗店小秘改成「确 定」之类）；③ **挑不到就返回 null**（宁可本单判失败重试，也不点错按钮——封号/数据污染风险）。
 */
export function markConfirmButton(popover: ParentNode | null): HTMLElement | null {
  if (!popover) return null
  const norm = (t: string | null | undefined) => clean(t).replace(/\s+/g, '')
  const btns = (Array.from(popover.querySelectorAll(SELECTORS.markConfirm)) as HTMLElement[]).filter(
    (b) => !b.classList.contains('created-mark') && !clean(b.textContent).includes('创建'),
  )
  return btns.find((b) => norm(b.textContent) === MARK_CONFIRM_TEXT) ?? null
}

/** 弹窗「取消」按钮。 */
export function markCancelButton(popover: ParentNode | null): HTMLElement | null {
  if (!popover) return null
  return (popover.querySelector(SELECTORS.markCancel) as HTMLElement | null) ?? null
}
