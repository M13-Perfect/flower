from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def left(self) -> float:
        return self.x

    @property
    def top(self) -> float:
        return self.y

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height


@dataclass(frozen=True)
class FitTransform:
    draw_x: float
    draw_y: float
    scale_x: float
    scale_y: float

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return self.draw_x + x * self.scale_x, self.draw_y + y * self.scale_y


def fit_content_bbox_to_target_rect(
    content_bbox: Rect,
    target_rect: Rect,
    mode: str = "contain",
    align: tuple[float, float] = (0.5, 0.5),
) -> FitTransform:
    """把真实可见内容 bbox 放进目标矩形；核心是扣除 bbox 原点偏移。"""
    if content_bbox.width <= 0 or content_bbox.height <= 0:
        raise ValueError("content_bbox width/height must be positive")
    if target_rect.width <= 0 or target_rect.height <= 0:
        raise ValueError("target_rect width/height must be positive")
    if mode not in {"contain", "cover", "stretch"}:
        raise ValueError("mode must be contain, cover, or stretch")

    sx = target_rect.width / content_bbox.width
    sy = target_rect.height / content_bbox.height
    if mode == "contain":
        sx = sy = min(sx, sy)
    elif mode == "cover":
        sx = sy = max(sx, sy)

    align_x, align_y = align
    draw_x = target_rect.x + (target_rect.width - content_bbox.width * sx) * align_x - content_bbox.x * sx
    draw_y = target_rect.y + (target_rect.height - content_bbox.height * sy) * align_y - content_bbox.y * sy
    return FitTransform(draw_x=draw_x, draw_y=draw_y, scale_x=sx, scale_y=sy)
