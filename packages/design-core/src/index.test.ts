import { describe, expect, it } from "vitest";

import {
  EXPORT_SETTINGS_SCHEMA_VERSION,
  LAYER_DOCUMENT_SCHEMA_VERSION,
  TEMPLATE_SCHEMA_VERSION,
  createEmptyLayerDocument,
  isLayerDocument,
  isTemplateDocument,
  validateLayerDocument,
} from "./index";

describe("design-core schemas", () => {
  it("creates an empty layer document with the current schema version", () => {
    const document = createEmptyLayerDocument({
      documentId: "doc_1",
      projectId: "project_1",
      jobId: "job_1",
      templateId: "template_1",
      width: 1000,
      height: 800,
    });

    expect(document.schemaVersion).toBe(LAYER_DOCUMENT_SCHEMA_VERSION);
    expect(document.canvas).toMatchObject({
      width: 1000,
      height: 800,
      unit: "px",
      background: { type: "solid", color: "#ffffff" },
    });
    expect(document.exportSettings.schemaVersion).toBe(EXPORT_SETTINGS_SCHEMA_VERSION);
    expect(document.layers).toEqual([]);
    expect(isLayerDocument(document)).toBe(true);
  });

  it("validates an editable document with text, image, and svg layers", () => {
    const document = createValidDocument();

    const result = validateLayerDocument(document);

    expect(result.ok).toBe(true);
    expect(isLayerDocument(document)).toBe(true);
  });

  it("rejects UI-only state in an exportable document", () => {
    const document = {
      ...createValidDocument(),
      editorState: {
        selectedLayerIds: ["layer_text"],
        zoom: 1.25,
      },
    };

    const result = validateLayerDocument(document);

    expect(result.ok).toBe(false);
    expect(result.errors).toContain("document.editorState is UI-only state");
    expect(isLayerDocument(document)).toBe(false);
  });

  it("rejects invalid layer payloads", () => {
    const document = createValidDocument() as any;
    document.layers[0] = {
      ...document.layers[0],
      text: "",
      fontRef: {
        family: "",
      },
    };

    const result = validateLayerDocument(document);

    expect(result.ok).toBe(false);
    expect(result.errors).toContain("layers[0].text must not be empty");
    expect(result.errors).toContain("layers[0].fontRef.family must not be empty");
  });

  it("accepts valid parsed JSON", () => {
    const parsed = JSON.parse(JSON.stringify(createValidDocument()));

    expect(validateLayerDocument(parsed).ok).toBe(true);
  });

  it("rejects invalid parsed JSON", () => {
    const parsed = JSON.parse(
      JSON.stringify({
        ...createValidDocument(),
        canvas: {
          width: 0,
          height: 3000,
          unit: "px",
          background: { type: "solid", color: "#ffffff" },
        },
      }),
    );

    const result = validateLayerDocument(parsed);

    expect(result.ok).toBe(false);
    expect(result.errors).toContain("document.canvas.width must be a positive number");
  });

  it("rejects old nested transform JSON", () => {
    const document = createValidDocument() as any;
    document.layers[0] = {
      ...document.layers[0],
      x: undefined,
      y: undefined,
      width: undefined,
      height: undefined,
      scaleX: undefined,
      scaleY: undefined,
      rotation: undefined,
      transform: {
        x: 200,
        y: 220,
        width: 1200,
        height: 260,
        rotation: 0,
        scaleX: 1,
        scaleY: 1,
      },
    };

    const result = validateLayerDocument(JSON.parse(JSON.stringify(document)));

    expect(result.ok).toBe(false);
    expect(result.errors).toContain("layers[0].x must be a finite number");
    expect(result.errors).toContain("layers[0].width must be a positive number");
  });

  it("rejects non-exportable editor overlay layers", () => {
    const document = createValidDocument() as any;
    document.layers.push({
      id: "layer_overlay",
      type: "text",
      name: "Selection outline",
      visible: true,
      locked: true,
      exportable: false,
      zIndex: 99,
      opacity: 1,
      x: 0,
      y: 0,
      width: 100,
      height: 100,
      rotation: 0,
      scaleX: 1,
      scaleY: 1,
      tags: ["editor-overlay"],
      text: "debug",
      fontRef: {
        family: "Inter",
      },
      style: {
        fontSize: 12,
        fill: "#ff0000",
        align: "left",
        lineHeight: 1,
        letterSpacing: 0,
      },
      layout: {
        mode: "box",
        overflow: "clip",
      },
    });

    const result = validateLayerDocument(document);

    expect(result.ok).toBe(false);
    expect(result.errors).toContain("layers[3] must be exportable document state");
  });

  it("accepts the minimal template document shape", () => {
    expect(
      isTemplateDocument({
        schemaVersion: TEMPLATE_SCHEMA_VERSION,
        templateId: "template_1",
        version: "1.0.0",
        productType: "birth-flower",
        displayName: "Birth flower",
        canvas: {
          width: 1000,
          height: 800,
          unit: "px",
          background: { type: "solid", color: "#ffffff" },
        },
        slots: [],
      }),
    ).toBe(true);
  });
});

function createValidDocument() {
  return {
    schemaVersion: LAYER_DOCUMENT_SCHEMA_VERSION,
    documentId: "doc_valid",
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
      width: 3000,
      height: 3000,
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
        id: "layer_text",
        type: "text",
        name: "Customer name",
      visible: true,
      locked: false,
      exportable: true,
      zIndex: 1,
      opacity: 1,
      x: 200,
      y: 220,
      width: 1200,
      height: 260,
      rotation: 0,
      scaleX: 1,
      scaleY: 1,
      slotId: "customer_name",
      tags: ["customer-text"],
      text: "Avery",
        fontRef: {
          family: "Birthmonth",
          source: "asset",
          assetId: "font_birthmonth",
          fallbackFamilies: ["serif"],
        },
        style: {
          fontSize: 180,
          fill: "#1f2933",
          stroke: "#ffffff",
          strokeWidth: 0,
          align: "center",
          lineHeight: 1.1,
          letterSpacing: 0,
        },
        layout: {
          mode: "box",
          overflow: "shrink-to-fit",
        },
        glyphOverrides: [
          {
            index: 4,
            originalText: "y",
            replacement: "U+E080",
            codepoint: "U+E075",
            glyphName: "n.005",
          },
        ],
      },
      {
        id: "layer_image",
        type: "image",
        name: "Product photo",
      visible: true,
      locked: false,
      exportable: true,
      zIndex: 2,
      opacity: 1,
        x: 100,
        y: 900,
        width: 800,
        height: 800,
        rotation: 0,
        scaleX: 1,
        scaleY: 1,
        slotId: "photo",
        tags: ["asset"],
        assetRef: {
          assetId: "asset_photo",
          path: "assets/samples/photo.png",
          checksum: "sha256:photo",
        },
        intrinsicSize: {
          width: 1200,
          height: 1200,
        },
        fit: "contain",
      },
      {
        id: "layer_svg",
        type: "svg",
        name: "Birth flower",
      visible: true,
      locked: false,
      exportable: true,
      zIndex: 3,
      opacity: 1,
        x: 1500,
        y: 600,
        width: 900,
        height: 1200,
        rotation: 0,
        scaleX: 1,
        scaleY: 1,
        slotId: "flower",
        tags: ["flower"],
        assetRef: {
          assetId: "asset_flower",
          path: "assets/flowers/june-rose.svg",
          checksum: "sha256:flower",
        },
        viewBox: {
          x: 0,
          y: 0,
          width: 512,
          height: 512,
        },
        preserveVector: true,
      },
    ],
  };
}
