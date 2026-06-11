import { useEffect, useRef, useState } from "react";
import {
  Canvas,
  FabricImage,
  FabricText,
  Textbox,
  loadSVGFromString,
  loadSVGFromURL,
  util,
  type FabricObject,
} from "fabric";

import type { LayerDocument } from "@flower/design-core";
import {
  buildTextWithGlyphOverrides,
  isSupportedEditorLayer,
  serializeLayerDocumentFromSnapshots,
  type FabricLayerObjectSnapshot,
  type SupportedEditorLayer,
  type SupportedFabricType,
} from "./layerFabricModel";

interface FabricCanvasProps {
  document: LayerDocument;
  selectedLayerId: string | null;
  onSelectLayer: (layerId: string | null) => void;
  onChangeDocument: (document: LayerDocument) => void;
}

interface EditorFabricMetadata {
  layerId: string;
  layerName: string;
  layerZIndex: number;
  layerType: SupportedEditorLayer["type"];
  fabricType: SupportedFabricType;
  modelWidth: number;
  modelHeight: number;
  fitScaleX: number;
  fitScaleY: number;
}

type EditorFabricObject = FabricObject & EditorFabricMetadata;

export function FabricCanvas({
  document,
  selectedLayerId,
  onSelectLayer,
  onChangeDocument,
}: FabricCanvasProps) {
  const canvasElementRef = useRef<HTMLCanvasElement | null>(null);
  const fabricCanvasRef = useRef<Canvas | null>(null);
  const documentRef = useRef(document);
  const hydrateTokenRef = useRef(0);
  const [loadErrors, setLoadErrors] = useState<string[]>([]);

  useEffect(() => {
    documentRef.current = document;
  }, [document]);

  useEffect(() => {
    const canvasElement = canvasElementRef.current;
    if (!canvasElement) {
      return;
    }

    const fabricCanvas = new Canvas(canvasElement, {
      width: document.canvas.width,
      height: document.canvas.height,
      preserveObjectStacking: true,
      selection: true,
    });

    fabricCanvasRef.current = fabricCanvas;

    const notifySelection = () => {
      const activeObject = fabricCanvas.getActiveObject();
      onSelectLayer(isEditorFabricObject(activeObject) ? activeObject.layerId : null);
    };

    const notifyDocumentChange = () => {
      const snapshots = fabricCanvas
        .getObjects()
        .map(createSnapshotFromFabricObject)
        .filter((snapshot): snapshot is FabricLayerObjectSnapshot => snapshot !== null);
      const nextDocument = serializeLayerDocumentFromSnapshots(documentRef.current, snapshots);
      onChangeDocument(nextDocument);
    };

    fabricCanvas.on("selection:created", notifySelection);
    fabricCanvas.on("selection:updated", notifySelection);
    fabricCanvas.on("selection:cleared", notifySelection);
    fabricCanvas.on("object:modified", notifyDocumentChange);

    return () => {
      void fabricCanvas.dispose();
      fabricCanvasRef.current = null;
    };
  }, [document.canvas.height, document.canvas.width, onChangeDocument, onSelectLayer]);

  useEffect(() => {
    const fabricCanvas = fabricCanvasRef.current;
    if (!fabricCanvas) {
      return;
    }

    const token = hydrateTokenRef.current + 1;
    hydrateTokenRef.current = token;
    const errors: string[] = [];
    const supportedLayers = document.layers
      .filter(isSupportedEditorLayer)
      .sort((left, right) => left.zIndex - right.zIndex);

    fabricCanvas.clear();
    fabricCanvas.setDimensions({
      width: document.canvas.width,
      height: document.canvas.height,
    });
    fabricCanvas.backgroundColor =
      document.canvas.background.type === "solid" ? document.canvas.background.color : "";

    void Promise.all(
      supportedLayers.map(async (layer) => {
        try {
          return await createFabricObjectFromLayer(layer);
        } catch (error) {
          errors.push(
            `${layer.name}: ${error instanceof Error ? error.message : "failed to load layer"}`,
          );
          return createMissingLayerPlaceholder(layer);
        }
      }),
    ).then((objects) => {
      if (hydrateTokenRef.current !== token) {
        return;
      }

      const nextObjects = objects.filter((object): object is EditorFabricObject => object !== null);
      fabricCanvas.add(...nextObjects);
      restoreActiveObject(fabricCanvas, selectedLayerId);
      fabricCanvas.requestRenderAll();
      setLoadErrors(errors);
    });
  }, [document, selectedLayerId]);

  useEffect(() => {
    const fabricCanvas = fabricCanvasRef.current;
    if (!fabricCanvas) {
      return;
    }

    restoreActiveObject(fabricCanvas, selectedLayerId);
    fabricCanvas.requestRenderAll();
  }, [selectedLayerId]);

  return (
    <div className="fabric-stage-wrap">
      <div className="fabric-stage">
        <canvas ref={canvasElementRef} />
      </div>
      {loadErrors.length > 0 ? (
        <div className="canvas-errors" role="status">
          {loadErrors.map((error) => (
            <p key={error}>{error}</p>
          ))}
        </div>
      ) : null}
    </div>
  );
}

