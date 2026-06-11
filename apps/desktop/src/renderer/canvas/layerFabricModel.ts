import {
  type GlyphOverride,
  type FontReference,
  type ImageLayer,
  type Layer,
  type LayerDocument,
  type SvgLayer,
  type TextLayer,
  validateLayerDocument,
} from "@flower/design-core";

export type SupportedEditorLayer = TextLayer | ImageLayer | SvgLayer;
export type SupportedFabricType = "text" | "image" | "svg";

export interface FabricLayerObjectSnapshot {
  layerId: string;
  layerType: SupportedEditorLayer["type"];
  fabricType: SupportedFabricType;
  name: string;
  left: number;
  top: number;
  width: number;
  height: number;
  scaleX: number;
  scaleY: number;
  angle: number;
  opacity: number;
  visible: boolean;
  locked: boolean;
  selectable: boolean;
  evented: boolean;
  zIndex: number;
  source?: string;
  preserveVector?: true;
  text?: string;
  fontFamily?: string;
  fontSize?: number;
  fill?: string;
  stroke?: string;
  strokeWidth?: number;
  textAlign?: TextLayer["style"]["align"];
  lineHeight?: number;
  charSpacing?: number;
  runtimeOnly?: unknown;
}

export interface SerializeLayerDocumentOptions {
  updatedAt?: string;
}

export interface LayerPropertyPatch {
  x?: number;
  y?: number;
  scale?: number;
  rotation?: number;
  opacity?: number;
  visible?: boolean;
  locked?: boolean;
}

export interface TextGlyphOverrideInput {
  index: number;
  replacement: string;
  codepoint?: string;
  glyphName?: string;
}

export interface TextLayerFontInput {
  family: string;
  source?: FontReference["source"];
  assetId?: string;
  fallbackFamilies?: string[];
}

export function isSupportedEditorLayer(layer: Layer): layer is SupportedEditorLayer {
  return layer.type === "text" || layer.type === "image" || layer.type === "svg";
}

export function listLayersForDisplay(layers: readonly Layer[]): Layer[] {
  return [...layers].sort((left, right) => right.zIndex - left.zIndex);
}

export function createLayerObjectSnapshot(layer: SupportedEditorLayer): FabricLayerObjectSnapshot {
  const base = createBaseSnapshot(layer);

  if (layer.type === "text") {
    return {
      ...base,
      fabricType: "text",
      layerType: "text",
      text: layer.text,
      fontFamily: layer.fontRef.family,
      fontSize: layer.style.fontSize,
      fill: layer.style.fill,
      stroke: layer.style.stroke,
      strokeWidth: layer.style.strokeWidth,
      textAlign: layer.style.align,
      lineHeight: layer.style.lineHeight,
      charSpacing: layer.style.letterSpacing,
    };
  }

  if (layer.type === "image") {
    return {
      ...base,
      fabricType: "image",
      layerType: "image",
      source: layer.assetRef.path,
    };
  }

  return {
    ...base,
    fabricType: "svg",
    layerType: "svg",
    source: layer.inlineSvg ?? layer.assetRef?.path ?? "",
    preserveVector: true,
  };
}

export function serializeLayerDocumentFromSnapshots(
  document: LayerDocument,
  snapshots: readonly FabricLayerObjectSnapshot[],
  options: SerializeLayerDocumentOptions = {},
): LayerDocument {
  const snapshotsById = new Map(snapshots.map((snapshot) => [snapshot.layerId, snapshot]));
  const updatedAt = options.updatedAt ?? new Date().toISOString();
  const nextDocument: LayerDocument = {
    ...document,
    metadata: {
      ...document.metadata,
      updatedAt,
    },
    layers: document.layers.map((layer) => updateLayerFromSnapshot(layer, snapshotsById)),
  };

  const validation = validateLayerDocument(nextDocument);
  if (!validation.ok) {
    throw new Error(`Saved layer document is invalid: ${validation.errors.join("; ")}`);
  }

  return nextDocument;
}

