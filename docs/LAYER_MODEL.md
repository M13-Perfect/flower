# Layer Model

## 核心原则

图层 JSON 是整个项目的单一事实来源。React UI 状态、Fabric.js 运行时对象、选中框、缩放、吸附线、调试框、右键菜单状态都不能写入导出模型。

模型目标：

- 保留可编辑性：文本保存为文本和字体引用，SVG 保存为矢量来源，图片保存为资产引用。
- 导出可复现：导出设置保存在文档中，但导出过程不能修改原始文档。
- 运行时可校验：加载、保存、导出前都必须调用 `validateLayerDocument`。

## Document

顶层结构：

```json
{
  "schemaVersion": "1.0",
  "documentId": "doc_001",
  "projectId": "project_001",
  "jobId": "job_001",
  "metadata": {
    "orderId": "order_001",
    "templateId": "birth-flower-card",
    "templateVersion": "1.0.0",
    "appVersion": "0.1.0",
    "createdAt": "2026-06-11T00:00:00.000Z",
    "updatedAt": "2026-06-11T00:00:00.000Z"
  },
  "canvas": {},
  "exportSettings": {},
  "layers": []
}
```

禁止字段：

- `editorState`
- `selectedLayerIds`
- `selection`
- `activeTool`
- `zoom`
- `pan`
- `viewport`
- `guides`
- `handles`
- `debugBounds`

这些字段只能存在于 renderer session state。

## Canvas

```json
{
  "width": 3000,
  "height": 3000,
  "unit": "px",
  "background": {
    "type": "solid",
    "color": "#ffffff"
  }
}
```

规则：

- `width` 和 `height` 必须是正数。
- `unit` 支持 `px`、`mm`、`in`。
- `background.type` 支持 `solid` 或 `transparent`。

## Common Layer Fields

所有图层都直接包含以下通用属性，不使用嵌套 `transform`：

```json
{
  "id": "layer_001",
  "type": "text",
  "name": "Customer name",
  "x": 200,
  "y": 220,
  "width": 1200,
  "height": 260,
  "scaleX": 1,
  "scaleY": 1,
  "rotation": 0,
  "opacity": 1,
  "visible": true,
  "locked": false,
  "exportable": true,
  "zIndex": 1,
  "slotId": "customer_name",
  "tags": ["customer-text"]
}
```

规则：

- `x`、`y`、`rotation` 必须是有限数字。
- `width`、`height`、`scaleX`、`scaleY` 必须是正数。
- `opacity` 范围是 `0` 到 `1`。
- 导出模型中的 layer 必须是 `exportable: true`。选区、控制点、辅助线等 UI overlay 不允许作为 layer 写入。

## Text Layer

```json
{
  "id": "layer_text",
  "type": "text",
  "name": "Customer name",
  "x": 200,
  "y": 220,
  "width": 1200,
  "height": 260,
  "scaleX": 1,
  "scaleY": 1,
  "rotation": 0,
  "opacity": 1,
  "visible": true,
  "locked": false,
  "exportable": true,
  "zIndex": 1,
  "tags": ["customer-text"],
  "text": "Avery",
  "fontRef": {
    "family": "Birthmonth",
    "source": "asset",
    "assetId": "font_birthmonth",
    "fallbackFamilies": ["serif"]
  },
  "style": {
    "fontSize": 180,
    "fill": "#1f2933",
    "stroke": "#ffffff",
    "strokeWidth": 0,
    "align": "center",
    "lineHeight": 1.1,
    "letterSpacing": 0
  },
  "layout": {
    "mode": "box",
    "overflow": "shrink-to-fit"
  },
  "glyphOverrides": [
    {
      "index": 4,
      "originalText": "y",
      "replacement": "U+E080",
      "codepoint": "U+E080",
      "glyphName": "y.005"
    }
  ]
}
```

`glyphOverrides` 用于记录特殊字形替换。它不改变原始 `text`，所以文本仍然可编辑，导出时再按 override 应用字形替换。

## Image Layer

```json
{
  "id": "layer_image",
  "type": "image",
  "name": "Product photo",
  "x": 100,
  "y": 900,
  "width": 800,
  "height": 800,
  "scaleX": 1,
  "scaleY": 1,
  "rotation": 0,
  "opacity": 1,
  "visible": true,
  "locked": false,
  "exportable": true,
  "zIndex": 2,
  "tags": ["asset"],
  "assetRef": {
    "assetId": "asset_photo",
    "path": "assets/samples/photo.png",
    "checksum": "sha256:photo"
  },
  "intrinsicSize": {
    "width": 1200,
    "height": 1200
  },
  "fit": "contain"
}
```

图片层保存资产引用和原始尺寸，不把图片数据直接塞入图层 JSON。

## SVG Layer

```json
{
  "id": "layer_svg",
  "type": "svg",
  "name": "Birth flower",
  "x": 1500,
  "y": 600,
  "width": 900,
  "height": 1200,
  "scaleX": 1,
  "scaleY": 1,
  "rotation": 0,
  "opacity": 1,
  "visible": true,
  "locked": false,
  "exportable": true,
  "zIndex": 3,
  "tags": ["flower"],
  "assetRef": {
    "assetId": "asset_flower",
    "path": "assets/flowers/june-rose.svg",
    "checksum": "sha256:flower"
  },
  "viewBox": {
    "x": 0,
    "y": 0,
    "width": 512,
    "height": 512
  },
  "preserveVector": true
}
```

SVG 层默认保留矢量来源。编辑阶段不得把 SVG 栅格化为图片层。

## Export Settings

```json
{
  "schemaVersion": "1.0",
  "defaultFormats": ["svg", "png", "dxf"],
  "svg": {
    "preserveText": true,
    "preserveVector": true,
    "includeMetadata": true
  },
  "png": {
    "scale": 1,
    "background": "canvas"
  },
  "dxf": {
    "textMode": "paths",
    "units": "px"
  }
}
```

导出规则：

- SVG 尽量保留文本和矢量。
- PNG 从导出场景渲染，不从 Fabric viewport 截图。
- DXF 只接受路径类几何；文本导出为路径。

## Runtime Validation

`packages/design-core` 暴露：

- `validateLayerDocument(value)`
- `isLayerDocument(value)`
- `isTemplateDocument(value)`
- `createEmptyLayerDocument(input)`
- `createDefaultExportSettings()`

`validateLayerDocument` 返回：

```json
{
  "ok": false,
  "errors": ["document.canvas.width must be a positive number"]
}
```

保存、导入、导出前都要用该函数校验。
