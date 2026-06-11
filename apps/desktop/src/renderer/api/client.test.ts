import { describe, expect, it } from "vitest";

import {
  EXPORT_SETTINGS_SCHEMA_VERSION,
  LAYER_DOCUMENT_SCHEMA_VERSION,
  type LayerDocument,
} from "@flower/design-core";
import { createApiClient } from "./client";

describe("desktop API client", () => {
  it("calls the backend health endpoint", async () => {
    const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
    const fetchImpl: typeof fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          status: "ok",
          service: "flower-api",
          version: "0.1.0",
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      );
    };

    const client = createApiClient({
      baseUrl: "http://127.0.0.1:8765",
      fetch: fetchImpl,
    });

    await expect(client.health()).resolves.toEqual({
      status: "ok",
      service: "flower-api",
      version: "0.1.0",
    });
    expect(String(calls[0].input)).toBe("http://127.0.0.1:8765/health");
    expect(calls[0].init?.method).toBe("GET");
  });

  it("calls the backend font catalog endpoint", async () => {
    const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
    const fetchImpl: typeof fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          fonts: [
            {
              id: "specimen",
              familyName: "Specimen",
              styleName: "Regular",
              fullName: "Specimen Regular",
              postscriptName: "Specimen-Regular",
              sourcePath: "assets/fonts/Specimen.ttf",
              format: "ttf",
              fileSize: 1024,
              metrics: {
                unitsPerEm: 1000,
                ascender: 800,
                descender: -200,
                lineGap: 0,
                bbox: { xMin: 0, yMin: -200, xMax: 900, yMax: 800 },
              },
              glyphCount: 3,
              mappedGlyphCount: 2,
              puaGlyphCount: 1,
            },
          ],
          issues: [],
          fontCount: 1,
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      );
    };

    const client = createApiClient({
      baseUrl: "http://127.0.0.1:8765/",
      fetch: fetchImpl,
    });

    await expect(client.listFonts()).resolves.toMatchObject({
      fontCount: 1,
      fonts: [{ id: "specimen", familyName: "Specimen", puaGlyphCount: 1 }],
    });
    expect(String(calls[0].input)).toBe("http://127.0.0.1:8765/fonts");
    expect(calls[0].init?.method).toBe("GET");
  });

  it("calls the backend font glyph endpoint", async () => {
    const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
    const fetchImpl: typeof fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          font: {
            id: "specimen",
            familyName: "Specimen",
            styleName: "Regular",
            fullName: "Specimen Regular",
            postscriptName: "Specimen-Regular",
            sourcePath: "assets/fonts/Specimen.ttf",
            format: "ttf",
            fileSize: 1024,
            metrics: {
              unitsPerEm: 1000,
              ascender: 800,
              descender: -200,
              lineGap: 0,
              bbox: { xMin: 0, yMin: -200, xMax: 900, yMax: 800 },
            },
            glyphCount: 3,
            mappedGlyphCount: 2,
            puaGlyphCount: 1,
          },
          glyphs: [
            {
              glyphId: 2,
              glyphName: "uniE123.swash",
              codepoint: "U+E123",
              char: "\ue123",
              isMapped: true,
              isPua: true,
              advanceWidth: 700,
              bbox: { xMin: 0, yMin: 0, xMax: 500, yMax: 700 },
            },
          ],
          issues: [],
          glyphCount: 1,
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      );
    };

    const client = createApiClient({
      baseUrl: "http://127.0.0.1:8765",
      fetch: fetchImpl,
    });

    await expect(client.listFontGlyphs("specimen")).resolves.toMatchObject({
      glyphCount: 1,
      glyphs: [{ glyphName: "uniE123.swash", char: "\ue123", isPua: true }],
    });
    expect(String(calls[0].input)).toBe("http://127.0.0.1:8765/fonts/specimen/glyphs");
    expect(calls[0].init?.method).toBe("GET");
  });

  it("posts order notes to the backend parser", async () => {
    const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
    const fetchImpl: typeof fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          parsedOrder: {
            orderId: "order-1",
            customerName: "Lacey",
            month: 9,
            monthName: "September",
            flower: { choice: 1, name: "Aster" },
            fontPreference: { choice: 3, label: "Font 3" },
            specialNotes: "",
          },
          warnings: [],
          requiresManualConfirmation: true,
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      );
    };

    const client = createApiClient({ fetch: fetchImpl });

    await expect(
      client.parseOrder({
        orderId: "order-1",
        orderNote: "Choose Your Birth Flower  ：Sep - Aster",
      }),
    ).resolves.toMatchObject({
      parsedOrder: { customerName: "Lacey", flower: { name: "Aster" } },
    });
    expect(String(calls[0].input)).toBe("http://127.0.0.1:8765/orders/parse");
    expect(calls[0].init?.method).toBe("POST");
    expect(calls[0].init?.body).toBe(
      JSON.stringify({
        orderId: "order-1",
        orderNote: "Choose Your Birth Flower  ：Sep - Aster",
      }),
    );
  });

  it("posts parsed order data to the template endpoint", async () => {
    const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
    const document = createDocument();
    const fetchImpl: typeof fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          document,
          warnings: [],
          requiresManualConfirmation: true,
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      );
    };

    const client = createApiClient({ fetch: fetchImpl });
    const parsedOrder = {
      orderId: "order-1",
      customerName: "Lacey",
      month: 9,
      monthName: "September",
      flower: { choice: 1, name: "Aster" },
      fontPreference: { choice: 3, label: "Font 3" },
      specialNotes: "",
    };

    await expect(
      client.applyTemplate({
        templateId: "birth-flower-card",
        parsedOrder,
      }),
    ).resolves.toMatchObject({ document });
    expect(String(calls[0].input)).toBe("http://127.0.0.1:8765/templates/apply");
    expect(calls[0].init?.method).toBe("POST");
    expect(calls[0].init?.body).toBe(
      JSON.stringify({
        templateId: "birth-flower-card",
        parsedOrder,
      }),
    );
  });

  it("posts documents to the DXF export endpoint", async () => {
    const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
    const fetchImpl: typeof fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          fileName: "birth-flower-card_order-1.dxf",
          mimeType: "application/dxf",
          contentBase64: "MERYRg==",
          metadata: { orderId: "order-1", templateId: "birth-flower-card" },
          warnings: [],
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      );
    };

    const client = createApiClient({ fetch: fetchImpl });
    const document = createDocument();

    await expect(client.exportDxf({ document, units: "px" })).resolves.toMatchObject({
      contentBase64: "MERYRg==",
      warnings: [],
    });
    expect(String(calls[0].input)).toBe("http://127.0.0.1:8765/exports/dxf");
    expect(calls[0].init?.method).toBe("POST");
    expect(calls[0].init?.body).toBe(JSON.stringify({ document, units: "px" }));
  });

  it("posts generated artifacts to the output save endpoint", async () => {
    const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
    const fetchImpl: typeof fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          outputDir: "outputs/Lacey",
          files: [
            {
              kind: "json",
              fileName: "order.json",
              relativePath: "outputs/Lacey/order.json",
              bytesWritten: 100,
            },
          ],
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      );
    };

    const client = createApiClient({ fetch: fetchImpl });
    const document = createDocument();

    await expect(
      client.saveOutputs({
        orderName: "Lacey",
        document,
        svg: "<svg></svg>",
        pngDataUrl: "data:image/png;base64,abc",
        dxfContentBase64: "ZA==",
      }),
    ).resolves.toMatchObject({ outputDir: "outputs/Lacey" });
    expect(String(calls[0].input)).toBe("http://127.0.0.1:8765/outputs/save");
    expect(calls[0].init?.method).toBe("POST");
    expect(calls[0].init?.body).toBe(
      JSON.stringify({
        orderName: "Lacey",
        document,
        svg: "<svg></svg>",
        pngDataUrl: "data:image/png;base64,abc",
        dxfContentBase64: "ZA==",
      }),
    );
  });
});

function createDocument(): LayerDocument {
  return {
    schemaVersion: LAYER_DOCUMENT_SCHEMA_VERSION,
    documentId: "doc-1",
    projectId: "project-1",
    jobId: "job-1",
    metadata: {
      orderId: "order-1",
      templateId: "birth-flower-card",
      templateVersion: "1.0.0",
      appVersion: "0.1.0",
      createdAt: "2026-06-12T00:00:00.000Z",
      updatedAt: "2026-06-12T00:00:00.000Z",
    },
    canvas: {
      width: 300,
      height: 200,
      unit: "px",
      background: { type: "solid", color: "#ffffff" },
    },
    exportSettings: {
      schemaVersion: EXPORT_SETTINGS_SCHEMA_VERSION,
      defaultFormats: ["svg", "png", "dxf"],
      svg: { preserveText: true, preserveVector: true, includeMetadata: true },
      png: { scale: 1, background: "canvas" },
      dxf: { textMode: "paths", units: "px" },
    },
    layers: [],
  };
}
