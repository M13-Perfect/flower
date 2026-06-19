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


def _load_order_from_json(path: Path) -> OrderImport:
    payload = json.loads(_read_text(path, encoding="utf-8"))
    remark = _find_value(payload, REMARK_KEYS)
    if not remark:
        raise ValueError("JSON 中未找到备注字段")
    return OrderImport(order_id=_find_value(payload, ORDER_ID_KEYS), remark=remark)


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
