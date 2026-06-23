import json
from pathlib import Path
from types import SimpleNamespace

import ui_app as ui_app_module
from config_store import (
    AppConfig,
    LayerPin,
    ProductConfig,
    active_product,
    load_config,
    save_config,
    with_product_defaults,
    with_product_layer_pins,
)
from material_library import MaterialEntry, MaterialLibrary
from models import (
    AnchoredHeartLayer,
    Document,
    EngravingLayout,
    HistoryManager,
    TextLayer,
    add_anchored_heart_layer,
    add_image_layer,
    add_text_layer,
)
from order_catalog import LibraryBundle
from production import ProductionParams
from ui_app import BirthFlowerApp


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeTree:
    def __init__(self):
        self.items = {}
        self.children = {"": []}
        self.selection = None
        self.focused = None

    def get_children(self, parent=""):
        return tuple(self.children.get(parent, ()))

    def delete(self, *iids):
        for iid in iids:
            self.items.pop(iid, None)
            for child_ids in self.children.values():
                if iid in child_ids:
                    child_ids.remove(iid)
            self.children.pop(iid, None)

    def insert(self, parent, index, *, iid, text, values, tags, open=True):
        self.items[iid] = {"parent": parent, "text": text, "values": values, "tags": tags, "open": open}
        self.children.setdefault(parent, []).append(iid)
        self.children.setdefault(iid, [])

    def exists(self, iid):
        return iid in self.items

    def selection_set(self, iid):
        self.selection = iid

    def focus(self, iid):
        self.focused = iid

    def item(self, iid, option=None):
        data = self.items[iid]
        return data if option is None else data[option]


def _layout_vars(layout: EngravingLayout) -> dict[str, FakeVar]:
    keys = (
        "canvas_width",
        "canvas_height",
        "flower_x",
        "flower_y",
        "flower_width",
        "flower_height",
        "text_x",
        "text_y",
        "text_width",
        "text_height",
        "text_size",
    )
    return {key: FakeVar(str(getattr(layout, key))) for key in keys}


def _fake_app(config: AppConfig, *, bundle: LibraryBundle | None = None):
    app = BirthFlowerApp.__new__(BirthFlowerApp)
    app.config = config
    app.active_bundle = bundle or LibraryBundle()
    app.layout_vars = _layout_vars(active_product(config).defaults)
    app.status_var = FakeVar()
    app.layer_detail_var = FakeVar()
    app.selected_preview_item = None
    app.inline_text_entry = None
    app.history_manager = HistoryManager()
    app._refresh_layers_panel = lambda: None
    app._redraw_preview = lambda: None
    app._sync_layer_properties = lambda _layer: None
    return app


def test_layer_pins_round_trip_and_invalid_payload_filtering(tmp_path):
    path = tmp_path / "config.json"
    pin = LayerPin(
        "image:lib:rose",
        ProductionParams(x=400, y=120, width=220, height=180, rotation=10),
    )
    config = AppConfig(
        products=(ProductConfig(id="p1", name="P1", layer_pins=(pin,)),),
        active_product_id="p1",
    )

    save_config(config, path)
    loaded = load_config(path)

    assert active_product(loaded).layer_pins == (pin,)

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["products"][0]["layer_pins"] = [
        {"key": "image:lib:rose", "production": {"x": 1, "y": 2, "width": 3, "height": 4}},
        {"key": "", "production": {"x": 1, "y": 2, "width": 3, "height": 4}},
        {"key": "image:lib:bad", "production": {"x": 1, "y": 2, "width": 0, "height": 4}},
        {"key": "image:lib:nan", "production": {"x": "NaN", "y": 2, "width": 3, "height": 4}},
    ]
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = load_config(path)

    assert [pin.key for pin in active_product(loaded).layer_pins] == ["image:lib:rose"]


