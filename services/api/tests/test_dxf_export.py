from __future__ import annotations

import base64
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from app.domain.exports.dxf import _text_with_glyph_overrides
from app.main import app


EXPORTED_AT = "2026-06-11T13:14:15.000Z"


def test_dxf_export_converts_simple_text_to_path_geometry(tmp_path, monkeypatch) -> None:
    install_fake_ezdxf(monkeypatch)
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
    dxf_text = decode_dxf(payload)
    assert payload["fileName"] == "birth-flower-card_order-1_2026-06-11T13-14-15-000Z.dxf"
    assert payload["metadata"]["templateId"] == "birth-flower-card"
    assert payload["warnings"] == []
    assert "INSUNITS=0" in dxf_text
    assert "LAYER=text_1" in dxf_text
    assert "POINT 12.0000,20.0000" in dxf_text
    assert "TEXT" not in dxf_text


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
    install_fake_ezdxf(monkeypatch)
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
    dxf_text = decode_dxf(response.json())
    assert "LAYER=svg_1" in dxf_text
    assert "POINT 5.0000,7.0000" in dxf_text
    assert "POINT 25.0000,7.0000" in dxf_text
    assert "POINT 25.0000,27.0000" in dxf_text


def test_dxf_export_normalizes_group_transforms_and_units(tmp_path, monkeypatch) -> None:
    install_fake_ezdxf(monkeypatch)
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
    dxf_text = decode_dxf(response.json())
    assert "INSUNITS=4" in dxf_text
    assert "LAYER=path_1" in dxf_text
    assert "POINT 20.0000,20.0000" in dxf_text
    assert "POINT 40.0000,20.0000" in dxf_text


def test_dxf_export_scales_px_canvas_to_template_physical_width_mm(
    tmp_path,
    monkeypatch,
) -> None:
    install_fake_ezdxf(monkeypatch)
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
    dxf_text = decode_dxf(response.json())
    points = dxf_points(dxf_text)
    xs = [point[0] for point in points]
    assert "INSUNITS=4" in dxf_text
    assert max(xs) - min(xs) == pytest.approx(80, abs=0.01)


def test_dxf_export_returns_warnings_for_unsupported_svg_features(tmp_path, monkeypatch) -> None:
    install_fake_ezdxf(monkeypatch)
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
    assert "LAYER=svg_1" in decode_dxf(payload)


def test_dxf_export_rejects_unsupported_layers_without_file(tmp_path, monkeypatch) -> None:
    install_fake_ezdxf(monkeypatch)
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


def install_project_root(path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLOWER_PROJECT_ROOT", str(path))
    (path / "assets" / "fonts").mkdir(parents=True, exist_ok=True)


def install_fake_ezdxf(monkeypatch) -> None:
    fake = ModuleType("ezdxf")
    fake.new = lambda dxfversion="R2010": FakeDxfDocument(dxfversion)
    monkeypatch.setitem(sys.modules, "ezdxf", fake)


class FakeDxfDocument:
    def __init__(self, dxfversion: str) -> None:
        self.dxfversion = dxfversion
        self.header: dict[str, Any] = {}
        self.units: int | None = None
        self._modelspace = FakeModelspace()

    def modelspace(self) -> "FakeModelspace":
        return self._modelspace

    def write(self, stream) -> None:
        stream.write(f"VERSION={self.dxfversion}\n")
        stream.write(f"INSUNITS={self.header.get('$INSUNITS')}\n")
        for item in self._modelspace.polylines:
            stream.write(f"LAYER={item['layer']}\n")
            stream.write(f"CLOSED={item['closed']}\n")
            for x, y in item["points"]:
                stream.write(f"POINT {x:.4f},{y:.4f}\n")


class FakeModelspace:
    def __init__(self) -> None:
        self.polylines: list[dict[str, Any]] = []

    def add_lwpolyline(self, points, close=False, dxfattribs=None) -> None:
        self.polylines.append(
            {
                "points": [(float(x), float(y)) for x, y in points],
                "closed": bool(close),
                "layer": (dxfattribs or {}).get("layer", "0"),
            }
        )


def decode_dxf(payload: dict[str, Any]) -> str:
    return base64.b64decode(payload["contentBase64"]).decode("utf-8")


def dxf_points(dxf_text: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for line in dxf_text.splitlines():
        if not line.startswith("POINT "):
            continue
        x_text, y_text = line.removeprefix("POINT ").split(",", maxsplit=1)
        points.append((float(x_text), float(y_text)))
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
