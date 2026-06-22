import type { DatabaseResult, RawOrder } from '../shared/contract'
import type { MarkJobInput } from './mark_writeback'

// 手动「→Flower」单笔**条件打标**的纯编排（依赖注入，可单测；DOM/HTTP 胶水在 content 注入）。
// 决策表（用户确认 2026-06-22）：只有「非 ai_done、非 ai_unrecognized、上传成功、且数据库 CREATED_NEW
// （新建 **或软删复活**）」才给页面打「AI未识别」；其余一律不动标签。每个分支返回稳定 reasonCode 便于诊断。
//
// 背景：手动点击=人主动要求处理该单，故不受「自动抓取」开关 / 任务租约约束（与受授权门控的后台打标轮询独立）。
// 作用范围仅本单；不读 refund_status/shop/paid_at/remark/items/order_in_scope 作为条件。
//
// ⚠️ 「CREATED_NEW」必须来自后端权威（IngestResponse.created：库里原本无该活跃订单、本次新建或复活软删行），
//   不能仅凭 HTTP 200 / 前端提示推断（见 client.postOrder 的严格三态）。

export interface ManualUploadResult {
  /** 上传是否成功（HTTP 2xx 且写库/收件夹成功）。 */
  success: boolean
  /** 数据库侧结果（严格三态）；仅 success=true 时有意义。 */
  databaseResult?: DatabaseResult
  error?: string
}

export interface ManualMarkDeps {
  /** 上传本单到本地服务，回传是否成功 + 数据库侧结果（CREATED_NEW/ALREADY_EXISTS/UNKNOWN）。 */
  upload: (order: RawOrder) => Promise<ManualUploadResult>
  /**
   * 给页面打「AI未识别」并**回读校验**：unrecognized 存在 且 DONE 不存在 → true（校验通过）。
   * 幂等：已是目标态直接判通过、不重复写。仅在 CREATED_NEW 分支调用一次。
   */
  addAiUnrecognizedAndVerify: (orderId: string) => Promise<boolean>
}

export type ManualAction = 'SKIP' | 'NO_LABEL_CHANGE' | 'LABEL_ADDED' | 'LABEL_FAILED'

export interface ManualOutcome {
  action: ManualAction
  reasonCode: string
}

/**
 * 手动单笔订单的完整条件打标决策（对齐用户伪代码 handleManualFlowerOrder）。
 * 上传前：标签冲突 / 已 DONE → 不上传不动标签。上传后：仅 CREATED_NEW 且原本无 AI 标签 → 打「AI未识别」+校验。
 */
export async function handleManualFlowerOrder(
  order: RawOrder,
  deps: ManualMarkDeps,
): Promise<ManualOutcome> {
  const orderId = (order.order_id ?? '').trim()
  if (!orderId) return { action: 'SKIP', reasonCode: 'INVALID_ORDER_NO' }

  const aiDone = order.ai_done === true
  const aiUnrecognized = order.ai_unrecognized === true

  // 标签冲突（同时挂 DONE + AI未识别）：不上传、不增删标签、记日志（不由前端猜保留哪个）。
  if (aiDone && aiUnrecognized) return { action: 'SKIP', reasonCode: 'DUPLICATE_AI_LABEL_CONFLICT' }
  // 已 AI已处理（DONE）：不上传、不动标签（保留 content 既有跳过语义）。
  if (aiDone) return { action: 'SKIP', reasonCode: 'SKIP_ALREADY_AI_DONE' }

  const up = await deps.upload(order)
  if (!up.success) return { action: 'NO_LABEL_CHANGE', reasonCode: 'NO_LABEL_UPLOAD_FAILED' }

  // 已是 AI未识别：上传照常，但不重复打标（无论库里新建/已存在，页面标签都不动）。
  if (aiUnrecognized) return { action: 'NO_LABEL_CHANGE', reasonCode: 'NO_CHANGE_ALREADY_AI_UNRECOGNIZED' }

  if (up.databaseResult === 'CREATED_NEW') {
    const ok = await deps.addAiUnrecognizedAndVerify(orderId)
    return ok
      ? { action: 'LABEL_ADDED', reasonCode: 'ADD_AI_UNRECOGNIZED_FOR_NEW_ORDER' }
      : { action: 'LABEL_FAILED', reasonCode: 'LABEL_VERIFICATION_FAILED' }
  }
  if (up.databaseResult === 'ALREADY_EXISTS') {
    // 库里已存在但页面无 AI 标签：本需求未规定补什么标 → 不自行推断、不打标。
    return { action: 'NO_LABEL_CHANGE', reasonCode: 'NO_LABEL_EXISTING_DATABASE_ORDER' }
  }
  // UNKNOWN（或缺省）：数据库状态未知 → 绝不按新单处理、不打标。
  return { action: 'NO_LABEL_CHANGE', reasonCode: 'NO_LABEL_DATABASE_RESULT_UNKNOWN' }
}

/**
 * 手动 force 打标只处理本次上传对应的【这一单】：直接构造该单的「AI未识别」任务，
 * 不走服务端 /inbox/mark/pending 拉取（那条受任务授权门控；手动以「人主动操作」为授权，故客户端直建）。
 */
export function manualMarkQueue(orderId: string): MarkJobInput[] {
  return [{ order_id: orderId, action: 'mark_unrecognized' }]
}