export function updateLayerProperty(
  document: LayerDocument,
  layerId: string,
  patch: LayerPropertyPatch,
): LayerDocument {
  const nextDocument: LayerDocument = {
    ...document,
    metadata: {
      ...document.metadata,
      updatedAt: new Date().toISOString(),
    },
    layers: document.layers.map((layer) => updateLayerPropertyById(layer, layerId, patch)),
  };

  const validation = validateLayerDocument(nextDocument);
  if (!validation.ok) {
    throw new Error(`Layer property update is invalid: ${validation.errors.join("; ")}`);
  }

  return nextDocument;
}

export function applyGlyphOverrideToTextLayer(
  document: LayerDocument,
  layerId: string,
  input: TextGlyphOverrideInput,
): LayerDocument {
  const nextDocument: LayerDocument = {
    ...document,
    metadata: {
      ...document.metadata,
      updatedAt: new Date().toISOString(),
    },
    layers: document.layers.map((layer) => updateGlyphOverrideById(layer, layerId, input)),
  };

  const validation = validateLayerDocument(nextDocument);
  if (!validation.ok) {
    throw new Error(`Glyph override update is invalid: ${validation.errors.join("; ")}`);
  }

  return nextDocument;
}

export function updateTextLayerContent(
  document: LayerDocument,
  layerId: string,
  text: string,
): LayerDocument {
  const nextDocument: LayerDocument = {
    ...document,
    metadata: {
      ...document.metadata,
      updatedAt: new Date().toISOString(),
    },
    layers: document.layers.map((layer) => updateTextContentById(layer, layerId, text)),
  };

  const validation = validateLayerDocument(nextDocument);
  if (!validation.ok) {
    throw new Error(`Text layer update is invalid: ${validation.errors.join("; ")}`);
  }

  return nextDocument;
}

export function updateTextLayerFont(
  document: LayerDocument,
  layerId: string,
  font: TextLayerFontInput,
): LayerDocument {
  const nextDocument: LayerDocument = {
    ...document,
    metadata: {
      ...document.metadata,
      updatedAt: new Date().toISOString(),
    },
    layers: document.layers.map((layer) => updateTextFontById(layer, layerId, font)),
  };

  const validation = validateLayerDocument(nextDocument);
  if (!validation.ok) {
    throw new Error(`Text layer font update is invalid: ${validation.errors.join("; ")}`);
  }

  return nextDocument;
}

export function buildTextWithGlyphOverrides(layer: TextLayer): string {
  const chars = Array.from(layer.text);
  const overrides = [...(layer.glyphOverrides ?? [])].sort((left, right) => left.index - right.index);

  for (const override of overrides) {
    if (!Number.isInteger(override.index) || override.index < 0 || override.index >= chars.length) {
      continue;
    }

    if (chars[override.index] !== override.originalText) {
      continue;
    }

    chars[override.index] = override.replacement;
  }

  return chars.join("");
}

function createBaseSnapshot(layer: SupportedEditorLayer): Omit<
  FabricLayerObjectSnapshot,
  "fabricType" | "layerType"
> {
  return {
    layerId: layer.id,
    name: layer.name,
    left: layer.x,
    top: layer.y,
    width: layer.width,
    height: layer.height,
    scaleX: layer.scaleX,
    scaleY: layer.scaleY,
    angle: layer.rotation,
    opacity: layer.opacity,
    visible: layer.visible,
    locked: layer.locked,
    selectable: !layer.locked,
    evented: !layer.locked,
    zIndex: layer.zIndex,
  };
}

function updateLayerFromSnapshot(
  layer: Layer,
  snapshotsById: ReadonlyMap<string, FabricLayerObjectSnapshot>,
): Layer {
  if (layer.type === "group") {
    return {
      ...layer,
      children: layer.children.map((child) => updateLayerFromSnapshot(child, snapshotsById)),
    };
  }

  const snapshot = snapshotsById.get(layer.id);
  if (!snapshot) {
    return layer;
  }

  return {
    ...layer,
    x: finiteNumber(snapshot.left, layer.x),
    y: finiteNumber(snapshot.top, layer.y),
    width: positiveNumber(snapshot.width, layer.width),
    height: positiveNumber(snapshot.height, layer.height),
    scaleX: positiveNumber(snapshot.scaleX, layer.scaleX),
    scaleY: positiveNumber(snapshot.scaleY, layer.scaleY),
    rotation: finiteNumber(snapshot.angle, layer.rotation),
    opacity: clampOpacity(snapshot.opacity),
    visible: snapshot.visible,
    locked: snapshot.locked,
  } as Layer;
}

