import {
  validateLayerDocument,
  type GroupLayer,
  type ImageLayer,
  type Layer,
  type LayerDocument,
  type PathLayer,
  type SvgLayer,
  type TextLayer,
} from "@flower/design-core";

export type ExportBackground = "canvas" | "transparent";

export interface ExportMetadata {
  templateId: string;
  orderId: string;
  exportedAt: string;
  appVersion: string;
}

export interface SvgExportOptions {
  background?: ExportBackground;
  exportedAt?: string;
}

export interface SvgExportFile {
  fileName: string;
  mimeType: "image/svg+xml";
  content: string;
  metadata: ExportMetadata;
}

export interface PngRasterizeInput {
  svg: string;
  width: number;
  height: number;
  scale: number;
  background: ExportBackground;
}

export type PngRasterizer = (input: PngRasterizeInput) => Promise<string>;

export interface PngExportOptions {
  background?: ExportBackground;
  exportedAt?: string;
  rasterize?: PngRasterizer;
  scale?: number;
}

export interface PngExportFile {
  fileName: string;
  mimeType: "image/png";
  dataUrl: string;
  bytes: Uint8Array;
  width: number;
  height: number;
  metadata: ExportMetadata;
}

const PNG_METADATA_KEYWORD = "flower-export-metadata";
const PNG_SIGNATURE = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]);
const HELPER_LAYER_MARKERS = new Set([
  "debug",
  "debug-bounds",
  "editor-overlay",
  "guide",
  "guides",
  "handle",
  "handles",
  "selection",
  "selection-box",
  "selection-handle",
  "selection_box",
  "selection_handle",
  "snap-line",
  "snap-lines",
]);

export function createSvgExport(document: LayerDocument, options: SvgExportOptions = {}): SvgExportFile {
  assertValidDocument(document);

  const exportedAt = options.exportedAt ?? new Date().toISOString();
  const metadata = createExportMetadata(document, exportedAt);
  const background = options.background ?? defaultSvgBackground(document);

  return {
    fileName: createExportFileName(metadata, "svg"),
    mimeType: "image/svg+xml",
    content: buildSvg(document, metadata, background),
    metadata,
  };
}

export async function createPngExport(
  document: LayerDocument,
  options: PngExportOptions = {},
): Promise<PngExportFile> {
  assertValidDocument(document);

  const exportedAt = options.exportedAt ?? new Date().toISOString();
  const metadata = createExportMetadata(document, exportedAt);
  const background = options.background ?? document.exportSettings.png.background;
  const scale = normalizeScale(options.scale ?? document.exportSettings.png.scale);
  const width = Math.round(document.canvas.width * scale);
  const height = Math.round(document.canvas.height * scale);
  const svg = createSvgExport(document, { background, exportedAt }).content;
  const rasterize = options.rasterize ?? rasterizeSvgToPng;
  const rawDataUrl = await rasterize({ svg, width, height, scale, background });
  const rawBytes = dataUrlToPngBytes(rawDataUrl);
  const bytes = writePngTextMetadata(rawBytes, PNG_METADATA_KEYWORD, JSON.stringify(metadata));

  return {
    fileName: createExportFileName(metadata, "png"),
    mimeType: "image/png",
    dataUrl: pngBytesToDataUrl(bytes),
    bytes,
    width,
    height,
    metadata,
  };
}

export function readPngTextMetadata(bytes: Uint8Array, keyword: string): string | null {
  assertPngSignature(bytes);

  let offset = PNG_SIGNATURE.length;
  while (offset + 12 <= bytes.length) {
    const length = readUint32(bytes, offset);
    const type = asciiFromBytes(bytes.slice(offset + 4, offset + 8));
    const dataStart = offset + 8;
    const dataEnd = dataStart + length;

    if (dataEnd + 4 > bytes.length) {
      throw new Error("PNG chunk length exceeds file size");
    }

    const data = bytes.slice(dataStart, dataEnd);
    if (type === "tEXt") {
      const separator = data.indexOf(0);
      if (separator > -1 && asciiFromBytes(data.slice(0, separator)) === keyword) {
        return asciiFromBytes(data.slice(separator + 1));
      }
    }

    if (type === "iTXt") {
      const text = readInternationalTextChunk(data, keyword);
      if (text !== null) {
        return text;
      }
    }

    offset = dataEnd + 4;
  }

  return null;
}

