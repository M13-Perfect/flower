from pathlib import Path

import pytest

from models import EngravingLayout
from text_layout import layout_personalization_text


def test_message_layout_wraps_and_fits_inside_safe_area():
    layout = layout_personalization_text(
        "I love you like no one else……Loves you!",
        EngravingLayout(),
        personalization_type="message",
    )

    assert layout.did_fit is True
    assert layout.line_count > 1
    assert layout.layout_confidence >= 0.9
    assert layout.text_bounds.left >= layout.safe_area_bounds.left
    assert layout.text_bounds.right <= layout.safe_area_bounds.right
    assert layout.text_bounds.top >= layout.safe_area_bounds.top
    assert layout.text_bounds.bottom <= layout.safe_area_bounds.bottom


def test_short_name_layout_keeps_signature_slot_and_preserves_emoji():
    layout = layout_personalization_text("Mom ❤️", EngravingLayout(), personalization_type="name")

    assert layout.did_fit is True
    assert layout.lines == ("Mom ❤️",)
    assert layout.line_count == 1
    assert layout.text_bounds.right <= layout.safe_area_bounds.right
    assert layout.layout_confidence >= 0.9


def test_name_layout_shrinks_when_signature_is_too_wide():
    layout = layout_personalization_text(
        "Alexandria Catherine Montgomery",
        EngravingLayout(),
        personalization_type="name",
    )

    assert layout.did_fit is True
    assert layout.line_count == 1
    assert layout.text_bounds.right <= layout.safe_area_bounds.right


def test_name_layout_shrinks_to_fit_explicit_text_box_size():
    engraving_layout = EngravingLayout(text_x=500, text_y=400, text_width=180, text_height=72)

    layout = layout_personalization_text("Victoria", engraving_layout, personalization_type="name")

    assert layout.did_fit is True
    assert layout.final_font_size < 90
    assert layout.text_bounds.width <= engraving_layout.text_width
    assert layout.text_bounds.height <= engraving_layout.text_height
    assert layout.text_bounds.left >= engraving_layout.text_x
    assert layout.text_bounds.right <= engraving_layout.text_x + engraving_layout.text_width
    assert layout.text_bounds.top >= engraving_layout.text_y
    assert layout.text_bounds.bottom <= engraving_layout.text_y + engraving_layout.text_height
    assert abs((layout.text_bounds.left + layout.text_bounds.right) / 2 - 590) < 1
    assert abs((layout.text_bounds.top + layout.text_bounds.bottom) / 2 - 436) < 1


def test_name_layout_fits_uniformly_without_stretching_explicit_text_box():
    engraving_layout = EngravingLayout(text_x=500, text_y=400, text_width=300, text_height=90)

    layout = layout_personalization_text("Hi", engraving_layout, personalization_type="name")

    assert layout.did_fit is True
    # 等比改造：不再非等比拉伸铺满，render_scale 恒为 1，墨迹按真实比例居中。
    assert layout.render_scale_x == pytest.approx(1.0)
    assert layout.render_scale_y == pytest.approx(1.0)
    assert layout.ink_bounds is not None
    # 墨迹在框内（不超框），且居中。
    assert layout.text_bounds.width <= engraving_layout.text_width + 1
    assert layout.text_bounds.height <= engraving_layout.text_height + 1
    center_x = engraving_layout.text_x + engraving_layout.text_width / 2
    center_y = engraving_layout.text_y + engraving_layout.text_height / 2
    assert abs((layout.text_bounds.left + layout.text_bounds.right) / 2 - center_x) < 1
    assert abs((layout.text_bounds.top + layout.text_bounds.bottom) / 2 - center_y) < 1


def test_name_layout_centers_real_ink_bbox_for_descenders_and_accents():
    font_path = Path("Birthmonth_font.ttf")
    if not font_path.is_file():
        pytest.skip("Optional business font asset is not present")
    engraving_layout = EngravingLayout(text_x=300, text_y=250, text_width=300, text_height=120)
    expected_center_x = engraving_layout.text_x + engraving_layout.text_width / 2
    expected_center_y = engraving_layout.text_y + engraving_layout.text_height / 2

    for text in ("Name", "gyjpq", "ÁÉÍ"):
        layout = layout_personalization_text(text, engraving_layout, personalization_type="name", font_path=font_path)

        assert layout.did_fit is True
        assert layout.text_bounds.width <= engraving_layout.text_width
        assert layout.text_bounds.height <= engraving_layout.text_height
        assert abs((layout.text_bounds.left + layout.text_bounds.right) / 2 - expected_center_x) < 1
        assert abs((layout.text_bounds.top + layout.text_bounds.bottom) / 2 - expected_center_y) < 1
        assert layout.ink_bounds is not None


def test_name_layout_handles_empty_and_space_only_text_without_crashing():
    font_path = Path("Birthmonth_font.ttf")
    engraving_layout = EngravingLayout(text_x=300, text_y=250, text_width=300, text_height=120)

    for text in ("", "   "):
        layout = layout_personalization_text(text, engraving_layout, personalization_type="name", font_path=font_path)

        assert layout.did_fit is True
        assert layout.final_font_size >= 1
        assert layout.text_bounds.width >= 0
        assert layout.text_bounds.height >= 0
        assert layout.ink_bounds is not None


def test_name_layout_supports_handwriting_font_ink_bounds():
    font_path = Path("BirthMonth flowers") / "Malovely Script.ttf"
    if not font_path.exists():
        font_path = Path("Birthmonth_font.ttf")
    engraving_layout = EngravingLayout(text_x=100, text_y=100, text_width=240, text_height=90)

    layout = layout_personalization_text("Name", engraving_layout, personalization_type="name", font_path=font_path)

    assert layout.did_fit is True
    assert layout.text_bounds.left >= engraving_layout.text_x
    assert layout.text_bounds.right <= engraving_layout.text_x + engraving_layout.text_width
    assert layout.text_bounds.top >= engraving_layout.text_y
    assert layout.text_bounds.bottom <= engraving_layout.text_y + engraving_layout.text_height


def test_message_layout_reports_warning_when_minimum_size_still_overflows():
    layout = layout_personalization_text(
        "supercalifragilisticexpialidocious" * 8,
        EngravingLayout(),
        personalization_type="message",
    )

    assert layout.did_fit is False
    assert layout.final_font_size == 36
    assert layout.layout_confidence < 0.9
    assert layout.warnings
