# Batch Review And Font Mapping Design

## Goal

Build the first production-safe batch workflow for order-driven material generation:

1. Import many customer orders from CSV.
2. Parse deterministic fields from order notes and personalization fields.
3. Resolve customer-facing font option numbers through a stable mapping table.
4. Generate editable draft designs only when required fields are confirmed.
5. Put ambiguous or missing data into a manual review queue.
6. Let reviewed decisions become reusable rules for later orders in the same product listing.

The system must not guess fonts from filenames, screenshots, or AI-only interpretation.

## Current Findings

- The FastAPI parser currently returns a structured parse or a recoverable `ORDER_PARSE_FAILED`.
- `ParseOrderResponse` already has `requiresManualConfirmation`, but the response does not yet carry detailed review issues.
- The legacy batch module already has `needs_review`, `warning`, `failed`, and isolated per-order failure handling.
- Font scanning is based on actual font files and internal font names. That is correct for assets, but not enough to represent customer-facing options like `Font 5`.
- The old font asset helper has a business ordering hook, but option order must become explicit data, not implicit filename sorting.
- CSV import exists only as a single-remark helper. Batch import needs to return many rows with row-level validation.

## Dynamic Path Comparison

### Conventional Compliant Path

Add explicit font option mapping, CSV batch import, and review issues in the existing backend/frontend architecture.

- Time: medium.
- Risk: low.
- Rework cost: low.
- Production fit: high.
- ROI: highest.

### Grey Bypass Path

Use AI or filename order to guess which font file is `Font 5`, and let the operator fix wrong outputs after export.

- Time: low.
- Risk: very high.
- Rework cost: high.
- Production fit: low.
- Failure mode: wrong font on customer assets.

### Platform Scraping Path

Automate browser scraping from the seller platform before CSV support.

- Time: high.
- Risk: medium to high because of login state, page structure changes, and platform throttling.
- Rework cost: medium.
- Production fit: useful later, not first.

Decision: implement the conventional path first. CSV is the lowest-cost reliable input contract. Scraping or platform API integration can be added after the generation pipeline is stable.

## Core Concepts

### Font Option Mapping

Customer notes refer to product listing option numbers. Font files do not.

Add a stable mapping model:

```json
{
  "listingId": "birth-flower-card",
  "listingVersion": "2026-06",
  "fontOptions": [
    {
      "optionNo": 5,
      "label": "Font 5",
      "fontId": "lovely-script",
      "sourcePath": "assets/fonts/LovelyScript.ttf",
      "fingerprint": "sha256...",
      "status": "active",
      "previewImage": "assets/font-previews/birth-flower-card/font-5.png"
    }
  ]
}
```

Rules:

- `optionNo` is customer-facing and stable.
- New product fonts append new option numbers. They do not renumber existing options.
- If `Font 5` exists in the listing but the local font file is missing, the order remains reviewable and blocked from final export with `FONT_ASSET_MISSING`.
- If the product page changes, create a new `listingVersion`; old orders keep their original mapping.
- The parser may extract `Font 5`, but only the mapping resolver may convert it to a concrete `fontId`.

### Review Issues

Parsing should produce structured issues instead of only success or failure.

Issue fields:

```text
code
severity: info | warning | blocking
field
message
rawValue
suggestedValue
requiresManualAction
```

Primary issue codes:

```text
FONT_OPTION_MISSING
FONT_OPTION_UNMAPPED
FONT_ASSET_MISSING
FONT_REFERENCE_REQUIRES_REVIEW
FLOWER_UNMAPPED
CUSTOM_FLOWER_REQUIRED
COLOR_UNSUPPORTED
PERSONALIZATION_ROLE_AMBIGUOUS
ORDER_FIELD_MISSING
TEMPLATE_UNSUPPORTED
CSV_ROW_INVALID
```

### Order Job Status

Batch rows move through these statuses:

```text
IMPORTED
PARSED
READY
NEEDS_REVIEW
BLOCKED
GENERATED_DRAFT
EXPORTED
FAILED
```

Status rules:

- `READY`: required fields and mapped assets are present.
- `NEEDS_REVIEW`: the system has a usable draft but one or more fields require human confirmation.
- `BLOCKED`: required production data is missing, such as unmapped font or missing flower asset.
- `FAILED`: technical failure, not a business ambiguity.

## Required Behavior

### Example 1: My Own Design With Picture Font Reference

Input:

```text
Choose Your Birth Flower: My Own Design
Font Design: My Own Design
Personalization: Make the flower a hydrangea and the name on the box should be Kristianna. Use the same font as the bottom box shown in the first picture.
```

Expected extraction:

```text
customerName = Kristianna
flower = hydrangea
flowerSource = custom
fontPreference = unresolved
```

Expected issues:

