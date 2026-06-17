import { describe, expect, it } from "vitest";

import {
  EXPORT_SETTINGS_SCHEMA_VERSION,
  LAYER_DOCUMENT_SCHEMA_VERSION,
  type LayerDocument,
} from "@flower/design-core";

import {
  createPngExport,
  createSvgExport,
  readPngTextMetadata,
  type PngRasterizeInput,
} from "./exportPipeline";

const EXPORTED_AT = "2026-06-11T13:14:15.000Z";
const TINY_PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/luzD7wAAAABJRU5ErkJggg==";

describe("export pipeline", () => {
  it("creates SVG from layer JSON with metadata and preserved vector/text objects", () => {
    const document = createDocument();

    const exported = createSvgExport(document, {
      background: "canvas",
      exportedAt: EXPORTED_AT,
    });

    expect(exported.fileName).toBe("birth-flower-card_order_1_2026-06-11T13-14-15-000Z.svg");
    expect(exported.metadata).toEqual({
      appVersion: "0.1.0",
      exportedAt: EXPORTED_AT,
      orderId: "order_1",
      templateId: "birth-flower-card",
    });
    expect(exported.content).toContain("<metadata");
    expect(exported.content).toContain('"templateId":"birth-flower-card"');
    expect(exported.content).toContain('<rect width="300" height="200" fill="#ffffff"');
    expect(exported.content).toContain("<text");
    expect(exported.content).toContain("Aver&#xE123;");
    expect(exported.content).toContain("<path d=\"M0 0h10v10z\"");
    expect(exported.content).not.toContain("selection_box");
    expect(exported.content).not.toContain("debug-bounds");
    expect(exported.content).not.toContain("#ff00ff");
  });

  it("embeds project font-face rules for asset fonts so PUA glyphs can render", () => {
    const exported = createSvgExport(createDocument(), {
      exportedAt: EXPORTED_AT,
      fontFaceUrlForAsset: (assetId) => `http://127.0.0.1:8765/fonts/${assetId}/file`,
    });

    expect(exported.content).toContain("@font-face");
    expect(exported.content).toContain("font-family: 'Specimen Script'");
    expect(exported.content).toContain("http://127.0.0.1:8765/fonts/specimen-script/file");
  });

  it("omits the canvas background when transparent export is requested", () => {
    const exported = createSvgExport(createDocument(), {
      background: "transparent",
      exportedAt: EXPORTED_AT,
    });

    expect(exported.content).not.toContain("<rect width=\"300\" height=\"200\"");
  });

  it("removes unsafe inline SVG wrapper and namespace attributes before export", () => {
    const document = createDocument();
    const flowerLayer = document.layers[1];
    if (flowerLayer.type !== "svg") {
      throw new Error("Expected fixture layer to be SVG");
    }

    document.layers[1] = {
      ...flowerLayer,
      inlineSvg:
        '<?xml version="1.0"?><!DOCTYPE svg><svg viewBox="0 0 10 10" xml:space="preserve" xmlns:serif="http://www.serif.com/"><g serif:id="20.svg"><path d="M0 0h10v10z" fill="#d74862"/></g></svg>',
    };

    const exported = createSvgExport(document, {
      exportedAt: EXPORTED_AT,
    });

    expect(exported.content).not.toContain("<!DOCTYPE");
    expect(exported.content.match(/<\?xml/g)).toHaveLength(1);
    expect(exported.content).not.toContain("xml:space");
    expect(exported.content).not.toContain("serif:id");
    expect(exported.content).toContain('<path d="M0 0h10v10z" fill="#d74862"/>');
  });

  it("rasterizes PNG from the exported SVG with requested scale and transparent background", async () => {
    const calls: PngRasterizeInput[] = [];

    const exported = await createPngExport(createDocument(), {
      background: "transparent",
      exportedAt: EXPORTED_AT,
      rasterize: async (input) => {
        calls.push(input);
        return TINY_PNG;
      },
      scale: 2,
    });

    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      background: "transparent",
      height: 400,
      scale: 2,
      width: 600,
    });
    expect(calls[0].svg).not.toContain("<rect width=\"300\" height=\"200\"");
    expect(exported.width).toBe(600);
    expect(exported.height).toBe(400);
    expect(exported.fileName).toBe("birth-flower-card_order_1_2026-06-11T13-14-15-000Z.png");
    expect(readPngTextMetadata(exported.bytes, "flower-export-metadata")).toEqual(
      JSON.stringify(exported.metadata),
    );
  });

  it("rasterizes PNG with an explicit output width while preserving canvas aspect ratio", async () => {
    const calls: PngRasterizeInput[] = [];

    const exported = await createPngExport(createDocument(), {
      exportedAt: EXPORTED_AT,
      outputWidth: 900,
      rasterize: async (input) => {
        calls.push(input);
        return TINY_PNG;
      },
    });

    expect(calls[0]).toMatchObject({
      height: 600,
      scale: 3,
      width: 900,
    });
    expect(exported.width).toBe(900);
    expect(exported.height).toBe(600);
  });
});

function createDocument(): LayerDocument {
  return {
    schemaVersion: LAYER_DOCUMENT_SCHEMA_VERSION,
    documentId: "doc_1",
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
      width: 300,
      height: 200,
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
        y: 120,
        width: 140,
        height: 48,
        scaleX: 1,
        scaleY: 1,
        rotation: 0,
        tags: ["customer-text"],
        text: "Avery",
        fontRef: {
          family: "Specimen Script",
          source: "asset",
          assetId: "specimen-script",
        },
        style: {
          fontSize: 32,
          fill: "#223344",
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
            replacement: "\ue123",
            codepoint: "U+E123",
            glyphName: "y.swash",
          },
        ],
      },
      {
        id: "svg_1",
        type: "svg",
        name: "Flower",
        visible: true,
        locked: false,
        exportable: true,
        zIndex: 2,
        opacity: 1,
        x: 170,
        y: 30,
        width: 80,
        height: 80,
        scaleX: 1,
        scaleY: 1,
        rotation: 0,
        tags: ["flower"],
        inlineSvg: '<svg viewBox="0 0 10 10"><path d="M0 0h10v10z" fill="#d74862"/></svg>',
        viewBox: {
          x: 0,
          y: 0,
          width: 10,
          height: 10,
        },
        preserveVector: true,
      },
      {
        id: "debug_1",
        type: "path",
        name: "selection_box",
        visible: true,
        locked: true,
        exportable: true,
        zIndex: 99,
        opacity: 1,
        x: 0,
        y: 0,
        width: 300,
        height: 200,
        scaleX: 1,
        scaleY: 1,
        rotation: 0,
        tags: ["debug-bounds"],
        pathData: "M0 0h300v200z",
        fill: "#ff00ff",
      },
    ],
  };
}
