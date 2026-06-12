# Dianxiaomi XLSX Batch Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import Dianxiaomi XLSX order exports, generate per-order SVG/DXF/PNG assets named by order id, and write a batch Excel report.

**Architecture:** Keep the frontend unchanged. Add backend domain modules for source adapters, batch persistence, generation, and report writing, then expose them through a lightweight `python -m app.cli` CLI. Use existing parser, template engine, DXF exporter, and output store behavior.

**Tech Stack:** Python 3.11+, FastAPI domain modules, Pydantic schemas, pytest, openpyxl, Pillow, existing LayerDocument and DXF exporter.

---

## File Structure

- Create `services/api/app/domain/orders/batch_import.py`: adapter registry, `dianxiaomi-xlsx` reader, `generic-csv` reader, and auto selection by extension.
- Create `services/api/app/domain/orders/batch_store.py`: JSON batch persistence under `outputs/batches`.
- Create `services/api/app/domain/orders/batch_generate.py`: parse ready rows, apply `birth-flower-card`, write `<orderId>.svg/.dxf/.png`, keep `order.json`.
- Create `services/api/app/domain/orders/report.py`: write `outputs/reports/<batchId>-report.xlsx` and UTF-8-SIG review CSV.
- Create `services/api/app/cli.py`: `import-orders` and `generate` subcommands.
- Modify `services/api/app/domain/output_store/store.py`: use order id for SVG/DXF/PNG filenames.
- Modify `requirements.txt` and `services/api/pyproject.toml`: add `openpyxl`.
- Add `services/api/tests/test_batch_import.py`: adapter tests.
- Add `services/api/tests/test_batch_generate.py`: generation/report/CLI tests.
- Add `services/api/tests/fixtures/orders/test.xlsx`: real Dianxiaomi fixture copied from Downloads.

## Status Rules

- `READY`: deterministic parse and production assets were generated.
- `BLOCKED`: required production data is not deterministic. `My Own Design` is blocked by user decision.
- `NEEDS_REVIEW`: reserved for non-blocking ambiguity. No final export runs for this status.

## TDD Tasks

### Task 1: Adapter Import

- [ ] Write failing tests for `dianxiaomi-xlsx`, `generic-csv`, and extension auto-selection.
- [ ] Run `npm run test --workspace @flower/api -- tests/test_batch_import.py -q` and confirm missing module failure.
- [ ] Implement adapters with row-level `BatchOrderItem` records and `ReviewIssue` values.
- [ ] Re-run the focused tests until they pass.

### Task 2: Output Naming

- [ ] Write failing output-store test asserting `order.json`, `<orderId>.svg`, `<orderId>.png`, and `<orderId>.dxf`.
- [ ] Run `npm run test --workspace @flower/api -- tests/test_outputs.py -q` and confirm filename failure.
- [ ] Update output store filenames.
- [ ] Re-run output tests until they pass.

### Task 3: Generate And Reports

- [ ] Write failing tests for `generate_batch`: three real fixture rows become `READY`, write assets, and report XLSX.
- [ ] Add a generated XLSX fixture row containing `My Own Design` and assert `BLOCKED` appears in the report.
- [ ] Implement batch store, generation, SVG/PNG helpers, XLSX report, and UTF-8-SIG review CSV.
- [ ] Re-run generation tests until they pass.

### Task 4: CLI E2E

- [ ] Write failing CLI tests or run direct E2E commands for `import-orders` and `generate`.
- [ ] Implement `services/api/app/cli.py`.
- [ ] Verify direct commands from `services/api`.

## Verification Commands

```powershell
npm run test --workspace @flower/api -- tests/test_batch_import.py tests/test_batch_generate.py tests/test_outputs.py -q
npm run lint --workspace @flower/api
python -m app.cli import-orders --source tests/fixtures/orders/test.xlsx
python -m app.cli generate --batch-id <batchId>
Get-ChildItem -Recurse outputs | Select-Object FullName,Length
```
