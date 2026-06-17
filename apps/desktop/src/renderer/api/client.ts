import type { LayerDocument } from "@flower/design-core";

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

export interface PathSettings {
  assetDirectories: string[];
  fontDirectories: string[];
  outputDirectory?: string | null;
}

export interface FlowerChoice {
  choice: number;
  name: string;
}

export interface FontPreference {
  choice: number;
  label: string;
}

export interface ParsedOrder {
  orderId?: string | null;
  customerName?: string | null;
  month?: number | null;
  monthName?: string | null;
  flower?: FlowerChoice | null;
  fontPreference?: FontPreference | null;
  specialNotes: string;
}

export interface ParseOrderRequest {
  orderNote: string;
  orderId?: string | null;
}

export interface ParseOrderResponse {
  parsedOrder: ParsedOrder;
  warnings: string[];
  requiresManualConfirmation: boolean;
}

export interface ApplyTemplateRequest {
  templateId: string;
  parsedOrder: ParsedOrder;
  projectId?: string | null;
  jobId?: string | null;
}

export interface ApplyTemplateResponse {
  document: LayerDocument;
  warnings: string[];
  requiresManualConfirmation: boolean;
}

export interface DxfExportRequest {
  document: LayerDocument;
  units?: "px" | "mm" | "in" | null;
  exportedAt?: string | null;
}

export interface ExportWarning {
  code: string;
  message: string;
  layerId?: string | null;
}

export interface DxfExportResponse {
  fileName: string;
  mimeType: "application/dxf";
  contentBase64: string;
  metadata: Record<string, string>;
  warnings: ExportWarning[];
}

export interface SaveOutputsRequest {
  orderName: string;
  document: LayerDocument;
  svg: string;
  pngDataUrl: string;
  dxfContentBase64?: string | null;
  outputDirectory?: string | null;
}

export interface SavedOutputFile {
  kind: "json" | "png" | "svg" | "dxf";
  fileName: string;
  relativePath: string;
  bytesWritten: number;
}

export interface SaveOutputsResponse {
  outputDir: string;
  files: SavedOutputFile[];
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
  const baseUrl = normalizeBaseUrl(options.baseUrl ?? resolveDefaultBaseUrl());
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

    fontFileUrl(fontId: string): string {
      return `${baseUrl}/fonts/${encodeURIComponent(fontId)}/file`;
    },

    async getPathSettings(): Promise<PathSettings> {
      return requestJson<PathSettings>(
        fetchImpl,
        `${baseUrl}/settings/paths`,
        "Path settings load failed",
      );
    },

    async updatePathSettings(request: PathSettings): Promise<PathSettings> {
      return putJson<PathSettings>(
        fetchImpl,
        `${baseUrl}/settings/paths`,
        request,
        "Path settings update failed",
      );
    },

    async parseOrder(request: ParseOrderRequest): Promise<ParseOrderResponse> {
      return postJson<ParseOrderResponse>(
        fetchImpl,
        `${baseUrl}/orders/parse`,
        request,
        "Order parse failed",
      );
    },

    async applyTemplate(request: ApplyTemplateRequest): Promise<ApplyTemplateResponse> {
      return postJson<ApplyTemplateResponse>(
        fetchImpl,
        `${baseUrl}/templates/apply`,
        request,
        "Template apply failed",
      );
    },

    async exportDxf(request: DxfExportRequest): Promise<DxfExportResponse> {
      return postJson<DxfExportResponse>(
        fetchImpl,
        `${baseUrl}/exports/dxf`,
        request,
        "DXF export failed",
      );
    },

    async saveOutputs(request: SaveOutputsRequest): Promise<SaveOutputsResponse> {
      return postJson<SaveOutputsResponse>(
        fetchImpl,
        `${baseUrl}/outputs/save`,
        request,
        "Output save failed",
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

async function postJson<T>(
  fetchImpl: typeof globalThis.fetch,
  url: string,
  body: unknown,
  failureMessage: string,
): Promise<T> {
  const response = await fetchImpl(url, {
    method: "POST",
    headers: {
      accept: "application/json",
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new ApiError(`${failureMessage} with HTTP ${response.status}`, response.status);
  }

  return (await response.json()) as T;
}

async function putJson<T>(
  fetchImpl: typeof globalThis.fetch,
  url: string,
  body: unknown,
  failureMessage: string,
): Promise<T> {
  const response = await fetchImpl(url, {
    method: "PUT",
    headers: {
      accept: "application/json",
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new ApiError(`${failureMessage} with HTTP ${response.status}`, response.status);
  }

  return (await response.json()) as T;
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, "");
}

function resolveDefaultBaseUrl(): string {
  return import.meta.env.VITE_FLOWER_API_BASE_URL || DEFAULT_BASE_URL;
}
