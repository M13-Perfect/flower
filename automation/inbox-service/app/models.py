from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# 订单在系统中的状态（见计划「状态机」）。
STATUS_RECEIVED = "RECEIVED"
STATUS_WRITTEN = "WRITTEN_TO_INBOX"
STATUS_WRITE_FAILED = "WRITE_FAILED"
STATUS_QUEUED = "QUEUED_FOR_BATCH"
STATUS_DONE = "DONE"  # 批量已完成（report.xlsx 中 EXPORTED）
STATUS_CANNOT_AUTOGEN = "CANNOT_AUTOGEN"  # 无法自动生成（需人工核验）


class Order(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    remark: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=STATUS_RECEIVED)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # 无法自动生成的原因汇总
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[str] = mapped_column(Text)  # 全量 payload，审计 / 重放
    inbox_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    shop: Mapped[str | None] = mapped_column(String(200), nullable=True)
    spec: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 店小秘订单实时状态（退款拦截用）；首次抓取写入，Phase 2 关键节点重抓刷新。取值待店小秘详情页确认。
    refund_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    written_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 行项目（打破「一单一件」）。幂等重发时整树替换，故 delete-orphan。
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItem.line_index",
    )

    def to_dict(self) -> dict:
        def iso(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        return {
            "order_id": self.order_id,
            "remark": self.remark,
            "status": self.status,
            "reason": self.reason,
            "error": self.error,
            "inbox_path": self.inbox_path,
            "shop": self.shop,
            "spec": self.spec,
            "source_url": self.source_url,
            "refund_status": self.refund_status,
            "items": [item.to_dict() for item in self.items],
            "received_at": iso(self.received_at),
            "updated_at": iso(self.updated_at),
            "written_at": iso(self.written_at),
            "done_at": iso(self.done_at),
        }


class OrderItem(Base):
    """订单行项目：同一订单可有多个目标盒子 + 其他商品。

    语义拆分（一条备注 N 个名字 → N 个定制单元）不在这里做，交给 Flower GPT 解析层；
    本表只承载扩展从店小秘详情页结构化抓到的「行项目 + 原始备注」。
    """

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.order_id", ondelete="CASCADE"), index=True
    )
    line_index: Mapped[int] = mapped_column(Integer)  # 订单内行项目序号，从 0 起
    product_sku: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_target_box: Mapped[bool] = mapped_column(Boolean, default=True)  # 是否本系统负责生产
    quantity: Mapped[int] = mapped_column(Integer, default=1)  # 该行件数（店小秘 ×N）
    personalization_raw: Mapped[str | None] = mapped_column(Text, nullable=True)  # 该行原始定制备注
    extras_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 该行店小秘特定字段（图片/链接等）

    order: Mapped["Order"] = relationship(back_populates="items")

    def to_dict(self) -> dict:
        return {
            "line_index": self.line_index,
            "product_sku": self.product_sku,
            "is_target_box": self.is_target_box,
            "quantity": self.quantity,
            "personalization_raw": self.personalization_raw,
            "extras": json.loads(self.extras_json) if self.extras_json else {},
        }
