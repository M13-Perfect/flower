import type { CanvasSpec } from "@flower/design-core";

export interface CanvasObjectBox {
  left: number;
  top: number;
  modelWidth: number;
  modelHeight: number;
  scaleX: number;
  scaleY: number;
  fitScaleX: number;
  fitScaleY: number;
}

export interface CanvasConstraintOptions {
  scaleToFit: boolean;
}

export function constrainCanvasObjectBox(
  canvas: CanvasSpec,
  object: CanvasObjectBox,
  options: CanvasConstraintOptions,
): CanvasObjectBox {
  let scaleX = positiveDimension(object.scaleX);
  let scaleY = positiveDimension(object.scaleY);
  const fitScaleX = positiveDimension(object.fitScaleX);
  const fitScaleY = positiveDimension(object.fitScaleY);
  const canvasWidth = positiveDimension(canvas.width);
  const canvasHeight = positiveDimension(canvas.height);

  let renderedWidth = renderedObjectSize(object.modelWidth, scaleX, fitScaleX);
  let renderedHeight = renderedObjectSize(object.modelHeight, scaleY, fitScaleY);

  if (options.scaleToFit && (renderedWidth > canvasWidth || renderedHeight > canvasHeight)) {
    const scaleRatio = Math.max(
      0.001,
      Math.min(canvasWidth / positiveDimension(renderedWidth), canvasHeight / positiveDimension(renderedHeight)),
    );
    scaleX *= scaleRatio;
    scaleY *= scaleRatio;
    renderedWidth = renderedObjectSize(object.modelWidth, scaleX, fitScaleX);
    renderedHeight = renderedObjectSize(object.modelHeight, scaleY, fitScaleY);
  }

  return {
    ...object,
    left: clampAxis(object.left, renderedWidth, canvasWidth),
    top: clampAxis(object.top, renderedHeight, canvasHeight),
    scaleX,
    scaleY,
  };
}

function renderedObjectSize(modelSize: number, scale: number, fitScale: number): number {
  return positiveDimension(modelSize) * (positiveDimension(scale) / positiveDimension(fitScale));
}

function clampAxis(position: number, size: number, containerSize: number): number {
  if (!Number.isFinite(position)) {
    return 0;
  }
  if (size >= containerSize) {
    return 0;
  }

  return Math.min(containerSize - size, Math.max(0, position));
}

function positiveDimension(value: number | undefined): number {
  return Number.isFinite(value) && value && value > 0 ? value : 1;
}
