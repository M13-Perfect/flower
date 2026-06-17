import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type RefObject } from "react";

import {
  EXPORT_SETTINGS_SCHEMA_VERSION,
  LAYER_DOCUMENT_SCHEMA_VERSION,
  type Layer,
  type LayerDocument,
  type TextLayer,
  validateLayerDocument,
} from "@flower/design-core";
import {
  createApiClient,
  type FontSummary,
  type HealthResponse,
  type ParsedOrder,
  type PathSettings,
} from "./api/client";
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
import { addImageAssetLayer, addSvgAssetLayer, addTextLayer } from "./editorActions";
import { ADD_ASSET_BUTTON_LABEL } from "./editorLabels";
import { loadProjectFonts } from "./fontLoader";
import { GlyphPicker } from "./GlyphPicker";
import { createDxfDataUrl, createOutputOrderName, selectInitialEditableLayerId } from "./orderWorkflow";
import "./styles.css";

type HealthState =
  | { status: "loading" }
  | { status: "ready"; health: HealthResponse }
  | { status: "error"; message: string };

type PathDirectoryKind = "asset" | "font" | "output";

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
  const [pathSettings, setPathSettings] = useState<PathSettings>({
    assetDirectories: [],
    fontDirectories: [],
    outputDirectory: null,
  });
  const [settingsMessage, setSettingsMessage] = useState("loading");
  const [exportScale, setExportScale] = useState(() => document.exportSettings.png.scale);
  const [outputWidth, setOutputWidth] = useState(() =>
    Math.round(document.canvas.width * document.exportSettings.png.scale),
  );
  const [outputHeight, setOutputHeight] = useState(() =>
    Math.round(document.canvas.height * document.exportSettings.png.scale),
  );
  const [transparentExport, setTransparentExport] = useState(
    () => document.exportSettings.png.background === "transparent",
  );
  const [exportMessage, setExportMessage] = useState("ready");
  const assetInputRef = useRef<HTMLInputElement | null>(null);

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
    setSettingsMessage("loading");

    apiClient
      .getPathSettings()
      .then((settings) => {
        if (!cancelled) {
          setPathSettings(settings);
          setSettingsMessage("ready");
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setSettingsMessage(error instanceof Error ? error.message : "Path settings failed");
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

  useEffect(() => {
    let cancelled = false;
    if (fonts.length === 0) {
      return () => {
        cancelled = true;
      };
    }

    void loadProjectFonts(fonts, apiClient.fontFileUrl).then((loaded) => {
      if (!cancelled && loaded > 0) {
        setFontMessage(`${fonts.length} fonts / ${loaded} loaded`);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [fonts]);

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
        setOutputWidth(
          Math.round(
            templateResponse.document.canvas.width * templateResponse.document.exportSettings.png.scale,
          ),
        );
        setOutputHeight(
          Math.round(
            templateResponse.document.canvas.height * templateResponse.document.exportSettings.png.scale,
          ),
        );
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

  const handleAddTextLayer = useCallback(() => {
    try {
      const result = addTextLayer(document);
      setDocument(result.document);
      setSelectedLayerId(result.layerId);
      setSavedJson(JSON.stringify(result.document, null, 2));
      setSaveMessage("text layer added");
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : "text layer add failed");
    }
  }, [document]);

  const handleChooseAsset = useCallback(() => {
    assetInputRef.current?.click();
  }, []);

  const handleChoosePathDirectory = useCallback(
    (kind: PathDirectoryKind) => {
      const chooseDirectory = window.flowerDesktop?.chooseDirectory;
      if (!chooseDirectory) {
        setSettingsMessage("desktop picker unavailable");
        return;
      }

      setSettingsMessage(`choosing ${kind}`);
      void chooseDirectory()
        .then((directory) => {
          if (!directory) {
            setSettingsMessage("cancelled");
            return null;
          }

          const request: PathSettings = {
            assetDirectories: pathSettings.assetDirectories,
            fontDirectories: pathSettings.fontDirectories,
            outputDirectory: pathSettings.outputDirectory ?? null,
          };
          if (kind === "asset") {
            request.assetDirectories = [directory];
          }
          if (kind === "font") {
            request.fontDirectories = [directory];
          }
          if (kind === "output") {
            request.outputDirectory = directory;
          }

          return apiClient.updatePathSettings(request).then((settings) => ({ settings, kind }));
        })
        .then((result) => {
          if (!result) {
            return;
          }
          setPathSettings(result.settings);
          setSettingsMessage("paths saved");

          if (result.kind === "font") {
            setFontMessage("loading");
            void apiClient
              .listFonts()
              .then((response) => {
                setFonts(response.fonts);
                setFontMessage(
                  response.fonts.length > 0 ? `${response.fonts.length} fonts` : "no fonts",
                );
              })
              .catch((error: unknown) => {
                setFonts([]);
                setFontMessage(error instanceof Error ? error.message : "Font scan failed");
              });
          }
        })
        .catch((error: unknown) => {
          setSettingsMessage(error instanceof Error ? error.message : "Path update failed");
        });
    },
    [pathSettings],
  );

  const handleAssetFileChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.currentTarget.files?.[0];
      event.currentTarget.value = "";
      if (!file) {
        return;
      }

      setSaveMessage("adding asset");
      void createImportedLayer(document, file)
        .then((result) => {
          setDocument(result.document);
          setSelectedLayerId(result.layerId);
          setSavedJson(JSON.stringify(result.document, null, 2));
          setSaveMessage("asset layer added");
        })
        .catch((error: unknown) => {
          setSaveMessage(error instanceof Error ? error.message : "asset layer add failed");
        });
    },
    [document],
  );

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

  const handleChangeExportScale = useCallback(
    (scale: number) => {
      if (scale <= 0) {
        return;
      }
      setExportScale(scale);
      setOutputWidth(Math.max(1, Math.round(document.canvas.width * scale)));
      setOutputHeight(Math.max(1, Math.round(document.canvas.height * scale)));
    },
    [document.canvas.height, document.canvas.width],
  );

  const handleChangeOutputWidth = useCallback(
    (width: number) => {
      if (width <= 0) {
        return;
      }
      const scale = width / document.canvas.width;
      setExportScale(scale);
      setOutputWidth(Math.max(1, Math.round(width)));
      setOutputHeight(Math.max(1, Math.round(document.canvas.height * scale)));
    },
    [document.canvas.height, document.canvas.width],
  );

  const handleChangeOutputHeight = useCallback(
    (height: number) => {
      if (height <= 0) {
        return;
      }
      const scale = height / document.canvas.height;
      setExportScale(scale);
      setOutputHeight(Math.max(1, Math.round(height)));
      setOutputWidth(Math.max(1, Math.round(document.canvas.width * scale)));
    },
    [document.canvas.height, document.canvas.width],
  );

  const handleExportSvg = useCallback(() => {
    try {
      const exported = createSvgExport(document, {
        background: exportBackground,
        fontFaceUrlForAsset: apiClient.fontFileUrl,
      });
      downloadTextFile(exported.content, exported.fileName, exported.mimeType);
      setExportMessage(`SVG ${exported.metadata.exportedAt}`);
    } catch (error) {
      setExportMessage(error instanceof Error ? error.message : "SVG export failed");
    }
  }, [document, exportBackground]);

  const handleExportPng = useCallback(() => {
    setExportMessage("PNG exporting");
    void createPngExport(document, {
      background: exportBackground,
      fontFaceUrlForAsset: apiClient.fontFileUrl,
      outputHeight,
      outputWidth,
      scale: exportScale,
    })
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
      Promise.resolve(
        createSvgExport(document, {
          background: exportBackground,
          fontFaceUrlForAsset: apiClient.fontFileUrl,
        }),
      ),
      createPngExport(document, {
        background: exportBackground,
        fontFaceUrlForAsset: apiClient.fontFileUrl,
        outputHeight,
        outputWidth,
        scale: exportScale,
      }),
      apiClient.exportDxf({ document, units: document.exportSettings.dxf.units }),
    ])
      .then(([svgExport, pngExport, dxfExport]) =>
        apiClient.saveOutputs({
          orderName: createOutputOrderName(document, parsedOrder?.customerName ?? ""),
          document,
          svg: svgExport.content,
          pngDataUrl: pngExport.dataUrl,
          dxfContentBase64: dxfExport.contentBase64,
          outputDirectory: pathSettings.outputDirectory,
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
  }, [
    document,
    exportBackground,
    exportScale,
    outputHeight,
    outputWidth,
    parsedOrder?.customerName,
    pathSettings.outputDirectory,
  ]);

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

          <LayerCreatePanel
            assetInputRef={assetInputRef}
            onAddText={handleAddTextLayer}
            onAssetFileChange={handleAssetFileChange}
            onChooseAsset={handleChooseAsset}
          />

          <PathSettingsPanel
            message={settingsMessage}
            onChooseDirectory={handleChoosePathDirectory}
            settings={pathSettings}
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
            onChangeOutputHeight={handleChangeOutputHeight}
            onChangeOutputWidth={handleChangeOutputWidth}
            onChangeScale={handleChangeExportScale}
            transparent={transparentExport}
            onChangeTransparent={setTransparentExport}
            onChooseOutputDirectory={() => handleChoosePathDirectory("output")}
            onExportDxf={handleExportDxf}
            onExportPng={handleExportPng}
            onExportSvg={handleExportSvg}
            onSaveAll={handleSaveAllOutputs}
            outputDirectory={pathSettings.outputDirectory}
            outputHeight={outputHeight}
            outputWidth={outputWidth}
            scale={exportScale}
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

function LayerCreatePanel({
  assetInputRef,
  onAddText,
  onAssetFileChange,
  onChooseAsset,
}: {
  assetInputRef: RefObject<HTMLInputElement | null>;
  onAddText: () => void;
  onAssetFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onChooseAsset: () => void;
}) {
  return (
    <section className="layer-create-panel" aria-label="Create layers">
      <button className="secondary-action" onClick={onAddText} type="button">
        Add text
      </button>
      <button className="secondary-action" onClick={onChooseAsset} type="button">
        {ADD_ASSET_BUTTON_LABEL}
      </button>
      <input
        accept=".svg,.png,.jpg,.jpeg,.webp,.bmp"
        className="visually-hidden-file"
        onChange={onAssetFileChange}
        ref={assetInputRef}
        type="file"
      />
    </section>
  );
}

function PathSettingsPanel({
  message,
  onChooseDirectory,
  settings,
}: {
  message: string;
  onChooseDirectory: (kind: PathDirectoryKind) => void;
  settings: PathSettings;
}) {
  return (
    <section className="path-panel" aria-label="Path settings">
      <div className="panel-header">
        <h2>Paths</h2>
        <span>{message}</span>
      </div>
      <PathRow
        label="素材目录"
        onChoose={() => onChooseDirectory("asset")}
        value={settings.assetDirectories[0] ?? "not set"}
      />
      <PathRow
        label="字体目录"
        onChoose={() => onChooseDirectory("font")}
        value={settings.fontDirectories[0] ?? "not set"}
      />
      <PathRow
        label="输出目录"
        onChoose={() => onChooseDirectory("output")}
        value={settings.outputDirectory ?? "not set"}
      />
    </section>
  );
}

function PathRow({
  label,
  onChoose,
  value,
}: {
  label: string;
  onChoose: () => void;
  value: string;
}) {
  return (
    <div className="path-row">
      <span>{label}</span>
      <code title={value}>{formatPathLabel(value)}</code>
      <button className="secondary-action" onClick={onChoose} type="button">
        Choose
      </button>
    </div>
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
  onChangeOutputHeight,
  onChangeOutputWidth,
  onChangeScale,
  onChangeTransparent,
  onChooseOutputDirectory,
  onExportDxf,
  onExportPng,
  onExportSvg,
  onSaveAll,
  outputDirectory,
  outputHeight,
  outputWidth,
  scale,
  transparent,
}: {
  message: string;
  onChangeOutputHeight: (height: number) => void;
  onChangeOutputWidth: (width: number) => void;
  onChangeScale: (scale: number) => void;
  onChangeTransparent: (transparent: boolean) => void;
  onChooseOutputDirectory: () => void;
  onExportDxf: () => void;
  onExportPng: () => void;
  onExportSvg: () => void;
  onSaveAll: () => void;
  outputDirectory?: string | null;
  outputHeight: number;
  outputWidth: number;
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
        <NumberField
          label="png width"
          min={1}
          step={1}
          value={outputWidth}
          onChange={onChangeOutputWidth}
        />
        <NumberField
          label="png height"
          min={1}
          step={1}
          value={outputHeight}
          onChange={onChangeOutputHeight}
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
      <div className="output-directory-row">
        <span title={outputDirectory ?? ""}>{formatPathLabel(outputDirectory ?? "not set")}</span>
        <button className="secondary-action" onClick={onChooseOutputDirectory} type="button">
          Output folder
        </button>
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

function formatPathLabel(value: string): string {
  if (value.length <= 34) {
    return value;
  }
  return `...${value.slice(-31)}`;
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

async function createImportedLayer(document: LayerDocument, file: File) {
  if (isSvgFile(file)) {
    return addSvgAssetLayer(document, {
      name: file.name,
      svgText: await file.text(),
    });
  }

  if (!isRasterImageFile(file)) {
    throw new Error("Unsupported asset file type");
  }

  const dataUrl = await readFileAsDataUrl(file);
  const size = await readImageSize(dataUrl);
  return addImageAssetLayer(document, {
    dataUrl,
    height: size.height,
    name: file.name,
    width: size.width,
  });
}

function isSvgFile(file: File): boolean {
  return file.type === "image/svg+xml" || file.name.toLocaleLowerCase().endsWith(".svg");
}

function isRasterImageFile(file: File): boolean {
  return (
    file.type.startsWith("image/") &&
    [".png", ".jpg", ".jpeg", ".webp", ".bmp"].some((extension) =>
      file.name.toLocaleLowerCase().endsWith(extension),
    )
  );
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        resolve(reader.result);
        return;
      }
      reject(new Error("Asset file could not be read"));
    };
    reader.onerror = () => reject(new Error("Asset file could not be read"));
    reader.readAsDataURL(file);
  });
}

function readImageSize(dataUrl: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      resolve({
        height: image.naturalHeight || 1,
        width: image.naturalWidth || 1,
      });
    };
    image.onerror = () => reject(new Error("Imported image could not be decoded"));
    image.src = dataUrl;
  });
}
