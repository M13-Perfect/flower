from __future__ import annotations

from dataclasses import replace
import re

from app.domain import DomainError
from app.domain.orders.batch_import import BatchOrderItem
from app.domain.orders.issues import ReviewIssue
from app.domain.orders.parser import FLOWERS_BY_MONTH, MONTH_ALIASES, MONTH_NAMES, parse_order_note
from app.schemas.orders import FlowerChoice, FontPreference, ParsedOrder


def review_imported_item(item: BatchOrderItem) -> BatchOrderItem:
    if item.issues:
        return item

    combined = "\n".join(
        part for part in [item.order_note, item.personalization, item.variation] if part
    )
    customer_name = _extract_customer_name(combined)
    month = _extract_month(combined)
    flower = _extract_flower(combined, month)
    color = _extract_labeled_value(combined, ("color",))
    font_option_no = _extract_font_option(combined)
    issues: list[ReviewIssue] = []

    if _mentions_custom_flower(combined):
        issues.append(
            ReviewIssue(
                code="CUSTOM_FLOWER_REQUIRED",
                severity="blocking",
                field="flower",
                message="My Own Design/custom flower requires manual confirmation.",
                raw_value=_custom_flower_raw_value(combined) or flower,
                requires_manual_action=True,
            )
        )

    if _mentions_picture_font_reference(combined):
        issues.append(
            ReviewIssue(
                code="FONT_REFERENCE_REQUIRES_REVIEW",
                severity="blocking",
                field="font",
                message="Order references a font from a picture and cannot be resolved deterministically.",
                raw_value=_picture_font_raw_value(combined),
                requires_manual_action=True,
            )
        )

    labeled_personalization = _extract_labeled_value(
        combined, ("personalization", "personalisation")
    )
    if _looks_like_date(item.personalization) or _looks_like_date(labeled_personalization):
        issues.append(
            ReviewIssue(
                code="PERSONALIZATION_ROLE_AMBIGUOUS",
                severity="warning",
                field="personalization",
                message="Personalization looks like a date and must be confirmed against the template role.",
                raw_value=item.personalization or labeled_personalization,
                requires_manual_action=True,
            )
        )

    parsed_order = None
    if not issues:
        try:
            parsed_order = parse_order_note(combined, item.order_id)
        except DomainError as exc:
            issues.append(
                ReviewIssue(
                    code=exc.code,
                    severity="blocking",
                    field=None,
                    message=exc.message,
                    requires_manual_action=True,
                )
            )
        else:
            customer_name = parsed_order.customer_name
            month = parsed_order.month
            flower = parsed_order.flower.name if parsed_order.flower else None
            font_option_no = (
                parsed_order.font_preference.choice if parsed_order.font_preference else None
            )

    return replace(
        item,
        status=_status_for_issues(issues, parsed_order is not None),
        customer_name=customer_name,
        month=month,
        flower=flower,
        color=color,
        font_option_no=font_option_no,
        issues=issues,
        parsed_order=parsed_order,
    )


def apply_review_decision(
    item: BatchOrderItem,
    *,
    customer_name: str | None,
    month: int | None,
    flower: str | None,
    color: str | None,
    font_option_no: int | None,
    font_id: str | None,
    personalization_role: str | None = None,
) -> BatchOrderItem:
    next_customer_name = customer_name or item.customer_name
    next_month = month if month is not None else item.month
    next_flower = flower or item.flower
    next_color = color or item.color
    next_font_option_no = font_option_no if font_option_no is not None else item.font_option_no
    next_font_id = font_id or item.font_id
    issues = [
        issue
        for issue in item.issues
        if not _decision_resolves_issue(
            issue,
            flower=flower,
            font_option_no=font_option_no,
            personalization_role=personalization_role,
            next_customer_name=next_customer_name,
            next_month=next_month,
            next_flower=next_flower,
            next_font_option_no=next_font_option_no,
        )
    ]

    parsed_order = None
    if next_customer_name and next_month is not None and next_flower and next_font_option_no:
        parsed_order = ParsedOrder(
            orderId=item.order_id,
            customerName=next_customer_name,
            month=next_month,
            monthName=MONTH_NAMES[next_month],
            flower=FlowerChoice(choice=_flower_choice(next_month, next_flower), name=next_flower),
            fontPreference=FontPreference(
                choice=next_font_option_no, label=f"Font {next_font_option_no}"
            ),
            specialNotes="",
        )

    return replace(
        item,
        status=_status_for_issues(issues, parsed_order is not None),
        customer_name=next_customer_name,
        month=next_month,
        flower=next_flower,
        color=next_color,
        font_option_no=next_font_option_no,
        font_id=next_font_id,
        issues=issues,
        parsed_order=parsed_order,
    )


def _status_for_issues(issues: list[ReviewIssue], has_parsed_order: bool) -> str:
    if any(issue.severity == "blocking" for issue in issues):
        return "BLOCKED"
    if issues:
        return "NEEDS_REVIEW"
    return "READY" if has_parsed_order else "NEEDS_REVIEW"


