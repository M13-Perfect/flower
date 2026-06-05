from __future__ import annotations

import json
import os
from typing import Any, Callable
from urllib import error, request

from models import ParseResult


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5-nano"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_MAX_OUTPUT_TOKENS = 1200


ORDER_REMARK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "text": {"type": "string"},
        "month": {"type": ["integer", "null"], "minimum": 1, "maximum": 12},
        "font": {"type": ["integer", "null"], "minimum": 1, "maximum": 8},
        "flower": {"type": ["integer", "null"], "minimum": 1, "maximum": 2},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["text", "month", "font", "flower", "warnings", "confidence"],
}

HttpPost = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


def parse_order_remark_with_gpt(
    remark: str,
    api_key: str | None = None,
    model: str | None = None,
    project: str | None = None,
    organization: str | None = None,
    provider: str | None = None,
    base_url: str | None = None,
    http_post: HttpPost | None = None,
    timeout: float = 20,
) -> ParseResult:
    """调用 OpenAI Responses API 用结构化输出识别订单备注。"""
    selected_provider = _normalize_provider(provider)
    if selected_provider == "deepseek":
        return _parse_order_remark_with_deepseek(
            remark,
            api_key=api_key,
            model=model,
            base_url=base_url,
            http_post=http_post,
            timeout=timeout,
        )
    if selected_provider != "openai":
        raise ValueError(f"不支持的 AI provider：{selected_provider}")

    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("未配置 OPENAI_API_KEY，无法调用 GPT 解析")

    selected_model = model or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
    payload = {
        "model": selected_model,
        "store": False,
        # GPT-5 nano 会消耗推理预算；过低时可能只返回 reasoning 而没有结构化文本。
        "max_output_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
        "input": [
            {
                "role": "system",
                "content": (
                    "你是 Birth Flower 订单备注解析器。只提取客户要雕刻的信息，"
                    "输出 JSON。字段：text=姓名或要雕刻文字，month=1-12，"
                    "font=字体编号，flower=同月份第几个花朵素材 1-2。"
                    "缺失或不确定时填 null 并写入中文 warnings。"
                ),
            },
            {"role": "user", "content": remark},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "birth_flower_order_parse",
                "strict": True,
                "schema": ORDER_REMARK_SCHEMA,
            }
        },
    }
    if _supports_reasoning(selected_model):
        payload["reasoning"] = {"effort": "minimal"}
    headers = _build_headers(key, project=project, organization=organization)
    try:
        response = (http_post or _http_post)(OPENAI_RESPONSES_URL, payload, headers, timeout)
    except error.HTTPError as exc:
        raise RuntimeError(_format_http_error(exc, "OpenAI")) from exc
    return parse_gpt_payload(_extract_structured_payload(response))


def parse_gpt_payload(payload: dict[str, Any]) -> ParseResult:
    """校验并转换 GPT JSON 为 ParseResult，避免 UI 直接信任模型输出。"""
    text = str(payload.get("text") or "").strip()
    month = _bounded_int(payload.get("month"), 1, 12)
    font = _bounded_int(payload.get("font"), 1, 8)
    flower = _bounded_int(payload.get("flower"), 1, 2)
    raw_warnings = payload.get("warnings", [])
    warnings = [str(item) for item in raw_warnings if str(item).strip()] if isinstance(raw_warnings, list) else []
    confidence = payload.get("confidence", 0)
    try:
        confidence_number = float(confidence)
    except (TypeError, ValueError):
        confidence_number = 0.0
    return ParseResult(
        text=text,
        month=month,
        font=font,
        flower=flower,
        warnings=warnings,
        confidence=round(max(0.0, min(1.0, confidence_number)), 2),
    )


def _http_post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_order_remark_with_deepseek(
    remark: str,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    http_post: HttpPost | None = None,
    timeout: float = 20,
) -> ParseResult:
    """调用 DeepSeek Chat Completions；只用于解析草稿，最终生成仍需人工确认。"""
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，无法调用 DeepSeek 解析")

    selected_model = model or os.environ.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
    payload = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": _order_remark_system_prompt()},
            {"role": "user", "content": remark},
        ],
        # DeepSeek 当前兼容 JSON object，不支持 OpenAI Responses json_schema；本地再做字段校验。
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "stream": False,
        "max_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
    }
    headers = _build_headers(key)
    try:
        response = (http_post or _http_post)(_deepseek_chat_url(base_url), payload, headers, timeout)
    except error.HTTPError as exc:
        raise RuntimeError(_format_http_error(exc, "DeepSeek")) from exc
    return parse_gpt_payload(_extract_chat_payload(response, "DeepSeek"))


