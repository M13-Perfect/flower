# Production Export CAD Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make batch SVG, PNG, and DXF outputs suitable for CAD engraving by removing preview-only SVG text/image output, scaling DXF geometry to template-defined physical millimeters, and rasterizing PNG from the corrected SVG.

**Architecture:** Keep the source of product physical size in `templates/products/<template>.json` under `exportSettings`. Reuse the existing FastAPI export modules so batch generation, API export, and future UI flows share one production export path.

**Tech Stack:** Python 3.11, FastAPI domain modules, fontTools, xml.etree.ElementTree, ezdxf, cairosvg, pytest.

---

## File Structure

- Modify `templates/products/birth-flower-card.json`: add per-template `exportSettings.physical.widthMm = 80`.
- Modify `services/api/app/domain/templates/engine.py`: copy template `exportSettings` into layer documents and derive `heightMm` from canvas aspect ratio.
- Modify `services/api/app/domain/exports/svg.py`: parse inline/asset SVG with ElementTree, inline child nodes in a scaled `<g>`, and convert text layers to `<path>` geometry.
- Modify `services/api/app/domain/exports/dxf.py`: derive px-to-mm scale from `document.exportSettings.physical`, set `$INSUNITS = 4`, and share/align text glyph outline behavior with SVG.
- Modify `services/api/app/domain/exports/png.py`: require cairosvg for PNG rasterization.
- Modify `services/api/app/domain/orders/workflow.py`: remove production fallback to PIL preview rendering when cairosvg is unavailable.
- Modify `services/api/pyproject.toml` and `requirements.txt`: declare `cairosvg` as a production dependency.
- Update tests under `services/api/tests/`: add XML parseability, CAD assertions, DXF physical bbox, PNG full-SVG rasterization, and golden ordering.

## Tasks

### Task 1: Red Tests For Production SVG

- [ ] Add tests that `export_svg()` output is accepted by `xml.etree.ElementTree.fromstring`.
- [ ] Add CAD assertions: no `<text>`, no `<image>`, and `<?xml` appears once at file start.
- [ ] Add a flower asset fixture containing XML declaration and DOCTYPE to prove XML parsing strips unsafe prolog markup.
- [ ] Run `pytest services/api/tests/test_svg_export.py -q`; expected failure: current output contains `<text>` or parsing/inline behavior is wrong.

### Task 2: Red Tests For Physical DXF

- [ ] Add tests that a px canvas with template `physical.widthMm = 80` exports DXF with `INSUNITS=4`.
- [ ] Add a fake ezdxf bbox assertion that output geometry width is approximately `80`.
- [ ] Run `pytest services/api/tests/test_dxf_export.py -q`; expected failure: current exporter keeps `INSUNITS=0` or unscaled px coordinates.

### Task 3: Red Tests For PNG Rasterization

- [ ] Update PNG tests so `rasterize_svg_to_png` requires cairosvg and does not silently fall back to preview paths.
- [ ] Update workflow tests so the bytes passed to cairosvg contain SVG path output for both flower and text.
- [ ] Run `pytest services/api/tests/test_png_export.py services/api/tests/test_python_batch_cli.py -q`; expected failure: current dependency/fallback assumptions differ.

### Task 4: Template Physical Settings

- [ ] Put `exportSettings.physical.widthMm = 80` in `templates/products/birth-flower-card.json`.
- [ ] Update `apply_template()` to merge template export settings over defaults and derive `heightMm = widthMm * canvas.height / canvas.width` when height is not specified.
- [ ] Preserve editability in layer JSON; only export converts text to paths.

### Task 5: SVG XML And Text Path Implementation

- [ ] Replace regex SVG shell extraction with ElementTree parsing.
- [ ] Reject malformed SVG with structured `SVG_PARSE_FAILED`.
- [ ] Remove `DOCTYPE`, XML declarations, script nodes, and event handler attributes before inlining child elements.
- [ ] Convert text layers to fontTools glyph path `<path d="...">` elements using the mapped `fontRef.assetId`/family path resolution already used by DXF.
- [ ] Keep text transform and alignment equivalent to existing output.

### Task 6: DXF Physical Scaling

- [ ] Add document physical size resolver using `exportSettings.physical.widthMm` and derived height.
- [ ] For px canvas to mm DXF, scale all geometry by `physical.widthMm / canvas.width`.
- [ ] Default target DXF units to `mm` when physical settings exist.
- [ ] Keep `$INSUNITS = 4` for production batch outputs.

### Task 7: PNG Production Path

- [ ] Make `rasterize_svg_to_png` use cairosvg as the production rasterizer.
- [ ] Remove workflow fallback to `_render_document_png_data_url()` for production generation.
- [ ] Keep old root `ui_app.py` preview export untouched.

### Task 8: Verification

- [ ] Run targeted API tests:
  `pytest services/api/tests/test_svg_export.py services/api/tests/test_dxf_export.py services/api/tests/test_png_export.py services/api/tests/test_python_batch_cli.py services/api/tests/test_batch_generate.py -q`
- [ ] Run broader backend checks if targeted tests pass:
  `pytest services/api/tests -q`
- [ ] Re-run `C:\Users\Administrator\Downloads\test.xlsx` through the batch CLI.
- [ ] List generated SVG/PNG/DXF outputs for CAD validation.

