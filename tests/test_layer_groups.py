"""PS 风格嵌套图组模型基础层单测（图层系统重做 Stage 1）。

最关键的不变量：**无图组时 flat_render_layers() 与 sorted_layers() 完全一致** ——
渲染/导出统一改走 flat_render_layers()，因此单图层（生产现状）字节零变化。
"""

from __future__ import annotations

from models import (
    Document,
    GroupLayer,
    add_image_layer,
    delete_layer,
    group_layers,
    hit_test,
    move_layer,
    ungroup_layer,
)


def _img(doc: Document, name: str, **kw):
    return add_image_layer(doc, f"{name}.svg", name=name, **kw)


def test_flat_equals_sorted_when_no_groups():
    doc = Document()
    _img(doc, "a")
    _img(doc, "b")
    _img(doc, "c")
    assert doc.flat_render_layers() == doc.sorted_layers()  # 对象/顺序一致 → 导出字节不变
    assert [layer.name for layer in doc.flat_render_layers()] == ["a", "b", "c"]


def test_group_flattens_leaves_in_order():
    doc = Document()
    _img(doc, "a")
    b = _img(doc, "b")
    c = _img(doc, "c")
    group = group_layers(doc, [b.id, c.id], name="g")
    assert isinstance(group, GroupLayer)
    assert [layer.name for layer in doc.layers] == ["a", "g"]  # 顶层 a + 图组
    assert [layer.name for layer in doc.flat_render_layers()] == ["a", "b", "c"]  # 摊平叶子顺序不变


def test_hidden_group_skips_all_children():
    doc = Document()
    _img(doc, "a")
    b = _img(doc, "b")
    c = _img(doc, "c")
    group = group_layers(doc, [b.id, c.id])
    group.visible = False
    assert [layer.name for layer in doc.flat_render_layers()] == ["a"]  # 整组不渲染


def test_ungroup_restores_children_in_place():
    doc = Document()
    _img(doc, "a")
    b = _img(doc, "b")
    c = _img(doc, "c")
    group = group_layers(doc, [b.id, c.id])
    restored = ungroup_layer(doc, group.id)
    assert [layer.name for layer in restored] == ["b", "c"]
    assert [layer.name for layer in doc.layers] == ["a", "b", "c"]
    assert all(not isinstance(layer, GroupLayer) for layer in doc.layers)


def test_hit_test_respects_group_lock_cascade():
    doc = Document()
    a = _img(doc, "a", x=0, y=0, width=100, height=100)
    group = group_layers(doc, [a.id])
    group.locked = True
    assert hit_test(doc, 50, 50) is None  # 组锁定 → 子层有效锁定 → 命中跳过
    group.locked = False
    assert hit_test(doc, 50, 50) is a


def test_move_layer_inside_group():
    doc = Document()
    a = _img(doc, "a")
    _img(doc, "b")
    _img(doc, "c")
    group_layers(doc, [a.id])  # a 单独成组
    assert move_layer(doc, a.id, "up") is False  # 组内仅一个 → 不能移动
    # 组内多个：重建
    doc2 = Document()
    x = _img(doc2, "x")
    y = _img(doc2, "y")
    z = _img(doc2, "z")
    g2 = group_layers(doc2, [x.id, y.id, z.id])
    assert move_layer(doc2, x.id, "up") is True
    assert [layer.name for layer in g2.children] == ["y", "x", "z"]


def test_delete_layer_inside_group():
    doc = Document()
    a = _img(doc, "a")
    b = _img(doc, "b")
    group = group_layers(doc, [a.id, b.id])
    removed = delete_layer(doc, a.id)
    assert removed is a
    assert [layer.name for layer in group.children] == ["b"]
