import { describe, expect, it } from "vitest";

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
});
