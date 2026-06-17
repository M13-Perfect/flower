import {
  type CanvasSpec,
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
  font?: TextLayerFontInput;
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
    layers: document.layers.map((layer) => updateLayerFromSnapshot(layer, snapshotsById, document.canvas)),
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
    layers: document.layers.map((layer) => updateLayerPropertyById(layer, layerId, patch, document.canvas)),
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

    if (containsUnicodeControlCharacter(override.replacement) || isControlCodepointString(override.codepoint)) {
      continue;
    }

    chars[override.index] = override.replacement;
  }

  return chars.join("");
}

function containsUnicodeControlCharacter(value: string): boolean {
  return Array.from(value).some((char) => isControlCodepoint(char.codePointAt(0) ?? -1));
}

function isControlCodepointString(value: string | undefined): boolean {
  if (!value) {
    return false;
  }
  const match = value.trim().match(/^(?:U\+|0x)?([0-9a-f]{4,6})$/i);
  return match ? isControlCodepoint(Number.parseInt(match[1], 16)) : false;
}

function isControlCodepoint(codepoint: number): boolean {
  return (codepoint >= 0x0000 && codepoint <= 0x001f) || (codepoint >= 0x007f && codepoint <= 0x009f);
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
  canvas: CanvasSpec,
): Layer {
  if (layer.type === "group") {
    return {
      ...layer,
      children: layer.children.map((child) => updateLayerFromSnapshot(child, snapshotsById, canvas)),
    };
  }

  const snapshot = snapshotsById.get(layer.id);
  if (!snapshot) {
    return layer;
  }

  const nextScale = constrainLayerScale(
    canvas,
    layer,
    positiveNumber(snapshot.scaleX, layer.scaleX),
    positiveNumber(snapshot.scaleY, layer.scaleY),
  );
  const nextPosition = constrainLayerPosition(
    canvas,
    layer,
    finiteNumber(snapshot.left, layer.x),
    finiteNumber(snapshot.top, layer.y),
    nextScale.scaleX,
    nextScale.scaleY,
  );

  return {
    ...layer,
    x: nextPosition.x,
    y: nextPosition.y,
    width: positiveNumber(snapshot.width, layer.width),
    height: positiveNumber(snapshot.height, layer.height),
    scaleX: nextScale.scaleX,
    scaleY: nextScale.scaleY,
    rotation: finiteNumber(snapshot.angle, layer.rotation),
    opacity: clampOpacity(snapshot.opacity),
    visible: snapshot.visible,
    locked: snapshot.locked,
  } as Layer;
}

function updateLayerPropertyById(
  layer: Layer,
  layerId: string,
  patch: LayerPropertyPatch,
  canvas: CanvasSpec,
): Layer {
  if (layer.type === "group") {
    return {
      ...layer,
      children: layer.children.map((child) => updateLayerPropertyById(child, layerId, patch, canvas)),
    };
  }

  if (layer.id !== layerId) {
    return layer;
  }

  const proposedScaleX = patch.scale === undefined ? layer.scaleX : positiveNumber(patch.scale, layer.scaleX);
  const proposedScaleY = patch.scale === undefined ? layer.scaleY : positiveNumber(patch.scale, layer.scaleY);
  const nextScale =
    patch.scale === undefined
      ? constrainLayerScale(canvas, layer, proposedScaleX, proposedScaleY)
      : constrainLayerUniformScale(canvas, layer, Math.min(proposedScaleX, proposedScaleY));
  const nextPosition = constrainLayerPosition(
    canvas,
    layer,
    patch.x === undefined ? layer.x : finiteNumber(patch.x, layer.x),
    patch.y === undefined ? layer.y : finiteNumber(patch.y, layer.y),
    nextScale.scaleX,
    nextScale.scaleY,
  );

  return {
    ...layer,
    x: nextPosition.x,
    y: nextPosition.y,
    scaleX: nextScale.scaleX,
    scaleY: nextScale.scaleY,
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
  if (containsUnicodeControlCharacter(input.replacement) || isControlCodepointString(input.codepoint)) {
    throw new Error("Glyph override replacement must not be a Unicode control character");
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
    fontRef: input.font ? createTextFontReference(layer, input.font) : layer.fontRef,
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
    fontRef: createTextFontReference(layer, font),
  };
}

function createTextFontReference(layer: TextLayer, font: TextLayerFontInput): FontReference {
  const family = font.family.trim();
  if (!family) {
    throw new Error("Font family must not be empty");
  }

  return {
    ...layer.fontRef,
    family,
    source: font.source ?? layer.fontRef.source,
    assetId: font.assetId ?? layer.fontRef.assetId,
    fallbackFamilies: font.fallbackFamilies ?? layer.fontRef.fallbackFamilies,
  };
}

function finiteNumber(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
}

function positiveNumber(value: number, fallback: number): number {
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function constrainLayerScale(
  canvas: CanvasSpec,
  layer: Exclude<Layer, { type: "group" }>,
  scaleX: number,
  scaleY: number,
) {
  // 业务规则：编辑态图层必须完整留在画布内，避免桌面端导出出现意外裁切。
  const maxScaleX = maxLayerScale(canvas.width, layer.width);
  const maxScaleY = maxLayerScale(canvas.height, layer.height);

  return {
    scaleX: Math.min(scaleX, maxScaleX),
    scaleY: Math.min(scaleY, maxScaleY),
  };
}

function constrainLayerUniformScale(
  canvas: CanvasSpec,
  layer: Exclude<Layer, { type: "group" }>,
  scale: number,
) {
  const nextScale = Math.min(
    scale,
    maxLayerScale(canvas.width, layer.width),
    maxLayerScale(canvas.height, layer.height),
  );

  return {
    scaleX: nextScale,
    scaleY: nextScale,
  };
}

function maxLayerScale(canvasSize: number, layerSize: number): number {
  return Math.max(0.001, positiveNumber(canvasSize, 1) / positiveNumber(layerSize, 1));
}

function constrainLayerPosition(
  canvas: CanvasSpec,
  layer: Exclude<Layer, { type: "group" }>,
  x: number,
  y: number,
  scaleX: number,
  scaleY: number,
) {
  const scaledWidth = positiveNumber(layer.width * scaleX, layer.width);
  const scaledHeight = positiveNumber(layer.height * scaleY, layer.height);
  return {
    x: clampNumber(x, 0, Math.max(0, canvas.width - scaledWidth)),
    y: clampNumber(y, 0, Math.max(0, canvas.height - scaledHeight)),
  };
}

function clampNumber(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.min(max, Math.max(min, value));
}

function clampOpacity(value: number): number {
  if (!Number.isFinite(value)) {
    return 1;
  }

  return Math.min(1, Math.max(0, value));
}
