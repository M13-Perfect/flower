# DXF Export

## Status

DXF export is experimental and lives in the FastAPI backend, not in the
renderer SVG/PNG export pipeline.

Entry point:

- `POST /exports/dxf`
- Domain service: `services/api/app/domain/exports/dxf.py`

DXF is treated as an engineering path format. The exporter never writes SVG
markup, browser text, images, selection boxes, guides, handles, or debug layers
into the DXF file.

## Request

```json
{
  "document": {
    "schemaVersion": "1.0",
    "canvas": {
      "unit": "px"
    },
    "exportSettings": {
      "dxf": {
        "textMode": "paths",
        "units": "px"
      }
    },
    "layers": []
  },
  "units": "mm",
  "exportedAt": "2026-06-11T13:14:15.000Z"
}
```

`units` is optional. If omitted, the exporter uses
`document.exportSettings.dxf.units`, then falls back to `document.canvas.unit`.

Supported unit labels:

- `px`: written as DXF unitless (`$INSUNITS = 0`)
- `in`: inches (`$INSUNITS = 1`)
- `mm`: millimeters (`$INSUNITS = 4`)

The exporter converts between `mm` and `in`. Pixel coordinates have no physical
scale; when converting between `px` and a physical unit, coordinates are left
unchanged and a `UNIT_SCALE_ASSUMED` warning is returned.

## Response

```json
{
  "fileName": "birth-flower-card_order-1_2026-06-11T13-14-15-000Z.dxf",
  "mimeType": "application/dxf",
  "contentBase64": "...",
  "metadata": {
    "templateId": "birth-flower-card",
    "orderId": "order-1",
    "exportedAt": "2026-06-11T13:14:15.000Z",
    "appVersion": "0.1.0"
  },
  "warnings": []
}
```

Fatal errors use the shared API error envelope and do not return
`contentBase64`.

## Text Handling

Text is always converted to paths before DXF generation.

Process:

1. Resolve a local font from `fontRef.assetId` or `fontRef.family`.
2. Apply `glyphOverrides`.
3. Read glyph outlines with `fontTools`.
4. Convert glyph outlines to path points.
5. Apply text layer transform and parent group transforms.
6. Write path geometry through `ezdxf`.

If a required glyph is missing, export fails with `GLYPH_MISSING`. The exporter
does not silently substitute a different visible character.

## SVG Handling

SVG layers must become path geometry.

Supported experimental subset:

- Inline SVG in `inlineSvg`.
- Asset SVG through safe relative `assetRef.path`.
- `<svg>`, `<g>`, and `<path>`.
- Path commands: `M`, `L`, `H`, `V`, `C`, `Q`, `Z`, including relative forms.
- SVG transforms: `translate`, `scale`, `rotate`, and `matrix`.

Unsupported recoverable features return `SVG_UNSUPPORTED_FEATURE` warnings and
are ignored when other path geometry can still be exported. Examples:

- gradients and paint servers
- `defs`
- `clipPath`
- `mask`
- `filter`
- `pattern`
- `image`
- `text`
- `use`
- `style`

If an SVG produces no usable path geometry, export fails with
`DXF_NO_GEOMETRY`.

## Transform Normalization

The exporter flattens transforms into absolute coordinates before writing DXF:

1. Unit conversion matrix.
2. Parent group transforms.
3. Layer `x`, `y`, `rotation`, `scaleX`, `scaleY`.
4. SVG viewBox-to-layer scaling.
5. SVG element transforms.
6. Path or glyph local coordinates.

DXF output receives geometry in final model coordinates. It does not depend on
viewer-side SVG transforms.

## Unsupported Layers

DXF accepts path-like geometry only.

Supported layer types:

- `text`: converted to glyph paths.
- `svg`: parsed into path geometry.
- `path`: parsed from SVG path data.
- `group`: recursively exports supported children.

Unsupported layer types, including `image`, fail with
`EXPORT_UNSUPPORTED_LAYER`. This is intentional: raster images cannot be
truthfully represented as DXF engineering paths.

## Failure Policy

The exporter must not silently generate a bad file.

Fatal examples:

- invalid layer document
- unsupported schema version
- unsupported layer type
- missing SVG asset
- SVG parse failure
- missing font
- missing glyph
- no generated geometry
- missing `ezdxf`

Recoverable examples:

- ignored SVG gradient or `defs`
- ignored unsupported SVG transform
- pixel-to-physical unit scale assumption
- fallback to a discovered local font when the requested font is absent

## Dependency

DXF writing uses `ezdxf`. Text outline extraction uses `fontTools`.

The API package declares:

```toml
dependencies = [
  "fonttools>=4.0",
  "ezdxf>=1.3"
]
```
