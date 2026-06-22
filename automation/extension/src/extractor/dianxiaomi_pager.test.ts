import { JSDOM } from 'jsdom'
import { describe, expect, it } from 'vitest'

import { clickNextPage, hasPager, isNextDisabled, isPrevDisabled } from './dianxiaomi_pager'

// 用用户提供的真实 vxe-pager（mini-d-pager）结构造文档。
function pagerDoc(opts: { nextDisabled?: boolean; prevDisabled?: boolean } = {}): Document {
  const next = opts.nextDisabled ? ' is--disabled' : ''
  const prev = opts.prevDisabled ? ' is--disabled' : ''
  const html = `<!doctype html><html><body>
    <div class="vxe-pager d-vxe-pager mini-d-pager">
      <div class="vxe-pager--wrapper">
        <span class="vxe-pager--left-wrapper"> 第101-165条， </span>
        <span class="vxe-pager--total">共 165 条记录</span>
        <button class="vxe-pager--prev-btn${prev}" type="button" title="上一页"><i class="vxe-icon-arrow-left"></i></button>
        <button class="vxe-pager--next-btn${next}" type="button" title="下一页"><i class="vxe-icon-arrow-right"></i></button>
      </div>
    </div>
  </body></html>`
  return new JSDOM(html).window.document
}

describe('dianxiaomi_pager', () => {
  it('识别翻页器存在', () => {
    expect(hasPager(pagerDoc())).toBe(true)
    expect(hasPager(new JSDOM('<body></body>').window.document)).toBe(false)
  })

  it('末页：下一页禁用 → isNextDisabled=true，clickNextPage 不点、返回 false', () => {
    const doc = pagerDoc({ nextDisabled: true })
    let clicked = false
    doc.querySelector<HTMLButtonElement>('.vxe-pager--next-btn')!.addEventListener('click', () => {
      clicked = true
    })
    expect(isNextDisabled(doc)).toBe(true)
    expect(clickNextPage(doc)).toBe(false)
    expect(clicked).toBe(false)
  })

  it('非末页：clickNextPage 点击并返回 true', () => {
    const doc = pagerDoc()
    let clicked = false
    doc.querySelector<HTMLButtonElement>('.vxe-pager--next-btn')!.addEventListener('click', () => {
      clicked = true
    })
    expect(isNextDisabled(doc)).toBe(false)
    expect(clickNextPage(doc)).toBe(true)
    expect(clicked).toBe(true)
  })

  it('首页：上一页禁用', () => {
    expect(isPrevDisabled(pagerDoc({ prevDisabled: true }))).toBe(true)
    expect(isPrevDisabled(pagerDoc())).toBe(false)
  })
})
