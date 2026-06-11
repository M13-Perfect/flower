# SELF CHECK REPORT

Date: 2026-06-11

Confirmed project root: `C:\Users\Administrator\Documents\flower`

Working directory: `C:\Users\Administrator\Documents\flower`

Business-domain evidence:
- `AGENTS.md`: order-driven material generation editor.
- `templates/products/birth-flower-card.json`: product template exists.
- `apps/desktop/src/renderer/canvas`, `apps/desktop/src/renderer/export`, `services/api/app/domain/orders`, `services/api/app/domain/fonts`, `services/api/app/domain/exports`: editor, parser, font, and export domains exist.

## Executive Verdict

Overall status: **FAIL**

Reason: the desktop/editor TypeScript side builds and its SVG/PNG export smoke passes, but the FastAPI side cannot start, test, lint, or typecheck because the active Python environment is missing `fastapi`, `uvicorn`, `ruff`, and `mypy`. The new desktop app is also still a sample layer editor, not the full order-driven parse -> template -> editable document -> export workflow.

Highest ROI fix order:
1. Fix Python environment/bootstrap first: install API runtime and dev dependencies into the exact interpreter used by `tools/python.mjs`.
2. Choose one Node package manager. Current repo scripts are `npm`; AGENTS says `pnpm`, but `pnpm` is not installed.
3. Wire the desktop UI to order parse/template APIs instead of `createSampleLayerDocument()`.
4. Harden root `npm run dev` process cleanup when one child fails.

## Environment

| Check | Status | Evidence |
| --- | --- | --- |
| `node --version` | PASS | `v24.14.0` |
| `npm --version` | PASS | `11.9.0` |
| `pnpm --version` | FAIL | `pnpm` is not recognized |
| `.\.venv\bin\python.exe --version` | PASS | `Python 3.14.3` |
| `.\.venv\bin\python.exe -m pytest --version` | PASS | `pytest 9.0.3` |
| `.\.venv\bin\python.exe -m ruff --version` | FAIL | `No module named ruff` |
| `.\.venv\bin\python.exe -m mypy --version` | FAIL | `No module named mypy` |

## Commands Run

| Area | Command | Status | Output summary |
| --- | --- | --- | --- |
| Root lint | `npm run lint` | FAIL | Desktop/design-core TS checks ran; API failed: `No module named ruff`. |
| Root test | `npm run test` | FAIL | Desktop `3 files / 12 tests` PASS; design-core `1 file / 9 tests` PASS; API collection failed: `No module named fastapi`. |
| Root build | `npm run build` | PASS | Desktop Vite build PASS, API `compileall app` PASS, design-core build PASS. Vite warns chunk is `519.82 kB`. |
| Desktop lint | `npm run lint --workspace @flower/desktop` | PASS | `tsc -p tsconfig.json --noEmit` and `tsc -p tsconfig.node.json --noEmit` passed. |
| Desktop test | `npm run test --workspace @flower/desktop` | PASS | `3 passed (3)`, `12 passed (12)`. Initial sandbox failure was re-run outside sandbox and passed. |
| Desktop build | `npm run build --workspace @flower/desktop` | PASS | Vite build passed; chunk-size warning over 500 kB. |
| Desktop dev | `npm run dev --workspace @flower/desktop` | PASS | Vite ready on `127.0.0.1:5173`; HTTP `/` returned 200. |
| Desktop browser smoke | in-app Browser to `http://127.0.0.1:5173/` | PASS | Page title `Flower Editor`; H1 `Layer editor`; canvas exists; Export/JSON controls visible; no browser error logs. Backend badge shows `Failed to fetch`. |
| Desktop UI export smoke | Browser clicked export SVG and PNG buttons | PASS | Export state changed from `ready` to `SVG 2026-06-11T14:19:37.533Z`, then `PNG 900x620`; no browser error logs. |
| Desktop export unit smoke | `npm run test --workspace @flower/desktop -- src/renderer/export/exportPipeline.test.ts` | PASS | `1 file / 3 tests` passed: SVG, PNG, metadata, helper-layer exclusion. |
| design-core lint | `npm run lint --workspace @flower/design-core` | PASS | TypeScript noEmit passed. |
| design-core test | `npm run test --workspace @flower/design-core` | PASS | `1 file / 9 tests` passed. |
| design-core build | `npm run build --workspace @flower/design-core` | PASS | `tsc -p tsconfig.build.json` passed. |
| API lint | `npm run lint --workspace @flower/api` | FAIL | `No module named ruff`. |
| API test | `npm run test --workspace @flower/api` | FAIL | 4 collection errors: `No module named fastapi`. |
| API build | `npm run build --workspace @flower/api` | PASS | `compileall app` passed. This only checks syntax/import compilation, not runtime dependencies. |
| API typecheck | `.\.venv\bin\python.exe -m mypy app` from `services/api` | FAIL | `No module named mypy`. |
| API dev | `npm run dev --workspace @flower/api` | FAIL | `No module named uvicorn`. |
| API health smoke | `Invoke-WebRequest http://127.0.0.1:8765/health` | FAIL | `Unable to connect to remote server`. |
| Root dev | `npm run dev` | FAIL | Desktop starts; API fails `No module named uvicorn`; root script left a Vite child process until manually killed. |
| Root pytest all | `.\.venv\bin\python.exe -m pytest -q` | FAIL | API tests collected first and failed on `No module named fastapi`. |
| Legacy root tests | `.\.venv\bin\python.exe -m pytest tests -q` | PASS | `193 passed in 3.51s`. |
| Root ruff | `.\.venv\bin\python.exe -m ruff check .` | FAIL | `No module named ruff`. |
| Root mypy | `.\.venv\bin\python.exe -m mypy .` | FAIL | `No module named mypy`. |
| DXF domain smoke | direct `export_dxf()` with fake `ezdxf` and path layer | PASS | Returned `.dxf`, `application/dxf`, `INSUNITS=0`, layer metadata. This is not API endpoint validation. |

