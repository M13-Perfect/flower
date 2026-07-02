from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _task(client):
    # P0 任务租约：批量入库属自动抓取路径，需有效任务授权（宽时间窗覆盖所有 paid_at）。
    resp = client.post(
        "/inbox/scrape/task/start",
        json={"flower_instance_id": "test-flower", "scrape_from": "2000-01-01 00:00"},
    )
    assert resp.status_code == 200, resp.text


def _order(order_id: str, remark: str = "name Amy font 1 flower 2") -> dict:
    # 带落在任务窗内的 paid_at，否则 order_in_scope=False 会被范围闸拦掉。
    return {
        "schema_version": "1.0",
        "order_id": order_id,
        "remark": remark,
        "extras": {"paid_at": "2026-06-19 02:25"},
    }


def test_batch_ingest_writes_all_and_reports_counts(client, settings):
    resp = client.post(
        "/inbox/orders/batch",
        json={"orders": [_order("B-1"), _order("B-2"), _order("B-3")]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    assert body["written"] == 3
    assert body["failed"] == 0
    assert {r["order_id"] for r in body["results"]} == {"B-1", "B-2", "B-3"}
    for oid in ("B-1", "B-2", "B-3"):
        assert (settings.inbox_dir / f"{oid}.json").is_file()
        assert client.get(f"/inbox/orders/{oid}").json()["status"] == "WRITTEN_TO_INBOX"


def test_batch_ingest_isolates_bad_order(client, settings):
    # 一单 schema 不符不连累整批：好单照常入库，坏单记 failed、不入库。
    resp = client.post(
        "/inbox/orders/batch",
        json={"orders": [_order("OK-1"), {"schema_version": "9.9", "order_id": "BAD-1", "remark": "x"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["written"] == 1
    assert body["failed"] == 1
    assert (settings.inbox_dir / "OK-1.json").is_file()
    assert client.get("/inbox/orders/BAD-1").status_code == 404
    bad = next(r for r in body["results"] if r["order_id"] == "BAD-1")
    assert bad["status"] == "schema_mismatch"


def test_list_orders_reports_total_count_and_respects_limit(client):
    for i in range(5):
        client.post("/inbox/orders", json=_order(f"L-{i}"))
    full = client.get("/inbox/orders").json()
    assert full["count"] == 5 and full["returned"] == 5 and len(full["orders"]) == 5
    page = client.get("/inbox/orders?limit=2").json()
    assert page["count"] == 5  # 总数仍是 5，不随分页变
    assert page["returned"] == 2 and page["limit"] == 2 and len(page["orders"]) == 2
    page2 = client.get("/inbox/orders?limit=2&offset=2").json()
    assert page2["returned"] == 2
    overlap = {o["order_id"] for o in page["orders"]} & {o["order_id"] for o in page2["orders"]}
    assert overlap == set()  # 分页不重叠
