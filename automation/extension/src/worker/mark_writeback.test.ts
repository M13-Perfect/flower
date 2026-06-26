import { describe, expect, it } from 'vitest'

import type { MarkState } from '../extractor/dianxiaomi_mark'
import { type MarkJobInput, type MarkWritebackDeps, runMarkJobs } from './mark_writeback'

// 用可控 fake 驱动纯编排。rowMarks[id] = 依次返回的订单行态序列（第 1 次=打标前/幂等判断，第 2 次=确定后校验）。
interface World {
  queue: MarkJobInput[]
  rowMarks: Record<string, (MarkState | null)[] | undefined>
  popoverSelection: MarkState
  canOperate?: boolean
  openOk?: boolean
  queueThrows?: boolean
  // 记录
  opened: string[]
  toggled: string[]
  confirmed: number
  cancelled: number
  results: { orderId: string; action: string; ok: boolean; detail?: string }[]
}

function world(partial: Partial<World>): World {
  return {
    queue: [],
    rowMarks: {},
    popoverSelection: { unrecognized: false, done: false },
    opened: [],
    toggled: [],
    confirmed: 0,
    cancelled: 0,
    results: [],
    ...partial,
  }
}

function depsFor(w: World): MarkWritebackDeps {
  const reads: Record<string, number> = {}
  return {
    canOperate: () => w.canOperate ?? true,
    getQueue: async () => {
      if (w.queueThrows) throw new Error('boom')
      return w.queue
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
    postResult: async (orderId, action, ok, detail) => {
      w.results.push({ orderId, action, ok, detail })
    },
  }
}

describe('runMarkJobs 编排', () => {
  it('当前页不可操作 → 整轮跳过、不拉队列', async () => {
    const w = world({ canOperate: false })
    const r = await runMarkJobs(depsFor(w))
    expect(r.skipped).toBe(true)
    expect(w.results).toHaveLength(0)
  })

  it('拉队列抛错 → 本轮不动队列，不崩', async () => {
    const w = world({ queueThrows: true })
    const r = await runMarkJobs(depsFor(w))
    expect(r.processed).toBe(0)
    expect(w.results).toHaveLength(0)
  })

  it('订单不在本页 → notOnPage，不开弹窗、不回 result（不耗 attempts）', async () => {
    const w = world({ queue: [{ order_id: 'X', action: 'mark_unrecognized' }] })
    const r = await runMarkJobs(depsFor(w))
    expect(r.notOnPage).toBe(1)
    expect(r.processed).toBe(0)
    expect(w.opened).toHaveLength(0)
    expect(w.results).toHaveLength(0)
  })

  it('幂等：订单行已是目标态 → 直接回 ok，不开弹窗', async () => {
    const w = world({
      queue: [{ order_id: 'A', action: 'mark_unrecognized' }],
      rowMarks: { A: [{ unrecognized: true, done: false }] },
    })
    const r = await runMarkJobs(depsFor(w))
    expect(r.applied).toBe(1)
    expect(w.opened).toHaveLength(0)
    expect(w.confirmed).toBe(0)
    expect(w.results).toEqual([{ orderId: 'A', action: 'mark_unrecognized', ok: true, detail: undefined }])
  })

  it('mark_unrecognized 需打：toggle 未识别 → 确定 → 校验通过 → ok', async () => {
    const w = world({
      queue: [{ order_id: 'A', action: 'mark_unrecognized' }],
      rowMarks: { A: [{ unrecognized: false, done: false }, { unrecognized: true, done: false }] },
      popoverSelection: { unrecognized: false, done: false },
    })
    const r = await runMarkJobs(depsFor(w))
    expect(w.toggled).toEqual(['unrecognized'])
    expect(w.confirmed).toBe(1)
    expect(r.applied).toBe(1)
    expect(w.results[0].ok).toBe(true)
  })

  it('mark_done：勾已处理 + 取消未识别 → 确定 → 校验通过', async () => {
    const w = world({
      queue: [{ order_id: 'A', action: 'mark_done' }],
      rowMarks: { A: [{ unrecognized: true, done: false }, { unrecognized: false, done: true }] },
      popoverSelection: { unrecognized: true, done: false },
    })
    const r = await runMarkJobs(depsFor(w))
    expect(w.toggled.sort()).toEqual(['done', 'unrecognized'])
    expect(w.confirmed).toBe(1)
    expect(r.applied).toBe(1)
    expect(w.results[0]).toMatchObject({ orderId: 'A', action: 'mark_done', ok: true })
  })

  it('打标后校验未通过 → 回失败', async () => {
    const w = world({
      queue: [{ order_id: 'A', action: 'mark_unrecognized' }],
      rowMarks: { A: [{ unrecognized: false, done: false }, { unrecognized: false, done: false }] },
    })
    const r = await runMarkJobs(depsFor(w))
    expect(r.failed).toBe(1)
    expect(w.results[0]).toMatchObject({ ok: false })
  })

  it('弹窗打不开 → 取消清场 + 回失败', async () => {
    const w = world({
      queue: [{ order_id: 'A', action: 'mark_done' }],
      rowMarks: { A: [{ unrecognized: false, done: false }] },
      openOk: false,
    })
    const r = await runMarkJobs(depsFor(w))
    expect(w.cancelled).toBe(1)
    expect(r.failed).toBe(1)
    expect(w.results[0].ok).toBe(false)
  })

  it('多任务混合：幂等单 + 需打单各自处理', async () => {
    const w = world({
      queue: [
        { order_id: 'A', action: 'mark_unrecognized' }, // 已满足
        { order_id: 'B', action: 'mark_done' }, // 需打
      ],
      rowMarks: {
        A: [{ unrecognized: true, done: false }],
        B: [{ unrecognized: false, done: false }, { unrecognized: false, done: true }],
      },
      popoverSelection: { unrecognized: false, done: false },
    })
    const r = await runMarkJobs(depsFor(w))
    expect(r.applied).toBe(2)
    expect(w.opened).toEqual(['B']) // A 幂等跳过、只为 B 开弹窗
    expect(w.toggled).toEqual(['done']) // B 只需勾已处理（未识别本就没选）
  })
})

describe('runMarkJobs 审查修复回归', () => {
  it('弹窗未锚定本单（选中态≠订单行现状）→ 取消 + deferred，不写不回 result', async () => {
    const w = world({
      queue: [{ order_id: 'A', action: 'mark_unrecognized' }],
      rowMarks: { A: [{ unrecognized: false, done: false }] },
      popoverSelection: { unrecognized: true, done: false }, // 残留上一单的选中态
    })
    const r = await runMarkJobs(depsFor(w))
    expect(r.deferred).toBe(1)
    expect(w.toggled).toHaveLength(0) // 没按错基线乱切
    expect(w.cancelled).toBe(1)
    expect(w.results).toHaveLength(0) // 留 pending，不耗 attempts
  })

  it('确定后回读不到订单行(null) → deferred，不回 result（下轮幂等复核）', async () => {
    const w = world({
      queue: [{ order_id: 'A', action: 'mark_unrecognized' }],
      rowMarks: { A: [{ unrecognized: false, done: false }, null] },
      popoverSelection: { unrecognized: false, done: false },
    })
    const r = await runMarkJobs(depsFor(w))
    expect(w.confirmed).toBe(1) // 确实点了确定（可能已写成功）
    expect(r.deferred).toBe(1)
    expect(r.failed).toBe(0) // 不把「读不到」当失败
    expect(w.results).toHaveLength(0)
  })
})
