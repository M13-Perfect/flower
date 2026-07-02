import { describe, expect, it } from 'vitest'

import type { RawOrder, ScrapeControl } from '../shared/contract'
import {
  actionAllowed,
  isAuthorized,
  orderInScope,
  pageBelowWindowFloor,
  toComparable,
} from './authorization'

function control(over: Partial<ScrapeControl> = {}): ScrapeControl {
  return {
    authorized: true,
    enabled: true,
    interval_seconds: 120,
    scrape_from: '2026-06-19 00:00',
    scrape_to: null,
    task_id: 't1',
    allowed_actions: 'scrape,mark',
    ...over,
  }
}

function order(paid_at?: string): RawOrder {
  return { order_id: 'A', remark: 'x', paid_at }
}

describe('isAuthorized', () => {
  it('authorized=true → true', () => {
    expect(isAuthorized(control())).toBe(true)
  })
  it('authorized=false（残留 enabled=true 旧态）→ false', () => {
    expect(isAuthorized(control({ authorized: false, enabled: true }))).toBe(false)
  })
  it('control 为空/undefined → false（fail-closed）', () => {
    expect(isAuthorized(null)).toBe(false)
    expect(isAuthorized(undefined)).toBe(false)
  })
  it('旧服务无 authorized 字段（undefined）→ false', () => {
    expect(isAuthorized({ enabled: true, interval_seconds: 60, scrape_from: null })).toBe(false)
  })
})

describe('actionAllowed', () => {
  it('在 allowed_actions 里且已授权 → true', () => {
    expect(actionAllowed(control({ allowed_actions: 'scrape' }), 'scrape')).toBe(true)
  })
  it('不在 allowed_actions → false', () => {
    expect(actionAllowed(control({ allowed_actions: 'scrape' }), 'mark')).toBe(false)
  })
  it('未授权 → 任何操作都 false', () => {
    expect(actionAllowed(control({ authorized: false }), 'scrape')).toBe(false)
  })
})

describe('toComparable', () => {
  it('店小秘空格格式与服务端 ISO 格式可跨格式比较（避免空格<T 字典序陷阱）', () => {
    const paid = toComparable('2026-06-19 02:25') // 02:25，晚于下界
    const fromIso = toComparable('2026-06-19T00:00:00')
    expect(paid).not.toBeNull()
    expect(fromIso).not.toBeNull()
    expect((paid as number) > (fromIso as number)).toBe(true) // 字典序里 '2026-06-19 ' < '2026-06-19T'，数字比则正确
  })
  it('无法解析 / 空 → null', () => {
    expect(toComparable(undefined)).toBeNull()
    expect(toComparable('')).toBeNull()
    expect(toComparable('not-a-date')).toBeNull()
  })
})

describe('orderInScope', () => {
  it('付款时间在窗内 → true', () => {
    expect(orderInScope(order('2026-06-20 10:00'), control({ scrape_from: '2026-06-19 00:00' }))).toBe(true)
  })
  it('早于下界（历史单）→ false', () => {
    expect(orderInScope(order('2026-06-18 10:00'), control({ scrape_from: '2026-06-19 00:00' }))).toBe(false)
  })
  it('晚于上界 → false', () => {
    expect(
      orderInScope(order('2026-06-22 10:00'), control({ scrape_from: '2026-06-19 00:00', scrape_to: '2026-06-21 00:00' })),
    ).toBe(false)
  })
  it('无付款时间 → false（fail-closed，防历史/未付款单混入）', () => {
    expect(orderInScope(order(undefined), control())).toBe(false)
  })
  it('未授权 → false', () => {
    expect(orderInScope(order('2026-06-20 10:00'), control({ authorized: false }))).toBe(false)
  })
})

describe('pageBelowWindowFloor', () => {
  const c = control({ scrape_from: '2026-06-19 00:00' })
  it('整页都早于下界 → true（应停止翻页）', () => {
    expect(pageBelowWindowFloor([order('2026-06-18 10:00'), order('2026-06-17 09:00')], c)).toBe(true)
  })
  it('本页含窗内单 → false（继续）', () => {
    expect(pageBelowWindowFloor([order('2026-06-20 10:00'), order('2026-06-18 09:00')], c)).toBe(false)
  })
  it('无下界 → false', () => {
    expect(pageBelowWindowFloor([order('2026-06-18 10:00')], control({ scrape_from: null }))).toBe(false)
  })
  it('本页无可判定付款时间 → false（交给游标/末页/上限）', () => {
    expect(pageBelowWindowFloor([order(undefined)], c)).toBe(false)
  })
})
