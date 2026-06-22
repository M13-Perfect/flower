from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db import session_scope
from app.models import Order, RefundCheck
from app.scrape_planner import (
    ManifestEntry,
    diff_manifest,
    is_order_complete,
    parse_paid_at,
)

UTC = timezone.utc


def _now() -> datetime:
    return datetime(2026, 6, 19, 14, 0, tzinfo=UTC)


# ── 付款时间解析 ─────────────────────────────────────────────────────


def test_parse_paid_at_formats():
    assert parse_paid_at("2026-06-19 02:25") == datetime(2026, 6, 19, 2, 25)
    assert parse_paid_at("2026-06-19 02:25:30") == datetime(2026, 6, 19, 2, 25, 30)
    assert parse_paid_at("2026-06-19T02:25:00") == datetime(2026, 6, 19, 2, 25)
    assert parse_paid_at(None) is None
    assert parse_paid_at("") is None
    assert parse_paid_at("乱码") is None


def test_paid_at_extracted_from_extras_on_ingest(client):
    client.post(
        "/inbox/orders",
        json={
            "schema_version": "1.0",
            "order_id": "PAID1",
            "remark": "x",
            "extras": {"paid_at": "2026-06-19 02:25"},
        },
    )
    got = client.get("/inbox/orders/PAID1").json()
    assert got["paid_at"] == "2026-06-19T02:25:00"


# ── 完整性判据 ───────────────────────────────────────────────────────


def _order(order_id, *, items=False, refund=None):
    o = Order(order_id=order_id, remark="x", raw_json="{}", refund_status=refund)
    if items:
        from app.models import OrderItem

        o.items.append(OrderItem(line_index=0, product_sku="S"))
    return o


def test_is_order_complete_requires_items_and_refund_status():
    assert is_order_complete(_order("a", items=True, refund="已审核")) is True
    assert is_order_complete(_order("b", items=True, refund=None)) is False  # 缺退款状态
    assert is_order_complete(_order("c", items=False, refund="已审核")) is False  # 缺行项目
    assert is_order_complete(_order("d")) is False


# ── manifest-diff：统一 worklist ─────────────────────────────────────


def _seed(session, order_id, *, items, refund, last_check=None, updated_at=None):
    o = _order(order_id, items=items, refund=refund)
    if updated_at is not None:
        o.updated_at = updated_at
    session.add(o)
    if last_check is not None:
        session.add(
            RefundCheck(
                order_id=order_id,
                stage="typesetting",
                queried_status=refund,
                blocked_action="allow",
                checked_at=last_check,
            )
        )


def test_diff_classifies_new_incomplete_refresh_and_skips_cached(app):
    now = _now()
    old = now - timedelta(seconds=9999)
    with session_scope(app.state.session_factory) as session:
        # complete + 新鲜检查（入库时间故意设旧，隔离出「靠检查新鲜」这条）→ 跳过
        _seed(session, "cached", items=True, refund="已审核", last_check=now - timedelta(seconds=60), updated_at=old)
        # complete + 检查过期 + 入库也过期 → refund_refresh
        _seed(session, "stale", items=True, refund="已审核", last_check=old, updated_at=old)
        # complete + 无检查 + 近期刚入库 → 跳过（修复①：自动循环重抓入库即视为状态新鲜，不再每轮重推）
        _seed(session, "freshingest", items=True, refund="已审核", updated_at=now - timedelta(seconds=30))
        # 缺行项目 / 缺退款状态 → incomplete
        _seed(session, "noitems", items=False, refund="已审核", updated_at=old)
        _seed(session, "norefund", items=True, refund=None, updated_at=old)

    manifest = [
        ManifestEntry(x, None) for x in ("cached", "stale", "freshingest", "noitems", "norefund")
    ] + [ManifestEntry("brandnew", parse_paid_at("2026-06-19 02:25"))]  # DB 没有 → new
    with session_scope(app.state.session_factory) as session:
        work = diff_manifest(session, manifest, now=now, recheck_interval_seconds=600)

    by_id = {w.order_id: w.reason for w in work}
    assert "cached" not in by_id  # 近期检查过 → 跳过
    assert "freshingest" not in by_id  # 修复①：刚重抓入库 → 跳过，不重推
    assert by_id == {
        "stale": "refund_refresh",
        "noitems": "incomplete",
        "norefund": "incomplete",
        "brandnew": "new",
    }
    new_item = next(w for w in work if w.order_id == "brandnew")
    assert new_item.paid_at == datetime(2026, 6, 19, 2, 25)


