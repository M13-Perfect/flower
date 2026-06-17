export const LAYER_DOCUMENT_SCHEMA_VERSION = "1.0" as const;
export const TEMPLATE_SCHEMA_VERSION = "1.0" as const;
export const EXPORT_SETTINGS_SCHEMA_VERSION = "1.0" as const;

export type CanvasUnit = "px" | "mm" | "in";
export type LayerKind = "text" | "image" | "svg" | "path" | "group";
export type ExportFormat = "svg" | "png" | "dxf";

export interface SolidCanvasBackground {
  type: "solid";
  color: string;
}

export interface TransparentCanvasBackground {
  type: "transparent";
}

export type CanvasBackground = SolidCanvasBackground | TransparentCanvasBackground;

export interface CanvasSpec {
  width: number;
  height: number;
  unit: CanvasUnit;
  background: CanvasBackground;
}

export interface AssetReference {
  assetId: string;
  path: string;
  checksum?: string;
}

export interface SizeSpec {
  width: number;
  height: number;
}

export interface RectSpec extends SizeSpec {
  x: number;
  y: number;
}

export interface LayerBase {
  id: string;
  type: LayerKind;
  name: string;
  visible: boolean;
  locked: boolean;
  exportable: true;
  zIndex: number;
  opacity: number;
  x: number;
  y: number;
  width: number;
  height: number;
  scaleX: number;
  scaleY: number;
  rotation: number;
  slotId?: string;
  tags: string[];
}

export interface FontReference {
  family: string;
  source?: "system" | "asset";
  assetId?: string;
  fallbackFamilies?: string[];
}

export interface TextStyle {
  fontSize: number;
  fill: string;
  stroke?: string;
  strokeWidth?: number;
  align: "left" | "center" | "right";
  lineHeight: number;
  letterSpacing: number;
}

export interface TextLayout {
  mode: "point" | "box";
  overflow: "clip" | "shrink-to-fit" | "wrap";
}

export interface GlyphOverride {
  index: number;
  originalText: string;
  replacement: string;
  codepoint?: string;
  glyphName?: string;
}

export interface TextLayer extends LayerBase {
  type: "text";
  text: string;
  fontRef: FontReference;
  style: TextStyle;
  layout: TextLayout;
  glyphOverrides?: GlyphOverride[];
}

export interface ImageLayer extends LayerBase {
  type: "image";
  assetRef: AssetReference;
  intrinsicSize: SizeSpec;
  fit: "contain" | "cover" | "stretch" | "none";
}

export interface SvgLayer extends LayerBase {
  type: "svg";
  assetRef?: AssetReference;
  inlineSvg?: string;
  viewBox: RectSpec;
  preserveVector: true;
}

export interface PathLayer extends LayerBase {
  type: "path";
  pathData: string;
  fill?: string;
  stroke?: string;
  strokeWidth?: number;
}

export interface GroupLayer extends LayerBase {
  type: "group";
  children: Layer[];
}

export type Layer = TextLayer | ImageLayer | SvgLayer | PathLayer | GroupLayer;

export interface LayerDocumentMetadata {
  orderId?: string;
  templateId: string;
  templateVersion?: string;
  appVersion: string;
  createdAt: string;
  updatedAt: string;
}

export interface SvgExportSettings {
  preserveText: boolean;
  preserveVector: boolean;
  includeMetadata: boolean;
}

export interface PngExportSettings {
  scale: number;
  background: "canvas" | "transparent";
}

export interface DxfExportSettings {
  textMode: "paths";
  units: CanvasUnit;
}

export interface ExportSettings {
  schemaVersion: typeof EXPORT_SETTINGS_SCHEMA_VERSION;
  defaultFormats: ExportFormat[];
  svg: SvgExportSettings;
  png: PngExportSettings;
  dxf: DxfExportSettings;
}

export interface LayerDocument {
  schemaVersion: typeof LAYER_DOCUMENT_SCHEMA_VERSION;
  documentId: string;
  projectId: string;
  jobId: string;
  metadata: LayerDocumentMetadata;
  canvas: CanvasSpec;
  exportSettings: ExportSettings;
  layers: Layer[];
}

export interface TemplateSlot {
  slotId: string;
  kind: LayerKind;
  required: boolean;
}

export interface TemplateDocument {
  schemaVersion: typeof TEMPLATE_SCHEMA_VERSION;
  templateId: string;
  version: string;
  productType: string;
  displayName: string;
  canvas: CanvasSpec;
  slots: TemplateSlot[];
}

