from models import Document, TextLayer, add_text_layer
from renderer import render_document_png, render_document_svg
from text_renderer import TextRenderer


def test_text_renderer_empty_text_returns_transparent_image_without_crashing():
    layer = TextLayer(text="", original_text="", render_text="", width=120, height=48, text_box_width=120, text_box_height=48)

    result = TextRenderer().render_layer(layer)

    assert result.image.size == (120, 48)
    assert result.render_text == ""
    assert result.image.getbbox() is None
    assert any("空文本" in warning for warning in result.warnings)


def test_text_renderer_missing_font_path_reports_warning(tmp_path):
    missing_font = tmp_path / "missing.ttf"
    layer = TextLayer(text="Rose", font_path=missing_font, width=180, height=72, text_box_width=180, text_box_height=72)

    result = TextRenderer().render_layer(layer)

    assert result.image.size == (180, 72)
    assert result.render_text == "Rose"
    assert any("字体文件不存在" in warning for warning in result.warnings)


def test_text_renderer_invalid_glyph_override_falls_back_to_normal_character():
    layer = TextLayer(
        text="abc",
        glyph_overrides={
            "1": {
                "index": 1,
                "base_char": "b",
                "replacement_char": "",
                "glyph_id": -1,
                "codepoint": "not-a-codepoint",
                "source": "manual",
            }
        },
        width=180,
        height=72,
        text_box_width=180,
        text_box_height=72,
    )

    result = TextRenderer().render_layer(layer)

    assert result.render_text == "abc"
    assert result.glyph_overrides == {}
    assert any("字形" in warning or "codepoint" in warning for warning in result.warnings)


def test_text_renderer_rerenders_after_text_changes():
    layer = TextLayer(text="A", width=120, height=60, text_box_width=120, text_box_height=60)
    renderer = TextRenderer()

    first = renderer.render_layer(layer)
    layer.original_text = "B"
    layer.text = "B"
    second = renderer.render_layer(layer)

    assert first.render_text == "A"
    assert second.render_text == "B"
    assert first.image is not second.image


def test_text_renderer_centers_ink_without_stretching_text_box():
    layer = TextLayer(
        text="Hi",
        width=240,
        height=80,
        text_box_width=240,
        text_box_height=80,
        font_size=64,
        align="center",
        vertical_align="middle",
    )

    result = TextRenderer().render_layer(layer)

    assert result.image.size == (240, 80)
    assert result.ink_bbox is not None
    ink = result.ink_bbox
    # 等比改造：墨迹不再拉伸铺满四边，而是按真实比例居中、四周留白。
    assert ink.left > 1
    assert ink.right < 239
    assert ink.top > 1
    assert ink.bottom < 79
    # 水平居中（默认 align=center）。
    assert abs((ink.left + ink.right) / 2 - 120) <= 12


def test_document_png_uses_text_renderer_for_text_layers(monkeypatch, tmp_path):
    calls = []

    class SpyTextRenderer(TextRenderer):
        def render_layer(self, layer):
            calls.append(layer.id)
            return super().render_layer(layer)

    import renderer as renderer_module

    monkeypatch.setattr(renderer_module, "TextRenderer", SpyTextRenderer)
    document = Document(canvas_width=240, canvas_height=120)
    layer = add_text_layer(document, "Live", x=20, y=20, width=120, height=48, font_size=28)

    output = render_document_png(document, tmp_path / "document.png")

    assert output.exists()
    assert calls == [layer.id]


def test_document_svg_export_does_not_include_editor_or_selection_helpers(tmp_path):
    document = Document(canvas_width=240, canvas_height=120)
    add_text_layer(document, "Clean", x=20, y=20, width=120, height=48, font_size=28)

    output = render_document_svg(document, tmp_path / "document.svg")
    svg = output.read_text(encoding="utf-8")

    assert "selection_box" not in svg
    assert "selection_handle" not in svg
    assert "inline_text_editor" not in svg


def test_document_svg_uses_text_renderer_for_text_layers(monkeypatch, tmp_path):
    calls = []

    class SpyTextRenderer(TextRenderer):
        def render_layer(self, layer):
            calls.append(layer.id)
            return super().render_layer(layer)

    import renderer as renderer_module

    monkeypatch.setattr(renderer_module, "TextRenderer", SpyTextRenderer)
    document = Document(canvas_width=240, canvas_height=120)
    layer = add_text_layer(document, "Vector?", x=20, y=20, width=120, height=48, font_size=28)

    output = render_document_svg(document, tmp_path / "document.svg")
    svg = output.read_text(encoding="utf-8")

    assert calls == [layer.id]
    assert "data:image/png;base64," in svg
    assert "TextLayer render_text: Vector?" in svg
