from __future__ import annotations

# P0：任务租约 + 授权守卫（2026-06-22）。覆盖「无 Flower 有效任务 → 零采集/零打标」。

import sys
from datetime import datetime
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.authorization import (  # noqa: E402
    action_allowed,
    is_authorized,
    lease_valid,
    order_in_scope,
    paid_in_time_window,
)
from app.models import ScrapeControl  # noqa: E402

NOW = datetime(2026, 6, 22, 12, 0, 0)
LEASE = datetime(2026, 6, 22, 12, 1, 0)  # NOW + 60s


def _control(**kw) -> ScrapeControl:
    base = dict(
        scope="order_scrape",
        enabled=True,
        task_id="t1",
        flower_instance_id="f1",
        lease_expires_at=LEASE,
        scrape_from=datetime(2000, 1, 1),
        scrape_to=None,
        allowed_actions="scrape,mark",
        shop_scope=None,
    )
    base.update(kw)
    return ScrapeControl(**base)


# ── 单元：授权判定（确定性，不靠真实时钟）─────────────────────────

def test_authorized_when_lease_fresh():
    assert is_authorized(_control(), now=NOW) is True


def test_unauthorized_when_lease_expired():
    """场景 7：租约过期（flower 关掉/不再心跳）→ 未授权。"""
    after = datetime(2026, 6, 22, 12, 1, 1)  # 超过 LEASE
    assert is_authorized(_control(), now=after) is False


def test_unauthorized_when_no_task():
    """场景 2/8：无任务（task_id 空）→ 未授权，哪怕 enabled=true。"""
    c = _control(task_id=None, lease_expires_at=None)
    assert is_authorized(c, now=NOW) is False
    assert lease_valid(c, now=NOW) is False


def test_enabled_true_without_lease_is_not_authorized():
    """核心修复 / 场景 2：残留 enabled=true 但无租约 → 仍未授权。"""
    c = _control(task_id=None, lease_expires_at=None, enabled=True)
    assert is_authorized(c, now=NOW) is False


def test_unauthorized_when_no_time_range():
    """规范：缺订单时间范围（scrape_from）必须拒绝。"""
    assert is_authorized(_control(scrape_from=None), now=NOW) is False


def test_unauthorized_when_disabled():
    assert is_authorized(_control(enabled=False), now=NOW) is False


def test_none_control_unauthorized():
    assert is_authorized(None, now=NOW) is False
    assert lease_valid(None, now=NOW) is False


def test_action_allowed_respects_allowed_actions():
    c = _control(allowed_actions="scrape")
    assert action_allowed(c, "scrape", now=NOW) is True
    assert action_allowed(c, "mark", now=NOW) is False  # 未授权该操作


# ── 单元：订单范围判定 ───────────────────────────────────────────

def test_order_in_scope_time_window():
    c = _control(scrape_from=datetime(2026, 6, 19), scrape_to=datetime(2026, 6, 21))
    assert order_in_scope(c, paid_at=datetime(2026, 6, 20)) is True
    assert order_in_scope(c, paid_at=datetime(2026, 6, 18)) is False  # 早于下界（历史）
    assert order_in_scope(c, paid_at=datetime(2026, 6, 22)) is False  # 晚于上界


def test_order_without_paid_at_is_out_of_scope():
    """fail-closed：无付款时间无法按时间判定 → 不在范围（防历史/未付款单混入打标）。"""
    assert order_in_scope(_control(), paid_at=None) is False
    assert paid_in_time_window(_control(), None) is False


def test_order_in_scope_shop_filter():
    c = _control(shop_scope="shopA,shopB")
    assert order_in_scope(c, paid_at=datetime(2026, 6, 20), shop="shopA") is True
    assert order_in_scope(c, paid_at=datetime(2026, 6, 20), shop="shopC") is False


# ── 集成：端点级 fail-closed ─────────────────────────────────────

def _order(order_id: str, paid_at: str | None = "2026-06-19 02:25") -> dict:
    body = {"schema_version": "1.0", "order_id": order_id, "remark": "x"}
    if paid_at is not None:
        body["extras"] = {"paid_at": paid_at}
    return body


def test_default_control_unauthorized(client):
    ctrl = client.get("/inbox/scrape/control").json()
    assert ctrl["authorized"] is False and ctrl["task_id"] is None


def test_start_task_authorizes_and_returns_task_id(client):
    start = client.post(
        "/inbox/scrape/task/start",
        json={"flower_instance_id": "f1", "scrape_from": "2000-01-01 00:00"},
    ).json()
    assert start["authorized"] is True
    assert start["task_id"]
    assert client.get("/inbox/scrape/control").json()["authorized"] is True


