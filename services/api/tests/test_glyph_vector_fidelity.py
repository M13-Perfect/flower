"""矢量字形保真度护栏：草书等平滑字形在 SVG/DXF 导出里不被压成实心块。

两个根因 + 修复：
1. `_quadratic_segments` 旧实现把多控制点 qCurveTo 塌缩成单段 → 平滑字形扭曲；改为按
   TrueType 隐含中点正确展开成多段。
2. SVG 文本导出旧实现逐 contour 各成一个 <path> → 内层 counter 各自填实；改为一个字形
   的全部 contour 合进同一个 <path>（子路径），nonzero 缠绕让 counter 成镂空孔。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.domain.exports.dxf import _quadratic_segments

FONT = Path(__file__).resolve().parents[3] / "BirthMonth flowers" / "AdoraBella.ttf"


def test_quadratic_segments_expands_multipoint_qcurve():
    # 3 个离曲线控制点 + 末端点 → 3 段 quad（不再塌缩成 1 段），相邻控制点间隐含锚点=中点。
    current = (0.0, 0.0)
    args = ((10.0, 10.0), (20.0, 10.0), (30.0, 0.0), (40.0, 0.0))
    segments = _quadratic_segments(current, args)
    assert len(segments) == 3
    assert all(seg[0] == "quad" for seg in segments)
    assert segments[0][2] == (15.0, 10.0)  # mid(off0, off1)
    assert segments[1][2] == (25.0, 5.0)  # mid(off1, off2)
    assert segments[2][2] == (40.0, 0.0)  # 末段落到真实端点


def test_quadratic_segments_single_control_unchanged():
    # 单控制点 + 末端点 → 1 段（普通二次贝塞尔），不退化。
    segments = _quadratic_segments((0.0, 0.0), ((10.0, 10.0), (20.0, 0.0)))
    assert segments == [("quad", (10.0, 10.0), (20.0, 0.0))]


@pytest.mark.skipif(not FONT.is_file(), reason="business font asset not present")
def test_svg_glyph_combines_contours_into_single_path():
    # 草书大写 A（AdoraBella 有 3 个 contour）→ 导出**一个** <path>，内含多个子路径(M)，
    # 这样内层环成镂空孔而非各自填实（旧实现是逐 contour 各一个 path → 实心块）。
    pytest.importorskip("fontTools")
    from app.domain.exports.svg import _render_text_layer

    layer = {
        "id": "t",
        "type": "text",
        "text": "A",
        "fontRef": {"path": str(FONT)},
        "style": {"fontSize": 400, "fill": "#111111"},
        "x": 100,
        "y": 100,
        "width": 400,
        "height": 400,
    }
    out = _render_text_layer(layer)
    path_count = out.count("<path")
    subpath_count = len(re.findall(r"[Mm]\s*-?\d", out))
    assert path_count == 1  # 整个字形一个 path
    assert subpath_count >= 2  # 多个子路径（外形 + 内环）→ nonzero 成孔
