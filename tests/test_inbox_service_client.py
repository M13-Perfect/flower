"""flower → inbox-service HTTP 客户端测试（不打真网络，注入 fake transport）。

覆盖：探活失败回 None、scrape/control 的 GET/PUT URL 与方法、PUT 部分更新只发显式字段。
"""

from __future__ import annotations

from urllib import error

import inbox_service_client as client


def test_health_returns_none_when_unreachable():
    def boom(url, method, payload, timeout):
        raise error.URLError("connection refused")

    assert client.health("http://127.0.0.1:8770", http_request=boom) is None


def test_health_returns_payload_on_ok():
    calls: dict = {}

    def fake(url, method, payload, timeout):
        calls.update(url=url, method=method)
        return {"status": "ok", "service": "flower-inbox"}

    out = client.health("http://127.0.0.1:8770/", http_request=fake)
    assert out["status"] == "ok"
    assert calls["url"] == "http://127.0.0.1:8770/healthz"  # 尾斜杠被规整
    assert calls["method"] == "GET"


def test_get_scrape_control_hits_right_endpoint():
    seen: dict = {}

    def fake(url, method, payload, timeout):
        seen.update(url=url, method=method, payload=payload)
        return {"enabled": False, "interval_seconds": 300, "scrape_from": None}

    out = client.get_scrape_control("http://h:8770", http_request=fake)
    assert seen["url"] == "http://h:8770/inbox/scrape/control"
    assert seen["method"] == "GET" and seen["payload"] is None
    assert out["interval_seconds"] == 300


def test_list_orders_hits_right_endpoint():
    seen: dict = {}

    def fake(url, method, payload, timeout):
        seen.update(url=url, method=method, payload=payload)
        return {"orders": [{"order_id": "DX001", "status": "RECEIVED"}], "count": 1}

    out = client.list_orders("http://h:8770", http_request=fake)
    assert seen["url"] == "http://h:8770/inbox/orders"
    assert seen["method"] == "GET" and seen["payload"] is None
    assert out["count"] == 1 and out["orders"][0]["order_id"] == "DX001"


def test_fetch_next_pending_order_returns_order_dict():
    # GET /inbox/orders/next → {"order": {...}}：取出内层 order。
    seen: dict = {}

    def fake(url, method, payload, timeout):
        seen.update(url=url, method=method, payload=payload)
        return {"order": {"order_id": "DX-OLDEST", "remark": "Jun - Rose", "ai_status": "pending"}}

    out = client.fetch_next_pending_order("http://h:8770", http_request=fake)
    assert seen["url"] == "http://h:8770/inbox/orders/next"
    assert seen["method"] == "GET" and seen["payload"] is None
    assert out["order_id"] == "DX-OLDEST"


def test_fetch_next_pending_order_returns_none_when_queue_empty():
    # 无待生成单 → {"order": null} → None。
    def fake(url, method, payload, timeout):
        return {"order": None}

    assert client.fetch_next_pending_order("http://h:8770", http_request=fake) is None


def test_fetch_next_pending_order_returns_none_when_unreachable():
    def boom(url, method, payload, timeout):
        raise error.URLError("connection refused")

    assert client.fetch_next_pending_order("http://h:8770", http_request=boom) is None


def test_delete_order_hits_right_endpoint():
    seen: dict = {}

    def fake(url, method, payload, timeout):
        seen.update(url=url, method=method, payload=payload)
        return {"deleted": "DX1"}

    out = client.delete_order("http://h:8770", "DX1", http_request=fake)
    assert seen["url"] == "http://h:8770/inbox/orders/DX1"
    assert seen["method"] == "DELETE" and seen["payload"] is None
    assert out["deleted"] == "DX1"


def test_purge_orders_posts_older_than_days():
    seen: dict = {}

    def fake(url, method, payload, timeout):
        seen.update(url=url, method=method, payload=payload)
        return {"deleted_count": 3, "older_than_days": 30}

    out = client.purge_orders("http://h:8770", 30, http_request=fake)
    assert seen["url"] == "http://h:8770/inbox/orders/purge"
    assert seen["method"] == "POST" and seen["payload"] == {"older_than_days": 30}
    assert out["deleted_count"] == 3


def test_put_scrape_control_carries_retention_days():
    seen: dict = {}

    def fake(url, method, payload, timeout):
        seen.update(payload=payload)
        return {"retention_days": 30}

    client.put_scrape_control("http://h:8770", retention_days=30, http_request=fake)
    assert seen["payload"] == {"retention_days": 30}