def test_start_requires_scrape_from(client):
    """规范：缺订单时间范围必须拒绝。"""
    r = client.post("/inbox/scrape/task/start", json={"flower_instance_id": "f1"})
    assert r.status_code == 422


def test_enabled_true_without_lease_blocks_side_effects(client):
    """场景 2：模拟旧失控态——PUT enabled=true（无租约）→ 仍未授权，副作用端点全拒。"""
    client.put("/inbox/scrape/control", json={"enabled": True, "restart_from": "2000-01-01 00:00"})
    ctrl = client.get("/inbox/scrape/control").json()
    assert ctrl["enabled"] is True
    assert ctrl["authorized"] is False
    assert client.post("/inbox/orders/batch", json={"orders": [_order("X1")]}).status_code == 403
    assert client.post("/inbox/scrape/diff", json={"orders": [{"order_id": "X1", "paid_at": "2026-06-19 02:25"}]}).status_code == 403
    assert client.get("/inbox/mark/pending").json()["jobs"] == []


def test_stop_releases_lease(client):
    """场景 6：停止 → 立即未授权。"""
    s = client.post(
        "/inbox/scrape/task/start",
        json={"flower_instance_id": "f1", "scrape_from": "2000-01-01 00:00"},
    ).json()
    client.post("/inbox/scrape/task/stop", json={"task_id": s["task_id"]})
    assert client.get("/inbox/scrape/control").json()["authorized"] is False
    assert client.post("/inbox/orders/batch", json={"orders": [_order("X1")]}).status_code == 403


def test_heartbeat_extends_and_rejects_wrong_task(client):
    s = client.post(
        "/inbox/scrape/task/start",
        json={"flower_instance_id": "f1", "scrape_from": "2000-01-01 00:00"},
    ).json()
    ok = client.post(
        "/inbox/scrape/task/heartbeat",
        json={"task_id": s["task_id"], "flower_instance_id": "f1"},
    )
    assert ok.status_code == 200 and ok.json()["authorized"] is True
    bad = client.post(
        "/inbox/scrape/task/heartbeat",
        json={"task_id": "deadbeefdeadbeef", "flower_instance_id": "f1"},
    )
    assert bad.status_code == 409  # 任务已失效 → 旧实例据此停手


def test_mark_pending_empty_without_task(client):
    """场景 3：无任务时即便库里有单也拉不到打标任务 → 零打标。"""
    # 单端上传开放（手动），但不入队打标（无任务/范围外）。
    client.post("/inbox/orders", json=_order("4090000100"))
    assert client.get("/inbox/mark/pending").json()["jobs"] == []


def test_mark_pending_scope_filters_backlog(client):
    """场景 10：旧 backlog（范围外的 pending 打标任务）不被下发到店小秘。"""
    # 用宽任务先入库 + 入队两单的打标任务。
    client.post(
        "/inbox/scrape/task/start",
        json={"flower_instance_id": "f1", "scrape_from": "2000-01-01 00:00"},
    )
    client.post("/inbox/orders", json=_order("OLD", paid_at="2026-06-01 00:00"))
    client.post("/inbox/orders", json=_order("NEW", paid_at="2026-06-20 00:00"))
    pend_all = {j["order_id"] for j in client.get("/inbox/mark/pending").json()["jobs"]}
    assert pend_all == {"OLD", "NEW"}  # 宽窗口下都在
    # 换一个窄窗口任务（只覆盖 6-19 之后）→ OLD（6-01）变成范围外 backlog，不再下发。
    client.post(
        "/inbox/scrape/task/start",
        json={"flower_instance_id": "f1", "scrape_from": "2026-06-19 00:00"},
    )
    pend_narrow = {j["order_id"] for j in client.get("/inbox/mark/pending").json()["jobs"]}
    assert pend_narrow == {"NEW"}  # OLD 被范围闸拦掉，不写店小秘


def test_batch_rejects_out_of_scope_order(client):
    """场景 5：扩展回传范围外/历史订单 → 入库前拦截，不写不打标。"""
    client.post(
        "/inbox/scrape/task/start",
        json={"flower_instance_id": "f1", "scrape_from": "2026-06-19 00:00"},
    )
    body = client.post(
        "/inbox/orders/batch",
        json={"orders": [_order("INWIN", "2026-06-20 00:00"), _order("HIST", "2026-06-01 00:00")]},
    ).json()
    results = {r["order_id"]: r["status"] for r in body["results"]}
    assert results["INWIN"] == "WRITTEN_TO_INBOX"
    assert results["HIST"] == "out_of_scope"
    assert client.get("/inbox/orders/HIST").status_code == 404  # 没入库
