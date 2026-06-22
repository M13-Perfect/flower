from __future__ import annotations

import json
import os
from typing import Any, Callable
from urllib import error, request

from models import ParsePromptTrace, ParseResult


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5-nano"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_MAX_OUTPUT_TOKENS = 1200

# DeepSeek 不支持 json_schema，只能要 json_object；这段「顶层 orders + 字段列表」是发给它的
# system 提示词**真实追加的后缀**（机器 I/O 约定，非业务规则，按用户要求保留）。抽成常量是为了让
# 解析页可观测性显示的「本次提示词」与真正发送内容逐字一致（见 ParsePromptTrace）。
DEEPSEEK_ORDERS_JSON_SUFFIX = (
    ' 必须输出 JSON：{"orders":[...]}，每个元素含 order_number, quantity, month, '
    "flower_name, flower, font, text, gift_message, warnings, confidence。"
)


ORDER_REMARK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "text": {"type": "string"},
        "month": {"type": ["integer", "null"], "minimum": 1, "maximum": 12},
        "font": {"type": ["integer", "null"], "minimum": 1, "maximum": 4},
        "flower": {"type": ["integer", "null"], "minimum": 1, "maximum": 2},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["text", "month", "font", "flower", "warnings", "confidence"],
}

# 多订单 schema：一次粘贴可能含多笔订单（每块第一行=订单号），模型输出 orders 数组，每条一笔。
ORDER_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "order_number": {"type": "string"},
        "quantity": {"type": ["integer", "null"], "minimum": 1},
        "month": {"type": ["integer", "null"], "minimum": 1, "maximum": 12},
        "flower_name": {"type": "string"},
        "flower": {"type": ["integer", "null"], "minimum": 1, "maximum": 2},
        "font": {"type": ["integer", "null"], "minimum": 1, "maximum": 4},
        "text": {"type": "string"},
        "gift_message": {"type": "string"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "order_number", "quantity", "month", "flower_name", "flower",
        "font", "text", "gift_message", "warnings", "confidence",
    ],
}

ORDERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"orders": {"type": "array", "items": ORDER_ITEM_SCHEMA}},
    "required": ["orders"],
}

