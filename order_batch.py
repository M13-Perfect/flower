from __future__ import annotations

from dataclasses import dataclass, field
import logging
import traceback
from pathlib import Path
from typing import Callable

from asset_resolver import find_flower_asset, scan_font_assets
from glyph_service import GlyphRulesConfig, apply_automatic_glyph_rules

LOGGER = logging.getLogger(__name__)

ORDER_STATUSES = {"pending", "parsed", "validated", "rendered", "exported", "warning", "failed"}


@dataclass
class ParsedOrderResult:
    """后续 AI 批量识别的结构化输入；本地校验仍是最终权威。"""

    order_id: str
    raw_note: str
    month: str | None = None
    flower: str | None = None
    flower_variant: str | None = None
    font_design: int | None = None
    personalization: str | None = None
    confidence: float = 0.0
    needs_review: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class OrderValidationResult:
    order: ParsedOrderResult
    status: str
    red_flags: list[str] = field(default_factory=list)
    yellow_flags: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.red_flags


@dataclass
class BatchOrderItemStatus:
    order_id: str
    status: str = "pending"
    output_paths: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class BatchRenderReport:
    items: list[BatchOrderItemStatus]

    @property
    def success_count(self) -> int:
        return sum(1 for item in self.items if item.status in {"rendered", "exported", "warning"} and not item.error)

    @property
    def failure_count(self) -> int:
        return sum(1 for item in self.items if item.status == "failed")

    @property
    def review_count(self) -> int:
        return sum(1 for item in self.items if item.warnings)


def validate_parsed_order(
    order: ParsedOrderResult,
    *,
    flower_dir: Path | str | None = None,
    font_source: Path | str | None = None,
    glyph_rules: GlyphRulesConfig | None = None,
) -> OrderValidationResult:
    """本地校验结构化订单结果；AI 只提供输入，不直接决定渲染。"""
    red: list[str] = []
    yellow: list[str] = list(order.warnings)
    if not order.order_id.strip():
        red.append("order_id 为空")
    if not (order.month or "").strip():
        red.append("month 缺失")
    if not (order.flower or "").strip():
        red.append("flower 缺失")
    if not (order.personalization or "").strip():
        red.append("personalization 缺失")
    if order.font_design is None:
        yellow.append("font_design 缺失")
    if order.confidence < 0.8:
        yellow.append("confidence < 0.8")
    month_number = _safe_int(order.month)
    flower_number = _safe_int(order.flower)
    if order.month and month_number is None:
        yellow.append("month 字段格式异常")
    if order.flower and flower_number is None:
        yellow.append("flower 字段格式异常")
    if flower_dir is not None and month_number is not None and flower_number is not None:
        if find_flower_asset(Path(flower_dir), month_number, flower_number) is None:
            red.append("本地花朵素材不存在")
    if font_source is not None and order.font_design is not None:
        fonts = scan_font_assets(Path(font_source))
        if not any(asset.index == order.font_design and asset.path.exists() for asset in fonts):
            red.append("字体文件不存在")
    if glyph_rules is not None and order.personalization and order.font_design is not None:
        try:
            _render_text, _overrides, rule_warnings, _applied = apply_automatic_glyph_rules(
                order.personalization,
                f"Font {order.font_design}",
                None,
                {},
                glyph_rules,
                order_id=order.order_id,
            )
            yellow.extend(f"自动字形应用失败：{warning}" for warning in rule_warnings)
        except Exception as exc:
            yellow.append(f"自动字形应用失败：{exc}")
            LOGGER.warning("自动字形规则失败：order_id=%s font_id=%s reason=%s", order.order_id, order.font_design, exc)
    status = "failed" if red else "warning" if yellow or order.needs_review else "validated"
    return OrderValidationResult(order, status, red, yellow)


def run_batch_render(
    orders: list[ParsedOrderResult],
    render_one: Callable[[ParsedOrderResult], list[Path]],
) -> BatchRenderReport:
    """批量渲染错误隔离：单个订单失败不会中断整批。"""
    items: list[BatchOrderItemStatus] = []
    for order in orders:
        item = BatchOrderItemStatus(order_id=order.order_id or "<empty>", status="pending")
        try:
            item.status = "parsed"
            paths = render_one(order)
            item.output_paths = list(paths)
            item.warnings = list(order.warnings)
            item.status = "warning" if item.warnings or order.needs_review else "exported"
        except Exception as exc:
            item.status = "failed"
            item.error = str(exc) or exc.__class__.__name__
            LOGGER.error("批量导出失败：order_id=%s reason=%s\n%s", item.order_id, item.error, traceback.format_exc())
        items.append(item)
    return BatchRenderReport(items)


def _safe_int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
