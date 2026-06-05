from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


REMARK_KEYS = ("remark", "remarks", "note", "notes", "order_remark", "buyer_message", "message", "备注", "订单备注")


def load_order_remark_from_file(path: Path | str) -> str:
    """从本地文件导入订单备注；后续店小秘 API 可复用同一输出契约。"""
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"订单备注文件不存在：{source}")

    suffix = source.suffix.casefold()
    if suffix == ".json":
        return _load_from_json(source)
    if suffix == ".csv":
        return _load_from_csv(source)
    return source.read_text(encoding="utf-8").strip()


def _load_from_json(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    remark = _find_remark(payload)
    if remark:
        return remark
    raise ValueError("JSON 中未找到备注字段")


def _load_from_csv(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            remark = _find_remark(row)
            if remark:
                return remark
    raise ValueError("CSV 中未找到备注字段")


def _find_remark(value: Any) -> str:
    if isinstance(value, dict):
        for key in REMARK_KEYS:
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        for raw in value.values():
            found = _find_remark(raw)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_remark(item)
            if found:
                return found
    return ""
