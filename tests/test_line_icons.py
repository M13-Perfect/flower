import pytest

import line_icons


def test_all_known_icons_present_as_svg():
    """门厅 + 产品栏要用的 14 个图标 SVG 都已落进 assets/icons（取自 Tabler/MIT）。"""
    missing = [name for name in line_icons.KNOWN_ICONS if not line_icons.icon_exists(name)]
    assert missing == []


def test_missing_icon_is_graceful():
    assert line_icons.icon_exists("definitely-not-an-icon") is False
    assert line_icons.rasterize_icon("definitely-not-an-icon", "#ffffff", 20) is None


def test_rasterize_recolors_and_sizes():
    if line_icons.cairosvg is None or line_icons.Image is None:
        pytest.skip("cairosvg/Pillow 不可用（无头环境），跳过栅格化测试")
    img = line_icons.rasterize_icon("flower", "#2fd4a8", 32)
    assert img is not None
    assert img.mode == "RGBA"
    assert img.size == (32, 32)
    # 染色生效：图里应有偏 teal（绿/蓝高、红低）的描边像素。用 tobytes 逐像素扫，避开 getdata 弃用。
    raw = img.tobytes()  # RGBA 连续字节
    teal = sum(
        1
        for i in range(0, len(raw), 4)
        if raw[i + 3] > 40 and raw[i + 1] > 120 and raw[i + 2] > 100 and raw[i] < 120
    )
    assert teal > 0