def _decision_resolves_issue(
    issue: ReviewIssue,
    *,
    flower: str | None,
    font_option_no: int | None,
    personalization_role: str | None,
    next_customer_name: str | None,
    next_month: int | None,
    next_flower: str | None,
    next_font_option_no: int | None,
) -> bool:
    if issue.code == "CUSTOM_FLOWER_REQUIRED":
        return bool(flower or next_flower)
    if issue.code == "FONT_REFERENCE_REQUIRES_REVIEW":
        return next_font_option_no is not None or font_option_no is not None
    if issue.code == "PERSONALIZATION_ROLE_AMBIGUOUS":
        return bool(personalization_role)
    if issue.code in {"ORDER_PARSE_FAILED", "ORDER_FIELD_MISSING", "ORDER_PARSE_INCOMPLETE"}:
        return bool(next_customer_name and next_month is not None and next_flower and next_font_option_no)
    return False


def _extract_customer_name(value: str) -> str | None:
    match = re.search(
        r"name on the box should be\s+([A-Za-z][A-Za-z '\-]{0,80})",
        value,
        flags=re.IGNORECASE,
    )
    if match:
        return _clean_sentence_tail(match.group(1))
    label_value = _extract_labeled_value(value, ("customer name", "name", "personalization"))
    return label_value or None


def _extract_month(value: str) -> int | None:
    birth_value = _extract_labeled_value(
        value, ("choose your birth flower", "choose you flower", "birth flower")
    )
    for candidate in [birth_value or "", value]:
        clean = candidate.casefold()
        for alias, month in sorted(
            MONTH_ALIASES.items(), key=lambda item: len(item[0]), reverse=True
        ):
            if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", clean):
                return month
    return None


def _extract_flower(value: str, month: int | None) -> str | None:
    custom = re.search(
        r"flower\s+(?:a|an|as)?\s*([A-Za-z][A-Za-z '\-]{0,80})",
        value,
        flags=re.IGNORECASE,
    )
    if custom and _mentions_custom_flower(value):
        return _clean_sentence_tail(custom.group(1)).casefold()
    birth_value = _extract_labeled_value(
        value, ("choose your birth flower", "choose you flower", "birth flower")
    )
    if month is not None and birth_value:
        compact = _compact(birth_value)
        for name in FLOWERS_BY_MONTH[month].values():
            if _compact(name) in compact:
                return name
    return None


def _extract_font_option(value: str) -> int | None:
    for match in re.finditer(r"\b(?:font\s*)?([1-9][0-9]?)\b", value, flags=re.IGNORECASE):
        if "font" in value[max(0, match.start() - 8) : match.end()].casefold():
            return int(match.group(1))
    return None


def _extract_labeled_value(value: str, labels: tuple[str, ...]) -> str:
    label_pattern = "|".join(
        _label_pattern(label) for label in sorted(labels, key=len, reverse=True)
    )
    match = re.search(rf"(?:{label_pattern})\s*:\s*([^\n\r]+)", value, flags=re.IGNORECASE)
    return _clean_sentence_tail(_split_next_labeled_segment(match.group(1))) if match else ""


def _mentions_custom_flower(value: str) -> bool:
    return "my own design" in value.casefold() or bool(
        re.search(r"flower\s+(?:a|an|as)\s+", value, flags=re.IGNORECASE)
    )


def _mentions_picture_font_reference(value: str) -> bool:
    clean = value.casefold()
    return "same font" in clean and ("picture" in clean or "photo" in clean or "image" in clean)


def _custom_flower_raw_value(value: str) -> str:
    return _extract_labeled_value(
        value, ("choose your birth flower", "choose you flower", "birth flower")
    )


def _picture_font_raw_value(value: str) -> str:
    match = re.search(
        r"[^.\n\r/]*same font[^.\n\r/]*(?:picture|photo|image)[^.\n\r/]*",
        value,
        flags=re.IGNORECASE,
    )
    return match.group(0).strip(" .,:;/") if match else value.strip()


def _looks_like_date(value: str) -> bool:
    return bool(re.fullmatch(r"\s*\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\s*", value or ""))


def _flower_choice(month: int, flower: str) -> int:
    compact_flower = _compact(flower)
    for choice, name in FLOWERS_BY_MONTH.get(month, {}).items():
        if _compact(name) == compact_flower:
            return choice
    return 1


def _clean_sentence_tail(value: str) -> str:
    return re.split(r"\.\s+|,\s+|\s+and\s+", value.strip(), maxsplit=1, flags=re.IGNORECASE)[
        0
    ].strip(" .,:;")


def _split_next_labeled_segment(value: str) -> str:
    return re.split(
        r"\s*/\s*(?=[A-Za-z][A-Za-z ]{0,40}\s*:)",
        value.strip(),
        maxsplit=1,
    )[0]


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _label_pattern(label: str) -> str:
    return r"\s+".join(re.escape(part) for part in label.split())
