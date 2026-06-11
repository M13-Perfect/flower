# Refactor Audit

## Scope

This audit covers the current repository at `C:\Users\Administrator\Documents\flower`.
It focuses on the existing implementation, not the target architecture described in
`AGENTS.md`.

Current reality: this repository is a Python/Tkinter Birth Flower MVP. It is not yet
the intended Electron + React + Fabric.js + FastAPI + shared TypeScript schema
monorepo.

Business-domain evidence cross-checked during the audit:

1. `AGENTS.md` defines the product as an order-driven material generation editor.
2. `README.md` identifies the current app as `Birth Flower MVP`.
3. Source code contains the full production chain: order parsing, material/font
   resolution, layer document state, glyph handling, and PNG/SVG/DXF export.

## Executive Summary

The current system is functionally valuable but architecturally transitional. The
best ROI path is not a direct rewrite. The lowest-cost migration is:

1. Freeze the Tkinter MVP as the production fallback.
2. Extract the domain and export logic behind stable JSON contracts.
3. Make `Document` the only export input.
4. Build the Electron/React/Fabric editor against that contract.
5. Deprecate the Tkinter UI only after output parity is proven.

The main architectural gap is that the current UI is already layer-oriented, but the
layer model is still Python dataclasses, not a versioned serializable design-core
schema. The main export gap is that multi-layer PNG/SVG exists, but multi-layer DXF
does not, and text/glyph output is not yet stable vector geometry.

## Repository Shape

Current tracked source is flat Python modules plus tests:

- `birth_flower_mvp.py`: Tkinter app entrypoint.
- `ui_app.py`: main desktop UI, app state, canvas interactions, parsing dispatch,
  glyph dispatch, and export dispatch.
- `models.py`: parser result, design, asset, font, layer, document, and layer
  mutation dataclasses.
- `renderer.py`: single-design and multi-layer export/render code.
- `text_layout.py`: personalization text layout and ink bbox measurement.
- `text_renderer.py`: transparent PNG text rendering for `TextLayer`.
- `glyph_service.py`: glyph scanning, mapping, rules, overrides, and thumbnails.
- `glyph_panel.py`: Tkinter glyph UI.
- `asset_resolver.py`: flower and font asset scanning.
- `birth_flower_parser.py`, `parse_pipeline.py`, `gpt_parser.py`,
  `order_importer.py`, `order_batch.py`: order import/parse pipeline.
- `config_store.py`: local UI configuration persistence.
- `visual_layout.py`: bbox-to-target fitting.
- `tests/`: broad pytest coverage for parser, renderer, glyphs, UI helpers,
  layer model, config, and packaging.

The target directories from `AGENTS.md` do not currently exist:

- `apps/desktop`
- `apps/desktop/src/renderer`
- `services/api`
- `packages/design-core`
- `templates`
- `assets`

## 1. Current UI Architecture

The UI is a single Tkinter application class:

- Entry: `birth_flower_mvp.py` imports and runs `ui_app.main()`.
- Main class: `ui_app.py` defines `BirthFlowerApp`.
- UI framework: `tkinter` and `ttk`.
- Canvas: `tk.Canvas`.
- Menus and dialogs: classic Tk menu, settings windows, layout editor, glyph panel.

Important code locations:

- `ui_app.py:411`: `BirthFlowerApp`.
- `ui_app.py:412-511`: constructor initializes root window, Tk variables, config,
  assets, `Document`, preview cache, glyph configs, and runtime dependency status.
- `ui_app.py:512-543`: menu setup.
- `ui_app.py:645-670`: layer panel.
- `ui_app.py:672-708`: order and manual confirmation panel.
- `ui_app.py:710-733`: live canvas panel.
- `ui_app.py:735-761`: production/material/font controls.
- `ui_app.py:763-783`: output bar and final confirmation button.

The current UI state is split across:

- Tk variables such as `name_var`, `month_var`, `font_var`, `flower_var`,
  `output_var`, and `layout_vars`.
- The layer document: `self.document`.
- Asset caches: `flower_assets`, `font_assets`, `flower_label_map`,
  `font_label_map`.
- Preview caches: `preview_cache`, `preview_text_images`,
  `preview_font_family_cache`.
