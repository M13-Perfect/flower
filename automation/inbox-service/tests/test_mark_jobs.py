from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.factory import create_app  # noqa: E402

# P0 任务租约：打标/入队现在要求有效任务授权 + 订单在范围内。每个用例先开一个宽时间窗任务，
# 订单都带落在窗内的 paid_at（否则 order_in_scope=False → 不入队/不下发）。
_PAID_AT = "2026-06-19 02:25"


@pytest.fixture(autouse=True)
def _task(client):
    resp = client.post(
        "/inbox/scrape/task/start",
        json={"flower_instance_id": "test-flower", "scrape_from": "2000-01-01 00:00"},
    )
    assert resp.status_code == 200, resp.text


def _order(order_id: str, **extra) -> dict:
    body = {"schema_version": "1.0", "order_id": order_id, "remark": "x"}
    body.setdefault("extras", {"paid_at": _PAID_AT})  # 落在任务时间窗内 → 在范围
    body.update(extra)
    return body


def test_new_order_auto_enqueues_unrecognized(client):
    assert client.post("/inbox/orders", json=_order("4090000001")).status_code == 200
    pend = client.get("/inbox/mark/pending").json()
    actions = {(j["order_id"], j["action"]) for j in pend["jobs"]}
    assert ("4090000001", "mark_unrecognized") in actions


def test_manual_upload_skips_enqueue_even_in_scope(client):
    """手动「→Flower」(?manual=1) 即便订单落在活跃任务范围内，服务端也**不入队 mark_job**
    （决策 2026-06-22：纯页面打标、服务端不留痕；打标由扩展按条件决策表纯页面完成）。
    对照 test_new_order_auto_enqueues_unrecognized：同样在范围内，不带 manual 则会入队。"""
    assert client.post("/inbox/orders?manual=1", json=_order("4090000050")).status_code == 200
    # 该单不在 pending（服务端没入队）。
    pend = {(j["order_id"], j["action"]) for j in client.get("/inbox/mark/pending").json()["jobs"]}
    assert ("4090000050", "mark_unrecognized") not in pend
    # 审计里也没有该单的任何 mark_job 行（彻底不留痕）。
    jobs = client.get("/inbox/mark/jobs", params={"order_id": "4090000050"}).json()
    assert jobs["count"] == 0
    # 但订单本身照常入库（上传成功、created=True）。
    assert client.get("/inbox/orders/4090000050").status_code == 200


def test_reingest_does_not_duplicate_job(client):
    client.post("/inbox/orders", json=_order("4090000002"))
    client.post("/inbox/orders", json=_order("4090000002", remark="y"))  # 重发
    jobs = client.get("/inbox/mark/jobs", params={"order_id": "4090000002"}).json()
    assert jobs["count"] == 1  # (order, action) 唯一，重发不重入队


def test_request_mark_done_supersedes_pending_unrecognized(client):
    client.post("/inbox/orders", json=_order("4090000003"))  # 自动入队 mark_unrecognized(pending)
    r = client.post("/inbox/mark/request", json={"order_id": "4090000003", "action": "mark_done"})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    pend = {(j["order_id"], j["action"]) for j in client.get("/inbox/mark/pending").json()["jobs"]}
    assert ("4090000003", "mark_done") in pend
    assert ("4090000003", "mark_unrecognized") not in pend  # 被 mark_done 取代、掉出 pending
    # 审计里两行都在：unrecognized=done(superseded)、done=pending
    jobs = {
        j["action"]: j["status"]
        for j in client.get("/inbox/mark/jobs", params={"order_id": "4090000003"}).json()["jobs"]
    }
    assert jobs["mark_unrecognized"] == "done" and jobs["mark_done"] == "pending"


def test_request_mark_for_missing_order_404(client):
    r = client.post("/inbox/mark/request", json={"order_id": "4099999999", "action": "mark_done"})
    assert r.status_code == 404


def test_request_unrecognized_for_missing_order_404(client):
    """手动确保打标：订单不存在 → 404（订单身份校验，扩展据此 pending=false 不误标）。"""
    r = client.post("/inbox/mark/request", json={"order_id": "4099999997", "action": "mark_unrecognized"})
    assert r.status_code == 404


