from __future__ import annotations

import json


def test_repeat_post_dedups_and_keeps_single_row(client, settings):
    first = client.post(
        "/inbox/orders",
        json={"schema_version": "1.0", "order_id": "ORD-1", "remark": "first"},
    ).json()
    assert first["dedup"] is False

    second = client.post(
        "/inbox/orders",
        json={"schema_version": "1.0", "order_id": "ORD-1", "remark": "second edit"},
    ).json()
    assert second["dedup"] is True

    # 只有一行，备注更新为最新。
    listing = client.get("/inbox/orders").json()
    assert listing["count"] == 1
    status = client.get("/inbox/orders/ORD-1").json()
    assert status["remark"] == "second edit"

    # 收件夹里只有一个文件，内容是最新备注。
    files = list(settings.inbox_dir.glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["remark"] == "second edit"
