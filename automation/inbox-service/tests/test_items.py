from __future__ import annotations

import json


def _order_with_items(order_id: str = "ORD-MULTI") -> dict:
    """一单两行：一个目标盒子（×2）+ 一个其他商品（配货提醒）。"""
    return {
        "schema_version": "1.0",
        "order_id": order_id,
        "remark": "two boxes",
        "refund_status": "normal",
        "items": [
            {
                "line_index": 0,
                "is_target_box": True,
                "quantity": 2,
                "personalization_raw": "Amy / Soph",
                "product_sku": "BOX-A",
            },
            {
                "line_index": 1,
                "is_target_box": False,
                "quantity": 1,
                "product_sku": "GIFT-WRAP",
                "extras": {"image": "http://x/y.png"},
            },
        ],
    }


def test_ingest_persists_items_and_refund_status(client, settings):
    resp = client.post("/inbox/orders", json=_order_with_items())
    assert resp.status_code == 200

    # 落盘文件携带 items + refund_status（顶层 remark 仍在，Flower 导入器零改动）。
    data = json.loads((settings.inbox_dir / "ORD-MULTI.json").read_text(encoding="utf-8"))
    assert data["remark"] == "two boxes"
    assert data["refund_status"] == "normal"
    assert len(data["items"]) == 2
    assert data["items"][0]["is_target_box"] is True

    # 查询返回结构化 items（按 line_index 升序），其他商品的 extras 兜底字段保留。
    status = client.get("/inbox/orders/ORD-MULTI").json()
    assert status["refund_status"] == "normal"
    assert [i["line_index"] for i in status["items"]] == [0, 1]
    assert status["items"][1]["is_target_box"] is False
    assert status["items"][1]["extras"]["image"] == "http://x/y.png"


def test_resend_replaces_items(client):
    client.post("/inbox/orders", json=_order_with_items())
    payload = _order_with_items()
    payload["items"] = [
        {"line_index": 0, "is_target_box": True, "quantity": 1, "personalization_raw": "Solo"}
    ]
    resp = client.post("/inbox/orders", json=payload)
    assert resp.json()["dedup"] is True

    # 旧两行被整树替换为新一行，无残留。
    status = client.get("/inbox/orders/ORD-MULTI").json()
    assert len(status["items"]) == 1
    assert status["items"][0]["personalization_raw"] == "Solo"


def test_legacy_order_without_items_still_works(client):
    resp = client.post(
        "/inbox/orders",
        json={"schema_version": "1.0", "order_id": "ORD-LEGACY", "remark": "hi"},
    )
    assert resp.status_code == 200
    status = client.get("/inbox/orders/ORD-LEGACY").json()
    assert status["items"] == []
    assert status["refund_status"] is None
