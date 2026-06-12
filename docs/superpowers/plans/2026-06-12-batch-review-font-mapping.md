# Batch Review Font Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build CSV batch import, stable customer-facing font option mapping, structured review issues, and a first desktop review surface for ambiguous orders.

**Architecture:** Keep deterministic business logic in FastAPI domain modules and keep React as the operator workflow surface. Batch state is stored as validated JSON under `outputs/batches/` so one failed order never stops the rest of the batch. The template engine only receives orders after blocking issues are resolved.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, pytest, React, TypeScript, Vitest, existing `@flower/design-core` layer documents.

---

## File Structure

- Create `services/api/app/schemas/batches.py`: API request/response models for batch import, review issues, batch rows, review decisions, and draft generation.
- Create `services/api/app/domain/orders/batch_import.py`: parse UTF-8 CSV text into row-level import records without logging raw customer notes.
- Create `services/api/app/domain/orders/review.py`: domain dataclasses, status rules, issue constructors, review decision application, and conversion to API bodies.
- Create `services/api/app/domain/orders/batch_store.py`: JSON persistence for batches under `outputs/batches/` with project-root path validation.
- Create `services/api/app/domain/fonts/options.py`: load `templates/font-options/<listingId>.json`, resolve `Font N` to a scanned font id or issue code.
- Create `templates/font-options/birth-flower-card.json`: first explicit listing font option mapping fixture for the default template.
- Modify `services/api/app/domain/orders/parser.py`: expose review-friendly parsing helpers, accept `Choose You Flower`, preserve `Color`, extract custom flower/name references.
- Modify `services/api/app/domain/orders/__init__.py`: export batch helpers.
- Modify `services/api/app/main.py`: add batch import, parse, list, review, and generate endpoints.
- Create `services/api/tests/test_batch_import.py`: CSV import, row validation, and UTF-8 BOM coverage.
- Create `services/api/tests/test_font_options.py`: font option mapping coverage independent from filename order.
- Create `services/api/tests/test_batch_routes.py`: end-to-end route coverage for import, parse, review, and generation guards.
- Modify `apps/desktop/src/renderer/api/client.ts`: add batch API types and methods.
- Modify `apps/desktop/src/renderer/api/client.test.ts`: verify new batch API calls.
- Create `apps/desktop/src/renderer/batchWorkflow.ts`: pure helpers for status counts, issue filtering, and export blocking.
- Create `apps/desktop/src/renderer/batchWorkflow.test.ts`: frontend status grouping and blocking behavior.
- Create `apps/desktop/src/renderer/BatchPanel.tsx`: CSV import and review UI.
- Modify `apps/desktop/src/renderer/App.tsx`: mount `BatchPanel` and open generated drafts in the existing editor.
- Modify `apps/desktop/src/renderer/styles.css`: add compact batch table and review panel styling.

---

### Task 1: Backend Batch Schemas

**Files:**
- Create: `services/api/app/schemas/batches.py`
- Test: `services/api/tests/test_batch_import.py`

- [ ] **Step 1: Write the failing schema smoke test**

Add this test file:

```python
from __future__ import annotations

from app.schemas.batches import BatchImportRequest, ReviewIssueBody


def test_batch_import_request_accepts_csv_content_aliases() -> None:
    request = BatchImportRequest(csvContent="orderId,listingId,orderNote,personalization,variation\n1,birth-flower-card,note,name,font")

    assert request.csv_content.startswith("orderId")
    assert request.source_name == "orders.csv"


def test_review_issue_body_uses_json_aliases() -> None:
    issue = ReviewIssueBody(
        code="FONT_OPTION_MISSING",
        severity="blocking",
        field="fontPreference",
        message="Font option is missing.",
        rawValue=None,
        suggestedValue=None,
        requiresManualAction=True,
    )

    assert issue.model_dump(by_alias=True) == {
        "code": "FONT_OPTION_MISSING",
        "severity": "blocking",
        "field": "fontPreference",
        "message": "Font option is missing.",
        "rawValue": None,
        "suggestedValue": None,
        "requiresManualAction": True,
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest services/api/tests/test_batch_import.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas.batches'`.

- [ ] **Step 3: Create batch schemas**

Create `services/api/app/schemas/batches.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.errors import ApiModel
from app.schemas.orders import ParsedOrder


ReviewSeverity = Literal["info", "warning", "blocking"]
OrderJobStatus = Literal[
    "IMPORTED",
    "PARSED",
    "READY",
    "NEEDS_REVIEW",
    "BLOCKED",
    "GENERATED_DRAFT",
    "EXPORTED",
    "FAILED",
]


class ReviewIssueBody(ApiModel):
    code: str = Field(min_length=1)
    severity: ReviewSeverity
    field: str | None = None
    message: str = Field(min_length=1)
    raw_value: str | None = Field(default=None, alias="rawValue")
    suggested_value: str | None = Field(default=None, alias="suggestedValue")
    requires_manual_action: bool = Field(alias="requiresManualAction")


class BatchImportRequest(ApiModel):
    csv_content: str = Field(alias="csvContent", min_length=1, max_length=2_000_000)
    source_name: str = Field(default="orders.csv", alias="sourceName", max_length=200)


class BatchSummaryBody(ApiModel):
    total: int
    ready: int
    needs_review: int = Field(alias="needsReview")
    blocked: int
    failed: int


class BatchOrderItemBody(ApiModel):
    order_job_id: str = Field(alias="orderJobId")
    batch_id: str = Field(alias="batchId")
    row_number: int = Field(alias="rowNumber", ge=1)
    status: OrderJobStatus
    order_id: str | None = Field(default=None, alias="orderId")
    listing_id: str | None = Field(default=None, alias="listingId")
    listing_version: str | None = Field(default=None, alias="listingVersion")
    order_note: str = Field(default="", alias="orderNote")
    personalization: str = ""
    variation: str = ""
    customer_name: str | None = Field(default=None, alias="customerName")
    month: int | None = None
    flower: str | None = None
    color: str | None = None
    font_option_no: int | None = Field(default=None, alias="fontOptionNo")
    font_id: str | None = Field(default=None, alias="fontId")
    issues: list[ReviewIssueBody] = Field(default_factory=list)
    parsed_order: ParsedOrder | None = Field(default=None, alias="parsedOrder")


class BatchImportResponse(ApiModel):
    batch_id: str = Field(alias="batchId")
    items: list[BatchOrderItemBody]
    summary: BatchSummaryBody


class BatchItemsResponse(ApiModel):
    batch_id: str = Field(alias="batchId")
    items: list[BatchOrderItemBody]
    summary: BatchSummaryBody


class ReviewDecisionRequest(ApiModel):
    customer_name: str | None = Field(default=None, alias="customerName", max_length=200)
    month: int | None = Field(default=None, ge=1, le=12)
    flower: str | None = Field(default=None, max_length=120)
    color: str | None = Field(default=None, max_length=80)
    font_option_no: int | None = Field(default=None, alias="fontOptionNo", ge=1, le=99)
    font_id: str | None = Field(default=None, alias="fontId", max_length=120)
    personalization_role: str | None = Field(default=None, alias="personalizationRole", max_length=80)
    apply_to_matching: bool = Field(default=False, alias="applyToMatching")


class ReviewDecisionResponse(ApiModel):
    item: BatchOrderItemBody


class GenerateDraftResponse(ApiModel):
    item: BatchOrderItemBody
    document: dict
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest services/api/tests/test_batch_import.py -q`

Expected: PASS for the two schema tests.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/schemas/batches.py services/api/tests/test_batch_import.py
git commit -m "feat(api): add batch review schemas"
```

---

### Task 2: CSV Batch Import Domain

**Files:**
- Create: `services/api/app/domain/orders/batch_import.py`
- Modify: `services/api/tests/test_batch_import.py`

- [ ] **Step 1: Add failing CSV import tests**

Append these tests to `services/api/tests/test_batch_import.py`:

```python
import pytest

