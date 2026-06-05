from __future__ import annotations

from dataclasses import dataclass

from models import ParseResult
from text_layout import TextLayoutResult


READY_THRESHOLD = 0.9
REVIEW_THRESHOLD = 0.4


@dataclass(frozen=True)
class GenerationReadiness:
    parse_confidence: float
    asset_confidence: float
    layout_confidence: float
    overall_confidence: float
    status: str
    warnings: list[str]


def build_generation_readiness(parse_result: ParseResult, layout_result: TextLayoutResult) -> GenerationReadiness:
    """汇总解析、素材和布局置信度；总分保守取最低项。"""
    parse_confidence = _normalized_score(parse_result.parse_confidence or parse_result.confidence)
    asset_confidence = _normalized_score(parse_result.asset_confidence)
    layout_confidence = _normalized_score(layout_result.layout_confidence)
    warnings = _merged_warnings(parse_result.warnings, layout_result.warnings)
    overall = min(parse_confidence, asset_confidence, layout_confidence)
    if warnings:
        overall = min(overall, 0.99)
    status = _status(overall, parse_confidence, layout_result.did_fit, bool(warnings))
    return GenerationReadiness(
        parse_confidence=parse_confidence,
        asset_confidence=asset_confidence,
        layout_confidence=layout_confidence,
        overall_confidence=round(overall, 2),
        status=status,
        warnings=warnings,
    )


def _normalized_score(value: float | int | None) -> float:
    try:
        score = float(value if value is not None else 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return round(max(0.0, min(1.0, score)), 2)


def _merged_warnings(*warning_groups: list[str]) -> list[str]:
    merged: list[str] = []
    for warnings in warning_groups:
        for warning in warnings:
            clean = str(warning).strip()
            if clean and clean not in merged:
                merged.append(clean)
    return merged


def _status(overall: float, parse_confidence: float, did_fit: bool, has_warnings: bool) -> str:
    if parse_confidence < REVIEW_THRESHOLD:
        return "Cannot generate"
    if has_warnings:
        return "Needs review"
    if overall >= READY_THRESHOLD and did_fit:
        return "Ready"
    return "Needs review"
