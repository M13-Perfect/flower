import { useCallback, useEffect, useMemo, useState } from "react";

import {
  EXPORT_SETTINGS_SCHEMA_VERSION,
  LAYER_DOCUMENT_SCHEMA_VERSION,
  type Layer,
  type LayerDocument,
  type TextLayer,
  validateLayerDocument,
} from "@flower/design-core";
import { createApiClient, type FontSummary, type HealthResponse, type ParsedOrder } from "./api/client";
import { FabricCanvas } from "./canvas/FabricCanvas";
import {
  applyGlyphOverrideToTextLayer,
  listLayersForDisplay,
  updateLayerProperty,
  updateTextLayerContent,
  updateTextLayerFont,
  type TextGlyphOverrideInput,
} from "./canvas/layerFabricModel";
import {
  createPngExport,
  createSvgExport,
  downloadDataUrl,
  downloadTextFile,
  type ExportBackground,
} from "./export/exportPipeline";
import { GlyphPicker } from "./GlyphPicker";
import { createDxfDataUrl, createOutputOrderName, selectInitialEditableLayerId } from "./orderWorkflow";
import "./styles.css";

type HealthState =
  | { status: "loading" }
  | { status: "ready"; health: HealthResponse }
  | { status: "error"; message: string };

const apiClient = createApiClient();