def _build_headers(api_key: str, project: str | None = None, organization: str | None = None) -> dict[str, str]:
    """生成 OpenAI 请求头；多项目账号可用环境变量明确路由到后台项目。"""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    project_value = project or os.environ.get("OPENAI_PROJECT")
    organization_value = organization or os.environ.get("OPENAI_ORG_ID")
    if project_value:
        headers["OpenAI-Project"] = project_value
    if organization_value:
        headers["OpenAI-Organization"] = organization_value
    return headers


def _format_http_error(exc: error.HTTPError, provider_label: str = "OpenAI") -> str:
    """保留 OpenAI 错误体，429 时区分额度不足、限流、项目权限等原因。"""
    request_id = exc.headers.get("x-request-id") if exc.headers else ""
    body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
    details = body.strip()
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {}
    api_error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(api_error, dict):
        parts = [
            str(api_error.get("type") or "").strip(),
            str(api_error.get("code") or "").strip(),
            str(api_error.get("message") or "").strip(),
        ]
        details = " - ".join(part for part in parts if part)
    message = f"{provider_label} API HTTP {exc.code}: {details or exc.reason}"
    if request_id:
        message = f"{message}; request_id={request_id}"
    return message


def _extract_chat_payload(response: dict[str, Any], provider_label: str) -> dict[str, Any]:
    choices = response.get("choices", [])
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return json.loads(content)
    raise ValueError(f"{provider_label} 响应中未找到 JSON 解析结果")


def _extract_structured_payload(response: dict[str, Any]) -> dict[str, Any]:
    incomplete_details = response.get("incomplete_details")
    if response.get("status") == "incomplete" or incomplete_details:
        reason = ""
        if isinstance(incomplete_details, dict):
            reason = str(incomplete_details.get("reason") or "").strip()
        output_types = _response_output_types(response)
        raise ValueError(
            "GPT 响应未完成"
            + (f"：{reason}" if reason else "")
            + (f"；output types: {', '.join(output_types)}" if output_types else "")
            + "；请提高 max_output_tokens 或降低 reasoning effort"
        )
    if isinstance(response.get("output_text"), str):
        return json.loads(response["output_text"])
    for item in response.get("output", []):
        for content in item.get("content", []):
            parsed = content.get("parsed")
            if isinstance(parsed, dict):
                return parsed
            json_payload = content.get("json")
            if isinstance(json_payload, dict):
                return json_payload
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return json.loads(text)
    output_types = _response_output_types(response)
    detail = f"；output types: {', '.join(output_types)}" if output_types else ""
    raise ValueError(f"GPT 响应中未找到结构化解析结果{detail}")


def _supports_reasoning(model_name: str) -> bool:
    clean = model_name.strip().casefold()
    return clean.startswith("gpt-5") or clean.startswith(("o1", "o3", "o4"))


def _normalize_provider(provider: str | None) -> str:
    value = (provider or os.environ.get("AI_PROVIDER") or "openai").strip().casefold()
    return value or "openai"


def _deepseek_chat_url(base_url: str | None) -> str:
    clean = (base_url or os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).strip().rstrip("/")
    if clean.endswith("/chat/completions"):
        return clean
    return f"{clean}/chat/completions"


def _order_remark_system_prompt() -> str:
    return (
        "你是 Birth Flower 订单备注解析器。只提取客户要雕刻的信息，输出 JSON。"
        "字段：text=姓名或要雕刻文字，month=1-12，font=字体编号，"
        "flower=同月份第几个花朵素材 1-2。缺失或不确定时填 null 并写入中文 warnings。"
        "必须输出字段：text, month, font, flower, warnings, confidence。"
    )


def _response_output_types(response: dict[str, Any]) -> list[str]:
    types: list[str] = []
    for item in response.get("output", []):
        item_type = item.get("type")
        if isinstance(item_type, str) and item_type not in types:
            types.append(item_type)
        for content in item.get("content", []):
            content_type = content.get("type")
            if isinstance(content_type, str) and content_type not in types:
                types.append(content_type)
    return types


def _bounded_int(value: Any, minimum: int, maximum: int) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < minimum or number > maximum:
        return None
    return number
