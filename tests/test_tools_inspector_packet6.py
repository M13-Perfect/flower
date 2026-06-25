"""Packet 6：工具/内容/Inspector 三分离 + 文字模式字段预留的 without_display 测试。

纯逻辑（无 Tk display）：
1. tools 注册表：get_tool('select'/'text') 可解析；SelectTool.on_press 委托
   app._on_canvas_press（fake app spy）；TextTool.activates_for 仅对 TextLayer True。
2. providers.inspector_sections：TextProvider 含 font_size/letter_spacing/line_spacing/
   align/color；ImageProvider 含 material/lock_aspect_ratio；通用 section 含 x/y/w/h。
3. 悬浮栏由 sections 驱动：_inspector_rows_from_provider 产出绑现有共享 var 的字段
   （复用 FakeVar/FakeRoot，不建 Tk 控件）。
4. layout_mode 默认 == box 行为：带默认 layout_mode 的 TextLayer 导出 dict 与「没有该字段的
   旧路径」逐字段一致（沿用 Packet 0/3 的 _text_layer 比对范式）。
"""
from __future__ import annotations

import desktop_export
import tools
from app.domain.exports.dxf import _project_root
from models import Document, ImageLayer, TextLayer, add_image_layer, add_text_layer
from providers import ImageProvider, TextProvider, get_provider
from tools import SelectTool, TextTool, get_tool

_FLOWER_SVG = _project_root() / "BirthMonth flowers" / "CherryMarch.svg"
_FONT = _project_root() / "Birthmonth_font.ttf"


class FakeVar:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


# ---------------------------------------------------------------------------
# 1. tools 注册表 + 委托
# ---------------------------------------------------------------------------
def test_get_tool_resolves_select_and_text():
    assert isinstance(get_tool("select"), SelectTool)
    assert isinstance(get_tool("text"), TextTool)
    assert get_tool("nope") is None


def test_active_tool_defaults_to_select():
    assert isinstance(tools.active_tool(), SelectTool)


def test_select_tool_delegates_press_drag_release_to_app():
    """SelectTool 的 on_press/on_drag/on_release 委托回 app._on_canvas_*（不自己实现交互）。"""
    calls: list[tuple[str, object]] = []

    class FakeApp:
        def _on_canvas_press(self, event):
            calls.append(("press", event))
            return "press-ret"

        def _on_canvas_drag(self, event):
            calls.append(("drag", event))

        def _on_canvas_release(self, event):
            calls.append(("release", event))

    app = FakeApp()
    ctx = {"app": app}
    tool = SelectTool()
    ev = object()
    assert tool.on_press(ev, ctx) == "press-ret"  # 透传返回值
    tool.on_drag(ev, ctx)
    tool.on_release(ev, ctx)
    assert calls == [("press", ev), ("drag", ev), ("release", ev)]


def test_text_tool_delegates_double_click_and_inline_edit():
    calls: list[str] = []

    class FakeApp:
        def _on_canvas_double_click(self, event):
            calls.append("double")

        def _start_inline_text_edit(self, layer_or_event):
            calls.append("inline")

    app = FakeApp()
    ctx = {"app": app}
    tool = TextTool()
    tool.on_double_click(object(), ctx)
    tool.start_inline_edit(object(), ctx)
    assert calls == ["double", "inline"]


def test_text_tool_activates_only_for_text_layer():
    tool = TextTool()
    assert tool.activates_for(TextLayer()) is True
    assert tool.activates_for(ImageLayer()) is False
    assert tool.activates_for(None) is False


def test_select_tool_activates_for_any_layer():
    tool = SelectTool()
    assert tool.activates_for(TextLayer()) is True
    assert tool.activates_for(ImageLayer()) is True


# ---------------------------------------------------------------------------
# 2. provider 声明 inspector_sections / capabilities
# ---------------------------------------------------------------------------
def _field_keys(sections) -> set[str]:
    return {fld.key for section in sections for fld in section.fields}


def test_common_section_has_geometry_for_any_provider():
    sections = TextProvider().inspector_sections(TextLayer())
    titles = [s.title for s in sections]
    assert "位置/尺寸" in titles
    assert {"x", "y", "width", "height"} <= _field_keys(sections)


def test_text_provider_declares_text_fields():
    sections = TextProvider().inspector_sections(TextLayer())
    keys = _field_keys(sections)
    for k in ("font_size", "letter_spacing", "line_spacing", "align", "color", "font_key"):
        assert k in keys, k


def test_image_provider_declares_material_fields():
    sections = ImageProvider().inspector_sections(ImageLayer())
    keys = _field_keys(sections)
    assert "material_key" in keys
    assert "lock_aspect_ratio" in keys
    # 也仍带通用几何 section。
    assert {"x", "y", "width", "height"} <= keys