function updateLayerPropertyById(layer: Layer, layerId: string, patch: LayerPropertyPatch): Layer {
  if (layer.type === "group") {
    return {
      ...layer,
      children: layer.children.map((child) => updateLayerPropertyById(child, layerId, patch)),
    };
  }

  if (layer.id !== layerId) {
    return layer;
  }

  return {
    ...layer,
    x: patch.x === undefined ? layer.x : finiteNumber(patch.x, layer.x),
    y: patch.y === undefined ? layer.y : finiteNumber(patch.y, layer.y),
    scaleX: patch.scale === undefined ? layer.scaleX : positiveNumber(patch.scale, layer.scaleX),
    scaleY: patch.scale === undefined ? layer.scaleY : positiveNumber(patch.scale, layer.scaleY),
    rotation: patch.rotation === undefined ? layer.rotation : finiteNumber(patch.rotation, layer.rotation),
    opacity: patch.opacity === undefined ? layer.opacity : clampOpacity(patch.opacity),
    visible: patch.visible ?? layer.visible,
    locked: patch.locked ?? layer.locked,
  } as Layer;
}

function updateGlyphOverrideById(layer: Layer, layerId: string, input: TextGlyphOverrideInput): Layer {
  if (layer.type === "group") {
    return {
      ...layer,
      children: layer.children.map((child) => updateGlyphOverrideById(child, layerId, input)),
    };
  }

  if (layer.id !== layerId) {
    return layer;
  }

  if (layer.type !== "text") {
    throw new Error("Glyph overrides can only be applied to text layers");
  }

  const chars = Array.from(layer.text);
  if (!Number.isInteger(input.index) || input.index < 0 || input.index >= chars.length) {
    throw new Error("Glyph override index is outside the text layer");
  }

  if (!input.replacement) {
    throw new Error("Glyph override replacement must not be empty");
  }

  const nextOverride: GlyphOverride = {
    index: input.index,
    originalText: chars[input.index],
    replacement: input.replacement,
    codepoint: input.codepoint,
    glyphName: input.glyphName,
  };
  const nextOverrides = [
    ...(layer.glyphOverrides ?? []).filter((override) => override.index !== input.index),
    nextOverride,
  ].sort((left, right) => left.index - right.index);

  return {
    ...layer,
    glyphOverrides: nextOverrides,
  };
}

function updateTextContentById(layer: Layer, layerId: string, text: string): Layer {
  if (layer.type === "group") {
    return {
      ...layer,
      children: layer.children.map((child) => updateTextContentById(child, layerId, text)),
    };
  }

  if (layer.id !== layerId) {
    return layer;
  }

  if (layer.type !== "text") {
    throw new Error("Text content updates can only be applied to text layers");
  }

  const chars = Array.from(text);
  const glyphOverrides = (layer.glyphOverrides ?? []).filter(
    (override) => chars[override.index] === override.originalText,
  );

  return {
    ...layer,
    text,
    glyphOverrides,
  };
}

function updateTextFontById(layer: Layer, layerId: string, font: TextLayerFontInput): Layer {
  if (layer.type === "group") {
    return {
      ...layer,
      children: layer.children.map((child) => updateTextFontById(child, layerId, font)),
    };
  }

  if (layer.id !== layerId) {
    return layer;
  }

  if (layer.type !== "text") {
    throw new Error("Font updates can only be applied to text layers");
  }

  const family = font.family.trim();
  if (!family) {
    throw new Error("Font family must not be empty");
  }

  return {
    ...layer,
    fontRef: {
      ...layer.fontRef,
      family,
      source: font.source ?? layer.fontRef.source,
      assetId: font.assetId ?? layer.fontRef.assetId,
      fallbackFamilies: font.fallbackFamilies ?? layer.fontRef.fallbackFamilies,
    },
  };
}

function finiteNumber(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
}

function positiveNumber(value: number, fallback: number): number {
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function clampOpacity(value: number): number {
  if (!Number.isFinite(value)) {
    return 1;
  }

  return Math.min(1, Math.max(0, value));
}
