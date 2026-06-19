"""护栏：末尾爱心几何常量与变换。

最关键的一条：HEART_PATH_D 必须只含 M/L/Q/C/Z（绝不含圆弧 A/a 或简写 S/T），
否则 services/api 的 DXF/SVG 路径解析器会抛 SVG_UNSUPPORTED_PATH_COMMAND，
Font 4 名字导 DXF 直接崩。改 assets/symbols/heart.svg 后须重跑 tmp_out/gen_heart.py。
"""
import re

import heart_symbol as h


def test_heart_path_uses_only_supported_commands():
    cmds = set(re.findall(r"[A-Za-z]", h.HEART_PATH_D))
    # DXF 解析器（_parse_path_objects）支持的命令全集；尤其不能出现 A/a（圆弧）、S/T（平滑简写）。
    assert cmds <= set("MLQCZ"), f"出现不支持的 path 命令：{sorted(cmds - set('MLQCZ'))}"
    assert "A" not in cmds and "a" not in cmds


def _bbox(path_d: str):
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.recordingPen import RecordingPen
    from fontTools.svgLib.path import parse_path

    rec = RecordingPen()
    parse_path(path_d, rec)
    bounds = BoundsPen(None)
    rec.replay(bounds)
    return bounds.bounds  # (minx, miny, maxx, maxy)


def test_heart_is_zero_based_and_matches_view_box():
    minx, miny, maxx, maxy = _bbox(h.HEART_PATH_D)
    assert abs(minx) < 0.5 and abs(miny) < 0.5  # 左上角对齐到 (0,0)
    assert abs((maxx - minx) - h.HEART_VIEW_W) < 0.5
    assert abs((maxy - miny) - h.HEART_VIEW_H) < 0.5
    assert abs(h.HEART_ASPECT - h.HEART_VIEW_W / h.HEART_VIEW_H) < 1e-6


def test_transformed_path_scales_and_translates_bbox():
    d = h.heart_path_d_transformed(10.0, 5.0, 2.0)
    assert set(re.findall(r"[A-Za-z]", d)) <= set("MLQCZ")
    minx, miny, maxx, maxy = _bbox(d)
    assert abs(minx - 10.0) < 0.5 and abs(miny - 5.0) < 0.5
    assert abs((maxx - minx) - h.HEART_VIEW_W * 2.0) < 0.5
    assert abs((maxy - miny) - h.HEART_VIEW_H * 2.0) < 0.5


def test_markup_is_self_contained_svg():
    markup = h.heart_svg_markup("#123456")
    assert markup.startswith("<svg")
    assert "viewBox" in markup and "#123456" in markup
    assert h.HEART_PATH_D in markup
