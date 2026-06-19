from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# 与 automation/contracts/order.schema.json 的 order_id 正则一致（文件名安全）。
ORDER_ID_PATTERN = r"^[A-Za-z0-9_.\-]+$"


class OrderItemPayload(BaseModel):
    """订单行项目，对齐 contracts/order.schema.json 的 items[]。

    扩展只抓「结构 + 原始备注」，**不做语义拆分**（一条备注 N 个名字 → N 个定制单元交给 Flower GPT 解析层）。
    """

    model_config = ConfigDict(extra="forbid")

    line_index: int = Field(ge=0)
    product_sku: str | None = Field(default=None, max_length=1000)
    is_target_box: bool = True
    quantity: int = Field(default=1, ge=1)
    personalization_raw: str | None = Field(default=None, max_length=5000)
    extras: dict[str, Any] = Field(default_factory=dict)


class OrderPayload(BaseModel):
    """扩展 → 服务的订单报文，对齐 contracts/order.schema.json（snake_case + additionalProperties:false）。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    order_id: str = Field(min_length=1, max_length=120, pattern=ORDER_ID_PATTERN)
    remark: str = Field(min_length=1, max_length=5000)
    shop: str | None = Field(default=None, max_length=200)
    spec: str | None = Field(default=None, max_length=1000)
    source_url: str | None = Field(default=None, max_length=2000)
    scraped_at: str | None = None
    # 店小秘实时状态（退款拦截，可选）；缺省 None=未抓到/旧扩展。
    refund_status: str | None = Field(default=None, max_length=64)
    # 行项目（可选）；缺省空列表=按 remark 走旧单件逻辑，老扩展零影响。
    items: list[OrderItemPayload] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    order_id: str
    status: str
    dedup: bool
    inbox_path: str | None = None
