import { describe, expect, it } from "vitest";

import {
  EXPORT_SETTINGS_SCHEMA_VERSION,
  LAYER_DOCUMENT_SCHEMA_VERSION,
  type LayerDocument,
} from "@flower/design-core";
import {
  createDxfDataUrl,
  createOutputOrderName,
  selectInitialEditableLayerId,
} from "./orderWorkflow";

describe("order workflow helpers", () => {
  it("uses parsed customer name as the output order name", () => {
    expect(createOutputOrderName(createDocument(), "Lacey")).toBe("Lacey");
  });

  it("falls back to document order id for output order name", () => {
    expect(createOutputOrderName(createDocument(), "")).toBe("order-1");
  });

  it("selects the customer text layer after applying a template", () => {
    expect(selectInitialEditableLayerId(createDocument())).toBe("layer_customer_name");
  });

  it("creates a DXF data URL from backend export content", () => {
    expect(createDxfDataUrl("application/dxf", "ZA==")).toBe("data:application/dxf;base64,ZA==");
  });
});

function createDocument(): LayerDocument {
  return {
    schemaVersion: LAYER_DOCUMENT_SCHEMA_VERSION,
    documentId: "doc-1",
    projectId: "project-1",
    jobId: "job-1",
    metadata: {
      orderId: "order-1",
      templateId: "birth-flower-card",
      templateVersion: "1.0.0",
      appVersion: "0.1.0",
      createdAt: "2026-06-12T00:00:00.000Z",
      updatedAt: "2026-06-12T00:00:00.000Z",
    },
    canvas: {
      width: 300,
      height: 200,
      unit: "px",
      background: { type: "solid", color: "#ffffff" },
    },
    exportSettings: {
      schemaVersion: EXPORT_SETTINGS_SCHEMA_VERSION,
      defaultFormats: ["svg", "png", "dxf"],
      svg: { preserveText: true, preserveVector: true, includeMetadata: true },
      png: { scale: 1, background: "canvas" },
      dxf: { textMode: "paths", units: "px" },
    },
    layers: [
      {
        id: "layer_flower",
        type: "svg",
        name: "Birth flower",
        visible: true,
        locked: false,
        exportable: true,
        zIndex: 1,
        opacity: 1,
        x: 0,
        y: 0,
        width: 10,
        height: 10,
        scaleX: 1,
        scaleY: 1,
        rotation: 0,
        slotId: "flower",
        tags: ["flower"],
        inlineSvg: "<svg></svg>",
        viewBox: { x: 0, y: 0, width: 10, height: 10 },
        preserveVector: true,
      },
      {
        id: "layer_customer_name",
        type: "text",
        name: "Customer name",
        visible: true,
        locked: false,
        exportable: true,
        zIndex: 2,
        opacity: 1,
        x: 0,
        y: 0,
        width: 100,
        height: 40,
        scaleX: 1,
        scaleY: 1,
        rotation: 0,
        slotId: "customer_name",
        tags: ["customer-text"],
        text: "Lacey",
        fontRef: { family: "Font 3", source: "asset", assetId: "font-3" },
        style: { fontSize: 24, fill: "#111111", align: "center", lineHeight: 1, letterSpacing: 0 },
        layout: { mode: "box", overflow: "shrink-to-fit" },
      },
    ],
  };
}
