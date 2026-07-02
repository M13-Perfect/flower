import { JSDOM } from 'jsdom'
import { describe, expect, it, vi } from 'vitest'

import { canSearch, fillSearchAndSubmit, findOrderInResults } from './dianxiaomi_search'

// 店小秘「搜索订单」页交互（定向重抓 option B）。搜索表单按真实样例：输入框 #orderSearchInput、
// 主按钮 type=submit 文本「搜索」；结果表仍是 vxe-table（复用 collectOrders）。

function searchDom(): Document {
  return new JSDOM(`<html><body>
    <input id="orderSearchInput" name="tableSearchInput" type="text">
    <button class="ant-btn ant-btn-primary" type="submit"><span>搜索</span></button>
  </body></html>`).window.document
}

describe('canSearch', () => {
  it('有订单号搜索框 → true', () => {
    expect(canSearch(searchDom())).toBe(true)
  })
  it('非搜索页（无搜索框）→ false', () => {
    expect(canSearch(new JSDOM('<body><div>列表页</div></body>').window.document)).toBe(false)
  })
  it('id 改版时用 name 兜底', () => {
    const doc = new JSDOM('<body><input name="tableSearchInput" type="text"></body>').window.document
    expect(canSearch(doc)).toBe(true)
  })

  it('列表页无搜索框但有订单行 → 也算可处理（直接读可见单）', () => {
    const doc = new JSDOM(
      '<body><table><tr rowid="1"><td class="orderCode"><span class="pointer">4090728276</span></td>' +
        '<td class="orderState"><div>已退款</div></td></tr></table></body>',
    ).window.document
    expect(canSearch(doc)).toBe(true)
  })
})

describe('fillSearchAndSubmit', () => {
  it('填入订单号（去空白）并点「搜索」按钮', () => {
    const doc = searchDom()
    const clicked = vi.fn()
    doc.querySelector('button')!.addEventListener('click', clicked)
    const input = doc.querySelector('#orderSearchInput') as HTMLInputElement
    const inputEvents = vi.fn()
    input.addEventListener('input', inputEvents)

    const ok = fillSearchAndSubmit(doc, '  4095532249  ')

    expect(ok).toBe(true)
    expect(input.value).toBe('4095532249') // 受控输入：原生 setter 已写入
    expect(inputEvents).toHaveBeenCalled() // 派发了 input 事件（框架 v-model 才收得到）
    expect(clicked).toHaveBeenCalled()
  })

  it('非搜索页 → 返回 false、不抛', () => {
    expect(fillSearchAndSubmit(new JSDOM('<body></body>').window.document, 'X')).toBe(false)
  })

  it('找不到搜索按钮 → 回车兜底提交（仍返回 true）', () => {
    const doc = new JSDOM('<body><input id="orderSearchInput" type="text"></body>').window.document
    const input = doc.querySelector('#orderSearchInput') as HTMLInputElement
    const keydown = vi.fn()
    input.addEventListener('keydown', keydown)
    expect(fillSearchAndSubmit(doc, 'A1')).toBe(true)
    expect(keydown).toHaveBeenCalled()
  })
})

describe('findOrderInResults（vxe 结果表，复用 collectOrders）', () => {
  function resultsDom(orderId: string, state: string): Document {
    return new JSDOM(`<html><body><table>
      <tr rowid="1">
        <td class="orderCode"><span class="pointer">${orderId}</span></td>
        <td class="orderState"><div>${state}</div></td>
      </tr>
    </table></body></html>`).window.document
  }

  it('命中订单号 → 返回该单（含实时退款状态）', () => {
    const order = findOrderInResults(resultsDom('4095532249', '已退款'), '4095532249')
    expect(order?.order_id).toBe('4095532249')
    expect(order?.refund_status).toBe('已退款')
  })

  it('订单号不匹配 → null', () => {
    expect(findOrderInResults(resultsDom('4095532249', '已审核'), '999999')).toBeNull()
  })
})
