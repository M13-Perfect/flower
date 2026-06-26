from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.factory import create_app  # noqa: E402
from app.models import AI_STATUS_LOCKED, AI_STATUS_RECOGNIZED  # noqa: E402
from app.repository import reconcile_ai_status, set_ai_status  # noqa: E402

# AI 对账端点受 ACTION_MARK 授权 gate（与打标同闸）：每个用例先开一个宽时间窗采集任务。
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
    body.setdefault("extras", {"paid_at": _PAID_AT})
    body.update(extra)
    return body


def _reconcile(client, order_id: str, *, ai_done: bool, ai_unrecognized: bool = False) -> dict:
    r = client.post(
        "/inbox/ai/reconcile",
        json={"order_id": order_id, "ai_done": ai_done, "ai_unrecognized": ai_unrecognized},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _ai_status(client, order_id: str):
    r = client.get(f"/inbox/orders/{order_id}")
    if r.status_code != 200:
        return None
    return r.json().get("ai_status")


# ── 不存在 → 原子创建 ──────────────────────────────────────────────


def test_absent_no_tag_creates_pending(client):
    """订单不存在、页面无 AI 标记 → 原子创建 pending，desired=pending（确保唯一「AI未识别」）。"""
    res = _reconcile(client, "4100000001", ai_done=False)
    assert res["desired_tag"] == "pending"
    assert res["created"] is True
    assert res["conflict"] is False
    assert res["ai_status"] == "pending"
    assert _ai_status(client, "4100000001") == "pending"  # 已落库


def test_absent_with_done_tag_creates_conflict(client):
    """订单不存在、页面已带「AI已处理」→ 数据冲突进复核：建 conflict，desired=none（不直接改为未识别）。"""
    res = _reconcile(client, "4100000002", ai_done=True)
    assert res["desired_tag"] == "none"
    assert res["conflict"] is True
    assert res["created"] is True
    assert res["ai_status"] == "conflict"
    assert _ai_status(client, "4100000002") == "conflict"


def test_reconcile_is_idempotent_create(client):
    """同一新单连调两次：第一次 created=True，第二次 created=False，都保持 pending。"""
    first = _reconcile(client, "4100000003", ai_done=False)
    second = _reconcile(client, "4100000003", ai_done=False)
    assert first["created"] is True and second["created"] is False
    assert first["desired_tag"] == second["desired_tag"] == "pending"


# ── 已存在 → 以权威态同步 ──────────────────────────────────────────


def test_existing_pending_returns_pending(client):
    client.post("/inbox/orders", json=_order("4100000010"))  # 入库即 pending
    res = _reconcile(client, "4100000010", ai_done=False)
    assert res["desired_tag"] == "pending"
    assert res["conflict"] is False and res["created"] is False


def test_existing_pending_but_page_done_is_conflict(client):
    """边缘 A：库里 pending 但页面已是「AI已处理」→ 判 conflict（不自动降级），desired=none。"""
    client.post("/inbox/orders", json=_order("4100000011"))
    res = _reconcile(client, "4100000011", ai_done=True)
    assert res["desired_tag"] == "none"
    assert res["conflict"] is True
    assert _ai_status(client, "4100000011") == "conflict"


def test_existing_recognized_never_downgrades(client):
    """生成完=recognized：即便页面显示「AI未识别」，desired 仍 recognized（绝不降级回未识别）。"""
    client.post("/inbox/orders", json=_order("4100000012"))
    client.post("/inbox/mark/request", json={"order_id": "4100000012", "action": "mark_done"})
    assert _ai_status(client, "4100000012") == "recognized"  # mark_done 同步置权威态
    res = _reconcile(client, "4100000012", ai_done=False, ai_unrecognized=True)
    assert res["desired_tag"] == "recognized"
    assert res["conflict"] is False
    assert _ai_status(client, "4100000012") == "recognized"  # 状态不变（不被降级）


def test_existing_conflict_is_frozen(client):
    """复核中：desired=none，扩展不动标签；权威态保持 conflict 等人工裁决。"""
    _reconcile(client, "4100000013", ai_done=True)  # 建成 conflict
    res = _reconcile(client, "4100000013", ai_done=False)  # 即便页面现在无 done
    assert res["desired_tag"] == "none"
    assert res["conflict"] is True
    assert _ai_status(client, "4100000013") == "conflict"  # 不被自动解冲突


# ── 不变式：AI已处理 与 待识别 不共存（由 desired_tag 驱动扩展，见扩展端测试）──


def test_invariant_never_both_via_desired(client):
    """权威态决定 desired_tag，二者互斥：recognized→recognized、pending→pending，不会同时要求两个标记。"""
    client.post("/inbox/orders", json=_order("4100000014"))
    assert _reconcile(client, "4100000014", ai_done=False)["desired_tag"] == "pending"
    client.post("/inbox/mark/request", json={"order_id": "4100000014", "action": "mark_done"})
    assert _reconcile(client, "4100000014", ai_done=True)["desired_tag"] == "recognized"


# ── 软删 → 视为不存在 → 复活 ───────────────────────────────────────


def test_soft_deleted_order_is_frozen_not_revived(client):
    """软删单：reconcile 不自动复活、不动标签（desired=none）；恢复需重新上传。"""
    client.post("/inbox/orders", json=_order("4100000020"))
    client.delete("/inbox/orders/4100000020")
    assert client.get("/inbox/orders/4100000020").status_code == 404  # 软删后对外不存在
    res = _reconcile(client, "4100000020", ai_done=False)
    assert res["desired_tag"] == "none"  # 冻结，不动标签
    assert res["created"] is False  # 不复活
    assert client.get("/inbox/orders/4100000020").status_code == 404  # 仍是软删态


def test_resolved_via_reupload_after_soft_delete(client):
    """软删后重新上传（upsert）复活 → 之后 reconcile 正常按 pending 同步（验证恢复路径）。"""
    client.post("/inbox/orders", json=_order("4100000021"))
    client.delete("/inbox/orders/4100000021")
    client.post("/inbox/orders", json=_order("4100000021", remark="z"))  # 重新上传 → upsert 复活
    res = _reconcile(client, "4100000021", ai_done=False)
    assert res["desired_tag"] == "pending"
    assert res["conflict"] is False


# ── 授权 / 总开关 gate（fail-closed）────────────────────────────────


def test_unauthorized_is_noop_and_creates_nothing(tmp_path):
    """无任务授权 → desired=none、authorized=false，且**不创建桩单**（防任意翻页造数据）。"""
    # 用独立 db 文件，避免与 autouse 的 _task 夹具（同 tmp_path/inbox.db）撞库——本用例要的就是「无任务」。
    settings = Settings(
        inbox_dir=tmp_path / "noauth_inbox",
        reports_dir=tmp_path / "noauth_reports",
        batches_dir=tmp_path / "noauth_batches",
        db_path=tmp_path / "noauth.db",
        sandbox_dir=tmp_path / "noauth_sandbox",
    )
    with TestClient(create_app(settings)) as c:  # 没开任务
        res = c.post("/inbox/ai/reconcile", json={"order_id": "4100000030", "ai_done": False})
        assert res.status_code == 200
        body = res.json()
        assert body["desired_tag"] == "none" and body["authorized"] is False
        assert c.get("/inbox/orders/4100000030").status_code == 404  # 未创建


def test_disabled_switch_is_noop(tmp_path):
    """总开关 ai_reconcile_enabled=False → 即便有授权也 no-op（不创建、desired=none）。"""
    # 独立 db 文件，避免与 autouse _task 夹具撞库。
    settings = Settings(
        inbox_dir=tmp_path / "disabled_inbox",
        reports_dir=tmp_path / "disabled_reports",
        batches_dir=tmp_path / "disabled_batches",
        db_path=tmp_path / "disabled.db",
        sandbox_dir=tmp_path / "disabled_sandbox",
        ai_reconcile_enabled=False,
    )
    with TestClient(create_app(settings)) as c:
        c.post(
            "/inbox/scrape/task/start",
            json={"flower_instance_id": "test-flower", "scrape_from": "2000-01-01 00:00"},
        )
        res = c.post("/inbox/ai/reconcile", json={"order_id": "4100000031", "ai_done": False})
        assert res.json()["desired_tag"] == "none"
        assert c.get("/inbox/orders/4100000031").status_code == 404


def test_validation_rejects_missing_ai_done(client):
    r = client.post("/inbox/ai/reconcile", json={"order_id": "4100000040"})
    assert r.status_code == 422  # ai_done 必填


# ── 仓库层：locked 保留态 + 人工裁决解冲突（无 HTTP setter，直接测仓库函数）──


def test_locked_status_behaves_like_recognized(app):
    """locked（人工锁定保留态）同样不降级：desired=recognized。"""
    factory = app.state.session_factory
    with session_scope(factory) as session:
        reconcile_ai_status(session, "4100000050", page_ai_done=False, page_ai_unrecognized=False)
        set_ai_status(session, "4100000050", AI_STATUS_LOCKED)
    with session_scope(factory) as session:
        res = reconcile_ai_status(session, "4100000050", page_ai_done=False, page_ai_unrecognized=True)
    assert res["desired_tag"] == "recognized"
    assert res["ai_status"] == AI_STATUS_LOCKED


def test_manual_resolve_conflict_to_recognized(app):
    """人工裁决：把 conflict 单 set 成 recognized 后，对账恢复正常同步（desired=recognized）。"""
    factory = app.state.session_factory
    with session_scope(factory) as session:
        reconcile_ai_status(session, "4100000051", page_ai_done=True, page_ai_unrecognized=False)  # → conflict
    with session_scope(factory) as session:
        set_ai_status(session, "4100000051", AI_STATUS_RECOGNIZED)
    with session_scope(factory) as session:
        res = reconcile_ai_status(session, "4100000051", page_ai_done=False, page_ai_unrecognized=False)
    assert res["desired_tag"] == "recognized" and res["conflict"] is False


def test_orders_list_includes_ai_status(client):
    client.post("/inbox/orders", json=_order("4100000060"))
    orders = client.get("/inbox/orders").json()["orders"]
    o = next(o for o in orders if o["order_id"] == "4100000060")
    assert o["ai_status"] == "pending"  # 配置端订单表数据源（含「复核」筛选）
