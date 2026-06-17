import { describe, expect, it } from "vitest";

import { calculateCanvasViewport } from "./canvasViewport";

describe("canvas viewport", () => {
  it("keeps small canvases at their real editing size", () => {
    expect(
      calculateCanvasViewport(
        { width: 900, height: 620 },
        { width: 1000, height: 720 },
      ),
    ).toEqual({
      displayHeight: 620,
      displayWidth: 900,
      scale: 1,
      scaled: false,
      zoomLabel: "100%",
    });
  });

  it("fits large production canvases inside the available drawing panel", () => {
    expect(
      calculateCanvasViewport(
        { width: 3000, height: 3000 },
        { width: 625, height: 700 },
      ),
    ).toEqual({
      displayHeight: 625,
      displayWidth: 625,
      scale: 0.208333,
      scaled: true,
      zoomLabel: "21%",
    });
  });
});
