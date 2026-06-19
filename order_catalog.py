"""订单解析的「素材库目录」对接层（见 ExecPlan §6 / Task 3）。

核心思想：不再让模型猜写死的 month 1-12 / font 1-8，而是把**当前产品各素材库的目录**
（key + 显示名 + 别名 + 标签）注入 GPT prompt，让它在目录里选一个 `material_key`/`font_key`；
输出用「目录真实 key 集合」做**动态枚举**校验，拒绝臆造。新增素材只需往库里加文件/改 library.json，
**本地解析规则零硬编码**。

本模块刻意不改 `gpt_parser.py`（复用其 HTTP 辅助），也不改 `ui_app.py`（消费侧接线属 Phase 2）：
- `LibraryBundle`：一个产品可用的图像库 + 字体库集合，供解析器识别与回查。
- `build_prompt_catalog` / `build_order_remark_schema`：注入 GPT 的目录上下文 + 动态枚举 schema。
- `parse_catalog_payload`：校验模型输出（动态枚举）并落到具体素材。
- `enrich_parse_result`：把任意来源（GPT / 本地旧 month-flower）的 ParseResult 落到 material_key + 素材路径。
- `parse_order_remark_with_gpt_catalog`：catalog 版 GPT 调用（OpenAI / DeepSeek），复用 gpt_parser 辅助。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from typing import Any
from urllib import error

import gpt_parser as _gpt
from material_library import MaterialEntry, MaterialLibrary
from models import ParseResult


@dataclass(frozen=True)
class LibraryBundle:
    """一个产品可用的素材库/字体库集合，喂给解析器做识别与回查。"""

    image_libraries: tuple[MaterialLibrary, ...] = ()
    font_libraries: tuple[MaterialLibrary, ...] = ()

    @classmethod
    def from_dirs(
        cls,
        image_dirs: "tuple[Any, ...] | list[Any]" = (),
        font_dirs: "tuple[Any, ...] | list[Any]" = (),
    ) -> "LibraryBundle":
        """从配置里的目录列表（如 ProductConfig.image_library_dirs）一行建库集合。"""
        image = tuple(MaterialLibrary.from_folder(path, kind="image") for path in image_dirs)
        font = tuple(MaterialLibrary.from_folder(path, kind="font") for path in font_dirs)
        return cls(image_libraries=image, font_libraries=font)

    def image_keys(self) -> list[str]:
        return _union_keys(self.image_libraries)

    def font_keys(self) -> list[str]:
        return _union_keys(self.font_libraries)

    def resolve_material(self, query: str) -> tuple[str, MaterialEntry] | None:
        """按 key 精确 / 别名模糊在所有图像库里定位，返回 (library_id, entry)。"""
        return _resolve(self.image_libraries, query)

    def resolve_font(self, query: str) -> tuple[str, MaterialEntry] | None:
        return _resolve(self.font_libraries, query)

    def resolve_material_by_tags(self, **tags: Any) -> tuple[str, MaterialEntry] | None:
        """按标签（如 birth-flower 的 month+flower）定位素材，用于兼容旧解析输出。"""
        return _resolve_by_tags(self.image_libraries, tags)

    def resolve_font_by_tags(self, **tags: Any) -> tuple[str, MaterialEntry] | None:
        return _resolve_by_tags(self.font_libraries, tags)


# ---------------------------------------------------------------------- 解析输出富化
def enrich_parse_result(result: ParseResult, bundle: LibraryBundle) -> ParseResult:
    """把 ParseResult 落到具体素材/字体：填 library_id + key + 资产路径，并回填 month/flower。

    解析优先级（素材）：已有 material_key（动态枚举校验）→ flower_name 模糊匹配。
    **不再用出生月份+序号挑素材**：素材只按 key / 花名定位，月份不参与选素材（按需求 2026-06-18 调整）。
    字体仍按业务编号：font_key → font 编号标签 → font_design 模糊。命中不了不臆造，只在 key 非法时记 warning。
    幂等：重复富化结果不变（catalog GPT 路径内部已富化一次，pipeline 再富化一次也安全）。
    """
    warnings = list(result.warnings)

    # ---- 素材 ----
    material_library_id = result.material_library_id
    material_key = result.material_key
    selected_flower = result.selected_flower_asset
    month, flower = result.month, result.flower

    found: tuple[str, MaterialEntry] | None = None
    if material_key:
        found = bundle.resolve_material(material_key)
        if found is None:
            warnings.append(f"素材 key「{material_key}」不在当前产品素材库中，已忽略")
            material_key = ""
    # 只按花名匹配：月份不再参与选素材（旧的 resolve_material_by_tags(month,flower) 已移除）。
    if found is None and result.flower_name:
        found = bundle.resolve_material(result.flower_name)
    if found is not None:
        material_library_id, entry = found
        material_key = entry.key
        selected_flower = str(entry.path)
        if month is None:
            month = entry.tags.get("month", month)
        if flower is None:
            flower = entry.tags.get("flower", flower)

    # ---- 字体 ----
    font_library_id = result.font_library_id
    font_key = result.font_key
    selected_font = result.selected_font_asset
    font_num = result.font

    font_found: tuple[str, MaterialEntry] | None = None
    if font_key:
        font_found = bundle.resolve_font(font_key)
        if font_found is None:
            warnings.append(f"字体 key「{font_key}」不在当前产品字体库中，已忽略")
            font_key = ""
    if font_found is None and font_num is not None:
        font_found = bundle.resolve_font_by_tags(index=font_num)
    if font_found is None and result.font_design:
        font_found = bundle.resolve_font(result.font_design)
    if font_found is not None:
        font_library_id, font_entry = font_found
        font_key = font_entry.key
        selected_font = str(font_entry.path)
        if font_num is None:
            font_num = font_entry.tags.get("index", font_num)

    return replace(
        result,
        month=month,
        flower=flower,
        font=font_num,
        material_library_id=material_library_id,
        material_key=material_key,
        font_library_id=font_library_id,
        font_key=font_key,
        selected_flower_asset=selected_flower,
        selected_font_asset=selected_font,
        warnings=warnings,
    )


# ---------------------------------------------------------------------- GPT 目录注入
def build_prompt_catalog(bundle: LibraryBundle) -> dict[str, Any]:
    """把库摊平成给 GPT 的目录上下文：每库 {id,name,kind,items:[{key,name,aliases,tags}]}。"""
    return {
        "image_libraries": [_lib_catalog(lib) for lib in bundle.image_libraries],
        "font_libraries": [_lib_catalog(lib) for lib in bundle.font_libraries],
    }


def build_order_remark_schema(material_keys: list[str], font_keys: list[str]) -> dict[str, Any]:
    """动态枚举 schema：material_key/font_key 只允许目录里出现过的 key 或 null。"""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "text": {"type": "string"},
            "material_key": _nullable_enum(material_keys),
            "font_key": _nullable_enum(font_keys),
            "warnings": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["text", "material_key", "font_key", "warnings", "confidence"],
    }


def build_catalog_system_prompt(bundle: LibraryBundle) -> str:
    catalog_json = json.dumps(build_prompt_catalog(bundle), ensure_ascii=False)
    return (
        "你是雕刻订单备注解析器。从下面给定的【素材库目录】里为订单选出最匹配的素材与字体，输出 JSON。\n"
        "字段：text=要雕刻的姓名或文字；material_key=从图像库目录里选一个 key（只能用目录里出现过的 key）；"
        "font_key=从字体库目录里选一个 key；warnings=中文提示数组；confidence=0-1。\n"
        "若订单信息不足以确定素材/字体，对应字段填 null 并在 warnings 说明，严禁臆造目录里没有的 key。\n"
        f"素材库目录（JSON）：{catalog_json}"
    )


def parse_catalog_payload(payload: dict[str, Any], bundle: LibraryBundle) -> ParseResult:
    """校验 GPT JSON（动态枚举）并富化为 ParseResult；模型臆造的 key 被丢弃并记 warning。"""
    text = str(payload.get("text") or "").strip()
    image_keys = set(bundle.image_keys())
    font_keys = set(bundle.font_keys())
    raw_material = payload.get("material_key")
    raw_font = payload.get("font_key")
    material_key = raw_material if isinstance(raw_material, str) and raw_material in image_keys else ""
    font_key = raw_font if isinstance(raw_font, str) and raw_font in font_keys else ""

    raw_warnings = payload.get("warnings", [])
    warnings = [str(item) for item in raw_warnings if str(item).strip()] if isinstance(raw_warnings, list) else []
    if isinstance(raw_material, str) and raw_material and not material_key:
        warnings.append(f"模型返回的素材 key「{raw_material}」不在素材库目录中，已忽略")
    if isinstance(raw_font, str) and raw_font and not font_key:
        warnings.append(f"模型返回的字体 key「{raw_font}」不在字体库目录中，已忽略")

    result = ParseResult(
        text=text,
        material_key=material_key,
        font_key=font_key,
        warnings=warnings,
        confidence=_confidence(payload.get("confidence")),
    )
    return enrich_parse_result(result, bundle)


def parse_order_remark_with_gpt_catalog(
    remark: str,
    bundle: LibraryBundle,
    *,
    api_key: str | None = None,
    model: str | None = None,
    project: str | None = None,
    organization: str | None = None,
    provider: str | None = None,
    base_url: str | None = None,
    http_post: _gpt.HttpPost | None = None,
    timeout: float = 20,
) -> ParseResult:
    """catalog 版 GPT 调用：注入目录 + 动态枚举 schema，复用 gpt_parser 的 HTTP 辅助。"""
    selected_provider = _gpt._normalize_provider(provider)
    system_prompt = build_catalog_system_prompt(bundle)
    if selected_provider == "deepseek":
        return _catalog_with_deepseek(remark, bundle, system_prompt, api_key, model, base_url, http_post, timeout)
    if selected_provider != "openai":
        raise ValueError(f"不支持的 AI provider：{selected_provider}")

    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("未配置 OPENAI_API_KEY，无法调用 GPT 解析")
    selected_model = model or os.environ.get("OPENAI_MODEL", _gpt.DEFAULT_MODEL)
    schema = build_order_remark_schema(bundle.image_keys(), bundle.font_keys())
    payload = {
        "model": selected_model,
        "store": False,
        "max_output_tokens": _gpt.DEFAULT_MAX_OUTPUT_TOKENS,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": remark},
        ],
        "text": {
            "format": {"type": "json_schema", "name": "order_material_parse", "strict": True, "schema": schema}
        },
    }
    if _gpt._supports_reasoning(selected_model):
        payload["reasoning"] = {"effort": "minimal"}
    headers = _gpt._build_headers(key, project=project, organization=organization)
    try:
        response = (http_post or _gpt._http_post)(_gpt.OPENAI_RESPONSES_URL, payload, headers, timeout)
    except error.HTTPError as exc:
        raise RuntimeError(_gpt._format_http_error(exc, "OpenAI")) from exc
    return parse_catalog_payload(_gpt._extract_structured_payload(response), bundle)


def _catalog_with_deepseek(
    remark: str,
    bundle: LibraryBundle,
    system_prompt: str,
    api_key: str | None,
    model: str | None,
    base_url: str | None,
    http_post: _gpt.HttpPost | None,
    timeout: float,
) -> ParseResult:
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，无法调用 DeepSeek 解析")
    selected_model = model or os.environ.get("DEEPSEEK_MODEL", _gpt.DEFAULT_DEEPSEEK_MODEL)
    payload = {
        "model": selected_model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt + " 必须输出字段：text, material_key, font_key, warnings, confidence。",
            },
            {"role": "user", "content": remark},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "stream": False,
        "max_tokens": _gpt.DEFAULT_MAX_OUTPUT_TOKENS,
    }
    headers = _gpt._build_headers(key)
    try:
        response = (http_post or _gpt._http_post)(_gpt._deepseek_chat_url(base_url), payload, headers, timeout)
    except error.HTTPError as exc:
        raise RuntimeError(_gpt._format_http_error(exc, "DeepSeek")) from exc
    return parse_catalog_payload(_gpt._extract_chat_payload(response, "DeepSeek"), bundle)


# ---------------------------------------------------------------------- 小工具
def _union_keys(libraries: tuple[MaterialLibrary, ...]) -> list[str]:
    keys: list[str] = []
    for library in libraries:
        for entry in library.entries:
            if entry.key not in keys:
                keys.append(entry.key)
    return keys


def _resolve(libraries: tuple[MaterialLibrary, ...], query: str) -> tuple[str, MaterialEntry] | None:
    if not query:
        return None
    for library in libraries:  # 先全库精确 key
        entry = library.by_key(query)
        if entry is not None:
            return (library.id, entry)
    for library in libraries:  # 再全库别名/显示名模糊
        entry = next((item for item in library.entries if item.matches(query)), None)
        if entry is not None:
            return (library.id, entry)
    return None


def _resolve_by_tags(
    libraries: tuple[MaterialLibrary, ...], tags: dict[str, Any]
) -> tuple[str, MaterialEntry] | None:
    wanted = {key: value for key, value in tags.items() if value is not None}
    if not wanted:
        return None
    for library in libraries:
        for entry in library.entries:
            if all(entry.tags.get(key) == value for key, value in wanted.items()):
                return (library.id, entry)
    return None


def _lib_catalog(library: MaterialLibrary) -> dict[str, Any]:
    catalog = library.catalog()
    return {"id": library.id, "name": library.name, "kind": library.kind, "items": list(catalog.items)}


def _nullable_enum(keys: list[str]) -> dict[str, Any]:
    return {"type": ["string", "null"], "enum": [*keys, None]}


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return round(max(0.0, min(1.0, number)), 2)
