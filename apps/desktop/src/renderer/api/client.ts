export interface HealthResponse {
  status: "ok";
  service: "flower-api";
  version: string;
}

export interface FontBounds {
  xMin: number;
  yMin: number;
  xMax: number;
  yMax: number;
}

export interface FontMetrics {
  unitsPerEm: number;
  ascender: number;
  descender: number;
  lineGap: number;
  capHeight?: number | null;
  xHeight?: number | null;
  bbox: FontBounds;
}

export interface FontSummary {
  id: string;
  familyName: string;
  styleName: string;
  fullName: string;
  postscriptName: string;
  sourcePath: string;
  format: string;
  fileSize: number;
  metrics: FontMetrics;
  glyphCount: number;
  mappedGlyphCount: number;
  puaGlyphCount: number;
}

export interface FontScanIssue {
  code: string;
  message: string;
  path?: string | null;
  recoverable: boolean;
}

export interface GlyphInfo {
  glyphId: number;
  glyphName: string;
  codepoint?: string | null;
  char?: string | null;
  isMapped: boolean;
  isPua: boolean;
  advanceWidth?: number | null;
  bbox?: FontBounds | null;
}

export interface ListFontsResponse {
  fonts: FontSummary[];
  issues: FontScanIssue[];
  fontCount: number;
}

export interface FontGlyphsResponse {
  font: FontSummary;
  glyphs: GlyphInfo[];
  issues: FontScanIssue[];
  glyphCount: number;
}

export interface ApiClientOptions {
  baseUrl?: string;
  fetch?: typeof globalThis.fetch;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const DEFAULT_BASE_URL = "http://127.0.0.1:8765";

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = normalizeBaseUrl(options.baseUrl ?? DEFAULT_BASE_URL);
  const fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);

  return {
    async health(): Promise<HealthResponse> {
      return requestJson<HealthResponse>(fetchImpl, `${baseUrl}/health`, "Health check failed");
    },

    async listFonts(): Promise<ListFontsResponse> {
      return requestJson<ListFontsResponse>(fetchImpl, `${baseUrl}/fonts`, "Font scan failed");
    },

    async listFontGlyphs(fontId: string): Promise<FontGlyphsResponse> {
      return requestJson<FontGlyphsResponse>(
        fetchImpl,
        `${baseUrl}/fonts/${encodeURIComponent(fontId)}/glyphs`,
        "Font glyph scan failed",
      );
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;

async function requestJson<T>(
  fetchImpl: typeof globalThis.fetch,
  url: string,
  failureMessage: string,
): Promise<T> {
  const response = await fetchImpl(url, {
    method: "GET",
    headers: {
      accept: "application/json",
    },
  });

  if (!response.ok) {
    throw new ApiError(`${failureMessage} with HTTP ${response.status}`, response.status);
  }

  return (await response.json()) as T;
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, "");
}
