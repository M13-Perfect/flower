from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, NamedTuple


REMARK_KEYS = ("remark", "remarks", "note", "notes", "order_remark", "buyer_message", "message", "备注", "订单备注")
ORDER_ID_KEYS = ("order_id", "orderId", "order_no", "orderNo", "order_number", "orderNumber", "订单号", "订单编号")
BINARY_FILE_ERROR = "该文件是二进制格式,请确认文件类型"


class OrderImport(NamedTuple):
    """一笔订单的导入结果：订单号 + 备注。

    ``order_id`` 在纯文本/无订单号字段的来源里为空串；``remark`` 为产品规格备注原文。
    """

    order_id: str
    remark: str


def load_order_from_file(path: Path | str) -> OrderImport:
    """从本地文件导入订单：**同时取订单号(order_id)与备注(remark)**。

    收件夹自动化（``{order_id}.json``）与店小秘 JSON 走这条；纯文本/无订单号字段时 order_id 为空串。
    """
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"订单备注文件不存在：{source}")

    suffix = source.suffix.casefold()
    if suffix == ".json":
        return _load_order_from_json(source)
    if suffix == ".csv":
        return _load_order_from_csv(source)
    return OrderImport(order_id="", remark=_read_text(source, encoding="utf-8").strip())


def load_order_remark_from_file(path: Path | str) -> str:
    """从本地文件导入订单备注（向后兼容；需要订单号时改用 load_order_from_file）。"""
    return load_order_from_file(path).remark


def order_from_payload(payload: Any) -> OrderImport:
    """从一条**已结构化的订单 dict** 取订单号 + 备注（如 inbox-service ``GET /inbox/orders`` 返回的某条）。

    与 ``_load_order_from_json`` 同源、但**只看顶层键**（库订单 dict 形状固定、嵌套 items/mark_jobs
    不含备注键，避免递归误命中）：优先顶层 ``remark``，空则回退 ``items[].personalization_raw`` 拼接。
    供「库驱动载单」（ui_app 后台轮询第一条未删订单）复用，免得多处重复拼备注。
    """
    if not isinstance(payload, dict):
        return OrderImport(order_id="", remark="")
    order_id = _first_str(payload, ORDER_ID_KEYS)
    remark = _first_str(payload, REMARK_KEYS)
    if not remark:
        remark = _remark_from_items(payload)
    return OrderImport(order_id=order_id, remark=remark)


def _first_str(payload: dict, keys: tuple[str, ...]) -> str:
    """按 keys 顺序取顶层第一个非空字符串值（不递归），找不到返回空串。"""
    for key in keys:
        raw = payload.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


def _load_order_from_json(path: Path) -> OrderImport:
    payload = json.loads(_read_text(path, encoding="utf-8"))
    remark = _find_value(payload, REMARK_KEYS)
    order_id = _find_value(payload, ORDER_ID_KEYS)
    if not remark:
        # 2026-06-19 契约放宽：remark 改为可选/可空串，数据由 items[].personalization_raw 承载。
        # 空 remark 时回退拼出备注；标品/无定制单 items 里没有定制原文 → remark 仍为空，
        # 但只要有行项目就**照常载入**（订单进系统，操作员据此判断无需生成），不再抛错丢单。
        remark = _remark_from_items(payload)
    if not remark and not _has_items(payload):
        # 既无备注又无行项目 = 真空/坏文件，沿用老约定报错（由调用方挪走、不堵队列）。
        raise ValueError("JSON 中未找到备注字段")
    return OrderImport(order_id=order_id, remark=remark)


def _has_items(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("items"), list) and len(payload["items"]) > 0


def _remark_from_items(payload: Any) -> str:
    """remark 为空时的回退：把各行 ``items[].personalization_raw`` 拼成单条备注（2026-06-19 契约放宽）。

    多盒子混单按行拼接，交给下游 GPT 解析层「N 名字 → N 单元」；无定制原文则返回空串。
    """
    if not isinstance(payload, dict):
        return ""
    items = payload.get("items")
    if not isinstance(items, list):
        return ""
    parts: list[str] = []
    for item in items:
        if isinstance(item, dict):
            raw = item.get("personalization_raw")
            if isinstance(raw, str) and raw.strip():
                parts.append(raw.strip())
    return " / ".join(parts)


def _load_order_from_csv(path: Path) -> OrderImport:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                remark = _find_value(row, REMARK_KEYS)
                if remark:
                    return OrderImport(order_id=_find_value(row, ORDER_ID_KEYS), remark=remark)
    except UnicodeDecodeError as exc:
        raise ValueError(BINARY_FILE_ERROR) from exc
    raise ValueError("CSV 中未找到备注字段")


def _read_text(path: Path, *, encoding: str) -> str:
    try:
        return path.read_text(encoding=encoding)
    except UnicodeDecodeError as exc:
        raise ValueError(BINARY_FILE_ERROR) from exc


def _find_value(value: Any, keys: tuple[str, ...]) -> str:
    """按 keys 顺序在 dict（含嵌套）/list 里找第一个非空字符串值，返回去白结果；找不到返回空串。"""
    if isinstance(value, dict):
        for key in keys:
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        for raw in value.values():
            found = _find_value(raw, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_value(item, keys)
            if found:
                return found
    return ""
