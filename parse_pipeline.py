from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from birth_flower_parser import parse_order_remark
from gpt_parser import parse_order_remark_with_gpt
from models import AIParseConfig, ParseResult


Parser = Callable[..., ParseResult]
LocalParser = Callable[[str], ParseResult]


def parse_order_remark_auto(
    remark: str,
    gpt_parser: Parser | None = None,
    local_parser: LocalParser | None = None,
    ai_config: AIParseConfig | None = None,
) -> ParseResult:
    """根据配置选择解析顺序：勾选 AI 优先时先调 API，否则只走本地规则。"""
    gpt = gpt_parser or parse_order_remark_with_gpt
    local = local_parser or parse_order_remark

    if _should_prefer_ai(ai_config):
        gpt_error = ""
        try:
            gpt_result = _call_gpt(gpt, remark, ai_config)
            if _is_complete(gpt_result):
                return _success_without_warnings(gpt_result)
            gpt_error = _incomplete_reason(gpt_result)
        except Exception as exc:
            gpt_error = str(exc)

        local_result = local(remark)
        if _is_complete(local_result):
            return _success_without_warnings(local_result)
        return _combined_failure(local_result, gpt_error)

    # 未勾选 AI 优先时不调用 API，避免慢请求和不必要费用。
    local_result = local(remark)
    if _is_complete(local_result):
        return _success_without_warnings(local_result)

    return _local_failure(local_result)


def _should_prefer_ai(ai_config: AIParseConfig | None) -> bool:
    return bool(ai_config is not None and ai_config.enabled and ai_config.prefer_ai)


def _combined_failure(local_result: ParseResult, gpt_error: str) -> ParseResult:
    warnings = [
        f"GPT解析失败：{gpt_error or '解析结果不完整'}",
        f"本地解析失败：{_incomplete_reason(local_result)}",
    ]
    return _with_low_parse_confidence(local_result, warnings)


def _local_failure(local_result: ParseResult) -> ParseResult:
    warnings = local_result.warnings or [f"本地解析失败：{_incomplete_reason(local_result)}"]
    return _with_low_parse_confidence(local_result, warnings)


def _with_low_parse_confidence(local_result: ParseResult, warnings: list[str]) -> ParseResult:
    low_confidence = min(local_result.confidence, 0.2)
    return replace(
        local_result,
        warnings=warnings,
        confidence=low_confidence,
        parse_confidence=min(local_result.parse_confidence or low_confidence, low_confidence),
    )


def _call_gpt(gpt: Parser, remark: str, ai_config: AIParseConfig | None) -> ParseResult:
    if ai_config is None:
        return gpt(remark)
    kwargs: dict[str, Any] = {
        "api_key": ai_config.api_key,
        "model": ai_config.model,
        "project": ai_config.project,
        "organization": ai_config.organization,
        "provider": ai_config.provider,
        "base_url": ai_config.base_url,
        "timeout": ai_config.timeout,
    }
    return gpt(remark, **kwargs)


def _is_complete(result: ParseResult) -> bool:
    return bool(result.text.strip()) and result.month is not None and result.font is not None and result.flower is not None


def _success_without_warnings(result: ParseResult) -> ParseResult:
    return replace(result, warnings=[])


def _incomplete_reason(result: ParseResult) -> str:
    missing: list[str] = []
    if not result.text.strip():
        missing.append("文字")
    if result.month is None:
        missing.append("月份")
    if result.font is None:
        missing.append("font")
    if result.flower is None:
        missing.append("flower")
    details = "、".join(missing) if missing else "解析结果不完整"
    if result.warnings:
        details = f"{details}；{'；'.join(result.warnings)}"
    return details
