from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from models import ParseResult


_FIELD_RE = re.compile(
    r"(?:\b(?:name|text|tên|ten|nama)\b|personalization|personalisation|姓名|ชื่อ)\s*[:=：]?\s*",
    re.IGNORECASE,
)

_FONT_LABELS = ("font", "字体", "ฟอนต์", "phông", "phong")
_FLOWER_LABELS = ("flower", "花", "ดอกไม้", "bunga")

_ORDER_FIELD_LABELS = (
    ("birth_flower", "Choose Your Birth Flower"),
    ("birth_flower", "Birth Flower"),
    ("birth_month", "Birth Month"),
    ("font_design", "Font Design"),
    ("personalization", "Personalization"),
    ("personalization", "Personalisation"),
    ("personalization", "Gift Message"),
    ("personalization", "Message"),
    ("personalization", "Name"),
    ("font_design", "Font"),
)

_ORDER_FIELD_RE = re.compile(
    "|".join(
        rf"(?P<label_{index}>{re.escape(label).replace(r'\ ', r'\s+')})\s*[:\uFF1A]"
        for index, (_canonical, label) in enumerate(_ORDER_FIELD_LABELS)
    ),
    re.IGNORECASE,
)

_MONTH_NUMBER_TO_SHORT = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}

_BIRTH_FLOWER_NAMES = {
    1: ((1, ("snowdrop",)), (2, ("carnation",))),
    2: ((1, ("violet",)), (2, ("primrose",))),
    3: ((1, ("daffodil",)), (2, ("cherry blossom", "cherry"))),
    4: ((1, ("daisy",)), (2, ("sweetpea", "sweet pea"))),
    5: ((1, ("lily of the valley", "lilyofthevalley")), (2, ("hawthorn",))),
    6: ((1, ("rose",)), (2, ("honeysuckle", "honey suckle"))),
    7: ((1, ("waterlily", "water lily")), (2, ("larkspur",))),
    8: ((1, ("poppy",)), (2, ("gladiolus",))),
    9: ((1, ("aster",)), (2, ("morning glory", "morningglory"))),
    10: ((1, ("marigold",)), (2, ("cosmos",))),
    11: ((1, ("chrysanthemum",)), (2, ("peony",))),
    12: ((1, ("holly",)), (2, ("narcissus",))),
}

_MONTH_PHRASES = {
    # 英文月份
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
    # 中文月份
    "一月": 1,
    "二月": 2,
    "三月": 3,
    "四月": 4,
    "五月": 5,
    "六月": 6,
    "七月": 7,
    "八月": 8,
    "九月": 9,
    "十月": 10,
    "十一月": 11,
    "十二月": 12,
    # 泰语月份
    "มกราคม": 1,
    "ม.ค.": 1,
    "กุมภาพันธ์": 2,
    "ก.พ.": 2,
    "มีนาคม": 3,
    "มี.ค.": 3,
    "เมษายน": 4,
    "เม.ย.": 4,
    "พฤษภาคม": 5,
    "พ.ค.": 5,
    "มิถุนายน": 6,
    "มิ.ย.": 6,
    "กรกฎาคม": 7,
    "ก.ค.": 7,
    "สิงหาคม": 8,
    "ส.ค.": 8,
    "กันยายน": 9,
    "ก.ย.": 9,
    "ตุลาคม": 10,
    "ต.ค.": 10,
    "พฤศจิกายน": 11,
    "พ.ย.": 11,
    "ธันวาคม": 12,
    "ธ.ค.": 12,
    # 越南语月份
    "tháng giêng": 1,
    "tháng một": 1,
    "thang mot": 1,
    "tháng hai": 2,
    "thang hai": 2,
    "tháng ba": 3,
    "thang ba": 3,
    "tháng tư": 4,
    "thang tu": 4,
    "tháng bốn": 4,
    "thang bon": 4,
    "tháng năm": 5,
    "thang nam": 5,
    "tháng sáu": 6,
    "thang sau": 6,
    "tháng bảy": 7,
    "thang bay": 7,
    "tháng tám": 8,
    "thang tam": 8,
    "tháng chín": 9,
    "thang chin": 9,
    "tháng mười": 10,
    "thang muoi": 10,
    "tháng mười một": 11,
    "thang muoi mot": 11,
    "tháng mười hai": 12,
    "thang muoi hai": 12,
    # 印尼语月份
    "januari": 1,
    "februari": 2,
    "maret": 3,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "agustus": 8,
    "oktober": 10,
    "desember": 12,
}