export function downloadTextFile(content: string, fileName: string, mimeType: string) {
  const blob = new Blob([content], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  triggerDownload(url, fileName);
  URL.revokeObjectURL(url);
}

export function downloadDataUrl(dataUrl: string, fileName: string) {
  triggerDownload(dataUrl, fileName);
}

function buildSvg(
  document: LayerDocument,
  metadata: ExportMetadata,
  background: ExportBackground,
): string {
  const layers = flattenRenderableLayers(document.layers)
    .sort((left, right) => left.zIndex - right.zIndex)
    .map(renderLayer)
    .filter((content) => content.length > 0);
  const backgroundRect =
    background === "canvas" && document.canvas.background.type === "solid"
      ? [
          `<rect width="${formatNumber(document.canvas.width)}" height="${formatNumber(
            document.canvas.height,
          )}" fill="${escapeAttribute(document.canvas.background.color)}" data-export-background="canvas"/>`,
        ]
      : [];

  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    `<svg xmlns="http://www.w3.org/2000/svg" width="${formatNumber(
      document.canvas.width,
    )}" height="${formatNumber(document.canvas.height)}" viewBox="0 0 ${formatNumber(
      document.canvas.width,
    )} ${formatNumber(document.canvas.height)}">`,
    `  <metadata id="flower-export-metadata">${escapeText(JSON.stringify(metadata))}</metadata>`,
    ...backgroundRect.map((line) => `  ${line}`),
    ...layers.map((line) => indentBlock(line, "  ")),
    "</svg>",
  ].join("\n");
}

function renderLayer(layer: Layer): string {
  if (layer.type === "text") {
    return renderTextLayer(layer);
  }

  if (layer.type === "image") {
    return renderImageLayer(layer);
  }

  if (layer.type === "svg") {
    return renderSvgLayer(layer);
  }

  if (layer.type === "path") {
    return renderPathLayer(layer);
  }

  return renderGroupLayer(layer);
}

function renderTextLayer(layer: TextLayer): string {
  const text = buildTextWithGlyphOverrides(layer);
  const anchor = textAnchor(layer.style.align);
  const textX = alignedTextX(layer);
  const lines = text.split(/\r\n|\n|\r/);
  const tspans = lines
    .map((line, index) => {
      const dy = index === 0 ? 0 : layer.style.fontSize * layer.style.lineHeight;
      return `<tspan x="${formatNumber(textX)}" dy="${formatNumber(dy)}">${escapeText(line)}</tspan>`;
    })
    .join("");
  const attrs = [
    `font-family="${escapeAttribute(layer.fontRef.family)}"`,
    `font-size="${formatNumber(layer.style.fontSize)}"`,
    `fill="${escapeAttribute(layer.style.fill)}"`,
    `text-anchor="${anchor}"`,
    'dominant-baseline="text-before-edge"',
    layer.style.letterSpacing ? `letter-spacing="${formatNumber(layer.style.letterSpacing)}"` : "",
    layer.style.stroke ? `stroke="${escapeAttribute(layer.style.stroke)}"` : "",
    layer.style.strokeWidth !== undefined ? `stroke-width="${formatNumber(layer.style.strokeWidth)}"` : "",
  ].filter(Boolean);

  return wrapLayer(
    layer,
    `<text x="0" y="0" ${attrs.join(" ")} data-layer-id="${escapeAttribute(layer.id)}">${tspans}</text>`,
  );
}

function renderImageLayer(layer: ImageLayer): string {
  return wrapLayer(
    layer,
    `<image width="${formatNumber(layer.width)}" height="${formatNumber(layer.height)}" href="${escapeAttribute(
      layer.assetRef.path,
    )}" preserveAspectRatio="${imagePreserveAspectRatio(layer.fit)}" data-layer-id="${escapeAttribute(
      layer.id,
    )}"/>`,
  );
}

function renderSvgLayer(layer: SvgLayer): string {
  if (!layer.inlineSvg) {
    return wrapLayer(
      layer,
      `<image width="${formatNumber(layer.width)}" height="${formatNumber(layer.height)}" href="${escapeAttribute(
        layer.assetRef?.path ?? "",
      )}" preserveAspectRatio="xMidYMid meet" data-layer-id="${escapeAttribute(layer.id)}"/>`,
    );
  }

  const inlineSvg = parseInlineSvg(layer);
  return wrapLayer(
    layer,
    [
      `<svg width="${formatNumber(layer.width)}" height="${formatNumber(
        layer.height,
      )}" viewBox="${escapeAttribute(inlineSvg.viewBox)}" preserveAspectRatio="xMidYMid meet" data-layer-id="${escapeAttribute(
        layer.id,
      )}">`,
      indentBlock(inlineSvg.inner, "  "),
      "</svg>",
    ].join("\n"),
  );
}

