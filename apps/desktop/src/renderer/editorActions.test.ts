import { describe, expect, it } from "vitest";

import {
  EXPORT_SETTINGS_SCHEMA_VERSION,
  LAYER_DOCUMENT_SCHEMA_VERSION,
  type LayerDocument,
  validateLayerDocument,
} from "@flower/design-core";
import {
  addImageAssetLayer,
  addSvgAssetLayer,
  addTextLayer,
} from "./editorActions";

const UPDATED_AT = "2026-06-12T12:00:00.000Z";

describe("editor actions", () => {
  it("adds a centered editable text layer above existing layers", () => {
    const result = addTextLayer(createDocument(), {
      id: "layer_text_added",
      now: UPDATED_AT,
      text: "New text",
    });

    expect(result.layerId).toBe("layer_text_added");
    expect(result.document.metadata.updatedAt).toBe(UPDATED_AT);
    expect(result.document.layers.at(-1)).toMatchObject({
      id: "layer_text_added",
      type: "text",
      name: "Text layer",
      text: "New text",
      x: 275,
      y: 360,
      width: 450,
      height: 80,
      zIndex: 3,
    });
    expect(validateLayerDocument(result.document)).toEqual({ ok: true, errors: [] });
  });

  it("adds an imported SVG asset layer with parsed viewBox geometry", () => {
    const result = addSvgAssetLayer(createDocument(), {
      id: "layer_svg_added",
      name: "Cherry.svg",
      now: UPDATED_AT,
      svgText: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 20"><path d="M0 0h10v20z"/></svg>',
    });

    expect(result.layerId).toBe("layer_svg_added");
    expect(result.document.layers.at(-1)).toMatchObject({
      id: "layer_svg_added",
      type: "svg",
      name: "Cherry",
      x: 430,
      y: 260,
      width: 140,
      height: 280,
      zIndex: 3,
      viewBox: { x: 0, y: 0, width: 10, height: 20 },
      preserveVector: true,
    });
    expect(validateLayerDocument(result.document).ok).toBe(true);
  });

  it("adds an imported raster asset layer using intrinsic image dimensions", () => {
    const result = addImageAssetLayer(createDocument(), {
      dataUrl: "data:image/png;base64,AAAA",
      height: 600,
      id: "layer_image_added",
      name: "photo.png",
      now: UPDATED_AT,
      width: 1200,
    });

    expect(result.layerId).toBe("layer_image_added");
    expect(result.document.layers.at(-1)).toMatchObject({
      id: "layer_image_added",
      type: "image",
      name: "photo",
      x: 360,
      y: 330,
      width: 280,
      height: 140,
      zIndex: 3,
      assetRef: {
        assetId: "imported-photo",
        path: "data:image/png;base64,AAAA",
      },
      intrinsicSize: {
        width: 1200,
        height: 600,
      },
    });
    expect(validateLayerDocument(result.document).ok).toBe(true);
  });

  it("keeps imported asset layers inside very small canvases", () => {
    const document = {
      ...createDocument(),
      canvas: {
        ...createDocument().canvas,
        width: 100,
        height: 80,
      },
    };

    const result = addImageAssetLayer(document, {
      dataUrl: "data:image/png;base64,AAAA",
      height: 600,
      id: "layer_image_added",
      name: "photo.png",
      now: UPDATED_AT,
      width: 600,
    });

    expect(result.document.layers.at(-1)).toMatchObject({
      x: 10,
      y: 0,
      width: 80,
      height: 80,
    });
    expect(validateLayerDocument(result.document).ok).toBe(true);
  });
});

function createDocument(): LayerDocument {
  return {
    schemaVersion: LAYER_DOCUMENT_SCHEMA_VERSION,
    documentId: "doc_editor",
    projectId: "project_1",
    jobId: "job_1",
    metadata: {
      orderId: "order_1",
      templateId: "birth-flower-card",
      templateVersion: "1.0.0",
      appVersion: "0.1.0",
      createdAt: "2026-06-11T00:00:00.000Z",
      updatedAt: "2026-06-11T00:00:00.000Z",
    },
    canvas: {
      width: 1000,
      height: 800,
      unit: "px",
      background: { type: "solid", color: "#ffffff" },
    },
    exportSettings: {
      schemaVersion: EXPORT_SETTINGS_SCHEMA_VERSION,
      defaultFormats: ["svg", "png", "dxf"],
      svg: {
        preserveText: true,
        preserveVector: true,
        includeMetadata: true,
      },
      png: {
        scale: 1,
        background: "canvas",
      },
      dxf: {
        textMode: "paths",
        units: "px",
      },
    },
    layers: [
      {
        id: "layer_flower",
        type: "svg",
        name: "Birth flower",
        visible: true,
        locked: false,
        exportable: true,
        zIndex: 1,
        opacity: 1,
        x: 120,
        y: 80,
        width: 200,
        height: 260,
        scaleX: 1,
        scaleY: 1,
        rotation: 0,
        tags: ["flower"],
        inlineSvg: "<svg viewBox=\"0 0 10 10\"><path d=\"M0 0h10v10z\" /></svg>",
        viewBox: {
          x: 0,
          y: 0,
          width: 10,
          height: 10,
        },
        preserveVector: true,
      },
      {
        id: "layer_customer_name",
        type: "text",
        name: "Customer name",
        visible: true,
        locked: false,
        exportable: true,
        zIndex: 2,
        opacity: 1,
        x: 300,
        y: 640,
        width: 400,
        height: 80,
        scaleX: 1,
        scaleY: 1,
        rotation: 0,
        tags: ["customer-text"],
        text: "Avery",
        fontRef: {
          family: "Georgia",
          source: "system",
          fallbackFamilies: ["serif"],
        },
        style: {
          fontSize: 64,
          fill: "#26352f",
          align: "center",
          lineHeight: 1.1,
          letterSpacing: 0,
        },
        layout: {
          mode: "box",
          overflow: "shrink-to-fit",
        },
      },
    ],
  };
}
