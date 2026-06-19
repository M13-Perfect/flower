// 与 automation/contracts/order.schema.json 对齐的类型（手写镜像；后续可由 schema 生成替换）。

export const SCHEMA_VERSION = '1.0'

/** 发往本地服务的订单报文（snake_case，与服务端 Pydantic OrderPayload 一致）。 */
export interface OrderPayload {
  schema_version: string
  order_id: string
  remark: string
  shop?: string
  spec?: string
  source_url?: string
  scraped_at?: string
  extras?: Record<string, unknown>
}

/** 提取器从页面抓到的原始字段（未补 schema_version / scraped_at）。 */
export interface RawOrder {
  order_id: string
  remark: string
  shop?: string
  spec?: string
  /** 该订单是否带「AI未识别」标记（酒红底档案图标）；随 extras 上报。 */
  ai_unrecognized?: boolean
}