function renderPathLayer(layer: PathLayer): string {
  const attrs = [
    `d="${escapeAttribute(layer.pathData)}"`,
    `fill="${escapeAttribute(layer.fill ?? "none")}"`,
    layer.stroke ? `stroke="${escapeAttribute(layer.stroke)}"` : "",
    layer.strokeWidth !== undefined ? `stroke-width="${formatNumber(layer.strokeWidth)}"` : "",
    `data-layer-id="${escapeAttribute(layer.id)}"`,
  ].filter(Boolean);

  return wrapLayer(layer, `<path ${attrs.join(" ")}/>`);
}

function renderGroupLayer(layer: GroupLayer): string {
  const children = flattenRenderableLayers(layer.children)
    .sort((left, right) => left.zIndex - right.zIndex)
    .map(renderLayer)
    .filter((content) => content.length > 0);

  if (children.length === 0) {
    return "";
  }

  return wrapLayer(layer, children.map((child) => indentBlock(child, "  ")).join("\n"));
}

function wrapLayer(layer: Layer, content: string): string {
  const attrs = [
    `id="${escapeAttribute(layer.id)}"`,
    `data-layer-name="${escapeAttribute(layer.name)}"`,
    `transform="${escapeAttribute(layerTransform(layer))}"`,
    layer.opacity < 1 ? `opacity="${formatNumber(layer.opacity)}"` : "",
  ].filter(Boolean);

  return [`<g ${attrs.join(" ")}>`, indentBlock(content, "  "), "</g>"].join("\n");
}

function flattenRenderableLayers(layers: readonly Layer[]): Layer[] {
  return layers.filter((layer) => {
    if (!layer.visible || layer.exportable !== true) {
      return false;
    }

    // 业务规则：即使误把选中框/辅助线/调试框写成 exportable，也不能进入生产导出。
    return !isEditorHelperLayer(layer);
  });
}

function isEditorHelperLayer(layer: Layer): boolean {
  const markers = [layer.name, ...layer.tags].map((value) => value.trim().toLowerCase());
  return markers.some((marker) => HELPER_LAYER_MARKERS.has(marker));
}

