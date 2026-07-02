from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db import session_scope
from app.models import STATUS_DONE, STATUS_WRITTEN, Order
from app.scheduler import (
    Window,
    advance_checkpoint,
    get_checkpoint,
    resolve_window,
    select_due_orders,
)

UTC = timezone.utc


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 19, hour, minute, tzinfo=UTC)


def _add_order(session, order_id: str, received_at: datetime, status: str = STATUS_WRITTEN) -> None:
    session.add(
        Order(
            order_id=order_id,
            remark="x",
            raw_json="{}",
            status=status,
            received_at=received_at,
        )
    )


# ── 纯函数：窗口解析（A/B/C + 半开）─────────────────────────────────


def test_resolve_window_rule_a_current_window():
    now = at(14, 0)
    w = resolve_window("A", now=now, window_seconds=600)
    assert w.start == at(13, 50)
    assert w.end == now


def test_resolve_window_rule_b_from_checkpoint_or_head():
    now = at(14, 0)
    assert resolve_window("B", now=now, checkpoint_cursor=at(12, 30)).start == at(12, 30)
    assert resolve_window("B", now=now, checkpoint_cursor=None).start is None  # 首跑=从头


def test_resolve_window_rule_c_requires_start_end():
    assert resolve_window("C", now=at(14), start=at(12), end=at(13)) == Window(at(12), at(13))
    with pytest.raises(ValueError):
        resolve_window("C", now=at(14), start=at(12), end=None)


def test_resolve_window_unknown_rule():
    with pytest.raises(ValueError):
        resolve_window("Z", now=at(14))


# ── 选单：半开区间 [start, end) + 排序 + active_only ──────────────────


def test_select_due_orders_half_open_and_order(app):
    with session_scope(app.state.session_factory) as session:
        _add_order(session, "before", at(12, 0))
        _add_order(session, "lo-boundary", at(12, 30))  # == start → 含
        _add_order(session, "mid", at(13, 30))
        _add_order(session, "hi-boundary", at(14, 0))  # == end → 不含
    with session_scope(app.state.session_factory) as session:
        due = select_due_orders(session, Window(at(12, 30), at(14, 0)))
        assert [o.order_id for o in due] == ["lo-boundary", "mid"]  # 升序、半开


def test_select_due_orders_active_only_excludes_done(app):
    with session_scope(app.state.session_factory) as session:
        _add_order(session, "active", at(13, 0), status=STATUS_WRITTEN)
        _add_order(session, "done", at(13, 10), status=STATUS_DONE)
    win = Window(at(12, 0), at(14, 0))
    with session_scope(app.state.session_factory) as session:
        assert [o.order_id for o in select_due_orders(session, win)] == ["active"]
    with session_scope(app.state.session_factory) as session:
        ids = [o.order_id for o in select_due_orders(session, win, active_only=False)]
        assert ids == ["active", "done"]


def test_select_due_orders_no_lower_bound(app):
    with session_scope(app.state.session_factory) as session:
        _add_order(session, "old", at(8, 0))
        _add_order(session, "new", at(13, 0))
    with session_scope(app.state.session_factory) as session:
        due = select_due_orders(session, Window(None, at(14, 0)))
        assert [o.order_id for o in due] == ["old", "new"]


def test_select_due_orders_is_side_effect_free(app):
    with session_scope(app.state.session_factory) as session:
        _add_order(session, "o1", at(13, 0))
    win = Window(at(12, 0), at(14, 0))
    with session_scope(app.state.session_factory) as session:
        select_due_orders(session, win)
        select_due_orders(session, win)  # 重复扫描
    with session_scope(app.state.session_factory) as session:
        # 状态未被调度改动（同单重复抓取无副作用）。
        assert session.get(Order, "o1").status == STATUS_WRITTEN


# ── 断点续跑：12:30 断、14:00 恢复，规则 B 不漏不重 ───────────────────


def test_rule_b_resume_no_miss_no_dup(app):
    with session_scope(app.state.session_factory) as session:
        _add_order(session, "a-1200", at(12, 0))  # 12:30 前已扫过
        _add_order(session, "b-1245", at(12, 45))  # 断档期到件
        _add_order(session, "c-1330", at(13, 30))  # 断档期到件
        advance_checkpoint(session, "refund_recheck", at(12, 30))  # 模拟扫到 12:30 就断了

    # 14:00 恢复：规则 B 从 checkpoint(12:30) 续到 now(14:00)。
    with session_scope(app.state.session_factory) as session:
        cur = get_checkpoint(session, "refund_recheck").cursor
        win = resolve_window("B", now=at(14, 0), checkpoint_cursor=cur)
        due = select_due_orders(session, win)
        assert [o.order_id for o in due] == ["b-1245", "c-1330"]  # 不漏断档、不重 12:00 前
        advance_checkpoint(session, "refund_recheck", win.end)  # 扫完推进到 14:00

    # 再次续跑：窗口 [14:00, 14:00) 为空，不重复。
    with session_scope(app.state.session_factory) as session:
        cur = get_checkpoint(session, "refund_recheck").cursor
        win = resolve_window("B", now=at(14, 0), checkpoint_cursor=cur)
        assert select_due_orders(session, win) == []


# ── 接口冒烟：/inbox/refund/scan ─────────────────────────────────────


def _ingest(client, order_id: str) -> None:
    assert (
        client.post(
            "/inbox/orders",
            json={"schema_version": "1.0", "order_id": order_id, "remark": "x"},
        ).status_code
        == 200
    )


def test_scan_endpoint_rule_c_lists_due_and_advances(client, app):
    _ingest(client, "S1")
    _ingest(client, "S2")
    resp = client.post(
        "/inbox/refund/scan",
        json={
            "rule": "C",
            "start": "2000-01-01T00:00:00+00:00",
            "end": "2100-01-01T00:00:00+00:00",
            "advance": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert {d["order_id"] for d in body["due"]} == {"S1", "S2"}
    assert body["checkpoint_advanced"] is True
    # checkpoint 已落库。
    with session_scope(app.state.session_factory) as session:
        assert get_checkpoint(session, "refund_recheck") is not None


def test_scan_endpoint_rule_c_missing_bounds_422(client):
    resp = client.post("/inbox/refund/scan", json={"rule": "C"})
    assert resp.status_code == 422


def test_scan_endpoint_rejects_bad_rule(client):
    resp = client.post("/inbox/refund/scan", json={"rule": "Z"})
    assert resp.status_code == 422
