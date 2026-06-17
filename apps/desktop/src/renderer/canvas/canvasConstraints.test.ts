import { describe, expect, it } from "vitest";

import { constrainCanvasObjectBox } from "./canvasConstraints";

describe("canvas object constraints", () => {
  it("allows horizontal movement for text boxes that fit the canvas", () => {
    const next = constrainCanvasObjectBox(
      { width: 800, height: 600, unit: "px", background: { type: "solid", color: "#fff" } },
      {
        left: 260,
        top: 90,
        modelWidth: 220,
        modelHeight: 80,
        scaleX: 1,
        scaleY: 1,
        fitScaleX: 1,
        fitScaleY: 1,
      },
      { scaleToFit: false },
    );

    expect(next.left).toBe(260);
    expect(next.top).toBe(90);
    expect(next.scaleX).toBe(1);
    expect(next.scaleY).toBe(1);
  });

  it("clamps movement at the right and bottom canvas edges without forcing x to zero", () => {
    const next = constrainCanvasObjectBox(
      { width: 800, height: 600, unit: "px", background: { type: "solid", color: "#fff" } },
      {
        left: 760,
        top: 580,
        modelWidth: 220,
        modelHeight: 80,
        scaleX: 1,
        scaleY: 1,
        fitScaleX: 1,
        fitScaleY: 1,
      },
      { scaleToFit: false },
    );

    expect(next.left).toBe(580);
    expect(next.top).toBe(520);
  });
});
