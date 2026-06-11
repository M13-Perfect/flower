from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    text: str = ""
    month: int | None = None
    font: int | None = None
    flower: int | None = None
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0
    birth_month: str | None = None
    flower_name: str | None = None
    font_design: str | None = None
    personalization_raw: str | None = None
    personalization_type: str = "unknown"
    selected_flower_asset: str | None = None
    selected_font_asset: str | None = None
    parse_confidence: float = 0.0
    asset_confidence: float = 0.0


@dataclass(frozen=True)
class AIParseConfig:
    enabled: bool = True
    prefer_ai: bool = False
    api_key: str | None = None
    model: str | None = None
    project: str | None = None
    organization: str | None = None
    provider: str = "openai"
    base_url: str | None = None
    timeout: float = 20.0


@dataclass(frozen=True)
class EngravingLayout:
    canvas_width: int = 1732
    canvas_height: int = 1280
    flower_x: int = 310
    flower_y: int = 40
    flower_width: int = 1060
    flower_height: int = 1060
    text_x: int = 808
    text_y: int = 830
    text_width: int = 804
    text_height: int = 260
    text_size: int = 190


@dataclass(frozen=True)
class BirthFlowerDesign:
    text: str
    month: int
    font: int
    flower: int
    flower_asset_path: Path | None = None
    font_path: Path | None = None
    flower_name: str = ""
    layout: EngravingLayout = field(default_factory=EngravingLayout)
    personalization_type: str = "unknown"
    glyph_overrides: dict[int, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class FlowerAsset:
    name: str
    month: int
    flower: int
    path: Path
    asset_key: str = ""
    display_name: str = ""
    category: str = "birth_flower"
    is_vector_safe: bool = True
    embedded_raster_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class FontAsset:
    name: str
    index: int
    path: Path
    font_design: str = ""
    family_name: str = ""
    file_size: int = 0
    has_ending_glyphs: bool = False


def _new_layer_id() -> str:
    """生成本地文档图层 ID；不依赖外部服务，方便测试和跨平台运行。"""
    import uuid

    return uuid.uuid4().hex


@dataclass
class Layer:
    """Photoshop 风格图层基类，所有可编辑对象都继承这些通用变换字段。"""

    id: str = field(default_factory=_new_layer_id)
    name: str = "Layer"
    type: str = "base"
    x: float = 0.0
    y: float = 0.0
    width: float = 100.0
    height: float = 100.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0
    opacity: float = 1.0
    visible: bool = True
    locked: bool = False
    z_index: int = 0

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """返回当前图层未旋转包围盒，供命中测试、选择框和基础缩放使用。"""
        return (self.x, self.y, self.x + self.width * self.scale_x, self.y + self.height * self.scale_y)


@dataclass
class ImageLayer(Layer):
    """PNG/JPG/SVG 素材图层；每个素材图层持有独立几何参数和素材信息。"""

    path: Path | None = None
    type: str = "image"
    preserve_svg: bool = True
    material_id: str = ""
    material_name: str = ""
    lock_aspect_ratio: bool = True


@dataclass
class TextLayer(Layer):
    """可编辑文本图层；保留原始文字，并用 render_text 承载字形替换后的视觉输出。"""

    text: str = "Text"
    original_text: str = ""
    render_text: str = ""
    glyph_overrides: dict[int, dict[str, Any]] = field(default_factory=dict)
    font_path: Path | None = None
    font_size: int = 120
    color: str = "#111111"
    fill_color: str = ""
    align: str = "center"
    vertical_align: str = "middle"
    line_spacing: float = 1.2
    tracking: float = 0.0
    letter_spacing: float = 0.0
    text_box_width: float = 400.0
    text_box_height: float = 160.0
    type: str = "text"

    def __post_init__(self) -> None:
        """兼容旧 TextLayer：旧数据只有 text 时，迁移出 original_text/render_text。"""
        if not self.original_text:
            self.original_text = self.text
            logger.info("迁移旧文本图层到 original_text：layer_id=%s", self.id)
        if not self.render_text:
            self.render_text = self.original_text
        if self.text != self.original_text:
            self.text = self.original_text
        # 新旧字段并存：旧 UI 仍读写 color/letter_spacing，新渲染器使用 fill_color/tracking。
        if not self.fill_color:
            self.fill_color = self.color or "#111111"
        if not self.color:
            self.color = self.fill_color or "#111111"
        if self.tracking == 0 and self.letter_spacing != 0:
            self.tracking = self.letter_spacing
        elif self.letter_spacing == 0 and self.tracking != 0:
            self.letter_spacing = self.tracking

    def display_text(self) -> str:
        """UI 可读文本：避免直接展示 PUA 乱码。"""
        return f"{self.original_text}（已应用特殊字形）" if self.glyph_overrides else self.original_text


@dataclass
class GlyphLayer(Layer):
    """预留 PUA 字形/装饰字形图层，后续可接入 glyph_service 的人工字形选择。"""

    codepoint: str | None = None
    font_path: Path | None = None
    type: str = "glyph"


@dataclass
class Document:
    """多图层文档，替代旧版单素材 current_asset 工作流。"""

    canvas_width: int = 1732
    canvas_height: int = 1280
    layers: list[Layer] = field(default_factory=list)
    selected_layer_id: str | None = None

    def sorted_layers(self) -> list[Layer]:
        """按 z_index 和列表顺序得到真实渲染顺序，低层先画，高层后画。"""
        indexed_layers = sorted(enumerate(self.layers), key=lambda item: (item[1].z_index, item[0]))
        return [layer for _, layer in indexed_layers]

    def normalize_z_indexes(self) -> None:
        """图层重排后同步 z_index，避免渲染顺序和面板顺序不一致。"""
        for index, layer in enumerate(self.layers):
            layer.z_index = index

    def selected_layer(self) -> Layer | None:
        return self.layer_by_id(self.selected_layer_id)

    def layer_by_id(self, layer_id: str | None) -> Layer | None:
        if layer_id is None:
            return None
        return next((layer for layer in self.layers if layer.id == layer_id), None)


@dataclass
class HistoryManager:
    """预留撤销/重做栈；当前 UI 先接入快捷键，后续可存储 Document 快照。"""

    undo_stack: list[Document] = field(default_factory=list)
    redo_stack: list[Document] = field(default_factory=list)


def add_image_layer(
    document: Document,
    path: Path | str,
    *,
    name: str | None = None,
    x: float = 0,
    y: float = 0,
    width: float = 300,
    height: float = 300,
    material_id: str = "",
    material_name: str = "",
    lock_aspect_ratio: bool = True,
) -> ImageLayer:
    """添加素材永远创建新 ImageLayer，绝不覆盖已有图层或旧选择。"""
    asset_path = Path(path)
    layer = ImageLayer(
        name=name or asset_path.stem,
        path=asset_path,
        x=x,
        y=y,
        width=width,
        height=height,
        z_index=len(document.layers),
        material_id=material_id or asset_path.stem,
        material_name=material_name or name or asset_path.stem,
        lock_aspect_ratio=lock_aspect_ratio,
    )
    document.layers.append(layer)
    document.selected_layer_id = layer.id
    document.normalize_z_indexes()
    return layer


def add_text_layer(
    document: Document,
    text: str,
    *,
    font_path: Path | str | None = None,
    name: str | None = None,
    x: float = 0,
    y: float = 0,
    width: float = 400,
    height: float = 160,
    font_size: int = 120,
) -> TextLayer:
    """添加可编辑 TextLayer；文本属性保留在图层上，便于属性面板反复修改。"""
    layer = TextLayer(
        name=name or "Text",
        text=text,
        original_text=text,
        render_text=text,
        font_path=Path(font_path) if font_path else None,
        x=x,
        y=y,
        width=width,
        height=height,
        text_box_width=width,
        text_box_height=height,
        font_size=font_size,
        z_index=len(document.layers),
    )
    document.layers.append(layer)
    document.selected_layer_id = layer.id
    document.normalize_z_indexes()
    return layer


def delete_layer(document: Document, layer_id: str | None) -> Layer | None:
    """删除图层并修复 selected_layer_id；锁定图层不可删除。"""
    layer = document.layer_by_id(layer_id)
    if layer is None or layer.locked:
        return None
    index = document.layers.index(layer)
    removed = document.layers.pop(index)
    document.normalize_z_indexes()
    if document.layers:
        next_index = min(index, len(document.layers) - 1)
        document.selected_layer_id = document.layers[next_index].id
    else:
        document.selected_layer_id = None
    return removed


def move_layer(document: Document, layer_id: str | None, action: str) -> bool:
    """支持上移、下移、置顶、置底；面板变化后渲染顺序随 z_index 更新。"""
    layer = document.layer_by_id(layer_id)
    if layer is None:
        return False
    old_index = document.layers.index(layer)
    new_index = old_index
    if action == "up":
        new_index = min(len(document.layers) - 1, old_index + 1)
    elif action == "down":
        new_index = max(0, old_index - 1)
    elif action == "top":
        new_index = len(document.layers) - 1
    elif action == "bottom":
        new_index = 0
    else:
        return False
    if new_index == old_index:
        return False
    document.layers.pop(old_index)
    document.layers.insert(new_index, layer)
    document.normalize_z_indexes()
    document.selected_layer_id = layer.id
    return True


def hit_test(document: Document, x: float, y: float) -> Layer | None:
    """从顶层向底层命中测试，只选择可见且未锁定的基础包围盒。"""
    for layer in reversed(document.sorted_layers()):
        if not layer.visible or layer.locked:
            continue
        left, top, right, bottom = layer.bounds
        if left <= x <= right and top <= y <= bottom:
            return layer
    return None
