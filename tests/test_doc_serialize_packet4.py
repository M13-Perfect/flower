"""Packet 4：Document v2 序列化 + 加载时迁移 + 资源失效不崩（§8 / §15 / §16）。

不需要 Tk display（纯 model + desktop_export 层 builder，无 UI/Tk root），与 without_display 范式一致。
覆盖：

1. v2 往返深度相等：production 形态 Document（image + text [+ heart] [+ group]）→ serialize →
   deserialize → 结构等价（层数/类型/关键字段，递归图组）。
2. legacy 迁移：手写 legacy dict（无 schema_version，用 material_id 而非 material_key）→ deserialize
   → 字段正确迁移（__post_init__ 复用）。
3. 往返后字节稳定（红线·单元级）：Document → serialize → deserialize → 导出 dict 与原始逐字段相等。
4. 资源失效不崩：已绑素材但文件不存在 → 导出跳过该层 + 不抛 ValueError；其余层照常导出。
5. 未知 provider_id → 占位层（UnknownLayer），保留原始 dict，不崩。
"""
from __future__ import annotations

from pathlib import Path

from app.domain.exports.dxf import _project_root
from desktop_export import _document_to_layer_document, _image_layer
from models import (
    AnchoredHeartLayer,
    Document,
    GroupLayer,
    ImageLayer,
    TextLayer,
    UnknownLayer,
    add_anchored_heart_layer,
    add_image_layer,
    add_text_layer,
    deserialize_document,
    group_layers,
    serialize_document,
)

_FLOWER_SVG = _project_root() / "BirthMonth flowers" / "CherryMarch.svg"
_FONT = _project_root() / "Birthmonth_font.ttf"


def _build_production_document(*, with_heart: bool = False, with_group: bool = False) -> Document:
    """production 形态 Document：1 image + 1 text [+ heart] [+ group]，id 固定为确定值。"""
    document = Document(canvas_width=1732, canvas_height=1280)
    image = add_image_layer(document, _FLOWER_SVG, x=100, y=100, width=600, height=600)
    text = add_text_layer(
        document, "Mia", font_path=_FONT, x=200, y=900, width=600, height=200, font_size=180
    )
    image.id = "p4-image"
    text.id = "p4-text"
    if with_heart:
        heart = add_anchored_heart_layer(document, anchor_layer_id=text.id)
        heart.id = "p4-heart"
    if with_group:
        group_layers(document, [image.id], name="组合A")
    return document


def _flatten_types(document: Document) -> list[str]:
    return [type(layer).__name__ for layer in document.iter_all_layers()]


# ---------------------------------------------------------------------------
# 1. v2 往返深度相等
# ---------------------------------------------------------------------------
def test_v2_round_trip_structural_equal_basic():
    document = _build_production_document()
    restored = deserialize_document(serialize_document(document))

    assert restored.schema_version == 2
    assert restored.canvas_width == document.canvas_width
    assert restored.canvas_height == document.canvas_height
    assert len(restored.layers) == len(document.layers)
    assert _flatten_types(restored) == _flatten_types(document)

    img_o = next(layer for layer in document.layers if isinstance(layer, ImageLayer))
    img_r = next(layer for layer in restored.layers if isinstance(layer, ImageLayer))
    assert img_r.path == img_o.path
    assert img_r.material_key == img_o.material_key
    assert (img_r.x, img_r.y, img_r.width, img_r.height) == (img_o.x, img_o.y, img_o.width, img_o.height)

    txt_o = next(layer for layer in document.layers if isinstance(layer, TextLayer))
    txt_r = next(layer for layer in restored.layers if isinstance(layer, TextLayer))
    assert txt_r.original_text == txt_o.original_text
    assert txt_r.font_path == txt_o.font_path
    assert txt_r.font_size == txt_o.font_size


def test_v2_round_trip_with_heart_and_group():
    document = _build_production_document(with_heart=True, with_group=True)
    restored = deserialize_document(serialize_document(document))

    assert _flatten_types(restored) == _flatten_types(document)
    # 图组递归还原：组内 children 类型/数量一致。
    grp_o = next(layer for layer in document.layers if isinstance(layer, GroupLayer))
    grp_r = next(layer for layer in restored.layers if isinstance(layer, GroupLayer))
    assert len(grp_r.children) == len(grp_o.children)
    assert [type(c).__name__ for c in grp_r.children] == [type(c).__name__ for c in grp_o.children]
    # 锚定爱心还原为 AnchoredHeartLayer，锚定关系保留。
    heart_r = next(layer for layer in restored.iter_all_layers() if isinstance(layer, AnchoredHeartLayer))
    heart_o = next(layer for layer in document.iter_all_layers() if isinstance(layer, AnchoredHeartLayer))
    assert heart_r.anchor_layer_id == heart_o.anchor_layer_id


# ---------------------------------------------------------------------------
# 2. legacy 迁移（无 schema_version，material_id 而非 material_key）
# ---------------------------------------------------------------------------
def test_legacy_migration_material_id_to_material_key():
    legacy = {
        # 注意：无 schema_version → 视为 v1，走 migrate_v1_to_v2。
        "canvas_width": 1732,
        "canvas_height": 1280,
        "layers": [
            {
                "type": "image",
                "name": "旧素材",
                "x": 100,
                "y": 100,
                "width": 600,
                "height": 600,
                "path": {"__path__": str(_FLOWER_SVG)},
                "material_id": "legacy-cherry",  # 旧字段，无 material_key
            },
            {
                "type": "text",
                "name": "旧文本",
                "text": "Mia",
                "font_path": {"__path__": str(_FONT)},  # 旧字段，无 font_key
                "x": 200,
                "y": 900,
            },
        ],
    }
    document = deserialize_document(legacy)
    assert document.schema_version == 2

    image = next(layer for layer in document.layers if isinstance(layer, ImageLayer))
    # __post_init__ 复用：material_id → material_key。
    assert image.material_key == "legacy-cherry"

    text = next(layer for layer in document.layers if isinstance(layer, TextLayer))
    # __post_init__ 复用：font_key 从 font_path stem 推导。
    assert text.font_key == Path(_FONT).stem


