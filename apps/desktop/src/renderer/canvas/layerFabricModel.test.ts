import { describe, expect, it } from "vitest";

import {
  EXPORT_SETTINGS_SCHEMA_VERSION,
  LAYER_DOCUMENT_SCHEMA_VERSION,
  type LayerDocument,
  validateLayerDocument,
} from "@flower/design-core";

import {
  applyGlyphOverrideToTextLayer,
  buildTextWithGlyphOverrides,
  createLayerObjectSnapshot,
  isSupportedEditorLayer,
  listLayersForDisplay,
  serializeLayerDocumentFromSnapshots,
  updateLayerProperty,
} from "./layerFabricModel";

describe("layer Fabric model conversion", () => {
  it("creates editable runtime snapshots for text, image, and SVG layers", () => {
    const document = createDocument();

    const snapshots = document.layers.filter(isSupportedEditorLayer).map(createLayerObjectSnapshot);

    expect(snapshots).toEqual([
      expect.objectContaining({
        fabricType: "text",
        layerId: "text_1",
        left: 20,
        top: 30,
        angle: 5,
        selectable: true,
        visible: true,
        text: "Avery",
        fontFamily: "Birthmonth",
        fontSize: 48,
      }),
      expect.objectContaining({
        fabricType: "image",
        layerId: "image_1",
        source: "assets/samples/photo.png",
        selectable: false,
        evented: false,
      }),
      expect.objectContaining({
        fabricType: "svg",
        layerId: "svg_1",
        source: "<svg viewBox=\"0 0 10 10\"><path d=\"M0 0h10v10z\" /></svg>",
        preserveVector: true,
      }),
    ]);
  });

  it("serializes Fabric geometry edits back to valid layer JSON without UI state", () => {
    const document = createDocument();
    const snapshots = document.layers.filter(isSupportedEditorLayer).map(createLayerObjectSnapshot);
    const changedText = {
      ...snapshots[0],
      left: 111,
      top: 222,
      scaleX: 1.75,
      scaleY: 1.75,
      angle: 33,
      opacity: 0.4,
      visible: false,
      locked: true,
      selectable: false,
      evented: false,
      runtimeOnly: {
        selection: { active: true },
        controls: ["tl", "br"],
      },
    };

    const saved = serializeLayerDocumentFromSnapshots(document, [changedText], {
      updatedAt: "2026-06-11T12:00:00.000Z",
    });

    expect(saved.layers[0]).toMatchObject({
      id: "text_1",
      x: 111,
      y: 222,
      scaleX: 1.75,
      scaleY: 1.75,
      rotation: 33,
      opacity: 0.4,
      visible: false,
      locked: true,
    });
    expect(JSON.stringify(saved)).not.toContain("runtimeOnly");
    expect(JSON.stringify(saved)).not.toContain("selection");
    expect(validateLayerDocument(saved)).toEqual({ ok: true, errors: [] });
  });

  it("updates layer properties used by the property panel", () => {
    const document = createDocument();

    const next = updateLayerProperty(document, "image_1", {
      x: 15,
      y: 25,
      scale: 0.8,
      rotation: 12,
      opacity: 0.5,
      visible: false,
      locked: true,
    });

    expect(next.layers[1]).toMatchObject({
      x: 15,
      y: 25,
      scaleX: 0.8,
      scaleY: 0.8,
      rotation: 12,
      opacity: 0.5,
      visible: false,
      locked: true,
    });
    expect(validateLayerDocument(next).ok).toBe(true);
  });

  it("saves glyph replacements as text layer glyphOverrides without changing original text", () => {
    const document = createDocument();

    const next = applyGlyphOverrideToTextLayer(document, "text_1", {
      index: 4,
      replacement: "\ue123",
      codepoint: "U+E123",
      glyphName: "y.swash",
    });

    const layer = next.layers[0];
    expect(layer).toMatchObject({
      type: "text",
      text: "Avery",
      glyphOverrides: [
        {
          index: 4,
          originalText: "y",
          replacement: "\ue123",
          codepoint: "U+E123",
          glyphName: "y.swash",
        },
      ],
    });
    expect(validateLayerDocument(next).ok).toBe(true);
  });

  it("builds render text from glyphOverrides and ignores stale positions", () => {
    const document = applyGlyphOverrideToTextLayer(createDocument(), "text_1", {
      index: 4,
      replacement: "\ue123",
      codepoint: "U+E123",
      glyphName: "y.swash",
    });
    const layer = document.layers[0];

    expect(layer.type === "text" ? buildTextWithGlyphOverrides(layer) : "").toBe("Aver\ue123");

    const staleLayer = {
      ...(layer as Extract<typeof layer, { type: "text" }>),
      text: "Averi",
    };
    expect(buildTextWithGlyphOverrides(staleLayer)).toBe("Averi");
  });

  it("lists layers by visual stacking order for the layer panel", () => {
    const document = createDocument();

    expect(listLayersForDisplay(document.layers).map((layer) => layer.id)).toEqual([
      "svg_1",
      "image_1",
      "text_1",
    ]);
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
      width: 800,
      height: 600,
      unit: "px",
      background: { type: "solid", color: "#ffffff" },
    },
    exportSettings: {
      schemaVersion: EXPORT_SETTINGS_SCHEMA_VERSION,
      defaultFormats: ["svg", "png"],
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
        id: "text_1",
        type: "text",
        name: "Customer name",
        visible: true,
        locked: false,
        exportable: true,
        zIndex: 1,
        opacity: 1,
        x: 20,
        y: 30,
        width: 220,
        height: 80,
        scaleX: 1,
        scaleY: 1,
        rotation: 5,
        tags: ["customer-text"],
        text: "Avery",
        fontRef: {
          family: "Birthmonth",
          source: "asset",
          assetId: "font_birthmonth",
        },
        style: {
          fontSize: 48,
          fill: "#223344",
          align: "center",
          lineHeight: 1.1,
          letterSpacing: 0,
        },
        layout: {
          mode: "box",
          overflow: "shrink-to-fit",
        },
      },
      {
        id: "image_1",
        type: "image",
        name: "Product photo",
        visible: true,
        locked: true,
        exportable: true,
        zIndex: 2,
        opacity: 0.9,
        x: 250,
        y: 120,
        width: 180,
        height: 180,
        scaleX: 1,
        scaleY: 1,
        rotation: 0,
        tags: ["asset"],
        assetRef: {
          assetId: "asset_photo",
          path: "assets/samples/photo.png",
        },
        intrinsicSize: {
          width: 1200,
          height: 1200,
        },
        fit: "contain",
      },
      {
        id: "svg_1",
        type: "svg",
        name: "Birth flower",
        visible: true,
        locked: false,
        exportable: true,
        zIndex: 3,
        opacity: 1,
        x: 470,
        y: 80,
        width: 140,
        height: 220,
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
    ],
  };
}