def test_put_scrape_control_sends_only_explicit_fields():
    seen: dict = {}

    def fake(url, method, payload, timeout):
        seen.update(url=url, method=method, payload=payload)
        return {"enabled": True}

    # 只开关 enabled：payload 仅含 enabled（部分更新，缺省字段不动）。
    client.put_scrape_control("http://h:8770", enabled=True, http_request=fake)
    assert seen["method"] == "PUT"
    assert seen["url"] == "http://h:8770/inbox/scrape/control"
    assert seen["payload"] == {"enabled": True}

    # 间隔 + 从某时间重抓 + 清空标志：各字段按需进 payload。
    client.put_scrape_control(
        "http://h:8770", interval_seconds=120, restart_from="2026-06-19 02:25",
        http_request=fake,
    )
    assert seen["payload"] == {"interval_seconds": 120, "restart_from": "2026-06-19 02:25"}

    client.put_scrape_control("http://h:8770", clear_restart_from=True, http_request=fake)
    assert seen["payload"] == {"clear_restart_from": True}


def test_put_scrape_control_empty_when_no_fields():
    seen: dict = {}

    def fake(url, method, payload, timeout):
        seen.update(payload=payload)
        return {}

    client.put_scrape_control("http://h:8770", http_request=fake)
    assert seen["payload"] == {}  # 都不给 → 空 body，服务端不动现状


def test_request_mark_posts_order_and_action():
    seen: dict = {}

    def fake(url, method, payload, timeout):
        seen.update(url=url, method=method, payload=payload)
        return {"order_id": "4090000003", "action": "mark_done", "status": "pending"}

    out = client.request_mark("http://h:8770", order_id="4090000003", action="mark_done", http_request=fake)
    assert seen["url"] == "http://h:8770/inbox/mark/request"
    assert seen["method"] == "POST"
    assert seen["payload"] == {"order_id": "4090000003", "action": "mark_done"}
    assert out["status"] == "pending"


def test_request_mark_http_error_becomes_runtime_error():
    def fake(url, method, payload, timeout):
        raise error.HTTPError(url, 404, "Not Found", {}, _FakeBody('{"detail": "未找到订单 \'X\'"}'))

    try:
        client.request_mark("http://h:8770", order_id="X", action="mark_done", http_request=fake)
        raise AssertionError("应抛 RuntimeError")
    except RuntimeError as exc:
        assert "404" in str(exc)


def test_start_scrape_task_posts_required_and_optional_fields():
    seen: dict = {}

    def fake(url, method, payload, timeout):
        seen.update(url=url, method=method, payload=payload)
        return {"task_id": "abc123", "authorized": True, "enabled": True}

    out = client.start_scrape_task(
        "http://h:8770", flower_instance_id="inst1", scrape_from="2026-06-22 12:00",
        interval_seconds=120, http_request=fake,
    )
    assert seen["url"] == "http://h:8770/inbox/scrape/task/start"
    assert seen["method"] == "POST"
    assert seen["payload"] == {
        "flower_instance_id": "inst1", "scrape_from": "2026-06-22 12:00", "interval_seconds": 120,
    }
    assert out["task_id"] == "abc123" and out["authorized"] is True


def test_heartbeat_409_raises_lease_lost():
    def fake(url, method, payload, timeout):
        raise error.HTTPError(url, 409, "Conflict", {}, _FakeBody('{"detail": "任务已失效"}'))

    try:
        client.heartbeat_scrape_task("http://h:8770", task_id="t1", flower_instance_id="i1", http_request=fake)
        raise AssertionError("应抛 LeaseLostError")
    except client.LeaseLostError as exc:
        assert "409" in str(exc)


def test_heartbeat_other_error_is_runtime_error_not_lease_lost():
    def fake(url, method, payload, timeout):
        raise error.HTTPError(url, 500, "Server Error", {}, _FakeBody('{"detail": "boom"}'))

    try:
        client.heartbeat_scrape_task("http://h:8770", task_id="t1", flower_instance_id="i1", http_request=fake)
        raise AssertionError("应抛 RuntimeError")
    except client.LeaseLostError:
        raise AssertionError("500 不应是 LeaseLostError")
    except RuntimeError as exc:
        assert "500" in str(exc)


def test_stop_scrape_task_posts_task_id():
    seen: dict = {}

    def fake(url, method, payload, timeout):
        seen.update(url=url, method=method, payload=payload)
        return {"authorized": False, "enabled": False}

    out = client.stop_scrape_task("http://h:8770", task_id="t1", http_request=fake)
    assert seen["url"] == "http://h:8770/inbox/scrape/task/stop"
    assert seen["method"] == "POST" and seen["payload"] == {"task_id": "t1"}
    assert out["authorized"] is False


def test_http_error_becomes_readable_runtime_error():
    def fake(url, method, payload, timeout):
        raise error.HTTPError(url, 422, "Unprocessable", {}, _FakeBody('{"detail": "restart_from 时间无法解析"}'))

    try:
        client.put_scrape_control("http://h:8770", restart_from="bad", http_request=fake)
        raise AssertionError("应抛 RuntimeError")
    except RuntimeError as exc:
        assert "422" in str(exc) and "restart_from" in str(exc)


class _FakeBody:
    """模拟 HTTPError 的可 read() 响应体。"""

    def __init__(self, text: str):
        self._data = text.encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def close(self) -> None:  # HTTPError 在析构时会调 close
        pass
