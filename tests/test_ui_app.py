import threading
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from types import SimpleNamespace

import pytest

from config_store import AIProfile
from generation_readiness import GenerationReadiness
from glyph_service import GlyphApplyResult, GlyphVariant
from models import FlowerAsset, FontAsset, ImageLayer, TextLayer
from models import FlowerAsset, FontAsset, TextLayer, add_text_layer
import ui_app as ui_app_module
from ui_app import (
    APP_COLORS,
    BirthFlowerApp,
    IMPORTABLE_ASSET_SUFFIXES,
    IMPORTABLE_FONT_SUFFIXES,
    _preview_text_ink_image,
    _ttf_family_name,
    build_ai_profile_from_settings,
    build_ai_parse_config,
    build_design_from_values,
    build_readiness_parse_result_from_values,
    dxf_path_for_svg,
    format_font_asset_label,
    format_glyph_detail,
    format_readiness_summary,
    layout_from_values,
    output_path_for_format,
    run_background,
    validate_output_formats,
)


class FakeRoot:
    def __init__(self):
        self.callbacks = []

    def after(self, delay, callback):
        self.callbacks.append((delay, callback))


def test_build_design_from_manual_values_accepts_user_edits():
    design = build_design_from_values(" Iris ", "4", "3", "2", "flowers/DaisyApril.svg", "font.ttf", "Daisy")

    assert design.text == "Iris"
    assert design.month == 4
    assert design.font == 3
    assert design.flower == 2
    assert design.flower_asset_path == Path("flowers/DaisyApril.svg")
    assert design.font_path == Path("font.ttf")
    assert design.flower_name == "Daisy"


def test_build_design_from_manual_values_accepts_extended_asset_and_font_indexes_when_paths_exist():
    design = build_design_from_values(
        " Iris ",
        "4",
        "8",
        "12",
        "flowers/CustomAsset.svg",
        "fonts/CustomFont.ttf",
        "Custom Asset",
    )

    assert design.font == 8
    assert design.flower == 12
    assert design.flower_asset_path == Path("flowers/CustomAsset.svg")
    assert design.font_path == Path("fonts/CustomFont.ttf")


def test_build_design_from_manual_values_rejects_invalid_manual_edits():
    with pytest.raises(ValueError):
        build_design_from_values("Iris", "13", "1", "1")


def test_build_readiness_parse_result_from_manual_values_lowers_asset_confidence_for_missing_assets():
    result = build_readiness_parse_result_from_values("Iris", "6", "2", "1", None, None, "name")

    assert result.parse_confidence == 1.0
    assert result.asset_confidence < 1.0
    assert "Missing flower asset" in result.warnings
    assert "Missing font asset" in result.warnings


def test_dxf_path_for_svg_reuses_output_stem():
    assert dxf_path_for_svg(Path("outputs/result.svg")) == Path("outputs/result.dxf")


def test_layout_from_values_parses_numeric_layout_fields():
    layout = layout_from_values(
        {
            "canvas_width": "1372",
            "canvas_height": "1280",
            "flower_x": "310",
            "flower_y": "40",
            "flower_width": "1060",
            "flower_height": "1060",
            "text_x": "1210",
            "text_y": "1090",
            "text_width": "804",
            "text_height": "260",
            "text_size": "190",
        }
    )

    assert layout.canvas_width == 1372
    assert layout.canvas_height == 1280
    assert layout.flower_width == 1060
    assert layout.text_width == 804
    assert layout.text_height == 260
    assert layout.text_size == 190


def test_preview_text_ink_image_is_cropped_to_visible_black_pixels():
    result = _preview_text_ink_image("gyjpq", 64, None)

    assert result is not None
    image, offset_left, offset_top = result
    assert image.width > 0
    assert image.height > 0
    assert image.getbbox() == (0, 0, image.width, image.height)
    assert isinstance(offset_left, float)
    assert isinstance(offset_top, float)


def test_preview_text_fill_image_resizes_black_ink_to_target_box():
    result = ui_app_module._preview_text_fill_image("Hi", 64, None, 240, 80)

    assert result is not None
    image = result
    assert image.size == (240, 80)
    assert image.getbbox() == (0, 0, 240, 80)


