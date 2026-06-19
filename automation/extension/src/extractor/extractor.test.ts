import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { JSDOM } from 'jsdom'
import { describe, expect, it } from 'vitest'

import { collectOrders, extractOrder, type OrderHit } from './extractor'

const here = dirname(fileURLToPath(import.meta.url))

function loadFixture(name: string): Document {
  const html = readFileSync(resolve(here, '../fixtures', name), 'utf-8')
  return new JSDOM(html).window.document
}

function byId(hits: OrderHit[], orderId: string): OrderHit {
  const hit = hits.find((h) => h.order.order_id === orderId)
  if (!hit) throw new Error(`订单 ${orderId} 未被收集`)
  return hit
}

describe('collectOrders（店小秘 vxe 列表页真实结构）', () => {
  const hits = collectOrders(loadFixture('dianxiaomi-order-sample.html'))

  it('按 rowid 去重后收齐 4 个订单', () => {
    expect(hits.map((h) => h.order.order_id).sort()).toEqual([
      '4090000000',
      '4093542955',
      '4093587551',
      '4093606621',
    ])
  })

  it('订单号 + 定制信息（备注）从明细行抓出并规整成单行', () => {
    const order = byId(hits, '4093542955').order
    expect(order.remark).toBe(
      'Choose Your Birth Flower: Jun - Honeysuckle / Font Design: Font 3 / Personalization: Esther / GiftMessage: Happy birthday my dearest Esther!',
    )
    expect(order.shop).toContain('Thai-1')
    expect(order.spec).toBe('21482780401')
  })

  it('无 GiftMessage 的订单只规整已有定制项', () => {
    expect(byId(hits, '4093587551').order.remark).toBe(
      'Choose Your Birth Flower: Jul - Waterlily / Font Design: Font 4 / Personalization: Michelle',
    )
    expect(byId(hits, '4093606621').order.remark).toContain('Personalization: 14.07.2021')
  })

  it('「AI未识别」标记识别：3 个标记单为 true，其余 false', () => {
    expect(byId(hits, '4093542955').order.ai_unrecognized).toBe(true)
    expect(byId(hits, '4093587551').order.ai_unrecognized).toBe(true)
    expect(byId(hits, '4093606621').order.ai_unrecognized).toBe(true)
    expect(byId(hits, '4090000000').order.ai_unrecognized).toBe(false)
  })

  it('每个订单都给出注入按钮的锚点（订单号单元格）', () => {
    for (const hit of hits) {
      expect(hit.anchorEl.classList.contains('orderCode')).toBe(true)
    }
  })
})

describe('边界', () => {
  it('无订单页返回空数组', () => {
    expect(collectOrders(loadFixture('dianxiaomi-order-empty.html'))).toEqual([])
  })

  it('extractOrder 在无订单时返回空 RawOrder', () => {
    const order = extractOrder(new JSDOM('<div>nothing</div>').window.document)
    expect(order.order_id).toBe('')
    expect(order.remark).toBe('')
  })
})