def test_product_defaults_and_pins_update_only_target_product(tmp_path):
    p1_defaults = EngravingLayout(canvas_width=1111, canvas_height=700, flower_x=10)
    p2_defaults = EngravingLayout(canvas_width=2222, canvas_height=800, flower_x=20)
    config = AppConfig(
        products=(
            ProductConfig(id="p1", name="P1", defaults=p1_defaults),
            ProductConfig(id="p2", name="P2", defaults=p2_defaults),
        ),
        active_product_id="p1",
        layout_defaults=p1_defaults,
    )
    p2_new = EngravingLayout(canvas_width=3333, canvas_height=900, flower_x=33)
    p2_pin = LayerPin("image:lib:heart", ProductionParams(x=5, y=6, width=7, height=8, rotation=15))

    config = with_product_defaults(config, p2_new, product_id="p2")
    config = with_product_layer_pins(config, (p2_pin,), product_id="p2")

    assert config.products[0].defaults == p1_defaults
    assert config.products[0].layer_pins == ()
    assert config.products[1].defaults == p2_new
    assert config.products[1].layer_pins == (p2_pin,)
    assert config.layout_defaults == p1_defaults

    p1_new = EngravingLayout(canvas_width=4444, canvas_height=1000, flower_x=44)
    config = with_product_defaults(config, p1_new, product_id="p1")

    assert config.products[0].defaults == p1_new
    assert config.layout_defaults == p1_new


def test_old_product_without_defaults_falls_back_to_global_defaults(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "layout_defaults": {"canvas_width": 2000, "canvas_height": 1200, "flower_x": 321},
                "products": [{"id": "p1", "name": "P1"}],
                "active_product_id": "p1",
            }
        ),
        encoding="utf-8",
    )

    product = active_product(load_config(path))

    assert product.defaults.canvas_width == 2000
    assert product.defaults.canvas_height == 1200
    assert product.defaults.flower_x == 321
    assert product.layer_pins == ()


def test_history_manager_push_undo_redo_clear_and_limit():
    history = HistoryManager()
    document = Document(1000, 500)
    layer = add_text_layer(document, "A", x=1, y=2)

    assert history.undo(document) is None
    assert history.redo(document) is None

    history.push(document)
    layer.x = 99
    undone = history.undo(document)

    assert undone is not None
    assert undone.layer_by_id(layer.id).x == 1
    assert document.layer_by_id(layer.id).x == 99

    redone = history.redo(undone)

    assert redone is not None
    assert redone.layer_by_id(layer.id).x == 99

    history.undo(redone)
    history.push(undone)
    assert history.redo_stack == []

    history.clear()
    assert history.undo_stack == []
    assert history.redo_stack == []

    for width in range(10):
        document.canvas_width = width
        history.push(document, limit=3)
    assert [snapshot.canvas_width for snapshot in history.undo_stack] == [7, 8, 9]


def test_pin_key_rules_and_anchored_heart_is_not_pinnable():
    config = AppConfig(products=(ProductConfig(id="p1", name="P1"),), active_product_id="p1")
    app = _fake_app(config)
    document = Document()
    image = add_image_layer(document, Path("rose.svg"), library_id="lib", material_key="rose")
    temp = add_image_layer(document, Path("loose.svg"))
    text = add_text_layer(document, "A")
    heart = add_anchored_heart_layer(document, anchor_layer_id=text.id)

    assert app._pin_key(image) == "image:lib:rose"
    assert app._pin_key(temp) == "path:loose.svg"
    assert app._pin_key(text) == "text:0"
    assert app._pin_key(heart) is None
    assert app._layer_pin_state(heart) == (False, False)


def test_effective_production_uses_pin_between_entry_and_layer_override():
    layout = EngravingLayout(flower_x=10, flower_y=20, flower_width=30, flower_height=40)
    pin = LayerPin(
        "image:lib:rose",
        ProductionParams(x=400, y=120, width=220, height=180, rotation=10),
    )
    config = AppConfig(
        products=(ProductConfig(id="p1", name="P1", defaults=layout, layer_pins=(pin,)),),
        active_product_id="p1",
    )
    library = MaterialLibrary(
        id="lib",
        name="Flowers",
        kind="image",
        root=Path("flowers"),
        defaults=ProductionParams(x=100, width=130),
        entries=(
            MaterialEntry(
                key="rose",
                name="Rose",
                path=Path("rose.svg"),
                defaults=ProductionParams(x=200, height=240, rotation=5),
            ),
        ),
    )
    app = _fake_app(config, bundle=LibraryBundle(image_libraries=(library,)))
    layer = add_image_layer(Document(), Path("rose.svg"), library_id="lib", material_key="rose")
    layer.production = ProductionParams(y=999)

    effective = app._layer_effective_production(layer)

    assert effective.x == 400
    assert effective.y == 999
    assert effective.width == 220
    assert effective.height == 180
    assert effective.rotation == 10