function parseInlineSvg(layer: SvgLayer): { inner: string; viewBox: string } {
  const sanitized = stripUnsafeSvgMarkup(layer.inlineSvg ?? "").trim();
  const match = sanitized.match(/<svg\b([^>]*)>([\s\S]*?)<\/svg>/i);
  const fallbackViewBox = `${formatNumber(layer.viewBox.x)} ${formatNumber(layer.viewBox.y)} ${formatNumber(
    layer.viewBox.width,
  )} ${formatNumber(layer.viewBox.height)}`;

  if (!match) {
    return {
      inner: sanitized,
      viewBox: fallbackViewBox,
    };
  }

  const viewBoxMatch = match[1].match(/\sviewBox=(["'])(.*?)\1/i);
  return {
    inner: match[2].trim(),
    viewBox: viewBoxMatch?.[2] ?? fallbackViewBox,
  };
}

function stripUnsafeSvgMarkup(svg: string): string {
  return svg
    .replace(/<\?xml[\s\S]*?\?>/gi, "")
    .replace(/<!doctype[\s\S]*?>/gi, "")
    .replace(/<script\b[\s\S]*?<\/script>/gi, "")
    // 真实花朵素材会带 serif/xml 等设计软件命名空间属性；抽出内层 SVG 后这些前缀可能失去声明，导致浏览器 PNG 栅格化失败。
    .replace(/\s(?:xmlns:[a-z][\w.-]*|[a-z][\w.-]*:[\w.-]+)\s*=\s*(?:"[^"]*"|'[^']*')/gi, "")
    .replace(/\son[a-z]+\s*=\s*(?:"[^"]*"|'[^']*')/gi, "");
}

function buildTextWithGlyphOverrides(layer: TextLayer): string {
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

function layerTransform(layer: Layer): string {
  const transforms = [`translate(${formatNumber(layer.x)} ${formatNumber(layer.y)})`];

  if (layer.rotation !== 0) {
    transforms.push(`rotate(${formatNumber(layer.rotation)})`);
  }

  if (layer.scaleX !== 1 || layer.scaleY !== 1) {
    transforms.push(`scale(${formatNumber(layer.scaleX)} ${formatNumber(layer.scaleY)})`);
  }

  return transforms.join(" ");
}

function textAnchor(align: TextLayer["style"]["align"]): "start" | "middle" | "end" {
  if (align === "center") {
    return "middle";
  }

  if (align === "right") {
    return "end";
  }

  return "start";
}

function alignedTextX(layer: TextLayer): number {
  if (layer.style.align === "center") {
    return layer.width / 2;
  }

  if (layer.style.align === "right") {
    return layer.width;
  }

  return 0;
}

function imagePreserveAspectRatio(fit: ImageLayer["fit"]): string {
  if (fit === "cover") {
    return "xMidYMid slice";
  }

  if (fit === "stretch") {
    return "none";
  }

  if (fit === "none") {
    return "xMinYMin";
  }

  return "xMidYMid meet";
}

function createExportMetadata(document: LayerDocument, exportedAt: string): ExportMetadata {
  return {
    templateId: document.metadata.templateId,
    orderId: document.metadata.orderId ?? "",
    exportedAt,
    appVersion: document.metadata.appVersion,
  };
}

function createExportFileName(metadata: ExportMetadata, extension: "png" | "svg"): string {
  return `${sanitizeFilePart(metadata.templateId)}_${sanitizeFilePart(metadata.orderId || "no-order")}_${sanitizeFilePart(
    metadata.exportedAt,
  )}.${extension}`;
}

function sanitizeFilePart(value: string): string {
  return value.replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/[.:]/g, "-").replace(/^-+|-+$/g, "") || "export";
}

function defaultSvgBackground(document: LayerDocument): ExportBackground {
  return document.canvas.background.type === "transparent" ? "transparent" : "canvas";
}

function normalizeScale(value: number): number {
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error("PNG export scale must be a positive number");
  }

  return value;
}

function assertValidDocument(document: LayerDocument) {
  const validation = validateLayerDocument(document);
  if (!validation.ok) {
    throw new Error(`Cannot export invalid layer document: ${validation.errors.join("; ")}`);
  }
}

async function rasterizeSvgToPng(input: PngRasterizeInput): Promise<string> {
  if (typeof window === "undefined" || typeof Image === "undefined") {
    throw new Error("PNG export requires a browser renderer");
  }

  const blob = new Blob([input.svg], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);

  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error("SVG rasterization failed"));
      image.src = url;
    });

    const canvas = window.document.createElement("canvas");
    canvas.width = input.width;
    canvas.height = input.height;
    const context = canvas.getContext("2d");
    if (!context) {
      throw new Error("PNG export could not create a 2D canvas context");
    }

    context.clearRect(0, 0, input.width, input.height);
    context.drawImage(image, 0, 0, input.width, input.height);
    return canvas.toDataURL("image/png");
  } finally {
    URL.revokeObjectURL(url);
  }
}

function writePngTextMetadata(bytes: Uint8Array, keyword: string, text: string): Uint8Array {
  assertPngSignature(bytes);
  const metadataChunk = createPngChunk("iTXt", createInternationalTextData(keyword, text));
  const parts: Uint8Array[] = [bytes.slice(0, PNG_SIGNATURE.length)];
  let offset = PNG_SIGNATURE.length;
  let inserted = false;

  while (offset + 12 <= bytes.length) {
    const length = readUint32(bytes, offset);
    const type = asciiFromBytes(bytes.slice(offset + 4, offset + 8));
    const chunkEnd = offset + 12 + length;
    if (chunkEnd > bytes.length) {
      throw new Error("PNG chunk length exceeds file size");
    }

    if (type === "IEND" && !inserted) {
      parts.push(metadataChunk);
      inserted = true;
    }

    parts.push(bytes.slice(offset, chunkEnd));
    offset = chunkEnd;
  }

  if (!inserted) {
    throw new Error("PNG file is missing IEND chunk");
  }

  return concatBytes(parts);
}

function createInternationalTextData(keyword: string, text: string): Uint8Array {
  return concatBytes([
    asciiBytes(keyword),
    Uint8Array.from([0, 0, 0, 0, 0]),
    new TextEncoder().encode(text),
  ]);
}