_TEXT_STOP_TOKENS = tuple(
    sorted(
        set(_MONTH_PHRASES)
        | {"font", "flower", "month", "months", "เดือน", "tháng", "thang", "bulan"}
        | set(_FONT_LABELS)
        | set(_FLOWER_LABELS),
        key=len,
        reverse=True,
    )
)


def normalize_unicode_digits(value: str) -> str:
    """把全角、泰语、阿拉伯等 Unicode 数字统一成 ASCII 数字。"""
    normalized: list[str] = []
    for char in value:
        try:
            normalized.append(str(unicodedata.decimal(char)))
        except (TypeError, ValueError):
            normalized.append(char)
    return "".join(normalized)


def parse_order_remark(remark: str) -> ParseResult:
    """解析订单备注；结果只作为 UI 预填，最终生成仍需人工确认。"""
    raw_remark = remark or ""
    normalized = normalize_unicode_digits(raw_remark)
    warnings: list[str] = []
    order_fields = _extract_order_fields(raw_remark)
    structured_mode = _uses_structured_order_fields(order_fields)

    text = _extract_text(normalized)
    searchable = _remove_extracted_text(normalized, text)
    month = _extract_month(searchable)
    font, font_warning = _extract_number_choice(
        searchable,
        _FONT_LABELS,
        valid_values={1, 2, 3, 4},
        missing_warning="未识别 font 1-4",
        invalid_warning="font 只能是 1-4",
    )
    flower, flower_warning, inferred_month = _extract_flower_choice(searchable, month)
    if month is None and inferred_month is not None:
        month = inferred_month

    structured = _structured_values_from_fields(order_fields)
    if structured_mode and structured["personalization_raw"]:
        text = structured["personalization_raw"] or ""
    if structured_mode and structured["month"] is not None:
        month = structured["month"]  # type: ignore[assignment]
    if structured_mode and structured["font"] is not None:
        font = structured["font"]  # type: ignore[assignment]
        font_warning = None
    if structured_mode and structured["flower"] is not None:
        flower = structured["flower"]  # type: ignore[assignment]
        flower_warning = None

    if not text:
        warnings.append("未识别 Name/Text/姓名/ชื่อ/tên/nama")
    if month is None:
        warnings.append("未识别月份")
    if font_warning:
        warnings.append(font_warning)
    if flower_warning:
        warnings.append(flower_warning)

    parse_confidence = _calculate_structured_parse_confidence(
        structured["birth_month"],
        structured["flower_name"],
        structured["font_design"],
        structured["personalization_raw"],
        warnings,
    )
    if not structured_mode:
        parse_confidence = _calculate_confidence(text, month, font, flower, warnings)
    asset_confidence = _calculate_asset_confidence(
        structured["selected_flower_asset"],
        structured["selected_font_asset"],
        structured["birth_month"],
        structured["flower_name"],
        structured["font_design"],
        warnings,
    )
    return ParseResult(
        text=text,
        month=month,
        font=font,
        flower=flower,
        warnings=warnings,
        confidence=parse_confidence,
        birth_month=structured["birth_month"] if structured_mode else None,
        flower_name=structured["flower_name"] if structured_mode else None,
        font_design=structured["font_design"] if structured_mode else None,
        personalization_raw=structured["personalization_raw"] if structured_mode else None,
        personalization_type=(structured["personalization_type"] if structured_mode else "unknown") or "unknown",
        selected_flower_asset=structured["selected_flower_asset"] if structured_mode else None,
        selected_font_asset=structured["selected_font_asset"] if structured_mode else None,
        parse_confidence=parse_confidence,
        asset_confidence=asset_confidence,
    )


def _extract_order_fields(value: str) -> dict[str, str]:
    """按字段标签边界切片，保留字段内部的原始 Unicode 文本。"""
    matches = list(_ORDER_FIELD_RE.finditer(value or ""))
    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        canonical = _canonical_order_label(match)
        if canonical is None:
            continue
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        fields[canonical] = value[match.end() : next_start].strip()
    return fields


def _canonical_order_label(match: re.Match[str]) -> str | None:
    for index, (canonical, _label) in enumerate(_ORDER_FIELD_LABELS):
        if match.group(f"label_{index}") is not None:
            return canonical
    return None


