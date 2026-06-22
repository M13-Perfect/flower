"""GET /inbox/orders/next：操作员端「库驱动载单」取『最旧待生成订单』（FIFO 队首）的回归护栏。

队首 = 未软删 + ai_status=pending，按 received_at 升序第一条；生成完(recognized)/软删/冲突(conflict)
都不算待生成、不得被取到。生成成功后该单 ai_status→recognized 自动掉出队列 → 队首前进到下一条。
"""
from __future__ import annotations

from datetime import timedelta

from app.db import session_scope
from app.models import (
    AI_STATUS_CONFLICT,
    AI_STATUS_PENDING,
    AI_STATUS_RECOGNIZED,
    Order,
    utcnow,
)


def _seed(app, order_id: str, *, minutes_ago: int, ai_status: str = AI_STATUS_PENDING, deleted: bool = False) -> None:
    now = utcnow()
    with session_scope(app.state.session_factory) as session:
        session.add(
            Order(
                order_id=order_id,
                remark=f"remark-{order_id}",
                raw_json="{}",
                received_at=now - timedelta(minutes=minutes_ago),
                ai_status=ai_status,
                deleted=deleted,
            )
        )


def _next(client):
    return client.get("/inbox/orders/next").json()["order"]


def test_next_returns_oldest_pending(app, client):
    # 三条待生成单 → 取 received_at 最旧那条（FIFO 先来先做）。
    _seed(app, "NEW", minutes_ago=1)
    _seed(app, "OLD", minutes_ago=10)
    _seed(app, "MID", minutes_ago=5)
    order = _next(client)
    assert order is not None
    assert order["order_id"] == "OLD"
    assert order["remark"] == "remark-OLD"  # 备注随单带回，供订单信息框直接载入


def test_next_skips_recognized_so_generated_orders_advance(app, client):
    # 已生成(recognized)的单跳过 → 队首前进到下一条未生成单（订单不删、仍在表里）。
    _seed(app, "DONE", minutes_ago=10, ai_status=AI_STATUS_RECOGNIZED)
    _seed(app, "TODO", minutes_ago=5)
    assert _next(client)["order_id"] == "TODO"


def test_next_excludes_soft_deleted_and_conflict(app, client):
    _seed(app, "GONE", minutes_ago=10, deleted=True)                       # 软删 → 不取
    _seed(app, "FROZEN", minutes_ago=8, ai_status=AI_STATUS_CONFLICT)      # 冲突冻结 → 走复核、不取
    _seed(app, "GO", minutes_ago=3)
    assert _next(client)["order_id"] == "GO"


def test_next_returns_null_when_no_pending(app, client):
    _seed(app, "DONE", minutes_ago=5, ai_status=AI_STATUS_RECOGNIZED)
    assert _next(client) is None  # 无待生成单 → {"order": null}
