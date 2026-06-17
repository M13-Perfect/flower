from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import logging

from production import ProductionParams

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
    # 新素材库体系：解析器把订单落到「哪个库 + 库内 key」，供图层引用与跨库识别（见 order_catalog）。
    material_library_id: str = ""
    material_key: str = ""
    font_library_id: str = ""
    font_key: str = ""


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
    # 全局默认字体样式（新增）：每个文本图层可覆盖（TextLayer.bold/.. = None 时继承这里）。
    # 加粗对脚本字体无真粗体字重，用「轮廓外扩」实现；bold_strength = 外扩量占字号的比例，
    # 预览端 stroke_width_px=round(strength*font_size)、矢量端 offset=strength*font_size，单位一致。
    bold: bool = False
    underline: bool = False
    italic: bool = False
    bold_strength: float = 0.016  # 经预览实测：≈stroke 2px@104，清晰可读且字怀不糊（0.028 起糊）
    letter_spacing: float = 0.0  # 字间距全局默认（已有 per-layer 全链路；建层时烘进图层）


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


def _coerce_production(value: Any) -> ProductionParams | None:
    """容忍生产参数以 dict（反序列化）或已是 ProductionParams 传入；其它一律视为无覆盖。"""
    if value is None or isinstance(value, ProductionParams):
        return value
    if isinstance(value, dict):
        return ProductionParams.from_mapping(value)
    return None


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
    # 新素材库体系：记录「引用哪个库 + 库内素材 key」，便于跨库引用与订单解析回查；
    # production = 该图层的生产参数 override（None=回落到素材/库/产品默认，见 production.resolve_chain）。
    library_id: str = ""
    material_key: str = ""
    production: ProductionParams | None = None

    def __post_init__(self) -> None:
        """旧素材图层只有 material_id：迁移出 material_key；production 容忍 dict 反序列化。"""
        if not self.material_key and self.material_id:
            self.material_key = self.material_id
        self.production = _coerce_production(self.production)


@dataclass
class TextLayer(Layer):
    """可编辑文本图层；保留原始文字，并用 render_text 承载字形替换后的视觉输出。"""

    text: str = "Text"
    raw_text: str = ""
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
    # 新素材库体系：文本图层记录引用的字体库 + 字体 key + 生产参数 override。
    font_library_id: str = ""
    font_key: str = ""
    production: ProductionParams | None = None
    # 字体样式 override（新增）：None=继承全局 EngravingLayout 默认；非 None=本图层显式取值。
    # 用 resolve_text_style(layer, layout) 解析最终样式，预览/导出共用同一结果。
    bold: bool | None = None
    underline: bool | None = None
    italic: bool | None = None
    bold_strength: float | None = None

    def __post_init__(self) -> None:
        """兼容旧 TextLayer：旧数据只有 text 时，迁移出 original_text/render_text。"""
        if self.raw_text and not self.original_text:
            self.original_text = self.raw_text
        if not self.original_text:
            self.original_text = self.text
            logger.info("迁移旧文本图层到 original_text：layer_id=%s", self.id)
        if not self.raw_text:
            self.raw_text = self.original_text
        if not self.render_text:
            self.render_text = self.original_text
        if self.text != self.original_text:
            self.text = self.original_text
        normalized_overrides: dict[int, dict[str, Any]] = {}
        for raw_index, override in (self.glyph_overrides or {}).items():
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                logger.warning("忽略无效 glyph_overrides key：layer_id=%s key=%r", self.id, raw_index)
                continue
            if isinstance(override, dict):
                normalized_overrides[index] = override
        self.glyph_overrides = normalized_overrides
        # 新旧字段并存：旧 UI 仍读写 color/letter_spacing，新渲染器使用 fill_color/tracking。
        if not self.fill_color:
            self.fill_color = self.color or "#111111"
        if not self.color:
            self.color = self.fill_color or "#111111"
        if self.tracking == 0 and self.letter_spacing != 0:
            self.tracking = self.letter_spacing
        elif self.letter_spacing == 0 and self.tracking != 0:
            self.letter_spacing = self.tracking
        # 旧文本图层只有 font_path：best-effort 迁移出 font_key（取文件名），生产参数容忍 dict。
        if not self.font_key and self.font_path is not None:
            self.font_key = Path(self.font_path).stem
        self.production = _coerce_production(self.production)

    def display_text(self) -> str:
        """UI 可读文本：避免直接展示 PUA 乱码。"""
        return f"{self.original_text}（已应用特殊字形）" if self.glyph_overrides else self.original_text


@dataclass(frozen=True)
class ResolvedTextStyle:
    """文本图层解析后的最终字体样式（已合并全局默认 + 图层 override）。预览/导出共用。"""

    bold: bool = False
    underline: bool = False
    italic: bool = False
    bold_strength: float = 0.0  # 已解析：bold=False 时恒为 0，下游无需再判 bold


