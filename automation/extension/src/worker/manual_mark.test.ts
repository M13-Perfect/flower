import { describe, expect, it, vi } from 'vitest'

import { handleManualFlowerOrder, type ManualMarkDeps, manualMarkQueue } from './manual_mark'
import type { DatabaseResult, RawOrder } from '../shared/contract'

// 手动条件打标决策表（用户确认 2026-06-22）的全量护栏。upload / addAiUnrecognizedAndVerify 用 spy 注入，
// 既断言返回 reasonCode，也断言「该不该上传 / 该不该打标」真的发生（防分支顺序回归）。

function order(extra: Partial<RawOrder> = {}): RawOrder {
  return { order_id: 'A1', remark: 'name Amy', ...extra }
}

function deps(
  upload: { success: boolean; databaseResult?: DatabaseResult; error?: string },
  verifyOk = true,
): ManualMarkDeps & {
  uploadSpy: ReturnType<typeof vi.fn>
  markSpy: ReturnType<typeof vi.fn>
} {
  const uploadSpy = vi.fn(async () => upload)
  const markSpy = vi.fn(async () => verifyOk)
  return { upload: uploadSpy, addAiUnrecognizedAndVerify: markSpy, uploadSpy, markSpy }
}

describe('handleManualFlowerOrder（手动单笔条件打标决策表）', () => {
  it('用例1：无标签 + 上传成功 + 新订单 → 打「AI未识别」', async () => {
    const d = deps({ success: true, databaseResult: 'CREATED_NEW' })
    const r = await handleManualFlowerOrder(order(), d)
    expect(r).toEqual({ action: 'LABEL_ADDED', reasonCode: 'ADD_AI_UNRECOGNIZED_FOR_NEW_ORDER' })
    expect(d.uploadSpy).toHaveBeenCalledTimes(1)
    expect(d.markSpy).toHaveBeenCalledTimes(1)
  })

  it('用例2：无标签 + 上传成功 + 数据库已存在 → 不打标', async () => {
    const d = deps({ success: true, databaseResult: 'ALREADY_EXISTS' })
    const r = await handleManualFlowerOrder(order(), d)
    expect(r).toEqual({ action: 'NO_LABEL_CHANGE', reasonCode: 'NO_LABEL_EXISTING_DATABASE_ORDER' })
    expect(d.markSpy).not.toHaveBeenCalled()
  })

  it('用例3：无标签 + 上传失败 → 不打标', async () => {
    const d = deps({ success: false, error: '服务返回 500' })
    const r = await handleManualFlowerOrder(order(), d)
    expect(r).toEqual({ action: 'NO_LABEL_CHANGE', reasonCode: 'NO_LABEL_UPLOAD_FAILED' })
    expect(d.markSpy).not.toHaveBeenCalled()
  })

  it('用例4/9：无标签 + 上传成功但数据库状态未知 → 不打标（数据库查询失败不得当新单）', async () => {
    const d = deps({ success: true, databaseResult: 'UNKNOWN' })
    const r = await handleManualFlowerOrder(order(), d)
    expect(r).toEqual({ action: 'NO_LABEL_CHANGE', reasonCode: 'NO_LABEL_DATABASE_RESULT_UNKNOWN' })
    expect(d.markSpy).not.toHaveBeenCalled()
  })

  it('用例4b：上传成功但 databaseResult 缺省 → 同样按未知、不打标', async () => {
    const d = deps({ success: true })
    const r = await handleManualFlowerOrder(order(), d)
    expect(r.reasonCode).toBe('NO_LABEL_DATABASE_RESULT_UNKNOWN')
    expect(d.markSpy).not.toHaveBeenCalled()
  })

  it('用例5：已有 AI未识别 + 上传成功 → 不重复打标', async () => {
    const d = deps({ success: true, databaseResult: 'CREATED_NEW' })
    const r = await handleManualFlowerOrder(order({ ai_unrecognized: true }), d)
    expect(r).toEqual({ action: 'NO_LABEL_CHANGE', reasonCode: 'NO_CHANGE_ALREADY_AI_UNRECOGNIZED' })
    expect(d.markSpy).not.toHaveBeenCalled()
  })

  it('用例6：已有 AI未识别 + 上传失败 → 保留原标签（记上传失败）', async () => {
    const d = deps({ success: false, error: 'boom' })
    const r = await handleManualFlowerOrder(order({ ai_unrecognized: true }), d)
    expect(r).toEqual({ action: 'NO_LABEL_CHANGE', reasonCode: 'NO_LABEL_UPLOAD_FAILED' })
    expect(d.markSpy).not.toHaveBeenCalled()
  })

  it('用例7：已 AI已处理 → 跳过，不上传、不改标签', async () => {
    const d = deps({ success: true, databaseResult: 'CREATED_NEW' })
    const r = await handleManualFlowerOrder(order({ ai_done: true }), d)
    expect(r).toEqual({ action: 'SKIP', reasonCode: 'SKIP_ALREADY_AI_DONE' })
    expect(d.uploadSpy).not.toHaveBeenCalled()
    expect(d.markSpy).not.toHaveBeenCalled()
  })

  it('用例8：两种 AI 标签同时存在 → 冲突，不上传、不动标签', async () => {
    const d = deps({ success: true, databaseResult: 'CREATED_NEW' })
    const r = await handleManualFlowerOrder(order({ ai_done: true, ai_unrecognized: true }), d)
    expect(r).toEqual({ action: 'SKIP', reasonCode: 'DUPLICATE_AI_LABEL_CONFLICT' })
    expect(d.uploadSpy).not.toHaveBeenCalled()
    expect(d.markSpy).not.toHaveBeenCalled()
  })

  it('打标后校验未通过 → LABEL_FAILED', async () => {
    const d = deps({ success: true, databaseResult: 'CREATED_NEW' }, /* verifyOk */ false)
    const r = await handleManualFlowerOrder(order(), d)
    expect(r).toEqual({ action: 'LABEL_FAILED', reasonCode: 'LABEL_VERIFICATION_FAILED' })
    expect(d.markSpy).toHaveBeenCalledTimes(1)
  })

  it('无订单号 → SKIP，不上传', async () => {
    const d = deps({ success: true, databaseResult: 'CREATED_NEW' })
    const r = await handleManualFlowerOrder(order({ order_id: '' }), d)
    expect(r).toEqual({ action: 'SKIP', reasonCode: 'INVALID_ORDER_NO' })
    expect(d.uploadSpy).not.toHaveBeenCalled()
  })

  it('用例10：同一单连点两次 → 第一次新建打标、第二次已存在不重复打标', async () => {
    // 第一次：CREATED_NEW → 打标
    const first = deps({ success: true, databaseResult: 'CREATED_NEW' })
    expect((await handleManualFlowerOrder(order(), first)).reasonCode).toBe(
      'ADD_AI_UNRECOGNIZED_FOR_NEW_ORDER',
    )
    expect(first.markSpy).toHaveBeenCalledTimes(1)
    // 第二次：库里已有该单 → ALREADY_EXISTS → 不重复打标（content 侧另有每单 in-flight 锁防真并发连点）。
    const second = deps({ success: true, databaseResult: 'ALREADY_EXISTS' })
    expect((await handleManualFlowerOrder(order(), second)).reasonCode).toBe(
      'NO_LABEL_EXISTING_DATABASE_ORDER',
    )
    expect(second.markSpy).not.toHaveBeenCalled()
  })
})

describe('manualMarkQueue（手动只处理本单）', () => {
  it('直接构造本单的 mark_unrecognized 任务', () => {
    expect(manualMarkQueue('A1')).toEqual([{ order_id: 'A1', action: 'mark_unrecognized' }])
  })
})
