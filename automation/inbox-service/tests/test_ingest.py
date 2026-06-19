from __future__ import annotations

import json


def test_ingest_writes_file_and_persists(client, settings):
    resp = client.post(
        "/inbox/orders",
        json={"schema_version": "1.0", "order_id": "ORD-1", "remark": "name Amy May font 1 flower 2"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["order_id"] == "ORD-1"
    assert body["status"] == "WRITTEN_TO_INBOX"
    assert body["dedup"] is False

    # 文件原子写入收件夹，且顶层有 remark（Flower 导入器零改动即可读）。
    written = settings.inbox_dir / "ORD-1.json"
    assert written.is_file()
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["remark"] == "name Amy May font 1 flower 2"
    assert data["order_id"] == "ORD-1"
    # 无残留临时文件。
    assert not list(settings.inbox_dir.glob(".*"))

    # 状态可查询。
    status = client.get("/inbox/orders/ORD-1").json()
    assert status["status"] == "WRITTEN_TO_INBOX"
    assert status["inbox_path"].endswith("ORD-1.json")


def test_ingest_rejects_missing_remark(client):
    resp = client.post("/inbox/orders", json={"schema_version": "1.0", "order_id": "ORD-2"})
    assert resp.status_code == 422


def test_ingest_rejects_bad_order_id(client):
    resp = client.post("/inbox/orders", json={"schema_version": "1.0", "order_id": "../evil", "remark": "x"})
    assert resp.status_code == 422


def test_ingest_rejects_schema_version_mismatch(client):
    resp = client.post("/inbox/orders", json={"schema_version": "9.9", "order_id": "ORD-3", "remark": "x"})
    assert resp.status_code == 422


def test_ingest_forbids_extra_fields(client):
    resp = client.post(
        "/inbox/orders",
        json={"schema_version": "1.0", "order_id": "ORD-4", "remark": "x", "bogus": 1},
    )
    assert resp.status_code == 422


def test_healthz_reports_paths(client, settings):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["inbox_dir"] == str(settings.inbox_dir)
    assert body["schema_version"] == "1.0"