def resolve_text_style(layer: "TextLayer", layout: EngravingLayout) -> ResolvedTextStyle:
    """解析文本图层最终字体样式：图层字段非 None 时优先，否则继承全局 EngravingLayout 默认。

    加粗强度(bold_strength，占字号比例)仅在最终 bold=True 时有效，否则归零——让 svg/dxf/预览
    下游只看 ResolvedTextStyle 即可，不必各自再判断 bold 与回落链。
    """

    def pick(name: str) -> Any:
        override = getattr(layer, name, None)
        return getattr(layout, name) if override is None else override

    bold = bool(pick("bold"))
    underline = bool(pick("underline"))
    italic = bool(pick("italic"))
    try:
        strength = float(pick("bold_strength"))
    except (TypeError, ValueError):
        strength = float(layout.bold_strength)
    return ResolvedTextStyle(bold=bold, underline=underline, italic=italic, bold_strength=strength if bold else 0.0)


DEFAULT_BOLD_STRENGTH = 0.016


def layer_text_style(layer: "TextLayer") -> ResolvedTextStyle:
    """从图层自身读已解析样式（None→关；强度缺省 DEFAULT_BOLD_STRENGTH）。预览(text_renderer)与
    矢量端(desktop_export)共用此读法，保证两端一致。全局默认在建层时由 resolve_text_style 烘进图层。"""
    bold = bool(getattr(layer, "bold", None) or False)
    underline = bool(getattr(layer, "underline", None) or False)
    italic = bool(getattr(layer, "italic", None) or False)
    raw = getattr(layer, "bold_strength", None)
    try:
        strength = DEFAULT_BOLD_STRENGTH if raw is None else float(raw)
    except (TypeError, ValueError):
        strength = DEFAULT_BOLD_STRENGTH
    return ResolvedTextStyle(bold=bold, underline=underline, italic=italic, bold_strength=strength if bold else 0.0)


@dataclass
class GlyphLayer(Layer):
    """预留 PUA 字形/装饰字形图层，后续可接入 glyph_service 的人工字形选择。"""

    codepoint: str | None = None
    font_path: Path | None = None
    type: str = "glyph"


@dataclass
class GroupLayer(Layer):
    """PS 风格图组：容器图层，``children`` 是嵌套子图层（可再含图组）。

    组的 ``visible`` / ``locked`` 向下级联——隐藏组=整组不渲染，锁定组=子层不可编辑/命中。
    渲染/导出始终经 ``Document.flat_render_layers()`` 摊平成叶子图层；**无图组时摊平结果与
    旧 ``sorted_layers()`` 完全一致，金标/批量字节不变**。
    """

    type: str = "group"
    children: list[Layer] = field(default_factory=list)
    collapsed: bool = False


@dataclass
class Document:
    """多图层文档，替代旧版单素材 current_asset 工作流。"""

    canvas_width: int = 1732
    canvas_height: int = 1280
    layers: list[Layer] = field(default_factory=list)
    selected_layer_id: str | None = None

    def sorted_layers(self) -> list[Layer]:
        """按 z_index 和列表顺序得到顶层渲染顺序，低层先画，高层后画（仅顶层，不摊平图组）。"""
        indexed_layers = sorted(enumerate(self.layers), key=lambda item: (item[1].z_index, item[0]))
        return [layer for _, layer in indexed_layers]

    def iter_all_layers(self):
        """深度优先遍历所有图层（含图组及其子层），用于查找/统计。"""
        def walk(layers: list[Layer]):
            for layer in layers:
                yield layer
                if isinstance(layer, GroupLayer):
                    yield from walk(layer.children)
        yield from walk(self.layers)

    def _flat_leaves(self) -> list[tuple[Layer, bool]]:
        """摊平成 (叶子图层, 有效锁定)，按渲染顺序；只含「祖先组都可见」的叶子。

        无图组时与 ``sorted_layers()`` 顺序、对象完全一致——是导出/金标字节不变的关键。
        """
        result: list[tuple[Layer, bool]] = []

        def walk(layers: list[Layer], ancestors_visible: bool, ancestors_locked: bool) -> None:
            ordered = [layer for _, layer in sorted(enumerate(layers), key=lambda it: (it[1].z_index, it[0]))]
            for layer in ordered:
                if isinstance(layer, GroupLayer):
                    walk(layer.children, ancestors_visible and layer.visible, ancestors_locked or layer.locked)
                elif ancestors_visible:
                    result.append((layer, ancestors_locked or layer.locked))

        walk(self.layers, True, False)
        return result

    def flat_render_layers(self) -> list[Layer]:
        """渲染/导出统一入口：摊平成叶子图层（隐藏图组整组跳过）。无图组时等于 sorted_layers()。"""
        return [layer for layer, _locked in self._flat_leaves()]

    def container_of(self, layer_id: str | None) -> tuple[list[Layer] | None, Layer | None]:
        """返回直接包含该图层的列表（顶层或某图组的 children）+ 图层；找不到返回 (None, None)。"""
        if layer_id is None:
            return None, None

        def walk(layers: list[Layer]) -> tuple[list[Layer] | None, Layer | None]:
            for layer in layers:
                if layer.id == layer_id:
                    return layers, layer
                if isinstance(layer, GroupLayer):
                    found_container, found_layer = walk(layer.children)
                    if found_container is not None:
                        return found_container, found_layer
            return None, None

        return walk(self.layers)

    def normalize_z_indexes(self) -> None:
        """图层重排后递归同步各层级 z_index，避免渲染顺序和面板顺序不一致。"""
        def walk(layers: list[Layer]) -> None:
            for index, layer in enumerate(layers):
                layer.z_index = index
                if isinstance(layer, GroupLayer):
                    walk(layer.children)
        walk(self.layers)

    def selected_layer(self) -> Layer | None:
        return self.layer_by_id(self.selected_layer_id)

    def layer_by_id(self, layer_id: str | None) -> Layer | None:
        if layer_id is None:
            return None
        return next((layer for layer in self.iter_all_layers() if layer.id == layer_id), None)


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
    library_id: str = "",
    material_key: str = "",
    production: ProductionParams | None = None,
) -> ImageLayer:
    """添加素材永远创建新 ImageLayer，绝不覆盖已有图层或旧选择。

    新素材库体系：传 ``library_id``/``material_key`` 记录该图层引用的库与素材；
    ``production`` 为该图层生产参数 override（None=回落到素材/库/产品默认）。
    """
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
        library_id=library_id,
        material_key=material_key,
        production=production,
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
    font_library_id: str = "",
    font_key: str = "",
    production: ProductionParams | None = None,
) -> TextLayer:
    """添加可编辑 TextLayer；文本属性保留在图层上，便于属性面板反复修改。

    新素材库体系：传 ``font_library_id``/``font_key`` 记录引用的字体库与字体；
    ``production`` 为该图层生产参数 override（None=回落到库/产品默认）。
    """
    layer = TextLayer(
        name=name or "Text",
        text=text,
        raw_text=text,
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
        font_library_id=font_library_id,
        font_key=font_key,
        production=production,
    )
    document.layers.append(layer)
    document.selected_layer_id = layer.id
    document.normalize_z_indexes()
    return layer