export interface CreateEmptyLayerDocumentInput {
  documentId: string;
  projectId: string;
  jobId: string;
  templateId: string;
  width: number;
  height: number;
}

export interface ValidationResult {
  ok: boolean;
  errors: string[];
}

const UI_ONLY_KEYS = new Set([
  "activeTool",
  "debugBounds",
  "editorState",
  "guides",
  "handles",
  "hoveredLayerId",
  "pan",
  "selection",
  "selectedLayerIds",
  "snapLines",
  "viewport",
  "zoom",
]);

export function createEmptyLayerDocument(input: CreateEmptyLayerDocumentInput): LayerDocument {
  const timestamp = new Date().toISOString();

  return {
    schemaVersion: LAYER_DOCUMENT_SCHEMA_VERSION,
    documentId: input.documentId,
    projectId: input.projectId,
    jobId: input.jobId,
    metadata: {
      templateId: input.templateId,
      appVersion: "0.1.0",
      createdAt: timestamp,
      updatedAt: timestamp,
    },
    canvas: {
      width: input.width,
      height: input.height,
      unit: "px",
      background: {
        type: "solid",
        color: "#ffffff",
      },
    },
    exportSettings: createDefaultExportSettings(),
    layers: [],
  };
}

export function createDefaultExportSettings(): ExportSettings {
  return {
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
  };
}

export function validateLayerDocument(value: unknown): ValidationResult {
  const errors: string[] = [];

  if (!isRecord(value)) {
    return { ok: false, errors: ["document must be an object"] };
  }

  rejectUiOnlyKeys(value, "document", errors);
  requireLiteral(value.schemaVersion, LAYER_DOCUMENT_SCHEMA_VERSION, "document.schemaVersion", errors);
  requireString(value.documentId, "document.documentId", errors);
  requireString(value.projectId, "document.projectId", errors);
  requireString(value.jobId, "document.jobId", errors);
  validateMetadata(value.metadata, errors);
  validateCanvas(value.canvas, "document.canvas", errors);
  validateExportSettings(value.exportSettings, errors);

  if (!Array.isArray(value.layers)) {
    errors.push("document.layers must be an array");
  } else {
    value.layers.forEach((layer, index) => validateLayer(layer, `layers[${index}]`, errors));
  }

  return { ok: errors.length === 0, errors };
}

export function isLayerDocument(value: unknown): value is LayerDocument {
  return validateLayerDocument(value).ok;
}

export function isTemplateDocument(value: unknown): value is TemplateDocument {
  if (!isRecord(value)) {
    return false;
  }

  return (
    value.schemaVersion === TEMPLATE_SCHEMA_VERSION &&
    typeof value.templateId === "string" &&
    value.templateId.length > 0 &&
    typeof value.version === "string" &&
    value.version.length > 0 &&
    typeof value.productType === "string" &&
    value.productType.length > 0 &&
    typeof value.displayName === "string" &&
    value.displayName.length > 0 &&
    isCanvasSpec(value.canvas) &&
    Array.isArray(value.slots)
  );
}

function validateMetadata(value: unknown, errors: string[]) {
  if (!isRecord(value)) {
    errors.push("document.metadata must be an object");
    return;
  }

  requireOptionalString(value.orderId, "document.metadata.orderId", errors);
  requireString(value.templateId, "document.metadata.templateId", errors);
  requireOptionalString(value.templateVersion, "document.metadata.templateVersion", errors);
  requireString(value.appVersion, "document.metadata.appVersion", errors);
  requireString(value.createdAt, "document.metadata.createdAt", errors);
  requireString(value.updatedAt, "document.metadata.updatedAt", errors);
}

function validateCanvas(value: unknown, path: string, errors: string[]) {
  if (!isRecord(value)) {
    errors.push(`${path} must be an object`);
    return;
  }

  requirePositiveNumber(value.width, `${path}.width`, errors);
  requirePositiveNumber(value.height, `${path}.height`, errors);
  validateUnit(value.unit, `${path}.unit`, errors);
  validateCanvasBackground(value.background, `${path}.background`, errors);
}

function validateCanvasBackground(value: unknown, path: string, errors: string[]) {
  if (!isRecord(value)) {
    errors.push(`${path} must be an object`);
    return;
  }

  if (value.type === "solid") {
    requireString(value.color, `${path}.color`, errors);
    return;
  }

  if (value.type !== "transparent") {
    errors.push(`${path}.type must be solid or transparent`);
  }
}