## NOT RUN

| Command / project | Status | Reason |
| --- | --- | --- |
| `pnpm lint` | NOT RUN | `pnpm` is not installed. Equivalent `npm run lint` was run and failed on API `ruff`. |
| `pnpm test` | NOT RUN | `pnpm` is not installed. Equivalent `npm run test` was run and failed on API `fastapi`. |
| `pnpm build` | NOT RUN | `pnpm` is not installed. Equivalent `npm run build` passed. |
| `pnpm --filter desktop dev` | NOT RUN | `pnpm` is not installed. Equivalent `npm run dev --workspace @flower/desktop` passed. |
| `pnpm --filter desktop build` | NOT RUN | `pnpm` is not installed. Equivalent `npm run build --workspace @flower/desktop` passed. |
| API route smoke: `POST /orders/parse` | NOT RUN | API cannot start: `uvicorn` missing. |
| API route smoke: `POST /templates/apply` | NOT RUN | API cannot start: `uvicorn` missing. |
| API route smoke: `POST /exports/dxf` | NOT RUN | API cannot start: `uvicorn` missing. Direct domain smoke was run separately with fake `ezdxf`. |
| Real DXF export with real `ezdxf` | NOT RUN | API/dev environment missing dependencies; direct smoke used fake `ezdxf`. |

## Failure Register

### F1: API environment missing runtime and dev dependencies

Risk: **HIGH**

Commands:
- `npm run test --workspace @flower/api`
- `npm run dev --workspace @flower/api`
- `npm run lint --workspace @flower/api`
- `.\.venv\bin\python.exe -m mypy app`

Error summary:
- `ModuleNotFoundError: No module named 'fastapi'`
- `No module named uvicorn`
- `No module named ruff`
- `No module named mypy`

Impact:
- Backend cannot start.
- API route smoke cannot run.
- API tests, lint, and typecheck are blocked.
- Root `npm run test` and `npm run lint` fail.

Fix recommendation:
- Install API runtime and dev dependencies into `C:\Users\Administrator\Documents\flower\.venv\bin\python.exe`, not another Python.
- Prefer one bootstrap command, for example `python -m pip install -e services/api[dev]` or `python -m pip install -r requirements.txt`, then re-run API commands.
- Consider using Python 3.11 or 3.12 for stability; current venv is Python 3.14.3.

### F2: AGENTS command set requires `pnpm`, but repo has runnable `npm` workspace scripts

Risk: **MEDIUM**

Command:
- `pnpm --version`

Error summary:
- `pnpm` is not recognized.

Impact:
- Documented frontend/desktop commands cannot be followed literally.
- CI/local onboarding will diverge depending on whether operators use `npm` or `pnpm`.

