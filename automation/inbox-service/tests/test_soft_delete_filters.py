"""软删过滤的回归护栏（2026-06-22）。

这些过滤点（scrape diff / 批量导出 / 退款调度 / 打标下发都要排除软删单）曾因编辑丢失而
**静默回退、测试却仍全绿**——因为原本没有任何用例覆盖它们。本文件单独把它们锁死。
最关键的是 diff：软删单必须被当「新单」，否则扩展不会重抓，用户设计的
「误删靠重新导入找回」在生产里永远不会触发。
"""
from __future__ import annotations

from app.batch_exporter import _pending_orders
from app.db import session_scope
from app.models import Order, utcnow


def _ingest(client, order_id: str, *, paid_at: str = "2026-06-19 02:25"):
    return client.post(
        "/inbox/orders",
        json={
            "schema_version": "1.0",
            "order_id": order_id,
            "remark": "x",
            "refund_status": "已审核",
            "items": [{"line_index": 0, "product_sku": "S"}],
            "extras": {"paid_at": paid_at},
        },
    )


def test_scrape_diff_treats_soft_deleted_as_new(client):
    """软删单在 scrape diff 必须被判 REASON_NEW（=不存在）→ 扩展重抓 → 重新导入 → 复活。"""
    client.post(
        "/inbox/scrape/task/start",
        json={"flower_instance_id": "test-flower", "scrape_from": "2000-01-01 00:00"},
    )
    _ingest(client, "REV")
    manifest = {"orders": [{"order_id": "REV", "paid_at": "2026-06-19 02:25"}]}
    # 未删：完整 + 新鲜 → 命中缓存、不进 worklist
    r0 = client.post("/inbox/scrape/diff", json=manifest).json()
    assert {w["order_id"]: w["reason"] for w in r0["worklist"]} == {}
    # 软删后：diff 视它为不存在 → new（这步保证恢复链路能触发）
    client.delete("/inbox/orders/REV")
    r1 = client.post("/inbox/scrape/diff", json=manifest).json()
    assert {w["order_id"]: w["reason"] for w in r1["worklist"]} == {"REV": "new"}


def test_soft_deleted_excluded_from_batch_export(client, app):
    """软删单不得进入批量导出池（不流入生产）。"""
    _ingest(client, "KEEP")
    _ingest(client, "GONE")
    client.delete("/inbox/orders/GONE")
    with session_scope(app.state.session_factory) as session:
        ids = [o.order_id for o in _pending_orders(session)]
    assert ids == ["KEEP"]


def test_soft_deleted_excluded_from_refund_recheck_scan(app):
    """退款重抓调度不得扫到软删单（已清理的单不再被后台处理）。"""
    from app.scheduler import due_for_recheck

    now = utcnow()
    with session_scope(app.state.session_factory) as session:
        session.add(Order(order_id="LIVE", remark="x", raw_json="{}", received_at=now))
        session.add(Order(order_id="DEAD", remark="x", raw_json="{}", received_at=now, deleted=True, deleted_at=now))
    with session_scope(app.state.session_factory) as session:
        ids = {o.order_id for o in due_for_recheck(session, now=now, interval_seconds=0)}
    assert "DEAD" not in ids and "LIVE" in ids
