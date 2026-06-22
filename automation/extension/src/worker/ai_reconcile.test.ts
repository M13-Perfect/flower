import { describe, expect, it } from 'vitest'

import type { ReconcileDecision } from '../shared/contract'
import type { MarkState } from '../extractor/dianxiaomi_mark'
import {
  type ReconcileDeps,
  type ReconcileOrderInput,
  runReconcile,
  targetForDesired,
} from './ai_reconcile'

// 可控 fake 驱动纯编排。rowMarks[id]=订单行态序列（第 1 次=对账前/幂等判断，第 2 次=确定后校验）。
// decisions[id]=该单 reconcile 返回值；缺省（undefined）= 返回 null（模拟查库失败）。
interface World {
  orders: ReconcileOrderInput[]
  decisions: Record<string, ReconcileDecision | null | undefined>
  rowMarks: Record<string, (MarkState | null)[] | undefined>
  popoverSelection: MarkState
  canOperate?: boolean
  ordersThrows?: boolean
  openOk?: boolean
  writeLimit?: number
  queryLimit?: number
  // 记录
  reconciled: string[]
  opened: string[]
  toggled: string[]
  confirmed: number
  cancelled: number
}

function world(partial: Partial<World>): World {
  return {
    orders: [],
    decisions: {},
    rowMarks: {},
    popoverSelection: { unrecognized: false, done: false },
    reconciled: [],
    opened: [],
    toggled: [],
    confirmed: 0,
    cancelled: 0,
    ...partial,
  }
}

function dec(
  desired: ReconcileDecision['desired_tag'],
  extra: Partial<ReconcileDecision> = {},
): ReconcileDecision {
  return { desired_tag: desired, ai_status: null, conflict: false, created: false, ...extra }
}

function depsFor(w: World): ReconcileDeps {
  const reads: Record<string, number> = {}
  return {
    canOperate: () => w.canOperate ?? true,
    getOrders: () => {
      if (w.ordersThrows) throw new Error('boom')
      return w.orders
    },
    reconcile: async (orderId) => {
      w.reconciled.push(orderId)
      const d = w.decisions[orderId]
      return d === undefined ? null : d
    },
    readOrderMarks: (id) => {
      const seq = w.rowMarks[id]
      if (seq === undefined) return null
      const n = reads[id] ?? 0
      reads[id] = n + 1
      return seq[Math.min(n, seq.length - 1)]
    },
    openPopover: async (id) => {
      w.opened.push(id)
      return w.openOk ?? true
    },
    readPopoverSelection: () => w.popoverSelection,
    toggleMark: async (key) => {
      w.toggled.push(key)
    },
    confirm: async () => {
      w.confirmed++
    },
    cancel: async () => {
      w.cancelled++
    },
    writeLimit: w.writeLimit ?? 3,
    queryLimit: w.queryLimit ?? 25,
  }
}

const O = (id: string, ai_done = false, ai_unrecognized = false): ReconcileOrderInput => ({
  order_id: id,
  ai_done,
  ai_unrecognized,
})

describe('targetForDesired（不变式：两标记互斥）', () => {
  it('recognized → 目标已处理且清未识别', () => {
    expect(targetForDesired('recognized')).toEqual({ done: true, unrecognized: false })
  })
  it('pending → 目标唯一未识别且清已处理', () => {
    expect(targetForDesired('pending')).toEqual({ unrecognized: true, done: false })
  })
  it('none → null（不动标签）', () => {
    expect(targetForDesired('none')).toBeNull()
  })
})