function validateExportSettings(value: unknown, errors: string[]) {
  if (!isRecord(value)) {
    errors.push("document.exportSettings must be an object");
    return;
  }

  requireLiteral(
    value.schemaVersion,
    EXPORT_SETTINGS_SCHEMA_VERSION,
    "document.exportSettings.schemaVersion",
    errors,
  );

  if (!Array.isArray(value.defaultFormats) || value.defaultFormats.length === 0) {
    errors.push("document.exportSettings.defaultFormats must be a non-empty array");
  } else {
    value.defaultFormats.forEach((format, index) => {
      if (!isExportFormat(format)) {
        errors.push(`document.exportSettings.defaultFormats[${index}] must be svg, png, or dxf`);
      }
    });
  }

  validateSvgExport(value.svg, errors);
  validatePngExport(value.png, errors);
  validateDxfExport(value.dxf, errors);
}

function validateSvgExport(value: unknown, errors: string[]) {
  if (!isRecord(value)) {
    errors.push("document.exportSettings.svg must be an object");
    return;
  }

  requireBoolean(value.preserveText, "document.exportSettings.svg.preserveText", errors);
  requireBoolean(value.preserveVector, "document.exportSettings.svg.preserveVector", errors);
  requireBoolean(value.includeMetadata, "document.exportSettings.svg.includeMetadata", errors);
}

function validatePngExport(value: unknown, errors: string[]) {
  if (!isRecord(value)) {
    errors.push("document.exportSettings.png must be an object");
    return;
  }

  requirePositiveNumber(value.scale, "document.exportSettings.png.scale", errors);
  if (value.background !== "canvas" && value.background !== "transparent") {
    errors.push("document.exportSettings.png.background must be canvas or transparent");
  }
}

function validateDxfExport(value: unknown, errors: string[]) {
  if (!isRecord(value)) {
    errors.push("document.exportSettings.dxf must be an object");
    return;
  }

  requireLiteral(value.textMode, "paths", "document.exportSettings.dxf.textMode", errors);
  validateUnit(value.units, "document.exportSettings.dxf.units", errors);
}

function validateLayer(value: unknown, path: string, errors: string[]) {
  if (!isRecord(value)) {
    errors.push(`${path} must be an object`);
    return;
  }

  rejectUiOnlyKeys(value, path, errors);

  if (value.exportable !== true) {
    errors.push(`${path} must be exportable document state`);
  }

  requireString(value.id, `${path}.id`, errors);
  requireString(value.name, `${path}.name`, errors);
  requireBoolean(value.visible, `${path}.visible`, errors);
  requireBoolean(value.locked, `${path}.locked`, errors);
  requireNumber(value.zIndex, `${path}.zIndex`, errors);
  requireNumberInRange(value.opacity, `${path}.opacity`, 0, 1, errors);
  validateLayerGeometry(value, path, errors);

  if (value.slotId !== undefined) {
    requireString(value.slotId, `${path}.slotId`, errors);
  }

  if (!Array.isArray(value.tags) || !value.tags.every((tag) => typeof tag === "string")) {
    errors.push(`${path}.tags must be an array of strings`);
  }

  if (value.type === "text") {
    validateTextLayer(value, path, errors);
    return;
  }

  if (value.type === "image") {
    validateImageLayer(value, path, errors);
    return;
  }

  if (value.type === "svg") {
    validateSvgLayer(value, path, errors);
    return;
  }

  if (value.type === "path") {
    validatePathLayer(value, path, errors);
    return;
  }

  if (value.type === "group") {
    validateGroupLayer(value, path, errors);
    return;
  }

  errors.push(`${path}.type must be text, image, svg, path, or group`);
}

function validateLayerGeometry(value: Record<string, unknown>, path: string, errors: string[]) {
  requireNumber(value.x, `${path}.x`, errors);
  requireNumber(value.y, `${path}.y`, errors);
  requirePositiveNumber(value.width, `${path}.width`, errors);
  requirePositiveNumber(value.height, `${path}.height`, errors);
  requireNumber(value.rotation, `${path}.rotation`, errors);
  requirePositiveNumber(value.scaleX, `${path}.scaleX`, errors);
  requirePositiveNumber(value.scaleY, `${path}.scaleY`, errors);
}

