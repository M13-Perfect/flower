"""Layer System v2 · Packet 7 错误恢复 + 性能冒烟（§16/§17/§18）。

Packet 7 的职责是**固化**错误恢复，不是重做前包已交付的部分。本文件分两类用例：

1. 新填的缺口（本包真正新增逻辑）：
   * ``ContentProvider.validate`` —— NaN/负尺寸/缺资源 → 错误列表；合法 → []。
   * Inspector 写回拒绝非法值（``_write_inspector_vars_to_layer`` 不把 NaN/负尺寸写进 layer）。
2. 跨包确认（前包/codex 已实现，本包加断言防回归，不重写实现）：
   * 未知 provider → 占位层（Packet 4 UnknownLayer），导出不崩。
   * 缺素材 → 导出跳过 + 不崩（Packet 4 _image_layer）。
   * 循环 reparent → 拒绝（既有 _iter_subtree 组循环检测）。
   * 嵌套过深 > max_depth → warning 而非崩（codex resolve_auto_layout）。
   * 空/零边界 → auto-layout 压到 1px，不除零（codex _layout/_set_group_bounds）。
   * 多图层（10–20）文档 serialize + 导出冒烟，无异常、耗时可接受。

全部走 ``without_display`` 范式（不起 Tk display），与既有测试一致。
"""
from __future__ import annotations

import time

import pytest

from app.domain.exports.dxf import _project_root
from desktop_export import (
    _document_to_layer_document,
    render_document_dxf,
    render_document_vector_svg,
)
from models import (
    Document,
    ImageLayer,
    UnknownLayer,
    add_image_layer,
    add_text_layer,
    deserialize_document,
    group_layers,
    reparent_layer,
    resolve_auto_layout,
    serialize_document,
)
from providers import ImageProvider, TextProvider, get_provider

import ui_app as ui_app_module
from ui_app import BirthFlowerApp

_FLOWER_SVG = _project_root() / "BirthMonth flowers" / "CherryMarch.svg"
_FONT = _project_root() / "Birthmonth_font.ttf"


# ---------------------------------------------------------------------------
# Part 1a — ContentProvider.validate（本包新增逻辑）
# ---------------------------------------------------------------------------
def test_text_provider_validate_accepts_valid_layer():
    document = Document(canvas_width=1000, canvas_height=500)
    layer = add_text_layer(document, "Mia", font_path=_FONT, x=10, y=20, width=300, height=120, font_size=80)
    assert TextProvider().validate(layer) == []


def test_text_provider_validate_flags_nan_and_negative_size():
    document = Document(canvas_width=1000, canvas_height=500)
    layer = add_text_layer(document, "Mia", width=300, height=120, font_size=80)
    layer.width = float("nan")
    layer.height = -5
    errors = TextProvider().validate(layer)
    assert any("宽度" in e for e in errors)
    assert any("高度" in e for e in errors)


def test_text_provider_validate_flags_bad_font_size_and_empty_text():
    document = Document(canvas_width=1000, canvas_height=500)
    layer = add_text_layer(document, "Mia", width=300, height=120, font_size=80)
    layer.font_size = 0
    layer.text = layer.render_text = layer.original_text = "   "
    errors = TextProvider().validate(layer)
    assert any("字号" in e for e in errors)
    assert any("文本为空" in e for e in errors)


def test_image_provider_validate_accepts_bound_material():
    document = Document(canvas_width=1000, canvas_height=500)
    layer = add_image_layer(document, _FLOWER_SVG, x=0, y=0, width=200, height=200)
    assert ImageProvider().validate(layer) == []


def test_image_provider_validate_flags_missing_material_and_inf_size():
    layer = ImageLayer(name="空白", width=float("inf"), height=200)
    errors = ImageProvider().validate(layer)
    assert any("缺素材" in e for e in errors)
    assert any("宽度" in e for e in errors)


def test_get_provider_validate_dispatches_by_type():
    """validate 也能从注册表查到 provider（与渲染/导出同源 dispatch）。"""
    document = Document(canvas_width=1000, canvas_height=500)
    text = add_text_layer(document, "Ok", font_path=_FONT, width=100, height=40, font_size=30)
    provider = get_provider(text)
    assert provider is not None
    assert provider.validate(text) == []


