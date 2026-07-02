from __future__ import annotations

from datetime import timedelta

from app.models import utcnow
from app.rescrape_queue import (
    STATE_ABSENT,
    STATE_DONE,
    STATE_EXPIRED,
    STATE_NOT_FOUND,
    STATE_PENDING,
    RescrapeQueue,
)

# 定向重抓握手（option B）：Ezcad 入队 → 扩展拉队列重抓 → 回填 → Ezcad 轮询拿结果。


# ── 内存队列纯逻辑 ─────────────────────────────────────────────


def test_request_then_pending_then_resolve_done():
    q = RescrapeQueue(ttl_seconds=60)
    q.request("A1")
    assert q.pending() == ["A1"]
    assert q.status("A1")["state"] == STATE_PENDING

    q.resolve("A1", found=True, refund_status="已退款")
    assert q.pending() == []  # 已解决 → 不再发给扩展
    st = q.status("A1")
    assert st["state"] == STATE_DONE
    assert st["refund_status"] == "已退款"


def test_resolve_not_found():
    q = RescrapeQueue(ttl_seconds=60)
    q.request("A1")
    q.resolve("A1", found=False)
    assert q.status("A1")["state"] == STATE_NOT_FOUND
    assert q.status("A1")["refund_status"] is None


def test_absent_when_never_requested():
    q = RescrapeQueue(ttl_seconds=60)
    assert q.status("NOPE")["state"] == STATE_ABSENT


def test_pending_expires_after_ttl():
    q = RescrapeQueue(ttl_seconds=10)
    now = utcnow()
    q.request("A1", now=now)
    later = now + timedelta(seconds=11)
    assert q.pending(now=later) == []  # 超 TTL 不再发给扩展
    assert q.status("A1", now=later)["state"] == STATE_EXPIRED


def test_pending_ordered_by_request_time():
    q = RescrapeQueue(ttl_seconds=60)
    now = utcnow()
    q.request("B", now=now)
    q.request("A", now=now + timedelta(seconds=1))
    assert q.pending(now=now + timedelta(seconds=2)) == ["B", "A"]


def test_re_request_resets_to_pending():
    q = RescrapeQueue(ttl_seconds=60)
    q.request("A1")
    q.resolve("A1", found=True, refund_status="正常")
    q.request("A1")  # 再次入队
    assert q.status("A1")["state"] == STATE_PENDING
    assert q.pending() == ["A1"]


# ── 端点串联 ───────────────────────────────────────────────────


def _ingest(client, order_id, refund_status=None):
    payload = {"schema_version": "1.0", "order_id": order_id, "remark": "x"}
    if refund_status is not None:
        payload["refund_status"] = refund_status
    assert client.post("/inbox/orders", json=payload).status_code == 200


def test_endpoint_full_handshake_refreshes_order(client):
    _ingest(client, "R1", "已审核")  # 入库时正常
    # Ezcad 入队
    assert client.post("/inbox/refund/rescrape/request", json={"order_id": "R1"}).json()["state"] == "pending"
    # 扩展拉队列
    assert client.get("/inbox/refund/rescrape/queue").json()["order_ids"] == ["R1"]
    # 扩展回填：店小秘现查为已退款
    res = client.post(
        "/inbox/refund/rescrape/result",
        json={"order_id": "R1", "found": True, "refund_status": "已退款"},
    ).json()
    assert res["state"] == "done" and res["refund_status"] == "已退款"
    # 队列已清空（不再发给扩展）
    assert client.get("/inbox/refund/rescrape/queue").json()["count"] == 0
    # Ezcad 轮询拿到 done
    assert client.get("/inbox/refund/rescrape/status/R1").json()["state"] == "done"
    # 关键：Order.refund_status 已被刷新 → 随后 /recheck 用的是新鲜值
    assert client.get("/inbox/orders/R1").json()["refund_status"] == "已退款"
    gate = client.post("/inbox/orders/R1/recheck", json={"stage": "engraving"}).json()
    assert gate["blocked"] is True


def test_endpoint_not_found_result(client):
    client.post("/inbox/refund/rescrape/request", json={"order_id": "GHOST"})
    client.post("/inbox/refund/rescrape/result", json={"order_id": "GHOST", "found": False})
    assert client.get("/inbox/refund/rescrape/status/GHOST").json()["state"] == "not_found"


def test_endpoint_status_absent_when_never_requested(client):
    assert client.get("/inbox/refund/rescrape/status/NEVER").json()["state"] == "absent"


def test_endpoint_request_rejects_bad_order_id(client):
    assert client.post("/inbox/refund/rescrape/request", json={"order_id": "../evil"}).status_code == 422
