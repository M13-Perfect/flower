import threading
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import pytest

from config_store import AIProfile
from generation_readiness import GenerationReadiness
from glyph_service import GlyphApplyResult
from models import FlowerAsset, FontAsset
from ui_app import (
    APP_COLORS,
    BirthFlowerApp,
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
        edit_menu = None
        for index in range(menu.index("end") + 1):
            if menu.type(index) == "cascade" and menu.entrycget(index, "label") == "编辑":
                edit_menu = root.nametowidget(menu.entrycget(index, "menu"))
                break
        assert edit_menu is not None
        edit_labels = [
            edit_menu.entrycget(index, "label")
            for index in range(edit_menu.index("end") + 1)
            if edit_menu.type(index) != "separator"
        ]
        assert edit_labels == ["字形..."]
        visible_texts = _widget_texts(root)
        assert "内容" in visible_texts
        assert "区分大小写" in visible_texts
        assert "添加" in visible_texts
        assert "画布宽" in visible_texts
        assert "画布高" in visible_texts
        assert "字宽" in visible_texts
        assert "字高" in visible_texts
        assert "字号" not in visible_texts
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


def test_add_buttons_put_selected_asset_and_font_on_canvas():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        flower_label = "1 - Snowdrop | SnowdropJanuary.svg"
        font_label = "Font 2 - Script"
        app.flower_label_map = {
            flower_label: FlowerAsset(name="Snowdrop", month=1, flower=1, path=Path("missing.svg"))
        }
        app.font_label_map = {
            font_label: FontAsset(name="Script", index=2, path=Path("missing.ttf"))
        }
        app.flower_asset_var.set(flower_label)
        app.font_asset_var.set(font_label)

        app._add_selected_flower_to_canvas()
        app._add_selected_font_to_canvas()

        assert app.month_var.get() == "1"
        assert app.flower_var.get() == "1"
        assert app.font_var.get() == "2"
        assert app.selected_preview_item == "text"
    finally:
        root.destroy()


def test_double_click_text_opens_inline_editor_and_commits_content():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        app.name_var.set("Rose")
        app._start_inline_text_edit(SimpleNamespace(x=120, y=80))

        assert app.inline_text_entry is not None
        app.inline_text_entry.delete(0, "end")
        app.inline_text_entry.insert(0, "Lily")
        app._commit_inline_text_edit()

        assert app.name_var.get() == "Lily"
        assert app.inline_text_entry is None
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

        app._select_preview_item("flower")
        root.update_idletasks()

        assert app.preview_canvas.find_withtag("selection_box")
        assert app.preview_canvas.find_withtag("flower_handle")

        app._delete_selected_preview_item()

        assert app.flower_asset_var.get() == ""
        assert app.flower_var.get() == "0"
        assert app.selected_preview_item is None
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