def test_ttf_family_name_reads_birthmonth_font_family():
    font_path = Path("Birthmonth_font.ttf")
    if not font_path.is_file():
        pytest.skip("Optional business font asset is not present")

    assert _ttf_family_name(font_path) == "birthmonth by hannah"


def test_output_path_for_format_reuses_output_stem():
    assert output_path_for_format(Path("outputs/result.svg"), "svg") == Path("outputs/result.svg")
    assert output_path_for_format(Path("outputs/result.svg"), "dxf") == Path("outputs/result.dxf")
    assert output_path_for_format(Path("outputs/result.svg"), "png") == Path("outputs/result.png")


def test_validate_output_formats_requires_at_least_one_format():
    with pytest.raises(ValueError):
        validate_output_formats([])

    assert validate_output_formats(["svg", "bad", "png", "svg"]) == ("svg", "png")


def test_birth_flower_app_initializes_desktop_ui_state():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        assert root.title() == "Birth Flower MVP"
        assert bool(root.cget("menu"))
        assert set(APP_COLORS) >= {"background", "panel", "border", "text", "muted", "warning"}
        assert app.remark_text is None or isinstance(app.remark_text, tk.Text)
        assert app.remark_text is not None
        assert int(app.remark_text.cget("height")) == 4
        assert app.confirm_button is None or hasattr(app.confirm_button, "invoke")
        assert isinstance(app.section_frames, dict)
        assert set(app.section_frames) >= {
            "preview_panel",
            "function_panel",
            "order_panel",
            "production_panel",
            "production_bar",
        }
        assert hasattr(app, "current_glyph_result")
        assert root.minsize() == (760, 560)
        assert app.preview_canvas is not None
        assert app.preview_canvas.bind("<Button-1>")
        assert app.preview_canvas.bind("<B1-Motion>")
        assert app.preview_canvas.bind("<ButtonRelease-1>")
        assert app.preview_canvas.bind("<Double-Button-1>")
        assert app.preview_canvas.bind("<Delete>")
        assert app.preview_canvas.bind("<BackSpace>")
        menu = root.nametowidget(root.cget("menu"))
        file_menu = None
        edit_menu = None
        for index in range(menu.index("end") + 1):
            if menu.type(index) == "cascade" and menu.entrycget(index, "label") == "文件":
                file_menu = root.nametowidget(menu.entrycget(index, "menu"))
            if menu.type(index) == "cascade" and menu.entrycget(index, "label") == "编辑":
                edit_menu = root.nametowidget(menu.entrycget(index, "menu"))
        assert file_menu is not None
        file_labels = [
            file_menu.entrycget(index, "label")
            for index in range(file_menu.index("end") + 1)
            if file_menu.type(index) != "separator"
        ]
        assert "导入" in file_labels
        assert edit_menu is not None
        edit_labels = [
            edit_menu.entrycget(index, "label")
            for index in range(edit_menu.index("end") + 1)
            if edit_menu.type(index) != "separator"
        ]
        assert edit_labels == ["布局设置...", "字形..."]
        assert app.preview_canvas.bind("<Button-3>")
        assert app.preview_canvas.bind("<Button-2>")
        visible_texts = _widget_texts(root)
        assert "内容" in visible_texts
        assert "区分大小写" in visible_texts
        assert "添加" not in visible_texts
        assert "画布宽" not in visible_texts
        assert "画布高" not in visible_texts
        assert "生产输出" in visible_texts
        assert "人工确认并生成" in visible_texts
        assert "姓名/文字" not in visible_texts
        assert "重新扫描" not in visible_texts
        assert "显示辅助框" not in visible_texts
        assert "适配窗口" not in visible_texts
        assert "100%" not in visible_texts
        assert "重置布局" not in visible_texts
        assert "字形详情" not in visible_texts
    finally:
        root.destroy()


