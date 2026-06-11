# Fabric Canvas Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable Fabric.js layer editor in the Electron React renderer without implementing export.

**Architecture:** Keep saved design state in `LayerDocument`. Keep Fabric runtime details in `apps/desktop/src/renderer/canvas`. Convert document layers into Fabric objects for editing, then serialize only project layer fields back into JSON.

**Tech Stack:** React, TypeScript, Fabric.js, Vitest, `@flower/design-core`.

---

### Task 1: Conversion Tests And Model

**Files:**
- Create: `apps/desktop/src/renderer/canvas/layerFabricModel.test.ts`
- Create: `apps/desktop/src/renderer/canvas/layerFabricModel.ts`

- [ ] Write failing tests for text, image, and SVG layer runtime snapshots.
- [ ] Write failing tests for geometry serialization back into `LayerDocument`.
- [ ] Implement pure conversion helpers without importing Fabric so tests run in Node.
- [ ] Validate saved documents with `validateLayerDocument`.

### Task 2: Fabric Host

**Files:**
- Create: `apps/desktop/src/renderer/canvas/FabricCanvas.tsx`
- Modify: `apps/desktop/package.json`
- Modify: `package-lock.json`

- [ ] Add `fabric` as the only new production dependency because the requested editor depends on Fabric.js interaction primitives.
- [ ] Hydrate text layers as editable Fabric text objects.
- [ ] Hydrate image layers from `assetRef.path`.
- [ ] Hydrate SVG layers from `inlineSvg` or `assetRef.path`.
- [ ] Enable Fabric selection, move, scale, rotate, and lock handling.
- [ ] Emit updated layer snapshots after object modifications.
- [ ] Store layer id/type metadata on Fabric objects only as runtime data.

### Task 3: Editor Shell

**Files:**
- Modify: `apps/desktop/src/renderer/App.tsx`
- Modify: `apps/desktop/src/renderer/styles.css`

- [ ] Add sample editable `LayerDocument` state.
- [ ] Add layer list sorted by z-index.
- [ ] Add property panel controls for `x`, `y`, uniform `scale`, `rotation`, `opacity`, `visible`, and `locked`.
- [ ] Add save-to-JSON panel that serializes the document and validates it.

### Task 4: Documentation

**Files:**
- Modify: `docs/LAYER_MODEL.md`

- [ ] Document Fabric hydration rules.
- [ ] Document serialization rules.
- [ ] Document why selection boxes, handles, guides, and viewport state stay out of `LayerDocument`.

### Task 5: Verification

**Commands:**
- `npm --workspace @flower/desktop run test`
- `npm --workspace @flower/desktop run lint`
- `npm --workspace @flower/desktop run build`
- `npm --workspace @flower/design-core run test`
