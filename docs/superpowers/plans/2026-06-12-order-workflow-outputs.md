# Order Workflow Outputs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the end-to-end order note to editable template to PNG/SVG/DXF/JSON output workflow.

**Architecture:** FastAPI owns deterministic parsing, template application, DXF generation, safe output paths, and filesystem persistence. React/Fabric owns manual editing, text/font/glyph controls, and browser PNG/SVG generation, then sends generated artifacts to the backend for saving under `outputs/<order-name>/`.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, pytest, React, TypeScript, Fabric.js, Vitest, `@flower/design-core`.

---

## File Map

- Modify `services/api/app/domain/orders/parser.py`: support real order note format and structured field extraction.
- Modify `services/api/tests/test_orders_templates.py`: add the 10 supplied real-note API parser regressions.
- Modify `services/api/app/domain/templates/engine.py`: resolve real flower/font asset paths without relying on committed private assets.
- Modify `services/api/tests/test_orders_templates.py`: add template asset-path behavior.
- Create `services/api/app/domain/outputs/store.py`: validate output directories and write artifacts.
- Create `services/api/app/schemas/outputs.py`: request/response schema for output saving.
- Modify `services/api/app/main.py`: add `/outputs/save` endpoint.
- Create `services/api/tests/test_outputs.py`: output path and file-writing tests.
- Modify `apps/desktop/src/renderer/api/client.ts`: typed parse, apply-template, DXF, and output-save client methods.
- Modify `apps/desktop/src/renderer/api/client.test.ts`: client request tests.
- Modify `apps/desktop/src/renderer/canvas/layerFabricModel.ts`: text/font layer update helpers.
- Modify `apps/desktop/src/renderer/canvas/layerFabricModel.test.ts`: text/font update tests.
- Modify `apps/desktop/src/renderer/App.tsx`: add order panel, text/font inspector controls, DXF and save-all actions.
- Modify `apps/desktop/src/renderer/styles.css`: layout styles for the order panel and new inspector controls.

## Baseline Task: Preserve Existing Worktree State

- [ ] **Step 1: Inspect worktree**

Run:

```powershell
git status --short
```

Expected: existing dirty state is visible before feature edits.

- [ ] **Step 2: Create a baseline commit if untracked app/API files are still uncommitted**

Run:

```powershell
git add AGENTS.md README.md PLANS.md package.json package-lock.json pnpm-workspace.yaml pytest.ini requirements.txt tsconfig.base.json apps packages services templates docs
git commit -m "chore: record flower editor baseline"
```

Expected: baseline files are committed so later feature commits only contain module work.

- [ ] **Step 3: Commit this plan**

Run:

```powershell
git add docs/superpowers/specs/2026-06-12-order-workflow-outputs-design.md docs/superpowers/plans/2026-06-12-order-workflow-outputs.md
git commit -m "docs: plan order workflow outputs"
```

Expected: plan/spec commit succeeds.

## Task 1: Order Parsing API

**Files:**
- Modify: `services/api/app/domain/orders/parser.py`
- Modify: `services/api/tests/test_orders_templates.py`

- [ ] **Step 1: Write failing real-note parser tests**

Add parametrized tests that post each supplied note to `/orders/parse` and assert `customerName`, `month`, `flower.name`, and `fontPreference.label`.

Run:

```powershell
npm run test --workspace @flower/api -- tests/test_orders_templates.py -q
```

Expected before implementation: tests for `Choose Your Birth Flower` notes fail if the API parser cannot extract fields.

- [ ] **Step 2: Implement structured field parsing**

Update the parser so `Choose Your Birth Flower  ：Sep - Aster`, `Font Design  ：Font 3`, and `Personalization  ：Lacey` produce a complete `ParsedOrder`.

- [ ] **Step 3: Verify parser tests**

Run:

```powershell
npm run test --workspace @flower/api -- tests/test_orders_templates.py -q
```

Expected: parser and template tests pass.

- [ ] **Step 4: Commit module**

Run:

```powershell
git add services/api/app/domain/orders/parser.py services/api/tests/test_orders_templates.py
git commit -m "feat(api): parse real birth flower order notes"
```

## Task 2: Template Asset Resolution

**Files:**
- Modify: `services/api/app/domain/templates/engine.py`
- Modify: `services/api/tests/test_orders_templates.py`

- [ ] **Step 1: Write failing asset resolution test**

Use `tmp_path` plus `FLOWER_PROJECT_ROOT` to create a fixture such as `BirthMonth flowers/AsterSeptember .svg`, then assert the returned SVG layer references a path that can be resolved by the app.

Run:

```powershell
npm run test --workspace @flower/api -- tests/test_orders_templates.py -q
```

Expected before implementation: asset path assertion fails.

- [ ] **Step 2: Implement deterministic asset lookup**

Resolve first from `assets/flowers/`, then from `BirthMonth flowers/` by matching compact flower and month names. Return a project-relative path.

- [ ] **Step 3: Verify template tests**

Run:

```powershell
npm run test --workspace @flower/api -- tests/test_orders_templates.py -q
```

Expected: parser/template tests pass.

- [ ] **Step 4: Commit module**

Run:

```powershell
git add services/api/app/domain/templates/engine.py services/api/tests/test_orders_templates.py
git commit -m "feat(api): resolve birth flower template assets"
```

## Task 3: Output Persistence API

