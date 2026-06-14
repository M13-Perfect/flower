from __future__ import annotations

from dataclasses import dataclass, field

from models import TextLayer
from text_renderer import TextRenderResult, TextRenderer


@dataclass
class CanvasTextItem:
    """画布文本项；普通状态只管理 TextLayer 数据和 TextRenderer 图像。"""

    layer: TextLayer
    renderer: TextRenderer = field(default_factory=TextRenderer)

    def render(self) -> TextRenderResult:
        result = self.renderer.render_layer(self.layer)
        self.layer.render_text = result.render_text
        self.layer.glyph_overrides = result.glyph_overrides
        self.layer.raw_text = self.layer.original_text
        self.layer.text = self.layer.original_text
        return result

    def move_by(self, dx: float, dy: float) -> None:
        self.layer.x = max(0, self.layer.x + dx)
        self.layer.y = max(0, self.layer.y + dy)

    def resize_by(self, dx: float, dy: float, *, min_size: float = 20) -> None:
        width = max(min_size, self.layer.width + dx)
        height = max(min_size, self.layer.height + dy)
        self.layer.width = width
        self.layer.height = height
        # 文本框尺寸属于数据层；缩放后必须立刻同步，下一帧会用同一渲染器重绘。
        self.layer.text_box_width = width
        self.layer.text_box_height = height

    def preview_bounds(self, scale: float, offset_x: float, offset_y: float) -> tuple[float, float, float, float]:
        left, top, right, bottom = self.layer.bounds
        return (
            offset_x + left * scale,
            offset_y + top * scale,
            offset_x + right * scale,
            offset_y + bottom * scale,
        )


@dataclass
class FloatingTextEditor:
    """临时编辑层状态；控件本身不属于 Document，退出后必须销毁。"""

    layer_id: str
    original_text: str
    window_id: int | None = None
