from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import STATUS_RECEIVED, Order, OrderItem
from app.schemas import OrderPayload


def get_order(session: Session, order_id: str) -> Order | None:
    return session.get(Order, order_id)


def upsert_order(session: Session, payload: OrderPayload, raw_json: str) -> tuple[Order, bool]:
    """按 order_id UPSERT；返回 (order, dedup)。dedup=True 表示这单之前已收过（幂等重发）。

    行项目（items）整树替换：以最新一份报文为准，避免旧行项目残留。
    """
    existing = session.get(Order, payload.order_id)
    dedup = existing is not None
    if existing is None:
        order = Order(order_id=payload.order_id, status=STATUS_RECEIVED)
        session.add(order)
    else:
        order = existing
    order.remark = payload.remark
    order.shop = payload.shop
    order.spec = payload.spec
    order.source_url = payload.source_url
    order.refund_status = payload.refund_status
    order.raw_json = raw_json

    order.items.clear()  # delete-orphan 清掉旧行项目
    for item in payload.items:
        order.items.append(
            OrderItem(
                line_index=item.line_index,
                product_sku=item.product_sku,
                is_target_box=item.is_target_box,
                quantity=item.quantity,
                personalization_raw=item.personalization_raw,
                extras_json=json.dumps(item.extras, ensure_ascii=False) if item.extras else None,
            )
        )
    return order, dedup


def recent_orders(session: Session, limit: int = 100) -> list[Order]:
    stmt = select(Order).order_by(Order.received_at.desc()).limit(limit)
    return list(session.scalars(stmt))