def test_text_fields_bind_existing_shared_vars():
    """字号/字距/颜色 字段声明绑现有共享 var（ADR-002，不私造副本）。"""
    sections = TextProvider().inspector_sections(TextLayer())
    by_key = {fld.key: fld for section in sections for fld in section.fields}
    assert by_key["font_size"].var_name == "layer_font_size_var"
    assert by_key["letter_spacing"].var_name == "layer_letter_spacing_var"
    assert by_key["color"].var_name == "layer_color_var"


def test_capabilities_text_vs_image():
    assert TextProvider().capabilities(TextLayer()) == {"resize", "editable_text", "wrap"}
    assert ImageProvider().capabilities(ImageLayer()) == {"resize"}


def test_get_provider_inspector_sections_roundtrip():
    """经 get_provider 取到的 provider 也能声明 sections（注册表打通）。"""
    doc = Document()
    layer = add_text_layer(doc, "Mia", font_path=_FONT)
    assert {"x", "y", "width", "height", "font_size"} <= _field_keys(
        get_provider(layer).inspector_sections(layer)
    )


# ---------------------------------------------------------------------------
# 3. 悬浮栏由 sections 驱动（without_display）
# ---------------------------------------------------------------------------
def _row_app(layer):
    """造一个只带共享 var 的 App 桩，绕开 __init__（headless 无 Tk）。"""
    from ui_app import BirthFlowerApp

    app = BirthFlowerApp.__new__(BirthFlowerApp)
    app.layer_x_var = FakeVar(f"{layer.x:g}")
    app.layer_y_var = FakeVar(f"{layer.y:g}")
    app.layer_w_var = FakeVar(f"{layer.width:g}")
    app.layer_h_var = FakeVar(f"{layer.height:g}")
    app.layer_font_size_var = FakeVar(str(getattr(layer, "font_size", 0)))
    app.layer_color_var = FakeVar("#111111")
    app.layer_letter_spacing_var = FakeVar("0")
    return app


def test_overlay_rows_built_from_provider_for_text():
    """文字层悬浮栏行 = 通用几何 + 字号，且每行 var 是现有共享 var 实例（ADR-002）。"""
    doc = Document()
    layer = add_text_layer(doc, "Mia", font_path=_FONT, x=10, y=20, width=400, height=160)
    app = _row_app(layer)
    rows = app._inspector_rows_from_provider(layer)
    labels = [lbl for lbl, _ in rows]
    assert labels == ["位置 X", "位置 Y", "宽", "高", "字号"]
    # 每行绑的就是 App 上的共享 var 对象本身（同一份事实源）。
    vars_by_label = dict(rows)
    assert vars_by_label["字号"] is app.layer_font_size_var
    assert vars_by_label["位置 X"] is app.layer_x_var


def test_overlay_rows_built_from_provider_for_image():
    """图片层悬浮栏行 = 仅通用几何（无字号；material/lock picker 不在栏渲染，是边界）。"""
    doc = Document()
    layer = add_image_layer(doc, _FLOWER_SVG, x=0, y=0, width=300, height=300)
    app = _row_app(layer)
    rows = app._inspector_rows_from_provider(layer)
    labels = [lbl for lbl, _ in rows]
    assert labels == ["位置 X", "位置 Y", "宽", "高"]


# ---------------------------------------------------------------------------
# 4. layout_mode 默认 == box 行为（导出字节不变）
# ---------------------------------------------------------------------------
def test_text_layer_layout_mode_default_is_box():
    assert TextLayer().layout_mode == "box"
    assert TextLayer().runs is None


def test_layout_mode_default_does_not_change_export():
    """带默认 layout_mode/runs 的 TextLayer 导出 dict 仍 mode=box，且与改前路径逐字段一致。

    _text_layer / _layer_base 是手搭 dict（不遍历 dataclass fields），新增字段不可能进导出
    dict —— 这里显式断言导出结果不含 layout_mode/runs，且 layout.mode 仍为 'box'。
    """
    doc = Document(canvas_width=1732, canvas_height=1280)
    layer = add_text_layer(
        doc, "Mia", font_path=_FONT, x=200, y=900, width=600, height=200, font_size=180
    )
    layer.id = "p6-text"
    schema = desktop_export._text_layer(layer)
    assert schema["layout"]["mode"] == "box"
    # 新字段绝不泄漏进导出 dict（Packet 0 金标稳定的根因）。
    assert "layout_mode" not in schema
    assert "runs" not in schema

    # 改变 layout_mode 到非默认值，导出 dict 仍逐字段不变（本轮不分支 layout_mode）。
    layer.layout_mode = "point"
    layer.runs = [{"text": "x"}]
    schema_after = desktop_export._text_layer(layer)
    assert schema_after == schema
