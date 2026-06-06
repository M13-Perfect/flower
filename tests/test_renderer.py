import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from models import BirthFlowerDesign, EngravingLayout
from renderer import PreviewCache, flower_preview_polylines, render_dxf, render_png, render_svg


def test_render_svg_creates_a_pure_vector_birth_flower_file(tmp_path):
    output_path = tmp_path / "birth-flower.svg"
    design = BirthFlowerDesign(text="Lily", month=3, font=2, flower=1)

    result_path = render_svg(design, output_path)

    assert result_path == output_path
    svg = output_path.read_text(encoding="utf-8")
    assert "<svg" in svg
    assert 'width="1732"' in svg
    assert 'height="1280"' in svg
    assert "Lily" in svg
    assert "March" in svg
    assert "<image" not in svg


def test_render_png_uses_layout_canvas_size(tmp_path, monkeypatch):
    output_path = tmp_path / "birth-flower.png"
    created_sizes = []

    class FakeImage:
        def __init__(self, size):
            self.size = size

        def save(self, path):
            Path(path).write_bytes(b"fake png")

    class FakeDraw:
        def ellipse(self, *_args, **_kwargs):
            return None

        def text(self, *_args, **_kwargs):
            return None

    def fake_new(_mode, size, _color):
        created_sizes.append(size)
        return FakeImage(size)

    image_module = SimpleNamespace(new=fake_new)
    draw_module = SimpleNamespace(Draw=lambda _image: FakeDraw())
    font_module = SimpleNamespace(load_default=lambda: object())
    monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(Image=image_module, ImageDraw=draw_module, ImageFont=font_module))
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageDraw", draw_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageFont", font_module)
    design = BirthFlowerDesign(
        text="Lily",
        month=3,
        font=2,
        flower=1,
        layout=EngravingLayout(canvas_width=1372, canvas_height=1280),
    )

    render_png(design, output_path)

    assert created_sizes[0] == (1372, 1280)


def test_render_png_does_not_draw_month_footer_label(tmp_path, monkeypatch):
    output_path = tmp_path / "birth-flower.png"
    drawn_texts = []

    class FakeImage:
        def __init__(self, size):
            self.size = size

        def save(self, path):
            Path(path).write_bytes(b"fake png")

    class FakeDraw:
        def ellipse(self, *_args, **_kwargs):
            return None

        def text(self, _position, text, **_kwargs):
            drawn_texts.append(text)

    def fake_new(_mode, size, _color):
        return FakeImage(size)

    image_module = SimpleNamespace(new=fake_new)
    draw_module = SimpleNamespace(Draw=lambda _image: FakeDraw())
    font_module = SimpleNamespace(load_default=lambda: object())
    monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(Image=image_module, ImageDraw=draw_module, ImageFont=font_module))
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageDraw", draw_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageFont", font_module)
    design = BirthFlowerDesign(text="hwl", month=1, font=2, flower=1)

    render_png(design, output_path)

    assert "hwl" in drawn_texts
    assert "January Birth Flower" not in drawn_texts


def test_render_png_draws_selected_flower_svg_polylines(tmp_path, monkeypatch):
    output_path = tmp_path / "birth-flower.png"
    flower_path = tmp_path / "LineFlower.svg"
    flower_path.write_text(
        '<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L10 10"/></svg>',
        encoding="utf-8",
    )
    drawn_lines = []

    class FakeImage:
        def __init__(self, size):
            self.size = size

        def save(self, path):
            Path(path).write_bytes(b"fake png")

    class FakeDraw:
        def ellipse(self, *_args, **_kwargs):
            return None

        def line(self, points, **kwargs):
            drawn_lines.append((points, kwargs))

        def text(self, *_args, **_kwargs):
            return None

    def fake_new(_mode, size, _color):
        return FakeImage(size)

    image_module = SimpleNamespace(new=fake_new)
    draw_module = SimpleNamespace(Draw=lambda _image: FakeDraw())
    font_module = SimpleNamespace(load_default=lambda: object())
    monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(Image=image_module, ImageDraw=draw_module, ImageFont=font_module))
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageDraw", draw_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageFont", font_module)
    design = BirthFlowerDesign(
        text="Lily",
        month=3,
        font=2,
        flower=1,
        flower_asset_path=flower_path,
        layout=EngravingLayout(
            canvas_width=100,
            canvas_height=100,
            flower_x=10,
            flower_y=20,
            flower_width=80,
            flower_height=40,
        ),
    )

    render_png(design, output_path)

    assert drawn_lines == [([(30.0, 20.0), (70.0, 60.0)], {"fill": "#111111", "width": 2, "joint": "curve"})]


