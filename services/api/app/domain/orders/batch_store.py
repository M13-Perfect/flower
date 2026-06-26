from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.domain import DomainError
from app.domain.orders.batch_import import BatchImport, BatchOrderItem
from app.domain.orders.issues import ReviewIssue
from app.schemas.orders import ParsedOrder


_MISSING = object()
# 冻结态(打包)由 runtime hook 注入 FLOWER_PROJECT_ROOT 指向随包资源根；未设时取仓库根（开发态行为不变）。
PROJECT_ROOT = Path(os.environ.get("FLOWER_PROJECT_ROOT", Path(__file__).resolve().parents[5])).resolve()


def save_batch(batch: BatchImport) -> BatchImport:
    path = _batch_path(batch.batch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(
            json.dumps(_batch_to_dict(batch), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise DomainError(
            code="BATCH_SAVE_FAILED",
            message="Batch file could not be written.",
            details={"batchId": batch.batch_id},
            recoverable=True,
        ) from exc
    return batch


def load_batch(batch_id: str) -> BatchImport:
    path = _batch_path(batch_id)
    if not path.is_file():
        raise DomainError(
            code="BATCH_NOT_FOUND",
            message="Batch was not found.",
            details={"batchId": batch_id},
            recoverable=True,
        )
    return _read_batch_file(path)


def list_batches() -> list[BatchImport]:
    root = _batches_root()
    if not root.is_dir():
        return []
    return [_read_batch_file(path) for path in sorted(root.glob("*.json"))]


def find_item(order_job_id: str) -> BatchOrderItem:
    for batch in list_batches():
        for item in batch.items:
            if item.order_job_id == order_job_id:
                return item
    raise DomainError(
        code="ORDER_JOB_NOT_FOUND",
        message="Order job was not found.",
        details={"orderJobId": order_job_id},
        recoverable=True,
    )


def replace_item(item: BatchOrderItem) -> BatchOrderItem:
    batch = load_batch(item.batch_id)
    for index, existing in enumerate(batch.items):
        if existing.order_job_id == item.order_job_id:
            batch.items[index] = item
            save_batch(batch)
            return item
    raise DomainError(
        code="ORDER_JOB_NOT_FOUND",
        message="Order job was not found in its batch.",
        details={"batchId": item.batch_id, "orderJobId": item.order_job_id},
        recoverable=True,
    )


def _read_batch_file(path: Path) -> BatchImport:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _invalid_batch("Batch JSON is invalid.") from exc
    except OSError as exc:
        raise DomainError(
            code="BATCH_LOAD_FAILED",
            message="Batch file could not be read.",
            details={"path": _relative_project_path(path)},
            recoverable=True,
        ) from exc
    try:
        return _batch_from_dict(payload)
    except DomainError:
        raise
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise _invalid_batch("Batch JSON structure is invalid.") from exc


def _batch_to_dict(batch: BatchImport) -> dict[str, Any]:
    return {
        "batch_id": batch.batch_id,
        "source_name": batch.source_name,
        "source_adapter": batch.source_adapter,
        "items": [_item_to_dict(item) for item in batch.items],
    }


def _item_to_dict(item: BatchOrderItem) -> dict[str, Any]:
    return {
        "order_job_id": item.order_job_id,
        "batch_id": item.batch_id,
        "row_number": item.row_number,
        "status": item.status,
        "order_id": item.order_id,
        "listing_id": item.listing_id,
        "order_note": item.order_note,
        "source_adapter": item.source_adapter,
        "personalization": item.personalization,
        "variation": item.variation,
        "listing_version": item.listing_version,
        "raw_row": item.raw_row,
        "issues": [_issue_to_dict(issue) for issue in item.issues],
        "customer_name": item.customer_name,
        "month": item.month,
        "flower": item.flower,
        "color": item.color,
        "font_option_no": item.font_option_no,
        "font_id": item.font_id,
        "parsed_order": _parsed_order_to_dict(item.parsed_order),
    }


def _issue_to_dict(issue: ReviewIssue) -> dict[str, Any]:
    return {
        "code": issue.code,
        "severity": issue.severity,
        "field": issue.field,
        "message": issue.message,
        "raw_value": issue.raw_value,
        "suggested_value": issue.suggested_value,
        "requires_manual_action": issue.requires_manual_action,
    }


def _parsed_order_to_dict(parsed_order: Any | None) -> dict[str, Any] | None:
    if parsed_order is None:
        return None
    if hasattr(parsed_order, "model_dump"):
        return parsed_order.model_dump(by_alias=True)
    if isinstance(parsed_order, dict):
        return parsed_order
    return None


def _batch_from_dict(payload: dict[str, Any]) -> BatchImport:
    if not isinstance(payload, dict):
        raise _invalid_batch("Batch JSON top-level value must be an object.")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise _invalid_batch("Batch JSON items must be a list.")
    return BatchImport(
        batch_id=str(_value(payload, "batch_id", "batchId")),
        source_name=str(_value(payload, "source_name", "sourceName", default="orders.csv")),
        source_adapter=str(_value(payload, "source_adapter", "sourceAdapter", default="unknown")),
        items=[_item_from_dict(item) for item in raw_items],
    )


def _item_from_dict(payload: dict[str, Any]) -> BatchOrderItem:
    if not isinstance(payload, dict):
        raise _invalid_batch("Batch JSON item must be an object.")
    raw_issues = _value(payload, "issues", default=[])
    if not isinstance(raw_issues, list):
        raise _invalid_batch("Batch JSON item issues must be a list.")
    raw_row = _value(payload, "raw_row", "rawRow", default={})
    if not isinstance(raw_row, dict):
        raise _invalid_batch("Batch JSON item raw row must be an object.")
    return BatchOrderItem(
        order_job_id=str(_value(payload, "order_job_id", "orderJobId")),
        batch_id=str(_value(payload, "batch_id", "batchId")),
        row_number=int(_value(payload, "row_number", "rowNumber")),
        status=str(_value(payload, "status")),
        order_id=str(_value(payload, "order_id", "orderId", default="") or ""),
        listing_id=str(_value(payload, "listing_id", "listingId", default="") or ""),
        order_note=str(_value(payload, "order_note", "orderNote", default="") or ""),
        source_adapter=str(_value(payload, "source_adapter", "sourceAdapter", default="unknown")),
        personalization=str(_value(payload, "personalization", default="") or ""),
        variation=str(_value(payload, "variation", default="") or ""),
        listing_version=_value(payload, "listing_version", "listingVersion", default=None),
        raw_row={str(key): str(value) for key, value in raw_row.items()},
        issues=[_issue_from_dict(issue) for issue in raw_issues],
        customer_name=_value(payload, "customer_name", "customerName", default=None),
        month=_value(payload, "month", default=None),
        flower=_value(payload, "flower", default=None),
        color=_value(payload, "color", default=None),
        font_option_no=_value(payload, "font_option_no", "fontOptionNo", default=None),
        font_id=_value(payload, "font_id", "fontId", default=None),
        parsed_order=_parsed_order_from_dict(_value(payload, "parsed_order", "parsedOrder", default=None)),
    )


def _issue_from_dict(payload: dict[str, Any]) -> ReviewIssue:
    if not isinstance(payload, dict):
        raise _invalid_batch("Batch JSON issue must be an object.")
    return ReviewIssue(
        code=str(_value(payload, "code")),
        severity=str(_value(payload, "severity")),
        field=_value(payload, "field", default=None),
        message=str(_value(payload, "message")),
        raw_value=_value(payload, "raw_value", "rawValue", default=None),
        suggested_value=_value(payload, "suggested_value", "suggestedValue", default=None),
        requires_manual_action=bool(
            _value(payload, "requires_manual_action", "requiresManualAction", default=True)
        ),
    )


def _parsed_order_from_dict(payload: Any) -> ParsedOrder | None:
    if not isinstance(payload, dict):
        return None
    return ParsedOrder.model_validate(payload)


def _value(payload: dict[str, Any], *keys: str, default: Any = _MISSING) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    if default is not _MISSING:
        return default
    raise KeyError(keys[0])


def _batch_path(batch_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", batch_id):
        raise DomainError(
            code="BATCH_ID_INVALID",
            message="Batch id is invalid.",
            details={"batchId": batch_id},
            recoverable=True,
        )
    path = (_batches_root() / f"{batch_id}.json").resolve()
    root = _batches_root()
    if root != path.parent:
        raise DomainError(
            code="PATH_TRAVERSAL_BLOCKED",
            message="Batch path is outside the batch store.",
            details={"batchId": batch_id},
            recoverable=True,
        )
    return path


def _batches_root() -> Path:
    return (_project_root() / "outputs" / "batches").resolve()


def _invalid_batch(message: str) -> DomainError:
    return DomainError(code="BATCH_INVALID", message=message, recoverable=True)


def _relative_project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(_project_root()).as_posix()
    except ValueError:
        return path.name


def _project_root() -> Path:
    return Path(os.environ.get("FLOWER_PROJECT_ROOT", PROJECT_ROOT)).resolve()