def test_import_asset_dispatches_font_and_flower_paths(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        font_path = tmp_path / "Custom.ttf"
        flower_path = tmp_path / "Custom.svg"
        font_path.write_bytes(b"font")
        flower_path.write_text("<svg/>", encoding="utf-8")
        calls = []

        def fake_import(path):
            calls.append(Path(path))

        monkeypatch.setattr(app, "_import_font_file", fake_import)
        monkeypatch.setattr(app, "_import_flower_file", fake_import)

        app._import_asset_path(font_path)
        app._import_asset_path(flower_path)

        assert calls == [font_path, flower_path]
        assert ".ttf" in IMPORTABLE_FONT_SUFFIXES
        assert ".svg" in IMPORTABLE_ASSET_SUFFIXES
    finally:
        root.destroy()


def test_import_font_file_selects_font_and_text(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        font_path = tmp_path / "Script.ttf"
        font_path.write_bytes(b"font")
        font_asset = FontAsset(name="Script", index=5, path=font_path)
        monkeypatch.setattr(ui_app_module, "scan_font_assets", lambda _path: [font_asset])
        monkeypatch.setattr(app, "_save_current_config", lambda: None)

        app._import_font_file(font_path)

        assert app.font_source_var.get() == str(font_path)
        assert app.font_assets == [font_asset]
        assert app.font_var.get() == "5"
        layer = app.document.selected_layer()
        assert isinstance(layer, TextLayer)
        assert app.selected_preview_item == layer.id
    finally:
        root.destroy()


def test_import_flower_file_selects_asset_and_flower(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        flower_path = tmp_path / "Custom.svg"
        flower_path.write_text("<svg/>", encoding="utf-8")
        flower_asset = FlowerAsset(name="Custom", month=12, flower=9, path=flower_path)
        monkeypatch.setattr(ui_app_module, "scan_flower_assets", lambda _path: [flower_asset])
        monkeypatch.setattr(app, "_save_current_config", lambda: None)

        app._import_flower_file(flower_path)

        assert app.flower_dir_var.get() == str(tmp_path)
        assert app.flower_assets == [flower_asset]
        assert app.month_var.get() == "12"
        assert app.flower_var.get() == "9"
        assert app.pending_flower_asset_label == app._flower_label(flower_asset)
        assert len(app.document.layers) == 1
        assert isinstance(app.document.selected_layer(), ImageLayer)
        assert app.document.selected_layer().path == flower_path
    finally:
        root.destroy()


def test_confirm_rejects_bitmap_flower_when_dxf_is_selected(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        flower_path = tmp_path / "Imported.png"
        flower_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        asset = FlowerAsset(name="Imported", month=4, flower=9, path=flower_path)
        app.name_var.set("Iris")
        app.month_var.set("4")
        app.flower_var.set("9")
        app.font_var.set("1")
        app.flower_assets = [asset]
        app._refresh_flower_choices()
        label = app._flower_label(asset)
        app.flower_asset_var.set(label)
        app.output_format_vars["png"].set(False)
        app.output_format_vars["svg"].set(False)
        app.output_format_vars["dxf"].set(True)
        errors = []
        asked = []

        monkeypatch.setattr(ui_app_module.messagebox, "showerror", lambda title, message: errors.append((title, message)))
        monkeypatch.setattr(ui_app_module.messagebox, "askyesno", lambda *_args, **_kwargs: asked.append(True))

        app.confirm_and_generate()

        assert errors
        assert "位图素材无法导出 DXF" in errors[0][1]
        assert asked == []
    finally:
        root.destroy()


def test_double_click_text_opens_inline_editor_and_commits_content():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        layer = add_text_layer(app.document, "Rose", x=100, y=80, width=240, height=90, font_size=72)
        app.document.selected_layer_id = layer.id
        app._start_inline_text_edit(layer)

        assert app.inline_text_entry is not None
        app.inline_text_entry.delete("1.0", "end")
        app.inline_text_entry.insert("1.0", "Lily")
        app._commit_inline_text_edit()

        assert layer.text == "Lily"
        assert app.inline_text_entry is None
        assert len([item for item in app.document.layers if isinstance(item, TextLayer)]) == 1
    finally:
        root.destroy()


def test_inline_text_editor_has_no_visual_frame_and_hides_selection_box():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        layer = add_text_layer(app.document, "Rose", x=100, y=80, width=240, height=90, font_size=72)
        app.document.selected_layer_id = layer.id
        app._redraw_preview()
        assert app.preview_canvas is not None
        assert app.preview_canvas.find_withtag("selection_box")

        app._start_inline_text_edit(layer)
        app._redraw_preview()

        assert app.inline_text_entry is not None
        assert app.inline_text_entry.cget("relief") == "flat"
        assert int(app.inline_text_entry.cget("borderwidth")) == 0
        assert int(app.inline_text_entry.cget("highlightthickness")) == 0
        assert not app.preview_canvas.find_withtag("selection_box")
        assert not app.preview_canvas.find_withtag("selection_handle")
    finally:
        root.destroy()


def test_inline_text_editor_updates_layer_live_and_preserves_pua(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        layer = add_text_layer(app.document, "old", x=100, y=80, width=240, height=90, font_size=72)
        app.document.selected_layer_id = layer.id
        app._start_inline_text_edit(layer)

        redraws = []
        monkeypatch.setattr(app, "_schedule_canvas_render", lambda delay_ms=25: redraws.append(delay_ms))
        assert app.inline_text_entry is not None
        app.inline_text_entry.delete("1.0", "end")
        app.inline_text_entry.insert("1.0", "h\ue014v")
        app.inline_text_entry.edit_modified(True)
        app._on_inline_text_modified(SimpleNamespace())

        assert layer.text == "h\ue014v"
        assert app.layer_text_var.get() == "h\ue014v"
        assert redraws == [25]
        assert len(app.document.layers) == 1
    finally:
        root.destroy()


def test_restore_glyph_uses_inline_text_selection(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    warnings = []
    monkeypatch.setattr(ui_app_module.messagebox, "showwarning", lambda title, message: warnings.append((title, message)))

    try:
        app = BirthFlowerApp(root)
        layer = add_text_layer(app.document, "Jazmin", x=100, y=80, width=240, height=90, font_size=72)
        layer.glyph_overrides[5] = {
            "index": 5,
            "base_char": "n",
            "original_char": "n",
            "replacement_char": "\ue123",
            "char": "\ue123",
            "codepoint": "E123",
            "glyph_name": "uniE123",
            "source": "manual",
        }
        app.document.selected_layer_id = layer.id
        app._apply_text_layer_render_text(layer)
        assert layer.render_text == "Jazmi\ue123"

        app._start_inline_text_edit(layer)
        assert app.inline_text_entry is not None
        app.inline_text_entry.tag_remove("sel", "1.0", "end")
        app.inline_text_entry.tag_add("sel", "1.5", "1.6")
        app.selected_glyph_position = None

        app.restore_selected_glyph_override()

        assert warnings == []
        assert app.selected_glyph_position == 5
        assert layer.glyph_overrides == {}
        assert layer.render_text == "Jazmin"
    finally:
        root.destroy()


def test_apply_recommended_glyph_uses_inline_text_selection(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    font_path = tmp_path / "Font2.ttf"
    font_path.write_bytes(b"fake font")
    variant = GlyphVariant.from_mapping(
        {
            "base_char": "n",
            "replacement_char": "\ue123",
            "codepoint": "E123",
            "glyph_name": "uniE123",
            "font_id": "Font 2",
            "font_path": str(font_path),
            "display_name": "n ending glyph",
            "usage": "end",
            "source": "manual_binding",
        }
    )

    monkeypatch.setattr(ui_app_module, "build_glyph_catalog", lambda *_args, **_kwargs: object(), raising=False)
    monkeypatch.setattr(ui_app_module, "recommended_glyph_variants", lambda _catalog, char: [variant] if char == "n" else [], raising=False)

    opened = []

    try:
        app = BirthFlowerApp(root)
        monkeypatch.setattr(app, "_selected_font_path", lambda: font_path)
        monkeypatch.setattr(app, "open_glyph_panel", lambda: opened.append(True))
        layer = add_text_layer(app.document, "Jazmin", x=100, y=80, width=240, height=90, font_size=72)
        app.document.selected_layer_id = layer.id
        app._start_inline_text_edit(layer)
        assert app.inline_text_entry is not None
        app.inline_text_entry.tag_remove("sel", "1.0", "end")
        app.inline_text_entry.tag_add("sel", "1.5", "1.6")

        app.apply_recommended_glyph_to_selection()

        assert opened == []
        assert app.selected_glyph_position == 5
        assert layer.glyph_overrides[5]["glyph_name"] == "uniE123"
        assert layer.render_text == "Jazmi\ue123"
    finally:
        root.destroy()


def test_inline_text_editor_escape_restores_original_text():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        layer = add_text_layer(app.document, "Rose", x=100, y=80, width=240, height=90, font_size=72)
        app.document.selected_layer_id = layer.id
        app._start_inline_text_edit(layer)

        assert app.inline_text_entry is not None
        app.inline_text_entry.delete("1.0", "end")
        app.inline_text_entry.insert("1.0", "Lily")
        app.inline_text_entry.edit_modified(True)
        app._on_inline_text_modified(SimpleNamespace())
        assert layer.text == "Lily"

        app._cancel_inline_text_edit()

        assert layer.text == "Rose"
        assert app.inline_text_entry is None
        assert len(app.document.layers) == 1
    finally:
        root.destroy()


def test_inline_text_editor_exit_removes_canvas_window_and_border():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        layer = add_text_layer(app.document, "Rose", x=100, y=80, width=240, height=90, font_size=72)
        app.document.selected_layer_id = layer.id
        app._start_inline_text_edit(layer)

        assert app.inline_text_entry is not None
        assert app.preview_canvas is not None
        assert any(app.preview_canvas.type(item) == "window" for item in app.preview_canvas.find_all())

        app._commit_inline_text_edit()
        app._redraw_preview()

        assert app.inline_text_entry is None
        assert app.inline_text_window is None
        assert not any(app.preview_canvas.type(item) == "window" for item in app.preview_canvas.find_all())
        assert not app.preview_canvas.find_withtag("inline_text_editor")
    finally:
        root.destroy()


def test_case_sensitive_checkbox_controls_render_content_case():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        app.name_var.set("AbCd")

        app.case_sensitive_var.set(True)
        assert app._content_text_for_render() == "AbCd"

        app.case_sensitive_var.set(False)
        assert app._content_text_for_render() == "abcd"
    finally:
        root.destroy()


def test_preview_selection_draws_box_and_can_delete_selected_flower(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        assert app.preview_canvas is not None
        flower_path = tmp_path / "RoseJune.svg"
        flower_path.write_text(
            '<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L10 10"/></svg>',
            encoding="utf-8",
        )
        label = "June / flower 1 / Rose"
        app.flower_label_map = {
            label: FlowerAsset(name="Rose", month=6, flower=1, path=flower_path, display_name="Rose")
        }
        app.flower_asset_var.set(label)

        app._add_selected_flower_to_canvas()
        layer = app.document.selected_layer()
        assert isinstance(layer, ImageLayer)
        root.update_idletasks()

        assert app.preview_canvas.find_withtag("selection_box")
        assert app.preview_canvas.find_withtag("selection_handle")

        app._delete_selected_preview_item()

        assert app.document.layers == []
        assert app.selected_preview_item is None
    finally:
        root.destroy()


def test_canvas_context_menu_selects_layer_and_exposes_canvas_and_glyph_actions(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    menus = []

    class FakeMenu:
        def __init__(self, *_args, **_kwargs):
            self.labels = []
            menus.append(self)

        def add_command(self, **kwargs):
            self.labels.append(kwargs.get("label"))

        def add_separator(self):
            self.labels.append("---")

        def tk_popup(self, *_args):
            self.popup_called = True

        def grab_release(self):
            self.released = True

    try:
        app = BirthFlowerApp(root)
        monkeypatch.setattr(ui_app_module.tk, "Menu", FakeMenu)
        layer = add_text_layer(app.document, "Rose", x=100, y=80, width=240, height=90, font_size=72)
        assert app.preview_canvas is not None
        app._redraw_preview()
        layout = layout_from_values(app.layout_vars)
        scale, offset_x, offset_y = app._preview_transform(layout)
        event = SimpleNamespace(
            x=int(offset_x + (layer.x + 10) * scale),
            y=int(offset_y + (layer.y + 10) * scale),
            x_root=300,
            y_root=240,
        )

        app._show_canvas_context_menu(event)

        assert app.document.selected_layer_id == layer.id
        assert menus
        labels = menus[-1].labels
        assert "编辑文本" in labels
        assert "删除" in labels
        assert "锁定" in labels
        assert "上移" in labels
        assert "下移" in labels
        assert "置顶" in labels
        assert "置底" in labels
        assert "字形..." in labels
        assert "应用推荐字形" in labels
        assert "恢复普通字符" in labels
    finally:
        root.destroy()



def test_flower_combo_change_without_selected_layer_only_updates_pending_material(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        flower_path = tmp_path / "Rose.svg"
        flower_path.write_text("<svg/>", encoding="utf-8")
        asset = FlowerAsset(name="Rose", month=6, flower=1, path=flower_path, display_name="Rose")
        app.flower_assets = [asset]
        app._refresh_flower_choices()
        label = app._flower_label(asset)

        app._select_preview_item(None)
        app.flower_asset_var.set(label)
        app._on_flower_combo_selected()

        assert app.document.layers == []
        assert app.pending_flower_asset_label == label
        assert app.flower_var.get() == "1"
    finally:
        root.destroy()


def test_flower_combo_change_while_text_layer_selected_does_not_create_or_modify_text(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        flower_path = tmp_path / "Daisy.svg"
        flower_path.write_text("<svg/>", encoding="utf-8")
        asset = FlowerAsset(name="Daisy", month=4, flower=2, path=flower_path, display_name="Daisy")
        app.flower_assets = [asset]
        app._refresh_flower_choices()
        label = app._flower_label(asset)
        app.name_var.set("Original")
        app._add_text_layer_from_fields()
        layer = app.document.selected_layer()
        assert isinstance(layer, TextLayer)

        app.flower_asset_var.set(label)
        app._on_flower_combo_selected()

        assert len(app.document.layers) == 1
        assert app.document.selected_layer() is layer
        assert layer.text == "Original"
        assert app.pending_flower_asset_label == label
    finally:
        root.destroy()


def test_flower_combo_change_while_image_layer_selected_replaces_only_current_image(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        first_path = tmp_path / "Rose.svg"
        second_path = tmp_path / "Lily.svg"
        first_path.write_text("<svg/>", encoding="utf-8")
        second_path.write_text("<svg/>", encoding="utf-8")
        first = FlowerAsset(name="Rose", month=6, flower=1, path=first_path, display_name="Rose")
        second = FlowerAsset(name="Lily", month=7, flower=2, path=second_path, display_name="Lily")
        app.flower_assets = [first, second]
        app._refresh_flower_choices()
        first_label = app._flower_label(first)
        second_label = app._flower_label(second)
        app.flower_asset_var.set(first_label)
        app._add_selected_flower_to_canvas()
        layer = app.document.selected_layer()
        assert isinstance(layer, ImageLayer)

        app.flower_asset_var.set(second_label)
        app._on_flower_combo_selected()

        assert len(app.document.layers) == 1
        assert app.document.selected_layer() is layer
        assert layer.path == second_path
        assert layer.name == "Lily"
        assert app.pending_flower_asset_label == second_label
    finally:
        root.destroy()


def test_programmatic_flower_refresh_and_parse_do_not_add_layers(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        flower_path = tmp_path / "IrisMay.svg"
        flower_path.write_text("<svg/>", encoding="utf-8")
        asset = FlowerAsset(name="Iris", month=5, flower=1, path=flower_path, display_name="Iris")
        app.flower_dir_var.set(str(tmp_path))
        app.flower_assets = [asset]
        warnings = []
        monkeypatch.setattr(ui_app_module.messagebox, "showwarning", lambda title, message: warnings.append((title, message)))

        app._refresh_flower_choices()
        app._apply_parse_result(SimpleNamespace(text="Ivy", month=5, font=1, flower=1, warnings=[]))

        assert app.document.layers == []
        assert app.pending_flower_asset_label == app._flower_label(asset)
        assert warnings == []
    finally:
        root.destroy()

def test_font_settings_uses_one_choose_font_button():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        app.open_settings()
        root.update_idletasks()
        texts = _widget_texts(root)

        assert "选择字体" in texts
        assert "选择字体文件" not in texts
        assert "选择字体目录" not in texts
    finally:
        root.destroy()


def test_output_settings_exposes_format_path_and_resolution():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        app.open_settings()
        root.update_idletasks()
        settings_window = [child for child in root.winfo_children() if isinstance(child, tk.Toplevel)][-1]
        notebook = next(child for child in settings_window.winfo_children() if isinstance(child, ttk.Notebook))
        tab_texts = [notebook.tab(index, "text") for index in range(len(notebook.tabs()))]
        texts = _widget_texts(root)

        assert "输出设置" in tab_texts
        assert "输出格式" in texts
        assert "输出路径" in texts
        assert "输出分辨率" in texts
        assert "画布宽" in texts
        assert "画布高" in texts
    finally:
        root.destroy()


def test_glyph_menu_opens_ps_like_glyph_window():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        app.open_glyph_panel()
        root.update()

        panels = [child for child in root.winfo_children() if isinstance(child, tk.Toplevel)]
        assert panels
        panel = panels[-1]
        assert panel.title() == "字形"
        texts = _widget_texts(panel)
        assert "字形" in texts
        assert "字体" in texts
        assert "样式" in texts
        assert "筛选" in texts
        assert "状态" in texts
        assert "识别字母" in texts
        assert "字形码位" in texts
        assert "提醒" in texts
        assert "字形网格" in texts
        assert "字母 a-z" not in texts
        assert "当前字体 PUA glyph" not in texts
    finally:
        root.destroy()


def test_glyph_help_explains_font2_default_binding(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    captured = {}

    def fake_showinfo(title, message):
        captured["title"] = title
        captured["message"] = message

    monkeypatch.setattr(ui_app_module.messagebox, "showinfo", fake_showinfo)

    try:
        app = BirthFlowerApp(root)
        app.show_glyph_help()

        assert captured["title"] == "字形使用说明"
        assert "Font 2 已内置 a-z 26 个结尾字形" in captured["message"]
        assert "a=U+E068" in captured["message"]
        assert "z=U+E081" in captured["message"]
        assert "编辑 -> 管理字形绑定" in captured["message"]
        assert "按 a-z 绑定" in captured["message"]
    finally:
        root.destroy()


def _widget_texts(widget):
    texts = []
    for child in widget.winfo_children():
        if hasattr(child, "cget"):
            try:
                text = child.cget("text")
            except tk.TclError:
                text = ""
            if text:
                texts.append(text)
        texts.extend(_widget_texts(child))
    return texts


def test_build_ai_parse_config_prefers_session_key_then_profile_environment():
    profile = AIProfile(
        provider="deepseek",
        model="gpt-5-nano",
        base_url="https://api.deepseek.com",
        api_key_env_var="SHOP_OPENAI_KEY",
        project_env_var="SHOP_PROJECT",
        org_env_var="SHOP_ORG",
        enabled=True,
        prefer_ai=True,
    )

    from_session = build_ai_parse_config(
        profile,
        session_api_key="sk-session",
        environ={"SHOP_OPENAI_KEY": "sk-env", "SHOP_PROJECT": "proj_1", "SHOP_ORG": "org_1"},
    )
    from_env = build_ai_parse_config(
        profile,
        session_api_key="",
        environ={"SHOP_OPENAI_KEY": "sk-env", "SHOP_PROJECT": "proj_1", "SHOP_ORG": "org_1"},
    )

    assert from_session.api_key == "sk-session"
    assert from_env.api_key == "sk-env"
    assert from_env.project == "proj_1"
    assert from_env.organization == "org_1"
    assert from_env.model == "gpt-5-nano"
    assert from_env.provider == "deepseek"
    assert from_env.base_url == "https://api.deepseek.com"
    assert from_env.prefer_ai is True


def test_build_ai_profile_from_settings_defaults_deepseek_fields_without_secret():
    profile = build_ai_profile_from_settings(
        AIProfile(name="OpenAI default"),
        provider="deepseek",
        model="",
        base_url="",
        api_key_env_var="",
        project_env_var="",
        org_env_var="",
        prefer_ai=True,
    )

    assert profile.provider == "deepseek"
    assert profile.model == "deepseek-v4-flash"
    assert profile.base_url == "https://api.deepseek.com"
    assert profile.api_key_env_var == "DEEPSEEK_API_KEY"
    assert profile.project_env_var == ""
    assert profile.org_env_var == ""
    assert profile.prefer_ai is True


def test_format_readiness_summary_shows_all_confidence_parts():
    summary = format_readiness_summary(
        GenerationReadiness(
            parse_confidence=0.97,
            asset_confidence=0.82,
            layout_confidence=0.45,
            overall_confidence=0.45,
            status="Needs review",
            warnings=["Text exceeds safe area"],
        )
    )

    assert "Needs review" in summary
    assert "parse 0.97" in summary
    assert "asset 0.82" in summary
    assert "layout 0.45" in summary
    assert "overall 0.45" in summary


def test_format_glyph_detail_shows_chinese_status_and_review_reason():
    detail = format_glyph_detail(
        GlyphApplyResult(
            original_text="Jazmin",
            render_text="Jazmi" + chr(0xE014),
            font_design="Font 4",
            apply_mode="replace_last_letter",
            source_letter="n",
            source_index=5,
            glyph_codepoint="U+E014",
            glyph_char=chr(0xE014),
            glyph_source="auto",
            needs_review=True,
            reason="长文本，建议人工确认",
        )
    )

    assert detail["status"] == "自动"
    assert detail["letter"] == "n"
    assert detail["codepoint"] == "U+E014"
    assert detail["apply_mode"] == "替换最后字母"
    assert detail["reason"] == "长文本，建议人工确认"


def test_format_font_asset_label_shows_font_design_size_and_glyph_status(tmp_path):
    path = tmp_path / "Malovely Script.ttf"
    path.write_bytes(b"font")
    label = format_font_asset_label(
        FontAsset(
            name="Malovely Script",
            index=2,
            path=path,
            font_design="Font 2",
            file_size=105944,
            has_ending_glyphs=True,
        )
    )

    assert label == "Font 2 - Malovely Script - Malovely Script.ttf - 103.5 KB - 含字形"


def test_run_background_returns_before_slow_work_finishes():
    root = FakeRoot()
    release = threading.Event()
    started = threading.Event()
    results = []
    errors = []

    def work():
        started.set()
        release.wait(timeout=2)
        return "ok"

    thread = run_background(root, work, results.append, errors.append)

    assert started.wait(timeout=1)
    assert thread.is_alive()
    assert root.callbacks == []

    release.set()
    thread.join(timeout=1)

    assert len(root.callbacks) == 1
    delay, callback = root.callbacks[0]
    assert delay == 0
    callback()
    assert results == ["ok"]
    assert errors == []


def test_global_layout_defaults_only_initialize_new_layers(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        monkeypatch.setattr(app, "_save_current_config", lambda: None)
        first_path = tmp_path / "First.svg"
        second_path = tmp_path / "Second.svg"
        first_path.write_text('<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        second_path.write_text('<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        first = FlowerAsset(name="First", month=1, flower=1, path=first_path, display_name="First")
        second = FlowerAsset(name="Second", month=2, flower=1, path=second_path, display_name="Second")
        app.flower_label_map = {"first": first, "second": second}

        app.layout_vars["flower_x"].set("10")
        app.layout_vars["flower_y"].set("20")
        app.layout_vars["flower_width"].set("300")
        app.layout_vars["flower_height"].set("400")
        app.flower_asset_var.set("first")
        app._add_selected_flower_to_canvas()
        first_layer = app.document.selected_layer()

        app.layout_vars["flower_x"].set("700")
        app.layout_vars["flower_y"].set("800")
        app.layout_vars["flower_width"].set("90")
        app.layout_vars["flower_height"].set("100")
        app.flower_asset_var.set("second")
        app._add_selected_flower_to_canvas()
        second_layer = app.document.selected_layer()

        assert first_layer.x == 10
        assert first_layer.y == 20
        assert first_layer.width == 300
        assert first_layer.height == 400
        assert second_layer.x == 700
        assert second_layer.y == 800
        assert second_layer.width == 90
        assert second_layer.height == 100
    finally:
        root.destroy()
