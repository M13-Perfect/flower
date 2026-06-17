import type { CanvasSpec } from "@flower/design-core";

export interface CanvasViewportBounds {
  width: number;
  height: number;
}

export interface CanvasViewport {
  displayWidth: number;
  displayHeight: number;
  scale: number;
  scaled: boolean;
  zoomLabel: string;
}

export function calculateCanvasViewport(
  canvas: Pick<CanvasSpec, "width" | "height">,
  bounds: CanvasViewportBounds,
): CanvasViewport {
  const safeCanvasWidth = positive(canvas.width, 1);
  const safeCanvasHeight = positive(canvas.height, 1);
  const safeBoundsWidth = positive(bounds.width, safeCanvasWidth);
  const safeBoundsHeight = positive(bounds.height, safeCanvasHeight);
  const rawScale = Math.min(1, safeBoundsWidth / safeCanvasWidth, safeBoundsHeight / safeCanvasHeight);
  const scale = roundScale(rawScale);
  const displayWidth = Math.max(1, Math.round(safeCanvasWidth * scale));
  const displayHeight = Math.max(1, Math.round(safeCanvasHeight * scale));

  return {
    displayHeight,
    displayWidth,
    scale,
    scaled: scale < 1,
    zoomLabel: `${Math.round(scale * 100)}%`,
  };
}

function positive(value: number, fallback: number): number {
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function roundScale(value: number): number {
  return Number(value.toFixed(6));
}
