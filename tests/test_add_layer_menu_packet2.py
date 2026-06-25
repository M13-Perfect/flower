"""Packet 2：统一「+ 添加图层」菜单 + 最小空白内容层 + 未绑层导出跳过。

沿用 without_display 范式（见 tests/test_inspector_packet1.py / test_canvas_layer_redesign.py）：
不建任何真实 Tk 控件——把 tk.Menu 换成纯记录用的 FakeMenu，把 App 关键方法桩掉，
只验可 headless 测的逻辑：

1. 「+ 添加图层」菜单按正确顺序建项，每项映射到正确的 add_*/组合处理器。
2. 空白内容层 = 未绑 ImageLayer（path=None），占位框非零、可被 hit_test 命中。
3. 未绑空白层被导出跳过（_image_layer 返回 None + warning），不抛异常；
   整文档导出（_document_to_layer_document）也跳过它而不崩。
4. 组合两项确实复用 codex（Packet 5）的 group_layers / auto_layout_group_layers。
"""
from __future__ import annotations

import desktop_export
import ui_app as ui_app_module
from models import (
    Document,
    GroupLayer,
    HistoryManager,
    ImageLayer,
    add_image_layer,
    add_text_layer,
    hit_test,
)
from ui_app import BirthFlowerApp


class FakeVar:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


class FakeMenu:
    """记录用假菜单：record 收集 (label, command, state)，cascade/separator 也入账。

    顶层 tk_popup/grab_release 为 no-op；构造时把自己登记到类级 instances 便于取顶层菜单。"""

    instances: list["FakeMenu"] = []

    def __init__(self, master=None, tearoff=False):
        self.master = master
        self.items: list[dict] = []
        FakeMenu.instances.append(self)

    def add_command(self, label="", command=None, state="normal", **kw):
        self.items.append({"kind": "command", "label": label, "command": command, "state": state})

    def add_separator(self):
        self.items.append({"kind": "separator"})

    def add_cascade(self, label="", menu=None, **kw):
        self.items.append({"kind": "cascade", "label": label, "menu": menu})

    def tk_popup(self, *a, **k):
        pass

    def grab_release(self):
        pass


class FakeRoot:
    def winfo_pointerx(self):
        return 0

    def winfo_pointery(self):
        return 0


def _menu_app(monkeypatch, *, doc=None, selected_ids=None):
    """造一个只带菜单/添加层所需属性的 App 桩，绕开 __init__；把 tk.Menu 换成 FakeMenu。"""
    monkeypatch.setattr(ui_app_module.tk, "Menu", FakeMenu)
    FakeMenu.instances.clear()
    app = BirthFlowerApp.__new__(BirthFlowerApp)
    app.document = doc if doc is not None else Document()
    app.history_manager = HistoryManager()
    app.root = FakeRoot()
    app.status_var = FakeVar()
    app.selected_preview_item = None
    # add_* 处理器在本测试里被打桩成记录调用，避免触碰真实资源/渲染。
    app._refresh_layers_panel = lambda: None
    app._redraw_preview = lambda: None
    app._sync_layer_properties = lambda _layer: None
    app._selected_layer_ids_for_group = lambda fallback_id=None: list(selected_ids or [])
    return app


# ---------------------------------------------------------------------------
# 1. 菜单结构 + 每项映射到正确处理器
# ---------------------------------------------------------------------------
def test_add_layer_menu_builds_expected_items(monkeypatch):
    app = _menu_app(monkeypatch, selected_ids=[])
    calls = []
    app._add_text_layer_from_fields = lambda: calls.append("text")
    app._add_selected_flower_to_canvas = lambda: calls.append("image")
    app._add_blank_content_layer = lambda: calls.append("blank")
    app._group_selected_layers = lambda *a, **k: calls.append("group")
    app._auto_layout_selected_layers = lambda *a, **k: calls.append("auto")

    app._show_add_layer_menu()

    top = FakeMenu.instances[0]
    commands = [it for it in top.items if it["kind"] == "command"]
    labels = [it["label"] for it in commands]
    assert labels == [
        "文字图层",
        "图片素材",
        "空白内容层",
        "普通组合（所选）",
        "自动布局组合（所选）",
    ]
    # 逐项触发：映射到正确处理器。
    for it in commands:
        it["command"]()
    assert calls == ["text", "image", "blank", "group", "auto"]


def test_combine_items_disabled_when_fewer_than_two_selected(monkeypatch):
    """组合两项在 <2 选层时置灰（复用右键 guard），>=2 时可用。"""
    app = _menu_app(monkeypatch, selected_ids=["a"])  # 只 1 个
    app._add_text_layer_from_fields = lambda: None
    app._add_selected_flower_to_canvas = lambda: None
    app._add_blank_content_layer = lambda: None
    app._group_selected_layers = lambda *a, **k: None
    app._auto_layout_selected_layers = lambda *a, **k: None
    app._show_add_layer_menu()
    state = {it["label"]: it["state"] for it in FakeMenu.instances[0].items if it["kind"] == "command"}
    assert state["普通组合（所选）"] == "disabled"
    assert state["自动布局组合（所选）"] == "disabled"

    app2 = _menu_app(monkeypatch, selected_ids=["a", "b"])  # 2 个
    app2._add_text_layer_from_fields = lambda: None
    app2._add_selected_flower_to_canvas = lambda: None
    app2._add_blank_content_layer = lambda: None
    app2._group_selected_layers = lambda *a, **k: None
    app2._auto_layout_selected_layers = lambda *a, **k: None
    app2._show_add_layer_menu()
    state2 = {it["label"]: it["state"] for it in FakeMenu.instances[0].items if it["kind"] == "command"}
    assert state2["普通组合（所选）"] == "normal"
    assert state2["自动布局组合（所选）"] == "normal"


