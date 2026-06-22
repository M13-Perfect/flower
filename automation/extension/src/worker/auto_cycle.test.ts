import { describe, expect, it, vi } from 'vitest'

import type { ManifestEntry, PendingItem, RawOrder, ScrapeControl, WorkItem } from '../shared/contract'
import { buildManifest, runAutoCycle, type CycleDeps } from './auto_cycle'

/** 构造一个没有付款时间的原始订单（不能用 order(id, undefined)——默认参数会填上默认值）。 */
function orderNoPaid(order_id: string): RawOrder {
  return { order_id, remark: 'x' }
}

// P0（2026-06-22）：runAutoCycle 现在以任务租约授权（authorized）为唯一执行判据，并按时间窗过滤订单。
// 默认用「已授权 + 极宽时间窗」的控制，订单默认带落在窗内的付款时间。
const WIDE_CONTROL: ScrapeControl = {
  authorized: true,
  enabled: true,
  interval_seconds: 120,
  scrape_from: '2000-01-01 00:00',
  scrape_to: null,
  task_id: 't1',
  allowed_actions: 'scrape,mark',
}

function order(order_id: string, paid_at: string | undefined = '2026-06-19 02:25'): RawOrder {
  return { order_id, remark: 'x', paid_at }
}

function deps(over: Partial<CycleDeps> = {}): CycleDeps {
  return {
    getControl: async (): Promise<ScrapeControl> => ({ ...WIDE_CONTROL }),
    postDiff: async () => [],
    pushOrders: async (orders) => orders.map((o) => ({ order_id: o.order_id, ok: true })),
    getPending: async () => [],
    postRecheck: async () => ({ ok: true }),
    ...over,
  }
}

function pending(order_id: string): PendingItem {
  return { order_id, refund_status: null, status: 'WRITTEN_TO_INBOX', source_url: null, received_at: null }
}

describe('buildManifest', () => {
  it('投影成 order_id + 付款时间，丢掉空 order_id', () => {
    const m = buildManifest([order('A', '2026-06-19 02:25'), orderNoPaid(''), orderNoPaid('B')])
    expect(m).toEqual([
      { order_id: 'A', paid_at: '2026-06-19 02:25' },
      { order_id: 'B', paid_at: undefined },
    ])
  })

  it('标准1：排除已打「AI已处理」的单（不抓不传）', () => {
    const done: RawOrder = { order_id: 'D', remark: 'x', ai_done: true }
    const m = buildManifest([order('A'), done, order('B')])
    expect(m.map((e) => e.order_id)).toEqual(['A', 'B']) // D 被排除
  })
})

describe('runAutoCycle · 授权门控（P0）', () => {
  it('未授权（authorized=false）→ 不 diff、不推送，回带间隔', async () => {
    const postDiff = vi.fn(async () => [] as WorkItem[])
    const pushOrders = vi.fn(async () => [])
    const getPending = vi.fn(async () => [])
    const result = await runAutoCycle([order('A')], deps({
      getControl: async () => ({ ...WIDE_CONTROL, authorized: false, enabled: false, interval_seconds: 300 }),
      postDiff,
      pushOrders,
      getPending,
    }))
    expect(result.enabled).toBe(false)
    expect(result.intervalSeconds).toBe(300)
    expect(postDiff).not.toHaveBeenCalled()
    expect(pushOrders).not.toHaveBeenCalled()
    expect(getPending).not.toHaveBeenCalled()
  })

  it('残留 enabled=true 但 authorized=false（旧失控态）→ 仍不动', async () => {
    const postDiff = vi.fn(async () => [] as WorkItem[])
    await runAutoCycle([order('A')], deps({
      getControl: async () => ({ ...WIDE_CONTROL, authorized: false, enabled: true }),
      postDiff,
    }))
    expect(postDiff).not.toHaveBeenCalled()
  })

  it('范围外订单（早于时间窗下界）→ 不进 manifest、不推送', async () => {
    const postDiff = vi.fn(async (m: ManifestEntry[]) =>
      m.map((e) => ({ order_id: e.order_id, reason: 'new', paid_at: e.paid_at ?? null } as WorkItem)),
    )
    const pushed: string[] = []
    const result = await runAutoCycle(
      [order('INWIN', '2026-06-20 00:00'), order('HIST', '2010-01-01 00:00')],
      deps({
        getControl: async () => ({ ...WIDE_CONTROL, scrape_from: '2026-06-19 00:00' }),
        postDiff,
        pushOrders: async (os) => {
          os.forEach((o) => pushed.push(o.order_id))
          return os.map((o) => ({ order_id: o.order_id, ok: true }))
        },
      }),
    )
    expect(result.manifestCount).toBe(1) // 只有 INWIN 进了清单
    expect(pushed).toEqual(['INWIN']) // HIST 历史单被时间窗拦掉
  })

  it('无付款时间的订单 → 视为范围外，不推送（fail-closed）', async () => {
    const pushOrders = vi.fn(async () => [])
    const result = await runAutoCycle([orderNoPaid('A')], deps({
      postDiff: async () => [{ order_id: 'A', reason: 'new', paid_at: null }],
      pushOrders,
    }))
    expect(pushOrders).not.toHaveBeenCalled()
    expect(result.manifestCount).toBe(0)
  })
})