def _uses_structured_order_fields(fields: dict[str, str]) -> bool:
    return any(key in fields for key in ("birth_flower", "birth_month", "font_design"))


def _structured_values_from_fields(fields: dict[str, str]) -> dict[str, object]:
    birth_flower_value = fields.get("birth_flower", "")
    birth_month_value = fields.get("birth_month", "")
    font_design_value = fields.get("font_design", "")
    personalization_raw = fields.get("personalization")

    month_text, flower_name = _split_birth_flower_value(birth_flower_value)
    if not month_text and birth_month_value:
        month_text = birth_month_value.strip()
    month = _extract_month(month_text) if month_text else None
    birth_month = _MONTH_NUMBER_TO_SHORT.get(month) if month is not None else None

    flower = _flower_number_from_name(month, flower_name)
    font = _font_number_from_design(font_design_value)
    font_design = f"Font {font}" if font is not None else (font_design_value.strip() or None)

    selected_flower_asset = _selected_flower_asset(month, flower)
    selected_font_asset = _selected_font_asset(font)
    return {
        "birth_month": birth_month,
        "flower_name": flower_name or None,
        "font_design": font_design,
        "personalization_raw": personalization_raw,
        "personalization_type": _classify_personalization(personalization_raw),
        "selected_flower_asset": selected_flower_asset,
        "selected_font_asset": selected_font_asset,
        "month": month,
        "font": font,
        "flower": flower,
    }


def _split_birth_flower_value(value: str) -> tuple[str, str]:
    clean_value = value.strip()
    if not clean_value:
        return "", ""
    parts = re.split(r"\s*[-\u2013\u2014]\s*", clean_value, maxsplit=1)
    if len(parts) == 1:
        return parts[0].strip(), ""
    return parts[0].strip(), parts[1].strip()


