from __future__ import annotations

import json

# D-1（真机 2026-06-19 测出）：列表页无定制备注的标品单 remark 为空，旧 min_length=1 → 422 拒收、
# 且因不在库被每轮 diff 当 new 反复重发。修法（用户拍板「进系统、改契约」）：remark 改可选、可空串，
# 数据由 items[] 承载。D-2：纯空白 remark 归一成空串（不再当有效备注）。


def _bare(order_id: str, **over) -> dict:
    payload = {"schema_version": "1.0", "order_id": order_id}
    payload.update(over)
    return payload


def test_empty_remark_with_items_is_accepted(client, settings):
    """空 remark + 有行项目（标品单）→ 200 入库，落盘 remark 为空串、items 保留。"""
    resp = client.post(
        "/inbox/orders",
        json=_bare(
            "ORD-NOREMARK",
            remark="",
            refund_status="已审核",
            items=[{"line_index": 0, "product_sku": "SKU-1", "quantity": 1}],
        ),
    )
    assert resp.status_code == 200

    data = json.loads((settings.inbox_dir / "ORD-NOREMARK.json").read_text(encoding="utf-8"))
    assert data["remark"] == ""
    assert len(data["items"]) == 1

    status = client.get("/inbox/orders/ORD-NOREMARK").json()
    assert status["remark"] == ""
    assert status["refund_status"] == "已审核"


def test_remark_omitted_entirely_defaults_to_empty(client):
    """完全不带 remark 字段 → 默认空串（契约已去掉 remark 必填）。"""
    resp = client.post("/inbox/orders", json=_bare("ORD-NOFIELD"))
    assert resp.status_code == 200
    assert client.get("/inbox/orders/ORD-NOFIELD").json()["remark"] == ""


def test_whitespace_only_remark_normalized_to_empty(client):
    """D-2：纯空白 remark 不再当有效备注，strip 成空串。"""
    resp = client.post("/inbox/orders", json=_bare("ORD-WS", remark="   "))
    assert resp.status_code == 200
    assert client.get("/inbox/orders/ORD-WS").json()["remark"] == ""


def test_remark_is_trimmed(client):
    """带内容的 remark 两端空白被 strip。"""
    resp = client.post("/inbox/orders", json=_bare("ORD-TRIM", remark="  hello  "))
    assert resp.status_code == 200
    assert client.get("/inbox/orders/ORD-TRIM").json()["remark"] == "hello"


def test_normal_remark_still_works(client):
    """回归：正常 remark 照常入库（老路径零影响）。"""
    resp = client.post("/inbox/orders", json=_bare("ORD-OK", remark="Jun - Honeysuckle / Esther"))
    assert resp.status_code == 200
    assert client.get("/inbox/orders/ORD-OK").json()["remark"] == "Jun - Honeysuckle / Esther"
