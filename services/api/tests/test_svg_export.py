from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from app.domain import DomainError
from app.domain.exports.svg import export_svg


EXPORTED_AT = "2026-06-12T10:11:12.000Z"


def test_svg_export_outputs_cad_safe_parseable_svg(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLOWER_PROJECT_ROOT", str(tmp_path))
    build_test_font(tmp_path / "assets" / "fonts" / "lovely-script.ttf")
    document = base_document(
        layers=[
            {
                **layer_base("selection_1", "path", z_index=99, name="selection-box"),
                "pathData": "M0 0 L10 0",
                "fill": "none",
                "stroke": "#ff0000",
            },
            {
                **layer_base("text_1", "text", x=10, y=20, width=100, height=40, z_index=2),
                "text": "Kristianna",
                "fontRef": {"family": "Font 5", "source": "asset", "assetId": "lovely-script"},
                "style": {
                    "fontSize": 24,
                    "fill": "#123456",
                    "stroke": "#ffffff",
                    "strokeWidth": 0,
                    "align": "center",
                    "lineHeight": 1.1,
                    "letterSpacing": 1,
                },
                "layout": {"mode": "box", "overflow": "shrink-to-fit"},
            },
            {
                **layer_base("flower_1", "svg", x=30, y=40, width=80, height=90, z_index=1),
                "inlineSvg": (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
                    '"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">'
                    '<svg viewBox="0 0 10 10">'
                    '<path d="M0 0h10v10z" fill="#00aa00" onclick="bad()"/>'
                    "</svg>"
                ),
                "viewBox": {"x": 0, "y": 0, "width": 10, "height": 10},
                "preserveVector": True,
            },
            {
                **layer_base("path_1", "path", x=1, y=2, z_index=3),
                "pathData": "M0 0 L10 0 L10 10 Z",
                "fill": "none",
                "stroke": "#111111",
                "strokeWidth": 2,
            },
        ]
    )

    result = export_svg(document, exported_at=EXPORTED_AT)

    assert result.file_name == "birth-flower-card_order-1_2026-06-12T10-11-12-000Z.svg"
    assert result.mime_type == "image/svg+xml"
    assert result.metadata == {
        "templateId": "birth-flower-card",
        "orderId": "order-1",
        "exportedAt": EXPORTED_AT,
        "appVersion": "0.1.0",
    }
    assert '<metadata id="flower-export-metadata">' in result.content
    assert '"orderId": "order-1"' in result.content
    assert (
        '<rect width="300" height="200" fill="#ffffff" data-export-background="canvas"/>'
        in result.content
    )
    assert 'id="flower_1"' in result.content
    assert 'id="text_1"' in result.content
    assert 'id="path_1"' in result.content
    assert result.content.index('id="flower_1"') < result.content.index('id="text_1"')
    assert 'data-source-viewBox="0 0 10 10"' in result.content
    assert "onclick" not in result.content
    assert "selection_1" not in result.content
    assert result.content.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert result.content.count("<?xml") == 1
    assert "<!DOCTYPE" not in result.content
    assert "<text" not in result.content
    assert "<image" not in result.content
    assert 'data-layer-id="text_1"' in result.content
    assert ET.fromstring(result.content) is not None


def test_svg_export_rejects_missing_required_document_fields() -> None:
    try:
        export_svg({"schemaVersion": "1.0", "layers": []})
    except DomainError as exc:
        assert exc.code == "VALIDATION_ERROR"
        assert exc.details["field"] == "canvas"
    else:
        raise AssertionError("export_svg should reject a document without canvas")


def base_document(*, layers: list[dict]) -> dict:
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
            "createdAt": "2026-06-12T00:00:00.000Z",
            "updatedAt": "2026-06-12T00:00:00.000Z",
        },
        "canvas": {
            "width": 300,
            "height": 200,
            "unit": "px",
            "background": {"type": "solid", "color": "#ffffff"},
        },
        "exportSettings": {
            "schemaVersion": "1.0",
            "defaultFormats": ["svg", "png", "dxf"],
            "svg": {"preserveText": True, "preserveVector": True, "includeMetadata": True},
            "png": {"scale": 1, "background": "canvas"},
            "dxf": {"textMode": "paths", "units": "px"},
        },
        "layers": layers,
    }


def build_test_font(path: Path) -> None:
    glyph_order = [".notdef", *list("Kristianna")]
    glyph_order = list(dict.fromkeys(glyph_order))
    glyphs = {name: draw_box_glyph() for name in glyph_order}
    advance_widths = {name: (500, 0) for name in glyph_order}
    path.parent.mkdir(parents=True, exist_ok=True)

    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap({ord(name): name for name in glyph_order if name != ".notdef"})
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
            "familyName": "Lovely Script",
            "styleName": "Regular",
            "uniqueFontIdentifier": "Lovely Script Regular",
            "fullName": "Lovely Script Regular",
            "psName": "LovelyScript-Regular",
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


def layer_base(
    layer_id: str,
    layer_type: str,
    *,
    name: str | None = None,
    x: float = 0,
    y: float = 0,
    width: float = 10,
    height: float = 10,
    scale_x: float = 1,
    scale_y: float = 1,
    rotation: float = 0,
    z_index: int = 1,
) -> dict:
    return {
        "id": layer_id,
        "type": layer_type,
        "name": name or layer_id,
        "visible": True,
        "locked": False,
        "exportable": True,
        "zIndex": z_index,
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