describe('runAutoCycle', () => {
  it('授权 → 只推送 worklist 命中本页的单，统计 pushed/failed', async () => {
    const orders = [order('A', '2026-06-19 02:25'), order('B'), order('C')]
    const worklist: WorkItem[] = [
      { order_id: 'A', reason: 'new', paid_at: '2026-06-19 02:25' },
      { order_id: 'B', reason: 'incomplete', paid_at: null },
    ]
    const pushed: string[] = []
    const result = await runAutoCycle(orders, deps({
      postDiff: async () => worklist,
      pushOrders: async (os) => {
        os.forEach((o) => pushed.push(o.order_id))
        return os.map((o) => ({
          order_id: o.order_id,
          ok: o.order_id !== 'B',
          error: o.order_id === 'B' ? 'boom' : undefined,
        }))
      },
    }))
    expect(pushed).toEqual(['A', 'B']) // C 不在 worklist → 不推（批量只收到 A、B）
    expect(result.manifestCount).toBe(3)
    expect(result.worklistCount).toBe(2)
    expect(result.pushed).toBe(1)
    expect(result.failed).toBe(1)
    expect(result.skipped).toBe(0)
  })

  it('worklist 含本页看不到的单（如更早页退款刷新）→ 计入 skipped、不报错', async () => {
    const result = await runAutoCycle([order('A')], deps({
      postDiff: async () => [
        { order_id: 'A', reason: 'new', paid_at: null },
        { order_id: 'OFFPAGE', reason: 'refund_refresh', paid_at: null },
      ],
    }))
    expect(result.pushed).toBe(1)
    expect(result.skipped).toBe(1)
  })

  it('D-1：空 remark 但有行项目（标品单）→ 照常推送', async () => {
    const o: RawOrder = {
      order_id: 'A', remark: '', paid_at: '2026-06-19 02:25',
      items: [{ line_index: 0, product_sku: 'SKU' }],
    }
    const pushed: string[] = []
    const result = await runAutoCycle([o], deps({
      postDiff: async () => [{ order_id: 'A', reason: 'new', paid_at: null }],
      pushOrders: async (os) => {
        os.forEach((x) => pushed.push(x.order_id))
        return os.map((x) => ({ order_id: x.order_id, ok: true }))
      },
    }))
    expect(pushed).toEqual(['A'])
    expect(result.pushed).toBe(1)
    expect(result.skipped).toBe(0)
  })

  it('D-1 防御：既无备注又无行项目的真空单 → 跳过、不推', async () => {
    const o: RawOrder = { order_id: 'A', remark: '', paid_at: '2026-06-19 02:25' }
    const pushOrders = vi.fn(async () => [])
    const result = await runAutoCycle([o], deps({
      postDiff: async () => [{ order_id: 'A', reason: 'new', paid_at: null }],
      pushOrders,
    }))
    expect(pushOrders).not.toHaveBeenCalled()
    expect(result.pushed).toBe(0)
    expect(result.skipped).toBe(1)
  })
})

describe('runAutoCycle · 退款重抓闭环', () => {
  it('本页可见的在产单 → 把实时退款状态回 /recheck，统计 rechecked', async () => {
    const o: RawOrder = { order_id: 'A', remark: 'x', paid_at: '2026-06-19 02:25', refund_status: '已审核' }
    const calls: Array<[string, string | null]> = []
    const result = await runAutoCycle([o], deps({
      getPending: async () => [pending('A')],
      postRecheck: async (id, status) => {
        calls.push([id, status])
        return { ok: true, action: 'allow', blocked: false }
      },
    }))
    expect(calls).toEqual([['A', '已审核']]) // 回的是本页重抓到的实时状态，非库里旧值
    expect(result.rechecked).toBe(1)
    expect(result.recheckBlocked).toBe(0)
  })

  it('实时状态判定 block（已退款）→ 计入 recheckBlocked', async () => {
    const o: RawOrder = { order_id: 'A', remark: 'x', paid_at: '2026-06-19 02:25', refund_status: '已退款' }
    const result = await runAutoCycle([o], deps({
      getPending: async () => [pending('A')],
      postRecheck: async () => ({ ok: true, action: 'block', blocked: true }),
    }))
    expect(result.rechecked).toBe(1)
    expect(result.recheckBlocked).toBe(1)
  })

  it('pending 单不在本页 / 本页未抓到状态 → 不回 /recheck', async () => {
    const onPageNoStatus: RawOrder = { order_id: 'A', remark: 'x', paid_at: '2026-06-19 02:25' }
    const postRecheck = vi.fn(async () => ({ ok: true }))
    const result = await runAutoCycle([onPageNoStatus], deps({
      getPending: async () => [pending('A'), pending('OFFPAGE')],
      postRecheck,
    }))
    expect(postRecheck).not.toHaveBeenCalled()
    expect(result.rechecked).toBe(0)
  })

  it('未授权 → 不跑退款闭环（getPending 不调用）', async () => {
    const getPending = vi.fn(async () => [pending('A')])
    await runAutoCycle([order('A')], deps({
      getControl: async () => ({ ...WIDE_CONTROL, authorized: false, enabled: false }),
      getPending,
    }))
    expect(getPending).not.toHaveBeenCalled()
  })

  it('触发器端点不可用（getPending 抛错）→ 不影响抓取结果', async () => {
    const o: RawOrder = { order_id: 'A', remark: 'x', paid_at: '2026-06-19 02:25', refund_status: '已审核' }
    const result = await runAutoCycle([o], deps({
      postDiff: async () => [{ order_id: 'A', reason: 'new', paid_at: null }],
      getPending: async () => {
        throw new Error('404')
      },
    }))
    expect(result.pushed).toBe(1)
    expect(result.rechecked).toBe(0)
  })
})
