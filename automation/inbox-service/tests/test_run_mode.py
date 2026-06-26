from __future__ import annotations

import json


def _order(order_id: str) -> dict:
    return {"schema_version": "1.0", "order_id": order_id, "remark": "x", "refund_status": "已审核"}


# ── 默认模式 + 切换 ──────────────────────────────────────────────────


def test_default_mode_is_production_retry(client, settings):
    body = client.get("/inbox/run-mode").json()
    assert body["mode"] == "production_retry"
    assert body["inbox_dir"] == str(settings.inbox_dir)


def test_put_mode_rejects_unknown(client):
    assert client.put("/inbox/run-mode", json={"mode": "wat"}).status_code == 422


# ── 生产模式：写生产收件夹 ───────────────────────────────────────────


def test_production_writes_to_production_inbox(client, settings):
    client.post("/inbox/orders", json=_order("PRD1"))
    assert (settings.inbox_dir / "PRD1.json").exists()
    # 没碰 sandbox。
    assert not (settings.sandbox_inbox_dir / "PRD1.json").exists()


# ── 测试重置：写 sandbox、绝不碰生产 outputs/ ────────────────────────


def test_test_reset_writes_sandbox_never_production(client, settings):
    put = client.put("/inbox/run-mode", json={"mode": "test_reset"}).json()
    assert put["mode"] == "test_reset"
    assert put["inbox_dir"] == str(settings.sandbox_inbox_dir)

    client.post("/inbox/orders", json=_order("T1"))
    # 落在 sandbox，生产收件夹一个都没有。
    assert (settings.sandbox_inbox_dir / "T1.json").exists()
    assert not (settings.inbox_dir / "T1.json").exists()
    assert list(settings.inbox_dir.glob("*.json")) == [] if settings.inbox_dir.exists() else True


def test_test_reset_clears_sandbox(client, settings):
    # 先在 sandbox 留一单
    client.put("/inbox/run-mode", json={"mode": "test_reset"})
    client.post("/inbox/orders", json=_order("OLD"))
    assert (settings.sandbox_inbox_dir / "OLD.json").exists()

    # 再次进 test_reset 并清旧 → 旧文件被清
    resp = client.put("/inbox/run-mode", json={"mode": "test_reset", "reset_sandbox": True}).json()
    assert resp["sandbox_cleared_files"] >= 1
    assert not (settings.sandbox_inbox_dir / "OLD.json").exists()


def test_switch_back_to_production_uses_production_dir(client, settings):
    client.put("/inbox/run-mode", json={"mode": "test_reset"})
    client.post("/inbox/orders", json=_order("S1"))
    client.put("/inbox/run-mode", json={"mode": "production_retry"})
    client.post("/inbox/orders", json=_order("S2"))
    assert (settings.sandbox_inbox_dir / "S1.json").exists()
    assert (settings.inbox_dir / "S2.json").exists()
    assert not (settings.inbox_dir / "S1.json").exists()  # 测试单没漏进生产


# ── 批量 xlsx：不覆盖（同名追加 -vN）─────────────────────────────────


def test_batch_export_does_not_overwrite_same_second(client, settings, monkeypatch):
    from datetime import datetime

    import app.batch_exporter as be

    # 冻结到同一秒；同一批待导出连续导两次（QUEUED 仍可导）→ 同名 stamp+count → 第二次必须不覆盖、带 -vN。
    fixed = datetime(2026, 6, 19, 12, 0, 0)
    monkeypatch.setattr(be, "datetime", type("D", (), {"now": staticmethod(lambda: fixed)}))

    client.post("/inbox/orders", json=_order("B1"))
    p1 = client.post("/inbox/batch/export").json()["path"]
    p2 = client.post("/inbox/batch/export").json()["path"]  # 同批、同秒再导
    assert p1 and p2 and p1 != p2
    assert "v2" in p2  # 同秒同名第二次带版本后缀，不覆盖 p1
    files = list(settings.batches_dir.glob("pooled-*.xlsx"))
    assert len(files) == 2


def test_test_reset_export_goes_to_sandbox_batches(client, settings):
    client.put("/inbox/run-mode", json={"mode": "test_reset"})
    client.post("/inbox/orders", json=_order("BX"))
    path = client.post("/inbox/batch/export").json()["path"]
    assert path is not None
    assert str(settings.sandbox_batches_dir) in path
    # 生产批次目录不产出。
    assert not (settings.batches_dir.exists() and list(settings.batches_dir.glob("*.xlsx")))


def test_ingest_response_has_sandbox_path_in_test_reset(client, settings):
    client.put("/inbox/run-mode", json={"mode": "test_reset"})
    resp = client.post("/inbox/orders", json=_order("RP1")).json()
    assert str(settings.sandbox_inbox_dir) in resp["inbox_path"]