Fix recommendation:
- Either add a pinned `packageManager` field and committed `pnpm-lock.yaml`, then require Corepack/pnpm, or update AGENTS/docs to use `npm`.
- Do not keep both as implied standards.

### F3: Root dev orchestration leaves frontend residue when API child fails

Risk: **MEDIUM**

Command:
- `npm run dev`

Error summary:
- API child failed: `No module named uvicorn`.
- Desktop child continued listening on `127.0.0.1:5173` and had to be manually killed.
- Node warning: `DEP0190 Passing args to a child process with shell option true can lead to security vulnerabilities`.

Impact:
- False-positive startup: UI appears up while API is dead.
- Repeated runs hit `Port 5173 is already in use`.
- Process cleanup is unreliable.

Fix recommendation:
- Remove `shell: true` where possible in `tools/dev.mjs`, or use a proven process manager.
- On any child failure, terminate the whole process tree and wait for child exit.
- Emit a nonzero final status only after cleanup completes.

### F4: New desktop app is still a sample editor, not the order-driven workflow

Risk: **HIGH**

Evidence:
- `apps/desktop/src/renderer/App.tsx:37` initializes from `createSampleLayerDocument()`.
- `apps/desktop/src/renderer/App.tsx:419` defines the sample document in app code.
- `apps/desktop/src/renderer/api/client.ts:92-104` only exposes `health`, `listFonts`, and `listFontGlyphs`.
- No desktop client methods or UI were found for `/orders/parse`, `/templates/apply`, or `/exports/dxf`.

Impact:
- It is usable as a layer editing prototype, but not yet the stated product.
- Customer order notes are not parsed through the UI.
- Product templates are not applied through the UI.
- DXF export is not reachable from the desktop UI.

Fix recommendation:
- Add typed client methods for parse/template/DXF endpoints.
- Replace the hardcoded sample document with parse -> manual confirm -> apply template -> editable `LayerDocument`.
- Add UI smoke tests for the real order workflow, not only the sample document.

### F5: Chinese comments and some Chinese strings are mojibake

Risk: **MEDIUM**

Evidence:
- `services/api/app/domain/orders/parser.py` comments and label aliases contain mojibake in earlier output.
- `services/api/app/domain/templates/engine.py` comments contain mojibake.
- `parse_pipeline.py` docstring and warning strings are mojibake.

Impact:
- Business rules are harder to audit.
- Chinese parsing aliases may be broken where mojibake replaced intended labels.

Fix recommendation:
- Normalize source files to UTF-8.
- Add tests for Chinese order labels.
- Review all Chinese comments/strings in Python modules.

### F6: Vite production bundle warning

Risk: **LOW**

Command:
- `npm run build --workspace @flower/desktop`

Error summary:
- Vite warning: one minified chunk is `519.82 kB`, above 500 kB.

Impact:
- Not a correctness failure.
- Startup/download cost may grow as editor features expand.

Fix recommendation:
- Split Fabric/editor code with dynamic imports if the app grows.

## Required Domain Checks

### 1. Is the functionality an empty shell?

Verdict: **PARTIAL / HIGH RISK**

The current desktop app is not empty: it renders a Fabric canvas, allows layer selection/property edits, can save JSON to a textarea, and can export SVG/PNG from the sample document. Browser smoke confirms the page renders and export buttons work.

However, the order-driven product workflow is not implemented end to end in the desktop app. It starts with a hardcoded sample document and does not call parse/template APIs. This is a prototype editor shell, not a complete order-driven material generation editor.

### 2. Does edit state pollute export state?

Verdict: **PASS with residual risk**

Evidence:
- Export builds a fresh scene from `LayerDocument`, not from the live Fabric viewport: `apps/desktop/src/renderer/export/exportPipeline.ts:79`, `:94`, `:174`.
- Helper-layer markers are filtered even if accidentally marked exportable: `apps/desktop/src/renderer/export/exportPipeline.ts:62`, `:321`.
- Document validation rejects UI-only keys: `packages/design-core/src/index.ts:206`, `:651`.
- Tests assert `selection_box`, `debug-bounds`, and debug fill do not appear in SVG export.
- DXF export has its own helper marker filter: `services/api/app/domain/exports/dxf.py:22`, `:231`.

Residual risk:
- Frontend asset paths in SVG export are emitted as `href` values; frontend export does not validate project-relative asset paths. Backend DXF does validate asset paths.

### 3. Is layer JSON the single source of truth?