from app.domain import DomainError
from app.domain.orders.batch_import import import_batch_csv


def test_import_batch_csv_accepts_utf8_bom_and_multiple_rows() -> None:
    csv_text = (
        "\ufefforderId,listingId,orderNote,personalization,variation\n"
        "1001,birth-flower-card,Choose Your Birth Flower: May - Lily of the valley,5-14-22,Color: Green\n"
        "1002,birth-flower-card,Font Design: Font 5,Kristianna,Choose Your Birth Flower: My Own Design\n"
    )

    batch = import_batch_csv(csv_text, source_name="etsy.csv", batch_id="batch_test")

    assert batch.batch_id == "batch_test"
    assert [item.row_number for item in batch.items] == [2, 3]
    assert batch.items[0].order_id == "1001"
    assert batch.items[0].listing_id == "birth-flower-card"
    assert batch.items[0].status == "IMPORTED"
    assert batch.items[0].issues == []


def test_import_batch_csv_marks_empty_required_values_as_row_invalid() -> None:
    csv_text = (
        "orderId,listingId,orderNote,personalization,variation\n"
        "1001,,Choose Your Birth Flower: May - Lily of the valley,5-14-22,Color: Green\n"
    )

    batch = import_batch_csv(csv_text, batch_id="batch_invalid")

    assert batch.items[0].status == "BLOCKED"
    assert [issue.code for issue in batch.items[0].issues] == ["CSV_ROW_INVALID"]
    assert batch.items[0].issues[0].field == "listingId"


