# Export Pipeline

## Goal

PNG and SVG export are generated from the same `LayerDocument` JSON used by the
renderer preview. Fabric.js remains an editor runtime only; selection boxes,
controls, guides, viewport state, and debug overlays are never used as export
input.

## Source Of Truth

The export entry points live in
`apps/desktop/src/renderer/export/exportPipeline.ts`.

Inputs:

- `LayerDocument`
- export background: `canvas` or `transparent`
- PNG scale
- generated `exportedAt` timestamp

Outputs:

- SVG string download
- PNG data URL download
- metadata embedded in the exported file

The pipeline validates the document with `validateLayerDocument` before
exporting. Invalid layer JSON fails loudly.

## SVG Export

SVG export builds a fresh SVG scene from exportable document layers sorted by
`zIndex`.

Layer handling:

- `text`: exported as SVG `<text>` and `<tspan>` elements.
- `svg`: inline SVG is embedded as nested SVG markup, preserving paths and other
  vector children where possible.
- `path`: exported as SVG `<path>`.
- `image`: exported as SVG `<image>` with the original asset reference.
- `group`: exported recursively.

Background handling:

- `canvas`: emits a background `<rect>` when the document canvas background is
  solid.
- `transparent`: omits the background rectangle.

Metadata:

```json
{
  "templateId": "birth-flower-card",
  "orderId": "order_1",
  "exportedAt": "2026-06-11T13:14:15.000Z",
  "appVersion": "0.1.0"
}
```

The metadata is written into the SVG `<metadata id="flower-export-metadata">`
node.

## PNG Export

PNG export first creates the SVG export from the same `LayerDocument`, then
rasterizes that SVG into a canvas at the requested scale.

The output pixel size is:

```text
width = document.canvas.width * scale
height = document.canvas.height * scale
```

The PNG background follows the same background option used by the SVG source:

- `canvas`: the SVG includes the canvas background before rasterization.
- `transparent`: the SVG omits the background and the canvas remains
  transparent.

After rasterization, the pipeline injects an uncompressed PNG `iTXt` chunk named
`flower-export-metadata` with the same metadata JSON used by SVG export.

## Editor-State Exclusion

The exporter never reads live Fabric canvas objects. It only reads
`LayerDocument`.

As a second guard, layers with helper markers are filtered even if they were
accidentally marked `exportable: true`:

- `selection`
- `selection-box`
- `selection-handle`
- `guide`
- `guides`
- `handle`
- `handles`
- `debug`
- `debug-bounds`
- `editor-overlay`
- `snap-line`
- `snap-lines`

## Regression Tests

Coverage lives in
`apps/desktop/src/renderer/export/exportPipeline.test.ts`.

The tests verify:

- SVG metadata fields.
- SVG vector and text preservation.
- transparent background behavior.
- PNG scale dimensions.
- PNG embedded metadata.
- exclusion of selection/debug helper layers.

## Current Limits

- External SVG asset references are emitted as `<image href="...">`; only inline
  SVG is embedded as editable vector markup in this front-end pipeline.
- Browser canvas rasterization can fail if an external image asset taints the
  canvas. Production file-backed export should eventually move asset resolution
  into the FastAPI export service.
- DXF remains out of this pipeline and should use path-only geometry in a later
  export service.