def test_render_svg_records_font_and_pua_text_risk_for_text_output(tmp_path):
    output_path = tmp_path / "glyph.svg"
    design = BirthFlowerDesign(text="Jazmi" + chr(0xE014), month=6, font=4, flower=1)

    render_svg(design, output_path)

    svg = output_path.read_text(encoding="utf-8")
    assert "PUA 字符" in svg
    assert "换环境可能显示异常" in svg


def test_render_svg_marks_unmapped_glyph_overrides_as_preview_only(tmp_path):
    output_path = tmp_path / "unmapped-glyph.svg"
    design = BirthFlowerDesign(
        text="Jazmin",
        month=6,
        font=4,
        flower=1,
        glyph_overrides={
            2: {
                "original_char": "z",
                "glyph_name": "z.swash",
                "glyph_id": 184,
                "codepoint": None,
            }
        },
    )

    render_svg(design, output_path)

    svg = output_path.read_text(encoding="utf-8")
    assert "z.swash" in svg
    assert "可预览但暂不支持导出" in svg


def test_render_svg_embeds_selected_flower_svg_and_font_reference(tmp_path):
    flower_path = tmp_path / "DaffodilMarch.svg"
    flower_path.write_text(
        '<svg width="3000px" height="3000px" xmlns="http://www.w3.org/2000/svg"><path d="M0 0h10v10z"/></svg>',
        encoding="utf-8",
    )
    font_path = tmp_path / "Birthmonth_font.ttf"
    font_path.write_bytes(b"font")
    output_path = tmp_path / "engraving.svg"
    design = BirthFlowerDesign(
        text="Victoria",
        month=3,
        font=1,
        flower=1,
        flower_asset_path=flower_path,
        font_path=font_path,
        flower_name="Daffodil",
        layout=EngravingLayout(
            canvas_width=1732,
            canvas_height=1280,
            flower_x=320,
            flower_y=60,
            flower_width=980,
            flower_height=980,
            text_x=1190,
            text_y=1080,
            text_size=170,
        ),
    )

    render_svg(design, output_path)

    svg = output_path.read_text(encoding="utf-8")
    assert "Daffodil" in svg
    assert "BirthFlowerSelected" in svg
    assert "Birthmonth_font.ttf" in svg
    assert "M0 0h10v10z" in svg
    assert 'id="flower-art"' in svg
    assert 'x="320"' in svg
    assert 'y="60"' in svg
    assert 'width="980"' in svg
    assert 'height="980"' in svg
    assert 'viewBox="0 0 10 10"' in svg
    assert 'preserveAspectRatio="xMidYMid meet"' in svg
    assert 'id="text-art"' in svg


def test_render_svg_allows_extended_indexes_when_asset_and_font_paths_are_selected(tmp_path):
    flower_path = tmp_path / "CustomAsset.svg"
    flower_path.write_text(
        '<svg width="100px" height="100px" xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L10 10"/></svg>',
        encoding="utf-8",
    )
    font_path = tmp_path / "CustomFont.ttf"
    font_path.write_bytes(b"font")
    output_path = tmp_path / "custom.svg"
    design = BirthFlowerDesign(
        text="Iris",
        month=4,
        font=8,
        flower=12,
        flower_asset_path=flower_path,
        font_path=font_path,
        flower_name="Custom Asset",
    )

    render_svg(design, output_path)

    svg = output_path.read_text(encoding="utf-8")
    assert "Custom Asset" in svg
    assert "CustomFont.ttf" in svg


