# Fabric Layer Mapping

## Boundary

Fabric.js objects are editor runtime objects. They are not the saved model.
The saved model remains `LayerDocument` from `packages/design-core`.

Selection boxes, control handles, active object state, viewport state, guides,
hover state, snap lines, and load errors are UI/session state only. They must
never be written into `LayerDocument`.

## Hydration

The renderer hydrates supported layers in `apps/desktop/src/renderer/canvas`.

- Text layer -> Fabric `Textbox`.
  - `text` maps to the editable Fabric text content.
  - `fontRef.family` maps to `fontFamily`.
  - `style.fontSize`, `style.fill`, `style.stroke`, `style.strokeWidth`,
    `style.align`, `style.lineHeight`, and `style.letterSpacing` map to Fabric
    text style properties.
- Image layer -> Fabric `FabricImage`.
  - `assetRef.path` is loaded at runtime.
  - Binary image data is not embedded into the layer JSON.
- SVG layer -> grouped Fabric vector objects.
  - `inlineSvg` is parsed directly.
  - Otherwise `assetRef.path` is loaded at runtime.
  - `preserveVector: true` remains in JSON; the editor does not convert SVG
    layers into image layers while editing.

Common geometry mapping:

| Layer JSON | Fabric runtime |
| --- | --- |
| `x` | `left` |
| `y` | `top` |
| `rotation` | `angle` |
| `opacity` | `opacity` |
| `visible` | `visible` |
| `locked` | `selectable/evented/lock*` |

Image and SVG objects may need a runtime fit scale because Fabric measures them
from their intrinsic bounds. That fit scale is stored only on the Fabric object.
The JSON `scaleX` and `scaleY` remain the user-facing model scale.

## Serialization

Saving reads only these editable fields from Fabric objects:

- `x`
- `y`
- `scaleX`
- `scaleY`
- `rotation`
- `opacity`
- `visible`
- `locked`

Layer-specific source fields such as `text`, `assetRef`, `inlineSvg`, `viewBox`,
and `preserveVector` remain owned by the layer JSON. Runtime-only Fabric
metadata is discarded.

After serialization, the renderer validates the result with
`validateLayerDocument`. Invalid saved JSON must fail loudly instead of being
accepted silently.

## Current Scope

The first Fabric editor supports text, image, and SVG layers. Export is
intentionally out of scope.
