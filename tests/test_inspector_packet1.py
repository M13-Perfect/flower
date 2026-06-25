"""Packet 1：非模态属性栏 + 事务化撤销的 without_display 逻辑测试。

只测 headless 可测的纯逻辑（var↔layer 双向同步、事务合并为单条 undo、Escape 回滚、
焦点判定、视口夹紧），不创建任何 Tk 控件（_open_inspector_overlay 需真机，见 AGENTS.md）。
"""
from models import (
    Document,
    HistoryManager,
    add_image_layer,
    add_text_layer,
)
from ui_app import BirthFlowerApp


class FakeVar:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


def _inspector_app(layer):
    """造一个只带属性栏所需共享 var / 几何方法的 App 桩，绕开 __init__（headless 无 Tk）。

    几何 var 预填该层当前值（= 真机里选层后 _sync_layer_properties 的效果），
    这样测试里只动某一个字段时，其余字段仍是合法数字，写回不会被整体否决。
    """
    app = BirthFlowerApp.__new__(BirthFlowerApp)
    doc = Document()
    app.document = doc
    app.history_manager = HistoryManager()
    app.layer_x_var = FakeVar(f"{layer.x:g}")
    app.layer_y_var = FakeVar(f"{layer.y:g}")
    app.layer_w_var = FakeVar(f"{layer.width:g}")
    app.layer_h_var = FakeVar(f"{layer.height:g}")
    app.layer_font_size_var = FakeVar(str(getattr(layer, "font_size", 0)))
    app.layer_text_var = FakeVar()
    app.layer_color_var = FakeVar()
    app.layer_bold_var = FakeVar(False)
    app.layer_underline_var = FakeVar(False)
    app.layer_letter_spacing_var = FakeVar("0")
    app._inspector_layer_id = layer.id
    app._inspector_entries = []
    app._inspector_suppress_trace = False
    app._redraw_preview = lambda: None
    app._refresh_layers_panel = lambda: None
    app._schedule_canvas_render = lambda *a, **k: None
    doc.selected_layer_id = layer.id
    return app


def _text_doc():
    doc = Document()
    layer = add_text_layer(doc, "生日快乐", x=100, y=200, width=400, height=160)
    return doc, layer


def test_inspector_var_to_layer_writes_geometry():
    """改 var → _write_inspector_vars_to_layer 写回 layer.x/y/w/h/font_size（双向同步的写方向）。"""
    doc, layer = _text_doc()
    app = _inspector_app(layer)
    app.document = doc
    app.layer_x_var.set("321")
    app.layer_y_var.set("654")
    app.layer_w_var.set("500")
    app.layer_h_var.set("220")
    app.layer_font_size_var.set("88")

    assert app._write_inspector_vars_to_layer(layer) is True
    assert (layer.x, layer.y, layer.width, layer.height) == (321.0, 654.0, 500.0, 220.0)
    assert layer.font_size == 88
    # 写回也落进图层级 production override（随层走）。
    assert layer.production is not None
    assert layer.production.x == 321.0 and layer.production.font_size == 88


def test_inspector_sync_layer_to_var_writes_vars():
    """选层/拖动 → _sync_layer_properties 把 layer 几何写进共享 var（双向同步的读方向）。"""
    doc, layer = _text_doc()
    app = _inspector_app(layer)
    layer.x, layer.y, layer.width, layer.height, layer.font_size = 11, 22, 333, 144, 77

    app._sync_layer_properties(layer)

    assert app.layer_x_var.get() == "11"
    assert app.layer_y_var.get() == "22"
    assert app.layer_w_var.get() == "333"
    assert app.layer_h_var.get() == "144"
    assert app.layer_font_size_var.get() == "77"


def test_inspector_invalid_values_are_ignored():
    """非法值（非数字 / 非正尺寸）不写 layer，避免脏几何。"""
    doc, layer = _text_doc()
    app = _inspector_app(layer)
    before = (layer.x, layer.y, layer.width, layer.height)

    app.layer_w_var.set("0")  # 宽 <= 0
    assert app._write_inspector_vars_to_layer(layer) is False
    app.layer_w_var.set("abc")  # 非数字
    assert app._write_inspector_vars_to_layer(layer) is False
    assert (layer.x, layer.y, layer.width, layer.height) == before


