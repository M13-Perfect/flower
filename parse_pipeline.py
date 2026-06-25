from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from gpt_parser import parse_order_remark_with_gpt, parse_orders_with_gpt
# 本地规则已停用（全局 AI 对齐），保留可恢复：
# from local_order_parser import parse_order_remark_local
from models import AIParseConfig, ParsePromptTrace, ParseResult
from order_catalog import LibraryBundle, enrich_parse_result


Parser = Callable[..., ParseResult]
LocalParser = Callable[[str], ParseResult]
OrdersParser = Callable[..., list[ParseResult]]

# 订单块第一行的「订单号」：≥6 位数字，可带 xN 数量后缀（如 29972194015x1）。
_ORDER_NUMBER_RE = re.compile(r"^\s*(\d{6,})\s*(?:[xX]\s*(\d+))?\s*$")


def parse_order_remark_auto(
    remark: str,
    gpt_parser: Parser | None = None,
    local_parser: LocalParser | None = None,
    ai_config: AIParseConfig | None = None,
    bundle: LibraryBundle | None = None,
) -> ParseResult:
    """根据配置选择解析顺序；若传入 bundle（产品素材/字体库），再把结果落到具体素材/字体 key。

    **全局使用 AI 解析**：本地回退已停用（见 _resolve_order_remark）；传/不传 bundle 仅决定是否富化落素材。
    """
    result = _resolve_order_remark(remark, gpt_parser, local_parser, ai_config)
    if bundle is not None:
        result = enrich_parse_result(result, bundle)
    return result


def parse_orders_auto(
    remark: str,
    *,
    ai_config: AIParseConfig | None = None,
    bundle: LibraryBundle | None = None,
    gpt_orders_parser: OrdersParser | None = None,
    local_parser: LocalParser | None = None,
    trace: ParsePromptTrace | None = None,
) -> list[ParseResult]:
    """多订单识别：一次粘贴可含多笔订单，返回 ParseResult 列表（每笔一条）。

    **全局使用 AI 解析**（用户要求）：始终走多订单 GPT，不受「AI 优先」开关影响；
    AI 失败直接抛错由 UI 提示，**不再静默回退本地规则**。传入 bundle 时每条再富化落素材/字体 key。
    传入 `trace`（空壳 ParsePromptTrace）时，解析路径把实际发出的提示词写回，供解析页可观测性展示。
    本地兜底代码（_local_orders / split_order_blocks / _should_prefer_ai 门控）已注释停用、保留可恢复。
    """
    gpt = gpt_orders_parser or parse_orders_with_gpt
    # 本地规则已停用：注释掉本地解析器与按块兜底，全局只用 AI。
    # local = local_parser or parse_order_remark_local

    results = [r for r in _call_orders_gpt(gpt, remark, ai_config, trace) if r is not None]
    # if _should_prefer_ai(ai_config):
    #     try:
    #         results = [r for r in _call_orders_gpt(gpt, remark, ai_config) if r is not None]
    #     except Exception:
    #         results = []
    # if not results:
    #     results = _local_orders(remark, local)

    if bundle is not None:
        results = [enrich_parse_result(result, bundle) for result in results]
    return results


def _call_orders_gpt(
    gpt: OrdersParser,
    remark: str,
    ai_config: AIParseConfig | None,
    trace: ParsePromptTrace | None = None,
) -> list[ParseResult]:
    # trace 仅在调用方需要可观测性时传入；为 None 时不放进 kwargs，保持对旧 fake 解析器的零侵入。
    kwargs: dict[str, Any] = {}
    if ai_config is not None:
        kwargs.update(
            api_key=ai_config.api_key,
            model=ai_config.model,
            project=ai_config.project,
            organization=ai_config.organization,
            provider=ai_config.provider,
            base_url=ai_config.base_url,
            system_prompt=ai_config.system_prompt,
            background_prompt=ai_config.background_prompt,
            timeout=ai_config.timeout,
        )
        if ai_config.user_content is not None:
            kwargs["user_content"] = ai_config.user_content
        if ai_config.reference_snapshot:
            kwargs["reference_snapshot"] = ai_config.reference_snapshot
    if trace is not None:
        kwargs["trace"] = trace
    return gpt(remark, **kwargs)


