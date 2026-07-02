from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db import session_scope
from app.models import STATUS_DONE, STATUS_WRITTEN, Order, RefundCheck
from app.refund_scheduler import RefundScheduler
from app.scheduler import due_for_recheck

UTC = timezone.utc


def _now() -> datetime:
    return datetime(2026, 6, 19, 14, 0, tzinfo=UTC)


def _add_order(session, order_id, *, status=STATUS_WRITTEN, received=None) -> None:
    session.add(
        Order(
            order_id=order_id,
            remark="x",
            raw_json="{}",
            status=status,
            received_at=received or datetime(2026, 6, 19, 10, 0, tzinfo=UTC),
        )
    )


def _add_check(session, order_id, *, checked_at, action="allow") -> None:
    session.add(
        RefundCheck(
            order_id=order_id,
            stage="typesetting",
            queried_status="已审核",
            blocked_action=action,
            checked_at=checked_at,
        )
    )


# ── 纯函数：新鲜度判定 ───────────────────────────────────────────────


def test_due_for_recheck_never_checked_is_due(app):
    with session_scope(app.state.session_factory) as session:
        _add_order(session, "fresh")
    with session_scope(app.state.session_factory) as session:
        due = due_for_recheck(session, now=_now(), interval_seconds=600)
        assert [o.order_id for o in due] == ["fresh"]


def test_due_for_recheck_recent_check_excluded_stale_included(app):
    now = _now()
    with session_scope(app.state.session_factory) as session:
        _add_order(session, "recent")
        _add_order(session, "stale")
        _add_check(session, "recent", checked_at=now - timedelta(seconds=60))  # 1min 前 → 新鲜
        _add_check(session, "stale", checked_at=now - timedelta(seconds=3600))  # 1h 前 → 过期
    with session_scope(app.state.session_factory) as session:
        due = due_for_recheck(session, now=now, interval_seconds=600)
        assert [o.order_id for o in due] == ["stale"]


def test_due_for_recheck_excludes_done_and_respects_limit(app):
    now = _now()
    with session_scope(app.state.session_factory) as session:
        _add_order(session, "a", received=datetime(2026, 6, 19, 9, 0, tzinfo=UTC))
        _add_order(session, "b", received=datetime(2026, 6, 19, 9, 30, tzinfo=UTC))
        _add_order(session, "done", status=STATUS_DONE)
    with session_scope(app.state.session_factory) as session:
        assert [o.order_id for o in due_for_recheck(session, now=now, interval_seconds=600)] == ["a", "b"]
        # limit 截断（按 received_at 升序，先到的优先）。
        assert [o.order_id for o in due_for_recheck(session, now=now, interval_seconds=600, limit=1)] == ["a"]
        # active_only=False 时把 done 也算进来。
        ids = [o.order_id for o in due_for_recheck(session, now=now, interval_seconds=600, active_only=False)]
        assert set(ids) == {"a", "b", "done"}


# ── 触发器端点：/inbox/refund/pending ────────────────────────────────


def _ingest(client, order_id, refund_status=None):
    payload = {"schema_version": "1.0", "order_id": order_id, "remark": "x"}
    if refund_status is not None:
        payload["refund_status"] = refund_status
    assert client.post("/inbox/orders", json=payload).status_code == 200


def test_pending_endpoint_drains_after_recheck(client):
    _ingest(client, "P1")
    _ingest(client, "P2")
    # 初始都待重抓。
    pending = client.get("/inbox/refund/pending").json()
    assert {p["order_id"] for p in pending["pending"]} == {"P1", "P2"}

    # 扩展对 P1 重抓后回 /recheck → P1 在 interval 内掉出清单。
    assert client.post("/inbox/orders/P1/recheck", json={"stage": "typesetting"}).status_code == 200
    after = client.get("/inbox/refund/pending").json()
    assert {p["order_id"] for p in after["pending"]} == {"P2"}

    # interval=0 → 强制全部待重抓（无视刚才的检查）。
    forced = client.get("/inbox/refund/pending", params={"recheck_interval": 0}).json()
    assert {p["order_id"] for p in forced["pending"]} == {"P1", "P2"}


def test_pending_endpoint_respects_limit(client):
    for i in range(3):
        _ingest(client, f"L{i}")
    body = client.get("/inbox/refund/pending", params={"limit": 2}).json()
    assert body["count"] == 2


# ── 后台线程：tick / 快照 / 驱动器 ───────────────────────────────────


def test_status_endpoint_reflects_tick(client):
    _ingest(client, "T1")
    # 初始未跑过。
    assert client.get("/inbox/refund/status").json()["last_run_at"] is None
    # 手动跑一轮（不依赖线程）。
    tick = client.post("/inbox/refund/tick").json()
    assert tick["pending_count"] == 1 and tick["pending_ids"] == ["T1"]
    status = client.get("/inbox/refund/status").json()
    assert status["last_run_at"] is not None
    assert status["pending_count"] == 1


def test_scheduler_tick_invokes_driver(app):
    seen: list[list[str]] = []
    with session_scope(app.state.session_factory) as session:
        _add_order(session, "D1")
        _add_order(session, "D2")
    scheduler = RefundScheduler(
        app.state.session_factory,
        recheck_interval_seconds=600,
        driver=seen.append,
    )
    ids = scheduler.tick_once()
    assert set(ids) == {"D1", "D2"}
    assert seen == [ids]  # driver 收到同一份清单
    assert scheduler.pending_count == 2
