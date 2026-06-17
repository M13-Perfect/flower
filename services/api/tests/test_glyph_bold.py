"""Stage 5 护栏：加粗轮廓外扩核心 offset_glyph_polygons（pyclipper）。
单独验证几何正确性：实心外扩、零/负不动、带孔时外圈扩内孔缩（镂空保持）。"""
from __future__ import annotations

from app.domain.exports.dxf import offset_glyph_polygons


def _bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def test_offset_grows_filled_square():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    out = offset_glyph_polygons([square], 1.0)
    assert len(out) == 1
    x0, y0, x1, y1 = _bbox(out[0])
    assert x0 < -0.5 and y0 < -0.5 and x1 > 10.5 and y1 > 10.5  # 四周外扩 ~1


def test_offset_zero_is_noop():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert offset_glyph_polygons([square], 0.0) == [square]
    assert offset_glyph_polygons([square], -2.0) == [square]


def test_offset_square_with_hole_outer_grows_hole_shrinks():
    outer = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)]  # CCW
    hole = [(5.0, 5.0), (5.0, 15.0), (15.0, 15.0), (15.0, 5.0)]  # CW → nonzero 下成孔
    out = offset_glyph_polygons([outer, hole], 1.0)
    assert len(out) == 2  # 仍是「外圈 + 内孔」两环
    by_width = sorted(out, key=lambda p: _bbox(p)[2] - _bbox(p)[0])
    inner, outer_out = by_width[0], by_width[1]
    ox0, _oy0, ox1, _oy1 = _bbox(outer_out)
    ix0, _iy0, ix1, _iy1 = _bbox(inner)
    assert ox0 < -0.5 and ox1 > 20.5  # 外圈外扩
    assert ix0 > 5.5 and ix1 < 14.5  # 内孔内缩（镂空变小 = 笔画变粗）
