"""Stage 5 护栏：矢量端（DXF/SVG）加粗(轮廓外扩)+下划线 端到端。
加粗/下划线默认关 → 现有金标零变化（已由既有金标测试覆盖）；这里只测开启时的产出正确。"""
from __future__ import annotations

from pathlib import Path

import pytest

FONT = Path("BirthMonth flowers/Malovely Script.ttf")


def _doc(text: str = "Lily Grace", **style):
    from models import Document, add_text_layer

    document = Document(1200, 360)
    layer = add_text_layer(document, text=text, x=60, y=70, width=1080, height=210, font_size=150)
    layer.font_path = FONT.resolve()
    layer.bold = style.get("bold")
    layer.underline = style.get("underline")
    return document


def _need_font():
    if not FONT.is_file():
        pytest.skip("测试字体缺失")


def test_dxf_entities_ezcad_safe_and_bold_uses_polyline(tmp_path):
    _need_font()
    import ezdxf

    from desktop_export import render_document_dxf

    allowed = {"SPLINE", "POLYLINE", "LWPOLYLINE", "LINE"}

    def entity_types(document) -> list[str]:
        path = tmp_path / "x.dxf"
        render_document_dxf(document, path, text_fill="outline")
        return [e.dxftype() for e in ezdxf.readfile(str(path)).modelspace()]

    plain = entity_types(_doc())
    bold = entity_types(_doc(bold=True, underline=True))
    # EzCad 友好：只允许 SPLINE/POLYLINE/LWPOLYLINE/LINE，绝无 TEXT/MTEXT/HATCH。
    assert set(plain) <= allowed and set(bold) <= allowed
    for bad in ("TEXT", "MTEXT", "HATCH"):
        assert bad not in plain and bad not in bold
    assert "SPLINE" in plain  # 非加粗字形=平滑曲线 SPLINE
    assert "POLYLINE" in bold  # 加粗=多边形外扩 → POLYLINE


def test_svg_underline_and_bold_change_output(tmp_path):
    _need_font()
    from desktop_export import render_document_vector_svg

    def svg(document) -> str:
        path = tmp_path / "x.svg"
        render_document_vector_svg(document, path)
        return path.read_text(encoding="utf-8")

    plain = svg(_doc())
    underlined = svg(_doc(underline=True))
    bold = svg(_doc(bold=True))
    assert underlined.count("<path") > plain.count("<path")  # 下划线多一条 path
    assert bold != plain  # 加粗改变字形轮廓 d
