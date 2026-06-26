import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ensureMarkUnrecognized, grabOrderIfNeeded } from './client'
import type { RawOrder } from '../shared/contract'

// 用可路由的 fetch fake 驱动 SW 侧 HTTP（POST /inbox/orders 等）。
// 重点验收：上传成功 → 据响应 created 透传严格三态 databaseResult（CREATED_NEW/ALREADY_EXISTS/UNKNOWN）；
// 缺 created → UNKNOWN（绝不误判新建）；上传失败 → uploaded:false、无 databaseResult。打标决策见 manual_mark.test.ts。

interface Route {
  status: number
  body?: unknown
}

function jsonResponse(route: Route): Response {
  return {
    ok: route.status >= 200 && route.status < 300,
    status: route.status,
    json: async () => route.body ?? {},
  } as unknown as Response
}

function makeOrder(extra: Partial<RawOrder> = {}): RawOrder {
  return { order_id: 'A1', remark: 'name Amy', ...extra }
}

let fetchMock: ReturnType<typeof vi.fn>

function routeFetch(handlers: {
  diff?: Route
  order?: Route
  ensure?: Route
}): void {
  fetchMock.mockImplementation((url: string) => {
    if (url.includes('/inbox/scrape/diff')) return Promise.resolve(jsonResponse(handlers.diff ?? { status: 200, body: { worklist: [] } }))
    if (url.includes('/inbox/mark/request')) return Promise.resolve(jsonResponse(handlers.ensure ?? { status: 200, body: { status: 'pending' } }))
    if (url.includes('/inbox/orders')) return Promise.resolve(jsonResponse(handlers.order ?? { status: 200, body: { status: 'written', dedup: false, created: true } }))
    throw new Error('unexpected url ' + url)
  })
}

function ensureCalls(): unknown[][] {
  return fetchMock.mock.calls.filter((c) => String(c[0]).includes('/inbox/mark/request'))
}

beforeEach(() => {
  fetchMock = vi.fn()
  globalThis.fetch = fetchMock as unknown as typeof fetch
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('grabOrderIfNeeded（手动「→Flower」单单上传 + 透传数据库三态）', () => {
  it('AI已处理 → 不传、不发任何 HTTP', async () => {
    routeFetch({})
    const r = await grabOrderIfNeeded(makeOrder({ ai_done: true }))
    expect(r).toMatchObject({ uploaded: false })
    expect(r.databaseResult).toBeUndefined()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('上传成功 + created:true → uploaded:true、databaseResult:CREATED_NEW，只打 /inbox/orders', async () => {
    routeFetch({ order: { status: 200, body: { status: 'written', dedup: false, created: true } } })
    const r = await grabOrderIfNeeded(makeOrder())
    expect(r).toMatchObject({ uploaded: true, databaseResult: 'CREATED_NEW' })
    expect(ensureCalls()).toHaveLength(0) // 不调 /inbox/mark/request（纯页面打标，服务端不留痕）
    const calls = fetchMock.mock.calls.map((c) => String(c[0]))
    // 手动路径必须带 ?manual=1 → 服务端不入队 mark_job（不留打标痕迹）。
    expect(calls.some((u) => u.includes('/inbox/orders?manual=1'))).toBe(true)
    expect(calls.some((u) => u.includes('/inbox/scrape/diff'))).toBe(false)
  })

  it('上传成功 + created:false → databaseResult:ALREADY_EXISTS', async () => {
    routeFetch({ order: { status: 200, body: { status: 'written', dedup: true, created: false } } })
    const r = await grabOrderIfNeeded(makeOrder())
    expect(r).toMatchObject({ uploaded: true, databaseResult: 'ALREADY_EXISTS' })
  })

  it('上传成功但响应缺 created → databaseResult:UNKNOWN（绝不误判新建）', async () => {
    routeFetch({ order: { status: 200, body: { status: 'written', dedup: false } } })
    const r = await grabOrderIfNeeded(makeOrder())
    expect(r).toMatchObject({ uploaded: true, databaseResult: 'UNKNOWN' })
  })

  it('上传失败 → uploaded:false、带错误、无 databaseResult', async () => {
    routeFetch({ order: { status: 500 } })
    const r = await grabOrderIfNeeded(makeOrder())
    expect(r.uploaded).toBe(false)
    expect(r.error).toBeTruthy()
    expect(r.databaseResult).toBeUndefined()
    expect(ensureCalls()).toHaveLength(0)
  })
})

describe('ensureMarkUnrecognized（确保 pending 打标任务）', () => {
  it('服务回 pending → pending=true', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: 200, body: { status: 'pending' } }))
    expect(await ensureMarkUnrecognized('A1')).toMatchObject({ ensured: true, pending: true })
  })

  it('订单不存在(404) → pending=false（身份校验，不误标）', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: 404 }))
    expect(await ensureMarkUnrecognized('A1')).toMatchObject({ ensured: false, pending: false })
  })

  it('已 AI已处理(skipped_done) → pending=false', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: 200, body: { status: 'skipped_done' } }))
    expect(await ensureMarkUnrecognized('A1')).toMatchObject({ ensured: true, pending: false })
  })

  it('服务不可达（抛错）→ pending=false（不误标）', async () => {
    fetchMock.mockRejectedValue(new Error('boom'))
    expect(await ensureMarkUnrecognized('A1')).toMatchObject({ ensured: false, pending: false })
  })
})
