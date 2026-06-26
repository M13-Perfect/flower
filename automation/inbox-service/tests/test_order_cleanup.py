from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db import session_scope
from app.models import Order, OrderItem, utcnow
from app.refund_scheduler import RefundScheduler
from app.repository import purge_orders_older_than, upsert_scrape_control

UTC = timezone.utc


def _add_order(session, order_id, *, received: datetime) -> None:
    session.add(Order(order_id=order_id, remark="x", raw_json="{}", received_at=received))


def _order_count(factory) -> int:
    # 「在册」订单数 = 未软删的（软删后语义：行还在但不计入）。
    with session_scope(factory) as session:
        return session.scalar(
            select(func.count()).select_from(Order).where(Order.deleted.is_(False))
        )


# ── 删除单个订单（HTTP + 级联） ─────────────────────────────────────


def test_delete_order_removes_it_and_404_on_missing(client):
    client.post("/inbox/orders", json={"schema_version": "1.0", "order_id": "DEL1", "remark": "x"})
    assert client.delete("/inbox/orders/DEL1").json() == {"deleted": "DEL1"}
    assert client.get("/inbox/orders/DEL1").status_code == 404
    assert client.delete("/inbox/orders/DEL1").status_code == 404  # 再删→404


def test_delete_order_soft_keeps_row_and_items(client, app):
    """软删（2026-06-22）：单删不再级联清子表，行与 items 都保留，只把订单标记 deleted。"""
    client.post("/inbox/orders", json={
        "schema_version": "1.0", "order_id": "DELC", "remark": "x",
        "items": [{"line_index": 0, "is_target_box": True, "quantity": 2}],
    })
    client.delete("/inbox/orders/DELC")
    with session_scope(app.state.session_factory) as session:
        order = session.get(Order, "DELC")
        assert order is not None and order.deleted is True and order.deleted_at is not None
        assert session.scalar(select(func.count()).select_from(OrderItem)) == 1  # 子表保留


# ── 手动按龄清理 ────────────────────────────────────────────────────


def test_purge_route_deletes_only_old_orders(client, app):
    now = utcnow()
    with session_scope(app.state.session_factory) as session:
        _add_order(session, "old", received=now - timedelta(days=40))
        _add_order(session, "new", received=now - timedelta(days=1))
    body = client.post("/inbox/orders/purge", json={"older_than_days": 30}).json()
    assert body["deleted_count"] == 1
    assert client.get("/inbox/orders/old").status_code == 404
    assert client.get("/inbox/orders/new").status_code == 200


def test_purge_request_rejects_zero(client):
    # older_than_days >=1（不提供删全部的危险路径）。
    assert client.post("/inbox/orders/purge", json={"older_than_days": 0}).status_code == 422


def test_purge_repository_days_nonpositive_is_noop(app):
    now = datetime(2026, 6, 19, tzinfo=UTC)
    with session_scope(app.state.session_factory) as session:
        _add_order(session, "x", received=now - timedelta(days=100))
    with session_scope(app.state.session_factory) as session:
        assert purge_orders_older_than(session, 0, now=now) == 0
        assert purge_orders_older_than(session, -5, now=now) == 0
    assert _order_count(app.state.session_factory) == 1  # 没删


# ── 后台 scheduler 按 retention_days 清理 ───────────────────────────


def test_scheduler_purges_by_retention(app):
    now = utcnow()
    with session_scope(app.state.session_factory) as session:
        _add_order(session, "old", received=now - timedelta(days=40))
        _add_order(session, "new", received=now - timedelta(days=2))
        upsert_scrape_control(session, retention_days=30)  # 保留最近 30 天
    RefundScheduler(app.state.session_factory).tick_once()
    assert _order_count(app.state.session_factory) == 1  # old 被后台删，new 留


def test_scheduler_retention_zero_keeps_all(app):
    now = utcnow()
    with session_scope(app.state.session_factory) as session:
        _add_order(session, "old", received=now - timedelta(days=400))
        # 不设 retention（默认 0=关）
    RefundScheduler(app.state.session_factory).tick_once()
    assert _order_count(app.state.session_factory) == 1  # 0=关 → 一单不删


def test_put_scrape_control_persists_retention_days(client):
    out = client.put("/inbox/scrape/control", json={"retention_days": 45}).json()
    assert out["retention_days"] == 45
    assert client.get("/inbox/scrape/control").json()["retention_days"] == 45


# ── 软删语义：列表过滤 + 重新导入复活 + 行存活（2026-06-22） ────────────


def test_soft_deleted_order_hidden_from_list_and_count(client, app):
    """软删后：列表 / 计数都看不到，但物理行还在（不真删）。"""
    client.post("/inbox/orders", json={"schema_version": "1.0", "order_id": "SD1", "remark": "x"})
    client.delete("/inbox/orders/SD1")
    body = client.get("/inbox/orders").json()
    assert body["count"] == 0
    assert [o["order_id"] for o in body["orders"]] == []
    with session_scope(app.state.session_factory) as session:
        assert session.get(Order, "SD1") is not None  # 行仍在（软删）


def test_reimport_revives_soft_deleted_order(client, app):
    """误删找回：被软删的单重新导入（即便内容逐字节一致）→ 复活成 deleted=False，重回列表。"""
    payload = {"schema_version": "1.0", "order_id": "SD2", "remark": "hello"}
    client.post("/inbox/orders", json=payload)
    client.delete("/inbox/orders/SD2")
    assert client.get("/inbox/orders/SD2").status_code == 404  # 软删后对外 404
    client.post("/inbox/orders", json=payload)  # 重新导入 → 复活
    assert client.get("/inbox/orders/SD2").status_code == 200
    with session_scope(app.state.session_factory) as session:
        order = session.get(Order, "SD2")
        assert order.deleted is False and order.deleted_at is None
    assert client.get("/inbox/orders").json()["count"] == 1  # 复活后重回列表


def test_purge_is_soft_row_survives(client, app):
    """立即清理（按龄）现在是软删：deleted_count 照常，但行不真删。"""
    now = utcnow()
    with session_scope(app.state.session_factory) as session:
        _add_order(session, "oldsd", received=now - timedelta(days=40))
    assert client.post("/inbox/orders/purge", json={"older_than_days": 30}).json()["deleted_count"] == 1
    assert client.get("/inbox/orders/oldsd").status_code == 404  # 对外不可见
    with session_scope(app.state.session_factory) as session:
        order = session.get(Order, "oldsd")
        assert order is not None and order.deleted is True  # 行还在，只是软删
