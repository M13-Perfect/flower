from __future__ import annotations

from app.db import session_scope
from app.models import (
    TEMPLATE_BINDING_BOUND,
    TEMPLATE_BINDING_UNBOUND,
    Order,
)
from app.repository import bind_order_template, get_order
from app.schemas import OrderPayload
from app.repository import upsert_order


def _ingest(client, order_id: str, remark: str = "x"):
    return client.post(
        "/inbox/orders",
        json={"schema_version": "1.0", "order_id": order_id, "remark": remark},
    ).json()


def test_fresh_order_defaults_unbound(client):
    """新单默认 template_binding_status=unbound，template_* 全 None（走真实入库 + to_dict）。"""
    _ingest(client, "TPL-1")
    order = client.get("/inbox/orders/TPL-1").json()
    assert order["template_binding_status"] == TEMPLATE_BINDING_UNBOUND
    assert order["template_id"] is None
    assert order["template_version"] is None
    assert order["template_sha256"] is None


def test_to_dict_round_trips_template_fields(app):
    """直接走 ORM/repository：绑定后字段持久化，to_dict 原样带回。"""
    factory = app.state.session_factory
    with session_scope(factory) as session:
        order = upsert_order(
            session,
            OrderPayload(schema_version="1.0", order_id="TPL-RT", remark="hi"),
            raw_json="{}",
        )[0]
        order.template_id = "ring-classic"
        order.template_version = "v3"
        order.template_sha256 = "a" * 64
        order.template_binding_status = TEMPLATE_BINDING_BOUND
    with session_scope(factory) as session:
        data = get_order(session, "TPL-RT").to_dict()
    assert data["template_id"] == "ring-classic"
    assert data["template_version"] == "v3"
    assert data["template_sha256"] == "a" * 64
    assert data["template_binding_status"] == TEMPLATE_BINDING_BOUND


def test_bind_order_template_sets_fields_and_bound_status(app):
    """bind_order_template 通过真实持久化路径设四字段 + status=bound。"""
    factory = app.state.session_factory
    with session_scope(factory) as session:
        session.add(Order(order_id="TPL-2", remark="x", raw_json="{}"))
    with session_scope(factory) as session:
        order = bind_order_template(
            session,
            "TPL-2",
            template_id="ring-classic",
            template_version="v1",
            template_sha256="b" * 64,
        )
        assert order is not None
        assert order.template_binding_status == TEMPLATE_BINDING_BOUND
    with session_scope(factory) as session:
        order = get_order(session, "TPL-2")
        assert order.template_id == "ring-classic"
        assert order.template_version == "v1"
        assert order.template_sha256 == "b" * 64
        assert order.template_binding_status == TEMPLATE_BINDING_BOUND


def test_bind_order_template_missing_returns_none(app):
    factory = app.state.session_factory
    with session_scope(factory) as session:
        result = bind_order_template(
            session,
            "NOPE",
            template_id="t",
            template_version="v",
            template_sha256="c" * 64,
        )
        assert result is None


def test_reimport_preserves_existing_binding(app):
    """扩展重抓重导入（upsert，报文不带 template_*）必须保留已有绑定，不抹成 None。"""
    factory = app.state.session_factory
    with session_scope(factory) as session:
        session.add(Order(order_id="TPL-3", remark="orig", raw_json="{}"))
    with session_scope(factory) as session:
        bind_order_template(
            session,
            "TPL-3",
            template_id="guitar-pick",
            template_version="v2",
            template_sha256="d" * 64,
        )
    # 重导入：内容变了（remark），走覆盖分支，但报文没有 template_* 字段。
    with session_scope(factory) as session:
        upsert_order(
            session,
            OrderPayload(schema_version="1.0", order_id="TPL-3", remark="re-scraped"),
            raw_json='{"changed": true}',
        )
    with session_scope(factory) as session:
        order = get_order(session, "TPL-3")
        assert order.remark == "re-scraped"  # 重导入确实覆盖了 remark
        assert order.template_id == "guitar-pick"  # 绑定被保留
        assert order.template_version == "v2"
        assert order.template_sha256 == "d" * 64
        assert order.template_binding_status == TEMPLATE_BINDING_BOUND


def test_bind_endpoint_end_to_end(client):
    """绑定端点端到端：入库 → POST 绑定 → 返回更新单 → GET 仍带绑定。"""
    _ingest(client, "TPL-4")
    resp = client.post(
        "/inbox/orders/TPL-4/template-binding",
        json={
            "template_id": "ring-classic",
            "template_version": "v5",
            "template_sha256": "e" * 64,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["template_id"] == "ring-classic"
    assert body["template_version"] == "v5"
    assert body["template_sha256"] == "e" * 64
    assert body["template_binding_status"] == TEMPLATE_BINDING_BOUND

    # 持久化：GET 仍带绑定。
    got = client.get("/inbox/orders/TPL-4").json()
    assert got["template_id"] == "ring-classic"
    assert got["template_binding_status"] == TEMPLATE_BINDING_BOUND


def test_bind_endpoint_404_for_missing_order(client):
    resp = client.post(
        "/inbox/orders/GHOST/template-binding",
        json={"template_id": "t", "template_version": "v", "template_sha256": "f" * 64},
    )
    assert resp.status_code == 404
