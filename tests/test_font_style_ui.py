"""Stage 6 护栏：字体样式全局默认的合并(_active_layout_defaults，两条保存路径共用)与
建新文本图层时把全局默认烘进图层。需 Tk display，缺则跳过。"""
from __future__ import annotations

import tkinter as tk

import pytest

from ui_app import BirthFlowerApp


def _app():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display 不可用")
    root.withdraw()
    return root, BirthFlowerApp(root)


def test_active_layout_defaults_merges_font_style():
    root, app = _app()
    try:
        app.font_bold_var.set(True)
        app.font_underline_var.set(True)
        app.bold_strength_var.set("0.02")
        app.letter_spacing_var.set("4")
        layout = app._active_layout_defaults()
        assert layout.bold is True
        assert layout.underline is True
        assert layout.bold_strength == 0.02
        assert layout.letter_spacing == 4.0
        # 几何仍来自 layout_vars，不受样式影响。
        assert layout.canvas_width == int(float(app.layout_vars["canvas_width"].get()))
    finally:
        root.destroy()


def test_new_text_layer_bakes_global_font_style():
    root, app = _app()
    try:
        app.font_bold_var.set(True)
        app.font_underline_var.set(False)
        app.bold_strength_var.set("0.05")
        app.letter_spacing_var.set("2.5")
        app._add_text_layer_from_fields()
        text_layers = [lyr for lyr in app.document.flat_render_layers() if getattr(lyr, "type", "") == "text"]
        assert text_layers, "应已新建文本图层"
        layer = text_layers[-1]
        assert layer.bold is True
        assert layer.underline is False
        assert layer.bold_strength == 0.05
        assert layer.letter_spacing == 2.5
    finally:
        root.destroy()


def test_apply_text_properties_overrides_layer_style():
    root, app = _app()
    try:
        # 建层烘的是全局默认（全关）；属性面板覆盖成开。
        app._add_text_layer_from_fields()
        layer = app.document.selected_layer()
        assert layer is not None
        app.layer_bold_var.set(True)
        app.layer_underline_var.set(True)
        app.layer_letter_spacing_var.set("6")
        app._apply_text_layer_properties()
        assert layer.bold is True
        assert layer.underline is True
        assert layer.letter_spacing == 6.0
        assert layer.tracking == 6.0  # 两字段同步
    finally:
        root.destroy()