def test_render_svg_embeds_selected_bitmap_flower_with_vector_warning(tmp_path):
    flower_path = tmp_path / "Imported.png"
    flower_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    output_path = tmp_path / "bitmap.svg"
    design = BirthFlowerDesign(
        text="Iris",
        month=4,
        font=1,
        flower=9,
        flower_asset_path=flower_path,
        flower_name="Imported",
    )

    render_svg(design, output_path)

    svg = output_path.read_text(encoding="utf-8")
    assert "不是纯矢量" in svg
    assert "data:image/png;base64," in svg
    assert "Imported" in svg


def test_render_dxf_rejects_bitmap_flower_with_clear_error(tmp_path):
    flower_path = tmp_path / "Imported.jpg"
    flower_path.write_bytes(b"jpeg")
    design = BirthFlowerDesign(
        text="Iris",
        month=4,
        font=1,
        flower=9,
        flower_asset_path=flower_path,
    )

    with pytest.raises(ValueError, match="位图素材无法导出 DXF"):
        render_dxf(design, tmp_path / "bitmap.dxf")


def test_render_dxf_creates_engraving_file_with_flower_paths_and_text(tmp_path):
    flower_path = tmp_path / "DaffodilMarch.svg"
    flower_path.write_text(
        '<svg width="3000px" height="3000px" xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L3000 0 L3000 3000 Z"/></svg>',
        encoding="utf-8",
    )
    output_path = tmp_path / "engraving.dxf"
    design = BirthFlowerDesign(
        text="Victoria",
        month=3,
        font=1,
        flower=1,
        flower_asset_path=flower_path,
        flower_name="Daffodil",
    )

    result_path = render_dxf(design, output_path)

    assert result_path == output_path
    dxf = output_path.read_text(encoding="utf-8")
    assert "SECTION" in dxf
    assert "ENTITIES" in dxf
    assert "POLYLINE" in dxf
    assert "VERTEX" in dxf
    assert "TEXT" in dxf
    assert "Victoria" in dxf


def test_render_dxf_records_text_entity_font_risk(tmp_path):
    output_path = tmp_path / "glyph.dxf"
    design = BirthFlowerDesign(text="Jazmi" + chr(0xE014), month=6, font=4, flower=1)

    render_dxf(design, output_path)

    dxf = output_path.read_text(encoding="utf-8")
    assert "DXF TEXT 依赖字体文件和 PUA 字符" in dxf


def test_render_dxf_centers_text_inside_layout_box(tmp_path):
    output_path = tmp_path / "engraving.dxf"
    design = BirthFlowerDesign(
        text="Amira",
        month=6,
        font=1,
        flower=1,
        layout=EngravingLayout(text_x=1000, text_y=900, text_width=400, text_height=120),
    )

    render_dxf(design, output_path)

    dxf = output_path.read_text(encoding="utf-8")
    assert "1200.0000" in dxf
    assert "320.0000" in dxf


def test_render_dxf_does_not_non_uniformly_stretch_text_width(tmp_path):
    output_path = tmp_path / "wide-text.dxf"
    design = BirthFlowerDesign(
        text="Hi",
        month=6,
        font=1,
        flower=1,
        layout=EngravingLayout(text_x=1000, text_y=900, text_width=500, text_height=120),
    )

    render_dxf(design, output_path)

    dxf = output_path.read_text(encoding="utf-8")
    assert "\n41\n" in dxf


def test_render_svg_scales_single_line_text_to_fill_layout_box(tmp_path):
    output_path = tmp_path / "wide-text.svg"
    design = BirthFlowerDesign(
        text="Hi",
        month=6,
        font=1,
        flower=1,
        layout=EngravingLayout(text_x=1000, text_y=900, text_width=500, text_height=120),
    )

    render_svg(design, output_path)

    svg = output_path.read_text(encoding="utf-8")
    assert 'transform="translate(1000 900) scale(' in svg
    assert 'id="text-art"' in svg


