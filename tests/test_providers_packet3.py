"""Packet 3：Content Provider 注册表（ADR-001）。

不需要 Tk display（纯 model + provider + desktop_export 层 builder，无 UI/Tk root），
与 without_display 范式一致。验三件事：

1. get_provider 查表：TextLayer→TextProvider、ImageLayer→ImageProvider；
   provider_id 为空时回退 layer.type。
2. provider 契约即字节稳定证明（单元级）：provider.render_export 产出的 dict
   与旧 _text_layer/_image_layer 的输出**逐字段相等**——证明 provider 化只搬调用点、
   不改算法（与 Packet 0 整文档字节门禁互为佐证）。
3. 注册表可扩展：注册一个 dummy provider 后 get_provider 能找到它
   （证明「新内容类型 = 注册 1 个 provider」）。
"""
from __future__ import annotations

import desktop_export
import providers
from app.domain.exports.dxf import _project_root
from models import Document, Layer, add_image_layer, add_text_layer
from providers import (
    ContentProvider,
    ImageProvider,
    TextProvider,
    get_provider,
    register_provider,
)

_FLOWER_SVG = _project_root() / "BirthMonth flowers" / "CherryMarch.svg"
_FONT = _project_root() / "Birthmonth_font.ttf"


# ---------------------------------------------------------------------------
# 1. get_provider 查表 + provider_id 空回退 type
# ---------------------------------------------------------------------------
def test_get_provider_returns_text_provider_for_text_layer():
    doc = Document()
    layer = add_text_layer(doc, "Mia", font_path=_FONT)
    assert isinstance(get_provider(layer), TextProvider)


def test_get_provider_returns_image_provider_for_image_layer():
    doc = Document()
    layer = add_image_layer(doc, _FLOWER_SVG, x=0, y=0, width=300, height=300)
    assert isinstance(get_provider(layer), ImageProvider)


def test_get_provider_falls_back_to_type_when_provider_id_empty():
    """provider_id 默认空 → 回退 layer.type。"""
    doc = Document()
    layer = add_text_layer(doc, "Mia", font_path=_FONT)
    assert layer.provider_id == ""  # 默认不填
    assert get_provider(layer) is providers.PROVIDERS["text"]


def test_get_provider_prefers_explicit_provider_id_over_type():
    """显式 provider_id 优先于 type（base 层 type='base' 无 provider，但显式 'text' 命中）。"""
    layer = Layer(provider_id="text")
    assert isinstance(get_provider(layer), TextProvider)


def test_get_provider_none_for_unknown_type():
    layer = Layer()  # type='base'，无注册 provider
    assert get_provider(layer) is None


# ---------------------------------------------------------------------------
# 2. provider 契约 = 字节稳定（单元级）：render_export == 旧 builder 输出
# ---------------------------------------------------------------------------
def test_text_provider_render_export_matches_legacy_text_layer():
    doc = Document(canvas_width=1732, canvas_height=1280)
    layer = add_text_layer(
        doc, "Mia", font_path=_FONT, x=200, y=900, width=600, height=200, font_size=180
    )
    layer.id = "stable-text"
    legacy = desktop_export._text_layer(layer)
    via_provider = get_provider(layer).render_export(layer, {})
    assert via_provider == legacy


def test_image_provider_render_export_matches_legacy_image_layer():
    doc = Document(canvas_width=1732, canvas_height=1280)
    layer = add_image_layer(doc, _FLOWER_SVG, x=100, y=100, width=600, height=600)
    layer.id = "stable-image"
    legacy = desktop_export._image_layer(layer)
    via_provider = get_provider(layer).render_export(layer, {})
    assert via_provider == legacy


def test_image_provider_render_export_preserves_unbound_skip():
    """Packet 2 语义保留：未绑空白层 render_export → None（跳过），不抛。"""
    from models import ImageLayer

    blank = ImageLayer(name="空白内容层", path=None, x=0, y=0, width=300, height=200)
    assert get_provider(blank).render_export(blank, {}) is None


# ---------------------------------------------------------------------------
# 3. 注册表可扩展：注册新 provider → get_provider 找到它
# ---------------------------------------------------------------------------
def test_register_new_provider_makes_get_provider_find_it():
    class DummyProvider(ContentProvider):
        provider_id = "dummy_packet3"

        def render_export(self, layer, ctx):
            return {"dummy": True}

        def render_preview(self, layer, ctx):
            return None

    saved = providers.PROVIDERS.get("dummy_packet3")
    try:
        register_provider(DummyProvider())
        layer = Layer(provider_id="dummy_packet3")
        provider = get_provider(layer)
        assert isinstance(provider, DummyProvider)
        assert provider.render_export(layer, {}) == {"dummy": True}
    finally:
        # 清理：别污染全局注册表（其它测试可能依赖干净表）。
        if saved is None:
            providers.PROVIDERS.pop("dummy_packet3", None)
        else:
            providers.PROVIDERS["dummy_packet3"] = saved