def test_request_unrecognized_enqueues_pending_for_existing_order(client):
    """手动确保打标：订单存在且未处理 → 入队/复活 mark_unrecognized 为 pending（幂等）。"""
    client.post("/inbox/orders", json=_order("4090000020"))
    # 先标成 done（模拟已打标），再手动 ensure → 复活回 pending，确保扩展能再打一次（幂等，已标记会跳过）。
    client.post("/inbox/mark/result", json={"order_id": "4090000020", "action": "mark_unrecognized", "ok": True})
    r = client.post("/inbox/mark/request", json={"order_id": "4090000020", "action": "mark_unrecognized"})
    assert r.status_code == 200
    assert r.json()["status"] == "pending"


def test_request_unrecognized_skipped_when_mark_done_active(client):
    """护栏：已/将「AI已处理」的单，手动 ensure mark_unrecognized 被拦（不把已处理单打回未识别）。"""
    client.post("/inbox/orders", json=_order("4090000021"))  # 自动入队 mark_unrecognized
    client.post("/inbox/mark/request", json={"order_id": "4090000021", "action": "mark_done"})  # 生成成功 → mark_done
    r = client.post("/inbox/mark/request", json={"order_id": "4090000021", "action": "mark_unrecognized"})
    assert r.status_code == 200
    assert r.json()["status"] == "skipped_done"  # 扩展据此 pending=false → 不打标
    pend = {(j["order_id"], j["action"]) for j in client.get("/inbox/mark/pending").json()["jobs"]}
    assert ("4090000021", "mark_unrecognized") not in pend  # 没被打回 pending


def test_request_rejects_unknown_action(client):
    client.post("/inbox/orders", json=_order("4090000009"))
    r = client.post("/inbox/mark/request", json={"order_id": "4090000009", "action": "mark_bogus"})
    assert r.status_code == 422  # Literal 校验


