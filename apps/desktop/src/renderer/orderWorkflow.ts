import type { Layer, LayerDocument } from "@flower/design-core";

export function createOutputOrderName(document: LayerDocument, parsedCustomerName: string): string {
  const customerName = parsedCustomerName.trim();
  if (customerName) {
    return customerName;
  }
  return document.metadata.orderId?.trim() || document.jobId || document.documentId;
}

export function selectInitialEditableLayerId(document: LayerDocument): string | null {
  return findLayer(document.layers, (layer) => layer.slotId === "customer_name")?.id ?? document.layers[0]?.id ?? null;
}

export function createDxfDataUrl(mimeType: string, contentBase64: string): string {
  return `data:${mimeType};base64,${contentBase64}`;
}

function findLayer(layers: readonly Layer[], predicate: (layer: Layer) => boolean): Layer | null {
  for (const layer of layers) {
    if (predicate(layer)) {
      return layer;
    }
    if (layer.type === "group") {
      const child = findLayer(layer.children, predicate);
      if (child) {
        return child;
      }
    }
  }
  return null;
}