# ---------------------------------------------------------------------------
# Part 1b — Inspector 写回拒绝非法值（本包新增防线）
# ---------------------------------------------------------------------------
class _FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def _make_inspector_app(layer):
    """无 display 装一个最小 App，只为测 _write_inspector_vars_to_layer 的拒绝逻辑。"""
    app = BirthFlowerApp.__new__(BirthFlowerApp)
    app.layer_x_var = _FakeVar(str(layer.x))
    app.layer_y_var = _FakeVar(str(layer.y))
    app.layer_w_var = _FakeVar(str(layer.width))
    app.layer_h_var = _FakeVar(str(layer.height))
    app.layer_font_size_var = _FakeVar(str(getattr(layer, "font_size", 100)))
    return app


def test_inspector_rejects_nan_width_without_mutating_layer():
    document = Document(canvas_width=1000, canvas_height=500)
    layer = add_text_layer(document, "Mia", width=300, height=120, font_size=80)
    before = (layer.x, layer.y, layer.width, layer.height)
    app = _make_inspector_app(layer)
    app.layer_w_var.set("nan")  # NaN 能通过 float()，但绝不能写进 layer。

    assert app._write_inspector_vars_to_layer(layer) is False
    assert (layer.x, layer.y, layer.width, layer.height) == before


def test_inspector_rejects_negative_height_without_mutating_layer():
    document = Document(canvas_width=1000, canvas_height=500)
    layer = add_text_layer(document, "Mia", width=300, height=120, font_size=80)
    before = (layer.x, layer.y, layer.width, layer.height)
    app = _make_inspector_app(layer)
    app.layer_h_var.set("-50")

    assert app._write_inspector_vars_to_layer(layer) is False
    assert (layer.x, layer.y, layer.width, layer.height) == before


def test_inspector_accepts_valid_geometry():
    document = Document(canvas_width=1000, canvas_height=500)
    layer = add_text_layer(document, "Mia", width=300, height=120, font_size=80)
    app = _make_inspector_app(layer)
    app.layer_x_var.set("11")
    app.layer_w_var.set("321")

    assert app._write_inspector_vars_to_layer(layer) is True
    assert layer.x == pytest.approx(11)
    assert layer.width == pytest.approx(321)


# ---------------------------------------------------------------------------
# Part 1c — 跨包确认（前包/codex 已实现，这里只加断言防回归）
# ---------------------------------------------------------------------------
def test_unknown_provider_layer_becomes_placeholder_and_exports_without_crash():
    """未知 provider_id → 占位层（Packet 4）；含占位层的文档仍能导出 dict（占位被跳过，不崩）。"""
    raw = serialize_document(_build_multi_layer_document(extra=2))
    raw["layers"].append(
        {"type": "future_widget", "provider_id": "future_widget", "name": "未来组件", "x": 0, "y": 0}
    )
    document = deserialize_document(raw)
    assert any(isinstance(layer, UnknownLayer) for layer in document.layers)
    # 导出 dict 不应因占位层抛异常。
    layer_document = _document_to_layer_document(document)
    assert layer_document is not None


def test_missing_resource_image_layer_is_skipped_on_export_without_crash():
    """缺素材（绑了不存在的路径）→ 导出跳过 + 不崩（Packet 4 _image_layer）。"""
    document = Document(canvas_width=1000, canvas_height=500)
    add_text_layer(document, "Mia", font_path=_FONT, x=10, y=10, width=300, height=120, font_size=80)
    ghost = add_image_layer(document, _FLOWER_SVG, x=0, y=0, width=200, height=200)
    ghost.path = _project_root() / "BirthMonth flowers" / "__does_not_exist__.svg"
    ghost.material_key = "ghost"
    # 不抛异常即通过；缺素材层被跳过。
    layer_document = _document_to_layer_document(document)
    assert layer_document is not None


