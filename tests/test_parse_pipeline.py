import pytest

from models import AIParseConfig, ParseResult
import parse_pipeline as parse_pipeline_module  # noqa: F401  (保留以便恢复本地路径测试时引用)
from parse_pipeline import parse_order_remark_auto


# 全局 AI 对齐（2026-06-18）：_resolve_order_remark 已改为「始终走 GPT、不回退本地」。
# 「按文件名零配置」重构（2026-06-25）：ParseResult 删除 month/flower 字段，花名统一用 flower_name；
# _is_complete 新口径 = text + font + (flower_name 或 material_key)。
# 原先覆盖「本地解析 / prefer-AI 门控回退 / 月份-花序号完整性」的用例，依赖的行为与字段均已删除，故移除。


def test_parse_order_remark_auto_uses_gpt_first_when_ai_is_preferred():
    calls = []

    def preferred_gpt(*_args, **_kwargs):
        calls.append("gpt")
        return ParseResult(text="AI", flower_name="Rose", font=2, confidence=0.91)

    def local(_remark):
        calls.append("local")
        return ParseResult(text="Local", flower_name="Tulip", font=1, confidence=1.0)

    result = parse_order_remark_auto(
        "Choose Your Birth Flower : Jun - Honeysuckle Font Design : Font 1 Personalization : Local",
        ai_config=AIParseConfig(enabled=True, prefer_ai=True),
        gpt_parser=preferred_gpt,
        local_parser=local,
    )

    assert result.text == "AI"
    assert result.flower_name == "Rose"
    assert result.font == 2
    assert calls == ["gpt"]
    assert result.warnings == []


def test_parse_order_remark_auto_passes_ai_config_to_gpt():
    calls = []

    def fake_gpt(
        remark,
        api_key=None,
        model=None,
        project=None,
        organization=None,
        timeout=20,
        provider=None,
        base_url=None,
    ):
        calls.append((remark, api_key, model, project, organization, timeout, provider, base_url))
        return ParseResult(text="AI", flower_name="Rose", font=1, confidence=0.9)

    result = parse_order_remark_auto(
        "AI remark",
        ai_config=AIParseConfig(
            enabled=True,
            prefer_ai=True,
            api_key="sk-session",
            model="gpt-5-nano",
            project="proj_ui",
            organization="org_ui",
            provider="deepseek",
            base_url="https://api.deepseek.com",
            timeout=9,
        ),
        gpt_parser=fake_gpt,
        local_parser=lambda remark: ParseResult(text="", font=None, flower_name=None, confidence=0.0),
    )

    assert result.text == "AI"
    assert calls[0] == (
        "AI remark",
        "sk-session",
        "gpt-5-nano",
        "proj_ui",
        "org_ui",
        9,
        "deepseek",
        "https://api.deepseek.com",
    )


# --- 全局 AI 对齐后的新行为（本地回退已停用） ---
def test_resolve_always_calls_gpt_even_when_ai_not_preferred():
    """不再受「AI 优先」开关影响：哪怕 prefer_ai=False 也调 GPT，不走本地。"""
    calls = []

    def gpt(*_args, **_kwargs):
        calls.append("gpt")
        return ParseResult(text="AI", flower_name="Daffodil", font=2, confidence=0.9)

    result = parse_order_remark_auto(
        "anything",
        ai_config=AIParseConfig(enabled=True, prefer_ai=False),
        gpt_parser=gpt,
    )

    assert result.text == "AI"
    assert calls == ["gpt"]


def test_incomplete_gpt_returns_low_confidence_failure_and_ignores_local():
    """GPT 结果不完整 → 低置信 + warning，绝不回退到 local 的完整结果。"""

    def gpt(*_args, **_kwargs):
        return ParseResult(text="", font=None, flower_name=None, confidence=0.8)

    def local(_remark):
        return ParseResult(text="LocalWouldComplete", flower_name="Rose", font=1, confidence=1.0)

    result = parse_order_remark_auto(
        "junk",
        ai_config=AIParseConfig(enabled=True, prefer_ai=True),
        gpt_parser=gpt,
        local_parser=local,
    )

    assert result.text == ""  # 没有采用 local 的完整结果
    assert result.confidence <= 0.2
    assert result.warnings and "AI解析不完整" in result.warnings[0]


def test_gpt_exception_propagates_no_local_fallback():
    """GPT 抛错直接上抛（由 UI 提示），不再静默回退本地。"""

    def broken_gpt(*_args, **_kwargs):
        raise RuntimeError("no key")

    def local(_remark):
        return ParseResult(text="Local", flower_name="Rose", font=1, confidence=1.0)

    with pytest.raises(RuntimeError, match="no key"):
        parse_order_remark_auto(
            "x",
            ai_config=AIParseConfig(enabled=True, prefer_ai=True),
            gpt_parser=broken_gpt,
            local_parser=local,
        )
