import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { JSDOM } from 'jsdom'
import { describe, expect, it } from 'vitest'

import {
  clickMarkItem,
  findMarkItem,
  findMarkTrigger,
  getMarkPopover,
  isMarkItemSelected,
  markCancelButton,
  markConfirmButton,
  readOrderRowMarks,
  readPopoverSelection,
  satisfies,
  targetFor,
  togglesFor,
} from './dianxiaomi_mark'

const here = dirname(fileURLToPath(import.meta.url))

function loadDoc(): Document {
  const html = readFileSync(resolve(here, '../fixtures', 'dianxiaomi-mark-popover.html'), 'utf-8')
  return new JSDOM(html).window.document
}

describe('纯逻辑：targetFor / satisfies / togglesFor（幂等核心）', () => {
  it('targetFor：done 顺带清未识别', () => {
    expect(targetFor('mark_unrecognized')).toEqual({ unrecognized: true })
    expect(targetFor('mark_done')).toEqual({ done: true, unrecognized: false })
  })

  it('satisfies 只看目标声明的键', () => {
    expect(satisfies({ unrecognized: true, done: false }, { unrecognized: true })).toBe(true)
    expect(satisfies({ unrecognized: true, done: true }, { unrecognized: true })).toBe(true) // done 不在目标
    expect(satisfies({ unrecognized: false, done: false }, { unrecognized: true })).toBe(false)
    expect(satisfies({ unrecognized: false, done: true }, { done: true, unrecognized: false })).toBe(true)
    expect(satisfies({ unrecognized: true, done: true }, { done: true, unrecognized: false })).toBe(false)
  })

  it('togglesFor 只返回需改变的键', () => {
    expect(togglesFor({ unrecognized: false, done: false }, { unrecognized: true })).toEqual(['unrecognized'])
    expect(togglesFor({ unrecognized: true, done: false }, { unrecognized: true })).toEqual([])
    expect(
      togglesFor({ unrecognized: true, done: false }, { done: true, unrecognized: false }).sort(),
    ).toEqual(['done', 'unrecognized'])
    expect(togglesFor({ unrecognized: false, done: true }, { done: true, unrecognized: false })).toEqual([])
  })
})

describe('订单行：读已打标记 + 找触发控件', () => {
  const doc = loadDoc()

  it('读已打标记靠图标 class（不靠颜色）', () => {
    expect(readOrderRowMarks(doc, '4090000001')).toEqual({ unrecognized: true, done: false })
    expect(readOrderRowMarks(doc, '4090000002')).toEqual({ unrecognized: false, done: false })
  })

  it('订单不在本页 → null', () => {
    expect(readOrderRowMarks(doc, '9999999999')).toBeNull()
  })

  it('findMarkTrigger 取空添加块，跳过已打标记块 / 纯色块', () => {
    const t1 = findMarkTrigger(doc, '4090000001')
    expect(t1).not.toBeNull()
    expect(t1?.querySelector('i')).toBeNull() // 不是 icon_brush_bill 那块
    expect(t1?.getAttribute('style') ?? '').not.toMatch(/background/)
    const t2 = findMarkTrigger(doc, '4090000002')
    expect(t2?.querySelector('i')).toBeNull()
    expect(t2?.getAttribute('style') ?? '').not.toMatch(/background/) // 不是 已排版 蓝块
  })
})

describe('弹窗：读选中态 + 控件', () => {
  const doc = loadDoc()
  const pop = getMarkPopover(doc)

  it('弹窗存在', () => {
    expect(pop).not.toBeNull()
  })

  it('选中判据：AI未识别 选中、AI已处理 未选', () => {
    expect(isMarkItemSelected(findMarkItem(pop!, 'AI未识别')!)).toBe(true)
    expect(isMarkItemSelected(findMarkItem(pop!, 'AI已处理')!)).toBe(false)
  })

  it('icon_completed 是标记自身图标、不算选中（假阳性防御）', () => {
    expect(isMarkItemSelected(findMarkItem(pop!, 'Confirmed-可以生产/发货')!)).toBe(false)
  })

  it('readPopoverSelection 汇总两目标态', () => {
    expect(readPopoverSelection(pop)).toEqual({ unrecognized: true, done: false })
  })

  it('确定按钮按文本精确挑（避开 创建标记 这个也是 primary 的按钮）', () => {
    expect(markConfirmButton(pop)?.textContent?.trim()).toBe('确定')
    expect(markCancelButton(pop)?.textContent?.trim()).toBe('取消')
  })

  it('clickMarkItem 点到目标行的 text 区', () => {
    let clicked = ''
    findMarkItem(pop!, 'AI已处理')!
      .querySelector('.remark-item__text')!
      .addEventListener('click', () => {
        clicked = 'done'
      })
    expect(clickMarkItem(pop, 'done')).toBe(true)
    expect(clicked).toBe('done')
  })
})

describe('审查修复回归', () => {
  it('#1 数字 rowid 但表头行缺失 → readOrderRowMarks 返回 null（不误判「未打标」）', () => {
    const doc = new JSDOM(
      `<table><tbody><tr rowid="5"><td class="orderCode"><span class="pointer">4090000005</span></td></tr></tbody></table>`,
    ).window.document
    expect(readOrderRowMarks(doc, '4090000005')).toBeNull()
  })

  it('#3 markConfirmButton 挑不到「确定」时返回 null（绝不回退到「创建标记」）', () => {
    const doc = new JSDOM(
      `<div class="markPopover"><div class="markPopover__header">
        <button class="ant-btn ant-btn-primary created-mark"><span>创建标记</span></button>
        <button class="ant-btn ant-btn-primary"><span>保存</span></button>
      </div></div>`,
    ).window.document
    expect(markConfirmButton(doc.querySelector('.markPopover'))).toBeNull()
  })

  it('#3 markConfirmButton 容忍「确 定」含空白', () => {
    const doc = new JSDOM(
      `<div class="markPopover"><div class="markPopover__header">
        <button class="ant-btn ant-btn-primary created-mark"><span>创建标记</span></button>
        <button class="ant-btn ant-btn-primary"><span>确 定</span></button>
      </div></div>`,
    ).window.document
    const btn = markConfirmButton(doc.querySelector('.markPopover'))
    expect(btn?.textContent?.replace(/\s+/g, '')).toBe('确定')
  })
})

describe('真机修复回归：getMarkPopover 取可见弹窗', () => {
  it('多个 .markPopover（隐藏模板 + 可见锚定）→ 返回可见那个', () => {
    const doc = new JSDOM(
      `<div class="ant-popover" style="display:none"><div class="markPopover">
         <div class="remark-item"><div class="remark-item__text">AI未识别</div><div class="remark-item__action"></div></div>
       </div></div>
       <div class="ant-popover"><div class="markPopover" id="visible">
         <div class="remark-item"><div class="remark-item__text">AI未识别</div>
           <div class="remark-item__action"><a><i class="icon_support"></i></a></div></div>
       </div></div>`,
    ).window.document
    const pop = getMarkPopover(doc)
    expect((pop as HTMLElement)?.id).toBe('visible')
    // 读取应取可见弹窗的选中态（AI未识别 选中），而非隐藏模板的空态
    expect(readPopoverSelection(pop)).toEqual({ unrecognized: true, done: false })
  })

  it('单实例（jsdom 夹具常态）直接返回，不做可见性判定', () => {
    const doc = new JSDOM(`<div class="markPopover"><span>x</span></div>`).window.document
    expect(getMarkPopover(doc)).not.toBeNull()
  })
})