```text
CUSTOM_FLOWER_REQUIRED
FONT_REFERENCE_REQUIRES_REVIEW
```

The order is `NEEDS_REVIEW` if a draft can be made with temporary fallback layers. It is `BLOCKED` if the custom flower or font must be resolved before any draft can be useful.

### Example 2: Flower, Color, Date, Missing Font

Input:

```text
Choose You Flower: May - Lily of the valley
Color: Green
Personalization: 5-14-22
```

Expected extraction:

```text
month = 5
flower = Lily of the Valley
color = Green
personalization = 5-14-22
```

Expected issues:

```text
FONT_OPTION_MISSING
PERSONALIZATION_ROLE_AMBIGUOUS
```

The typo `Choose You Flower` should be accepted as an alias. `Color` should be preserved even if the first template version does not use it.

## CSV Input Contract

First version supports CSV import. Required columns:

```text
orderId
listingId
orderNote
personalization
variation
```

Optional columns:

```text
listingVersion
sku
quantity
buyerMessage
imageRefs
dueDate
```

Import rules:

- Each row becomes one order job.
- Empty required CSV fields produce `CSV_ROW_INVALID`.
- Raw customer data is stored in the order job payload but must not be written to logs.
- CSV parsing must support UTF-8 with BOM.
- Later XLSX support may be added only after CSV is stable.

## Backend Design

Add or extend modules under `services/api/app/domain`:

```text
orders/parser.py          Parse raw note fields and aliases.
orders/batch_import.py    Convert CSV rows to order jobs.
orders/review.py          Build issue list and status.
fonts/options.py          Resolve listing font option numbers to scanned fonts.
templates/engine.py       Apply resolved fields to editable LayerDocument drafts.
```

Routes:

```text
POST /orders/batch/import
POST /orders/batch/{batchId}/parse
GET  /orders/batch/{batchId}/items
POST /orders/{orderJobId}/review
POST /orders/{orderJobId}/generate
```

The first implementation can store batch state in local JSON files under a validated runtime directory. Database storage is unnecessary until the workflow proves useful.

## Frontend Design

Add a batch review surface to the existing desktop renderer:

```text
Batch Import
Batch Items Table
Review Panel
Generate Draft / Open In Editor
```

The table should show:

```text
orderId
customerName
flower
font
status
issueCount
```

The review panel should allow:

```text
select mapped font option
confirm custom flower handling
confirm personalization role
apply same correction to matching unresolved rows
generate editable draft after confirmation
```

No export should run automatically for `NEEDS_REVIEW` or `BLOCKED` items.

## Data Flow

1. Operator exports CSV from the sales platform.
2. Operator imports CSV into the app.
3. Backend creates a batch and validates rows.
4. Parser extracts deterministic fields.
5. Font option resolver maps customer-facing option numbers to local fonts.
6. Review builder assigns status and issue codes.
7. Frontend shows ready and review queues.
8. Operator resolves ambiguous rows.
9. Backend applies the product template and creates editable design drafts.
10. Operator opens drafts in the editor, adjusts if needed, and exports.

## Error Handling

- Business ambiguity must be returned as review issues, not thrown as unhandled errors.
- File I/O failures, invalid CSV, unsafe paths, and missing mapping files return structured API errors.
- One failed order must not stop the whole batch.
- Export remains blocked when required mapped assets are missing.
- Raw order notes must not appear in logs unless explicitly enabled for debugging.

## Testing

Backend tests:

- CSV import with UTF-8 BOM.
- Missing required CSV columns.
- Batch import creates multiple row-level jobs.
- Font option `5` resolves through mapping, independent of filename.
- Unmapped font option creates `FONT_OPTION_UNMAPPED`.
- Missing mapped font file creates `FONT_ASSET_MISSING`.
- `My Own Design` picture font reference creates `FONT_REFERENCE_REQUIRES_REVIEW`.
- `Choose You Flower` alias parses May and Lily of the Valley.
- `Color: Green` is preserved.
- `5-14-22` produces `PERSONALIZATION_ROLE_AMBIGUOUS` when template role is unclear.

Frontend tests:

- API client supports batch import and review endpoints.
- Batch table groups statuses correctly.
- Review panel blocks export for unresolved blocking issues.
- Applying a review decision updates the displayed status.

## Out Of Scope

- Direct seller-platform scraping.
- Platform API integration.
- AI image comparison for font matching.
- XLSX import.
- Automatic final export of unreviewed orders.
- Renumbering existing product font options.

## Done

- CSV batch import works for multiple orders.
- Font option numbers resolve from explicit mapping, not filenames.
- Ambiguous orders are isolated in a review queue.
- The two real examples above produce deterministic issues.
- Reviewed orders can generate editable draft documents.
- Relevant backend and frontend tests pass.