- Glyph state: `glyph_config`, `glyph_bindings`, `glyph_rules`,
  `current_glyph_result`, `current_glyph_overrides`, `selected_glyph_position`.
- Inline editing state: `inline_text_entry`, `inline_text_layer_id`,
  `floating_text_editor`.

Audit conclusion: the Tkinter UI should be treated as an MVP shell, not as an
architecture to extend. It is too coupled to migrate incrementally into React. Its
behavior should be harvested into tests and services.

## 2. Image Rendering And Export Flow

There are two export models in `renderer.py`.

### Single-Design Export

The older path takes `BirthFlowerDesign`:

- `renderer.py:86`: `render_svg`.
- `renderer.py:116`: `render_dxf`.
- `renderer.py:136`: `render_png`.

This path combines:

- One selected flower asset.
- One personalization text value.
- One font.
- One layout.
- Optional glyph overrides.

SVG uses `<text>` for text in the older path. DXF uses `TEXT` entities for text.
The code explicitly documents that text is not path-outline geometry yet.

### Multi-Layer Document Export

The newer path takes `Document`:

- `renderer.py:196`: `render_document_png`.
- `renderer.py:222`: `render_document_svg`.

This path supports multiple visible layers ordered by `Document.sorted_layers()`.

PNG export:

- Creates one RGBA canvas.
- Composites visible `ImageLayer` and `TextLayer` instances.
- Uses `TextRenderer` for text layers.

SVG export:

- Emits a top-level SVG.
- Adds SVG/bitmap image layers as `<image>`.
- Renders `TextLayer` through `TextRenderer`, then embeds the transparent PNG as
  a data URI.
- Adds comments/metadata warning that text layers are not pure vector output.

### Live Preview

Live canvas preview is in `ui_app.py`:

- `ui_app.py:2285`: `_redraw_preview`.
- `ui_app.py:2332`: `_draw_image_layer_preview`.
- `ui_app.py:2358`: `_draw_bitmap_image_layer_preview`.
- `ui_app.py:2378`: `_draw_text_layer_preview`.

Preview uses:

- `PreviewCache` for SVG path-to-polyline caching.
- `CanvasTextItem(layer).render()` for text preview.
- `PhotoImage` references retained in `preview_text_images` to avoid Tk garbage
  collection.

### Export Dispatch

Final generation is explicitly gated behind user confirmation:

- `ui_app.py:1554`: `confirm_and_generate`.
- `ui_app.py:1608-1615`: if `self.document.layers` exists, SVG/PNG use
  document export; DXF still falls back to the older single-design `render_dxf`.

Audit conclusion: export is the most important migration target. The system needs a
single Document-based export pipeline for PNG, SVG, and DXF.

## 3. Where Order Parsing Happens

Order parsing is already reasonably separated from UI.

### Import

- `order_importer.py:12`: `load_order_remark_from_file`.
- Supports `.txt`, `.json`, and `.csv`.
- Recursively searches JSON/list/dict values for known remark keys.

### Local Rule Parser

- `birth_flower_parser.py:199`: `parse_order_remark`.
- Handles multilingual labels and month names.
- Normalizes Unicode digits.
- Extracts text, month, font, and flower.
- Supports structured shop/order fields such as `Choose Your Birth Flower`,
  `Birth Month`, `Font Design`, and `Personalization`.

### AI Parser

- `gpt_parser.py:35`: `parse_order_remark_with_gpt`.
- Supports OpenAI Responses structured outputs.
- Supports DeepSeek Chat Completions JSON output.
- Normalizes model output into `ParseResult`.

### Dispatch Policy

- `parse_pipeline.py:16`: `parse_order_remark_auto`.
- If AI is preferred, call AI first and fall back to local rules.
- If AI is not preferred or disabled, use local rules only.
- Parsing does not generate files.

### UI Integration

- `ui_app.py:1173`: `parse_remark`.
- Runs parsing in a background thread through `run_background`.
- `ui_app.py:1202`: `_apply_parse_result` fills UI fields and selects pending
  flower/font choices.
- Tests verify programmatic parse refresh does not create canvas layers.

Audit conclusion: parsing code can move to `services/api/app/domain` with minimal
behavioral change. The UI should call an API endpoint and display `ParseResult`.