def test_cycle_reparent_is_rejected():
    """把图组拖进它自己的子层 → 既有组循环检测拒绝（返回 False），树不成环。"""
    document = Document(canvas_width=1000, canvas_height=500)
    a = add_image_layer(document, _FLOWER_SVG, x=0, y=0, width=100, height=100)
    b = add_image_layer(document, _FLOWER_SVG, x=10, y=10, width=100, height=100)
    outer = group_layers(document, [a.id, b.id], name="外组")
    assert outer is not None
    inner = group_layers(document, [a.id], name="内组")
    assert inner is not None
    # 把 outer 拖进 inner（inner 是 outer 的后代）→ 拒绝。
    assert reparent_layer(document, outer.id, inner.id, "inside") is False


def test_deeply_nested_auto_layout_warns_not_crashes():
    """嵌套深度超过 max_depth → warning 而非崩（codex resolve_auto_layout）。"""
    document = Document(canvas_width=1000, canvas_height=500)
    leaf = add_image_layer(document, _FLOWER_SVG, x=0, y=0, width=50, height=50)
    current_ids = [leaf.id]
    # 连续包 20 层组，超过默认 max_depth=16。
    for i in range(20):
        grp = group_layers(document, current_ids, name=f"组{i}")
        assert grp is not None
        current_ids = [grp.id]
    warnings = resolve_auto_layout(document, max_depth=16)
    assert any("过深" in w for w in warnings)


def test_empty_bounds_clamped_to_one_px_no_division_error():
    """零/坏尺寸子层 → auto-layout 把组边界压到 >=1px，不除零、不崩。"""
    document = Document(canvas_width=1000, canvas_height=500)
    a = add_image_layer(document, _FLOWER_SVG, x=0, y=0, width=0, height=0)
    a.material_key = "x"
    group = group_layers(document, [a.id], name="零尺寸组")
    assert group is not None
    resolve_auto_layout(document)  # 不应抛 ZeroDivisionError。
    assert group.width >= 1.0
    assert group.height >= 1.0


# ---------------------------------------------------------------------------
# Part 2 — 性能冒烟（§17）：多图层文档 serialize + 导出无异常、耗时可接受
# ---------------------------------------------------------------------------
def _build_multi_layer_document(*, extra: int = 16) -> Document:
    """生产形态 + 额外若干图层的多图层文档（共 ~2+extra 层）。"""
    document = Document(canvas_width=1732, canvas_height=1280)
    add_image_layer(document, _FLOWER_SVG, x=100, y=100, width=600, height=600)
    add_text_layer(
        document, "Mia", font_path=_FONT, x=200, y=900, width=600, height=200, font_size=180
    )
    for i in range(extra):
        if i % 2 == 0:
            add_image_layer(document, _FLOWER_SVG, x=50 * i, y=40 * i, width=120, height=120)
        else:
            add_text_layer(
                document, f"N{i}", font_path=_FONT, x=30 * i, y=20 * i,
                width=200, height=80, font_size=60,
            )
    return document


def test_multi_layer_document_serialize_and_export_smoke(tmp_path):
    """10–20 图层文档：serialize 往返 + DXF/SVG 导出全程无异常，且耗时在合理上限内。"""
    document = _build_multi_layer_document(extra=16)
    assert len(document.layers) >= 10

    start = time.perf_counter()
    restored = deserialize_document(serialize_document(document))
    assert len(restored.layers) == len(document.layers)
    render_document_dxf(restored, tmp_path / "multi.dxf", physical_width_mm=80)
    render_document_vector_svg(restored, tmp_path / "multi.svg")
    elapsed = time.perf_counter() - start

    # 冒烟阈值（极宽松，只为抓住灾难性退化，非性能基准）：10–20 层 << 30s。
    assert elapsed < 30.0


def test_schedule_canvas_render_debounce_default_is_25ms():
    """§17：保留 25ms root.after 去抖（不引入 dirty flag）。确认默认延时未被改动。"""
    import inspect

    sig = inspect.signature(ui_app_module.BirthFlowerApp._schedule_canvas_render)
    assert sig.parameters["delay_ms"].default == 25
