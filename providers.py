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

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 仅类型标注用，避免运行时 import 环（providers 不该拖进重模块）。
    from models import Layer


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

    def validate(self, layer):  # noqa: ANN001, ANN201
        """Packet 7：返回错误列表（缺资源/非法尺寸），不崩。本轮未实现。"""
        return NotImplemented

    def migrate(self, raw, from_version):  # noqa: ANN001, ANN201
        """Packet 4：旧字段→新字段，复用 __post_init__ 迁移。本轮未实现。"""
        return NotImplemented

    def measure(self, layer):  # noqa: ANN001, ANN201
        """Packet 5：返回 bounds，供 auto-layout 取子节点尺寸。本轮未实现。"""
        return NotImplemented

    def inspector_sections(self, layer):  # noqa: ANN001, ANN201
        """Packet 6：声明属性栏字段（见 §10）。本轮未实现。"""
        return NotImplemented

    def capabilities(self):  # noqa: ANN201
        """Packet 6：{'resize','rotate','editable_text',...}，UI 据此显隐。本轮未实现。"""
        return NotImplemented

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


# 导入时注册两个 provider（懒版：模块级副作用，import providers 即生效）。
register_provider(TextProvider())
register_provider(ImageProvider())
