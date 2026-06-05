from io import BytesIO

import pytest
from urllib.error import HTTPError

from gpt_parser import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_MODEL,
    OPENAI_RESPONSES_URL,
    parse_gpt_payload,
    parse_order_remark_with_gpt,
)


def test_parse_gpt_payload_returns_parse_result():
    result = parse_gpt_payload(
        {
            "text": "Vivian",
            "month": 6,
            "font": 1,
            "flower": 1,
            "warnings": [],
            "confidence": 0.96,
        }
    )

    assert result.text == "Vivian"
    assert result.month == 6
    assert result.font == 1
    assert result.flower == 1
    assert result.confidence == 0.96


def test_openai_responses_url_is_endpoint_not_secret():
    assert OPENAI_RESPONSES_URL == "https://api.openai.com/v1/responses"
    assert not OPENAI_RESPONSES_URL.startswith("sk-")


def test_default_model_uses_low_cost_test_model():
    assert DEFAULT_MODEL == "gpt-5-nano"


def test_default_deepseek_profile_uses_current_fast_model():
    assert DEFAULT_DEEPSEEK_BASE_URL == "https://api.deepseek.com"
    assert DEFAULT_DEEPSEEK_MODEL == "deepseek-v4-flash"


def test_parse_order_remark_with_gpt_uses_structured_outputs():
    calls = []

    def fake_http_post(url, payload, headers, timeout):
        calls.append((url, payload, headers, timeout))
        return {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"text":"Louise","month":6,"font":1,"flower":1,"warnings":[],"confidence":0.94}',
                        }
                    ]
                }
            ]
        }

    result = parse_order_remark_with_gpt("for Louise, June flower one", api_key="sk-test", http_post=fake_http_post)

    assert result.text == "Louise"
    assert result.month == 6
    assert calls[0][0].endswith("/v1/responses")
    assert calls[0][1]["text"]["format"]["type"] == "json_schema"
    assert calls[0][1]["text"]["format"]["strict"] is True
    assert "OPENAI_API_KEY" not in calls[0][2]["Authorization"]
    assert calls[0][1]["max_output_tokens"] >= 1000
    assert calls[0][1]["reasoning"]["effort"] == "minimal"


def test_parse_order_remark_with_gpt_can_call_deepseek_chat_completions():
    calls = []

    def fake_http_post(url, payload, headers, timeout):
        calls.append((url, payload, headers, timeout))
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"text":"Chen","month":6,"font":1,"flower":1,"warnings":[],"confidence":0.88}'
                    }
                }
            ]
        }

    result = parse_order_remark_with_gpt(
        "Name: Chen June font 1 flower 1",
        api_key="ds-test",
        model="deepseek-v4-flash",
        provider="deepseek",
        base_url="https://api.deepseek.com",
        http_post=fake_http_post,
    )

    assert result.text == "Chen"
    assert result.month == 6
    assert calls[0][0] == "https://api.deepseek.com/chat/completions"
    assert calls[0][1]["model"] == "deepseek-v4-flash"
    assert calls[0][1]["response_format"]["type"] == "json_object"
    assert calls[0][1]["thinking"]["type"] == "disabled"
    assert calls[0][1]["stream"] is False
    assert calls[0][2]["Authorization"] == "Bearer ds-test"
    assert "OpenAI-Project" not in calls[0][2]


def test_parse_order_remark_with_gpt_omits_reasoning_for_non_reasoning_models():
    calls = []

    def fake_http_post(url, payload, headers, timeout):
        calls.append((url, payload, headers, timeout))
        return {"output_text": '{"text":"Louise","month":6,"font":1,"flower":1,"warnings":[],"confidence":0.94}'}

    parse_order_remark_with_gpt(
        "for Louise, June flower one",
        api_key="sk-test",
        model="gpt-4o-mini",
        http_post=fake_http_post,
    )

    assert "reasoning" not in calls[0][1]


def test_parse_order_remark_with_gpt_can_send_project_and_org_headers(monkeypatch):
    calls = []
    monkeypatch.setenv("OPENAI_PROJECT", "proj_test")
    monkeypatch.setenv("OPENAI_ORG_ID", "org_test")

    def fake_http_post(url, payload, headers, timeout):
        calls.append((url, payload, headers, timeout))
        return {"output_text": '{"text":"Louise","month":6,"font":1,"flower":1,"warnings":[],"confidence":0.94}'}

    parse_order_remark_with_gpt("for Louise, June flower one", api_key="sk-test", http_post=fake_http_post)

    assert calls[0][2]["OpenAI-Project"] == "proj_test"
    assert calls[0][2]["OpenAI-Organization"] == "org_test"


def test_parse_order_remark_with_gpt_includes_openai_error_body():
    def rate_limited(_url, _payload, _headers, _timeout):
        raise HTTPError(
            url=OPENAI_RESPONSES_URL,
            code=429,
            msg="Too Many Requests",
            hdrs={"x-request-id": "req_test"},
            fp=BytesIO(
                b'{"error":{"message":"You exceeded your current quota","type":"insufficient_quota","code":"insufficient_quota"}}'
            ),
        )

    with pytest.raises(RuntimeError) as exc_info:
        parse_order_remark_with_gpt("Name: Vivian June font 1 flower 1", api_key="sk-test", http_post=rate_limited)

    message = str(exc_info.value)
    assert "OpenAI API HTTP 429" in message
    assert "insufficient_quota" in message
    assert "You exceeded your current quota" in message
    assert "req_test" in message


def test_parse_order_remark_with_gpt_reports_incomplete_response_reason():
    def incomplete(_url, _payload, _headers, _timeout):
        return {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"type": "reasoning"}],
        }

    with pytest.raises(ValueError) as exc_info:
        parse_order_remark_with_gpt("Name: Vivian June font 1 flower 1", api_key="sk-test", http_post=incomplete)

    message = str(exc_info.value)
    assert "max_output_tokens" in message
    assert "reasoning" in message


def test_parse_order_remark_with_gpt_prefers_explicit_project_and_org(monkeypatch):
    calls = []
    monkeypatch.setenv("OPENAI_PROJECT", "proj_env")
    monkeypatch.setenv("OPENAI_ORG_ID", "org_env")

    def fake_http_post(url, payload, headers, timeout):
        calls.append((url, payload, headers, timeout))
        return {"output_text": '{"text":"Mina","month":5,"font":1,"flower":1,"warnings":[],"confidence":0.9}'}

    parse_order_remark_with_gpt(
        "Mina May font 1 flower 1",
        api_key="sk-test",
        model="gpt-5-nano",
        project="proj_ui",
        organization="org_ui",
        http_post=fake_http_post,
    )

    assert calls[0][2]["OpenAI-Project"] == "proj_ui"
    assert calls[0][2]["OpenAI-Organization"] == "org_ui"
