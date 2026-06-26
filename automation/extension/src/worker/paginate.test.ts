import { describe, expect, it, vi } from 'vitest'

import type { RawOrder } from '../shared/contract'
import { maxPaidAt, pageReachedCursor, type PagedSweepDeps, runPagedSweep } from './paginate'

const o = (id: string, paid?: string): RawOrder => ({ order_id: id, remark: 'x', paid_at: paid })

function harness(pages: RawOrder[][], opts: { cursor?: string | null; maxPages?: number } = {}) {
  let idx = 0
  let saved: string | null = opts.cursor ?? null
  const cycled: RawOrder[][] = []
  const gotoNextPage = vi.fn(async () => {
    if (idx < pages.length - 1) {
      idx++
      return true
    }
    return false
  })
  const gotoFirstPage = vi.fn(async () => {
    idx = 0
  })
  const deps: PagedSweepDeps = {
    gotoFirstPage,
    readPage: async () => pages[idx] ?? [],
    runCycle: async (orders) => {
      cycled.push(orders)
    },
    gotoNextPage,
    getCursor: async () => saved,
    setCursor: async (c) => {
      saved = c
    },
    maxPages: opts.maxPages,
  }
  return { deps, cycled, gotoNextPage, gotoFirstPage, savedCursor: () => saved }
}

describe('pageReachedCursor', () => {
  it('游标为 null（首次）→ 永不触及', () => {
    expect(pageReachedCursor([o('A', '2026-06-19 03:00')], null)).toBe(false)
  })
  it('本页含 paid_at <= 游标 的单 → 触及', () => {
    const orders = [o('A', '2026-06-19 03:00'), o('B', '2026-06-19 01:00')]
    expect(pageReachedCursor(orders, '2026-06-19 02:00')).toBe(true)
  })
  it('整页都比游标新 → 未触及', () => {
    const orders = [o('A', '2026-06-19 05:00'), o('B', '2026-06-19 04:00')]
    expect(pageReachedCursor(orders, '2026-06-19 02:00')).toBe(false)
  })
  it('无 paid_at 的单不参与判定', () => {
    expect(pageReachedCursor([o('A'), o('B')], '2026-06-19 02:00')).toBe(false)
  })
})

describe('maxPaidAt', () => {
  it('取最新；忽略无 paid_at；都无则回退', () => {
    expect(maxPaidAt([o('A', '2026-06-19 01:00'), o('B', '2026-06-19 03:00'), o('C')], null)).toBe(
      '2026-06-19 03:00',
    )
    expect(maxPaidAt([o('A')], '2026-06-19 00:00')).toBe('2026-06-19 00:00')
  })
})

describe('runPagedSweep', () => {
  it('稳态：第 1 页即触及游标 → 只读一页、不翻页、游标推进到最新', async () => {
    const h = harness([[o('A', '2026-06-19 03:00'), o('B', '2026-06-19 01:00')]], {
      cursor: '2026-06-19 02:00',
    })
    const r = await runPagedSweep(h.deps)
    expect(r.pages).toBe(1)
    expect(r.reachedCursor).toBe(true)
    expect(h.gotoNextPage).not.toHaveBeenCalled()
    expect(h.gotoFirstPage).toHaveBeenCalledTimes(1)
    expect(h.savedCursor()).toBe('2026-06-19 03:00')
  })

  it('洪峰：往后翻到接上游标为止', async () => {
    const h = harness(
      [
        [o('A', '2026-06-19 05:00')],
        [o('B', '2026-06-19 04:00')],
        [o('C', '2026-06-19 04:00'), o('D', '2026-06-18 23:00')],
        [o('E', '2026-06-18 20:00')],
      ],
      { cursor: '2026-06-19 00:00' },
    )
    const r = await runPagedSweep(h.deps)
    expect(r.pages).toBe(3) // p3 含 D(06-18 23:00 <= 游标) → 停，不读 p4
    expect(r.reachedCursor).toBe(true)
    expect(h.gotoNextPage).toHaveBeenCalledTimes(2)
    expect(h.savedCursor()).toBe('2026-06-19 05:00')
    expect(h.cycled.map((p) => p.map((x) => x.order_id))).toEqual([['A'], ['B'], ['C', 'D']])
  })

  it('首轮（游标 null）：翻到末页为止，游标设到最新', async () => {
    const h = harness([
      [o('A', '2026-06-19 05:00')],
      [o('B', '2026-06-19 04:00')],
      [o('C', '2026-06-19 03:00')],
    ])
    const r = await runPagedSweep(h.deps)
    expect(r.pages).toBe(3)
    expect(r.reachedCursor).toBe(false) // 靠末页停，不是靠游标
    expect(h.savedCursor()).toBe('2026-06-19 05:00')
  })

  it('翻页上限：永远到不了游标也不死循环', async () => {
    const h = harness(
      [
        [o('A', '2026-06-19 05:00')],
        [o('B', '2026-06-19 04:00')],
        [o('C', '2026-06-19 03:00')],
      ],
      { cursor: '2020-01-01 00:00', maxPages: 2 },
    )
    const r = await runPagedSweep(h.deps)
    expect(r.pages).toBe(2)
    expect(r.reachedCursor).toBe(false)
    expect(h.gotoNextPage).toHaveBeenCalledTimes(2)
  })
})
