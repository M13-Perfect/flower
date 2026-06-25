"""Content Provider 注册表（Layer System v2 · Packet 3 · ADR-001）。

把散落在 ``desktop_export`` / ``ui_app`` 里的 ``isinstance`` 类型分发收敛为一个模块级
注册表。**本 Packet 只搬「调用点」，不动任何渲染/导出算法**：每个 provider 的
``render_export`` / ``render_preview`` 都**委托回现有函数**（desktop_export 的层 builder、
App 的 ``_draw_*_preview`` 绑定方法），因此导出字节与预览像素均不可能漂移
（Packet 0 字节门禁、test_dxf_golden_lock 保持绿）。

§7 设想 provider 还应有 create_default / validate / migrate / measure /
inspector_sections / capabilities / resource_dependencies / serialize 等方法——这些
**留给后续 Packet**（见各方法 docstring 标注），Packet 3 一律不实现（YAGNI）。
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:  # 仅类型标注用，避免运行时 import 环（providers 不该拖进重模块）。
    from models import Layer


def _is_finite_number(value: object) -> bool:
    """有限实数判定（拦 None/字符串/bool/NaN/inf）。"""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return math.isfinite(value)


def _validate_geometry(layer: "Layer") -> list[str]:
    """所有层共用的几何校验（§16「数值非法」行）：宽/高必须是有限正数；x/y 只拦 NaN/inf/非数（允许负，画布外）。"""
    errors: list[str] = []
    width = getattr(layer, "width", None)
    height = getattr(layer, "height", None)
    if not _is_finite_number(width) or width <= 0:
        errors.append(f"非法宽度: {width!r}")
    if not _is_finite_number(height) or height <= 0:
        errors.append(f"非法高度: {height!r}")
    for axis in ("x", "y"):
        value = getattr(layer, axis, None)
        if value is not None and not _is_finite_number(value):
            errors.append(f"非法坐标 {axis}: {value!r}")
    return errors


# ---------------------------------------------------------------------------
# Inspector 声明结构（Layer System v2 · Packet 6 · §10）
#
# 属性栏内容**由 ContentProvider 声明，不硬编码进悬浮栏组件**（RFC §7 硬要求）。
# 用最小的 NamedTuple 承载「显示哪些字段」的声明：``var`` 复用现有共享 var
# （ADR-002 硬规则，绝不私造数据副本）；``attr`` 是该字段对应的 layer 属性名
# （供未来字段在没有共享 var 时直接绑 layer 属性，本轮仅声明）。
# ---------------------------------------------------------------------------
class InspectorField(NamedTuple):
    """属性栏单个字段声明（绑定一个共享 var 或一个 layer 属性）。"""

    key: str                       # 逻辑键，如 'font_size' / 'x'（也是 layer 属性名兜底）
    label: str                     # 显示名，如 '字号'
    widget: str                    # 'number'|'slider'|'select'|'color'|'toggle'|'segmented'
    var_name: str = ""             # App 上共享 var 的属性名，如 'layer_font_size_var'（ADR-002）
    attr: str = ""                 # 无共享 var 时直接绑的 layer 属性名（本轮多为声明用）
    step: float | None = None
    min: float | None = None       # noqa: A003  字段名与 RFC §10 对齐
    max: float | None = None       # noqa: A003
    unit: str = ""


class InspectorSection(NamedTuple):
    """属性栏一个分组（标题 + 字段列表）。悬浮栏只渲染 section 列表，不认识具体字段。"""

    title: str
    fields: list[InspectorField]


class ContentProvider:
    """每种内容层「创建/校验/迁移/渲染/测量/属性/能力/资源/序列化」差异的薄包装。

    Packet 3 只接线两个方法：``render_export`` 与 ``render_preview``，均委托现有实现。
    其余按 §7 声明为占位 stub，由后续 Packet 落地（不在本轮实现）。
    """

    provider_id: str = ""

    # --- Packet 3 接线：委托现有实现，算法不变 ---
    def render_export(self, layer: "Layer", ctx: dict[str, Any]) -> dict[str, Any] | None:
        """导出该层 → services/api 图层 dict（None=跳过，沿用 Packet 2 未绑跳过语义）。"""
        raise NotImplementedError

    def render_preview(self, layer: "Layer", ctx: dict[str, Any]) -> None:
        """在画布上预览该层；委托 App 现有 ``_draw_*_preview`` 绑定方法。"""
        raise NotImplementedError

    # --- 以下为 §7 设想接口，后续 Packet 落地（本轮不实现）---
    def create_default(self, document, **kw):  # noqa: D401, ANN001, ANN201
        """Packet 6：复用 models.add_text_layer/add_image_layer。本轮未实现。"""
        return NotImplemented

    def validate(self, layer: "Layer") -> list[str]:
        """返回该层的错误字符串列表（空列表 = 合法）；§16「数值非法」防线，绝不抛异常。

        基类只校验通用几何（宽/高有限正数、x/y 非 NaN/inf）。子类**先取 super().validate()
        再追加自己字段**（字号/文本/素材），保持「新内容类型 = 多写一条校验」。
        """
        return _validate_geometry(layer)

    def migrate(self, raw, from_version):  # noqa: ANN001, ANN201
        """Packet 4：旧字段→新字段，复用 __post_init__ 迁移。本轮未实现。"""
        return NotImplemented

    def measure(self, layer):  # noqa: ANN001, ANN201
        """Packet 5：返回 bounds，供 auto-layout 取子节点尺寸。本轮未实现。"""
        return NotImplemented

    def inspector_sections(self, layer: "Layer") -> list[InspectorSection]:
        """声明该层在属性栏显示哪些分组/字段（§10）。

        基类提供**通用 section（位置 X/Y、宽、高）**——对所有层适用，绑现有共享 var
        （ADR-002）。子类覆写时**先取 super() 的通用 section 再 append 自己的**，
        从而「未来字段 = provider 多声明一个 section」，悬浮栏组件无需改动（§14）。
        """
        return [_common_geometry_section()]

    def capabilities(self, layer: "Layer | None" = None) -> set[str]:
        """{'resize','rotate','editable_text','wrap',...}，UI 据此显隐手柄/入口（§7）。

        基类默认仅 ``{'resize'}``（当前唯一的右下角缩放手柄）。子类追加自己的能力。
        """
        return {"resize"}

    def resource_dependencies(self, layer):  # noqa: ANN001, ANN201
        """Packet 4：text→字体 / image→素材 SVG（见 §8）。委托 models.resource_dependencies（只读现有字段）。"""
        import models

        return models.resource_dependencies(layer)

    def serialize(self, layer):  # noqa: ANN001, ANN201
        """Packet 4：单层 → dict（§15）。委托 models.serialize_layer（dataclasses.fields 范式）。"""
        import models

        return models.serialize_layer(layer)

    def deserialize(self, raw):  # noqa: ANN001, ANN201
        """Packet 4：dict → 单层（§15）。委托 models.deserialize_layer（按 type/provider_id dispatch）。"""
        import models

        return models.deserialize_layer(raw)


# --- 模块级注册表（懒版：一个 dict，不造工厂/插件加载器）---
PROVIDERS: dict[str, ContentProvider] = {}


def register_provider(provider: ContentProvider) -> None:
    """登记 provider，键 = provider.provider_id。新内容类型 = 注册 1 个 provider。"""
    PROVIDERS[provider.provider_id] = provider


def get_provider(layer: "Layer") -> ContentProvider | None:
    """查表：优先 layer.provider_id，空则回退 layer.type（旧内存态兼容，见 §6）。"""
    return PROVIDERS.get(getattr(layer, "provider_id", "") or getattr(layer, "type", ""))


def _common_geometry_section() -> InspectorSection:
    """通用「位置/尺寸」section：对所有层适用，绑现有几何共享 var（ADR-002）。

    = 现有 _open_inspector_overlay 硬编码的前 4 行（位置 X/Y、宽、高），声明化后由悬浮栏
    数据驱动渲染。number 控件，无 var 时悬浮栏兜底绑 layer 属性（attr）。
    """
    return InspectorSection(
        "位置/尺寸",
        [
            InspectorField("x", "位置 X", "number", var_name="layer_x_var", attr="x"),
            InspectorField("y", "位置 Y", "number", var_name="layer_y_var", attr="y"),
            InspectorField("width", "宽", "number", var_name="layer_w_var", attr="width", min=1),
            InspectorField("height", "高", "number", var_name="layer_h_var", attr="height", min=1),
        ],
    )


class TextProvider(ContentProvider):
    """文字内容 provider：render_export/render_preview 委托现有 _text_layer / _draw_text_layer_preview。"""

    provider_id = "text"

    def render_export(self, layer: "Layer", ctx: dict[str, Any]) -> dict[str, Any] | None:
        # 委托 desktop_export 现有函数；算法不变 → 字节稳定（Packet 0 门禁）。
        import desktop_export

        return desktop_export._text_layer(layer)  # type: ignore[arg-type]

    def render_preview(self, layer: "Layer", ctx: dict[str, Any]) -> None:
        # ctx 携带 App 实例与画布坐标变换；委托 App 绑定方法（绘制逻辑原封不动）。
        ctx["app"]._draw_text_layer_preview(
            ctx["canvas"], layer, ctx["scale"], ctx["offset_x"], ctx["offset_y"]
        )

    def inspector_sections(self, layer: "Layer") -> list[InspectorSection]:
        """通用几何 + 文字分组（字号/字距/行距/对齐/颜色/字体）。

        绑定优先复用现有共享 var（ADR-002）：字号→layer_font_size_var、字距→
        layer_letter_spacing_var、颜色→layer_color_var。今天**没有专属共享 var** 的字段
        （行距/对齐/字体 picker）以 ``attr`` 声明对应的 layer 属性名（line_spacing/align/
        font_key），由悬浮栏按能力渲染或特例化（picker 仍特例化，见 ui_app 边界说明）。
        """
        sections = super().inspector_sections(layer)
        sections.append(
            InspectorSection(
                "文字",
                [
                    InspectorField("font_size", "字号", "number",
                                   var_name="layer_font_size_var", attr="font_size", min=1),
                    InspectorField("letter_spacing", "字距", "number",
                                   var_name="layer_letter_spacing_var", attr="letter_spacing"),
                    InspectorField("line_spacing", "行距", "number", attr="line_spacing", min=0),
                    InspectorField("align", "对齐", "segmented", attr="align"),
                    InspectorField("color", "颜色", "color",
                                   var_name="layer_color_var", attr="fill_color"),
                    InspectorField("font_key", "字体", "select", attr="font_key"),
                ],
            )
        )
        return sections

    def capabilities(self, layer: "Layer | None" = None) -> set[str]:
        return {"resize", "editable_text", "wrap"}

    def validate(self, layer: "Layer") -> list[str]:
        """通用几何 + 文字字段：字号必须有限正数；text 必填（空文本导出没有墨迹）。"""
        errors = super().validate(layer)
        font_size = getattr(layer, "font_size", None)
        if not _is_finite_number(font_size) or font_size <= 0:
            errors.append(f"非法字号: {font_size!r}")
        text = getattr(layer, "render_text", None) or getattr(layer, "text", "")
        if not str(text).strip():
            errors.append("文本为空")
        return errors


class ImageProvider(ContentProvider):
    """素材内容 provider：委托现有 _image_layer / _draw_image_layer_preview。

    保留 Packet 2 语义：``_image_layer`` 对未绑素材的空白层返回 None（跳过 + warning）。
    """

    provider_id = "image"

    def render_export(self, layer: "Layer", ctx: dict[str, Any]) -> dict[str, Any] | None:
        import desktop_export

        return desktop_export._image_layer(layer)  # type: ignore[arg-type]

    def render_preview(self, layer: "Layer", ctx: dict[str, Any]) -> None:
        # 预览用闭包 sx/sy（屏幕↔文档坐标）；委托 App 绑定方法。
        ctx["app"]._draw_image_layer_preview(ctx["canvas"], layer, ctx["sx"], ctx["sy"])

    def inspector_sections(self, layer: "Layer") -> list[InspectorSection]:
        """通用几何 + 素材分组（素材 picker、锁定宽高比）。最小集（§10）。"""
        sections = super().inspector_sections(layer)
        sections.append(
            InspectorSection(
                "素材",
                [
                    InspectorField("material_key", "素材", "select", attr="material_key"),
                    InspectorField("lock_aspect_ratio", "锁定宽高比", "toggle",
                                   attr="lock_aspect_ratio"),
                ],
            )
        )
        return sections

    def capabilities(self, layer: "Layer | None" = None) -> set[str]:
        return {"resize"}

    def validate(self, layer: "Layer") -> list[str]:
        """通用几何 + 素材字段：必须绑定素材（material_key 或 path 之一非空），否则报「缺素材」。

        与 Packet 4 导出语义一致——未绑素材在导出端会被跳过 + warning；validate 提前把它
        作为一条错误暴露给上层（Inspector/批检），但不阻断已有的「占位 + 跳过」恢复路径。
        """
        errors = super().validate(layer)
        material_key = str(getattr(layer, "material_key", "") or "").strip()
        path = getattr(layer, "path", None)
        if not material_key and not path:
            errors.append("缺素材：未绑定 material_key / path")
        return errors


# 导入时注册两个 provider（懒版：模块级副作用，import providers 即生效）。
register_provider(TextProvider())
register_provider(ImageProvider())
