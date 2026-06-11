# Experimental DXF Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an experimental backend DXF exporter that converts text and SVG layers to normalized path geometry and writes valid DXF with `ezdxf`.

**Architecture:** FastAPI owns DXF export because DXF needs deterministic font, SVG, geometry, and file-generation logic. The renderer keeps SVG/PNG export for now; DXF is exposed through an API endpoint and domain service under `services/api/app/domain/exports`.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, fontTools, ezdxf, pytest.

---

### Task 1: Contract And Tests

**Files:**
- Create: `services/api/tests/test_dxf_export.py`

- [ ] Write tests for simple text export converting glyphs to DXF path entities.
- [ ] Write tests for simple inline SVG export converting SVG paths to DXF path entities.
- [ ] Write tests for a grouped template with text and SVG, verifying transform normalization and units.
- [ ] Write tests for unsupported SVG features returning warnings.
- [ ] Write tests for fatal unsupported layers returning structured errors instead of a misleading DXF file.
- [ ] Run the new tests and confirm they fail because the DXF endpoint/service does not exist yet.

### Task 2: DXF Domain Service

**Files:**
- Create: `services/api/app/domain/exports/__init__.py`
- Create: `services/api/app/domain/exports/dxf.py`

- [ ] Validate the layer document schema and export settings.
- [ ] Resolve exportable layers recursively and reject editor-only helper layers.
- [ ] Convert text to glyph outlines with `fontTools`; use deterministic fallback font discovery only with warnings.
- [ ] Parse inline SVG and safe asset SVG files into supported path geometry.
- [ ] Normalize layer and SVG transforms into absolute coordinates.
- [ ] Generate DXF through `ezdxf`, set `$INSUNITS`, write metadata, and fail if no geometry is produced.
- [ ] Return warnings for unsupported recoverable SVG features, and raise `DomainError` for unsupported fatal export input.

### Task 3: API Schema And Route

**Files:**
- Create: `services/api/app/schemas/exports.py`
- Modify: `services/api/app/main.py`

- [ ] Add a `POST /exports/dxf` endpoint accepting a layer document and optional unit override.
- [ ] Return file name, base64 DXF bytes, metadata, and warnings.
- [ ] Map `DomainError` to the existing structured error envelope.

### Task 4: Dependencies And Documentation

**Files:**
- Modify: `services/api/pyproject.toml`
- Create: `docs/DXF_EXPORT.md`

- [ ] Add `ezdxf>=1.3` to the API package dependency list.
- [ ] Document the experimental DXF scope, supported SVG subset, text-to-path behavior, units, transform normalization, warnings, and fatal errors.

### Task 5: Verification

**Commands:**
- `node ../../tools/python.mjs -m pytest tests/test_dxf_export.py -q` from `services/api`
- `node ../../tools/python.mjs -m pytest tests -q` from `services/api`
- `node ../../tools/python.mjs -m ruff check .` from `services/api`

- [ ] Install missing local dependencies only if tests fail due to missing declared dependencies.
- [ ] Fix implementation or tests until DXF tests pass.
- [ ] Report changed files, test results, and known limitations.
