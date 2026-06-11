# Font Glyph System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a font scan API and a React glyph picker that lets text layers save explicit per-character glyph overrides.

**Architecture:** The backend owns deterministic font discovery and glyph metadata extraction under `services/api/app/domain/fonts`. The renderer consumes typed endpoints, keeps picker UI state in React, and writes only serializable `glyphOverrides` into the selected text layer JSON.

**Tech Stack:** FastAPI, Pydantic, fontTools, pytest, React, TypeScript, Fabric.js, Vitest.

---

### Task 1: Backend Font API

**Files:**
- Create: `services/api/app/domain/fonts/__init__.py`
- Create: `services/api/app/domain/fonts/scanner.py`
- Create: `services/api/app/schemas/fonts.py`
- Modify: `services/api/app/main.py`
- Modify: `services/api/pyproject.toml`
- Test: `services/api/tests/test_fonts.py`

- [ ] Write failing pytest coverage for `GET /fonts` and `GET /fonts/{font_id}/glyphs`.
- [ ] Verify the tests fail because the routes do not exist.
- [ ] Implement font discovery with supported extensions `.ttf`, `.otf`, `.ttc`, `.otc`.
- [ ] Include scan issues for missing directories, unreadable/corrupt files, duplicates, and unsupported files in known font folders.
- [ ] Extract `name` table family/style, `head`/`hhea`/`OS/2` metrics, Unicode cmap records, glyph names, glyph IDs, advance widths, bounding boxes, and PUA flags.
- [ ] Return structured domain errors for missing `font_id`.
- [ ] Re-run backend tests until green.

### Task 2: Frontend Glyph Data And JSON Updates

**Files:**
- Modify: `apps/desktop/src/renderer/api/client.ts`
- Modify: `apps/desktop/src/renderer/api/client.test.ts`
- Modify: `apps/desktop/src/renderer/canvas/layerFabricModel.ts`
- Modify: `apps/desktop/src/renderer/canvas/layerFabricModel.test.ts`

- [ ] Write failing Vitest coverage for font endpoint calls.
- [ ] Write failing Vitest coverage for applying a glyph override to a text layer.
- [ ] Implement typed API methods and JSON update helper.
- [ ] Ensure original `text` remains unchanged and `glyphOverrides` stores replacement metadata.
- [ ] Re-run renderer tests until green.

### Task 3: GlyphPicker UI

**Files:**
- Create: `apps/desktop/src/renderer/GlyphPicker.tsx`
- Modify: `apps/desktop/src/renderer/App.tsx`
- Modify: `apps/desktop/src/renderer/styles.css`
- Modify: `apps/desktop/src/renderer/canvas/FabricCanvas.tsx`

- [ ] Add a panel visible only for selected text layers.
- [ ] Load fonts and glyphs from the backend and show current font availability.
- [ ] Let the user choose a character index from the selected layer text.
- [ ] Let the user replace that character with a selected Unicode mapped glyph.
- [ ] Render text preview with overrides applied while keeping saved JSON editable.
- [ ] Handle empty text, missing backend, missing font, unsupported glyph, and no PUA glyph cases.

### Task 4: Documentation And Verification

**Files:**
- Create: `docs/FONT_GLYPHS.md`

- [ ] Document scan paths, API response shape, glyph override JSON, PUA behavior, and limitations.
- [ ] Run `.\.venv\bin\python.exe -m pytest services/api/tests -q`.
- [ ] Run `pnpm --filter @flower/desktop test`.
- [ ] Run `pnpm --filter @flower/design-core test`.
- [ ] Run `pnpm --filter @flower/desktop build`.
- [ ] Report changed files, test results, and known limitations.