def _local_orders(remark: str, local: LocalParser) -> list[ParseResult]:
    """无 AI 兜底：按订单块切分，逐块走本地规则；单块时与旧行为一致。"""
    blocks = split_order_blocks(remark)
    if len(blocks) <= 1:
        result = local(remark)
        number = blocks[0][0] if blocks else ""
        if number and not result.order_number:
            result = replace(result, order_number=number)
        return [result]
    results: list[ParseResult] = []
    for order_number, quantity, block_text in blocks:
        result = local(block_text)
        patch: dict[str, Any] = {}
        if order_number and not result.order_number:
            patch["order_number"] = order_number
        if quantity and result.quantity == 1:
            patch["quantity"] = quantity
        results.append(replace(result, **patch) if patch else result)
    return results


def split_order_blocks(remark: str) -> list[tuple[str, int, str]]:
    """把多笔订单文本按空行切块；每块第一行若是订单号则提取。返回 [(order_number, quantity, block_text)]。"""
    blocks: list[tuple[str, int, str]] = []
    for raw in re.split(r"\n\s*\n", remark.strip()):
        if not raw.strip():
            continue
        order_number = ""
        quantity = 1
        for line in raw.splitlines():
            match = _ORDER_NUMBER_RE.match(line)
            if match:
                order_number = match.group(1)
                if match.group(2):
                    quantity = int(match.group(2))
                break
        blocks.append((order_number, quantity, raw))
    return blocks


def _resolve_order_remark(
    remark: str,
    gpt_parser: Parser | None = None,
    local_parser: LocalParser | None = None,
    ai_config: AIParseConfig | None = None,
) -> ParseResult:
    """**全局使用 AI 解析**（用户要求）：始终走 GPT，不受「AI 优先」开关影响；
    AI 失败直接抛错由 UI 提示，AI 结果不完整返回低置信 + warnings，**不再回退本地规则**。
    本地兜底（parse_order_remark_local / prefer-AI 门控）已注释停用、保留可恢复。
    （local_parser 形参仅为签名兼容保留，已不再使用。）
    """
    gpt = gpt_parser or parse_order_remark_with_gpt
    # 本地规则已停用：注释掉本地解析器与回退，全局只用 AI。
    # local = local_parser or parse_order_remark_local

    gpt_result = _call_gpt(gpt, remark, ai_config)
    if _is_complete(gpt_result):
        return _success_without_warnings(gpt_result)
    return _with_low_parse_confidence(gpt_result, [f"AI解析不完整：{_incomplete_reason(gpt_result)}"])

    # --- 旧逻辑（AI 优先门控 + 本地回退），保留可恢复 ---
    # local = local_parser or parse_order_remark_local
    # if _should_prefer_ai(ai_config):
    #     gpt_error = ""
    #     try:
    #         gpt_result = _call_gpt(gpt, remark, ai_config)
    #         if _is_complete(gpt_result):
    #             return _success_without_warnings(gpt_result)
    #         gpt_error = _incomplete_reason(gpt_result)
    #     except Exception as exc:
    #         gpt_error = str(exc)
    #     local_result = local(remark)
    #     if _is_complete(local_result):
    #         return _success_without_warnings(local_result)
    #     return _combined_failure(local_result, gpt_error)
    #
    # local_result = local(remark)
    # if _is_complete(local_result):
    #     return _success_without_warnings(local_result)
    # return _local_failure(local_result)


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
    return (
        bool(result.text.strip())
        and result.font is not None
        and bool(result.flower_name or result.material_key)
    )


def _success_without_warnings(result: ParseResult) -> ParseResult:
    return replace(result, warnings=[])


def _incomplete_reason(result: ParseResult) -> str:
    missing: list[str] = []
    if not result.text.strip():
        missing.append("文字")
    if not (result.flower_name or result.material_key):
        missing.append("花名")
    if result.font is None:
        missing.append("font")
    details = "、".join(missing) if missing else "解析结果不完整"
    if result.warnings:
        details = f"{details}；{'；'.join(result.warnings)}"
    return details