def test_result_ok_marks_done_and_drops_from_pending(client):
    client.post("/inbox/orders", json=_order("4090000004"))
    r = client.post(
        "/inbox/mark/result",
        json={"order_id": "4090000004", "action": "mark_unrecognized", "ok": True},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "done"
    pend = client.get("/inbox/mark/pending").json()
    assert all(j["order_id"] != "4090000004" for j in pend["jobs"])  # done 掉出 pending


def test_result_failure_increments_attempts_then_fails(client):
    client.post("/inbox/orders", json=_order("4090000005"))
    for i in range(4):  # 默认 max_attempts=5：前 4 次失败仍 pending
        r = client.post(
            "/inbox/mark/result",
            json={"order_id": "4090000005", "action": "mark_unrecognized", "ok": False, "detail": "boom"},
        )
        assert r.json()["status"] == "pending"
        assert r.json()["attempts"] == i + 1
    r = client.post(
        "/inbox/mark/result",
        json={"order_id": "4090000005", "action": "mark_unrecognized", "ok": False},
    )
    assert r.json()["status"] == "failed"
    assert r.json()["attempts"] == 5
    pend = client.get("/inbox/mark/pending").json()
    assert all(j["order_id"] != "4090000005" for j in pend["jobs"])  # failed 不再被拉取


def test_result_for_missing_job_404(client):
    r = client.post(
        "/inbox/mark/result",
        json={"order_id": "4099999998", "action": "mark_done", "ok": True},
    )
    assert r.status_code == 404


def test_reenqueue_resets_failed_job_to_pending(client):
    client.post("/inbox/orders", json=_order("4090000006"))
    for _ in range(5):  # 弄成 failed
        client.post(
            "/inbox/mark/result",
            json={"order_id": "4090000006", "action": "mark_unrecognized", "ok": False},
        )
    r = client.post("/inbox/mark/request", json={"order_id": "4090000006", "action": "mark_unrecognized"})
    assert r.json()["status"] == "pending"  # 重入队复活
    assert r.json()["attempts"] == 0


def test_pending_respects_limit(client):
    for i in range(3):
        client.post("/inbox/orders", json=_order(f"409010000{i}"))
    pend = client.get("/inbox/mark/pending", params={"limit": 2}).json()
    assert pend["count"] == 2


def test_pending_carries_source_url(client):
    client.post("/inbox/orders", json=_order("4090000010", source_url="https://www.dianxiaomi.com/x"))
    pend = client.get("/inbox/mark/pending").json()
    job = next(j for j in pend["jobs"] if j["order_id"] == "4090000010")
    assert job["source_url"] == "https://www.dianxiaomi.com/x"


def test_enqueue_unrecognized_can_be_disabled(tmp_path):
    settings = Settings(
        inbox_dir=tmp_path / "inbox",
        reports_dir=tmp_path / "reports",
        batches_dir=tmp_path / "batches",
        db_path=tmp_path / "inbox.db",
        sandbox_dir=tmp_path / "sandbox",
        mark_enqueue_unrecognized=False,
    )
    with TestClient(create_app(settings)) as c:
        c.post(
            "/inbox/scrape/task/start",
            json={"flower_instance_id": "test-flower", "scrape_from": "2000-01-01 00:00"},
        )
        c.post("/inbox/orders", json=_order("4090000011"))
        # 关了入队开关：即便有任务授权且订单在范围内，也不自动入队（查审计端点确认无任务）。
        assert c.get("/inbox/mark/jobs", params={"order_id": "4090000011"}).json()["count"] == 0


def test_reingest_after_mark_done_does_not_restamp_unrecognized(client):
    client.post("/inbox/orders", json=_order("4090000013"))  # 自动入队 mark_unrecognized(pending)
    client.post("/inbox/mark/request", json={"order_id": "4090000013", "action": "mark_done"})  # supersede unrec→done
    client.post("/inbox/mark/result", json={"order_id": "4090000013", "action": "mark_done", "ok": True})  # 打标成功
    # 该单被再次抓取上传（dedup）→ 标准2：已有 active mark_done，不把 mark_unrecognized 重置回 pending。
    client.post("/inbox/orders", json=_order("4090000013", remark="z"))
    jobs = {
        j["action"]: j["status"]
        for j in client.get("/inbox/mark/jobs", params={"order_id": "4090000013"}).json()["jobs"]
    }
    assert jobs["mark_done"] == "done"
    assert jobs["mark_unrecognized"] == "done"  # 仍是 superseded 的 done，没被打回 pending
    pend = {(j["order_id"], j["action"]) for j in client.get("/inbox/mark/pending").json()["jobs"]}
    assert ("4090000013", "mark_unrecognized") not in pend


def test_list_orders_includes_mark_jobs_summary(client):
    client.post("/inbox/orders", json=_order("4090000014"))
    orders = client.get("/inbox/orders").json()["orders"]
    o = next(o for o in orders if o["order_id"] == "4090000014")
    actions = {j["action"]: j["status"] for j in o.get("mark_jobs", [])}
    assert actions.get("mark_unrecognized") == "pending"  # 标签状态列数据源


def test_reingest_restamps_unrecognized_when_no_mark_done(client):
    client.post("/inbox/orders", json=_order("4090000015"))
    # 把 mark_unrecognized 标成 done（模拟已打标），再次上传 → 无 mark_done，标准2 会重新入队（回 pending）确保标记在
    client.post("/inbox/mark/result", json={"order_id": "4090000015", "action": "mark_unrecognized", "ok": True})
    client.post("/inbox/orders", json=_order("4090000015", remark="z2"))
    pend = {(j["order_id"], j["action"]) for j in client.get("/inbox/mark/pending").json()["jobs"]}
    assert ("4090000015", "mark_unrecognized") in pend  # 重新上传 → 再确保未识别（幂等，扩展会跳过已标记）


def test_recheck_response_carries_ai_processed(client):
    client.post("/inbox/orders", json=_order("4090000016"))
    # 未生成（无 mark_done）→ ai_processed False（EzCad 会软警告）
    r1 = client.post("/inbox/orders/4090000016/recheck", json={"stage": "engraving"})
    assert r1.status_code == 200 and r1.json()["ai_processed"] is False
    # flower 生成 → 入队 mark_done → ai_processed True（EzCad 放行不警告）
    client.post("/inbox/mark/request", json={"order_id": "4090000016", "action": "mark_done"})
    r2 = client.post("/inbox/orders/4090000016/recheck", json={"stage": "engraving"})
    assert r2.json()["ai_processed"] is True


def test_delete_order_soft_keeps_mark_jobs(client):
    """软删（2026-06-22）：删单不再级联清 mark_jobs——审计行保留，但订单对外 404。"""
    client.post("/inbox/orders", json=_order("4090000012"))
    assert client.get("/inbox/mark/jobs", params={"order_id": "4090000012"}).json()["count"] == 1
    client.delete("/inbox/orders/4090000012")
    # 软删：mark_jobs 行不删（审计/复活需要），订单本身对外 404。
    assert client.get("/inbox/mark/jobs", params={"order_id": "4090000012"}).json()["count"] == 1
    assert client.get("/inbox/orders/4090000012").status_code == 404