def delete_layer(document: Document, layer_id: str | None) -> Layer | None:
    """删除图层（在其所属容器内）并修复 selected_layer_id；锁定图层不可删除。"""
    container, layer = document.container_of(layer_id)
    if container is None or layer is None or layer.locked:
        return None
    index = container.index(layer)
    removed = container.pop(index)
    document.normalize_z_indexes()
    if document.layers:
        sibling = container or document.layers
        if sibling:
            next_index = min(index, len(sibling) - 1)
            document.selected_layer_id = sibling[next_index].id
        else:
            document.selected_layer_id = document.layers[-1].id
    else:
        document.selected_layer_id = None
    return removed


def move_layer(document: Document, layer_id: str | None, action: str) -> bool:
    """在图层所属容器内上移/下移/置顶/置底；渲染顺序随 z_index 更新（图组内也适用）。"""
    container, layer = document.container_of(layer_id)
    if container is None or layer is None:
        return False
    old_index = container.index(layer)
    new_index = old_index
    if action == "up":
        new_index = min(len(container) - 1, old_index + 1)
    elif action == "down":
        new_index = max(0, old_index - 1)
    elif action == "top":
        new_index = len(container) - 1
    elif action == "bottom":
        new_index = 0
    else:
        return False
    if new_index == old_index:
        return False
    container.pop(old_index)
    container.insert(new_index, layer)
    document.normalize_z_indexes()
    document.selected_layer_id = layer.id
    return True


def group_layers(document: Document, layer_ids: list[str], *, name: str = "图组") -> "GroupLayer | None":
    """把指定（同一容器内的）图层包成 GroupLayer，插到原最上面成员的位置。返回新组或 None。"""
    ids = [lid for lid in layer_ids if lid]
    if not ids:
        return None
    container, _first = document.container_of(ids[0])
    if container is None:
        return None
    id_set = set(ids)
    members = [layer for layer in container if layer.id in id_set]
    if not members:
        return None
    insert_at = min(container.index(member) for member in members)
    for member in members:
        container.remove(member)
    group = GroupLayer(name=name, children=members)
    container.insert(insert_at, group)
    document.normalize_z_indexes()
    document.selected_layer_id = group.id
    return group


def ungroup_layer(document: Document, group_id: str | None) -> list[Layer]:
    """解散图组，把子层按原顺序放回原位置；返回被放回的子层列表。"""
    container, group = document.container_of(group_id)
    if container is None or not isinstance(group, GroupLayer):
        return []
    at = container.index(group)
    container.remove(group)
    children = list(group.children)
    for offset, child in enumerate(children):
        container.insert(at + offset, child)
    document.normalize_z_indexes()
    if children:
        document.selected_layer_id = children[0].id
    return children


def hit_test(document: Document, x: float, y: float) -> Layer | None:
    """从顶层向底层命中测试，只选可见且未锁定（含图组级联锁定）的叶子图层包围盒。"""
    for layer, effective_locked in reversed(document._flat_leaves()):
        if not layer.visible or effective_locked:
            continue
        left, top, right, bottom = layer.bounds
        if left <= x <= right and top <= y <= bottom:
            return layer
    return None
