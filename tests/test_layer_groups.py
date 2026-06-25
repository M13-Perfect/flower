"""PS 风格嵌套图组模型基础层单测（图层系统重做 Stage 1）。

最关键的不变量：**无图组时 flat_render_layers() 与 sorted_layers() 完全一致** ——
渲染/导出统一改走 flat_render_layers()，因此单图层（生产现状）字节零变化。
"""

from __future__ import annotations

from models import (
    AnchoredHeartLayer,
    Document,
    GroupLayer,
    ImageLayer,
    TextLayer,
    add_anchored_heart_layer,
    add_image_layer,
    add_text_layer,
    add_universal_layer,
    delete_layer,
    duplicate_layer,
    group_layers,
    hit_test,
    move_layer,
    reparent_layer,
    ungroup_layer,
    validate_document,
)


def _img(doc: Document, name: str, **kw):
    return add_image_layer(doc, f"{name}.svg", name=name, **kw)


def test_universal_layer_combines_material_and_text_into_one_group():
    doc = Document()
    created = add_universal_layer(
        doc,
        material=dict(path="rose.svg", material_key="rose", library_id="flowers"),
        text=dict(text="Emma", font_key="font4", font_library_id="scripts"),
    )
    assert isinstance(created, GroupLayer) and created.name == "通用图层"
    kinds = {type(child) for child in created.children}
    assert kinds == {ImageLayer, TextLayer}  # 一个图层里既有素材又有文字
    assert created in doc.layers  # 组在顶层，子层已收进组
    assert not any(isinstance(layer, (ImageLayer, TextLayer)) for layer in doc.layers)


def test_universal_layer_single_side_returns_bare_leaf_not_group():
    doc = Document()
    only_material = add_universal_layer(doc, material=dict(path="rose.svg", material_key="rose"))
    assert isinstance(only_material, ImageLayer)  # 只素材 → 不做无意义的一层嵌套
    assert add_universal_layer(doc) is None  # 都不给 → 不建空组


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


# ---- 跨组移动 / 组循环检测（reparent_layer）----

def test_reparent_before_after_within_container():
    doc = Document()
    a = _img(doc, "a")
    b = _img(doc, "b")
    c = _img(doc, "c")  # [a, b, c]
    assert reparent_layer(doc, c.id, a.id, "before") is True
    assert [layer.name for layer in doc.layers] == ["c", "a", "b"]
    assert reparent_layer(doc, c.id, b.id, "after") is True
    assert [layer.name for layer in doc.layers] == ["a", "b", "c"]


def test_reparent_into_and_out_of_group():
    doc = Document()
    a = _img(doc, "a")
    b = _img(doc, "b")
    g = group_layers(doc, [b.id], name="g")  # 顶层 [a, g]；g=[b]
    assert reparent_layer(doc, a.id, g.id, "inside") is True
    assert [layer.name for layer in doc.layers] == ["g"]
    assert [layer.name for layer in g.children] == ["b", "a"]
    # 再把 a 拖回顶层、放到 g 之后
    assert reparent_layer(doc, a.id, g.id, "after") is True
    assert [layer.name for layer in doc.layers] == ["g", "a"]
    assert [layer.name for layer in g.children] == ["b"]


def test_reparent_rejects_group_into_own_subtree():
    doc = Document()
    a = _img(doc, "a")
    g = group_layers(doc, [a.id])  # g.children = [a]
    assert reparent_layer(doc, g.id, a.id, "before") is False  # a 是 g 的后代 → 成环
    assert reparent_layer(doc, g.id, a.id, "inside") is False
    assert a in g.children and g in doc.layers  # 树未被破坏


def test_reparent_rejects_locked_layer():
    doc = Document()
    a = _img(doc, "a")
    b = _img(doc, "b")
    a.locked = True
    assert reparent_layer(doc, a.id, b.id, "after") is False


def test_reparent_inside_requires_group_target():
    doc = Document()
    a = _img(doc, "a")
    b = _img(doc, "b")
    assert reparent_layer(doc, a.id, b.id, "inside") is False  # b 不是组


# ---- 复制图层（duplicate_layer）----

def test_duplicate_layer_inserts_copy_above_with_new_id():
    doc = Document()
    a = _img(doc, "a")
    _img(doc, "b")
    copy = duplicate_layer(doc, a.id)
    assert copy is not None and copy.id != a.id
    assert [layer.name for layer in doc.layers] == ["a", "a 副本", "b"]
    assert doc.selected_layer_id == copy.id


def test_duplicate_group_remaps_inner_anchor():
    doc = Document()
    t = add_text_layer(doc, "Emma")
    h = add_anchored_heart_layer(doc, anchor_layer_id=t.id)
    g = group_layers(doc, [t.id, h.id])
    copy = duplicate_layer(doc, g.id)
    assert isinstance(copy, GroupLayer)
    new_text = next(c for c in copy.children if isinstance(c, TextLayer))
    new_heart = next(c for c in copy.children if isinstance(c, AnchoredHeartLayer))
    assert new_text.id != t.id and new_heart.id != h.id
    assert new_heart.anchor_layer_id == new_text.id  # 指向副本内文字，不是原文字


# ---- 文档不变量校验（validate_document）----

def test_validate_document_flags_duplicate_id():
    doc = Document()
    a = _img(doc, "a")
    b = _img(doc, "b")
    assert validate_document(doc) == []
    b.id = a.id  # 人为制造重复 id
    assert validate_document(doc)  # 非空 → 报问题
