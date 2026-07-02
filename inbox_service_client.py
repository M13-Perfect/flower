"""flower → inbox-service（automation 本地服务，默认 127.0.0.1:8770）HTTP 客户端。

只做 flower 该做的那点对接：**读/写「自动抓开关」`ScrapeControl`**（`GET/PUT /inbox/scrape/control`）+ 探活。
拓扑（见 automation/AGENTS.md）：flower → inbox-service（写开关）→ 扩展（读开关去抓 + 拉 worklist + 回传）；
inbox-service 是唯一中转点，flower 不直连扩展。**flower 只写这一个开关**，扩展读它决定跑不跑/往回翻到几时。

注意：这是 automation 的 **inbox-service**（live 本地服务），**不是**已暂缓的 web `services/api`——别混。
不引入新依赖：用标准库 urllib，错误转成可读消息交 UI 提示；探活失败返回 None（不抛）。
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable
from urllib import error, request

# 服务地址：默认 127.0.0.1:8770，可被 env 覆盖以对齐服务端（FLOWER_INBOX_PORT/HOST，见 automation 跑法）。
DEFAULT_HOST = os.environ.get("FLOWER_INBOX_HOST", "127.0.0.1")
DEFAULT_PORT = os.environ.get("FLOWER_INBOX_PORT", "8770")
DEFAULT_BASE_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"

SCRAPE_CONTROL_PATH = "/inbox/scrape/control"
SCRAPE_TASK_START_PATH = "/inbox/scrape/task/start"
SCRAPE_TASK_HEARTBEAT_PATH = "/inbox/scrape/task/heartbeat"
SCRAPE_TASK_STOP_PATH = "/inbox/scrape/task/stop"
ORDERS_PATH = "/inbox/orders"
NEXT_ORDER_PATH = "/inbox/orders/next"
PURGE_PATH = "/inbox/orders/purge"
MARK_REQUEST_PATH = "/inbox/mark/request"
HEALTH_PATH = "/healthz"


class LeaseLostError(RuntimeError):
    """心跳续约被服务端拒绝（HTTP 409）：当前任务已失效（被替换/停止/实例不符）。

    flower 据此停掉心跳并把「自动抓取」开关回弹到关——别再以为自己还持有授权。
    """

# (url, method, payload|None, timeout) -> dict；注入点便于测试（不打真网络）。
HttpRequest = Callable[[str, str, "dict[str, Any] | None", float], "dict[str, Any]"]


def _http_request(url: str, method: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = request.Request(url, data=data, headers=headers, method=method)
    with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 (本机 http)
        body = response.read().decode("utf-8")
        return json.loads(body) if body.strip() else {}


def _format_http_error(exc: error.HTTPError) -> str:
    """把 FastAPI 的 {"detail": ...} 错误体转成可读消息（供 UI 提示）。"""
    detail = ""
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        if isinstance(payload, dict):
            raw = payload.get("detail")
            detail = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    except Exception:
        detail = ""
    return f"inbox-service HTTP {exc.code}：{detail or exc.reason}"


def health(base_url: str = DEFAULT_BASE_URL, *, timeout: float = 3.0, http_request: HttpRequest | None = None) -> dict[str, Any] | None:
    """探活：返回 /healthz dict；服务不可达/超时返回 None（不抛，供 UI 显示「未连接」）。"""
    try:
        return (http_request or _http_request)(f"{base_url.rstrip('/')}{HEALTH_PATH}", "GET", None, timeout)
    except (error.URLError, OSError, ValueError):
        return None


def list_orders(
    base_url: str = DEFAULT_BASE_URL,
    *,
    limit: int | None = None,
    offset: int | None = None,
    timeout: float = 5.0,
    http_request: HttpRequest | None = None,
) -> dict[str, Any]:
    """列「已入库」订单（操作员配置端订单表用）：返回 {orders, count(总数), returned(本页), limit, offset}。

    数据=扩展抓取后经 inbox-service 入库的单（GET /inbox/orders，按 received_at 倒序分页）。每条含 order_id/
    status/refund_status/paid_at/received_at/items[]（items 里有 quantity/is_target_box/原始备注），
    件数=各行 quantity 之和、是否有「其他商品」=存在 is_target_box=False 的行，由 UI 侧聚合。
    limit/offset 缺省=服务端默认（limit 100）；阶段三虚拟列表就位后可放大 limit 拉全量。
    服务不可达/超时抛 RuntimeError，交 UI 显示未连接。
    """
    url = f"{base_url.rstrip('/')}{ORDERS_PATH}"
    params = []
    if limit is not None:
        params.append(f"limit={int(limit)}")
    if offset is not None:
        params.append(f"offset={int(offset)}")
    if params:
        url = f"{url}?{'&'.join(params)}"
    try:
        return (http_request or _http_request)(url, "GET", None, timeout)
    except error.HTTPError as exc:
        raise RuntimeError(_format_http_error(exc)) from exc


def fetch_next_pending_order(
    base_url: str = DEFAULT_BASE_URL,
    *,
    timeout: float = 5.0,
    http_request: HttpRequest | None = None,
) -> dict[str, Any] | None:
    """取库中『最旧的待生成订单』（FIFO 队首：未软删 + ai_status=pending；服务端 GET /inbox/orders/next）。

    操作员端「库驱动载单」轮询用：生成完的单在服务端 ai_status→recognized（生成成功 mark_done 触发）自动掉出队列，
    故本接口**天然只回未生成单**、生成后前进到下一条。无待生成单 / 服务不可达 / 任意 HTTP 错误 → 返回 None
    （不抛，供轮询静默跳过、保持当前内容）。
    """
    url = f"{base_url.rstrip('/')}{NEXT_ORDER_PATH}"
    try:
        payload = (http_request or _http_request)(url, "GET", None, timeout)
    except (error.HTTPError, error.URLError, OSError, ValueError):
        return None
    order = payload.get("order") if isinstance(payload, dict) else None
    return order if isinstance(order, dict) else None


def delete_order(base_url: str, order_id: str, *, timeout: float = 5.0, http_request: HttpRequest | None = None) -> dict[str, Any]:
    """删除单个订单（含级联 items/退款检查）：DELETE /inbox/orders/{order_id}。404 等转 RuntimeError。"""
    url = f"{base_url.rstrip('/')}{ORDERS_PATH}/{order_id}"
    try:
        return (http_request or _http_request)(url, "DELETE", None, timeout)
    except error.HTTPError as exc:
        raise RuntimeError(_format_http_error(exc)) from exc


def purge_orders(base_url: str, older_than_days: int, *, timeout: float = 10.0, http_request: HttpRequest | None = None) -> dict[str, Any]:
    """手动清理：删除 received_at 早于 (now - N 天) 的订单（N>=1），返回 {deleted_count, older_than_days}。"""
    payload = {"older_than_days": int(older_than_days)}
    try:
        return (http_request or _http_request)(f"{base_url.rstrip('/')}{PURGE_PATH}", "POST", payload, timeout)
    except error.HTTPError as exc:
        raise RuntimeError(_format_http_error(exc)) from exc


def request_mark(
    base_url: str = DEFAULT_BASE_URL,
    *,
    order_id: str,
    action: str,
    timeout: float = 5.0,
    http_request: HttpRequest | None = None,
) -> dict[str, Any]:
    """入队一条标记回写任务：让扩展去店小秘给订单打自定义标记。

    action: 'mark_unrecognized'（待处理）| 'mark_done'（已处理，顺带清未识别）。
    flower 生成成功后调它入队 'mark_done'（抓单时的 'mark_unrecognized' 由 inbox-service 自动入队）。
    服务端 404（订单未入库）/422（动作非法）等转 RuntimeError。
    """
    payload = {"order_id": order_id, "action": action}
    try:
        return (http_request or _http_request)(f"{base_url.rstrip('/')}{MARK_REQUEST_PATH}", "POST", payload, timeout)
    except error.HTTPError as exc:
        raise RuntimeError(_format_http_error(exc)) from exc


def get_scrape_control(base_url: str = DEFAULT_BASE_URL, *, timeout: float = 5.0, http_request: HttpRequest | None = None) -> dict[str, Any]:
    """读自动抓任务租约：{enabled, authorized, interval_seconds, scrape_from, scrape_to, task_id, lease_expires_at, ...}。

    ⚠️ P0：扩展据 ``authorized`` 决定是否执行（服务端时钟据任务租约算）。flower 这边主要看它显示状态。
    """
    try:
        return (http_request or _http_request)(f"{base_url.rstrip('/')}{SCRAPE_CONTROL_PATH}", "GET", None, timeout)
    except error.HTTPError as exc:
        raise RuntimeError(_format_http_error(exc)) from exc


def start_scrape_task(
    base_url: str = DEFAULT_BASE_URL,
    *,
    flower_instance_id: str,
    scrape_from: str,
    scrape_to: str | None = None,
    interval_seconds: int | None = None,
    allowed_actions: list[str] | None = None,
    shop_scope: list[str] | None = None,
    lease_seconds: float | None = None,
    timeout: float = 5.0,
    http_request: HttpRequest | None = None,
) -> dict[str, Any]:
    """flower「开始采集」：下发一个有租约的采集任务（P0）。返回含 task_id + authorized。

    scrape_from 必填（订单时间范围下界，墙钟）；缺省下界=由调用方传「现在」以只抓此刻之后的新单、绝不回溯历史。
    服务端 422（时间无法解析）等转 RuntimeError。
    """
    payload: dict[str, Any] = {"flower_instance_id": flower_instance_id, "scrape_from": scrape_from}
    if scrape_to is not None:
        payload["scrape_to"] = scrape_to
    if interval_seconds is not None:
        payload["interval_seconds"] = int(interval_seconds)
    if allowed_actions is not None:
        payload["allowed_actions"] = allowed_actions
    if shop_scope is not None:
        payload["shop_scope"] = shop_scope
    if lease_seconds is not None:
        payload["lease_seconds"] = float(lease_seconds)
    try:
        return (http_request or _http_request)(f"{base_url.rstrip('/')}{SCRAPE_TASK_START_PATH}", "POST", payload, timeout)
    except error.HTTPError as exc:
        raise RuntimeError(_format_http_error(exc)) from exc


def heartbeat_scrape_task(
    base_url: str = DEFAULT_BASE_URL,
    *,
    task_id: str,
    flower_instance_id: str,
    lease_seconds: float | None = None,
    timeout: float = 5.0,
    http_request: HttpRequest | None = None,
) -> dict[str, Any]:
    """flower 心跳续约（须周期调用，否则租约到期 → 扩展自动停）。

    服务端 409（任务已失效/被替换/实例不符）→ 抛 ``LeaseLostError``，flower 据此停心跳 + 回弹开关。
    其它 HTTP 错误 / 网络错误按原异常抛出（瞬时错误调用方可重试）。
    """
    payload: dict[str, Any] = {"task_id": task_id, "flower_instance_id": flower_instance_id}
    if lease_seconds is not None:
        payload["lease_seconds"] = float(lease_seconds)
    try:
        return (http_request or _http_request)(f"{base_url.rstrip('/')}{SCRAPE_TASK_HEARTBEAT_PATH}", "POST", payload, timeout)
    except error.HTTPError as exc:
        if exc.code == 409:
            raise LeaseLostError(_format_http_error(exc)) from exc
        raise RuntimeError(_format_http_error(exc)) from exc


def stop_scrape_task(
    base_url: str = DEFAULT_BASE_URL,
    *,
    task_id: str | None = None,
    flower_instance_id: str | None = None,
    timeout: float = 5.0,
    http_request: HttpRequest | None = None,
) -> dict[str, Any]:
    """flower「停止采集」/ 关闭 App：释放任务租约 → 扩展立即未授权。幂等。"""
    payload: dict[str, Any] = {}
    if task_id is not None:
        payload["task_id"] = task_id
    if flower_instance_id is not None:
        payload["flower_instance_id"] = flower_instance_id
    try:
        return (http_request or _http_request)(f"{base_url.rstrip('/')}{SCRAPE_TASK_STOP_PATH}", "POST", payload, timeout)
    except error.HTTPError as exc:
        raise RuntimeError(_format_http_error(exc)) from exc


def put_scrape_control(
    base_url: str = DEFAULT_BASE_URL,
    *,
    enabled: bool | None = None,
    interval_seconds: int | None = None,
    restart_from: str | None = None,
    clear_restart_from: bool = False,
    retention_days: int | None = None,
    timeout: float = 5.0,
    http_request: HttpRequest | None = None,
) -> dict[str, Any]:
    """写自动抓开关（部分更新，缺省字段不动）：开/关、间隔、从某付款时间重抓（restart_from / 清空）、订单保留天数。

    对齐服务端 `ScrapeControlUpdate`：只放显式给定的字段；都不给则发空 body（服务端不动现状）。
    """
    payload: dict[str, Any] = {}
    if enabled is not None:
        payload["enabled"] = enabled
    if interval_seconds is not None:
        payload["interval_seconds"] = interval_seconds
    if restart_from is not None:
        payload["restart_from"] = restart_from
    if clear_restart_from:
        payload["clear_restart_from"] = True
    if retention_days is not None:
        payload["retention_days"] = int(retention_days)
    try:
        return (http_request or _http_request)(f"{base_url.rstrip('/')}{SCRAPE_CONTROL_PATH}", "PUT", payload, timeout)
    except error.HTTPError as exc:
        raise RuntimeError(_format_http_error(exc)) from exc
