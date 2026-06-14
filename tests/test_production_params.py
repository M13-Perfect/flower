"""ProductionParams 合并 / 回落链单测（见 ExecPlan §5）。"""

from __future__ import annotations

from production import ProductionParams, resolve_chain


def test_merge_onto_self_overrides_non_none():
    base = ProductionParams(x=0, y=0, width=100, height=100)
    top = ProductionParams(x=310, width=1060)
    merged = top.merge_onto(base)
    assert merged.x == 310  # top 覆盖
    assert merged.width == 1060  # top 覆盖
    assert merged.y == 0  # top 为 None → 保留 base
    assert merged.height == 100


def test_merge_onto_none_base():
    top = ProductionParams(font_size=120)
    merged = top.merge_onto(None)
    assert merged.font_size == 120
    assert merged.x is None


def test_resolve_chain_low_to_high_priority():
    product = ProductionParams(x=0, y=0, width=100, height=100, font_size=190)
    library = ProductionParams(width=1060, height=1060)
    material = ProductionParams(width=1040)
    layer = ProductionParams(x=310, y=40)
    resolved = resolve_chain(product, library, material, layer)
    assert resolved.x == 310  # 图层 override 最高优先级
    assert resolved.y == 40
    assert resolved.width == 1040  # 素材 > 库 > 产品
    assert resolved.height == 1060  # 库覆盖产品
    assert resolved.font_size == 190  # 仅产品声明
    assert resolved.rotation is None
    assert resolved.lock_aspect_ratio is None


def test_resolve_chain_tolerates_none_levels():
    product = ProductionParams(width=100)
    resolved = resolve_chain(None, product, None, ProductionParams(width=200))
    assert resolved.width == 200


def test_from_mapping_ignores_unknown_and_none():
    params = ProductionParams.from_mapping({"width": 500, "unknown": 9, "height": None})
    assert params.width == 500
    assert params.height is None


def test_from_mapping_empty():
    assert ProductionParams.from_mapping(None).is_empty()
    assert ProductionParams.from_mapping({}).is_empty()


def test_to_dict_drops_none():
    params = ProductionParams(width=300, height=200)
    assert params.to_dict() == {"width": 300, "height": 200}
    full = params.to_dict(drop_none=False)
    assert full["x"] is None and full["width"] == 300