function readInternationalTextChunk(data: Uint8Array, keyword: string): string | null {
  const keywordEnd = data.indexOf(0);
  if (keywordEnd < 0 || asciiFromBytes(data.slice(0, keywordEnd)) !== keyword) {
    return null;
  }

  const compressionFlagIndex = keywordEnd + 1;
  const compressionMethodIndex = compressionFlagIndex + 1;
  const languageStart = compressionMethodIndex + 1;
  if (languageStart >= data.length || data[compressionFlagIndex] !== 0) {
    return null;
  }

  const languageEnd = data.indexOf(0, languageStart);
  if (languageEnd < 0) {
    return null;
  }

  const translatedKeywordEnd = data.indexOf(0, languageEnd + 1);
  if (translatedKeywordEnd < 0) {
    return null;
  }

  return new TextDecoder().decode(data.slice(translatedKeywordEnd + 1));
}

function createPngChunk(type: string, data: Uint8Array): Uint8Array {
  if (!/^[A-Za-z]{4}$/.test(type)) {
    throw new Error("PNG chunk type must contain exactly four ASCII letters");
  }

  const typeBytes = asciiBytes(type);
  const lengthBytes = uint32Bytes(data.length);
  const crcInput = concatBytes([typeBytes, data]);
  const crcBytes = uint32Bytes(crc32(crcInput));
  return concatBytes([lengthBytes, typeBytes, data, crcBytes]);
}

function dataUrlToPngBytes(dataUrl: string): Uint8Array {
  const prefix = "data:image/png;base64,";
  if (!dataUrl.startsWith(prefix)) {
    throw new Error("PNG rasterizer must return a PNG data URL");
  }

  return base64ToBytes(dataUrl.slice(prefix.length));
}

function pngBytesToDataUrl(bytes: Uint8Array): string {
  return `data:image/png;base64,${bytesToBase64(bytes)}`;
}

function assertPngSignature(bytes: Uint8Array) {
  for (let index = 0; index < PNG_SIGNATURE.length; index += 1) {
    if (bytes[index] !== PNG_SIGNATURE[index]) {
      throw new Error("Invalid PNG signature");
    }
  }
}

function readUint32(bytes: Uint8Array, offset: number): number {
  return (
    ((bytes[offset] << 24) | (bytes[offset + 1] << 16) | (bytes[offset + 2] << 8) | bytes[offset + 3]) >>>
    0
  );
}

function uint32Bytes(value: number): Uint8Array {
  return Uint8Array.from([(value >>> 24) & 255, (value >>> 16) & 255, (value >>> 8) & 255, value & 255]);
}

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  }

  return (crc ^ 0xffffffff) >>> 0;
}

const CRC_TABLE = createCrcTable();

function createCrcTable(): Uint32Array {
  const table = new Uint32Array(256);
  for (let index = 0; index < table.length; index += 1) {
    let value = index;
    for (let bit = 0; bit < 8; bit += 1) {
      value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    }
    table[index] = value >>> 0;
  }
  return table;
}

function base64ToBytes(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

function asciiBytes(value: string): Uint8Array {
  const bytes = new Uint8Array(value.length);
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code > 127 || code === 0) {
      throw new Error("PNG metadata keyword must be non-null ASCII");
    }
    bytes[index] = code;
  }
  return bytes;
}

function asciiFromBytes(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => String.fromCharCode(byte)).join("");
}

function concatBytes(parts: readonly Uint8Array[]): Uint8Array {
  const totalLength = parts.reduce((sum, part) => sum + part.length, 0);
  const result = new Uint8Array(totalLength);
  let offset = 0;
  for (const part of parts) {
    result.set(part, offset);
    offset += part.length;
  }
  return result;
}

function triggerDownload(url: string, fileName: string) {
  const link = window.document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.rel = "noopener";
  window.document.body.append(link);
  link.click();
  link.remove();
}

function escapeText(value: string): string {
  return Array.from(value, (char) => {
    if (char === "&") {
      return "&amp;";
    }
    if (char === "<") {
      return "&lt;";
    }
    if (char === ">") {
      return "&gt;";
    }

    const codePoint = char.codePointAt(0) ?? 0;
    if (codePoint > 0x7e) {
      return `&#x${codePoint.toString(16).toUpperCase()};`;
    }

    return char;
  }).join("");
}

function escapeAttribute(value: string): string {
  return escapeText(value).replace(/"/g, "&quot;").replace(/'/g, "&apos;");
}

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) {
    throw new Error("Cannot format non-finite SVG number");
  }

  return Number(value.toFixed(4)).toString();
}

function indentBlock(value: string, indent: string): string {
  return value
    .split("\n")
    .map((line) => `${indent}${line}`)
    .join("\n");
}