function validateTextLayer(value: Record<string, unknown>, path: string, errors: string[]) {
  requireString(value.text, `${path}.text`, errors);
  validateFontRef(value.fontRef, `${path}.fontRef`, errors);
  validateTextStyle(value.style, `${path}.style`, errors);
  validateTextLayout(value.layout, `${path}.layout`, errors);

  if (Array.isArray(value.glyphOverrides)) {
    value.glyphOverrides.forEach((override, index) =>
      validateGlyphOverride(override, `${path}.glyphOverrides[${index}]`, errors),
    );
  } else if (value.glyphOverrides !== undefined) {
    errors.push(`${path}.glyphOverrides must be an array`);
  }
}

function validateFontRef(value: unknown, path: string, errors: string[]) {
  if (!isRecord(value)) {
    errors.push(`${path} must be an object`);
    return;
  }

  requireString(value.family, `${path}.family`, errors);

  if (value.source !== undefined && value.source !== "system" && value.source !== "asset") {
    errors.push(`${path}.source must be system or asset`);
  }

  requireOptionalString(value.assetId, `${path}.assetId`, errors);

  if (
    value.fallbackFamilies !== undefined &&
    (!Array.isArray(value.fallbackFamilies) ||
      !value.fallbackFamilies.every((family) => typeof family === "string" && family.length > 0))
  ) {
    errors.push(`${path}.fallbackFamilies must be an array of non-empty strings`);
  }
}

function validateTextStyle(value: unknown, path: string, errors: string[]) {
  if (!isRecord(value)) {
    errors.push(`${path} must be an object`);
    return;
  }

  requirePositiveNumber(value.fontSize, `${path}.fontSize`, errors);
  requireString(value.fill, `${path}.fill`, errors);
  requireOptionalString(value.stroke, `${path}.stroke`, errors);
  if (value.strokeWidth !== undefined) {
    requireNumber(value.strokeWidth, `${path}.strokeWidth`, errors);
  }
  if (value.align !== "left" && value.align !== "center" && value.align !== "right") {
    errors.push(`${path}.align must be left, center, or right`);
  }
  requirePositiveNumber(value.lineHeight, `${path}.lineHeight`, errors);
  requireNumber(value.letterSpacing, `${path}.letterSpacing`, errors);
}

function validateTextLayout(value: unknown, path: string, errors: string[]) {
  if (!isRecord(value)) {
    errors.push(`${path} must be an object`);
    return;
  }

  if (value.mode !== "point" && value.mode !== "box") {
    errors.push(`${path}.mode must be point or box`);
  }
  if (value.overflow !== "clip" && value.overflow !== "shrink-to-fit" && value.overflow !== "wrap") {
    errors.push(`${path}.overflow must be clip, shrink-to-fit, or wrap`);
  }
}

function validateGlyphOverride(value: unknown, path: string, errors: string[]) {
  if (!isRecord(value)) {
    errors.push(`${path} must be an object`);
    return;
  }

  requireNonNegativeInteger(value.index, `${path}.index`, errors);
  requireString(value.originalText, `${path}.originalText`, errors);
  requireString(value.replacement, `${path}.replacement`, errors);
  if (typeof value.replacement === "string" && containsUnicodeControlCharacter(value.replacement)) {
    errors.push(`${path}.replacement must not be a Unicode control character`);
  }
  requireOptionalString(value.codepoint, `${path}.codepoint`, errors);
  if (typeof value.codepoint === "string" && isControlCodepointString(value.codepoint)) {
    errors.push(`${path}.codepoint must not be a Unicode control character`);
  }
  requireOptionalString(value.glyphName, `${path}.glyphName`, errors);
}

function containsUnicodeControlCharacter(value: string): boolean {
  return Array.from(value).some((char) => isControlCodepoint(char.codePointAt(0) ?? -1));
}

function isControlCodepointString(value: string): boolean {
  const match = value.trim().match(/^(?:U\+|0x)?([0-9a-f]{4,6})$/i);
  return match ? isControlCodepoint(Number.parseInt(match[1], 16)) : false;
}

function isControlCodepoint(codepoint: number): boolean {
  return (codepoint >= 0x0000 && codepoint <= 0x001f) || (codepoint >= 0x007f && codepoint <= 0x009f);
}

function validateImageLayer(value: Record<string, unknown>, path: string, errors: string[]) {
  validateAssetRef(value.assetRef, `${path}.assetRef`, errors);
  validateSize(value.intrinsicSize, `${path}.intrinsicSize`, errors);

  if (value.fit !== "contain" && value.fit !== "cover" && value.fit !== "stretch" && value.fit !== "none") {
    errors.push(`${path}.fit must be contain, cover, stretch, or none`);
  }
}