def test_render_svg_wraps_message_text_with_smaller_font(tmp_path):
    output_path = tmp_path / "message.svg"
    design = BirthFlowerDesign(
        text="I love you like no one else……Loves you!",
        month=8,
        font=2,
        flower=1,
        personalization_type="message",
    )

    render_svg(design, output_path)

    svg = output_path.read_text(encoding="utf-8")
    font_size = int(re.search(r'font-size="(\d+)"', svg).group(1))
    assert svg.count("<text") > 1
    assert font_size < EngravingLayout().text_size
    assert "……" in svg


def test_render_dxf_writes_message_as_multiple_text_entities(tmp_path):
    output_path = tmp_path / "message.dxf"
    design = BirthFlowerDesign(
        text="I love you like no one else……Loves you!",
        month=8,
        font=2,
        flower=1,
        personalization_type="message",
    )

    render_dxf(design, output_path)

    dxf = output_path.read_text(encoding="utf-8")
    assert dxf.count("\nTEXT\n") > 1
    assert "I love you like" in dxf


def test_flower_preview_polylines_use_canvas_coordinates(tmp_path):
    flower_path = tmp_path / "DaisyApril.svg"
    flower_path.write_text(
        '<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L10 10"/></svg>',
        encoding="utf-8",
    )
    layout = EngravingLayout(
        canvas_width=200,
        canvas_height=200,
        flower_x=20,
        flower_y=30,
        flower_width=100,
        flower_height=100,
        text_x=100,
        text_y=150,
        text_size=20,
    )

    polylines = flower_preview_polylines(flower_path, layout)

    assert polylines == [[(20.0, 30.0), (120.0, 130.0)]]


def test_flower_preview_polylines_center_and_fit_non_square_layout_box(tmp_path):
    flower_path = tmp_path / "TallFlower.svg"
    flower_path.write_text(
        '<svg viewBox="0 0 10 20" xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L10 20"/></svg>',
        encoding="utf-8",
    )
    layout = EngravingLayout(
        canvas_width=300,
        canvas_height=300,
        flower_x=30,
        flower_y=40,
        flower_width=120,
        flower_height=80,
    )

    polylines = flower_preview_polylines(flower_path, layout)

    assert polylines == [[(70.0, 40.0), (110.0, 120.0)]]


def test_flower_preview_polylines_use_visual_bbox_not_viewbox_padding(tmp_path):
    flower_path = tmp_path / "PaddedFlower.svg"
    flower_path.write_text(
        '<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">'
        '<path d="M10 20 L20 20 L20 30 L10 30 Z"/></svg>',
        encoding="utf-8",
    )
    layout = EngravingLayout(
        canvas_width=100,
        canvas_height=100,
        flower_x=0,
        flower_y=0,
        flower_width=100,
        flower_height=100,
    )

    polylines = flower_preview_polylines(flower_path, layout)

    assert polylines == [[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)]]


def test_flower_preview_polylines_include_group_transform_and_stroke_width(tmp_path):
    flower_path = tmp_path / "StrokedFlower.svg"
    flower_path.write_text(
        '<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">'
        '<g transform="translate(50 50)">'
        '<path d="M0 0 L10 0" stroke="#111" stroke-width="10" fill="none"/>'
        "</g></svg>",
        encoding="utf-8",
    )
    layout = EngravingLayout(
        canvas_width=100,
        canvas_height=100,
        flower_x=0,
        flower_y=0,
        flower_width=100,
        flower_height=100,
    )

    polylines = flower_preview_polylines(flower_path, layout)

    assert polylines == [[(25.0, 50.0), (75.0, 50.0)]]


def test_preview_cache_reuses_polylines_when_file_and_layout_are_unchanged(tmp_path):
    flower_path = tmp_path / "RoseJune.svg"
    flower_path.write_text(
        '<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L10 10"/></svg>',
        encoding="utf-8",
    )
    layout = EngravingLayout(flower_x=20, flower_y=30, flower_width=100, flower_height=100)
    cache = PreviewCache()

    first = cache.polylines(flower_path, layout)
    second = cache.polylines(flower_path, layout)

    assert second is first
    assert first == [[(20.0, 30.0), (120.0, 130.0)]]