Verdict: **MOSTLY PASS for layer geometry; PARTIAL for product state**

Evidence:
- Fabric object changes are serialized back to `LayerDocument`: `apps/desktop/src/renderer/canvas/FabricCanvas.tsx:83-92`.
- Runtime Fabric metadata is stored separately on objects and converted back through snapshots: `FabricCanvas.tsx:246`, `:270`.
- `serializeLayerDocumentFromSnapshots()` validates the saved document: `apps/desktop/src/renderer/canvas/layerFabricModel.ts:113`.

Gaps:
- The UI starts from `createSampleLayerDocument()` and does not hydrate from API/template data.
- `savedJson` is a textarea snapshot, not durable storage.
- PNG `scale` and `transparent` are React UI state overrides, not persisted back into `document.exportSettings`.

### 4. Are PNG/SVG exports usable?

Verdict: **PASS for desktop sample document**

Evidence:
- Unit smoke: `exportPipeline.test.ts` passed 3 tests for SVG, PNG, metadata, and helper exclusion.
- Browser smoke clicked real SVG/PNG buttons:
  - SVG state: `SVG 2026-06-11T14:19:37.533Z`
  - PNG state: `PNG 900x620`
  - Browser error logs: none

Limitations:
- PNG test uses injected rasterizer at unit level; real browser button smoke did execute actual browser rasterization, but did not inspect the downloaded file bytes.
- Backend DXF endpoint was not runnable because the API cannot start.

### 5. Are font/material missing cases handled?

Verdict: **PARTIAL**

Evidence:
- Frontend canvas catches layer load errors and creates missing placeholders: `apps/desktop/src/renderer/canvas/FabricCanvas.tsx`.
- Backend font scanner emits structured issues such as `FONT_DIRECTORY_MISSING` and `FONT_READ_FAILED`: `services/api/app/domain/fonts/scanner.py:99`, `:158`.
- DXF font resolution returns structured errors for missing fonts/glyphs.

Gaps:
- The current Python environment cannot run the API font tests because `fastapi` is missing.
- Source includes mojibake in some Chinese business comments/strings.
- Template engine builds flower asset paths but does not verify the asset exists at template-apply time; failure is deferred to render/export.

### 6. Is path safety acceptable?

Verdict: **PASS on backend critical paths; PARTIAL on frontend**

Evidence:
- Template id is regex-limited before path construction: `services/api/app/domain/templates/engine.py:58`.
- Template path is resolved and checked under project root: `engine.py:67-79`.
- DXF asset path blocks absolute paths and traversal: `services/api/app/domain/exports/dxf.py:931-942`.
- Font scanner converts stored relative paths back through project-root validation: `services/api/app/domain/fonts/scanner.py:366-370`.

Gap:
- Frontend `resolveAssetUrl()` accepts `http://`, `https://`, `blob:`, `data:`, absolute `/`, and arbitrary relative strings. This is acceptable for an editor preview, but not enough for production export policy if untrusted layer JSON can enter the renderer.

### 7. Is customer privacy logging acceptable?

Verdict: **PASS for new API code seen; PARTIAL for legacy AI path**

Evidence:
- `services/api/tests/test_orders_templates.py:61` asserts raw order note is not in logs.
- `services/api/app/main.py` does not log request bodies.
- Legacy logs found generally use `order_id`, `layer_id`, font id, warnings, and exception reasons, not raw notes.

Residual risk:
- Legacy AI parser paths can transmit order remarks to OpenAI/DeepSeek when AI parsing is explicitly enabled. That is a product feature, but privacy UX and consent should remain explicit.
- Do not store raw customer order data in logs; keep the existing test and extend it to batch/legacy paths if those remain production entry points.

## Cleanup Performed

Temporary Vite servers created during smoke tests were killed. Final port check showed no `LISTENING` entry on `5173` or `8765`; only transient `TIME_WAIT` / `FIN_WAIT_2` rows remained.

## Recommended Acceptance Gate

Do not accept this project as production-ready.

Minimum next gate:
- `npm run lint` PASS.
- `npm run test` PASS.
- `npm run build` PASS.
- API dev starts and `/health`, `/orders/parse`, `/templates/apply`, `/exports/dxf` smoke pass.
- Desktop workflow starts from real order input, applies a real template, edits a real layer document, and exports SVG/PNG/DXF.
- Remove or clearly freeze legacy Tkinter MVP from new architecture acceptance criteria.
