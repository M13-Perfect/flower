from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

import ezdxf
import pytest
from ezdxf import bbox as ezbbox
from fastapi.testclient import TestClient
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from app.domain.exports.dxf import _ENGRAVE_LAYER, _text_with_glyph_overrides
from app.main import app


EXPORTED_AT = "2026-06-11T13:14:15.000Z"


def test_dxf_export_converts_simple_text_to_path_geometry(tmp_path, monkeypatch) -> None:
    install_project_root(tmp_path, monkeypatch)
    build_test_font(tmp_path / "assets" / "fonts" / "specimen.ttf")
    document = base_document(
        layers=[
            text_layer("text_1", "A", x=12, y=34, width=80, height=40, font_size=20),
        ]
    )

    response = TestClient(app).post(
        "/exports/dxf",
        json={"document": document, "exportedAt": EXPORTED_AT},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["fileName"] == "birth-flower-card_order-1_2026-06-11T13-14-15-000Z.dxf"
    assert payload["metadata"]["templateId"] == "birth-flower-card"
    assert payload["warnings"] == []

    doc = load_dxf(payload)
    assert doc.dxfversion == "AC1032"  # R2018
    assert doc.header["$INSUNITS"] == 0  # px 画布无物理单位
    types = entity_types(doc)
    assert "TEXT" not in types
    # 文字只输出闭合轮廓,DXF 内不填充:EzCad 不认 DXF HATCH,实心改由 EzCad 导入后原生「填充」完成。
    assert "HATCH" not in types
    assert "LINE" not in types  # flower 不在 DXF 里排扫描线填充
    # 字形是可编辑的闭合 POLYLINE/SPLINE 轮廓,正好可被 EzCad 选中填充。
    assert "POLYLINE" in types
    assert content_layers(doc) == {_ENGRAVE_LAYER}
    # Y 翻转(画布高 200):方块字形左上角落在 (12,180)。
    assert (12.0, 180.0) in all_points(doc)


def test_dxf_text_outline_mode_emits_editable_polyline(tmp_path, monkeypatch) -> None:
    install_project_root(tmp_path, monkeypatch)
    build_test_font(tmp_path / "assets" / "fonts" / "specimen.ttf")
    document = base_document(
        layers=[text_layer("text_1", "A", x=12, y=34, width=80, height=40, font_size=20)],
    )
    # 空心模式:字形改输出 SPLINE/POLYLINE 轮廓,而非 HATCH。
    document["exportSettings"]["text"] = {"fill": "outline"}

    response = TestClient(app).post(
        "/exports/dxf",
        json={"document": document, "exportedAt": EXPORTED_AT},
    )

    assert response.status_code == 200
    doc = load_dxf(response.json())
    types = entity_types(doc)
    assert "HATCH" not in types
    assert "LINE" not in types  # 空心模式不生成扫描线填充
    assert "POLYLINE" in types  # 方块字形是直线段 → POLYLINE 轮廓
    assert (12.0, 180.0) in all_points(doc)


def test_dxf_text_helper_ignores_control_character_glyph_override() -> None:
    layer = text_layer("text_1", "A")
    layer["glyphOverrides"] = [
        {
            "index": 0,
            "originalText": "A",
            "replacement": "\n",
            "codepoint": "U+000A",
            "glyphName": "linefeed.alt",
        }
    ]

    assert _text_with_glyph_overrides(layer) == "A"


def test_dxf_export_converts_simple_inline_svg_to_path_geometry(tmp_path, monkeypatch) -> None:
    install_project_root(tmp_path, monkeypatch)
    document = base_document(
        layers=[
            svg_layer(
                "svg_1",
                '<svg viewBox="0 0 10 10"><path d="M0 0 L10 0 L10 10 Z"/></svg>',
                x=5,
                y=7,
                width=20,
                height=20,
            ),
        ]
    )

    response = TestClient(app).post(
        "/exports/dxf",
        json={"document": document, "exportedAt": EXPORTED_AT},
    )

    assert response.status_code == 200
    doc = load_dxf(response.json())
    assert content_layers(doc) == {_ENGRAVE_LAYER}
    points = all_points(doc)
    # Y 翻转(画布高 200):y -> 200-y。
    assert (5.0, 193.0) in points
    assert (25.0, 193.0) in points
    assert (25.0, 173.0) in points


def test_dxf_export_normalizes_group_transforms_and_units(tmp_path, monkeypatch) -> None:
    install_project_root(tmp_path, monkeypatch)
    document = base_document(
        canvas_unit="mm",
        dxf_units="mm",
        layers=[
            {
                **layer_base("group_1", "group", x=10, y=20, width=100, height=100, scale_x=2),
                "children": [
                    {
                        **layer_base("path_1", "path", x=5, y=0, width=10, height=10),
                        "pathData": "M0 0 L10 0 L10 10 Z",
                        "fill": "none",
                        "stroke": "#111111",
                    }
                ],
            }
        ],
    )

    response = TestClient(app).post(
        "/exports/dxf",
        json={"document": document, "units": "mm", "exportedAt": EXPORTED_AT},
    )

    assert response.status_code == 200
    doc = load_dxf(response.json())
    assert doc.header["$INSUNITS"] == 4
    assert content_layers(doc) == {_ENGRAVE_LAYER}
    points = all_points(doc)
    # Y 翻转(画布高 200):y -> 200-y。
    assert (20.0, 180.0) in points
    assert (40.0, 180.0) in points


def test_dxf_export_scales_px_canvas_to_template_physical_width_mm(
    tmp_path,
    monkeypatch,
) -> None:
    install_project_root(tmp_path, monkeypatch)
    document = base_document(
        dxf_units="mm",
        physical_width_mm=80,
        layers=[
            {
                **layer_base("path_1", "path", width=300, height=20),
                "pathData": "M0 0 L300 0 L300 100 L0 100 Z",
                "fill": "none",
                "stroke": "#111111",
            }
        ],
    )

    response = TestClient(app).post(
        "/exports/dxf",
        json={"document": document, "exportedAt": EXPORTED_AT},
    )

    assert response.status_code == 200
    doc = load_dxf(response.json())
    assert doc.header["$INSUNITS"] == 4
    extents = ezbbox.extents(doc.modelspace())
    assert extents.size.x == pytest.approx(80, abs=0.01)


def test_dxf_export_returns_warnings_for_unsupported_svg_features(tmp_path, monkeypatch) -> None:
    install_project_root(tmp_path, monkeypatch)
    document = base_document(
        layers=[
            svg_layer(
                "svg_1",
                (
                    '<svg viewBox="0 0 10 10">'
                    "<defs><linearGradient id=\"g\"/></defs>"
                    '<path d="M0 0 L10 0 L10 10 Z" fill="url(#g)"/>'
                    "</svg>"
                ),
            ),
        ]
    )

    response = TestClient(app).post(
        "/exports/dxf",
        json={"document": document, "exportedAt": EXPORTED_AT},
    )

    assert response.status_code == 200
    payload = response.json()
    assert any(warning["code"] == "SVG_UNSUPPORTED_FEATURE" for warning in payload["warnings"])
    assert content_layers(load_dxf(payload)) == {_ENGRAVE_LAYER}


def test_dxf_export_rejects_unsupported_layers_without_file(tmp_path, monkeypatch) -> None:
    install_project_root(tmp_path, monkeypatch)
    document = base_document(
        layers=[
            {
                **layer_base("image_1", "image", width=100, height=80),
                "assetRef": {"assetId": "photo", "path": "assets/photo.png"},
                "intrinsicSize": {"width": 100, "height": 80},
                "fit": "contain",
            }
        ],
    )

    response = TestClient(app).post(
        "/exports/dxf",
        json={"document": document, "exportedAt": EXPORTED_AT},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "EXPORT_UNSUPPORTED_LAYER"
    assert "contentBase64" not in payload


def test_dxf_collects_all_geometry_on_single_engrave_layer(tmp_path, monkeypatch) -> None:
    install_project_root(tmp_path, monkeypatch)
    document = base_document(
        layers=[
            svg_layer(
                "layer_flower",
                '<svg viewBox="0 0 10 10"><path d="M0 0 L10 0 L10 10 Z"/></svg>',
                x=5,
                y=7,
                width=20,
                height=20,
            ),
            {
                **layer_base("layer_text", "path", x=1, y=2),
                "pathData": "M0 0 L5 0 L5 5 Z",
                "fill": "none",
                "stroke": "#111111",
            },
        ]
    )

    response = TestClient(app).post(
        "/exports/dxf",
        json={"document": document, "exportedAt": EXPORTED_AT},
    )

    assert response.status_code == 200
    doc = load_dxf(response.json())
    # 花与字必须落在同一内容层、同一颜色 7(同一道激光工序),对齐标准样件。
    assert content_layers(doc) == {_ENGRAVE_LAYER}
    assert doc.layers.get(_ENGRAVE_LAYER).dxf.color == 7


def test_dxf_cubic_path_becomes_spline_preserving_endpoints(tmp_path, monkeypatch) -> None:
    install_project_root(tmp_path, monkeypatch)
    # 一条三次贝塞尔:导出为 SPLINE(平滑可编辑曲线),而非扁平折线。
    document = base_document(
        canvas_unit="mm",
        dxf_units="mm",
        layers=[
            {
                **layer_base("curve_1", "path", x=0, y=0, width=10, height=10),
                "pathData": "M0 0 C1 0.05 2 0.05 3 0",
                "fill": "none",
                "stroke": "#111111",
            }
        ],
    )

    response = TestClient(app).post(
        "/exports/dxf",
        json={"document": document, "units": "mm", "exportedAt": EXPORTED_AT},
    )

    assert response.status_code == 200
    doc = load_dxf(response.json())
    splines = [e for e in doc.modelspace() if e.dxftype() == "SPLINE"]
    assert len(splines) == 1
    control = [(round(float(p[0]), 4), round(float(p[1]), 4)) for p in splines[0].control_points]
    # 单段三次贝塞尔 → 4 个控制点,且端点精确保留。
    # Y 翻转(画布高 200):端点 y=0 -> 200。
    assert len(control) == 4
    assert control[0] == (0.0, 200.0)
    assert control[-1] == (3.0, 200.0)


def install_project_root(path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLOWER_PROJECT_ROOT", str(path))
    (path / "assets" / "fonts").mkdir(parents=True, exist_ok=True)


def load_dxf(payload: dict[str, Any]) -> Any:
    text = base64.b64decode(payload["contentBase64"]).decode("utf-8")
    return ezdxf.read(io.StringIO(text))


def entity_types(doc: Any) -> list[str]:
    return [entity.dxftype() for entity in doc.modelspace()]


def content_layers(doc: Any) -> set[str]:
    return {entity.dxf.layer for entity in doc.modelspace()}


def _entity_points(entity: Any) -> list[tuple[float, float]]:
    kind = entity.dxftype()
    if kind == "SPLINE":
        raw = entity.control_points
    elif kind == "POLYLINE":
        raw = list(entity.points())
    elif kind == "LWPOLYLINE":
        raw = list(entity.get_points("xy"))
    elif kind == "LINE":
        raw = [entity.dxf.start, entity.dxf.end]
    else:
        raw = []
    return [(round(float(point[0]), 4), round(float(point[1]), 4)) for point in raw]


def all_points(doc: Any) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for entity in doc.modelspace():
        points.extend(_entity_points(entity))
    return points


def base_document(
    *,
    layers: list[dict[str, Any]],
    canvas_unit: str = "px",
    dxf_units: str = "px",
    physical_width_mm: float | None = None,
) -> dict[str, Any]:
    export_settings: dict[str, Any] = {
        "schemaVersion": "1.0",
        "defaultFormats": ["dxf"],
        "svg": {"preserveText": True, "preserveVector": True, "includeMetadata": True},
        "png": {"scale": 1, "background": "transparent"},
        "dxf": {"textMode": "paths", "units": dxf_units},
    }
    if physical_width_mm is not None:
        export_settings["physical"] = {"widthMm": physical_width_mm}
    return {
        "schemaVersion": "1.0",
        "documentId": "doc-1",
        "projectId": "project-1",
        "jobId": "job-1",
        "metadata": {
            "orderId": "order-1",
            "templateId": "birth-flower-card",
            "templateVersion": "1.0.0",
            "appVersion": "0.1.0",
            "createdAt": "2026-06-11T00:00:00.000Z",
            "updatedAt": "2026-06-11T00:00:00.000Z",
        },
        "canvas": {
            "width": 300,
            "height": 200,
            "unit": canvas_unit,
            "background": {"type": "transparent"},
        },
        "exportSettings": export_settings,
        "layers": layers,
    }


def text_layer(
    layer_id: str,
    text: str,
    *,
    x: float = 0,
    y: float = 0,
    width: float = 100,
    height: float = 50,
    font_size: float = 20,
) -> dict[str, Any]:
    return {
        **layer_base(layer_id, "text", x=x, y=y, width=width, height=height),
        "text": text,
        "fontRef": {"family": "Specimen", "source": "asset", "assetId": "specimen"},
        "style": {
            "fontSize": font_size,
            "fill": "#111111",
            "align": "left",
            "lineHeight": 1,
            "letterSpacing": 0,
        },
        "layout": {"mode": "box", "overflow": "clip"},
    }


def svg_layer(
    layer_id: str,
    inline_svg: str,
    *,
    x: float = 0,
    y: float = 0,
    width: float = 10,
    height: float = 10,
) -> dict[str, Any]:
    return {
        **layer_base(layer_id, "svg", x=x, y=y, width=width, height=height),
        "inlineSvg": inline_svg,
        "viewBox": {"x": 0, "y": 0, "width": 10, "height": 10},
        "preserveVector": True,
    }


def layer_base(
    layer_id: str,
    layer_type: str,
    *,
    x: float = 0,
    y: float = 0,
    width: float = 10,
    height: float = 10,
    scale_x: float = 1,
    scale_y: float = 1,
    rotation: float = 0,
) -> dict[str, Any]:
    return {
        "id": layer_id,
        "type": layer_type,
        "name": layer_id,
        "visible": True,
        "locked": False,
        "exportable": True,
        "zIndex": 1,
        "opacity": 1,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "scaleX": scale_x,
        "scaleY": scale_y,
        "rotation": rotation,
        "tags": [],
    }


def build_test_font(path: Path) -> None:
    glyph_order = [".notdef", "A"]
    glyphs = {name: draw_box_glyph() for name in glyph_order}
    advance_widths = {".notdef": (500, 0), "A": (700, 0)}
    path.parent.mkdir(parents=True, exist_ok=True)

    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap({0x0041: "A"})
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(advance_widths)
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupOS2(
        sTypoAscender=780,
        sTypoDescender=-220,
        usWinAscent=820,
        usWinDescent=220,
    )
    builder.setupNameTable(
        {
            "familyName": "Specimen",
            "styleName": "Regular",
            "uniqueFontIdentifier": "Specimen Regular",
            "fullName": "Specimen Regular",
            "psName": "Specimen-Regular",
        }
    )
    builder.setupPost()
    builder.save(path)


def draw_box_glyph() -> Any:
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((500, 0))
    pen.lineTo((500, 700))
    pen.lineTo((0, 700))
    pen.closePath()
    return pen.glyph()
