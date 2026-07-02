import type { MarkAction } from '../shared/contract'
import {
  type MarkLabelKey,
  type MarkState,
  satisfies,
  targetFor,
  togglesFor,
} from '../extractor/dianxiaomi_mark'

// 标记回写一轮的纯编排（仿 rescrape.ts，依赖注入可单测；DOM 点击 + chrome 消息胶水在 content 注入）。
// 流程：(当前页有订单行才跑) 拉队列 → 逐单：
//   ① 读订单行现状；不在本页 → 跳过留 pending（不耗 attempts）。
//   ② 幂等：已满足目标态 → 直接回 ok，不开弹窗（已有标记不重打）。
//   ③ 否则开弹窗 → 按现选中态算需切换的标记 → 逐个点 → 确定 → 回读订单行校验 → 回填 ok/失败。
// 写操作有店小秘封号风险：调用方限频 + 串行 + 失败计 attempts（超上限服务端置 failed 掉出）。

export interface MarkJobInput {
  order_id: string
  action: MarkAction
}

export interface MarkWritebackDeps {
  /** 当前页是否可操作（在店小秘订单列表页、有订单行）。false → 本轮整体跳过。 */
  canOperate: () => boolean
  /** 拉待打标任务队列。 */
  getQueue: () => Promise<MarkJobInput[]>
  /** 读订单行已打的目标标记；订单不在本页 → null。 */
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
  /** 回填结果（ok=成功打标 / 失败=记 attempts）。 */
  postResult: (orderId: string, action: MarkAction, ok: boolean, detail?: string) => Promise<void>
}

export interface MarkRunResult {
  skipped: boolean // 当前页不可操作 → 整轮跳过
  processed: number // 本页可处理（在本页）的任务数
  applied: number // 成功打标（或已满足，幂等）
  failed: number // 打标失败（回填后服务端累计 attempts）
  notOnPage: number // 不在本页、本轮跳过（留 pending）
  deferred: number // 开了弹窗但无法安全下结论（弹窗未锚定本单 / 确定后回读不到行）→ 留 pending 下轮复核，不耗 attempts
}

export async function runMarkJobs(deps: MarkWritebackDeps): Promise<MarkRunResult> {
  const result: MarkRunResult = {
    skipped: false,
    processed: 0,
    applied: 0,
    failed: 0,
    notOnPage: 0,
    deferred: 0,
  }
  if (!deps.canOperate()) {
    result.skipped = true
    return result // 不在订单列表页：留队列，等下一轮/操作员切到列表页
  }
  let queue: MarkJobInput[]
  try {
    queue = await deps.getQueue()
  } catch {
    return result // 服务/SW 不可用 → 本轮不动队列
  }

  for (const job of queue) {
    const target = targetFor(job.action)
    const current = deps.readOrderMarks(job.order_id)
    if (!current) {
      result.notOnPage++ // 不在本页 → 不回 result（不耗 attempts），下轮或翻页再处理
      continue
    }
    result.processed++

    if (satisfies(current, target)) {
      // 幂等：订单行已是目标态（标记已打/已清）→ 直接回 ok，不开弹窗、不重复写。
      await deps.postResult(job.order_id, job.action, true)
      result.applied++
      continue
    }

    try {
      const opened = await deps.openPopover(job.order_id)
      if (!opened) throw new Error('标记弹窗未打开')
      const selection = deps.readPopoverSelection()
      // 防串单：弹窗是全页单例复用，可能残留上一单的选中态。弹窗选中态须与刚读的订单行现状一致，
      // 否则视为弹窗未锚定到本单 → 取消、留 pending、不写、不耗 attempts（下轮重试）。
      if (selection.unrecognized !== current.unrecognized || selection.done !== current.done) {
        await deps.cancel()
        result.deferred++
        continue
      }
      for (const key of togglesFor(selection, target)) {
        await deps.toggleMark(key)
      }
      await deps.confirm()
      const after = deps.readOrderMarks(job.order_id)
      if (after === null) {
        // 确定后回读不到订单行（vxe 重渲染瞬间）→ 不下结论，留 pending；下轮幂等复核（已打成功则直接 ok，不重写）。
        await deps.cancel()
        result.deferred++
        continue
      }
      if (satisfies(after, target)) {
        await deps.postResult(job.order_id, job.action, true)
        result.applied++
      } else {
        await deps.cancel() // 关掉可能残留的弹窗，免得污染下一单
        await deps.postResult(job.order_id, job.action, false, '打标后校验未通过')
        result.failed++
      }
    } catch (error) {
      try {
        await deps.cancel()
      } catch {
        /* 关弹窗失败忽略，避免卡住后续任务 */
      }
      await deps.postResult(job.order_id, job.action, false, String((error as Error)?.message ?? error))
      result.failed++
    }
  }
  return result
}
