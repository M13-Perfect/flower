from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.domain import DomainError
from app.domain.orders.batch_import import BatchImport, BatchOrderItem, ReviewIssue


def save_batch(batch: BatchImport) -> BatchImport:
    path = _batch_path(batch.batch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(batch), ensure_ascii=False, indent=2), encoding="utf-8")
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
    return _batch_from_dict(json.loads(path.read_text(encoding="utf-8")))


def _batch_path(batch_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", batch_id):
        raise DomainError(
            code="BATCH_ID_INVALID",
            message="Batch id is invalid.",
            details={"batchId": batch_id},
            recoverable=True,
        )
    path = (_project_root() / "outputs" / "batches" / f"{batch_id}.json").resolve()
    root = (_project_root() / "outputs" / "batches").resolve()
    if root != path.parent:
        raise DomainError(
            code="PATH_TRAVERSAL_BLOCKED",
            message="Batch path is outside the batch store.",
            details={"batchId": batch_id},
            recoverable=True,
        )
    return path


def _batch_from_dict(payload: dict[str, Any]) -> BatchImport:
    items: list[BatchOrderItem] = []
    for raw_item in payload.get("items", []):
        raw_issues = raw_item.get("issues", [])
        issues = [ReviewIssue(**issue) for issue in raw_issues]
        item_payload = {key: value for key, value in raw_item.items() if key != "issues"}
        items.append(BatchOrderItem(**item_payload, issues=issues))
    return BatchImport(
        batch_id=payload["batch_id"],
        source_name=payload["source_name"],
        source_adapter=payload["source_adapter"],
        items=items,
    )


def _project_root() -> Path:
    default_root = Path(__file__).resolve().parents[5]
    return Path(os.environ.get("FLOWER_PROJECT_ROOT", default_root)).resolve()
