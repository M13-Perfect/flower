from models import AIParseConfig, ParseResult
import parse_pipeline as parse_pipeline_module
from parse_pipeline import parse_order_remark_auto


def test_parse_order_remark_auto_uses_local_when_ai_is_not_preferred():
    calls = []

    def wrong_gpt(*_args, **_kwargs):
        calls.append("gpt")
        return ParseResult(text="Jessica", month=6, font=1, flower=1, confidence=0.72)

    result = parse_order_remark_auto(
        "Choose Your Birth Flower  ：Jun - HoneysuckleFont Design  ：Font 1Personalization  ：Jessica",
        ai_config=AIParseConfig(enabled=True, prefer_ai=False),
        gpt_parser=wrong_gpt,
    )

    assert result.text == "Jessica"
    assert result.month == 6
    assert result.font == 1
    assert result.flower == 2
    assert calls == []
    assert result.warnings == []


def test_parse_order_remark_auto_default_local_uses_web_local_rules():
    def forbidden_gpt(*_args, **_kwargs):
        raise AssertionError("GPT should not be called")

    result = parse_order_remark_auto(
        "Customer Name: Ava Chen\n"
        "Birth Month: June\n"
        "Flower: Rose\n"
        "Font Design: Font 8",
        ai_config=AIParseConfig(enabled=False, prefer_ai=True),
        gpt_parser=forbidden_gpt,
    )

    assert result.text == "Ava Chen"
    assert result.month == 6
    assert result.flower == 1
    assert result.font == 8
    assert result.warnings == []


def test_parse_order_remark_auto_defaults_to_shared_local_parser(monkeypatch):
    calls = []

    def shared_local(remark):
        calls.append(remark)
        return ParseResult(text="Shared", month=9, font=8, flower=2, confidence=0.97)

    monkeypatch.setattr(parse_pipeline_module, "parse_order_remark_local", shared_local)

    result = parse_order_remark_auto(
        "web local format",
        ai_config=AIParseConfig(enabled=False, prefer_ai=False),
    )

    assert result.text == "Shared"
    assert result.month == 9
    assert result.font == 8
    assert result.flower == 2
    assert calls == ["web local format"]


def test_parse_order_remark_auto_uses_gpt_first_when_ai_is_preferred():
    calls = []

    def preferred_gpt(*_args, **_kwargs):
        calls.append("gpt")
        return ParseResult(text="AI", month=8, font=2, flower=1, confidence=0.91)

    def local(_remark):
        calls.append("local")
        return ParseResult(text="Local", month=6, font=1, flower=2, confidence=1.0)

    result = parse_order_remark_auto(
        "Choose Your Birth Flower : Jun - Honeysuckle Font Design : Font 1 Personalization : Local",
        ai_config=AIParseConfig(enabled=True, prefer_ai=True),
        gpt_parser=preferred_gpt,
        local_parser=local,
    )

    assert result.text == "AI"
    assert result.month == 8
    assert result.font == 2
    assert result.flower == 1
    assert calls == ["gpt"]
    assert result.warnings == []


def test_parse_order_remark_auto_uses_local_when_gpt_fails():
    def broken_gpt(_remark):
        raise RuntimeError("no key")

    result = parse_order_remark_auto(
        "Name: Local June font 1 flower 1",
        gpt_parser=broken_gpt,
        local_parser=lambda remark: ParseResult(text="Local", month=6, font=1, flower=1, confidence=0.9),
    )

    assert result.text == "Local"
    assert result.warnings == []


def test_parse_order_remark_auto_warns_only_when_both_fail():
    def broken_gpt(_remark, **_kwargs):
        raise RuntimeError("gpt failed")

    result = parse_order_remark_auto(
        "???",
        ai_config=AIParseConfig(enabled=True, prefer_ai=True),
        gpt_parser=broken_gpt,
        local_parser=lambda remark: ParseResult(warnings=["missing month"], confidence=0.0),
    )

    assert result.text == ""
    assert len(result.warnings) == 2
    assert "GPT" in result.warnings[0]
    assert "gpt failed" in result.warnings[0]
    assert "missing month" in result.warnings[1]


def test_parse_order_remark_auto_skips_gpt_when_ai_disabled():
    def forbidden_gpt(_remark):
        raise AssertionError("GPT should not be called")

    result = parse_order_remark_auto(
        "Name: Local June font 1 flower 1",
        ai_config=AIParseConfig(enabled=False, prefer_ai=True),
        gpt_parser=forbidden_gpt,
        local_parser=lambda remark: ParseResult(text="Local", month=6, font=1, flower=1, confidence=0.8),
    )

    assert result.text == "Local"
    assert result.warnings == []


def test_parse_order_remark_auto_skips_gpt_when_ai_is_not_preferred_even_if_local_is_incomplete():
    def forbidden_gpt(_remark):
        raise AssertionError("GPT should not be called")

    result = parse_order_remark_auto(
        "???",
        ai_config=AIParseConfig(enabled=True, prefer_ai=False),
        gpt_parser=forbidden_gpt,
        local_parser=lambda remark: ParseResult(warnings=["missing month"], confidence=0.0),
    )

    assert result.text == ""
    assert "GPT" not in " ".join(result.warnings)


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
        return ParseResult(text="AI", month=6, font=1, flower=1, confidence=0.9)

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
        local_parser=lambda remark: ParseResult(text="", month=None, font=None, flower=None, confidence=0.0),
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
