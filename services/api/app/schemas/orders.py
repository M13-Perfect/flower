from __future__ import annotations

from pydantic import Field

from app.schemas.errors import ApiModel


class ParseOrderRequest(ApiModel):
    order_note: str = Field(alias="orderNote", min_length=1, max_length=5000)
    order_id: str | None = Field(default=None, alias="orderId", max_length=120)


class FlowerChoice(ApiModel):
    choice: int = Field(ge=1, le=2)
    name: str = Field(min_length=1)


class FontPreference(ApiModel):
    choice: int = Field(ge=1, le=8)
    label: str = Field(min_length=1)


class ParsedOrder(ApiModel):
    order_id: str | None = Field(default=None, alias="orderId", max_length=120)
    customer_name: str | None = Field(default=None, alias="customerName", max_length=200)
    month: int | None = Field(default=None, ge=1, le=12)
    month_name: str | None = Field(default=None, alias="monthName", max_length=20)
    flower: FlowerChoice | None = None
    font_preference: FontPreference | None = Field(default=None, alias="fontPreference")
    special_notes: str = Field(default="", alias="specialNotes", max_length=1000)


class ParseOrderResponse(ApiModel):
    parsed_order: ParsedOrder = Field(alias="parsedOrder")
    warnings: list[str] = Field(default_factory=list)
    requires_manual_confirmation: bool = Field(default=True, alias="requiresManualConfirmation")