export function App() {
  const [healthState, setHealthState] = useState<HealthState>({ status: "loading" });
  const [document, setDocument] = useState<LayerDocument>(() => createSampleLayerDocument());
  const [selectedLayerId, setSelectedLayerId] = useState<string | null>("layer_text");
  const [savedJson, setSavedJson] = useState(() => JSON.stringify(createSampleLayerDocument(), null, 2));
  const [saveMessage, setSaveMessage] = useState("valid");
  const [orderId, setOrderId] = useState("");
  const [orderNote, setOrderNote] = useState("");
  const [orderMessage, setOrderMessage] = useState("ready");
  const [parsedOrder, setParsedOrder] = useState<ParsedOrder | null>(null);
  const [fonts, setFonts] = useState<FontSummary[]>([]);
  const [fontMessage, setFontMessage] = useState("loading");
  const [exportScale, setExportScale] = useState(() => document.exportSettings.png.scale);
  const [transparentExport, setTransparentExport] = useState(
    () => document.exportSettings.png.background === "transparent",
  );
  const [exportMessage, setExportMessage] = useState("ready");

  useEffect(() => {
    let cancelled = false;

    apiClient
      .health()
      .then((health) => {
        if (!cancelled) {
          setHealthState({ status: "ready", health });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setHealthState({
            status: "error",
            message: error instanceof Error ? error.message : "Backend health check failed",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setFontMessage("loading");

    apiClient
      .listFonts()
      .then((response) => {
        if (!cancelled) {
          setFonts(response.fonts);
          setFontMessage(response.fonts.length > 0 ? `${response.fonts.length} fonts` : "no fonts");
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setFonts([]);
          setFontMessage(error instanceof Error ? error.message : "Font scan failed");
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const selectedLayer = useMemo(
    () => findLayerById(document.layers, selectedLayerId),
    [document.layers, selectedLayerId],
  );
  const selectedTextLayer = selectedLayer?.type === "text" ? selectedLayer : null;
  const visibleLayers = useMemo(() => listLayersForDisplay(document.layers), [document.layers]);
  const exportBackground: ExportBackground = transparentExport ? "transparent" : "canvas";

  const handleSelectLayer = useCallback((layerId: string | null) => {
    setSelectedLayerId(layerId);
  }, []);

  const handleChangeDocument = useCallback((nextDocument: LayerDocument) => {
    setDocument(nextDocument);
  }, []);

  const handlePropertyPatch = useCallback(
    (patch: Parameters<typeof updateLayerProperty>[2]) => {
      if (!selectedLayerId) {
        return;
      }

      setDocument((currentDocument) => updateLayerProperty(currentDocument, selectedLayerId, patch));
    },
    [selectedLayerId],
  );

  const handleParseAndApplyOrder = useCallback(() => {
    const trimmedNote = orderNote.trim();
    if (!trimmedNote) {
      setOrderMessage("order note required");
      return;
    }

    setOrderMessage("parsing");
    void apiClient
      .parseOrder({
        orderNote: trimmedNote,
        orderId: orderId.trim() || undefined,
      })
      .then((parseResponse) => {
        setParsedOrder(parseResponse.parsedOrder);
        setOrderMessage("applying template");
        return apiClient.applyTemplate({
          templateId: "birth-flower-card",
          parsedOrder: parseResponse.parsedOrder,
        });
      })
      .then((templateResponse) => {
        setDocument(templateResponse.document);
        setSelectedLayerId(selectInitialEditableLayerId(templateResponse.document));
        setSavedJson(JSON.stringify(templateResponse.document, null, 2));
        setSaveMessage("template applied");
        setExportScale(templateResponse.document.exportSettings.png.scale);
        setTransparentExport(templateResponse.document.exportSettings.png.background === "transparent");
        setOrderMessage("template applied");
      })
      .catch((error: unknown) => {
        setOrderMessage(error instanceof Error ? error.message : "Order workflow failed");
      });
  }, [orderId, orderNote]);

  const handleTextContentChange = useCallback(
    (text: string) => {
      if (!selectedLayerId) {
        return;
      }
      try {
        setDocument((currentDocument) => updateTextLayerContent(currentDocument, selectedLayerId, text));
        setSaveMessage("text updated");
      } catch (error) {
        setSaveMessage(error instanceof Error ? error.message : "text update failed");
      }
    },
    [selectedLayerId],
  );

  const handleTextFontChange = useCallback(
    (fontId: string) => {
      if (!selectedLayerId) {
        return;
      }
      const font = fonts.find((candidate) => candidate.id === fontId);
      if (!font) {
        setSaveMessage("font not found");
        return;
      }
      try {
        setDocument((currentDocument) =>
          updateTextLayerFont(currentDocument, selectedLayerId, {
            family: font.familyName,
            source: "asset",
            assetId: font.id,
            fallbackFamilies: ["serif"],
          }),
        );
        setSaveMessage("font updated");
      } catch (error) {
        setSaveMessage(error instanceof Error ? error.message : "font update failed");
      }
    },
    [fonts, selectedLayerId],
  );

  const handleSaveJson = () => {
    const validation = validateLayerDocument(document);
    if (!validation.ok) {
      setSaveMessage(validation.errors.join("; "));
      return;
    }

    setSavedJson(JSON.stringify(document, null, 2));
    setSaveMessage("valid");
  };

  const handleApplyGlyph = useCallback(
    (input: TextGlyphOverrideInput) => {
      if (!selectedLayerId) {
        return;
      }

      try {
        setDocument((currentDocument) =>
          applyGlyphOverrideToTextLayer(currentDocument, selectedLayerId, input),
        );
        setSaveMessage("glyph saved");
      } catch (error) {
        setSaveMessage(error instanceof Error ? error.message : "glyph save failed");
      }
    },
    [selectedLayerId],
  );

  const handleExportSvg = useCallback(() => {
    try {
      const exported = createSvgExport(document, { background: exportBackground });
      downloadTextFile(exported.content, exported.fileName, exported.mimeType);
      setExportMessage(`SVG ${exported.metadata.exportedAt}`);
    } catch (error) {
      setExportMessage(error instanceof Error ? error.message : "SVG export failed");
    }
  }, [document, exportBackground]);

  const handleExportPng = useCallback(() => {
    setExportMessage("PNG exporting");
    void createPngExport(document, { background: exportBackground, scale: exportScale })
      .then((exported) => {
        downloadDataUrl(exported.dataUrl, exported.fileName);
        setExportMessage(`PNG ${exported.width}x${exported.height}`);
      })
      .catch((error: unknown) => {
        setExportMessage(error instanceof Error ? error.message : "PNG export failed");
      });
  }, [document, exportBackground, exportScale]);

  const handleExportDxf = useCallback(() => {
    setExportMessage("DXF exporting");
    void apiClient
      .exportDxf({
        document,
        units: document.exportSettings.dxf.units,
      })
      .then((exported) => {
        downloadDataUrl(createDxfDataUrl(exported.mimeType, exported.contentBase64), exported.fileName);
        setExportMessage(exported.warnings.length > 0 ? `DXF ${exported.warnings.length} warnings` : "DXF ready");
      })
      .catch((error: unknown) => {
        setExportMessage(error instanceof Error ? error.message : "DXF export failed");
      });
  }, [document]);

  const handleSaveAllOutputs = useCallback(() => {
    setExportMessage("saving outputs");
    void Promise.all([
      Promise.resolve(createSvgExport(document, { background: exportBackground })),
      createPngExport(document, { background: exportBackground, scale: exportScale }),
      apiClient.exportDxf({ document, units: document.exportSettings.dxf.units }),
    ])
      .then(([svgExport, pngExport, dxfExport]) =>
        apiClient.saveOutputs({
          orderName: createOutputOrderName(document, parsedOrder?.customerName ?? ""),
          document,
          svg: svgExport.content,
          pngDataUrl: pngExport.dataUrl,
          dxfContentBase64: dxfExport.contentBase64,
        }),
      )
      .then((saved) => {
        setSavedJson(JSON.stringify(document, null, 2));
        setSaveMessage("outputs saved");
        setExportMessage(`saved ${saved.outputDir}`);
      })
      .catch((error: unknown) => {
        setExportMessage(error instanceof Error ? error.message : "Output save failed");
      });
  }, [document, exportBackground, exportScale, parsedOrder?.customerName]);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Flower</p>
          <h1>Layer editor</h1>
        </div>
        <BackendStatus state={healthState} />
      </header>

      <section className="editor-grid" aria-label="Fabric layer editor">
        <aside className="sidebar" aria-label="Layers">
          <OrderPanel
            message={orderMessage}
            orderId={orderId}
            orderNote={orderNote}
            parsedOrder={parsedOrder}
            onChangeOrderId={setOrderId}
            onChangeOrderNote={setOrderNote}
            onParseAndApply={handleParseAndApplyOrder}
          />

          <div className="panel-header">
            <h2>Layers</h2>
            <span>{document.layers.length}</span>
          </div>
          <div className="layer-list">
            {visibleLayers.map((layer) => (
              <button
                className={layer.id === selectedLayerId ? "layer-row active" : "layer-row"}
                key={layer.id}
                onClick={() => setSelectedLayerId(layer.id)}
                type="button"
              >
                <span className="layer-kind">{layer.type}</span>
                <span className="layer-name">{layer.name}</span>
                <span className="layer-state">{layer.visible ? "shown" : "hidden"}</span>
              </button>
            ))}
          </div>
        </aside>

        <section className="canvas-panel" aria-label="Canvas">
          <FabricCanvas
            document={document}
            selectedLayerId={selectedLayerId}
            onChangeDocument={handleChangeDocument}
            onSelectLayer={handleSelectLayer}
          />
        </section>

        <aside className="inspector" aria-label="Inspector">
          <div className="panel-header">
            <h2>Properties</h2>
            <span>{selectedLayer?.type ?? "none"}</span>
          </div>
          {selectedLayer ? (
            <PropertyPanel layer={selectedLayer} onChange={handlePropertyPatch} />
          ) : (
            <p className="empty-state">No layer selected.</p>
          )}

          <TextLayerPanel
            fonts={fonts}
            fontMessage={fontMessage}
            layer={selectedTextLayer}
            onChangeFont={handleTextFontChange}
            onChangeText={handleTextContentChange}
          />

          <GlyphPicker
            apiClient={apiClient}
            layer={selectedTextLayer}
            onApplyGlyph={handleApplyGlyph}
          />

          <ExportPanel
            message={exportMessage}
            scale={exportScale}
            transparent={transparentExport}
            onChangeScale={setExportScale}
            onChangeTransparent={setTransparentExport}
            onExportDxf={handleExportDxf}
            onExportPng={handleExportPng}
            onExportSvg={handleExportSvg}
            onSaveAll={handleSaveAllOutputs}
          />

          <div className="save-panel">
            <div className="panel-header">
              <h2>JSON</h2>
              <span>{saveMessage}</span>
            </div>
            <button className="primary-action" onClick={handleSaveJson} type="button">
              Save JSON
            </button>
            <textarea readOnly value={savedJson} />
          </div>
        </aside>
      </section>
    </main>
  );
}

function OrderPanel({
  message,
  onChangeOrderId,
  onChangeOrderNote,
  onParseAndApply,
  orderId,
  orderNote,
  parsedOrder,
}: {
  message: string;
  onChangeOrderId: (value: string) => void;
  onChangeOrderNote: (value: string) => void;
  onParseAndApply: () => void;
  orderId: string;
  orderNote: string;
  parsedOrder: ParsedOrder | null;
}) {
  return (
    <section className="order-panel" aria-label="Order workflow">
      <div className="panel-header">
        <h2>Order</h2>
        <span>{message}</span>
      </div>
      <label className="text-field">
        <span>id</span>
        <input
          onChange={(event) => onChangeOrderId(event.currentTarget.value)}
          placeholder="optional"
          value={orderId}
        />
      </label>
      <label className="stack-field">
        <span>note</span>
        <textarea
          onChange={(event) => onChangeOrderNote(event.currentTarget.value)}
          value={orderNote}
        />
      </label>
      <button className="primary-action" onClick={onParseAndApply} type="button">
        Parse + apply
      </button>
      {parsedOrder ? (
        <dl className="order-summary">
          <div>
            <dt>name</dt>
            <dd>{parsedOrder.customerName}</dd>
          </div>
          <div>
            <dt>flower</dt>
            <dd>{parsedOrder.flower?.name}</dd>
          </div>
          <div>
            <dt>font</dt>
            <dd>{parsedOrder.fontPreference?.label}</dd>
          </div>
        </dl>
      ) : null}
    </section>
  );
}

function TextLayerPanel({
  fontMessage,
  fonts,
  layer,
  onChangeFont,
  onChangeText,
}: {
  fontMessage: string;
  fonts: FontSummary[];
  layer: TextLayer | null;
  onChangeFont: (fontId: string) => void;
  onChangeText: (text: string) => void;
}) {
  const selectedFontId = layer ? matchLayerFontId(layer, fonts) : "";

  return (
    <section className="text-panel" aria-label="Text layer editor">
      <div className="panel-header">
        <h2>Text</h2>
        <span>{layer ? layer.fontRef.family : "text only"}</span>
      </div>
      {!layer ? <p className="empty-state">No text layer selected.</p> : null}
      {layer ? (
        <>
          <label className="stack-field">
            <span>content</span>
            <textarea
              onChange={(event) => onChangeText(event.currentTarget.value)}
              value={layer.text}
            />
          </label>
          <label className="select-field">
            <span>font</span>
            <select
              disabled={fonts.length === 0}
              onChange={(event) => onChangeFont(event.currentTarget.value)}
              value={selectedFontId}
            >
              {selectedFontId === "" ? <option value="">Current: {layer.fontRef.family}</option> : null}
              {fonts.map((font) => (
                <option key={font.id} value={font.id}>
                  {font.familyName}
                </option>
              ))}
            </select>
          </label>
          <p className="field-note">{fontMessage}</p>
        </>
      ) : null}
    </section>
  );
}

function ExportPanel({
  message,
  onChangeScale,
  onChangeTransparent,
  onExportDxf,
  onExportPng,
  onExportSvg,
  onSaveAll,
  scale,
  transparent,
}: {
  message: string;
  onChangeScale: (scale: number) => void;
  onChangeTransparent: (transparent: boolean) => void;
  onExportDxf: () => void;
  onExportPng: () => void;
  onExportSvg: () => void;
  onSaveAll: () => void;
  scale: number;
  transparent: boolean;
}) {
  return (
    <div className="export-panel">
      <div className="panel-header">
        <h2>Export</h2>
        <span>{message}</span>
      </div>
      <div className="property-grid">
        <NumberField
          label="scale"
          min={0.1}
          step={0.25}
          value={scale}
          onChange={(value) => {
            if (value > 0) {
              onChangeScale(value);
            }
          }}
        />
        <label className="toggle-row">
          <input
            checked={transparent}
            onChange={(event) => onChangeTransparent(event.currentTarget.checked)}
            type="checkbox"
          />
          transparent
        </label>
      </div>
      <div className="export-actions">
        <button className="secondary-action" onClick={onExportSvg} type="button">
          SVG
        </button>
        <button className="secondary-action" onClick={onExportDxf} type="button">
          DXF
        </button>
        <button className="primary-action" onClick={onExportPng} type="button">
          PNG
        </button>
        <button className="primary-action" onClick={onSaveAll} type="button">
          Save all
        </button>
      </div>
    </div>
  );
}

function BackendStatus({ state }: { state: HealthState }) {
  if (state.status === "ready") {
    return (
      <div className="status status-ready">
        <span>{state.health.service}</span>
        <strong>{state.health.status}</strong>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="status status-error">
        <span>backend</span>
        <strong>{state.message}</strong>
      </div>
    );
  }

  return (
    <div className="status">
      <span>backend</span>
      <strong>checking</strong>
    </div>
  );
}

function PropertyPanel({
  layer,
  onChange,
}: {
  layer: Layer;
  onChange: (patch: Parameters<typeof updateLayerProperty>[2]) => void;
}) {
  const scale = Number(((layer.scaleX + layer.scaleY) / 2).toFixed(3));

  return (
    <div className="property-grid">
      <NumberField label="x" value={layer.x} onChange={(x) => onChange({ x })} />
      <NumberField label="y" value={layer.y} onChange={(y) => onChange({ y })} />
      <NumberField label="scale" step={0.05} value={scale} onChange={(nextScale) => onChange({ scale: nextScale })} />
      <NumberField
        label="rotation"
        value={layer.rotation}
        onChange={(rotation) => onChange({ rotation })}
      />
      <NumberField
        label="opacity"
        max={1}
        min={0}
        step={0.05}
        value={layer.opacity}
        onChange={(opacity) => onChange({ opacity })}
      />
      <label className="toggle-row">
        <input
          checked={layer.visible}
          onChange={(event) => onChange({ visible: event.currentTarget.checked })}
          type="checkbox"
        />
        visible
      </label>
      <label className="toggle-row">
        <input
          checked={layer.locked}
          onChange={(event) => onChange({ locked: event.currentTarget.checked })}
          type="checkbox"
        />
        locked
      </label>
    </div>
  );
}

function NumberField({
  label,
  max,
  min,
  onChange,
  step = 1,
  value,
}: {
  label: string;
  max?: number;
  min?: number;
  onChange: (value: number) => void;
  step?: number;
  value: number;
}) {
  return (
    <label className="number-field">
      <span>{label}</span>
      <input
        max={max}
        min={min}
        onChange={(event) => {
          const nextValue = Number(event.currentTarget.value);
          if (Number.isFinite(nextValue)) {
            onChange(nextValue);
          }
        }}
        step={step}
        type="number"
        value={Number(value.toFixed(3))}
      />
    </label>
  );
}

function findLayerById(layers: readonly Layer[], layerId: string | null): Layer | null {
  if (!layerId) {
    return null;
  }

  for (const layer of layers) {
    if (layer.id === layerId) {
      return layer;
    }

    if (layer.type === "group") {
      const child = findLayerById(layer.children, layerId);
      if (child) {
        return child;
      }
    }
  }

  return null;
}

function matchLayerFontId(layer: TextLayer, fonts: readonly FontSummary[]): string {
  const normalizedFamily = layer.fontRef.family.trim().toLocaleLowerCase();
  return (
    fonts.find(
      (font) =>
        font.id === layer.fontRef.assetId ||
        font.familyName.trim().toLocaleLowerCase() === normalizedFamily ||
        font.fullName.trim().toLocaleLowerCase() === normalizedFamily,
    )?.id ?? ""
  );
}

function createSampleLayerDocument(): LayerDocument {
  return {
    schemaVersion: LAYER_DOCUMENT_SCHEMA_VERSION,
    documentId: "doc_fabric_sample",
    projectId: "project_local",
    jobId: "job_preview",
    metadata: {
      orderId: "order_preview",
      templateId: "birth-flower-card",
      templateVersion: "1.0.0",
      appVersion: "0.1.0",
      createdAt: "2026-06-11T00:00:00.000Z",
      updatedAt: "2026-06-11T00:00:00.000Z",
    },
    canvas: {
      width: 900,
      height: 620,
      unit: "px",
      background: {
        type: "solid",
        color: "#fbfaf7",
      },
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
        id: "layer_image",
        type: "image",
        name: "Reference photo",
        visible: true,
        locked: false,
        exportable: true,
        zIndex: 1,
        opacity: 0.95,
        x: 78,
        y: 120,
        width: 260,
        height: 260,
        scaleX: 1,
        scaleY: 1,
        rotation: -3,
        tags: ["sample-image"],
        assetRef: {
          assetId: "sample_photo",
          path: svgDataUrl(`
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 260">
              <rect width="260" height="260" rx="24" fill="#d9ece7"/>
              <circle cx="132" cy="112" r="62" fill="#f1b8b6"/>
              <path d="M50 216c36-48 84-60 160-10" fill="none" stroke="#2d5a4f" stroke-width="18" stroke-linecap="round"/>
            </svg>
          `),
        },
        intrinsicSize: {
          width: 260,
          height: 260,
        },
        fit: "contain",
      },
      {
        id: "layer_svg",
        type: "svg",
        name: "Birth flower",
        visible: true,
        locked: false,
        exportable: true,
        zIndex: 2,
        opacity: 1,
        x: 470,
        y: 88,
        width: 260,
        height: 330,
        scaleX: 1,
        scaleY: 1,
        rotation: 4,
        tags: ["sample-svg"],
        inlineSvg: `
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 160">
            <path d="M62 72 C48 38 54 16 72 8 C88 30 82 52 62 72Z" fill="#d74862"/>
            <path d="M58 72 C30 50 22 28 34 12 C58 26 68 48 58 72Z" fill="#ef7d8f"/>
            <path d="M60 74 C86 54 106 54 114 70 C94 90 74 90 60 74Z" fill="#c93755"/>
            <path d="M60 76 C34 82 20 100 28 120 C54 118 66 98 60 76Z" fill="#f09dad"/>
            <path d="M60 76 C78 98 76 126 58 150" fill="none" stroke="#2f7d5f" stroke-width="8" stroke-linecap="round"/>
            <path d="M64 104 C84 94 102 102 108 118 C88 126 72 120 64 104Z" fill="#55a06f"/>
          </svg>
        `,
        viewBox: {
          x: 0,
          y: 0,
          width: 120,
          height: 160,
        },
        preserveVector: true,
      },
      {
        id: "layer_text",
        type: "text",
        name: "Customer name",
        visible: true,
        locked: false,
        exportable: true,
        zIndex: 3,
        opacity: 1,
        x: 278,
        y: 450,
        width: 360,
        height: 84,
        scaleX: 1,
        scaleY: 1,
        rotation: 0,
        tags: ["sample-text"],
        text: "Avery",
        fontRef: {
          family: "Georgia",
          source: "system",
          fallbackFamilies: ["serif"],
        },
        style: {
          fontSize: 72,
          fill: "#26352f",
          align: "center",
          lineHeight: 1.1,
          letterSpacing: 0,
        },
        layout: {
          mode: "box",
          overflow: "shrink-to-fit",
        },
      },
    ],
  };
}

function svgDataUrl(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg.trim())}`;
}
