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

  it('单件订单仍抓出长度 1 的 items[]，product_sku 与 spec 一致，无 refund_status', () => {
    const order = byId(hits, '4093542955').order
    expect(order.items).toHaveLength(1)
    expect(order.items?.[0].line_index).toBe(0)
    expect(order.items?.[0].product_sku).toBe(order.spec)
    expect(order.items?.[0].personalization_raw).toBe(order.remark)
    expect(order.refund_status).toBeUndefined()
  })
})

describe('一单多件 + 退款状态（店小秘「全部订单」列表页真实结构）', () => {
  const hits = collectOrders(loadFixture('dianxiaomi-order-multi.html'))

  it('混单：4 个行项目按序抓出，跨固定列不重复', () => {
    const order = byId(hits, '4092270213').order
    expect(order.items).toHaveLength(4)
    expect(order.items?.map((it) => it.line_index)).toEqual([0, 1, 2, 3])
    expect(order.items?.map((it) => it.product_sku)).toEqual([
      '21842163406',
      '21842163420',
      '27901510805',
      '28275184592',
    ])
  })

  it('件数 ×N 解析：默认 1，显式数量按整数读', () => {
    const items = byId(hits, '4092270213').order.items
    expect(items?.[0].quantity).toBe(1)
    expect(items?.[1].quantity).toBe(2)
    // 第三件无 quantity span → 缺省（按 1，不写字段）
    expect(items?.[2].quantity).toBeUndefined()
  })

  it('每个行项目带本行原始定制备注 + extras（listing/price/缩略图）', () => {
    const items = byId(hits, '4092270213').order.items
    expect(items?.[0].personalization_raw).toBe(
      'Choose Your Birth Flower: Oct - Cosmos / Font Design: Font 3 / Personalization: Anna Veit',
    )
    expect(items?.[0].extras?.listing_url).toBe('https://www.etsy.com/listing/1763390413')
    expect(items?.[0].extras?.price).toBe('USD 79.50')
    expect(items?.[0].extras?.thumbnail).toBe('https://i.etsystatic.com/il_100x100.a.jpg')
  })

  it('退款状态从 .orderState 抓出原文', () => {
    expect(byId(hits, '4092270213').order.refund_status).toBe('待打单（有货）')
    expect(byId(hits, '4092128423').order.refund_status).toBe('已退款')
  })

  it('付款时间从时间轴「付款：」项抓出（自动抓取时间基准）', () => {
    expect(byId(hits, '4092270213').order.paid_at).toBe('2026-06-19 02:25')
    expect(byId(hits, '4092128423').order.paid_at).toBe('2026-06-19 03:10')
  })

  it('已退款订单仍抓出 2 个行项目（结构不受状态影响）', () => {
    const order = byId(hits, '4092128423').order
    expect(order.items).toHaveLength(2)
    expect(order.items?.map((it) => it.product_sku)).toEqual(['21842163266', '21482780391'])
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

describe('AI已处理 标记读取（标准1）', () => {
  it('表头行含 icon_change_order → ai_done=true；否则 false', () => {
    const doc = new JSDOM(
      `<table><tbody>
        <tr rowid="1"><td class="orderCode"><span class="pointer">4090627965</span></td></tr>
        <tr rowid="1_header"><td><div class="order-mark-block"><i class="icon_change_order"></i></div></td></tr>
        <tr rowid="2"><td class="orderCode"><span class="pointer">4093542955</span></td></tr>
        <tr rowid="2_header"><td><div class="order-mark-block"><i class="icon_brush_bill"></i></div></td></tr>
      </tbody></table>`,
    ).window.document
    const hits = collectOrders(doc)
    expect(byId(hits, '4090627965').order.ai_done).toBe(true)
    expect(byId(hits, '4093542955').order.ai_done).toBe(false)
    expect(byId(hits, '4093542955').order.ai_unrecognized).toBe(true)
  })
})