function validateSvgLayer(value: Record<string, unknown>, path: string, errors: string[]) {
  if (value.assetRef === undefined && value.inlineSvg === undefined) {
    errors.push(`${path} must include assetRef or inlineSvg`);
  }
  if (value.assetRef !== undefined) {
    validateAssetRef(value.assetRef, `${path}.assetRef`, errors);
  }
  requireOptionalString(value.inlineSvg, `${path}.inlineSvg`, errors);
  validateRect(value.viewBox, `${path}.viewBox`, errors);
  requireLiteral(value.preserveVector, true, `${path}.preserveVector`, errors);
}

function validatePathLayer(value: Record<string, unknown>, path: string, errors: string[]) {
  requireString(value.pathData, `${path}.pathData`, errors);
  requireOptionalString(value.fill, `${path}.fill`, errors);
  requireOptionalString(value.stroke, `${path}.stroke`, errors);
  if (value.strokeWidth !== undefined) {
    requireNumber(value.strokeWidth, `${path}.strokeWidth`, errors);
  }
}

function validateGroupLayer(value: Record<string, unknown>, path: string, errors: string[]) {
  if (!Array.isArray(value.children)) {
    errors.push(`${path}.children must be an array`);
    return;
  }

  value.children.forEach((child, index) => validateLayer(child, `${path}.children[${index}]`, errors));
}

function validateAssetRef(value: unknown, path: string, errors: string[]) {
  if (!isRecord(value)) {
    errors.push(`${path} must be an object`);
    return;
  }

  requireString(value.assetId, `${path}.assetId`, errors);
  requireString(value.path, `${path}.path`, errors);
  requireOptionalString(value.checksum, `${path}.checksum`, errors);
}

function validateSize(value: unknown, path: string, errors: string[]) {
  if (!isRecord(value)) {
    errors.push(`${path} must be an object`);
    return;
  }

  requirePositiveNumber(value.width, `${path}.width`, errors);
  requirePositiveNumber(value.height, `${path}.height`, errors);
}

function validateRect(value: unknown, path: string, errors: string[]) {
  if (!isRecord(value)) {
    errors.push(`${path} must be an object`);
    return;
  }

  requireNumber(value.x, `${path}.x`, errors);
  requireNumber(value.y, `${path}.y`, errors);
  requirePositiveNumber(value.width, `${path}.width`, errors);
  requirePositiveNumber(value.height, `${path}.height`, errors);
}

function isCanvasSpec(value: unknown): value is CanvasSpec {
  const errors: string[] = [];
  validateCanvas(value, "canvas", errors);
  return errors.length === 0;
}

function rejectUiOnlyKeys(value: Record<string, unknown>, path: string, errors: string[]) {
  for (const key of Object.keys(value)) {
    if (UI_ONLY_KEYS.has(key)) {
      errors.push(`${path}.${key} is UI-only state`);
    }
  }
}

function requireString(value: unknown, path: string, errors: string[]) {
  if (typeof value !== "string" || value.length === 0) {
    errors.push(`${path} must not be empty`);
  }
}

function requireOptionalString(value: unknown, path: string, errors: string[]) {
  if (value !== undefined && (typeof value !== "string" || value.length === 0)) {
    errors.push(`${path} must not be empty`);
  }
}

function requireNumber(value: unknown, path: string, errors: string[]) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    errors.push(`${path} must be a finite number`);
  }
}

function requirePositiveNumber(value: unknown, path: string, errors: string[]) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    errors.push(`${path} must be a positive number`);
  }
}

function requireNumberInRange(
  value: unknown,
  path: string,
  min: number,
  max: number,
  errors: string[],
) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < min || value > max) {
    errors.push(`${path} must be between ${min} and ${max}`);
  }
}

function requireNonNegativeInteger(value: unknown, path: string, errors: string[]) {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    errors.push(`${path} must be a non-negative integer`);
  }
}

function requireBoolean(value: unknown, path: string, errors: string[]) {
  if (typeof value !== "boolean") {
    errors.push(`${path} must be a boolean`);
  }
}

function requireLiteral<T>(value: unknown, expected: T, path: string, errors: string[]) {
  if (value !== expected) {
    errors.push(`${path} must be ${String(expected)}`);
  }
}

function validateUnit(value: unknown, path: string, errors: string[]) {
  if (value !== "px" && value !== "mm" && value !== "in") {
    errors.push(`${path} must be px, mm, or in`);
  }
}

function isExportFormat(value: unknown): value is ExportFormat {
  return value === "svg" || value === "png" || value === "dxf";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