def test_legacy_migration_ignores_unknown_keys():
    legacy = {
        "canvas_width": 1732,
        "canvas_height": 1280,
        "layers": [
            {
                "type": "text",
                "name": "文本",
                "text": "Mia",
                "x": 0,
                "y": 0,
                "totally_unknown_field": "ignored",  # config_store 范式：未知键忽略，不报错。
            }
        ],
    }
    document = deserialize_document(legacy)
    text = next(layer for layer in document.layers if isinstance(layer, TextLayer))
    assert not hasattr(text, "totally_unknown_field")


# ---------------------------------------------------------------------------
# 3. 往返后字节稳定（红线·单元级）
# ---------------------------------------------------------------------------
def test_export_dict_stable_after_round_trip():
    """红线门禁：Document → serialize → deserialize → 导出 dict 与原始逐字段相等。"""
    original = _document_to_layer_document(_build_production_document())
    restored_doc = deserialize_document(serialize_document(_build_production_document()))
    after = _document_to_layer_document(restored_doc)
    assert after == original


# ---------------------------------------------------------------------------
# 4. 资源失效不崩：已绑素材但文件不存在 → 跳过 + warning，其余照常
# ---------------------------------------------------------------------------
def test_missing_bound_material_skips_layer_no_crash():
    document = _build_production_document()
    image = next(layer for layer in document.layers if isinstance(layer, ImageLayer))
    image.path = Path("nonexistent/ghost.svg")  # 已绑但文件缺失
    image.material_key = "ghost"

    # 单层导出不抛 ValueError（旧行为是崩溃），而是返回 None（跳过）。
    assert _image_layer(image) is None

    # 整文档仍可导出：跳过缺失素材层，文本层照常导出。
    out = _document_to_layer_document(document)
    assert len(out["layers"]) == 1
    assert out["layers"][0]["type"] == "text"


def test_missing_material_round_trips_as_image_layer():
    """缺失素材层经 serialize/deserialize 仍是 ImageLayer（不被误判为占位）。"""
    document = _build_production_document()
    image = next(layer for layer in document.layers if isinstance(layer, ImageLayer))
    image.path = Path("nonexistent/ghost.svg")
    image.material_key = "ghost"
    restored = deserialize_document(serialize_document(document))
    img_r = next(layer for layer in restored.layers if isinstance(layer, ImageLayer))
    assert img_r.path == Path("nonexistent/ghost.svg")
    assert img_r.material_key == "ghost"


# ---------------------------------------------------------------------------
# 5. 未知 provider_id / type → 占位层，保留原始 dict，不崩
# ---------------------------------------------------------------------------
def test_unknown_provider_id_becomes_placeholder_preserving_raw():
    raw = serialize_document(_build_production_document())
    raw["layers"].append(
        {"type": "future_widget", "provider_id": "future_widget", "name": "未来组件", "custom": 99}
    )
    document = deserialize_document(raw)

    placeholders = [layer for layer in document.layers if isinstance(layer, UnknownLayer)]
    assert len(placeholders) == 1
    # 原始 dict 无损保留（未来版本可还原）。
    assert placeholders[0].raw["custom"] == 99
    assert placeholders[0].raw["provider_id"] == "future_widget"
    # 其余真实层照常加载。
    assert any(isinstance(layer, ImageLayer) for layer in document.layers)
    assert any(isinstance(layer, TextLayer) for layer in document.layers)


def test_unknown_placeholder_round_trips_losslessly():
    """占位层再次 serialize 吐回原始 raw（无损往返）。"""
    raw_layer = {"type": "future_widget", "name": "未来组件", "deep": {"nested": [1, 2, 3]}}
    placeholder = UnknownLayer(name="未来组件", raw=raw_layer)
    from models import serialize_layer

    assert serialize_layer(placeholder) == raw_layer


def test_single_layer_failure_becomes_placeholder():
    """单层构造失败（坏字段触发 __post_init__ 异常）→ 该层占位，整文档仍加载（§15）。"""
    raw = {
        "schema_version": 2,
        "canvas_width": 1732,
        "canvas_height": 1280,
        "layers": [
            {"type": "text", "name": "好层", "text": "Mia", "x": 0, "y": 0},
            # glyph_overrides 给一个非 dict 的字符串：TextLayer.__post_init__ 会 .items() → AttributeError，
            # deserialize_layer 捕获 → 占位（保留原始 dict），不中断整文档。
            {"type": "text", "name": "坏层", "text": "X", "glyph_overrides": "not-a-dict"},
        ],
    }
    document = deserialize_document(raw)
    assert len(document.layers) == 2
    assert any(isinstance(layer, TextLayer) for layer in document.layers)
    placeholders = [layer for layer in document.layers if isinstance(layer, UnknownLayer)]
    assert len(placeholders) == 1
    assert placeholders[0].raw["name"] == "坏层"