describe('runReconcile 编排', () => {
  it('当前页不可操作 → 整轮跳过、不查库', async () => {
    const w = world({ canOperate: false, orders: [O('A')] })
    const r = await runReconcile(depsFor(w))
    expect(r.skipped).toBe(true)
    expect(w.reconciled).toHaveLength(0)
  })

  it('getOrders 抛错 → 本轮不崩、不查库', async () => {
    const w = world({ ordersThrows: true })
    const r = await runReconcile(depsFor(w))
    expect(r.queried).toBe(0)
    expect(w.reconciled).toHaveLength(0)
  })

  it('查库失败（reconcile 返回 null）→ 跳过、绝不动标签', async () => {
    const w = world({ orders: [O('A')], decisions: {} }) // A 不在 decisions → null
    const r = await runReconcile(depsFor(w))
    expect(w.reconciled).toEqual(['A']) // 查了
    expect(r.queried).toBe(0) // 但没有效判定
    expect(w.opened).toHaveLength(0)
    expect(w.toggled).toHaveLength(0)
    expect(w.confirmed).toBe(0)
  })

  it('desired=none（复核冻结/未授权）→ 不开弹窗、不动标签', async () => {
    const w = world({
      orders: [O('A', true)],
      decisions: { A: dec('none', { conflict: true, ai_status: 'conflict' }) },
      rowMarks: { A: [{ unrecognized: false, done: true }] },
    })
    const r = await runReconcile(depsFor(w))
    expect(r.frozen).toBe(1)
    expect(r.conflict).toBe(1)
    expect(w.opened).toHaveLength(0)
    expect(w.toggled).toHaveLength(0)
  })

  it('desired=pending 且页面无标签 → 打唯一「未识别」', async () => {
    const w = world({
      orders: [O('A')],
      decisions: { A: dec('pending', { ai_status: 'pending', created: true }) },
      rowMarks: { A: [{ unrecognized: false, done: false }, { unrecognized: true, done: false }] },
      popoverSelection: { unrecognized: false, done: false },
    })
    const r = await runReconcile(depsFor(w))
    expect(w.toggled).toEqual(['unrecognized'])
    expect(w.confirmed).toBe(1)
    expect(r.applied).toBe(1)
    expect(r.created).toBe(1)
  })

  it('幂等：desired=pending 且页面已是未识别 → 不开弹窗、不写', async () => {
    const w = world({
      orders: [O('A', false, true)],
      decisions: { A: dec('pending') },
      rowMarks: { A: [{ unrecognized: true, done: false }] },
    })
    const r = await runReconcile(depsFor(w))
    expect(w.opened).toHaveLength(0)
    expect(w.confirmed).toBe(0)
    expect(r.applied).toBe(0)
  })

  it('desired=recognized 且页面是未识别 → 勾已处理+清未识别（不变式：不并存）', async () => {
    const w = world({
      orders: [O('A', false, true)],
      decisions: { A: dec('recognized', { ai_status: 'recognized' }) },
      rowMarks: { A: [{ unrecognized: true, done: false }, { unrecognized: false, done: true }] },
      popoverSelection: { unrecognized: true, done: false },
    })
    const r = await runReconcile(depsFor(w))
    expect(w.toggled.sort()).toEqual(['done', 'unrecognized'])
    expect(w.confirmed).toBe(1)
    expect(r.applied).toBe(1)
  })

  it('幂等：desired=recognized 且页面已是已处理 → 不写', async () => {
    const w = world({
      orders: [O('A', true)],
      decisions: { A: dec('recognized') },
      rowMarks: { A: [{ unrecognized: false, done: true }] },
    })
    const r = await runReconcile(depsFor(w))
    expect(w.opened).toHaveLength(0)
    expect(r.applied).toBe(0)
  })

  it('防降级：desired=pending 但页面此刻已是已处理 → deferred，不清已处理', async () => {
    const w = world({
      orders: [O('A')],
      decisions: { A: dec('pending') }, // 服务基于查询时无 done 回 pending
      rowMarks: { A: [{ unrecognized: false, done: true }] }, // 但页面此刻已 done（状态在查询后变化）
    })
    const r = await runReconcile(depsFor(w))
    expect(r.deferred).toBe(1)
    expect(w.opened).toHaveLength(0) // 不开弹窗
    expect(w.toggled).toHaveLength(0) // 绝不把 done 清成未识别
  })

  it('弹窗未锚定本单（选中态≠订单行现状）→ 取消 + deferred，不写', async () => {
    const w = world({
      orders: [O('A')],
      decisions: { A: dec('pending') },
      rowMarks: { A: [{ unrecognized: false, done: false }] },
      popoverSelection: { unrecognized: true, done: false }, // 残留上一单
    })
    const r = await runReconcile(depsFor(w))
    expect(r.deferred).toBe(1)
    expect(w.toggled).toHaveLength(0)
    expect(w.cancelled).toBe(1)
  })

  it('确定后回读不到订单行(null) → deferred，不当失败', async () => {
    const w = world({
      orders: [O('A')],
      decisions: { A: dec('pending') },
      rowMarks: { A: [{ unrecognized: false, done: false }, null] },
      popoverSelection: { unrecognized: false, done: false },
    })
    const r = await runReconcile(depsFor(w))
    expect(w.confirmed).toBe(1)
    expect(r.deferred).toBe(1)
    expect(r.failed).toBe(0)
  })

  it('写后校验未通过 → 取消清场 + failed', async () => {
    const w = world({
      orders: [O('A')],
      decisions: { A: dec('pending') },
      rowMarks: { A: [{ unrecognized: false, done: false }, { unrecognized: false, done: false }] },
      popoverSelection: { unrecognized: false, done: false },
    })
    const r = await runReconcile(depsFor(w))
    expect(r.failed).toBe(1)
    expect(w.cancelled).toBe(1)
  })

  it('弹窗打不开 → 取消清场 + failed', async () => {
    const w = world({
      orders: [O('A')],
      decisions: { A: dec('pending') },
      rowMarks: { A: [{ unrecognized: false, done: false }] },
      openOk: false,
    })
    const r = await runReconcile(depsFor(w))
    expect(r.failed).toBe(1)
    expect(w.cancelled).toBe(1)
  })

  it('writeLimit：两单都需写、limit=1 → 只落 1 次（剩余留下轮）', async () => {
    const w = world({
      orders: [O('A'), O('B')],
      decisions: { A: dec('pending'), B: dec('pending') },
      rowMarks: {
        A: [{ unrecognized: false, done: false }, { unrecognized: true, done: false }],
        B: [{ unrecognized: false, done: false }, { unrecognized: true, done: false }],
      },
      popoverSelection: { unrecognized: false, done: false },
      writeLimit: 1,
    })
    const r = await runReconcile(depsFor(w))
    expect(r.applied).toBe(1)
    expect(w.opened).toHaveLength(1) // 第 2 单未开弹窗
  })

  it('queryLimit：三单、limit=2 → 只对账查 2 单', async () => {
    const w = world({
      orders: [O('A'), O('B'), O('C')],
      decisions: { A: dec('pending'), B: dec('pending'), C: dec('pending') },
      rowMarks: {
        A: [{ unrecognized: true, done: false }],
        B: [{ unrecognized: true, done: false }],
        C: [{ unrecognized: true, done: false }],
      },
      queryLimit: 2,
    })
    await runReconcile(depsFor(w))
    expect(w.reconciled).toEqual(['A', 'B']) // C 未查
  })
})