# 【已删除·本地业务规则提示词】原 ORDERS_PROMPT_SCAFFOLD（角色定义＋订单块格式＋输出字段＋warnings 规则）
# 与 DEFAULT_EXTRACTION_RULES 兜底文案曾写死在此处。按要求「解析不携带任何本地业务规则」已彻底删除：
# 多订单系统提示词现在 **100% 来自前台**（字段区规则 + 背景提示词框，见 ui_app._assemble_field_rules）。
# 机器 I/O 约定（让模型输出 orders 数组/字段名）不属于业务规则、按要求保留：
#   - OpenAI：由 ORDERS_SCHEMA（json_schema strict）强约束输出结构；
#   - DeepSeek：由 _parse_orders_with_deepseek 追加的「顶层 orders + 字段列表」提醒兜底。

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
        # 【已删除·本地业务规则】原 system 提示词（text/month/font/flower 语义、warnings 规则）已删除。
        # 单订单 OpenAI 路径输出结构由 ORDER_REMARK_SCHEMA（json_schema strict）保证，本地不再注入业务规则。
        "input": [
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
    font = _bounded_int(payload.get("font"), 1, 4)
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


def build_orders_system_prompt(
    rules: str | None = None, background_prompt: str | None = None
) -> str:
    """组装多订单系统提示词：**只拼接前台内容**（字段区规则 + 背景提示词），本地不再注入任何脚手架/业务规则。

    `rules` 来自前台字段区（ui_app._assemble_field_rules），`background_prompt` 来自背景提示词框；
    两者都为空时返回空串——此时输出结构仍由 OpenAI 的 ORDERS_SCHEMA / DeepSeek 的字段提醒保证。
    """
    prompt = (rules or "").strip()
    extra = (background_prompt or "").strip()
    if extra:
        prompt = f"{prompt}\n\n【背景】{extra}" if prompt else f"【背景】{extra}"
    return prompt


def parse_orders_with_gpt(
    remark: str,
    api_key: str | None = None,
    model: str | None = None,
    project: str | None = None,
    organization: str | None = None,
    provider: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    background_prompt: str | None = None,
    http_post: HttpPost | None = None,
    timeout: float = 20,
    trace: ParsePromptTrace | None = None,
) -> list[ParseResult]:
    """多订单版：一次解析含多笔订单的文本，返回 ParseResult 列表（每笔一条）。

    系统提示词来自前台「提取/背景提示词」（system_prompt/background_prompt），为空时回落默认提示词。
    传入 `trace`（空壳 ParsePromptTrace）时，把**实际发出**的 system 提示词 + 用户内容 + provider/model
    就地写回，供解析页可观测性展示（见 ③）；不传则零行为变化。
    """
    selected_provider = _normalize_provider(provider)
    prompt = build_orders_system_prompt(system_prompt, background_prompt)
    if selected_provider == "deepseek":
        return _parse_orders_with_deepseek(
            remark, prompt, api_key=api_key, model=model, base_url=base_url,
            http_post=http_post, timeout=timeout, trace=trace,
        )
    if selected_provider != "openai":
        raise ValueError(f"不支持的 AI provider：{selected_provider}")

    # 提示词不依赖密钥/模型，尽早写回 trace：即便后续因缺 key 抛错，解析页也能看到「本次提示词」。
    if trace is not None:
        trace.provider = "openai"
        trace.system_prompt = prompt
        trace.user_content = remark
        trace.filled = True
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("未配置 OPENAI_API_KEY，无法调用 GPT 解析")
    selected_model = model or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
    if trace is not None:
        trace.model = selected_model
    payload = {
        "model": selected_model,
        "store": False,
        "max_output_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
        "input": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": remark},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "birth_flower_orders_parse",
                "strict": True,
                "schema": ORDERS_SCHEMA,
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
    return parse_orders_payload(_extract_structured_payload(response))


def _parse_orders_with_deepseek(
    remark: str,
    system_prompt: str,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    http_post: HttpPost | None = None,
    timeout: float = 20,
    trace: ParsePromptTrace | None = None,
) -> list[ParseResult]:
    # 真正发给 DeepSeek 的 system 全文 = 前台提示词 + JSON 约定后缀；trace 也记这份全文（逐字一致）。
    full_system_prompt = system_prompt + DEEPSEEK_ORDERS_JSON_SUFFIX
    if trace is not None:
        trace.provider = "deepseek"
        trace.system_prompt = full_system_prompt
        trace.user_content = remark
        trace.filled = True
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，无法调用 DeepSeek 解析")
    selected_model = model or os.environ.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
    if trace is not None:
        trace.model = selected_model
    payload = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": full_system_prompt},
            {"role": "user", "content": remark},
        ],
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
    return parse_orders_payload(_extract_chat_payload(response, "DeepSeek"))


def parse_orders_payload(payload: dict[str, Any]) -> list[ParseResult]:
    """校验并转换多订单 JSON 为 ParseResult 列表；兼容模型偶尔直接返回单条对象。"""
    if not isinstance(payload, dict):
        return []
    raw_orders = payload.get("orders")
    if isinstance(raw_orders, list):
        return [_parse_order_item(item) for item in raw_orders if isinstance(item, dict)]
    # 容错：模型未包 orders 直接给了单条结果。
    if "text" in payload or "order_number" in payload or "flower" in payload:
        return [_parse_order_item(payload)]
    return []


def _parse_order_item(item: dict[str, Any]) -> ParseResult:
    """单条订单字段校验：越界数字裁成 None，字符串去空白，绝不信任模型原样输出。"""
    # 刻字内容：去首尾 + 把中间连续多空格/换行合并成单个空格（多余空格无效、不影响生产）。
    text = " ".join(str(item.get("text") or "").split())
    month = _bounded_int(item.get("month"), 1, 12)
    font = _bounded_int(item.get("font"), 1, 4)
    flower = _bounded_int(item.get("flower"), 1, 2)
    order_number = str(item.get("order_number") or "").strip()
    quantity = _bounded_int(item.get("quantity"), 1, 100000) or 1
    flower_name = str(item.get("flower_name") or "").strip()
    gift_message = str(item.get("gift_message") or "").strip()
    raw_warnings = item.get("warnings", [])
    warnings = (
        [str(w) for w in raw_warnings if str(w).strip()] if isinstance(raw_warnings, list) else []
    )
    try:
        confidence_number = float(item.get("confidence", 0))
    except (TypeError, ValueError):
        confidence_number = 0.0
    return ParseResult(
        text=text,
        month=month,
        font=font,
        flower=flower,
        flower_name=flower_name or None,
        order_number=order_number,
        quantity=quantity,
        gift_message=gift_message,
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
    # 【已删除·本地业务规则】原本写死 month=1-12 / flower=同月第几个花朵 / font 语义 / warnings 规则，已删除。
    # DeepSeek 单订单无 json_schema，这里**仅保留机器 I/O 约定**（输出 JSON 及字段名），不含任何业务规则。
    return "只输出 JSON，不要解释。必须包含字段：text, month, font, flower, warnings, confidence。"


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