**Files:**
- Create: `services/api/app/domain/outputs/store.py`
- Create: `services/api/app/schemas/outputs.py`
- Modify: `services/api/app/main.py`
- Create: `services/api/tests/test_outputs.py`

- [ ] **Step 1: Write failing output-save tests**

Test that JSON, SVG, PNG base64, and DXF base64 content are written under `outputs/Lacey/`, and that names like `../bad` are sanitized inside `outputs/`.

Run:

```powershell
npm run test --workspace @flower/api -- tests/test_outputs.py -q
```

Expected before implementation: import or endpoint failure.

- [ ] **Step 2: Implement output store**

Create a safe directory from `orderName`, validate all resolved paths remain inside `<project-root>/outputs`, decode base64/data URLs, and write files.

- [ ] **Step 3: Add `/outputs/save` endpoint**

Accept document JSON, SVG text, PNG data URL, optional DXF base64, and return relative output file paths.

- [ ] **Step 4: Verify output tests**

Run:

```powershell
npm run test --workspace @flower/api -- tests/test_outputs.py -q
```

Expected: output-save tests pass.

- [ ] **Step 5: Commit module**

Run:

```powershell
git add services/api/app/domain/outputs services/api/app/schemas/outputs.py services/api/app/main.py services/api/tests/test_outputs.py
git commit -m "feat(api): save order outputs safely"
```

## Task 4: Frontend API Client

**Files:**
- Modify: `apps/desktop/src/renderer/api/client.ts`
- Modify: `apps/desktop/src/renderer/api/client.test.ts`

- [ ] **Step 1: Write failing client tests**

Add tests for `parseOrder`, `applyTemplate`, `exportDxf`, and `saveOutputs` request method, URL, and JSON payload.

Run:

```powershell
npm run test --workspace @flower/desktop -- src/renderer/api/client.test.ts
```

Expected before implementation: methods are missing.

- [ ] **Step 2: Implement typed client methods**

Add TypeScript interfaces matching backend schemas and POST helper support.

- [ ] **Step 3: Verify client tests**

Run:

```powershell
npm run test --workspace @flower/desktop -- src/renderer/api/client.test.ts
```

Expected: client tests pass.

- [ ] **Step 4: Commit module**

Run:

```powershell
git add apps/desktop/src/renderer/api/client.ts apps/desktop/src/renderer/api/client.test.ts
git commit -m "feat(desktop): add order workflow API client"
```

## Task 5: Text And Font Layer Editing

**Files:**
- Modify: `apps/desktop/src/renderer/canvas/layerFabricModel.ts`
- Modify: `apps/desktop/src/renderer/canvas/layerFabricModel.test.ts`

- [ ] **Step 1: Write failing layer update tests**

Test `updateTextLayerContent` changes text and drops stale `glyphOverrides`; test `updateTextLayerFont` changes `fontRef.family` and `assetId`.

Run:

```powershell
npm run test --workspace @flower/desktop -- src/renderer/canvas/layerFabricModel.test.ts
```

Expected before implementation: helper functions are missing.

- [ ] **Step 2: Implement text/font update helpers**

Keep helpers pure and validate the resulting `LayerDocument`.

- [ ] **Step 3: Verify layer model tests**

Run:

```powershell
npm run test --workspace @flower/desktop -- src/renderer/canvas/layerFabricModel.test.ts
```

Expected: layer model tests pass.

- [ ] **Step 4: Commit module**

Run:

```powershell
git add apps/desktop/src/renderer/canvas/layerFabricModel.ts apps/desktop/src/renderer/canvas/layerFabricModel.test.ts
git commit -m "feat(desktop): edit text layer content and fonts"
```

## Task 6: Frontend Workflow And Export Actions

**Files:**
- Modify: `apps/desktop/src/renderer/App.tsx`
- Modify: `apps/desktop/src/renderer/styles.css`

- [ ] **Step 1: Add UI with existing client and model helpers**

Add order note inputs, parse/apply button, text/font controls in the inspector, DXF export button, and save-all button.

- [ ] **Step 2: Run focused desktop tests**

Run:

```powershell
npm run test --workspace @flower/desktop
```

Expected: desktop tests pass.

- [ ] **Step 3: Run desktop type check**

Run:

```powershell
npm run lint --workspace @flower/desktop
```

Expected: TypeScript check passes.

- [ ] **Step 4: Commit module**

Run:

```powershell
git add apps/desktop/src/renderer/App.tsx apps/desktop/src/renderer/styles.css
git commit -m "feat(desktop): add order workflow controls"
```

## Task 7: Final Verification

- [ ] **Step 1: Backend verification**

Run:

```powershell
npm run test --workspace @flower/api
npm run lint --workspace @flower/api
npm run build --workspace @flower/api
```

- [ ] **Step 2: Frontend verification**

Run:

```powershell
npm run test --workspace @flower/desktop
npm run lint --workspace @flower/desktop
npm run build --workspace @flower/desktop
```

- [ ] **Step 3: Shared package verification**

Run:

```powershell
npm run test --workspace @flower/design-core
npm run lint --workspace @flower/design-core
npm run build --workspace @flower/design-core
```

- [ ] **Step 4: Root verification**

Run:

```powershell
npm run test
npm run lint
npm run build
```

Expected: any failing command is reported with exact failing output and no false completion claim.
