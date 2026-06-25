from __future__ import annotations

import pytest

from models import (
    AutoLayoutGroupLayer,
    Document,
    HistoryManager,
    TextLayer,
    add_image_layer,
    add_text_layer,
    auto_layout_group_layers,
    delete_layer,
    duplicate_layer,
    resolve_auto_layout,
    ungroup_layer,
)


def _img(doc: Document, name: str, **kw):
    return add_image_layer(doc, f"{name}.svg", name=name, **kw)


def test_horizontal_auto_layout_keeps_gap_when_text_width_changes():
    doc = Document()
    image = _img(doc, "flower", x=20, y=30, width=100, height=80)
    text = add_text_layer(doc, "生日快乐", x=200, y=30, width=60, height=40)
    group = auto_layout_group_layers(doc, [image.id, text.id], name="auto", gap=16, align="center")
    assert isinstance(group, AutoLayoutGroupLayer)

    group.x = 20
    group.y = 30
    resolve_auto_layout(doc)

    assert image.x == pytest.approx(20)
    assert image.y == pytest.approx(30)
    assert text.x == pytest.approx(image.x + image.width + 16)
    assert text.y == pytest.approx(50)
    assert group.width == pytest.approx(176)
    assert group.height == pytest.approx(80)

    text.original_text = "生日快乐，愿你每天都有很多很多快乐"
    text.text = text.original_text
    text.render_text = text.original_text
    text.width = text.text_box_width = 180
    resolve_auto_layout(doc)

    assert text.x == pytest.approx(image.x + image.width + 16)
    assert group.width == pytest.approx(296)
    assert group.height == pytest.approx(80)


def test_vertical_auto_layout_applies_padding_gap_and_cross_axis_align():
    doc = Document()
    image = _img(doc, "flower", width=50, height=20)
    text = add_text_layer(doc, "Name", width=30, height=10)
    group = auto_layout_group_layers(
        doc,
        [image.id, text.id],
        name="vertical",
        direction="vertical",
        gap=8,
        padding=(10, 20, 30, 40),
        align="end",
    )
    assert isinstance(group, AutoLayoutGroupLayer)
    group.x = 5
    group.y = 7

    resolve_auto_layout(doc)

    assert image.x == pytest.approx(45)
    assert image.y == pytest.approx(17)
    assert text.x == pytest.approx(65)
    assert text.y == pytest.approx(45)
    assert group.width == pytest.approx(110)
    assert group.height == pytest.approx(78)


def test_auto_layout_ignores_hidden_and_deleted_children():
    doc = Document()
    image = _img(doc, "flower", width=100, height=80)
    text = add_text_layer(doc, "Name", width=60, height=40)
    hidden = _img(doc, "hidden", width=400, height=400)
    hidden.visible = False
    group = auto_layout_group_layers(doc, [image.id, text.id, hidden.id], gap=16)
    assert isinstance(group, AutoLayoutGroupLayer)

    resolve_auto_layout(doc)
    assert text.x == pytest.approx(image.x + image.width + 16)
    assert group.width == pytest.approx(176)

    assert delete_layer(doc, text.id) is text
    resolve_auto_layout(doc)
    assert group.width == pytest.approx(100)
    assert group.height == pytest.approx(80)


def test_nested_auto_layout_groups_resolve_children_first():
    doc = Document()
    a = _img(doc, "a", width=20, height=20)
    b = _img(doc, "b", width=30, height=10)
    c = _img(doc, "c", width=40, height=15)
    inner = auto_layout_group_layers(doc, [a.id, b.id], name="inner", gap=5)
    outer = auto_layout_group_layers(
        doc,
        [inner.id, c.id],
        name="outer",
        direction="vertical",
        gap=10,
    )
    assert isinstance(inner, AutoLayoutGroupLayer)
    assert isinstance(outer, AutoLayoutGroupLayer)
    outer.x = 100
    outer.y = 200

    resolve_auto_layout(doc)

    assert inner.x == pytest.approx(100)
    assert inner.y == pytest.approx(200)
    assert inner.width == pytest.approx(55)
    assert c.y == pytest.approx(inner.y + inner.height + 10)
    assert outer.height == pytest.approx(inner.height + 10 + c.height)


def test_ungroup_auto_layout_preserves_resolved_visual_positions():
    doc = Document()
    image = _img(doc, "flower", width=100, height=80)
    text = add_text_layer(doc, "Name", width=60, height=40)
    group = auto_layout_group_layers(doc, [image.id, text.id], gap=16)
    assert isinstance(group, AutoLayoutGroupLayer)
    group.x = 20
    group.y = 30
    resolve_auto_layout(doc)
    before = {child.id: child.bounds for child in group.children}

    restored = ungroup_layer(doc, group.id)

    assert [child.id for child in restored] == [image.id, text.id]
    assert {child.id: child.bounds for child in restored} == before


def test_duplicate_auto_layout_group_keeps_type_and_new_child_ids():
    doc = Document()
    image = _img(doc, "flower", width=100, height=80)
    text = add_text_layer(doc, "Name", width=60, height=40)
    group = auto_layout_group_layers(doc, [image.id, text.id], gap=16)
    assert isinstance(group, AutoLayoutGroupLayer)

    copy = duplicate_layer(doc, group.id)

    assert isinstance(copy, AutoLayoutGroupLayer)
    assert copy.id != group.id
    assert [child.id for child in copy.children] != [child.id for child in group.children]


def test_text_change_and_auto_layout_restore_with_one_history_snapshot():
    doc = Document()
    image = _img(doc, "flower", width=100, height=80)
    text = add_text_layer(doc, "Name", width=60, height=40)
    group = auto_layout_group_layers(doc, [image.id, text.id], gap=16)
    assert isinstance(group, AutoLayoutGroupLayer)
    resolve_auto_layout(doc)
    original_bounds = text.bounds

    history = HistoryManager()
    history.push(doc)
    text.original_text = "Longer Name"
    text.text = text.original_text
    text.render_text = text.original_text
    text.width = text.text_box_width = 160
    resolve_auto_layout(doc)
    assert text.bounds != original_bounds

    restored = history.undo(doc)
    assert restored is not None
    restored_text = restored.layer_by_id(text.id)
    assert isinstance(restored_text, TextLayer)
    assert restored_text.bounds == original_bounds
