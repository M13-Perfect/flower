# AGENTS.md

## Project Goal

This project is an order-driven material generation editor.

The goal is to build a lightweight design editor for custom product assets:
- Parse customer order notes.
- Apply product templates.
- Create editable layer-based designs.
- Let the user manually confirm and adjust.
- Export PNG, SVG, and later DXF.

## Architecture

Use the following architecture:

- `apps/desktop`: Electron desktop shell.
- `apps/desktop/src/renderer`: React + TypeScript frontend.
- `apps/desktop/src/renderer/canvas`: Fabric.js canvas editor.
- `services/api`: Python FastAPI backend.
- `services/api/app/domain`: business logic.
- `packages/design-core`: shared TypeScript schemas for templates and layer models.
- `templates`: JSON product templates.
- `assets`: local fonts, flowers, sample files.
- `docs`: architecture, export pipeline, font handling, and refactor notes.

## Core Rules

- Preserve editability. Do not rasterize text, SVG, or layers during editing.
- Save designs as JSON layer documents.
- Separate editor UI state from export state.
- Selection boxes, guides, debug rectangles, and handles must never appear in exported files.
- Keep parsing logic, template logic, font logic, and export logic separated.
- Prefer deterministic code over AI guessing for production export.
- Add full error handling for file I/O, font loading, SVG parsing, and export failures.
- Add Chinese comments for non-obvious business logic.
- Avoid global mutable state unless there is a clear reason.
- Do not introduce new production dependencies without explaining why.

## Frontend Conventions

- Use React + TypeScript.
- Use Fabric.js only inside canvas-related modules.
- Keep React component state separate from Fabric canvas object state.
- Use typed API clients for backend calls.
- Store editor document data in a serializable JSON model.
- Add boundary handling for empty canvas, missing fonts, missing assets, invalid templates, and failed API calls.

## Backend Conventions

- Use Python 3.11+.
- Use FastAPI for HTTP APIs.
- Use Pydantic models for request and response validation.
- Keep route handlers thin.
- Put business logic under `app/domain`.
- All file operations must validate paths and avoid path traversal.
- Return structured errors with clear error codes.
- Add pytest tests for parser, template engine, font scanner, and exporters.

## Export Rules

- PNG export must not include editor-only UI elements.
- SVG export should preserve vector paths whenever possible.
- DXF export should only use path-like geometry; convert text to paths before DXF export.
- Export outputs must include metadata: template id, order id, timestamp, app version.
- Add golden image or snapshot tests for critical templates when possible.

## Test Commands

Frontend:
- `pnpm lint`
- `pnpm test`
- `pnpm build`

Backend:
- `pytest`
- `ruff check .`
- `mypy app`

Desktop:
- `pnpm --filter desktop dev`
- `pnpm --filter desktop build`

## Definition of Done

A task is done only when:
- The feature works through the UI or API.
- Relevant tests are added or updated.
- Lint and type checks pass.
- Edge cases are handled.
- The implementation is documented if behavior changed.
- The final response includes changed files, test results, and known limitations.

## Do Not Do

- Do not rewrite unrelated modules.
- Do not mix old Tkinter UI code with the new editor.
- Do not hardcode absolute local paths.
- Do not silently ignore export errors.
- Do not assume fonts contain normal Unicode characters only.
- Do not store customer order data in logs unless explicitly needed for debugging.

## ExecPlan Rule

For complex features, migrations, or architectural refactors, create or update an execution plan under `docs/` before implementation.