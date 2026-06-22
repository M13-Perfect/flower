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


def test_identical_repost_is_noop_and_does_not_rewrite_file(client, settings):
    """检测 1：内容逐字节一致 → no-op，不覆盖、不重写收件夹文件（避免重触发 flower）。"""
    payload = {"schema_version": "1.0", "order_id": "ORD-2", "remark": "same"}
    first = client.post("/inbox/orders", json=payload).json()
    assert first["dedup"] is False
    assert first["unchanged"] is False

    file_path = next(settings.inbox_dir.glob("*.json"))
    mtime_before = file_path.stat().st_mtime_ns

    second = client.post("/inbox/orders", json=payload).json()
    assert second["dedup"] is True
    assert second["unchanged"] is True  # 内容一致 → no-op
    # 文件没有被重写（mtime 不变），仍只有一个文件。
    assert file_path.stat().st_mtime_ns == mtime_before
    assert len(list(settings.inbox_dir.glob("*.json"))) == 1


def test_relist_without_refund_status_keeps_known_status(client, settings):
    """检测 2：列表页重抓无退款列（refund_status=None）不能抹掉已知「已退款」。"""
    client.post(
        "/inbox/orders",
        json={"schema_version": "1.0", "order_id": "ORD-3", "remark": "x", "refund_status": "已退款"},
    )
    assert client.get("/inbox/orders/ORD-3").json()["refund_status"] == "已退款"

    # 重新入库：备注变了（内容不一致，会走覆盖分支），但不带 refund_status。
    second = client.post(
        "/inbox/orders",
        json={"schema_version": "1.0", "order_id": "ORD-3", "remark": "x changed"},
    ).json()
    assert second["dedup"] is True
    assert second["unchanged"] is False  # 内容有变（备注），不是 no-op
    # 退款状态被保留，没有被 None 抹掉。
    assert client.get("/inbox/orders/ORD-3").json()["refund_status"] == "已退款"


def test_created_flag_new_repeat_and_revive(client):
    """created 位（手动条件打标判 CREATED_NEW 的依据，2026-06-22）：
    - 全新单 → created=True、dedup=False；
    - 幂等重发 → created=False、dedup=True（已存在的活跃单，不打标）；
    - 软删后重新导入复活 → created=True（视为新单，打标），但 dedup 仍为 True（语义不变）。
    """
    payload = {"schema_version": "1.0", "order_id": "CRT-1", "remark": "x"}

    first = client.post("/inbox/orders", json=payload).json()
    assert first["created"] is True and first["dedup"] is False

    second = client.post(
        "/inbox/orders",
        json={"schema_version": "1.0", "order_id": "CRT-1", "remark": "x changed"},
    ).json()
    assert second["created"] is False and second["dedup"] is True

    client.delete("/inbox/orders/CRT-1")  # 软删
    revived = client.post("/inbox/orders", json=payload).json()
    assert revived["created"] is True  # 复活 → 当新单 → 手动据此打标
    assert revived["dedup"] is True  # dedup 含软删，语义不变


def test_relist_with_new_refund_status_overwrites(client):
    """检测 2 不挡正常更新：带非空 refund_status 时照常覆盖。"""
    client.post(
        "/inbox/orders",
        json={"schema_version": "1.0", "order_id": "ORD-4", "remark": "x", "refund_status": "已审核"},
    )
    client.post(
        "/inbox/orders",
        json={"schema_version": "1.0", "order_id": "ORD-4", "remark": "x", "refund_status": "已退款"},
    )
    assert client.get("/inbox/orders/ORD-4").json()["refund_status"] == "已退款"
