"""订单截图 → 视觉模型 → 结构化 ParseResult（见 2026-06-14 截图解析需求）。

现有解析只吃文本字符串；本模块新增「截图直解」：把图片 base64 成 data URL，
随 OpenAI Responses 的 input_image（或 DeepSeek 视觉的 image_url）一起送多模态模型，
**复用与文本路径完全相同的结构化输出 schema**，产出 UI 可直接消费的 ParseResult。

刻意不改 gpt_parser.py / ui_app.py：
- 复用 gpt_parser 的 HTTP 辅助（headers/post/extract/error）；
- UI 上的「选截图」按钮由 UI 线接（调本函数 → 复用 _apply_parse_result）；
- 不传 bundle：用 text/flower_name/font schema（只按花名配素材）；
- 传 bundle（order_catalog.LibraryBundle）：用 catalog 动态枚举 schema（material_key/font_key）。

注意：模型必须是**支持视觉**的型号（如 gpt-4o-mini）；纯文本型（gpt-5-nano 等）会拒图。
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any
from urllib import error

import gpt_parser as _gpt
from models import ParseResult
from order_catalog import (
    LibraryBundle,
    build_catalog_system_prompt,
    build_order_remark_schema,
    parse_catalog_payload,
)

# 视觉默认模型：必须支持图像输入；可被 settings/环境变量覆盖。
DEFAULT_VISION_MODEL = "gpt-4o-mini"
DEFAULT_DEEPSEEK_VISION_MODEL = "deepseek-vl2"

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
}

VISION_SYSTEM_PROMPT = (
    "你是 Birth Flower 订单截图解析器。看图，只提取客户要雕刻的信息，输出 JSON。"
    "字段：text=姓名或要雕刻文字，flower_name=客户选用的花名，font=字体编号。"
    "缺失或不确定时填 null 并写入中文 warnings。"
)

_USER_INSTRUCTION = "解析这张订单截图，只提取客户要雕刻的信息。"


def parse_order_screenshot_with_gpt(
    image: str | Path | bytes,
    *,
    bundle: LibraryBundle | None = None,
    api_key: str | None = None,
    model: str | None = None,
    project: str | None = None,
    organization: str | None = None,
    provider: str | None = None,
    base_url: str | None = None,
    http_post: _gpt.HttpPost | None = None,
    timeout: float = 30,
    mime: str | None = None,
) -> ParseResult:
    """把订单截图送视觉模型识别成 ParseResult。image 可为路径或原始字节。"""
    data_url = _image_data_url(image, mime)
    selected_provider = _gpt._normalize_provider(provider)
    if selected_provider == "deepseek":
        return _screenshot_with_deepseek(data_url, bundle, api_key, model, base_url, http_post, timeout)
    if selected_provider != "openai":
        raise ValueError(f"不支持的 AI provider：{selected_provider}")

    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("未配置 OPENAI_API_KEY，无法调用视觉解析")
    selected_model = model or os.environ.get("OPENAI_VISION_MODEL") or DEFAULT_VISION_MODEL
    system_prompt, schema = _prompt_and_schema(bundle)
    payload = {
        "model": selected_model,
        "store": False,
        "max_output_tokens": _gpt.DEFAULT_MAX_OUTPUT_TOKENS,
        "input": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": _USER_INSTRUCTION},
                    {"type": "input_image", "image_url": data_url},
                ],
            },
        ],
        "text": {
            "format": {"type": "json_schema", "name": "order_screenshot_parse", "strict": True, "schema": schema}
        },
    }
    if _gpt._supports_reasoning(selected_model):
        payload["reasoning"] = {"effort": "minimal"}
    headers = _gpt._build_headers(key, project=project, organization=organization)
    try:
        response = (http_post or _gpt._http_post)(_gpt.OPENAI_RESPONSES_URL, payload, headers, timeout)
    except error.HTTPError as exc:
        raise RuntimeError(_gpt._format_http_error(exc, "OpenAI")) from exc
    return _parse_payload(_gpt._extract_structured_payload(response), bundle)


def _screenshot_with_deepseek(
    data_url: str,
    bundle: LibraryBundle | None,
    api_key: str | None,
    model: str | None,
    base_url: str | None,
    http_post: _gpt.HttpPost | None,
    timeout: float,
) -> ParseResult:
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，无法调用视觉解析")
    selected_model = model or os.environ.get("DEEPSEEK_VISION_MODEL") or DEFAULT_DEEPSEEK_VISION_MODEL
    system_prompt, _schema = _prompt_and_schema(bundle)
    payload = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": system_prompt + " 必须输出 JSON。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _USER_INSTRUCTION},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
        "max_tokens": _gpt.DEFAULT_MAX_OUTPUT_TOKENS,
    }
    headers = _gpt._build_headers(key)
    try:
        response = (http_post or _gpt._http_post)(_gpt._deepseek_chat_url(base_url), payload, headers, timeout)
    except error.HTTPError as exc:
        raise RuntimeError(_gpt._format_http_error(exc, "DeepSeek")) from exc
    return _parse_payload(_gpt._extract_chat_payload(response, "DeepSeek"), bundle)


def _prompt_and_schema(bundle: LibraryBundle | None) -> tuple[str, dict[str, Any]]:
    """有 bundle 走 catalog 动态枚举 schema，否则旧 month/font/flower schema。"""
    if bundle is not None:
        prompt = build_catalog_system_prompt(bundle) + "\n（输入是订单截图，请看图在目录里选 key。）"
        return prompt, build_order_remark_schema(bundle.image_keys(), bundle.font_keys())
    return VISION_SYSTEM_PROMPT, _gpt.ORDER_REMARK_SCHEMA


def _parse_payload(payload: dict[str, Any], bundle: LibraryBundle | None) -> ParseResult:
    if bundle is not None:
        return parse_catalog_payload(payload, bundle)
    return _gpt.parse_gpt_payload(payload)


def _image_data_url(image: str | Path | bytes, mime: str | None) -> str:
    if isinstance(image, (bytes, bytearray)):
        raw = bytes(image)
        resolved_mime = mime or "image/png"
    else:
        path = Path(image)
        raw = path.read_bytes()
        resolved_mime = mime or _MIME_BY_SUFFIX.get(path.suffix.casefold(), "image/png")
    return f"data:{resolved_mime};base64,{base64.b64encode(raw).decode('ascii')}"
