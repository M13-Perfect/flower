import {
  type ImageLayer,
  type LayerDocument,
  type RectSpec,
  type SvgLayer,
  type TextLayer,
  validateLayerDocument,
} from "@flower/design-core";

export interface EditorActionResult {
  document: LayerDocument;
  layerId: string;
}

export interface AddTextLayerOptions {
  id?: string;
  now?: string;
  text?: string;
}

export interface AddSvgAssetLayerInput {
  id?: string;
  name: string;
  now?: string;
  svgText: string;
}

export interface AddImageAssetLayerInput {
  dataUrl: string;
  height: number;
  id?: string;
  name: string;
  now?: string;
  width: number;
}

export function addTextLayer(
  document: LayerDocument,
  options: AddTextLayerOptions = {},
): EditorActionResult {
  const layerId = options.id ?? createLayerId("layer_text");
  const size = textLayerSize(document);
  const layer: TextLayer = {
    ...layerBase(document, layerId, "Text layer"),
    type: "text",
    ...centeredRect(document, size.width, size.height),
    text: options.text ?? "New text",
    fontRef: {
      family: "Georgia",
      source: "system",
      fallbackFamilies: ["serif"],
    },
    style: {
      fontSize: Math.max(24, Math.round(size.height * 0.72)),
      fill: "#26352f",
      align: "center",
      lineHeight: 1.1,
      letterSpacing: 0,
    },
    layout: {
      mode: "box",
      overflow: "shrink-to-fit",
    },
  };

  return appendLayer(document, layer, options.now);
}

export function addSvgAssetLayer(
  document: LayerDocument,
  input: AddSvgAssetLayerInput,
): EditorActionResult {
  const viewBox = parseSvgViewBox(input.svgText);
  const size = assetLayerSize(document, viewBox.width, viewBox.height);
  const layerId = input.id ?? createLayerId("layer_svg");
  const layer: SvgLayer = {
    ...layerBase(document, layerId, displayName(input.name)),
    type: "svg",
    ...centeredRect(document, size.width, size.height),
    assetRef: {
      assetId: `imported-${slug(displayName(input.name))}`,
      path: `inline:${input.name}`,
    },
    inlineSvg: input.svgText,
    viewBox,
    preserveVector: true,
  };

  return appendLayer(document, layer, input.now);
}

export function addImageAssetLayer(
  document: LayerDocument,
  input: AddImageAssetLayerInput,
): EditorActionResult {
  const size = assetLayerSize(document, input.width, input.height);
  const layerId = input.id ?? createLayerId("layer_image");
  const layer: ImageLayer = {
    ...layerBase(document, layerId, displayName(input.name)),
    type: "image",
    ...centeredRect(document, size.width, size.height),
    assetRef: {
      assetId: `imported-${slug(displayName(input.name))}`,
      path: input.dataUrl,
    },
    intrinsicSize: {
      width: positive(input.width, 1),
      height: positive(input.height, 1),
    },
    fit: "contain",
  };

  return appendLayer(document, layer, input.now);
}

function appendLayer(
  document: LayerDocument,
  layer: TextLayer | SvgLayer | ImageLayer,
  now = new Date().toISOString(),
): EditorActionResult {
  const nextDocument: LayerDocument = {
    ...document,
    metadata: {
      ...document.metadata,
      updatedAt: now,
    },
    layers: [...document.layers, layer],
  };
  const validation = validateLayerDocument(nextDocument);
  if (!validation.ok) {
    throw new Error(`Added layer document is invalid: ${validation.errors.join("; ")}`);
  }

  return {
    document: nextDocument,
    layerId: layer.id,
  };
}

function layerBase(
  document: LayerDocument,
  id: string,
  name: string,
) {
  return {
    id,
    name,
    visible: true,
    locked: false,
    exportable: true as const,
    zIndex: nextZIndex(document),
    opacity: 1,
    scaleX: 1,
    scaleY: 1,
    rotation: 0,
    tags: ["user-added"],
  };
}

function textLayerSize(document: LayerDocument) {
  const canvasWidth = positive(document.canvas.width, 1);
  const canvasHeight = positive(document.canvas.height, 1);
  return {
    width: Math.round(Math.min(canvasWidth, 1200, Math.max(240, canvasWidth * 0.45))),
    height: Math.round(Math.min(canvasHeight, 260, Math.max(80, canvasHeight * 0.08))),
  };
}

function assetLayerSize(document: LayerDocument, sourceWidth: number, sourceHeight: number) {
  const safeWidth = positive(sourceWidth, 1);
  const safeHeight = positive(sourceHeight, 1);
  const canvasShortSide = Math.max(
    1,
    Math.min(positive(document.canvas.width, 1), positive(document.canvas.height, 1)),
  );
  // 业务规则：导入素材默认要足够可选中，但不能比画布本身还大。
  const targetLongSide = Math.min(canvasShortSide, Math.max(120, Math.round(canvasShortSide * 0.35)));
  const scale = targetLongSide / Math.max(safeWidth, safeHeight);

  return {
    width: Math.max(1, Math.round(safeWidth * scale)),
    height: Math.max(1, Math.round(safeHeight * scale)),
  };
}

function centeredRect(document: LayerDocument, width: number, height: number) {
  const maxX = Math.max(0, positive(document.canvas.width, 1) - width);
  const maxY = Math.max(0, positive(document.canvas.height, 1) - height);
  return {
    x: Math.round(Math.min(maxX, Math.max(0, (document.canvas.width - width) / 2))),
    y: Math.round(Math.min(maxY, Math.max(0, (document.canvas.height - height) / 2))),
    width,
    height,
  };
}

function nextZIndex(document: LayerDocument): number {
  return Math.max(0, ...document.layers.map((layer) => layer.zIndex)) + 1;
}

function parseSvgViewBox(svgText: string): RectSpec {
  const viewBoxMatch = svgText.match(/\bviewBox\s*=\s*["']\s*([+-]?\d*\.?\d+)\s+([+-]?\d*\.?\d+)\s+([+-]?\d*\.?\d+)\s+([+-]?\d*\.?\d+)\s*["']/i);
  if (!viewBoxMatch) {
    return { x: 0, y: 0, width: 512, height: 512 };
  }

  return {
    x: finite(Number(viewBoxMatch[1]), 0),
    y: finite(Number(viewBoxMatch[2]), 0),
    width: positive(Number(viewBoxMatch[3]), 512),
    height: positive(Number(viewBoxMatch[4]), 512),
  };
}

function displayName(fileName: string): string {
  return fileName.replace(/\.[^.]+$/, "").trim() || "Imported asset";
}

function slug(value: string): string {
  const slugged = value
    .trim()
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slugged || "asset";
}

function createLayerId(prefix: string): string {
  const randomId = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `${prefix}_${randomId.replace(/[^a-zA-Z0-9]+/g, "_")}`;
}

function finite(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
}

function positive(value: number, fallback: number): number {
  return Number.isFinite(value) && value > 0 ? value : fallback;
}