def test_inspector_transaction_collapses_to_single_undo():
    """begin → preview×N → commit 只产生一条 undo；连续改值不堆叠（ADR-003/§12）。"""
    doc, layer = _text_doc()
    app = _inspector_app(layer)
    app.document = doc
    assert app.history_manager.undo_stack == []

    # 模拟连续改值（每次 var write 触发一次 _on_inspector_var_write）。
    for w in ("410", "420", "430", "440", "450"):
        app.layer_w_var.set(w)
        app._on_inspector_var_write()

    app._inspector_commit()

    assert len(app.history_manager.undo_stack) == 1  # 整段连续编辑 = 单条 undo
    assert layer.width == 450.0  # 末值已写入


def test_inspector_rollback_restores_pre_edit_snapshot():
    """Escape → rollback 还原进入编辑前的快照，并弹掉进入时压入的 undo（§12）。"""
    doc, layer = _text_doc()
    app = _inspector_app(layer)
    app.document = doc
    orig_w = layer.width

    app.layer_w_var.set("999")
    app._on_inspector_var_write()  # begin_transaction + 写 layer
    assert layer.width == 999.0
    assert len(app.history_manager.undo_stack) == 1

    app._inspector_rollback()

    # 文档已被快照替换：取回滚后的当前层确认宽度复原。
    restored = app.document.layer_by_id(layer.id)
    assert restored.width == orig_w
    assert app.history_manager.undo_stack == []  # 进入时的快照已弹掉
    assert app.history_manager._txn_active is False


def test_inspector_reentrant_begin_is_noop():
    """连续 begin_transaction 幂等：只压一次快照（连续按住 +/- 不堆叠）。"""
    doc, layer = _text_doc()
    app = _inspector_app(layer)
    app.history_manager.begin_transaction(doc)
    app.history_manager.begin_transaction(doc)
    app.history_manager.begin_transaction(doc)
    assert len(app.history_manager.undo_stack) == 1


def test_focus_is_text_input_true_for_inspector_entry():
    """属性栏 Entry 获得焦点时 _focus_is_text_input 为 True，画布快捷键让路（§11）。"""
    doc, layer = _text_doc()
    app = _inspector_app(layer)

    sentinel_entry = object()  # 桩控件，代表栏内 Entry
    app._inspector_entries = [sentinel_entry]
    app.root = type("R", (), {"focus_get": staticmethod(lambda: sentinel_entry)})()

    assert app._focus_is_text_input() is True

    # 焦点不在任何输入控件上 → False（不拦截快捷键）。
    app.root = type("R", (), {"focus_get": staticmethod(lambda: None)})()
    assert app._focus_is_text_input() is False


def test_overlay_clamp_keeps_bar_inside_viewport():
    """视口夹紧：栏永不越界（min(max(...)) 纯坐标计算，§11）。"""
    clamp = BirthFlowerApp._clamp_overlay_position
    win_w, win_h, bar_w, bar_h, margin = 1000, 700, 160, 200, 8

    # 远超右下 → 夹到右下边界内。
    x, y = clamp(5000, 5000, bar_w, bar_h, win_w, win_h, margin)
    assert x == win_w - bar_w - margin
    assert y == win_h - bar_h - margin

    # 负坐标 → 夹到左上 margin。
    x, y = clamp(-500, -500, bar_w, bar_h, win_w, win_h, margin)
    assert x == margin
    assert y == margin

    # 栏比窗大 → 退化为 margin，不出现负 max。
    x, y = clamp(0, 0, 2000, 2000, win_w, win_h, margin)
    assert x == margin and y == margin


def test_image_layer_inspector_has_no_font_size():
    """非文字层写回不碰 font_size（图片层无字号字段）。"""
    doc = Document()
    layer = add_image_layer(doc, "x.svg", x=0, y=0, width=300, height=300)
    app = _inspector_app(layer)
    app.document = doc
    app.layer_x_var.set("50")
    app.layer_y_var.set("60")
    app.layer_w_var.set("200")
    app.layer_h_var.set("180")

    assert app._write_inspector_vars_to_layer(layer) is True
    assert (layer.x, layer.y, layer.width, layer.height) == (50.0, 60.0, 200.0, 180.0)
    assert layer.production is not None and layer.production.font_size is None