## 4. Fonts And Glyphs

### Font Asset Scanning

- `asset_resolver.py:114`: `scan_font_assets`.
- Accepts one font file or a directory.
- Assigns business font indexes by file names and sizes:
  - `Malovely Script` small/large -> Font 1/2.
  - `AdoraBella` small/large -> Font 3/4.
- Marks Font 2 and Font 4 as having ending glyphs.
- Reads family name through `fontTools.ttLib.TTFont` when available.

### Glyph Config And Rules

- `glyph_maps/glyph_maps.json`: legacy font-to-ending-codepoint config.
- `glyph_maps/glyph_bindings.json`: base character binding metadata.
- `glyph_maps/glyph_rules.json`: automatic start/end replacement rules.
- `glyph_service.py:37-41`: Font 2 default a-z ending glyphs map to
  `U+E068` through `U+E081`.

### Glyph Scanning And Rendering

- `glyph_service.py:417`: `scan_font_glyphs`.
- Reads cmap and glyph order through `fontTools`.
- Includes unmapped glyphs when not filtering to PUA only.
- `glyph_service.py:522`: `render_glyph_thumbnail`.
- Mapped glyphs render through Pillow.
- Unmapped glyphs render through `freetype-py` by glyph index.

### Glyph Application

- `glyph_service.py:545`: `apply_glyph_overrides`.
- `glyph_service.py:1031`: `rebuild_render_text`.
- `glyph_service.py:1096`: `apply_glyph_variant_to_text`.
- `glyph_service.py:1115`: `apply_automatic_glyph_rules`.

`TextLayer` stores:

- `original_text`: customer/user-visible text.
- `render_text`: text after glyph substitutions.
- `glyph_overrides`: per-character replacement metadata.

### Glyph UI

- `glyph_panel.py` is a Tkinter panel tightly coupled to the app object.
- It directly reads and mutates `app.document`, `app.selected_glyph_position`,
  `app.glyph_bindings`, `app.font_asset_var`, and app private helpers.

Audit conclusion: `glyph_service.py` is valuable and reusable. `glyph_panel.py` is
UI-specific and should be replaced in React. The highest unresolved glyph risk is
unmapped glyph export: it can be previewed as a bitmap thumbnail, but cannot yet be
exported as stable SVG/DXF vector geometry.

## 5. Where Canvas State Is Stored

Canvas document state lives in `models.py`.

Important code locations:

- `models.py:103`: `Layer`.
- `models.py:129`: `ImageLayer`.
- `models.py:141`: `TextLayer`.
- `models.py:186`: `GlyphLayer`.
- `models.py:195`: `Document`.
- `models.py:230`: `add_image_layer`.
- `models.py:263`: `add_text_layer`.
- `models.py:297`: `delete_layer`.
- `models.py:313`: `move_layer`.
- `models.py:339`: `hit_test`.

`Document` stores:

- `canvas_width`
- `canvas_height`
- `layers`
- `selected_layer_id`

Layer order is normalized through `z_index` and list order.

`BirthFlowerApp` uses `self.document` as the live canvas data source. However,
other state still lives outside the document:

- Current order fields.
- Output choices.
- Selected/pending asset labels.
- Glyph panel state.
- Inline editor state.
- Preview cache.
- Layout defaults.

Audit conclusion: `Document` is the right conceptual center, but it is not yet a
portable, versioned JSON document. It should be promoted into `packages/design-core`
and mirrored with Python Pydantic models.

## 6. Code That Can Be Reused

High-value reusable modules:

- `birth_flower_parser.py`: local deterministic parser.
- `parse_pipeline.py`: parse fallback policy, after API-bound adaptation.
- `gpt_parser.py`: provider adapter logic, after being wrapped by backend service
  boundaries.
- `order_importer.py`: file import shape, useful for backend ingestion tests.
- `order_batch.py`: early batch result/validation model.
- `asset_resolver.py`: flower/font scanning and business numbering.
- `glyph_service.py`: glyph catalog, rules, bindings, codepoint validation, and
  render-text reconstruction.
- `text_layout.py`: deterministic text layout and ink bbox calculation.
- `text_renderer.py`: current visual text rasterization implementation.
- `visual_layout.py`: generic bbox fitting.
- `renderer.py`: SVG path parsing, visual bbox extraction, preview polylines,
  and current export logic.
