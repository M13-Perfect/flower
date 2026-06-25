"""VB-1 金标锁:引入 compile_layer_geometry 公开入口前后,固定 fixture 的 DXF 几何必须逐点一致
(行为保持)。基线缺失时自动生成(首跑生成→skip),再跑即逐实体比对。

锁的是真实导出链 render_document_dxf(内部走 export_dxf),覆盖 svg-path + text-glyph 两条编译分支。
"""
from __future__ import annotations

import json
from pathlib import Path

import ezdxf
import pytest

from app.domain.exports.dxf import _project_root
from desktop_export import render_document_dxf
from models import Document, add_image_layer, add_text_layer

FIX = Path(__file__).parent / "fixtures"
BASELINE = FIX / "dxf_golden_lock_baseline.json"

FLOWER_SVG = (
    '<svg viewBox="0 0 100 100"><path d="M10 10 C30 0 70 0 90 10 '
    'C100 30 100 70 90 90 C70 100 30 100 10 90 C0 70 0 30 10 10 Z"/></svg>'
)


def _build_document(tmp_path) -> Document:
    svg_file = tmp_path / "flower.svg"
    svg_file.write_text(FLOWER_SVG, encoding="utf-8")
    document = Document(canvas_width=1000, canvas_height=1000)
    add_image_layer(document, svg_file, x=100, y=100, width=600, height=600)
    font_path = _project_root() / "Birthmonth_font.ttf"
    add_text_layer(
        document, "Mia", font_path=font_path, x=200, y=760, width=600, height=200, font_size=180
    )
    return document


def _round_pt(p, nd=6):
    return [round(float(p[0]), nd), round(float(p[1]), nd)]


def _extract_geometry(dxf_path) -> dict:
    drawing = ezdxf.readfile(str(dxf_path))
    entities = []
    for e in drawing.modelspace():
        t = e.dxftype()
        rec = {"type": t, "layer": e.dxf.layer}
        if t == "SPLINE":
            rec["control_points"] = [_round_pt(p) for p in e.control_points]
            rec["closed"] = bool(e.closed)
        elif t == "LWPOLYLINE":
            rec["points"] = [_round_pt(p) for p in e.get_points("xy")]
            rec["closed"] = bool(e.closed)
        elif t == "POLYLINE":
            rec["points"] = [_round_pt((v.dxf.location.x, v.dxf.location.y)) for v in e.vertices]
        entities.append(rec)
    return {
        "dxfversion": drawing.dxfversion,
        "insunits": drawing.header.get("$INSUNITS"),
        "entity_count": len(entities),
        "entities": entities,
    }


def test_dxf_geometry_golden_lock(tmp_path):
    out = render_document_dxf(_build_document(tmp_path), tmp_path / "lock.dxf", physical_width_mm=80)
    geom = _extract_geometry(out)
    if not BASELINE.exists():
        FIX.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(geom, ensure_ascii=False, indent=2), encoding="utf-8")
        pytest.skip(f"baseline generated at {BASELINE}; re-run to lock")
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert geom["dxfversion"] == baseline["dxfversion"]
    assert geom["insunits"] == baseline["insunits"]
    assert geom["entity_count"] == baseline["entity_count"], "实体数变化=几何行为非保持"
    assert geom["entities"] == baseline["entities"], "DXF 几何相对基线逐点比对失败(行为非保持)"
