from __future__ import annotations

import re
import unicodedata

from app.domain import DomainError
from app.schemas.orders import FlowerChoice, FontPreference, ParsedOrder


MONTH_NAMES = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}

MONTH_ALIASES = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

FLOWERS_BY_MONTH = {
    1: {1: "Carnation", 2: "Snowdrop"},
    2: {1: "Violet", 2: "Primrose"},
    3: {1: "Daffodil", 2: "Cherry Blossom"},
    4: {1: "Daisy", 2: "Sweet Pea"},
    5: {1: "Lily of the Valley", 2: "Hawthorn"},
    6: {1: "Rose", 2: "Honeysuckle"},
    7: {1: "Waterlily", 2: "Larkspur"},
    8: {1: "Poppy", 2: "Gladiolus"},
    9: {1: "Aster", 2: "Morning Glory"},
    10: {1: "Marigold", 2: "Cosmos"},
    11: {1: "Chrysanthemum", 2: "Peony"},
    12: {1: "Holly", 2: "Narcissus"},
}

FIELD_LABELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("birth_flower", ("choose your birth flower", "birth flower", "出生花")),
    ("customer_name", ("customer name", "name", "personalization", "personalisation", "text", "客户名字", "客户姓名", "姓名", "名字", "刻字")),
    ("month", ("birth month", "month", "月份")),
    ("flower", ("flower", "花朵", "花")),
    ("font", ("font design", "font preference", "font", "字体偏好", "字体")),
    ("notes", ("special notes", "special requests", "notes", "remarks", "remark", "特殊备注", "备注", "要求")),
)


def parse_order_note(order_note: str, order_id: str | None = None) -> ParsedOrder:
    normalized_note = _normalize_digits(order_note)
    fields = _extract_fields(normalized_note)

    customer_name = _clean_text(fields.get("customer_name", ""))
    birth_flower_value = fields.get("birth_flower", "")
    month = _parse_month(fields.get("month", "")) or _parse_month(_birth_flower_month_part(birth_flower_value))
    flower = _parse_flower(fields.get("flower", "") or _birth_flower_flower_part(birth_flower_value), month)
    font_preference = _parse_font(fields.get("font", ""))
    special_notes = _clean_text(fields.get("notes", ""))

    missing_fields = _missing_fields(customer_name, month, flower, font_preference)
    if missing_fields:
        # 订单备注只作为预填草稿；字段缺失时必须让人工补齐，不能靠猜测继续生成。
        raise DomainError(
            code="ORDER_PARSE_FAILED",
            message="Order note cannot be parsed deterministically.",
            details={"missingFields": missing_fields},
            recoverable=True,
        )

    assert month is not None
    assert flower is not None
    assert font_preference is not None

    return ParsedOrder(
        orderId=order_id,
        customerName=customer_name,
        month=month,
        monthName=MONTH_NAMES[month],
        flower=flower,
        fontPreference=font_preference,
        specialNotes=special_notes,
    )


def _extract_fields(value: str) -> dict[str, str]:
    matches = list(_field_pattern().finditer(value))
    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        canonical = _canonical_label(match)
        if canonical is None:
            continue
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        fields[canonical] = value[match.end() : next_start].strip()
    return fields


def _field_pattern() -> re.Pattern[str]:
    parts: list[str] = []
    for index, (_canonical, labels) in enumerate(FIELD_LABELS):
        for label in sorted(labels, key=len, reverse=True):
            parts.append(f"(?P<label_{index}_{len(parts)}>{_label_pattern(label)})\\s*[:：=]")
    return re.compile("|".join(parts), re.IGNORECASE)


def _canonical_label(match: re.Match[str]) -> str | None:
    for name, value in match.groupdict().items():
        if value is None:
            continue
        label_index = int(name.split("_")[1])
        return FIELD_LABELS[label_index][0]
    return None


def _label_pattern(label: str) -> str:
    return r"\s+".join(re.escape(part) for part in label.split())


def _birth_flower_month_part(value: str) -> str:
    return re.split(r"\s*[-–—]\s*", value, maxsplit=1)[0].strip()


def _birth_flower_flower_part(value: str) -> str:
    parts = re.split(r"\s*[-–—]\s*", value, maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


def _parse_month(value: str) -> int | None:
    clean = _clean_text(value).casefold()
    if not clean:
        return None
    number_match = re.search(r"\b(1[0-2]|[1-9])\b", clean)
    if number_match:
        return int(number_match.group(1))
    for alias, month in sorted(MONTH_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", clean):
            return month
    return None


def _parse_flower(value: str, month: int | None) -> FlowerChoice | None:
    if month is None:
        return None
    clean = _clean_text(value)
    if not clean:
        return None
    number_match = re.search(r"\b([12])\b", clean)
    if number_match:
        choice = int(number_match.group(1))
        return FlowerChoice(choice=choice, name=FLOWERS_BY_MONTH[month][choice])

    compact_value = _compact(clean)
    for choice, name in FLOWERS_BY_MONTH[month].items():
        if _compact(name) in compact_value:
            return FlowerChoice(choice=choice, name=name)
    return None


def _parse_font(value: str) -> FontPreference | None:
    clean = _clean_text(value)
    match = re.search(r"\b(?:font\s*)?([1-8])\b", clean, flags=re.IGNORECASE)
    if not match:
        return None
    choice = int(match.group(1))
    return FontPreference(choice=choice, label=f"Font {choice}")


def _missing_fields(
    customer_name: str,
    month: int | None,
    flower: FlowerChoice | None,
    font_preference: FontPreference | None,
) -> list[str]:
    missing: list[str] = []
    if not customer_name:
        missing.append("customerName")
    if month is None:
        missing.append("month")
    if flower is None:
        missing.append("flower")
    if font_preference is None:
        missing.append("fontPreference")
    return missing


def _normalize_digits(value: str) -> str:
    chars: list[str] = []
    for char in value or "":
        try:
            chars.append(str(unicodedata.decimal(char)))
        except (TypeError, ValueError):
            chars.append(char)
    return "".join(chars)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" \t\r\n,;")


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())
