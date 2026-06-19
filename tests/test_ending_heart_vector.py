"""护栏：Font 4 末尾独立实心爱心进 SVG/DXF 矢量端。

链路：desktop_export._text_layer 把爱心烘成 textLayout.endingHeart.pathData（box 本地闭合 path），
svg.py 追加一条实心 <path>、dxf.py 经 _parse_path_objects 出闭合 SPLINE/POLYLINE（EzCad 自填）。
爱心几何由 layer.ending_heart 驱动、与字体无关，故此处用任意业务字体即可。
"""
import re
from pathlib import Path

import pytest

FONT = Path("BirthMonth flowers/AdoraBella.ttf")


def _require():
    pytest.importorskip("PIL")
    ezdxf = pytest.importorskip("ezdxf")
    if not FONT.is_file():
        pytest.skip("business font asset not present")
    return ezdxf


def _doc(ending_heart: bool):
    from models import Document, add_text_layer

    doc = Document(canvas_width=1732, canvas_height=1280)
    layer = add_text_layer(doc, "Ammy", font_size=190, x=780, y=830, width=804, height=260)
    layer.font_path = FONT
    layer.ending_heart = ending_heart
    return doc


def _text_layout(doc):
    from desktop_export import _document_to_layer_document

    layer = next(item for item in _document_to_layer_document(doc)["layers"] if item["type"] == "text")
    return layer["textLayout"]


def test_endingheart_only_baked_when_flagged_and_uses_supported_commands():
    _require()
    heart = _text_layout(_doc(True)).get("endingHeart")
    assert heart and heart.get("pathData")
    cmds = set(re.findall(r"[A-Za-z]", heart["pathData"]))
    assert cmds <= set("MLQCZ"), f"DXF 不支持的命令：{sorted(cmds - set('MLQCZ'))}"
    # 闭合（以 Z 收尾）：_parse_path_objects 据此 close()，EzCad 才能把净轮廓填实心。
    assert heart["pathData"].rstrip().endswith("Z")
    # 不带爱心：schema 完全无该 key（其它文字零变化，金标安全）。
    assert "endingHeart" not in _text_layout(_doc(False))


def test_svg_export_adds_exactly_one_solid_heart_path(tmp_path):
    _require()
    from desktop_export import render_document_vector_svg

    def svg_paths(doc, name):
        out = render_document_vector_svg(doc, tmp_path / name)
        text = out if isinstance(out, str) else (tmp_path / name).read_text(encoding="utf-8")
        return text.count("<path")

    n_no = svg_paths(_doc(False), "no.svg")
    n_yes = svg_paths(_doc(True), "yes.svg")
    assert n_yes == n_no + 1  # 恰好多一条爱心 path


def test_dxf_export_heart_is_closed_spline_no_text_no_hatch(tmp_path):
    ezdxf = _require()
    from desktop_export import render_document_dxf

    def types(doc, name):
        path = render_document_dxf(doc, tmp_path / name)
        d = ezdxf.readfile(str(path))
        counts: dict[str, int] = {}
        for e in d.modelspace():
            counts[e.dxftype()] = counts.get(e.dxftype(), 0) + 1
        return counts

    c_no = types(_doc(False), "no.dxf")
    c_yes = types(_doc(True), "yes.dxf")
    # 不出现 TEXT/MTEXT（文字与爱心都已转矢量轮廓）、不出现 HATCH。
    for counts in (c_no, c_yes):
        assert "TEXT" not in counts and "MTEXT" not in counts
        assert "HATCH" not in counts
    # 爱心是一条闭合曲线轮廓：带爱心比不带多出 SPLINE/POLYLINE（闭合性在 schema 测里以 Z 收尾保证）。
    total_yes = c_yes.get("SPLINE", 0) + c_yes.get("POLYLINE", 0)
    total_no = c_no.get("SPLINE", 0) + c_no.get("POLYLINE", 0)
    assert total_yes > total_no