def _font_number_from_design(value: str) -> int | None:
    match = re.search(r"\bfont\s*([1-8])\b", value or "", flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _flower_number_from_name(month: int | None, flower_name: str) -> int | None:
    if month is None or not flower_name.strip():
        return None
    matched = _match_flower_name(flower_name, month)
    return matched[1] if matched is not None else None


def _classify_personalization(value: str | None) -> str:
    if value is None or not value.strip():
        return "unknown"
    text = value.strip()
    words = re.findall(r"[\w']+", text, flags=re.UNICODE)
    has_sentence_punctuation = re.search(r"[.!?;\u3002\uff01\uff1f\u2026]", text) is not None
    if len(words) >= 5 or (has_sentence_punctuation and len(words) >= 3):
        return "message"
    return "name"


def _selected_flower_asset(month: int | None, flower: int | None) -> str | None:
    if month is None or flower is None:
        return None
    try:
        from asset_resolver import find_flower_asset
    except ImportError:
        return None
    asset_dir = Path(__file__).resolve().parent / "BirthMonth flowers"
    asset = find_flower_asset(asset_dir, month, flower)
    return str(asset.path) if asset is not None else None


def _selected_font_asset(font: int | None) -> str | None:
    if font is None:
        return None
    font_path = Path(__file__).resolve().parent / "Birthmonth_font.ttf"
    if 1 <= font <= 8 and font_path.exists():
        return str(font_path)
    return None


def _calculate_structured_parse_confidence(
    birth_month: object,
    flower_name: object,
    font_design: object,
    personalization_raw: object,
    warnings: list[str],
) -> float:
    score = 1.0
    if not birth_month or not flower_name:
        score -= 0.35
    if not font_design:
        score -= 0.25
    if not personalization_raw:
        score -= 0.30
    score -= len(warnings) * 0.05
    if warnings:
        score = min(score, 0.99)
    return round(max(0.0, min(1.0, score)), 2)


def _calculate_asset_confidence(
    selected_flower_asset: object,
    selected_font_asset: object,
    birth_month: object,
    flower_name: object,
    font_design: object,
    warnings: list[str],
) -> float:
    score = 1.0
    if birth_month or flower_name:
        if not selected_flower_asset:
            score -= 0.45
    if font_design and not selected_font_asset:
        score -= 0.35
    score -= len(warnings) * 0.03
    if warnings:
        score = min(score, 0.99)
    return round(max(0.0, min(1.0, score)), 2)


def _extract_text(value: str) -> str:
    match = _FIELD_RE.search(value)
    if not match:
        return ""

    candidate = value[match.end() :].strip()
    if not candidate:
        return ""

    # 字段值通常在分隔符、月份或 font/flower 之前结束。
    stop_at = len(candidate)
    for separator in (",", ";", "，", "；", "\n", "\r"):
        index = candidate.find(separator)
        if index >= 0:
            stop_at = min(stop_at, index)

    candidate_key = candidate.casefold()
    for token in _TEXT_STOP_TOKENS:
        index = candidate_key.find(token.casefold())
        if index > 0:
            stop_at = min(stop_at, index)

    numeric_month = re.search(r"\b(1[0-2]|[1-9])\s*月", candidate_key)
    if numeric_month and numeric_month.start() > 0:
        stop_at = min(stop_at, numeric_month.start())

    return candidate[:stop_at].strip(" \t\r\n:=：,;，；")


def _remove_extracted_text(value: str, text: str) -> str:
    """移除已识别的雕刻文字，避免客户名被当成月份或花名。"""
    if not text:
        return value
    field_match = _FIELD_RE.search(value)
    if not field_match:
        return value
    index = value.casefold().find(text.casefold(), field_match.end())
    if index < 0:
        return value
    return value[:index] + value[index + len(text) :]


def _extract_month(value: str) -> int | None:
    key = value.casefold()

    # 数字月份必须带 month/月/เดือน/tháng/bulan 等上下文，避免误把 font/flower 当月份。
    numeric_patterns = (
        r"(?:month|months|เดือน|tháng|thang|bulan)\s*[:=：]?\s*(1[0-2]|[1-9])\b",
        r"\b(1[0-2]|[1-9])\s*月",
    )
    for pattern in numeric_patterns:
        match = re.search(pattern, key, re.IGNORECASE)
        if match:
            return int(match.group(1))

    for phrase, month in sorted(_MONTH_PHRASES.items(), key=lambda item: len(item[0]), reverse=True):
        if _phrase_in_text(key, phrase):
            return month
    return None


def _phrase_in_text(value: str, phrase: str) -> bool:
    phrase_key = phrase.casefold()
    if re.fullmatch(r"[a-z. ]+", phrase_key):
        return re.search(rf"(?<![a-z]){re.escape(phrase_key)}(?![a-z])", value) is not None
    return phrase_key in value


def _extract_number_choice(
    value: str,
    labels: tuple[str, ...],
    valid_values: set[int],
    missing_warning: str,
    invalid_warning: str,
) -> tuple[int | None, str | None]:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{label_pattern})\s*[:=#：-]?\s*(\d+)", value, re.IGNORECASE)
    if not match:
        return None, missing_warning

    number = int(match.group(1))
    if number not in valid_values:
        return None, invalid_warning
    return number, None


def _extract_flower_choice(value: str, month: int | None) -> tuple[int | None, str | None, int | None]:
    number, warning = _extract_number_choice(
        value,
        _FLOWER_LABELS,
        valid_values={1, 2},
        missing_warning="未识别 flower 1-2",
        invalid_warning="flower 只能是 1-2",
    )
    if number is not None or warning == "flower 只能是 1-2":
        return number, warning, None

    matched = _match_flower_name(value, month)
    if matched is None:
        return None, warning, None
    matched_month, flower = matched
    return flower, None, matched_month


def _match_flower_name(value: str, month: int | None) -> tuple[int, int] | None:
    compact_value = _compact_text(value)
    options: list[tuple[int, int, tuple[str, ...]]] = []
    if month is not None:
        options = [(month, flower, aliases) for flower, aliases in _BIRTH_FLOWER_NAMES.get(month, ())]
    else:
        for option_month, flowers in _BIRTH_FLOWER_NAMES.items():
            options.extend((option_month, flower, aliases) for flower, aliases in flowers)

    alias_hits: list[tuple[int, int, int]] = []
    for option_month, flower, aliases in options:
        for alias in aliases:
            alias_key = _compact_text(alias)
            if alias_key and alias_key in compact_value:
                alias_hits.append((len(alias_key), option_month, flower))
    if not alias_hits:
        return None
    _, matched_month, matched_flower = max(alias_hits)
    return matched_month, matched_flower


def _compact_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _calculate_confidence(
    text: str,
    month: int | None,
    font: int | None,
    flower: int | None,
    warnings: list[str],
) -> float:
    found_count = sum((bool(text), month is not None, font is not None, flower is not None))
    score = found_count / 4
    score -= len(warnings) * 0.05
    return round(max(0.0, min(1.0, score)), 2)
