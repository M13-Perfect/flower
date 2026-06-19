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


# ---- 末尾独立爱心（Font 4）布局护栏 ----

FONT4 = Path("BirthMonth flowers/AdoraBella.ttf")


def _require_font():
    pytest.importorskip("PIL")
    if not FONT4.is_file():
        pytest.skip("business font asset not present")


def test_ending_advance_ratio_zero_is_byte_identical():
    # ratio=0（默认）必须与不传完全一致：保证非 Font 4 文字零回归。
    _require_font()
    from text_layout import fit_text_box

    a = fit_text_box("Ammy", 804, 260, FONT4, personalization_type="name")
    b = fit_text_box("Ammy", 804, 260, FONT4, personalization_type="name", ending_advance_ratio=0.0)
    assert a == b


def test_place_ending_heart_sits_right_of_last_ink_and_scales_with_font():
    _require_font()
    from text_layout import (
        ENDING_HEART_ADVANCE_RATIO,
        HEART_VIEW_H,
        fit_text_box,
        measure_text_ink_bbox,
        place_ending_heart,
    )
    from text_layout import ENDING_HEART_SIZE_RATIO

    fit = fit_text_box(
        "Ammy", 804, 260, FONT4, personalization_type="name",
        ending_advance_ratio=ENDING_HEART_ADVANCE_RATIO,
    )
    placement = place_ending_heart(fit, FONT4)
    assert placement is not None
    x, y, scale = placement
    # x 在末行墨迹右缘之右（gap>0）。
    pen_x, _baseline = fit.origins[-1]
    ink = measure_text_ink_bbox(fit.lines[-1], fit.font_size, FONT4)
    assert x > pen_x + ink.right
    # scale = 爱心目标高 / 视图高；爱心高随字号等比。
    assert abs(scale - (ENDING_HEART_SIZE_RATIO * fit.font_size) / HEART_VIEW_H) < 1e-6


def test_ending_advance_reserves_width_so_name_plus_heart_fits():
    # 窄框 + 长名：带爱心预留时字号应 <= 不带；且名字+爱心右缘不超框（contain-fit）。
    _require_font()
    from text_layout import (
        ENDING_HEART_ADVANCE_RATIO,
        ENDING_HEART_SIZE_RATIO,
        HEART_ASPECT,
        fit_text_box,
        place_ending_heart,
    )

    name, w, h = "Gwendolyn", 360, 260
    plain = fit_text_box(name, w, h, FONT4, personalization_type="name")
    withh = fit_text_box(name, w, h, FONT4, personalization_type="name", ending_advance_ratio=ENDING_HEART_ADVANCE_RATIO)
    assert withh.font_size <= plain.font_size

    placement = place_ending_heart(withh, FONT4)
    assert placement is not None
    x, _y, _scale = placement
    heart_w = ENDING_HEART_SIZE_RATIO * withh.font_size * HEART_ASPECT
    # 爱心右缘不超出文本框宽（允许 1px 容差）。
    assert x + heart_w <= w + 1.0


# ---- 字号驱动文本框（字号=真实大小、框随字号长大）护栏 ----


def test_text_box_size_for_font_renders_exact_target_size():
    # 核心契约：按字号反推框，再 fit(box, cap=字号) 渲染出的真实字号==目标字号。
    _require_font()
    from text_layout import fit_text_box, text_box_size_for_font

    for fs in (60, 120, 240, 360):
        w, h, clamped = text_box_size_for_font("Patty", fs, FONT4, max_width=10_000_000, max_height=10_000_000)
        assert not clamped
        fit = fit_text_box("Patty", w, h, FONT4, personalization_type="name", font_size_cap=fs)
        assert fit.font_size == fs


def test_text_box_size_for_font_grows_with_font():
    # 框宽高都随字号单调长大。
    _require_font()
    from text_layout import text_box_size_for_font

    small = text_box_size_for_font("Patty", 80, FONT4, max_width=10_000_000, max_height=10_000_000)
    big = text_box_size_for_font("Patty", 200, FONT4, max_width=10_000_000, max_height=10_000_000)
    assert big[0] > small[0] and big[1] > small[1]


def test_text_box_size_for_font_wraps_when_single_line_too_wide():
    # 单行太宽 → 自动断行：框变窄（不超可用宽），渲染成 >=2 行。
    _require_font()
    from text_layout import fit_text_box, text_box_size_for_font

    name, fs = "Gwendolyn Alexandra", 120
    single_w, _h, _c = text_box_size_for_font(name, fs, FONT4, max_width=10_000_000, max_height=10_000_000)
    w, h, _clamped = text_box_size_for_font(name, fs, FONT4, max_width=single_w * 0.6, max_height=10_000_000)
    assert w < single_w
    fit = fit_text_box(name, w, h, FONT4, personalization_type="name", font_size_cap=fs)
    assert len(fit.lines) >= 2


def test_text_box_size_for_font_clamps_to_canvas_and_flags():
    # 字号超大、画布很小 → 封顶到上限并置 clamped=True。
    _require_font()
    from text_layout import text_box_size_for_font

    w, h, clamped = text_box_size_for_font("Patty", 5000, FONT4, max_width=1492, max_height=1140)
    assert clamped
    assert w <= 1492 and h <= 1140


def test_text_box_size_for_font_widens_with_longer_text_at_fixed_font():
    # 「框随墨迹实时变动」核心契约：同一字号下，名字越长（墨迹越宽）→ 反推的框越宽。
    _require_font()
    from text_layout import text_box_size_for_font

    fs = 120
    short_w, _sh, _sc = text_box_size_for_font("Al", fs, FONT4, max_width=10_000_000, max_height=10_000_000)
    long_w, _lh, _lc = text_box_size_for_font("Alexandria", fs, FONT4, max_width=10_000_000, max_height=10_000_000)
    assert long_w > short_w