- `models.py`: domain concepts, after conversion to versioned schemas.
- Tests in `tests/`: they encode current production behavior and should guide the
  migration.

## 7. Code That Should Be Deprecated

Deprecate or freeze:

- `ui_app.py`: keep as legacy shell until new app reaches parity.
- `glyph_panel.py`: replace with React glyph UI.
- `birth_flower_mvp.py`: replace with Electron entry.
- `tools/build_windows_exe.py`: useful only for legacy Tkinter packaging.
- `BirthFlowerMVP.spec`: legacy PyInstaller packaging.
- `BirthFlowerDesign`: old single-design export DTO; replace with Document export
  input after compatibility bridge is built.
- Direct config writes in the source directory through `config_store.py`: replace
  with app/user config storage and backend settings APIs.

Do not delete these immediately. Freeze first, then remove only after tests prove
Electron/FastAPI parity.

## 8. Highest-Risk Modules

### 1. `ui_app.py`

Risk: highest.

Reason: nearly all application orchestration is in one class: Tk variables,
canvas state, parsing, glyph dispatch, preview rendering, config persistence,
asset scanning, and export dispatch.

Migration action: treat as behavior reference and test source, not as code to port.

### 2. `renderer.py`

Risk: high.

Reason: old single-design exports and new multi-layer exports coexist. DXF is not
Document-based. Text vector fidelity is incomplete.

Migration action: create a unified Document export service.

### 3. `glyph_service.py`

Risk: high.

Reason: glyph logic handles cmap, PUA, unmapped glyphs, manual overrides, automatic
rules, config repair, and dependency detection. The business value is high, but
edge cases are numerous.

Migration action: keep service code, add path/outline export work before relying on
SVG/DXF glyph fidelity.

### 4. `text_renderer.py`

Risk: high for target architecture.

Reason: it rasterizes `TextLayer` to transparent PNG for visual consistency. This
conflicts with the target rule that text and layers must remain editable during
editing and that SVG should preserve vector paths when possible.

Migration action: keep as PNG preview/export fallback, but implement vector text or
text-outline export for SVG/DXF.

### 5. `models.py`

Risk: medium-high.

Reason: concepts are correct, but the model is not a stable JSON schema and has no
versioned migrations.

Migration action: define `design-core` schemas before changing UI.

### 6. `config_store.py`

Risk: medium.

Reason: local app config is file-based and source-directory oriented.

Migration action: separate user settings from document state and backend config.

### 7. `asset_resolver.py`

Risk: medium.

Reason: business asset matching relies heavily on filenames and fixed business
font rules.

Migration action: move fixed rules into templates/config and validate scanned
assets.

### 8. `gpt_parser.py`

Risk: medium.

Reason: direct provider calls are embedded in local code. Good tests exist, but a
backend service should own provider adapters, rate/error policy, and secrets.

Migration action: wrap behind backend parse service.

## Architecture Gaps Against `AGENTS.md`

The current repository violates or only partially satisfies the target architecture:

- No `apps/desktop` Electron shell.
- No React + TypeScript frontend.
- No Fabric.js canvas.
- No `services/api` FastAPI backend.
- No `packages/design-core` shared TypeScript schemas.
- No template JSON system under `templates`.
- No formal JSON document persistence layer.
- No backend route/domain separation.
- No path traversal validation around future API file operations because there is
  no API yet.

The current code does satisfy several product rules conceptually:

- Manual confirmation before final generation.
- Layer-based document model.
- Separation between parser modules and renderer modules.
- Export helper suppression from output.
- Font/glyph error handling in several paths.
- Tests for parser, config, renderer, glyph, and UI helper behavior.

## Migration Recommendation

### Phase 0: Freeze And Baseline The MVP

Goal: stop compounding Tkinter coupling while preserving the working production
tool.

Actions:

- Mark `ui_app.py` and `glyph_panel.py` as legacy UI.
- Allow only bug fixes and behavior tests in legacy UI.
- Add an explicit legacy smoke test list:
  - parse note
  - add image layer
  - add text layer
  - apply glyph
  - export PNG
  - export SVG
  - reject bitmap DXF