# ---------------------------------------------------------------------------
# 2. 空白内容层：非零占位框 + 可命中
# ---------------------------------------------------------------------------
def test_blank_layer_has_nonzero_size_and_is_hittable(monkeypatch):
    doc = Document(canvas_width=1732, canvas_height=1280)
    app = _menu_app(monkeypatch, doc=doc)
    app._active_layout_defaults = lambda: ui_app_module.EngravingLayout(
        flower_x=100, flower_y=120, flower_width=300, flower_height=200
    )

    app._add_blank_content_layer()

    assert len(doc.layers) == 1
    layer = doc.layers[0]
    assert isinstance(layer, ImageLayer)
    # 未绑：无 path、无 material_key。
    assert layer.path is None
    assert layer.material_key == ""
    # 占位框非零（不是 0×0 隐形层）。
    assert layer.width > 0 and layer.height > 0
    left, top, right, bottom = layer.bounds
    assert right > left and bottom > top
    # 命中走占位 bbox：框中心点命中到本层。
    cx, cy = (left + right) / 2, (top + bottom) / 2
    assert hit_test(doc, cx, cy) is layer
    # add 压了一次 history（删除/撤销正常的前提）。
    assert len(app.history_manager.undo_stack) == 1


# ---------------------------------------------------------------------------
# 3. 未绑空白层：导出跳过（不抛），已绑层不受影响
# ---------------------------------------------------------------------------
def test_unbound_blank_layer_is_skipped_by_image_export():
    """_image_layer 对未绑空白层返回 None（跳过）而不抛 ValueError。"""
    blank = ImageLayer(name="空白内容层", path=None, x=0, y=0, width=300, height=200)
    assert blank.material_key == ""
    assert desktop_export._image_layer(blank) is None


def test_unbound_blank_layer_skipped_in_document_export(caplog):
    """整文档导出跳过未绑层 + 记 warning，留下已绑层，不崩。"""
    doc = Document(canvas_width=1732, canvas_height=1280)
    # 一个已绑的真实矢量花（保证导出本身能产出图层）。
    from app.domain.exports.dxf import _project_root

    flower = _project_root() / "BirthMonth flowers" / "CherryMarch.svg"
    add_image_layer(doc, flower, x=100, y=100, width=600, height=600)
    # 一个未绑空白层。
    doc.layers.append(ImageLayer(name="空白内容层", path=None, x=0, y=0, width=300, height=200))
    doc.normalize_z_indexes()

    with caplog.at_level("WARNING", logger="desktop_export"):
        result = desktop_export._document_to_layer_document(doc)

    # 只导出 1 个图层（已绑的花），空白层被跳过；不抛异常。
    assert len(result["layers"]) == 1
    assert any("空白内容层" in rec.message or "未绑定" in rec.message for rec in caplog.records)


def test_bound_image_layer_export_unaffected():
    """已绑图片层照常导出（不被新 guard 误跳）—— Packet 0 字节稳定的回归保险。"""
    from app.domain.exports.dxf import _project_root

    doc = Document(canvas_width=1732, canvas_height=1280)
    flower = _project_root() / "BirthMonth flowers" / "CherryMarch.svg"
    layer = add_image_layer(doc, flower, x=100, y=100, width=600, height=600)
    schema = desktop_export._image_layer(layer)
    assert schema is not None
    assert "inlineSvg" in schema


# ---------------------------------------------------------------------------
# 4. 组合项复用 codex（Packet 5）的 group_layers / auto_layout_group_layers
# ---------------------------------------------------------------------------
def test_group_item_reuses_codex_group_layers(monkeypatch):
    """普通组合处理器调 models.group_layers（不重实现分组）。"""
    doc = Document()
    a = add_image_layer(doc, "a.svg", x=0, y=0, width=100, height=100)
    b = add_text_layer(doc, "x", x=200, y=0, width=100, height=100)
    app = _menu_app(monkeypatch, doc=doc, selected_ids=[a.id, b.id])
    called = {}
    real_group = ui_app_module.group_layers

    def spy(document, ids, *, name="图组"):
        called["ids"] = list(ids)
        return real_group(document, ids, name=name)

    monkeypatch.setattr(ui_app_module, "group_layers", spy)
    app._group_selected_layers()
    assert called.get("ids") == [a.id, b.id]
    # 文档里出现一个组。
    assert any(isinstance(layer, GroupLayer) for layer in doc.layers)


def test_auto_layout_item_reuses_codex_auto_layout_group_layers(monkeypatch):
    """自动布局组合处理器调 models.auto_layout_group_layers（不重实现）。"""
    doc = Document()
    a = add_image_layer(doc, "a.svg", x=0, y=0, width=100, height=100)
    b = add_text_layer(doc, "x", x=200, y=0, width=100, height=100)
    app = _menu_app(monkeypatch, doc=doc, selected_ids=[a.id, b.id])
    called = {}
    real_auto = ui_app_module.auto_layout_group_layers

    def spy(document, ids, **kw):
        called["ids"] = list(ids)
        called["kw"] = kw
        return real_auto(document, ids, **kw)

    monkeypatch.setattr(ui_app_module, "auto_layout_group_layers", spy)
    app._auto_layout_selected_layers()
    assert called.get("ids") == [a.id, b.id]