def test_import_batch_csv_rejects_missing_required_columns() -> None:
    csv_text = "orderId,listingId,orderNote\n1001,birth-flower-card,note\n"

    with pytest.raises(DomainError) as error:
        import_batch_csv(csv_text)

    assert error.value.code == "CSV_INVALID"
    assert error.value.details["missingColumns"] == ["personalization", "variation"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest services/api/tests/test_batch_import.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.orders.batch_import'`.

- [ ] **Step 3: Implement CSV import**

Create `services/api/app/domain/orders/batch_import.py`:

```python
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from io import StringIO
from uuid import uuid4

from app.domain import DomainError


REQUIRED_COLUMNS = ("orderId", "listingId", "orderNote", "personalization", "variation")
OPTIONAL_COLUMNS = ("listingVersion", "sku", "quantity", "buyerMessage", "imageRefs", "dueDate")


@dataclass(frozen=True)
class ReviewIssue:
    code: str
    severity: str
    field: str | None
    message: str
    raw_value: str | None = None
    suggested_value: str | None = None
    requires_manual_action: bool = True


@dataclass(frozen=True)
class BatchOrderItem:
    order_job_id: str
    batch_id: str
    row_number: int
    status: str
    order_id: str | None
    listing_id: str | None
    listing_version: str | None
    order_note: str
    personalization: str
    variation: str
    raw_row: dict[str, str]
    issues: list[ReviewIssue] = field(default_factory=list)
    customer_name: str | None = None
    month: int | None = None
    flower: str | None = None
    color: str | None = None
    font_option_no: int | None = None
    font_id: str | None = None
    parsed_order: object | None = None


@dataclass(frozen=True)
class BatchImport:
    batch_id: str
    source_name: str
    items: list[BatchOrderItem]


def import_batch_csv(csv_content: str, *, source_name: str = "orders.csv", batch_id: str | None = None) -> BatchImport:
    clean_content = csv_content.lstrip("\ufeff")
    reader = csv.DictReader(StringIO(clean_content))
    fieldnames = list(reader.fieldnames or [])
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing_columns:
        raise DomainError(
            code="CSV_INVALID",
            message="CSV is missing required columns.",
            details={"missingColumns": missing_columns},
            recoverable=True,
        )

    resolved_batch_id = batch_id or f"batch_{uuid4().hex}"
    items: list[BatchOrderItem] = []
    for row_number, row in enumerate(reader, start=2):
        normalized = {key: _clean_cell(value) for key, value in row.items() if key is not None}
        issues = _row_issues(normalized)
        status = "BLOCKED" if issues else "IMPORTED"
        items.append(
            BatchOrderItem(
                order_job_id=f"job_{uuid4().hex}",
                batch_id=resolved_batch_id,
                row_number=row_number,
                status=status,
                order_id=normalized.get("orderId") or None,
                listing_id=normalized.get("listingId") or None,
                listing_version=normalized.get("listingVersion") or None,
                order_note=normalized.get("orderNote", ""),
                personalization=normalized.get("personalization", ""),
                variation=normalized.get("variation", ""),
                raw_row=normalized,
                issues=issues,
            )
        )

    return BatchImport(batch_id=resolved_batch_id, source_name=source_name, items=items)


def _row_issues(row: dict[str, str]) -> list[ReviewIssue]:
    issues: list[ReviewIssue] = []
    for column in REQUIRED_COLUMNS:
        if not row.get(column, "").strip():
            issues.append(
                ReviewIssue(
                    code="CSV_ROW_INVALID",
                    severity="blocking",
                    field=column,
                    message=f"CSV required column is empty: {column}",
                    raw_value=row.get(column),
                    requires_manual_action=True,
                )
            )
    return issues


def _clean_cell(value: object) -> str:
    return str(value or "").strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest services/api/tests/test_batch_import.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/domain/orders/batch_import.py services/api/tests/test_batch_import.py
git commit -m "feat(api): import order batches from csv"
```

---

### Task 3: Font Option Mapping Resolver

**Files:**
- Create: `services/api/app/domain/fonts/options.py`
- Create: `services/api/tests/test_font_options.py`
- Create: `templates/font-options/birth-flower-card.json`
- Modify: `services/api/app/domain/fonts/__init__.py`

- [ ] **Step 1: Write failing font option tests**

Create `services/api/tests/test_font_options.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from app.domain.fonts import options
from app.domain.fonts.options import resolve_font_option


def test_resolve_font_option_uses_listing_mapping_not_filename_order(tmp_path, monkeypatch) -> None:
    font_dir = tmp_path / "assets" / "fonts"
    mapping_dir = tmp_path / "templates" / "font-options"
    font_dir.mkdir(parents=True)
    mapping_dir.mkdir(parents=True)
    font_path = font_dir / "z-last-file-name.ttf"
    font_path.write_bytes(b"fake font bytes")
    (mapping_dir / "birth-flower-card.json").write_text(
        json.dumps(
            {
                "listingId": "birth-flower-card",
                "listingVersion": "2026-06",
                "fontOptions": [
                    {
                        "optionNo": 5,
                        "label": "Font 5",
                        "fontId": "lovely-script",
                        "sourcePath": "assets/fonts/z-last-file-name.ttf",
                        "fingerprint": "",
                        "status": "active",
                        "previewImage": "assets/font-previews/birth-flower-card/font-5.png",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(options, "PROJECT_ROOT", tmp_path)

    resolution = resolve_font_option("birth-flower-card", "2026-06", 5)

    assert resolution.font_id == "lovely-script"
    assert resolution.label == "Font 5"
    assert resolution.issues == []


def test_resolve_font_option_reports_unmapped_option(tmp_path, monkeypatch) -> None:
    mapping_dir = tmp_path / "templates" / "font-options"
    mapping_dir.mkdir(parents=True)
    (mapping_dir / "birth-flower-card.json").write_text(
        json.dumps({"listingId": "birth-flower-card", "listingVersion": "2026-06", "fontOptions": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(options, "PROJECT_ROOT", tmp_path)

    resolution = resolve_font_option("birth-flower-card", "2026-06", 5)

    assert resolution.font_id is None
    assert [issue.code for issue in resolution.issues] == ["FONT_OPTION_UNMAPPED"]


def test_resolve_font_option_reports_missing_mapped_font_file(tmp_path, monkeypatch) -> None:
    mapping_dir = tmp_path / "templates" / "font-options"
    mapping_dir.mkdir(parents=True)
    (mapping_dir / "birth-flower-card.json").write_text(
        json.dumps(
            {
                "listingId": "birth-flower-card",
                "listingVersion": "2026-06",
                "fontOptions": [
                    {
                        "optionNo": 5,
                        "label": "Font 5",
                        "fontId": "lovely-script",
                        "sourcePath": "assets/fonts/missing.ttf",
                        "fingerprint": "",
                        "status": "active",
                        "previewImage": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(options, "PROJECT_ROOT", tmp_path)

    resolution = resolve_font_option("birth-flower-card", "2026-06", 5)

    assert resolution.font_id is None
    assert [issue.code for issue in resolution.issues] == ["FONT_ASSET_MISSING"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest services/api/tests/test_font_options.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.fonts.options'`.

- [ ] **Step 3: Implement font option resolver**

Create `services/api/app/domain/fonts/options.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from app.domain import DomainError
from app.domain.orders.batch_import import ReviewIssue


PROJECT_ROOT = Path(__file__).resolve().parents[5]


@dataclass(frozen=True)
class FontOptionResolution:
    option_no: int
    label: str
    font_id: str | None
    source_path: str | None
    issues: list[ReviewIssue] = field(default_factory=list)


def resolve_font_option(
    listing_id: str,
    listing_version: str | None,
    option_no: int | None,
) -> FontOptionResolution:
    if option_no is None:
        return FontOptionResolution(
            option_no=0,
            label="",
            font_id=None,
            source_path=None,
            issues=[
                ReviewIssue(
                    code="FONT_OPTION_MISSING",
                    severity="blocking",
                    field="fontPreference",
                    message="Font option number is missing.",
                    requires_manual_action=True,
                )
            ],
        )

    mapping = _load_mapping(listing_id)
    options = mapping.get("fontOptions", [])
    for option in options:
        if int(option.get("optionNo", 0)) != option_no:
            continue
        source_path = str(option.get("sourcePath") or "")
        resolved_path = _resolve_project_path(source_path)
        if not source_path or not resolved_path.is_file():
            return FontOptionResolution(
                option_no=option_no,
                label=str(option.get("label") or f"Font {option_no}"),
                font_id=None,
                source_path=source_path or None,
                issues=[
                    ReviewIssue(
                        code="FONT_ASSET_MISSING",
                        severity="blocking",
                        field="fontPreference",
                        message=f"Mapped font file is missing for Font {option_no}.",
                        raw_value=str(option_no),
                        suggested_value=str(option.get("fontId") or ""),
                        requires_manual_action=True,
                    )
                ],
            )
        return FontOptionResolution(
            option_no=option_no,
            label=str(option.get("label") or f"Font {option_no}"),
            font_id=str(option.get("fontId") or ""),
            source_path=source_path,
            issues=[],
        )

    return FontOptionResolution(
        option_no=option_no,
        label=f"Font {option_no}",
        font_id=None,
        source_path=None,
        issues=[
            ReviewIssue(
                code="FONT_OPTION_UNMAPPED",
                severity="blocking",
                field="fontPreference",
                message=f"Font option is not mapped for this listing: Font {option_no}.",
                raw_value=str(option_no),
                requires_manual_action=True,
            )
        ],
    )


def _load_mapping(listing_id: str) -> dict:
    mapping_path = _resolve_project_path(f"templates/font-options/{listing_id}.json")
    if not mapping_path.is_file():
        raise DomainError(
            code="FONT_OPTION_MAPPING_MISSING",
            message="Font option mapping file was not found.",
            details={"listingId": listing_id},
            recoverable=True,
        )
    try:
        return json.loads(mapping_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DomainError(
            code="FONT_OPTION_MAPPING_INVALID",
            message="Font option mapping JSON is invalid.",
            details={"listingId": listing_id},
            recoverable=True,
        ) from exc


def _resolve_project_path(relative_path: str) -> Path:
    raw_path = Path(relative_path)
    path = raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path
    resolved = path.resolve()
    root = PROJECT_ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise DomainError(
            code="PATH_TRAVERSAL_BLOCKED",
            message="Font option path is outside the project root.",
            details={"path": relative_path},
            recoverable=True,
        )
    return resolved
```

Modify `services/api/app/domain/fonts/__init__.py`:

```python
from app.domain.fonts.options import FontOptionResolution, resolve_font_option
from app.domain.fonts.scanner import get_font_file_path, list_fonts, list_glyphs

__all__ = [
    "FontOptionResolution",
    "get_font_file_path",
    "list_fonts",
    "list_glyphs",
    "resolve_font_option",
]
```

Create `templates/font-options/birth-flower-card.json`:

```json
{
  "listingId": "birth-flower-card",
  "listingVersion": "2026-06",
  "fontOptions": []
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest services/api/tests/test_font_options.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/domain/fonts/options.py services/api/app/domain/fonts/__init__.py services/api/tests/test_font_options.py templates/font-options/birth-flower-card.json
git commit -m "feat(api): resolve listing font option mappings"
```

---

### Task 4: Review-Friendly Order Parsing And Status Rules

**Files:**
- Modify: `services/api/app/domain/orders/parser.py`
- Create: `services/api/app/domain/orders/review.py`
- Modify: `services/api/tests/test_batch_import.py`

- [ ] **Step 1: Add failing review parse tests**

Append these tests to `services/api/tests/test_batch_import.py`:

```python
from app.domain.orders.batch_import import BatchOrderItem
from app.domain.orders.review import review_imported_item


def make_imported_item(order_note: str, personalization: str = "", variation: str = "") -> BatchOrderItem:
    return BatchOrderItem(
        order_job_id="job_1",
        batch_id="batch_1",
        row_number=2,
        status="IMPORTED",
        order_id="1001",
        listing_id="birth-flower-card",
        listing_version="2026-06",
        order_note=order_note,
        personalization=personalization,
        variation=variation,
        raw_row={},
        issues=[],
    )


def test_review_imported_item_extracts_custom_flower_name_and_picture_font_issue() -> None:
    item = make_imported_item(
        "Choose Your Birth Flower: My Own Design\n"
        "Font Design: My Own Design\n"
        "Personalization: Make the flower a hydrangea and the name on the box should be Kristianna. "
        "Use the same font as the bottom box shown in the first picture."
    )

    reviewed = review_imported_item(item)

    assert reviewed.customer_name == "Kristianna"
    assert reviewed.flower == "hydrangea"
    assert reviewed.status == "BLOCKED"
    assert {issue.code for issue in reviewed.issues} >= {
        "CUSTOM_FLOWER_REQUIRED",
        "FONT_REFERENCE_REQUIRES_REVIEW",
    }


def test_review_imported_item_accepts_choose_you_flower_color_and_ambiguous_date() -> None:
    item = make_imported_item(
        "Choose You Flower: May - Lily of the valley\nColor: Green\nPersonalization: 5-14-22"
    )

    reviewed = review_imported_item(item)

    assert reviewed.month == 5
    assert reviewed.flower == "Lily of the Valley"
    assert reviewed.color == "Green"
    assert reviewed.status == "BLOCKED"
    assert {issue.code for issue in reviewed.issues} >= {
        "FONT_OPTION_MISSING",
        "PERSONALIZATION_ROLE_AMBIGUOUS",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest services/api/tests/test_batch_import.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.orders.review'`.

- [ ] **Step 3: Implement review logic**

Create `services/api/app/domain/orders/review.py`:

```python
from __future__ import annotations

from dataclasses import replace
import re

from app.domain.fonts.options import resolve_font_option
from app.domain.orders.batch_import import BatchOrderItem, ReviewIssue
from app.domain.orders.parser import FLOWERS_BY_MONTH, MONTH_ALIASES, MONTH_NAMES
from app.schemas.orders import FlowerChoice, FontPreference, ParsedOrder


def review_imported_item(item: BatchOrderItem) -> BatchOrderItem:
    if item.issues:
        return item

    combined = "\n".join(part for part in [item.order_note, item.personalization, item.variation] if part)
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
                message="Order asks for a custom flower that must be confirmed.",
                raw_value=flower,
                requires_manual_action=True,
            )
        )

    if _mentions_picture_font_reference(combined):
        issues.append(
            ReviewIssue(
                code="FONT_REFERENCE_REQUIRES_REVIEW",
                severity="blocking",
                field="fontPreference",
                message="Order references a font from a picture and cannot be resolved deterministically.",
                requires_manual_action=True,
            )
        )

    if _looks_like_date(item.personalization) or _looks_like_date(_extract_labeled_value(combined, ("personalization",))):
        issues.append(
            ReviewIssue(
                code="PERSONALIZATION_ROLE_AMBIGUOUS",
                severity="warning",
                field="personalization",
                message="Personalization looks like a date and must be confirmed against the template role.",
                raw_value=item.personalization or _extract_labeled_value(combined, ("personalization",)),
                requires_manual_action=True,
            )
        )

    if not customer_name and not _looks_like_date(item.personalization):
        customer_name = _single_text_personalization(item.personalization)

    if not customer_name:
        issues.append(_missing_issue("customerName", "Customer name is missing."))
    if month is None:
        issues.append(_missing_issue("month", "Birth month is missing."))
    if flower is None:
        issues.append(_missing_issue("flower", "Birth flower is missing."))

    resolution = resolve_font_option(item.listing_id or "birth-flower-card", item.listing_version, font_option_no)
    issues.extend(resolution.issues)

    parsed_order = None
    if customer_name and month is not None and flower and resolution.font_id:
        parsed_order = ParsedOrder(
            orderId=item.order_id,
            customerName=customer_name,
            month=month,
            monthName=MONTH_NAMES[month],
            flower=FlowerChoice(choice=_flower_choice(month, flower), name=flower),
            fontPreference=FontPreference(choice=font_option_no or 1, label=resolution.label),
            specialNotes="",
        )

    status = _status_for_issues(issues, parsed_order is not None)
    return replace(
        item,
        status=status,
        customer_name=customer_name,
        month=month,
        flower=flower,
        color=color,
        font_option_no=font_option_no,
        font_id=resolution.font_id,
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
        if issue.field not in {"customerName", "month", "flower", "fontPreference", "personalization"}
    ]
    parsed_order = None
    if next_customer_name and next_month is not None and next_flower and next_font_option_no and next_font_id:
        parsed_order = ParsedOrder(
            orderId=item.order_id,
            customerName=next_customer_name,
            month=next_month,
            monthName=MONTH_NAMES[next_month],
            flower=FlowerChoice(choice=_flower_choice(next_month, next_flower), name=next_flower),
            fontPreference=FontPreference(choice=next_font_option_no, label=f"Font {next_font_option_no}"),
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


def _extract_customer_name(value: str) -> str | None:
    match = re.search(r"name on the box should be\s+([A-Za-z][A-Za-z '\-]{0,80})", value, flags=re.IGNORECASE)
    if match:
        return _clean_sentence_tail(match.group(1))
    label_value = _extract_labeled_value(value, ("customer name", "name"))
    return label_value or None


def _extract_month(value: str) -> int | None:
    birth_value = _extract_labeled_value(value, ("choose your birth flower", "choose you flower", "birth flower"))
    candidates = [birth_value or "", value]
    for candidate in candidates:
        clean = candidate.casefold()
        for alias, month in sorted(MONTH_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", clean):
                return month
    return None


def _extract_flower(value: str, month: int | None) -> str | None:
    custom = re.search(r"flower\s+(?:a|an|as)\s+([A-Za-z][A-Za-z '\-]{0,80})", value, flags=re.IGNORECASE)
    if custom:
        return _clean_sentence_tail(custom.group(1)).casefold()
    birth_value = _extract_labeled_value(value, ("choose your birth flower", "choose you flower", "birth flower"))
    if month is not None and birth_value:
        compact = _compact(birth_value)
        for name in FLOWERS_BY_MONTH[month].values():
            if _compact(name) in compact:
                return name
    return None


def _extract_font_option(value: str) -> int | None:
    match = re.search(r"\b(?:font\s*)?([1-9][0-9]?)\b", value, flags=re.IGNORECASE)
    if match and "font" in value[max(0, match.start() - 8) : match.end()].casefold():
        return int(match.group(1))
    return None


def _extract_labeled_value(value: str, labels: tuple[str, ...]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{label_pattern})\s*[:：]\s*([^\n\r]+)", value, flags=re.IGNORECASE)
    return _clean_sentence_tail(match.group(1)) if match else ""


def _mentions_custom_flower(value: str) -> bool:
    return "my own design" in value.casefold() or bool(re.search(r"flower\s+(?:a|an|as)\s+", value, flags=re.IGNORECASE))


def _mentions_picture_font_reference(value: str) -> bool:
    clean = value.casefold()
    return "same font" in clean and ("picture" in clean or "photo" in clean or "image" in clean)


def _looks_like_date(value: str) -> bool:
    return bool(re.fullmatch(r"\s*\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\s*", value or ""))


def _single_text_personalization(value: str) -> str | None:
    clean = value.strip()
    if re.fullmatch(r"[A-Za-z][A-Za-z '\-]{0,80}", clean):
        return clean
    return None


def _missing_issue(field: str, message: str) -> ReviewIssue:
    return ReviewIssue(code="ORDER_FIELD_MISSING", severity="blocking", field=field, message=message)


def _flower_choice(month: int, flower: str) -> int:
    compact_flower = _compact(flower)
    for choice, name in FLOWERS_BY_MONTH.get(month, {}).items():
        if _compact(name) == compact_flower:
            return choice
    return 1


def _clean_sentence_tail(value: str) -> str:
    return re.split(r"\.\s+|,\s+|\s+and\s+", value.strip(), maxsplit=1, flags=re.IGNORECASE)[0].strip(" .,:;")


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())
```

- [ ] **Step 4: Modify parser aliases for current single-order parser**

In `services/api/app/domain/orders/parser.py`, add `"choose you flower"` to the existing `birth_flower` label tuple. Preserve every existing label in that tuple, including legacy non-ASCII labels.

```python
("birth_flower", ("choose your birth flower", "choose you flower", "birth flower"))
```

The code block shows the required ASCII aliases only. The implementation must keep any additional labels already present in the file.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest services/api/tests/test_batch_import.py services/api/tests/test_font_options.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/api/app/domain/orders/parser.py services/api/app/domain/orders/review.py services/api/tests/test_batch_import.py
git commit -m "feat(api): classify batch order review issues"
```

---

### Task 5: Batch Store And API Routes

**Files:**
- Create: `services/api/app/domain/orders/batch_store.py`
- Modify: `services/api/app/domain/orders/__init__.py`
- Modify: `services/api/app/main.py`
- Create: `services/api/tests/test_batch_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `services/api/tests/test_batch_routes.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.orders import batch_store
from app.main import app


def test_batch_import_parse_list_and_review_routes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(batch_store, "PROJECT_ROOT", tmp_path)
    client = TestClient(app)
    csv_text = (
        "orderId,listingId,orderNote,personalization,variation\n"
        "1001,birth-flower-card,Choose You Flower: May - Lily of the valley,5-14-22,Color: Green\n"
    )

    import_response = client.post(
        "/orders/batch/import",
        json={"csvContent": csv_text, "sourceName": "orders.csv"},
    )
    assert import_response.status_code == 200
    batch_id = import_response.json()["batchId"]
    assert import_response.json()["summary"]["total"] == 1

    parse_response = client.post(f"/orders/batch/{batch_id}/parse")
    assert parse_response.status_code == 200
    parsed_item = parse_response.json()["items"][0]
    assert parsed_item["status"] == "BLOCKED"
    assert {issue["code"] for issue in parsed_item["issues"]} >= {
        "FONT_OPTION_MISSING",
        "PERSONALIZATION_ROLE_AMBIGUOUS",
    }

    list_response = client.get(f"/orders/batch/{batch_id}/items")
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["orderId"] == "1001"

    order_job_id = parsed_item["orderJobId"]
    review_response = client.post(
        f"/orders/{order_job_id}/review",
        json={
            "customerName": "Kristianna",
            "month": 5,
            "flower": "Lily of the Valley",
            "fontOptionNo": 5,
            "fontId": "lovely-script",
            "personalizationRole": "date",
        },
    )
    assert review_response.status_code == 200
    assert review_response.json()["item"]["customerName"] == "Kristianna"


def test_generate_route_blocks_unresolved_items(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(batch_store, "PROJECT_ROOT", tmp_path)
    client = TestClient(app)
    csv_text = (
        "orderId,listingId,orderNote,personalization,variation\n"
        "1001,birth-flower-card,Choose You Flower: May - Lily of the valley,5-14-22,Color: Green\n"
    )
    batch_id = client.post("/orders/batch/import", json={"csvContent": csv_text}).json()["batchId"]
    item = client.post(f"/orders/batch/{batch_id}/parse").json()["items"][0]

    response = client.post(f"/orders/{item['orderJobId']}/generate")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ORDER_REVIEW_REQUIRED"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest services/api/tests/test_batch_routes.py -q`

Expected: FAIL with HTTP 404 for `/orders/batch/import`.

- [ ] **Step 3: Implement batch store**

Create `services/api/app/domain/orders/batch_store.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from app.domain import DomainError
from app.domain.orders.batch_import import BatchImport, BatchOrderItem, ReviewIssue


PROJECT_ROOT = Path(__file__).resolve().parents[5]


def save_batch(batch: BatchImport) -> BatchImport:
    path = _batch_path(batch.batch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_batch_to_dict(batch), ensure_ascii=False, indent=2), encoding="utf-8")
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


def replace_item(order_job_id: str, next_item: BatchOrderItem) -> BatchImport:
    batch = load_batch(next_item.batch_id)
    items = [next_item if item.order_job_id == order_job_id else item for item in batch.items]
    next_batch = BatchImport(batch_id=batch.batch_id, source_name=batch.source_name, items=items)
    return save_batch(next_batch)


def find_item(order_job_id: str) -> BatchOrderItem:
    for path in _batch_dir().glob("*.json"):
        batch = _batch_from_dict(json.loads(path.read_text(encoding="utf-8")))
        for item in batch.items:
            if item.order_job_id == order_job_id:
                return item
    raise DomainError(
        code="ORDER_JOB_NOT_FOUND",
        message="Order job was not found.",
        details={"orderJobId": order_job_id},
        recoverable=True,
    )


def save_item(next_item: BatchOrderItem) -> BatchOrderItem:
    replace_item(next_item.order_job_id, next_item)
    return next_item


def _batch_path(batch_id: str) -> Path:
    if not batch_id.startswith("batch_") and batch_id != "batch_test" and batch_id != "batch_invalid":
        raise DomainError(
            code="BATCH_ID_INVALID",
            message="Batch id is invalid.",
            details={"batchId": batch_id},
            recoverable=True,
        )
    path = (_batch_dir() / f"{batch_id}.json").resolve()
    root = PROJECT_ROOT.resolve()
    if root not in path.parents:
        raise DomainError(
            code="PATH_TRAVERSAL_BLOCKED",
            message="Batch path is outside the project root.",
            details={"batchId": batch_id},
            recoverable=True,
        )
    return path


def _batch_dir() -> Path:
    return (PROJECT_ROOT / "outputs" / "batches").resolve()


def _batch_to_dict(batch: BatchImport) -> dict[str, Any]:
    return asdict(batch)


def _batch_from_dict(payload: dict[str, Any]) -> BatchImport:
    items: list[BatchOrderItem] = []
    for raw_item in payload.get("items", []):
        issues = [ReviewIssue(**raw_issue) for raw_issue in raw_item.get("issues", [])]
        raw_item = {**raw_item, "issues": issues}
        items.append(BatchOrderItem(**raw_item))
    return BatchImport(
        batch_id=payload["batch_id"],
        source_name=payload.get("source_name", "orders.csv"),
        items=items,
    )
```

- [ ] **Step 4: Implement API conversion and routes**

Modify `services/api/app/main.py` imports:

```python
from dataclasses import replace

from app.domain.orders.batch_import import BatchImport, BatchOrderItem, ReviewIssue, import_batch_csv
from app.domain.orders.batch_store import find_item, load_batch, save_batch, save_item
from app.domain.orders.review import apply_review_decision, review_imported_item
from app.schemas.batches import (
    BatchImportRequest,
    BatchImportResponse,
    BatchItemsResponse,
    BatchOrderItemBody,
    BatchSummaryBody,
    GenerateDraftResponse,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewIssueBody,
)
```

Add these routes before `def _domain_error_response`:

```python
@app.post("/orders/batch/import", response_model=None)
def import_order_batch(request: BatchImportRequest) -> Any:
    try:
        batch = save_batch(import_batch_csv(request.csv_content, source_name=request.source_name))
    except DomainError as exc:
        return _domain_error_response(exc, status_code=422)
    return _batch_response(batch).model_dump(by_alias=True)


@app.post("/orders/batch/{batch_id}/parse", response_model=None)
def parse_order_batch(batch_id: str) -> Any:
    try:
        batch = load_batch(batch_id)
        reviewed_items = [review_imported_item(item) for item in batch.items]
        parsed_batch = save_batch(BatchImport(batch_id=batch.batch_id, source_name=batch.source_name, items=reviewed_items))
    except DomainError as exc:
        return _domain_error_response(exc, status_code=422)
    return _batch_response(parsed_batch).model_dump(by_alias=True)


@app.get("/orders/batch/{batch_id}/items", response_model=None)
def list_order_batch_items(batch_id: str) -> Any:
    try:
        batch = load_batch(batch_id)
    except DomainError as exc:
        return _domain_error_response(exc, status_code=404 if exc.code == "BATCH_NOT_FOUND" else 422)
    return BatchItemsResponse(
        batchId=batch.batch_id,
        items=[_batch_item_body(item) for item in batch.items],
        summary=_batch_summary(batch.items),
    ).model_dump(by_alias=True)


@app.post("/orders/{order_job_id}/review", response_model=None)
def review_order_job(order_job_id: str, request: ReviewDecisionRequest) -> Any:
    try:
        item = find_item(order_job_id)
        next_item = apply_review_decision(
            item,
            customer_name=request.customer_name,
            month=request.month,
            flower=request.flower,
            color=request.color,
            font_option_no=request.font_option_no,
            font_id=request.font_id,
        )
        saved_item = save_item(next_item)
    except DomainError as exc:
        return _domain_error_response(exc, status_code=404 if exc.code == "ORDER_JOB_NOT_FOUND" else 422)
    return ReviewDecisionResponse(item=_batch_item_body(saved_item)).model_dump(by_alias=True)


@app.post("/orders/{order_job_id}/generate", response_model=None)
def generate_order_job(order_job_id: str) -> Any:
    try:
        item = find_item(order_job_id)
        if item.parsed_order is None or item.status in {"BLOCKED", "NEEDS_REVIEW"}:
            raise DomainError(
                code="ORDER_REVIEW_REQUIRED",
                message="Order must be reviewed before draft generation.",
                details={"orderJobId": order_job_id, "status": item.status},
                recoverable=True,
            )
        document = apply_template("birth-flower-card", item.parsed_order, job_id=item.order_job_id)
        saved_item = save_item(replace(item, status="GENERATED_DRAFT"))
    except DomainError as exc:
        return _domain_error_response(exc, status_code=422)
    return GenerateDraftResponse(item=_batch_item_body(saved_item), document=document).model_dump(by_alias=True)
```

Add these helpers near the bottom of `services/api/app/main.py`:

```python
def _batch_response(batch: BatchImport) -> BatchImportResponse:
    return BatchImportResponse(
        batchId=batch.batch_id,
        items=[_batch_item_body(item) for item in batch.items],
        summary=_batch_summary(batch.items),
    )


def _batch_summary(items: list[BatchOrderItem]) -> BatchSummaryBody:
    return BatchSummaryBody(
        total=len(items),
        ready=sum(1 for item in items if item.status == "READY"),
        needsReview=sum(1 for item in items if item.status == "NEEDS_REVIEW"),
        blocked=sum(1 for item in items if item.status == "BLOCKED"),
        failed=sum(1 for item in items if item.status == "FAILED"),
    )


def _batch_item_body(item: BatchOrderItem) -> BatchOrderItemBody:
    return BatchOrderItemBody(
        orderJobId=item.order_job_id,
        batchId=item.batch_id,
        rowNumber=item.row_number,
        status=item.status,
        orderId=item.order_id,
        listingId=item.listing_id,
        listingVersion=item.listing_version,
        orderNote=item.order_note,
        personalization=item.personalization,
        variation=item.variation,
        customerName=item.customer_name,
        month=item.month,
        flower=item.flower,
        color=item.color,
        fontOptionNo=item.font_option_no,
        fontId=item.font_id,
        issues=[_review_issue_body(issue) for issue in item.issues],
        parsedOrder=item.parsed_order,
    )


def _review_issue_body(issue: ReviewIssue) -> ReviewIssueBody:
    return ReviewIssueBody(
        code=issue.code,
        severity=issue.severity,
        field=issue.field,
        message=issue.message,
        rawValue=issue.raw_value,
        suggestedValue=issue.suggested_value,
        requiresManualAction=issue.requires_manual_action,
    )
```

Modify `services/api/app/domain/orders/__init__.py`:

```python
from app.domain.orders.batch_import import BatchImport, BatchOrderItem, ReviewIssue, import_batch_csv
from app.domain.orders.review import apply_review_decision, review_imported_item
from app.domain.orders.parser import parse_order_note

__all__ = [
    "BatchImport",
    "BatchOrderItem",
    "ReviewIssue",
    "apply_review_decision",
    "import_batch_csv",
    "parse_order_note",
    "review_imported_item",
]
```

- [ ] **Step 5: Run route tests**

Run: `pytest services/api/tests/test_batch_routes.py -q`

Expected: PASS.

- [ ] **Step 6: Run backend focused tests**

Run: `pytest services/api/tests/test_batch_import.py services/api/tests/test_font_options.py services/api/tests/test_batch_routes.py services/api/tests/test_orders_templates.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add services/api/app/domain/orders/batch_store.py services/api/app/domain/orders/__init__.py services/api/app/main.py services/api/tests/test_batch_routes.py
git commit -m "feat(api): expose batch review workflow"
```

---

### Task 6: Frontend API Client And Workflow Helpers

**Files:**
- Modify: `apps/desktop/src/renderer/api/client.ts`
- Modify: `apps/desktop/src/renderer/api/client.test.ts`
- Create: `apps/desktop/src/renderer/batchWorkflow.ts`
- Create: `apps/desktop/src/renderer/batchWorkflow.test.ts`

- [ ] **Step 1: Add failing frontend API tests**

Append this test to `apps/desktop/src/renderer/api/client.test.ts` inside the existing `describe` block:

```typescript
  it("calls batch import, parse, list, review, and generate endpoints", async () => {
    const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
    const item = {
      orderJobId: "job_1",
      batchId: "batch_1",
      rowNumber: 2,
      status: "BLOCKED",
      orderId: "1001",
      listingId: "birth-flower-card",
      listingVersion: "2026-06",
      orderNote: "note",
      personalization: "5-14-22",
      variation: "Color: Green",
      customerName: null,
      month: 5,
      flower: "Lily of the Valley",
      color: "Green",
      fontOptionNo: null,
      fontId: null,
      issues: [],
      parsedOrder: null,
    };
    const fetchImpl: typeof fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          batchId: "batch_1",
          items: [item],
          item,
          summary: { total: 1, ready: 0, needsReview: 0, blocked: 1, failed: 0 },
          document: createDocument(),
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    };
    const client = createApiClient({ baseUrl: "http://127.0.0.1:8765", fetch: fetchImpl });

    await expect(client.importBatch({ csvContent: "orderId,listingId,orderNote,personalization,variation\n" })).resolves.toMatchObject({ batchId: "batch_1" });
    await expect(client.parseBatch("batch_1")).resolves.toMatchObject({ batchId: "batch_1" });
    await expect(client.listBatchItems("batch_1")).resolves.toMatchObject({ batchId: "batch_1" });
    await expect(client.reviewOrderJob("job_1", { customerName: "Kristianna" })).resolves.toMatchObject({ item });
    await expect(client.generateOrderDraft("job_1")).resolves.toMatchObject({ document: createDocument() });

    expect(String(calls[0].input)).toBe("http://127.0.0.1:8765/orders/batch/import");
    expect(String(calls[1].input)).toBe("http://127.0.0.1:8765/orders/batch/batch_1/parse");
    expect(String(calls[2].input)).toBe("http://127.0.0.1:8765/orders/batch/batch_1/items");
    expect(String(calls[3].input)).toBe("http://127.0.0.1:8765/orders/job_1/review");
    expect(String(calls[4].input)).toBe("http://127.0.0.1:8765/orders/job_1/generate");
  });
```

Create `apps/desktop/src/renderer/batchWorkflow.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { countBatchStatuses, hasBlockingIssues } from "./batchWorkflow";

describe("batch workflow helpers", () => {
  it("counts item statuses for the batch table", () => {
    expect(
      countBatchStatuses([
        { status: "READY", issues: [] },
        { status: "BLOCKED", issues: [] },
        { status: "NEEDS_REVIEW", issues: [] },
      ]),
    ).toEqual({ ready: 1, needsReview: 1, blocked: 1, failed: 0 });
  });

  it("blocks export when an item has blocking issues", () => {
    expect(
      hasBlockingIssues({
        status: "BLOCKED",
        issues: [{ code: "FONT_OPTION_MISSING", severity: "blocking" }],
      }),
    ).toBe(true);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --filter desktop test -- --run apps/desktop/src/renderer/api/client.test.ts apps/desktop/src/renderer/batchWorkflow.test.ts`

Expected: FAIL with missing client methods and missing `batchWorkflow.ts`.

- [ ] **Step 3: Add client types and methods**

In `apps/desktop/src/renderer/api/client.ts`, add these exported interfaces after `ParseOrderResponse`:

```typescript
export type ReviewSeverity = "info" | "warning" | "blocking";
export type OrderJobStatus =
  | "IMPORTED"
  | "PARSED"
  | "READY"
  | "NEEDS_REVIEW"
  | "BLOCKED"
  | "GENERATED_DRAFT"
  | "EXPORTED"
  | "FAILED";

export interface ReviewIssue {
  code: string;
  severity: ReviewSeverity;
  field?: string | null;
  message?: string;
  rawValue?: string | null;
  suggestedValue?: string | null;
  requiresManualAction?: boolean;
}

export interface BatchOrderItem {
  orderJobId: string;
  batchId: string;
  rowNumber: number;
  status: OrderJobStatus;
  orderId?: string | null;
  listingId?: string | null;
  listingVersion?: string | null;
  orderNote: string;
  personalization: string;
  variation: string;
  customerName?: string | null;
  month?: number | null;
  flower?: string | null;
  color?: string | null;
  fontOptionNo?: number | null;
  fontId?: string | null;
  issues: ReviewIssue[];
  parsedOrder?: ParsedOrder | null;
}

export interface BatchSummary {
  total: number;
  ready: number;
  needsReview: number;
  blocked: number;
  failed: number;
}

export interface BatchImportRequest {
  csvContent: string;
  sourceName?: string;
}

export interface BatchImportResponse {
  batchId: string;
  items: BatchOrderItem[];
  summary: BatchSummary;
}

export interface BatchItemsResponse {
  batchId: string;
  items: BatchOrderItem[];
  summary: BatchSummary;
}

export interface ReviewDecisionRequest {
  customerName?: string | null;
  month?: number | null;
  flower?: string | null;
  color?: string | null;
  fontOptionNo?: number | null;
  fontId?: string | null;
  personalizationRole?: string | null;
  applyToMatching?: boolean;
}

export interface ReviewDecisionResponse {
  item: BatchOrderItem;
}

export interface GenerateDraftResponse {
  item: BatchOrderItem;
  document: LayerDocument;
}
```

Inside the `return` object from `createApiClient`, add:

```typescript
    async importBatch(request: BatchImportRequest): Promise<BatchImportResponse> {
      return postJson<BatchImportResponse>(
        fetchImpl,
        `${baseUrl}/orders/batch/import`,
        request,
        "Batch import failed",
      );
    },

    async parseBatch(batchId: string): Promise<BatchImportResponse> {
      return postJson<BatchImportResponse>(
        fetchImpl,
        `${baseUrl}/orders/batch/${encodeURIComponent(batchId)}/parse`,
        {},
        "Batch parse failed",
      );
    },

    async listBatchItems(batchId: string): Promise<BatchItemsResponse> {
      return requestJson<BatchItemsResponse>(
        fetchImpl,
        `${baseUrl}/orders/batch/${encodeURIComponent(batchId)}/items`,
        "Batch items load failed",
      );
    },

    async reviewOrderJob(
      orderJobId: string,
      request: ReviewDecisionRequest,
    ): Promise<ReviewDecisionResponse> {
      return postJson<ReviewDecisionResponse>(
        fetchImpl,
        `${baseUrl}/orders/${encodeURIComponent(orderJobId)}/review`,
        request,
        "Order review failed",
      );
    },

    async generateOrderDraft(orderJobId: string): Promise<GenerateDraftResponse> {
      return postJson<GenerateDraftResponse>(
        fetchImpl,
        `${baseUrl}/orders/${encodeURIComponent(orderJobId)}/generate`,
        {},
        "Draft generation failed",
      );
    },
```

- [ ] **Step 4: Add workflow helpers**

Create `apps/desktop/src/renderer/batchWorkflow.ts`:

```typescript
import type { BatchOrderItem, OrderJobStatus, ReviewIssue } from "./api/client";

export interface BatchStatusCounts {
  ready: number;
  needsReview: number;
  blocked: number;
  failed: number;
}

export function countBatchStatuses(items: Array<Pick<BatchOrderItem, "status" | "issues">>): BatchStatusCounts {
  return items.reduce<BatchStatusCounts>(
    (counts, item) => {
      if (item.status === "READY" || item.status === "GENERATED_DRAFT" || item.status === "EXPORTED") {
        counts.ready += 1;
      }
      if (item.status === "NEEDS_REVIEW") {
        counts.needsReview += 1;
      }
      if (item.status === "BLOCKED") {
        counts.blocked += 1;
      }
      if (item.status === "FAILED") {
        counts.failed += 1;
      }
      return counts;
    },
    { ready: 0, needsReview: 0, blocked: 0, failed: 0 },
  );
}

export function hasBlockingIssues(item: { status: OrderJobStatus; issues: Array<Pick<ReviewIssue, "severity">> }): boolean {
  return item.status === "BLOCKED" || item.issues.some((issue) => issue.severity === "blocking");
}
```

- [ ] **Step 5: Run frontend focused tests**

Run: `pnpm --filter desktop test -- --run apps/desktop/src/renderer/api/client.test.ts apps/desktop/src/renderer/batchWorkflow.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/desktop/src/renderer/api/client.ts apps/desktop/src/renderer/api/client.test.ts apps/desktop/src/renderer/batchWorkflow.ts apps/desktop/src/renderer/batchWorkflow.test.ts
git commit -m "feat(desktop): add batch review api client"
```

---

### Task 7: Desktop Batch Review Panel

**Files:**
- Create: `apps/desktop/src/renderer/BatchPanel.tsx`
- Modify: `apps/desktop/src/renderer/App.tsx`
- Modify: `apps/desktop/src/renderer/styles.css`

- [ ] **Step 1: Create the batch panel component**

Create `apps/desktop/src/renderer/BatchPanel.tsx`:

```tsx
import { useMemo, useState, type ChangeEvent } from "react";

import type { LayerDocument } from "@flower/design-core";
import type { ApiClient, BatchOrderItem, BatchSummary, FontSummary } from "./api/client";
import { countBatchStatuses, hasBlockingIssues } from "./batchWorkflow";

export function BatchPanel({
  apiClient,
  fonts,
  onOpenDraft,
}: {
  apiClient: ApiClient;
  fonts: FontSummary[];
  onOpenDraft: (document: LayerDocument, item: BatchOrderItem) => void;
}) {
  const [items, setItems] = useState<BatchOrderItem[]>([]);
  const [summary, setSummary] = useState<BatchSummary | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [message, setMessage] = useState("ready");
  const selectedItem = useMemo(
    () => items.find((item) => item.orderJobId === selectedId) ?? items[0] ?? null,
    [items, selectedId],
  );
  const counts = useMemo(() => countBatchStatuses(items), [items]);

  function updateItems(nextItems: BatchOrderItem[], nextSummary: BatchSummary | null) {
    setItems(nextItems);
    setSummary(nextSummary);
    setSelectedId(nextItems[0]?.orderJobId ?? null);
  }

  function handleCsvFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) {
      return;
    }
    setMessage("importing");
    void file
      .text()
      .then((csvContent) => apiClient.importBatch({ csvContent, sourceName: file.name }))
      .then((response) => apiClient.parseBatch(response.batchId))
      .then((response) => {
        updateItems(response.items, response.summary);
        setMessage(`batch ${response.batchId}`);
      })
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "Batch import failed");
      });
  }

  function handleReviewSelected() {
    if (!selectedItem) {
      return;
    }
    const selectedFont = fonts[0];
    setMessage("saving review");
    void apiClient
      .reviewOrderJob(selectedItem.orderJobId, {
        customerName: selectedItem.customerName ?? "",
        month: selectedItem.month ?? null,
        flower: selectedItem.flower ?? null,
        color: selectedItem.color ?? null,
        fontOptionNo: selectedItem.fontOptionNo ?? 1,
        fontId: selectedFont?.id ?? selectedItem.fontId ?? null,
        personalizationRole: "confirmed",
      })
      .then((response) => {
        setItems((current) =>
          current.map((item) => (item.orderJobId === response.item.orderJobId ? response.item : item)),
        );
        setMessage("review saved");
      })
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "Review failed");
      });
  }

  function handleGenerateSelected() {
    if (!selectedItem || hasBlockingIssues(selectedItem)) {
      setMessage("resolve blocking issues first");
      return;
    }
    setMessage("generating");
    void apiClient
      .generateOrderDraft(selectedItem.orderJobId)
      .then((response) => {
        setItems((current) =>
          current.map((item) => (item.orderJobId === response.item.orderJobId ? response.item : item)),
        );
        onOpenDraft(response.document, response.item);
        setMessage("draft generated");
      })
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "Draft generation failed");
      });
  }

  return (
    <section className="batch-panel" aria-label="Batch review">
      <div className="panel-header">
        <h2>Batch</h2>
        <span>{message}</span>
      </div>
      <label className="batch-file-button">
        Import CSV
        <input accept=".csv,text/csv" onChange={handleCsvFile} type="file" />
      </label>
      <div className="batch-counts">
        <span>ready {summary?.ready ?? counts.ready}</span>
        <span>review {summary?.needsReview ?? counts.needsReview}</span>
        <span>blocked {summary?.blocked ?? counts.blocked}</span>
        <span>failed {summary?.failed ?? counts.failed}</span>
      </div>
      <div className="batch-table" role="table">
        {items.map((item) => (
          <button
            className={item.orderJobId === selectedItem?.orderJobId ? "batch-row active" : "batch-row"}
            key={item.orderJobId}
            onClick={() => setSelectedId(item.orderJobId)}
            type="button"
          >
            <span>{item.orderId ?? item.rowNumber}</span>
            <span>{item.customerName ?? "name?"}</span>
            <span>{item.flower ?? "flower?"}</span>
            <strong>{item.status}</strong>
          </button>
        ))}
      </div>
      {selectedItem ? (
        <div className="review-box">
          <strong>{selectedItem.orderId ?? selectedItem.orderJobId}</strong>
          <p>{selectedItem.orderNote}</p>
          <ul>
            {selectedItem.issues.map((issue) => (
              <li key={`${issue.code}-${issue.field ?? "field"}`}>{issue.code}</li>
            ))}
          </ul>
          <button className="secondary-action" onClick={handleReviewSelected} type="button">
            Save review
          </button>
          <button className="primary-action" onClick={handleGenerateSelected} type="button">
            Generate draft
          </button>
        </div>
      ) : null}
    </section>
  );
}
```

- [ ] **Step 2: Mount panel in App**

In `apps/desktop/src/renderer/App.tsx`, add import:

```typescript
import { BatchPanel } from "./BatchPanel";
```

Add callback inside `App`:

```typescript
  const handleOpenBatchDraft = useCallback((nextDocument: LayerDocument, item: BatchOrderItem) => {
    setDocument(nextDocument);
    setSelectedLayerId(selectInitialEditableLayerId(nextDocument));
    setSavedJson(JSON.stringify(nextDocument, null, 2));
    setOrderId(item.orderId ?? "");
    setOrderMessage(`draft ${item.status}`);
  }, []);
```

Also add `type BatchOrderItem` to the existing API import list:

```typescript
  type BatchOrderItem,
```

Also add `type LayerDocument` to the existing `@flower/design-core` import list if it is not already present in the file.

Render `BatchPanel` after `OrderPanel`:

```tsx
          <BatchPanel apiClient={apiClient} fonts={fonts} onOpenDraft={handleOpenBatchDraft} />
```

- [ ] **Step 3: Add compact styles**

Append to `apps/desktop/src/renderer/styles.css`:

```css
.batch-panel {
  display: grid;
  gap: 10px;
}

.batch-file-button {
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  display: inline-flex;
  font-size: 13px;
  justify-content: center;
  padding: 8px 10px;
}

.batch-file-button input {
  display: none;
}

.batch-counts {
  display: grid;
  font-size: 12px;
  gap: 6px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.batch-table {
  display: grid;
  gap: 6px;
  max-height: 180px;
  overflow: auto;
}

.batch-row {
  align-items: center;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  display: grid;
  gap: 6px;
  grid-template-columns: 0.8fr 1fr 1fr 1fr;
  padding: 8px;
  text-align: left;
}

.batch-row.active {
  border-color: var(--accent);
}

.review-box {
  border: 1px solid var(--border);
  border-radius: 8px;
  display: grid;
  gap: 8px;
  padding: 10px;
}

.review-box p {
  font-size: 12px;
  line-height: 1.4;
  margin: 0;
}
```

- [ ] **Step 4: Run frontend tests**

Run: `pnpm --filter desktop test -- --run apps/desktop/src/renderer/api/client.test.ts apps/desktop/src/renderer/batchWorkflow.test.ts`

Expected: PASS.

- [ ] **Step 5: Run frontend type check or build**

Run: `pnpm --filter desktop build`

Expected: PASS. If build fails because the existing workspace has unrelated TypeScript errors, record the exact first unrelated error and run the focused tests from Step 4 again.

- [ ] **Step 6: Commit**

```bash
git add apps/desktop/src/renderer/BatchPanel.tsx apps/desktop/src/renderer/App.tsx apps/desktop/src/renderer/styles.css
git commit -m "feat(desktop): add batch review panel"
```

---

### Task 8: End-To-End Verification And Docs

**Files:**
- Modify: `docs/USER_OPERATION_GUIDE.md`

- [ ] **Step 1: Add operation guide section**

Append this section to `docs/USER_OPERATION_GUIDE.md`:

````markdown
## Batch Review Workflow

Use CSV as the first batch import format. Required columns are:

```text
orderId,listingId,orderNote,personalization,variation
```

The app imports every row as a separate order job. Rows with missing required CSV values are marked `BLOCKED`. Orders with unclear font, custom flower, picture-based font references, or ambiguous personalization are sent to review instead of being exported.

Font numbers in customer notes are listing option numbers. They must be mapped through `templates/font-options/<listingId>.json`; font filenames are not used as option numbers.
````

- [ ] **Step 2: Run backend verification**

Run: `pytest services/api/tests/test_batch_import.py services/api/tests/test_font_options.py services/api/tests/test_batch_routes.py services/api/tests/test_orders_templates.py services/api/tests/test_fonts.py -q`

Expected: PASS.

- [ ] **Step 3: Run frontend verification**

Run: `pnpm --filter desktop test -- --run apps/desktop/src/renderer/api/client.test.ts apps/desktop/src/renderer/batchWorkflow.test.ts`

Expected: PASS.

- [ ] **Step 4: Run broader checks**

Run:

```bash
pytest services/api/tests -q
pnpm --filter desktop build
```

Expected: PASS. If broader checks fail because of pre-existing unrelated dirty-worktree changes, keep the focused verification from Steps 2 and 3 and include the exact unrelated failure in the final handoff.

- [ ] **Step 5: Commit**

```bash
git add docs/USER_OPERATION_GUIDE.md
git commit -m "docs: explain batch review workflow"
```

---

## Self-Review

Spec coverage:

- CSV import is covered in Tasks 1, 2, 5, 6, 7, and 8.
- Stable font option mapping is covered in Task 3 and verified in Task 4 review status.
- Manual review issues and statuses are covered in Tasks 1, 4, 5, 6, and 7.
- The two real examples are covered by Task 4 tests.
- Editable draft generation is covered by Task 5.
- Frontend review surface is covered by Tasks 6 and 7.
- No platform scraping, XLSX, or AI font matching is included.

Type consistency:

- Backend status literals use uppercase `OrderJobStatus`.
- Frontend status literals mirror the backend uppercase values.
- Backend issue fields use snake_case in domain dataclasses and camelCase API aliases.
- Frontend issue fields use API camelCase.

Final verification target:

```bash
pytest services/api/tests/test_batch_import.py services/api/tests/test_font_options.py services/api/tests/test_batch_routes.py services/api/tests/test_orders_templates.py services/api/tests/test_fonts.py -q
pnpm --filter desktop test -- --run apps/desktop/src/renderer/api/client.test.ts apps/desktop/src/renderer/batchWorkflow.test.ts
```