- Capture golden outputs for a small set of known templates/assets.

ROI: high. Cost is low and it prevents rewrite drift.

### Phase 1: Define The Design Document Contract

Goal: make the layer document portable.

Actions:

- Create `packages/design-core` with TypeScript schemas for:
  - `Document`
  - `Layer`
  - `ImageLayer`
  - `TextLayer`
  - `GlyphOverride`
  - `ExportOptions`
  - `TemplateReference`
  - metadata: order id, template id, timestamp, app version
- Mirror the schema in Python with Pydantic.
- Add JSON round-trip tests.
- Add migration tests from current Python dataclass instances.

ROI: highest. It unlocks React, FastAPI, and export unification.

### Phase 2: Extract Backend Domain Services

Goal: move deterministic production logic out of UI.

Target modules:

- `services/api/app/domain/order_parser.py`
- `services/api/app/domain/asset_resolver.py`
- `services/api/app/domain/font_service.py`
- `services/api/app/domain/glyph_service.py`
- `services/api/app/domain/text_layout.py`
- `services/api/app/domain/export_service.py`

Actions:

- Move or wrap parser logic from `birth_flower_parser.py`.
- Move AI provider adapters from `gpt_parser.py`.
- Move asset and font scanning from `asset_resolver.py`.
- Move glyph service with minimal changes first.
- Keep route handlers thin.
- Add path validation before any API file operation.

ROI: high. It preserves working logic while creating the backend required by the
target architecture.

### Phase 3: Unify Export Around `Document`

Goal: remove split export behavior.

Actions:

- Make `Document` JSON the only export input.
- Port `render_document_png` and `render_document_svg` to the new schema.
- Implement `render_document_dxf`.
- Decide text policy:
  - PNG: raster text acceptable.
  - SVG: preserve `<text>` for editable preview exports or convert to paths for
    production-safe exports.
  - DXF: convert text/glyphs to path-like geometry before final production export.
- Add explicit export modes:
  - editable SVG
  - production SVG
  - production DXF
  - PNG proof

ROI: high. This directly addresses production correctness.

### Phase 4: Build The React/Fabric Editor

Goal: replace Tkinter interactions without rewriting business logic.

Actions:

- Create `apps/desktop`.
- Use Electron shell.
- Build React renderer under `apps/desktop/src/renderer`.
- Use Fabric.js only inside canvas modules.
- Store editor state as Document JSON.
- Keep selection boxes, handles, guides, and debug overlays outside export state.
- Build typed API client for parse, asset scan, font scan, glyph scan, and export.

ROI: medium-high after Phases 1-3. Doing this first has poor ROI because it would
duplicate unstable contracts.

### Phase 5: Template System

Goal: move hardcoded birth flower layout rules into templates.

Actions:

- Create `templates/`.
- Define template JSON for:
  - canvas size
  - slots
  - default flower placement
  - text placement
  - allowed output formats
  - asset categories
- Convert current `EngravingLayout` defaults into a template.
- Add tests for invalid/missing templates.

ROI: medium. Required for multi-product material generation.

### Phase 6: Cutover And Deprecation

Goal: retire Tkinter only after parity.

Actions:

- Run new app and legacy app against the same golden cases.
- Compare PNG snapshots and SVG/DXF structural expectations.
- Keep `ui_app.py` available as rollback until production exports match.
- Remove or archive legacy packaging after successful cutover.

ROI: high risk-control value.

## Recommended Immediate Next Step

Create an execution plan under `docs/` for Phase 1: Design Document Contract.

Do not start by building the Electron UI. That path has poor ROI because the
current schema/export contract is not stable enough. The cheapest global path is
to make the document model portable first, then move deterministic services, then
build the new editor.

## Verification Notes

This audit is based on static repository inspection. Tests were not run during the
initial read-only audit because the project confirmation gate had not yet been
satisfied. After confirmation, this document was created only; no production code
was modified.

Recommended verification after future implementation work:

- `pytest`
- `ruff check .`
- `mypy app` once `services/api` exists
- `pnpm lint` once `apps/desktop` exists
- `pnpm test` once `apps/desktop` exists
- export golden tests for PNG/SVG/DXF once templates exist

