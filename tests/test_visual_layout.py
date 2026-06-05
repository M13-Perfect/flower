import pytest

from visual_layout import Rect, fit_content_bbox_to_target_rect


def test_fit_content_bbox_to_target_rect_contain_subtracts_content_origin():
    fit = fit_content_bbox_to_target_rect(
        Rect(10, 20, 30, 10),
        Rect(100, 200, 300, 300),
        mode="contain",
    )

    assert fit.scale_x == pytest.approx(10)
    assert fit.scale_y == pytest.approx(10)
    assert fit.draw_x == pytest.approx(0)
    assert fit.draw_y == pytest.approx(100)


def test_fit_content_bbox_to_target_rect_cover_and_stretch_modes():
    cover = fit_content_bbox_to_target_rect(Rect(0, 0, 50, 100), Rect(0, 0, 200, 200), mode="cover")
    stretch = fit_content_bbox_to_target_rect(Rect(5, 10, 50, 100), Rect(0, 0, 200, 200), mode="stretch")

    assert cover.scale_x == pytest.approx(4)
    assert cover.scale_y == pytest.approx(4)
    assert cover.draw_y == pytest.approx(-100)
    assert stretch.scale_x == pytest.approx(4)
    assert stretch.scale_y == pytest.approx(2)
    assert stretch.draw_x == pytest.approx(-20)
    assert stretch.draw_y == pytest.approx(-20)


def test_fit_content_bbox_to_target_rect_rejects_invalid_sizes():
    with pytest.raises(ValueError):
        fit_content_bbox_to_target_rect(Rect(0, 0, 0, 10), Rect(0, 0, 100, 100))

    with pytest.raises(ValueError):
        fit_content_bbox_to_target_rect(Rect(0, 0, 10, 10), Rect(0, 0, -1, 100))