def test_toggle_layer_pin_saves_config_and_does_not_touch_history(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    config = AppConfig(products=(ProductConfig(id="p1", name="P1"),), active_product_id="p1")
    app = _fake_app(config)
    document = Document()
    layer = add_image_layer(
        document,
        Path("rose.svg"),
        x=400,
        y=120,
        width=220,
        height=180,
        library_id="lib",
        material_key="rose",
    )
    layer.rotation = 10
    app.document = document
    monkeypatch.setattr(ui_app_module, "save_config", lambda cfg: save_config(cfg, path))

    app._toggle_layer_initial_pin(layer)

    saved_pin = active_product(load_config(path)).layer_pins[0]
    assert saved_pin.key == "image:lib:rose"
    assert saved_pin.production.x == 400
    assert saved_pin.production.y == 120
    assert saved_pin.production.rotation == 10
    assert app.history_manager.undo_stack == []

    app._toggle_layer_initial_pin(layer)

    assert active_product(load_config(path)).layer_pins == ()


def test_render_layers_tree_derives_row_state_without_tk():
    pin = LayerPin("image:lib:rose", ProductionParams(x=1, y=2, width=3, height=4))
    config = AppConfig(
        products=(ProductConfig(id="p1", name="P1", layer_pins=(pin,)),),
        active_product_id="p1",
    )
    app = _fake_app(config)
    tree = FakeTree()
    document = Document()
    image = add_image_layer(document, Path("rose.svg"), library_id="lib", material_key="rose")
    locked = add_text_layer(document, "Locked")
    locked.locked = True
    heart = add_anchored_heart_layer(document, anchor_layer_id=locked.id)
    document.selected_layer_id = image.id
    app.document = document
    app.layers_tree = tree

    app._render_layers_tree()

    assert "pinned" in tree.item(image.id, "tags")
    assert "locked" in tree.item(locked.id, "tags")
    assert "pinned" not in tree.item(heart.id, "tags")
    assert tree.selection == image.id


def test_delete_text_layer_cleans_anchored_heart_and_undo_restores(monkeypatch):
    config = AppConfig(products=(ProductConfig(id="p1", name="P1"),), active_product_id="p1")
    app = _fake_app(config)
    document = Document()
    text = add_text_layer(document, "A")
    heart = add_anchored_heart_layer(document, anchor_layer_id=text.id)
    document.selected_layer_id = text.id
    app.document = document
    monkeypatch.setattr(ui_app_module.messagebox, "askyesno", lambda *args, **kwargs: True)

    app._delete_selected_layer()

    assert document.layer_by_id(text.id) is None
    assert document.layer_by_id(heart.id) is None
    assert document.selected_layer_id is None
    undo = app.history_manager.undo(document)
    assert undo is not None
    assert isinstance(undo.layer_by_id(text.id), TextLayer)
    assert isinstance(undo.layer_by_id(heart.id), AnchoredHeartLayer)


def test_canvas_size_text_and_focus_routing_helpers():
    config = AppConfig(products=(ProductConfig(id="p1", name="P1"),), active_product_id="p1")
    app = _fake_app(config)

    assert "2000" in app._preview_canvas_size_text(EngravingLayout(canvas_width=2000, canvas_height=1280))
    assert app._preview_canvas_size_text(EngravingLayout(canvas_width=0, canvas_height=1280)).endswith("px")

    app.root = SimpleNamespace(focus_get=lambda: SimpleNamespace(winfo_class=lambda: "Entry"))
    assert app._focus_is_text_input() is True
    app.root = SimpleNamespace(focus_get=lambda: SimpleNamespace(winfo_class=lambda: "Canvas"))
    assert app._focus_is_text_input() is False
