import { type OrderPayload, type RawOrder, SCHEMA_VERSION } from '../shared/contract'

const SERVICE_BASE = 'http://127.0.0.1:8770'

export interface SendResult {
  ok: boolean
  status?: string
  dedup?: boolean
  error?: string
}

export async function postOrder(raw: RawOrder, sourceUrl?: string): Promise<SendResult> {
  const extras: Record<string, unknown> = {}
  if (raw.ai_unrecognized) extras.ai_unrecognized = true

  const payload: OrderPayload = {
    schema_version: SCHEMA_VERSION,
    order_id: raw.order_id,
    remark: raw.remark,
    shop: raw.shop,
    spec: raw.spec,
    source_url: sourceUrl,
    scraped_at: new Date().toISOString(),
    extras: Object.keys(extras).length ? extras : undefined,
  }
  // JSON.stringify 自动丢弃值为 undefined 的可选字段。
  try {
    const resp = await fetch(`${SERVICE_BASE}/inbox/orders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (resp.ok) {
      const data = await resp.json()
      return { ok: true, status: data.status, dedup: Boolean(data.dedup) }
    }
    if (resp.status === 422) {
      const data = await resp.json().catch(() => ({}))
      const detail = typeof data.detail === 'string' ? data.detail : '字段校验未通过'
      return { ok: false, error: detail }
    }
    return { ok: false, error: `服务返回 ${resp.status}` }
  } catch {
    return { ok: false, error: '无法连接本地服务（是否已在 8770 启动？）' }
  }
}

export async function checkHealth(): Promise<boolean> {
  try {
    const resp = await fetch(`${SERVICE_BASE}/healthz`)
    return resp.ok
  } catch {
    return false
  }
}
