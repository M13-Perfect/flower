from __future__ import annotations

import csv
from dataclasses import replace
from io import StringIO

from app.domain import DomainError
from app.domain.orders.batch_import import BatchImport, BatchOrderItem
from app.domain.orders.issues import ReviewIssue
from app.domain.orders.review import apply_review_decision


REVIEW_CSV_COLUMNS = (
    "orderJobId",
    "orderId",
    "field",
    "rawNote",
    "rawValue",
    "failureReason",
    "suggestedValue",
    "manualValue",
    "customerName",
    "month",
    "flower",
    "color",
    "fontOptionNo",
    "fontId",
    "personalizationRole",
)


def export_review_csv(batch: BatchImport) -> str:
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=REVIEW_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for item in batch.items:
        if item.status not in {"NEEDS_REVIEW", "BLOCKED"}:
            continue
        issues = item.issues or [
            ReviewIssue(
                code="ITEM_PENDING_REVIEW",
                severity="warning",
                field="",
                raw_value="",
                suggested_value="",
                message="Item is pending review.",
            )
        ]
        for issue in issues:
            writer.writerow(
                {
                    "orderJobId": item.order_job_id,
                    "orderId": item.order_id or "",
                    "field": issue.field or "",
                    "rawNote": item.order_note,
                    "rawValue": issue.raw_value or "",
                    "failureReason": f"{issue.code}: {issue.message}",
                    "suggestedValue": issue.suggested_value or "",
                    "manualValue": "",
                    "customerName": "",
                    "month": "",
                    "flower": "",
                    "color": "",
                    "fontOptionNo": "",
                    "fontId": "",
                    "personalizationRole": "",
                }
            )
    return output.getvalue()


def import_review_csv(batch: BatchImport, csv_content: str) -> BatchImport:
    reader = csv.DictReader(StringIO(csv_content.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise DomainError(
            code="REVIEW_CSV_INVALID",
            message="Review CSV has no header row.",
            recoverable=True,
        )

    missing_columns = [
        column for column in ("orderJobId", "orderId") if column not in reader.fieldnames
    ]
    if missing_columns:
        raise DomainError(
            code="REVIEW_CSV_INVALID",
            message="Review CSV is missing locator columns.",
            details={"missingColumns": missing_columns},
            recoverable=True,
        )

    decisions: dict[str, dict[str, str]] = {}
    for row_number, row in enumerate(reader, start=2):
        item = _find_batch_item(
            batch,
            _clean(row.get("orderJobId")),
            _clean(row.get("orderId")),
            row_number,
        )
        decision = decisions.setdefault(item.order_job_id, {})
        _merge_decision_values(decision, row)

    items = list(batch.items)
    for order_job_id, decision in decisions.items():
        index = next(index for index, item in enumerate(items) if item.order_job_id == order_job_id)
        items[index] = apply_review_decision(
            items[index],
            customer_name=decision.get("customerName") or None,
            month=_parse_int(decision.get("month"), "month", order_job_id),
            flower=decision.get("flower") or None,
            color=decision.get("color") or None,
            font_option_no=_parse_int(decision.get("fontOptionNo"), "fontOptionNo", order_job_id),
            font_id=decision.get("fontId") or None,
            personalization_role=decision.get("personalizationRole") or None,
        )

    return replace(batch, items=items)


def _find_batch_item(
    batch: BatchImport, order_job_id: str, order_id: str, row_number: int
) -> BatchOrderItem:
    if order_job_id:
        for item in batch.items:
            if item.order_job_id == order_job_id:
                return item
        raise _not_found(row_number, order_job_id=order_job_id, order_id=order_id)

    if order_id:
        matches = [item for item in batch.items if item.order_id == order_id]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise DomainError(
                code="REVIEW_CSV_ITEM_AMBIGUOUS",
                message="Review CSV order id matches multiple items; orderJobId is required.",
                details={"rowNumber": row_number, "orderId": order_id},
                recoverable=True,
            )
    raise _not_found(row_number, order_job_id=order_job_id, order_id=order_id)


def _merge_decision_values(decision: dict[str, str], row: dict[str, str | None]) -> None:
    for column in (
        "customerName",
        "month",
        "flower",
        "color",
        "fontOptionNo",
        "fontId",
        "personalizationRole",
    ):
        value = _clean(row.get(column))
        if value:
            decision[column] = value

    manual_value = _clean(row.get("manualValue"))
    field = _clean(row.get("field"))
    if manual_value and field in {
        "customerName",
        "month",
        "flower",
        "color",
        "fontOptionNo",
        "fontId",
    }:
        decision[field] = manual_value


def _parse_int(value: str | None, field: str, order_job_id: str) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise DomainError(
            code="REVIEW_CSV_INVALID_VALUE",
            message=f"Review CSV field must be an integer: {field}.",
            details={"orderJobId": order_job_id, "field": field, "value": value},
            recoverable=True,
        ) from exc


def _not_found(row_number: int, *, order_job_id: str, order_id: str) -> DomainError:
    return DomainError(
        code="REVIEW_CSV_ITEM_NOT_FOUND",
        message="Review CSV row does not match an item in this batch.",
        details={"rowNumber": row_number, "orderJobId": order_job_id, "orderId": order_id},
        recoverable=True,
    )


def _clean(value: object) -> str:
    return str(value or "").strip()
