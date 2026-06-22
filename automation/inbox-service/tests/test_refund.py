from __future__ import annotations

import pytest

from app.refund_gate import classify_status, decide


def _ingest(client, order_id: str, refund_status: str | None) -> None:
    payload = {"schema_version": "1.0", "order_id": order_id, "remark": "x"}
    if refund_status is not None:
        payload["refund_status"] = refund_status
    assert client.post("/inbox/orders", json=payload).status_code == 200


# ── 纯函数判定（不碰 DB）──────────────────────────────────────────────


@pytest.mark.parametrize(
    "status,expected",
    [
        ("已退款", "refund"),
        ("退款中", "refund"),
        ("已取消", "refund"),
        ("Refunded", "refund"),
        ("Cancelled", "refund"),
        ("风控中", "caution"),
        ("已冻结", "caution"),
        (None, "caution"),
        ("", "caution"),
        ("unknown", "caution"),
        ("已审核", "normal"),
        ("待打单（有货）", "normal"),
        ("已发货", "normal"),
    ],
)
def test_classify_status(status, expected):
    assert classify_status(status) == expected


def test_decide_refund_blocks_every_stage():
    for stage in ("typesetting", "engraving", "shipping"):
        action, _ = decide("已退款", stage)
        assert action == "block"


def test_decide_d4_caution_warns_before_typesetting_blocks_before_irreversible():
    assert decide(None, "typesetting")[0] == "warn"
    assert decide("风控中", "typesetting")[0] == "warn"
    assert decide(None, "engraving")[0] == "block"
    assert decide(None, "shipping")[0] == "block"
    assert decide("风控中", "engraving")[0] == "block"


def test_decide_normal_allows():
    assert decide("已发货", "typesetting")[0] == "allow"
    assert decide("已审核", "shipping")[0] == "allow"


# ── 接口：/recheck + 审计 ────────────────────────────────────────────


def test_recheck_refund_blocks_and_records(client):
    _ingest(client, "R-REFUND", "已退款")
    resp = client.post("/inbox/orders/R-REFUND/recheck", json={"stage": "typesetting"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["blocked"] is True
    assert body["action"] == "block"
    assert body["queried_status"] == "已退款"
    assert body["stage_label"] == "排版前"

    history = client.get("/inbox/orders/R-REFUND/refund-checks").json()
    assert history["count"] == 1
    assert history["checks"][0]["blocked_action"] == "block"
    assert history["checks"][0]["stage"] == "typesetting"


def test_recheck_d4_by_stage_for_missing_status(client):
    _ingest(client, "R-UNKNOWN", None)  # 无状态（旧扩展/未抓到）
    typeset = client.post("/inbox/orders/R-UNKNOWN/recheck", json={"stage": "typesetting"}).json()
    assert typeset["action"] == "warn" and typeset["blocked"] is False
    engrave = client.post("/inbox/orders/R-UNKNOWN/recheck", json={"stage": "engraving"}).json()
    assert engrave["action"] == "block" and engrave["blocked"] is True

    # 两次检查都落审计。
    assert client.get("/inbox/orders/R-UNKNOWN/refund-checks").json()["count"] == 2


def test_recheck_normal_allows(client):
    _ingest(client, "R-OK", "已发货")
    body = client.post("/inbox/orders/R-OK/recheck", json={"stage": "engraving"}).json()
    assert body["action"] == "allow" and body["blocked"] is False


def test_recheck_inline_status_refreshes_order(client):
    _ingest(client, "R-FRESH", "已审核")  # 入库时正常
    # 扩展重抓发现已退款 → 随 recheck 传入，先刷新再判定。
    body = client.post(
        "/inbox/orders/R-FRESH/recheck",
        json={"stage": "typesetting", "refund_status": "已退款", "operator": "op-1"},
    ).json()
    assert body["blocked"] is True
    # Order.refund_status 已被刷新。
    assert client.get("/inbox/orders/R-FRESH").json()["refund_status"] == "已退款"
    # operator 落审计。
    assert client.get("/inbox/orders/R-FRESH/refund-checks").json()["checks"][0]["operator"] == "op-1"


def test_recheck_response_carries_refund_status_and_items(client):
    """/recheck 响应必须带 refund_status(别名 queried_status) + items[]——下游 Ezcad 按这俩键读，
    缺了会把退款单误判为 NONE 放行（2026-06-19 真机踩到的契约错配）。"""
    client.post(
        "/inbox/orders",
        json={
            "schema_version": "1.0",
            "order_id": "R-SHAPE",
            "remark": "x",
            "refund_status": "已退款",
            "items": [
                {"line_index": 0, "is_target_box": True, "product_sku": "BOX"},
                {"line_index": 1, "is_target_box": False, "product_sku": "CARD"},
            ],
        },
    )
    body = client.post("/inbox/orders/R-SHAPE/recheck", json={"stage": "engraving"}).json()
    assert body["refund_status"] == "已退款"  # 关键：下游读这个键
    assert body["queried_status"] == "已退款"  # 别名一致
    assert body["blocked"] is True
    assert len(body["items"]) == 2
    assert body["items"][1]["is_target_box"] is False  # 其他商品提醒数据


def test_recheck_unknown_order_404(client):
    assert client.post("/inbox/orders/NOPE/recheck", json={"stage": "typesetting"}).status_code == 404
    assert client.get("/inbox/orders/NOPE/refund-checks").status_code == 404


def test_recheck_rejects_bad_stage(client):
    _ingest(client, "R-BADSTAGE", "已发货")
    resp = client.post("/inbox/orders/R-BADSTAGE/recheck", json={"stage": "painting"})
    assert resp.status_code == 422