# ── 端点：/inbox/scrape/diff + /control ──────────────────────────────


def test_scrape_diff_endpoint(client):
    # P0：diff 是自动抓取规划入口，需有效任务授权（宽时间窗）。
    client.post(
        "/inbox/scrape/task/start",
        json={"flower_instance_id": "test-flower", "scrape_from": "2000-01-01 00:00"},
    )
    client.post(
        "/inbox/orders",
        json={
            "schema_version": "1.0",
            "order_id": "EXIST",
            "remark": "x",
            "refund_status": "已审核",
            "items": [{"line_index": 0, "product_sku": "S"}],
            "extras": {"paid_at": "2026-06-19 02:25"},
        },
    )
    resp = client.post(
        "/inbox/scrape/diff",
        json={"orders": [
            {"order_id": "EXIST", "paid_at": "2026-06-19 02:25"},
            {"order_id": "NEW1", "paid_at": "2026-06-19 02:25"},
        ]},
    )
    assert resp.status_code == 200
    body = resp.json()
    # EXIST 刚入库(完整+updated_at 新) → 命中缓存、跳过（修复①）；NEW1 不在库 → new。
    reasons = {w["order_id"]: w["reason"] for w in body["worklist"]}
    assert reasons == {"NEW1": "new"}
    assert body["counts"]["new"] == 1


def test_scrape_diff_requires_task_authorization(client):
    """P0：无有效任务 → diff 拒绝（403），扩展拿不到 worklist → 零抓取。"""
    resp = client.post(
        "/inbox/scrape/diff",
        json={"orders": [{"order_id": "NEW1", "paid_at": "2026-06-19 02:25"}]},
    )
    assert resp.status_code == 403


def test_scrape_diff_drops_out_of_time_window(client):
    """P0：任务时间窗外（历史订单）的清单条目不进 worklist，扩展不会去抓它们。"""
    client.post(
        "/inbox/scrape/task/start",
        json={"flower_instance_id": "test-flower", "scrape_from": "2026-06-19 00:00"},
    )
    resp = client.post(
        "/inbox/scrape/diff",
        json={"orders": [
            {"order_id": "OLD", "paid_at": "2026-06-01 00:00"},   # 窗外（历史）
            {"order_id": "NEW", "paid_at": "2026-06-20 00:00"},   # 窗内
        ]},
    ).json()
    reasons = {w["order_id"]: w["reason"] for w in resp["worklist"]}
    assert reasons == {"NEW": "new"}  # OLD 被时间窗拦掉
    assert resp["out_of_scope_dropped"] == 1


def test_scrape_control_get_default_and_put(client):
    # 默认未配置：关、无起点。
    default = client.get("/inbox/scrape/control").json()
    assert default["enabled"] is False and default["scrape_from"] is None

    # flower 写：开 + 间隔 + 从 T 重抓。
    put = client.put(
        "/inbox/scrape/control",
        json={"enabled": True, "interval_seconds": 120, "restart_from": "2026-06-19 00:00"},
    ).json()
    assert put["enabled"] is True
    assert put["interval_seconds"] == 120
    assert put["scrape_from"] == "2026-06-19T00:00:00"

    # 部分更新：只关开关，起点不动。
    put2 = client.put("/inbox/scrape/control", json={"enabled": False}).json()
    assert put2["enabled"] is False
    assert put2["scrape_from"] == "2026-06-19T00:00:00"  # 未传 restart_from → 不动


def test_scrape_control_put_rejects_bad_time(client):
    resp = client.put("/inbox/scrape/control", json={"restart_from": "乱码时间"})
    assert resp.status_code == 422
