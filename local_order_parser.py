from __future__ import annotations

import importlib.util
import re
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from birth_flower_parser import parse_order_remark as parse_legacy_order_remark
from models import ParseResult


SERVICE_API_ROOT = Path(__file__).resolve().parent / "services" / "api"
WEB_ORDER_PARSER_PATH = SERVICE_API_ROOT / "app" / "domain" / "orders" / "parser.py"
_WEB_RULE_MODULE: Any | None = None


@dataclass
class _WebFlowerChoice:
    choice: int
    name: str


@dataclass
class _WebFontPreference:
    choice: int
    label: str


@dataclass
class _WebParsedOrder:
    order_id: str | None = None
    customer_name: str | None = None
    month: int | None = None
    month_name: str | None = None
    flower: _WebFlowerChoice | None = None
    font_preference: _WebFontPreference | None = None
    special_notes: str = ""

    def __init__(
        self,
        orderId: str | None = None,
        customerName: str | None = None,
        month: int | None = None,
        monthName: str | None = None,
        flower: _WebFlowerChoice | None = None,
        fontPreference: _WebFontPreference | None = None,
        specialNotes: str = "",
    ) -> None:
        self.order_id = orderId
        self.customer_name = customerName
        self.month = month
        self.month_name = monthName
        self.flower = flower
        self.font_preference = fontPreference
        self.special_notes = specialNotes


def parse_order_remark_local(remark: str) -> ParseResult:
    """复用网页版本地订单识别规则，并转换成纯 Python 桌面版 ParseResult。"""
    try:
        parsed = _parse_with_web_rules(remark)
    except Exception:
        return parse_legacy_order_remark(remark)

    legacy = parse_legacy_order_remark(remark)
    return ParseResult(
        text=str(_value(parsed, "customer_name") or ""),
        month=_value(parsed, "month"),
        font=_value(_value(parsed, "font_preference"), "choice"),
        flower=_value(_value(parsed, "flower"), "choice"),
        warnings=[],
        confidence=1.0,
        birth_month=str(_value(parsed, "month_name") or ""),
        flower_name=str(_value(_value(parsed, "flower"), "name") or ""),
        font_design=str(_value(_value(parsed, "font_preference"), "label") or ""),
        personalization_raw=str(_value(parsed, "customer_name") or ""),
        personalization_type=_personalization_type(str(_value(parsed, "customer_name") or "")),
        parse_confidence=1.0,
        selected_flower_asset=legacy.selected_flower_asset,
        selected_font_asset=legacy.selected_font_asset,
        asset_confidence=legacy.asset_confidence,
    )


def _parse_with_web_rules(remark: str) -> Any:
    module = _load_web_order_parser()
    return module.parse_order_note(remark)


def _load_web_order_parser() -> Any:
    global _WEB_RULE_MODULE
    if _WEB_RULE_MODULE is not None:
        return _WEB_RULE_MODULE
    if not WEB_ORDER_PARSER_PATH.is_file():
        raise FileNotFoundError(WEB_ORDER_PARSER_PATH)

    service_path = str(SERVICE_API_ROOT)
    if service_path not in sys.path:
        sys.path.insert(0, service_path)

    previous_schema = sys.modules.get("app.schemas.orders")
    sys.modules["app.schemas.orders"] = _web_schema_shim()
    try:
        spec = importlib.util.spec_from_file_location("_flower_web_order_parser", WEB_ORDER_PARSER_PATH)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load web order parser: {WEB_ORDER_PARSER_PATH}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if previous_schema is None:
            sys.modules.pop("app.schemas.orders", None)
        else:
            sys.modules["app.schemas.orders"] = previous_schema

    _WEB_RULE_MODULE = module
    return module


def _web_schema_shim() -> types.ModuleType:
    module = types.ModuleType("app.schemas.orders")
    module.FlowerChoice = _WebFlowerChoice
    module.FontPreference = _WebFontPreference
    module.ParsedOrder = _WebParsedOrder
    return module


def _value(source: Any, name: str) -> Any:
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(name) or source.get(_camel(name))
    return getattr(source, name, None)


def _camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part[:1].upper() + part[1:] for part in rest)


def _personalization_type(value: str) -> str:
    if len(value) > 32 or re.search(r"[.!?;\u3002\uff01\uff1f\u2026]", value):
        return "message"
    return "name" if value.strip() else "unknown"
