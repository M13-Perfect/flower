import { describe, expect, it, vi } from 'vitest'

import type { RawOrder } from '../shared/contract'
import { runRescrapeJobs, type RescrapeDeps } from './rescrape'

function order(order_id: string, refund_status?: string): RawOrder {
  return { order_id, remark: 'x', refund_status }
}

function deps(over: Partial<RescrapeDeps> = {}): RescrapeDeps {
  return {
    canSearch: () => true,
    getQueue: async () => [],
    searchAndExtract: async () => null,
    pushOrder: async () => ({ ok: true }),
    postResult: async () => {},
    ...over,
  }
}

describe('runRescrapeJobs（定向重抓编排）', () => {
  it('不在搜索页 → 整轮跳过，不拉队列、不回填', async () => {
    const getQueue = vi.fn(async () => ['A1'])
    const postResult = vi.fn(async () => {})
    const r = await runRescrapeJobs(deps({ canSearch: () => false, getQueue, postResult }))
    expect(r.skipped).toBe(true)
    expect(getQueue).not.toHaveBeenCalled()
    expect(postResult).not.toHaveBeenCalled()
  })

  it('搜到单且有状态 → 推送刷新 + 回填 done(带状态)', async () => {
    const pushed: string[] = []
    const results: Array<[string, boolean, string | undefined]> = []
    const r = await runRescrapeJobs(
      deps({
        getQueue: async () => ['A1'],
        searchAndExtract: async (id) => order(id, '已退款'),
        pushOrder: async (o) => {
          pushed.push(o.order_id)
          return { ok: true }
        },
        postResult: async (id, found, status) => {
          results.push([id, found, status])
        },
      }),
    )
    expect(pushed).toEqual(['A1'])
    expect(results).toEqual([['A1', true, '已退款']])
    expect(r.found).toBe(1)
    expect(r.notFound).toBe(0)
  })

  it('店小秘搜不到该单 → 回填 not_found、不推送', async () => {
    const pushOrder = vi.fn(async () => ({ ok: true }))
    const results: Array<[string, boolean]> = []
    const r = await runRescrapeJobs(
      deps({
        getQueue: async () => ['GHOST'],
        searchAndExtract: async () => null,
        pushOrder,
        postResult: async (id, found) => {
          results.push([id, found])
        },
      }),
    )
    expect(pushOrder).not.toHaveBeenCalled()
    expect(results).toEqual([['GHOST', false]])
    expect(r.notFound).toBe(1)
  })

  it('搜到单但没抓到状态原文 → 从严当 not_found（让 Ezcad 阻断而非误放行）', async () => {
    const results: Array<[string, boolean]> = []
    const r = await runRescrapeJobs(
      deps({
        getQueue: async () => ['A1'],
        searchAndExtract: async (id) => order(id, undefined),
        postResult: async (id, found) => {
          results.push([id, found])
        },
      }),
    )
    expect(results).toEqual([['A1', false]])
    expect(r.found).toBe(0)
  })

  it('队列多单逐个处理；searchAndExtract 抛错的单计 not_found，不影响其它', async () => {
    const r = await runRescrapeJobs(
      deps({
        getQueue: async () => ['A1', 'BOOM', 'A2'],
        searchAndExtract: async (id) => {
          if (id === 'BOOM') throw new Error('dom error')
          return order(id, '已审核')
        },
      }),
    )
    expect(r.processed).toBe(3)
    expect(r.found).toBe(2)
    expect(r.notFound).toBe(1)
  })

  it('getQueue 抛错 → 不崩、当轮不处理', async () => {
    const r = await runRescrapeJobs(
      deps({
        getQueue: async () => {
          throw new Error('sw down')
        },
      }),
    )
    expect(r.processed).toBe(0)
    expect(r.skipped).toBe(false)
  })
})
