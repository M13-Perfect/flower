// AI 识别状态对账（纯编排，DI 可单测，仿 mark_writeback.ts）。
//
// 流程：内容脚本在店小秘订单列表页，对每个可见单上报「页面是否带 AI未识别/AI已处理 标记」给服务对账，
// 服务以 DB ai_status 为唯一权威返回 desired_tag；本模块据 desired_tag 把店小秘标记同步到位（模拟网页操作）。
//
// 关键约束（忠实需求）：
// - 查库失败（reconcile 返回 null）→ **跳过该单、不动任何标签**。
// - desired=none（复核冻结 / 未授权）→ 不动标签。
// - desired=recognized → 目标「AI已处理」且清「AI未识别」（绝不出现两者并存）。
// - desired=pending → 目标唯一「AI未识别」（清掉可能的「AI已处理」）；但若页面此刻已是「AI已处理」
//   则**不自动降级**（留给下一轮对账，服务会判其为 conflict 冻结）。
// - 写操作有封号风险 → 每轮最多落 writeLimit 次标记写；幂等：已满足目标态的单直接跳过、不开弹窗。
import type { DesiredTag, ReconcileDecision } from '../shared/contract'
import { type MarkLabelKey, type MarkState, satisfies, togglesFor } from '../extractor/dianxiaomi_mark'

/** 本页一个待对账订单（含页面标记现状）。 */
export interface ReconcileOrderInput {
  order_id: string
  ai_done: boolean
  ai_unrecognized: boolean
}

export interface ReconcileDeps {
  /** 当前页是否可操作（在店小秘订单列表页、有订单行）。false → 整轮跳过。 */
  canOperate: () => boolean
  /** 本页可见订单（含页面标记现状）。 */
  getOrders: () => ReconcileOrderInput[]
  /** 调服务对账：返回判定；查库失败 → null（本单跳过、不动标签）。 */
  reconcile: (
    orderId: string,
    aiDone: boolean,
    aiUnrecognized: boolean,
  ) => Promise<ReconcileDecision | null>
  /** 读订单行已打的标记；订单不在本页 → null。 */
  readOrderMarks: (orderId: string) => MarkState | null
  /** 为该订单打开标记弹窗；返回是否成功打开。 */
  openPopover: (orderId: string) => Promise<boolean>
  /** 读当前打开弹窗里两个目标标记的选中态。 */
  readPopoverSelection: () => MarkState
  /** 在弹窗里点击切换某目标标记。 */
  toggleMark: (key: MarkLabelKey) => Promise<void>
  /** 点「确定」提交。 */
  confirm: () => Promise<void>
  /** 点「取消」/关弹窗（不提交），用于异常清场。 */
  cancel: () => Promise<void>
  /** 每轮最多落几次标记写（封号防护）；剩余留下轮。 */
  writeLimit: number
  /** 每轮最多对账查询几单（防把整页都打到服务/SW）；剩余留下轮。 */
  queryLimit: number
}

export interface ReconcileRunResult {
  skipped: boolean // 当前页不可操作 → 整轮跳过
  queried: number // 本轮实际对账查询的单数
  applied: number // 成功同步标记（写并校验通过）
  failed: number // 写后校验未过 / 异常
  conflict: number // 服务判为复核冲突的单数
  created: number // 服务原子创建（桩单）的单数
  deferred: number // 开了弹窗但无法安全下结论（弹窗未锚定本单 / 回读不到行 / 防降级）→ 留下轮
  frozen: number // desired=none（复核冻结/未授权）→ 不动标签
}

/** desired_tag → 目标标记态（Partial）。none → null（不动标签）。
 * 不变式：两个目标都显式给出 → 必然互斥（recognized 清未识别 / pending 清已处理）。 */
export function targetForDesired(desired: DesiredTag): Partial<MarkState> | null {
  if (desired === 'recognized') return { done: true, unrecognized: false }
  if (desired === 'pending') return { unrecognized: true, done: false }
  return null
}

export async function runReconcile(deps: ReconcileDeps): Promise<ReconcileRunResult> {
  const result: ReconcileRunResult = {
    skipped: false,
    queried: 0,
    applied: 0,
    failed: 0,
    conflict: 0,
    created: 0,
    deferred: 0,
    frozen: 0,
  }
  if (!deps.canOperate()) {
    result.skipped = true
    return result
  }
  let orders: ReconcileOrderInput[]
  try {
    orders = deps.getOrders()
  } catch {
    return result // DOM 读取偶发失败 → 本轮跳过
  }

  let writes = 0
  let queries = 0
  for (const order of orders) {
    if (!order.order_id) continue
    if (queries >= deps.queryLimit) break // 本轮查询配额用尽，余下留下轮
    queries++

    const decision = await deps.reconcile(order.order_id, order.ai_done, order.ai_unrecognized)
    if (!decision) continue // 查库失败 → 不动标签（需求硬约束）
    result.queried++
    if (decision.conflict) result.conflict++
    if (decision.created) result.created++

    const target = targetForDesired(decision.desired_tag)
    if (!target) {
      result.frozen++ // desired=none：复核冻结 / 未授权 → 不动标签
      continue
    }

    const current = deps.readOrderMarks(order.order_id)
    if (!current) continue // 不在本页（罕见，刚读过）→ 留下轮

    // 防降级：服务基于「查询时页面无 AI已处理」才回 pending；若此刻页面已是 AI已处理（状态在查询后变化），
    // 不要把它清成未识别（那是降级）。留下轮——下轮对账会带 ai_done=true 上报，服务判其为 conflict 冻结。
    if (decision.desired_tag === 'pending' && current.done) {
      result.deferred++
      continue
    }

    if (satisfies(current, target)) continue // 已满足目标态 → 不开弹窗、不写（幂等）

    if (writes >= deps.writeLimit) break // 写配额用尽，余下留下轮（封号防护）
    writes++

    try {
      const opened = await deps.openPopover(order.order_id)
      if (!opened) throw new Error('标记弹窗未打开')
      const selection = deps.readPopoverSelection()
      // 防串单：弹窗是全页单例，可能残留上一单的选中态。须与刚读的订单行现状一致，否则视为未锚定本单 →
      // 取消、留下轮、不写（与 mark_writeback 同策略）。
      if (selection.unrecognized !== current.unrecognized || selection.done !== current.done) {
        await deps.cancel()
        result.deferred++
        continue
      }
      for (const key of togglesFor(selection, target)) {
        await deps.toggleMark(key)
      }
      await deps.confirm()
      const after = deps.readOrderMarks(order.order_id)
      if (after === null) {
        // 确定后回读不到订单行（vxe 重渲染瞬间）→ 不下结论，留下轮（下轮幂等复核）。
        await deps.cancel()
        result.deferred++
        continue
      }
      if (satisfies(after, target)) {
        result.applied++
      } else {
        await deps.cancel()
        result.failed++
      }
    } catch {
      try {
        await deps.cancel()
      } catch {
        /* 关弹窗失败忽略，避免卡住后续订单 */
      }
      result.failed++
    }
  }
  return result
}