async function createFabricObjectFromLayer(layer: SupportedEditorLayer): Promise<EditorFabricObject> {
  if (layer.type === "text") {
    const object = new Textbox(buildTextWithGlyphOverrides(layer), {
      width: layer.width,
      height: layer.height,
      fontFamily: layer.fontRef.family,
      fontSize: layer.style.fontSize,
      fill: layer.style.fill,
      stroke: layer.style.stroke,
      strokeWidth: layer.style.strokeWidth,
      textAlign: layer.style.align,
      lineHeight: layer.style.lineHeight,
      charSpacing: layer.style.letterSpacing,
    });

    return applyLayerRuntimeOptions(object, layer, "text", 1, 1);
  }

  if (layer.type === "image") {
    const image = await FabricImage.fromURL(resolveAssetUrl(layer.assetRef.path), {}, {});
    const fitScaleX = layer.width / positiveDimension(image.width);
    const fitScaleY = layer.height / positiveDimension(image.height);

    return applyLayerRuntimeOptions(image, layer, "image", fitScaleX, fitScaleY);
  }

  const svgObject = await createSvgFabricObject(layer);
  const fitScaleX = layer.width / positiveDimension(svgObject.width);
  const fitScaleY = layer.height / positiveDimension(svgObject.height);

  return applyLayerRuntimeOptions(svgObject, layer, "svg", fitScaleX, fitScaleY);
}

async function createSvgFabricObject(layer: Extract<SupportedEditorLayer, { type: "svg" }>) {
  const svgOutput = layer.inlineSvg
    ? await loadSVGFromString(layer.inlineSvg)
    : await loadSVGFromURL(resolveAssetUrl(layer.assetRef?.path ?? ""));
  const svgObjects = svgOutput.objects.filter(
    (object): object is FabricObject => object !== null,
  );

  if (svgObjects.length === 0) {
    throw new Error("SVG did not contain renderable vector objects");
  }

  return util.groupSVGElements(svgObjects, svgOutput.options);
}

function applyLayerRuntimeOptions(
  object: FabricObject,
  layer: SupportedEditorLayer,
  fabricType: SupportedFabricType,
  fitScaleX: number,
  fitScaleY: number,
): EditorFabricObject {
  object.set({
    left: layer.x,
    top: layer.y,
    scaleX: layer.scaleX * fitScaleX,
    scaleY: layer.scaleY * fitScaleY,
    angle: layer.rotation,
    opacity: layer.opacity,
    visible: layer.visible,
    selectable: !layer.locked,
    evented: !layer.locked,
    hasControls: !layer.locked,
    lockMovementX: layer.locked,
    lockMovementY: layer.locked,
    lockScalingX: layer.locked,
    lockScalingY: layer.locked,
    lockRotation: layer.locked,
  });
  object.setCoords();

  const runtimeObject = object as EditorFabricObject;
  runtimeObject.layerId = layer.id;
  runtimeObject.layerName = layer.name;
  runtimeObject.layerZIndex = layer.zIndex;
  runtimeObject.layerType = layer.type;
  runtimeObject.fabricType = fabricType;
  runtimeObject.modelWidth = layer.width;
  runtimeObject.modelHeight = layer.height;
  runtimeObject.fitScaleX = fitScaleX;
  runtimeObject.fitScaleY = fitScaleY;

  return runtimeObject;
}

function createMissingLayerPlaceholder(layer: SupportedEditorLayer): EditorFabricObject {
  const object = new FabricText(`${layer.type.toUpperCase()} missing`, {
    fontFamily: "Inter, sans-serif",
    fontSize: 18,
    fill: "#7a2e2e",
    backgroundColor: "#ffe8e8",
  });

  return applyLayerRuntimeOptions(object, layer, layer.type, 1, 1);
}

function createSnapshotFromFabricObject(
  object: FabricObject,
): FabricLayerObjectSnapshot | null {
  if (!isEditorFabricObject(object)) {
    return null;
  }

  return {
    layerId: object.layerId,
    layerType: object.layerType,
    fabricType: object.fabricType,
    name: object.layerName,
    left: object.left ?? 0,
    top: object.top ?? 0,
    width: object.modelWidth,
    height: object.modelHeight,
    scaleX: positiveDimension(object.scaleX) / object.fitScaleX,
    scaleY: positiveDimension(object.scaleY) / object.fitScaleY,
    angle: object.angle ?? 0,
    opacity: object.opacity ?? 1,
    visible: object.visible ?? true,
    locked: !object.selectable,
    selectable: object.selectable ?? true,
    evented: object.evented ?? true,
    zIndex: object.layerZIndex,
  };
}

function restoreActiveObject(fabricCanvas: Canvas, selectedLayerId: string | null) {
  if (!selectedLayerId) {
    fabricCanvas.discardActiveObject();
    return;
  }

  const activeObject = fabricCanvas
    .getObjects()
    .find((object) => isEditorFabricObject(object) && object.layerId === selectedLayerId);

  if (activeObject && activeObject.selectable && activeObject.visible) {
    fabricCanvas.setActiveObject(activeObject);
  } else {
    fabricCanvas.discardActiveObject();
  }
}

function isEditorFabricObject(object: FabricObject | undefined): object is EditorFabricObject {
  return Boolean(
    object &&
      "layerId" in object &&
      "layerName" in object &&
      "layerZIndex" in object &&
      "layerType" in object &&
      "fabricType" in object &&
      "modelWidth" in object &&
      "modelHeight" in object,
  );
}

function resolveAssetUrl(source: string): string {
  if (
    source.startsWith("data:") ||
    source.startsWith("http://") ||
    source.startsWith("https://") ||
    source.startsWith("blob:") ||
    source.startsWith("/")
  ) {
    return source;
  }

  return source;
}

function positiveDimension(value: number | undefined): number {
  return Number.isFinite(value) && value && value > 0 ? value : 1;
}
