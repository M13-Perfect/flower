"""Stage 3 护栏：全局默认字体样式（加粗/下划线/斜体/加粗强度）的配置 round-trip
与「全局默认 + 每图层覆盖」解析逻辑。样式默认全 False/归零 → 对现有导出零行为变化。"""
from __future__ import annotations

import json

from config_store import AppConfig, load_config, save_config
from models import EngravingLayout, TextLayer, resolve_text_style


def test_layout_defaults_font_style_round_trips(tmp_path):
    layout = EngravingLayout(bold=True, underline=True, italic=False, bold_strength=0.05, letter_spacing=3.0)
    path = tmp_path / "cfg.json"
    save_config(AppConfig(layout_defaults=layout), path)
    loaded = load_config(path)
    assert loaded.layout_defaults.bold is True
    assert loaded.layout_defaults.underline is True
    assert loaded.layout_defaults.italic is False
    assert loaded.layout_defaults.bold_strength == 0.05
    assert loaded.layout_defaults.letter_spacing == 3.0


def test_old_config_without_font_style_falls_back_to_defaults(tmp_path):
    # 旧配置没有样式字段 → 用项目默认（全 False，强度 0.016），用户零感知。
    path = tmp_path / "cfg.json"
    path.write_text(
        json.dumps({"layout_defaults": {"canvas_width": 1732, "canvas_height": 1280}}),
        encoding="utf-8",
    )
    loaded = load_config(path)
    assert loaded.layout_defaults.bold is False
    assert loaded.layout_defaults.underline is False
    assert loaded.layout_defaults.italic is False
    assert loaded.layout_defaults.bold_strength == 0.016
    assert loaded.layout_defaults.letter_spacing == 0.0


def test_resolve_inherits_global_when_layer_unset():
    layout = EngravingLayout(bold=True, underline=False, italic=True, bold_strength=0.04)
    style = resolve_text_style(TextLayer(text="Emma"), layout)  # 所有 override = None
    assert (style.bold, style.underline, style.italic) == (True, False, True)
    assert style.bold_strength == 0.04  # bold=True → 保留强度


def test_resolve_layer_override_wins():
    layout = EngravingLayout(bold=True, bold_strength=0.04)
    style = resolve_text_style(TextLayer(text="Emma", bold=False), layout)  # 显式关
    assert style.bold is False
    assert style.bold_strength == 0.0  # bold=False → 强度归零


def test_resolve_strength_zeroed_when_not_bold():
    layout = EngravingLayout(bold=False, bold_strength=0.06)
    style = resolve_text_style(TextLayer(text="Emma"), layout)
    assert style.bold is False
    assert style.bold_strength == 0.0


def test_resolve_layer_strength_override():
    layout = EngravingLayout(bold=False, bold_strength=0.03)
    style = resolve_text_style(TextLayer(text="Emma", bold=True, bold_strength=0.08), layout)
    assert style.bold is True
    assert style.bold_strength == 0.08


# ---- Stage 4：预览端 TextRenderer 加粗/下划线（需 Pillow + 真字体；缺则跳过）----

def _ink_pixels(layer) -> int:
    from text_renderer import TextRenderer
    image = TextRenderer().render_layer(layer).image
    return sum(image.getchannel("A").histogram()[1:])  # alpha>0 的像素数


def test_preview_bold_and_underline_add_ink():
    from pathlib import Path

    import pytest

    font = Path("BirthMonth flowers/Malovely Script.ttf")
    if not font.is_file():
        pytest.skip("测试字体缺失")
    try:
        import PIL  # noqa: F401
    except ImportError:
        pytest.skip("未装 Pillow")

    common = dict(text="Emma", font_path=font, font_size=120, text_box_width=700, text_box_height=320)
    plain = _ink_pixels(TextLayer(**common))
    bold = _ink_pixels(TextLayer(**common, bold=True, bold_strength=0.06))
    underlined = _ink_pixels(TextLayer(**common, underline=True))
    assert plain > 0
    assert bold > plain  # 加粗 stroke → 墨迹更多
    assert underlined > plain  # 下划线 → 墨迹更多


def test_preview_plain_unchanged_when_no_style():
    # 不开样式时，新增 stroke=0/underline=False 路径应与"无样式字段"图层渲染一致（零回归）。
    from pathlib import Path

    import pytest

    font = Path("BirthMonth flowers/Malovely Script.ttf")
    if not font.is_file():
        pytest.skip("测试字体缺失")
    common = dict(text="Grace", font_path=font, font_size=120, text_box_width=700, text_box_height=320)
    assert _ink_pixels(TextLayer(**common)) == _ink_pixels(TextLayer(**common, bold=False, underline=False))
