from __future__ import annotations

from app.domain import DomainError
from app.domain.exports.svg import export_svg


EXPORTED_AT = "2026-06-12T10:11:12.000Z"


def test_svg_export_preserves_layers_metadata_and_filters_editor_helpers() -> None:
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
                    '<svg viewBox="0 0 10 10">'
                    '<path d="M0 0h10v10z" fill="#00aa00"/></svg>'
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
    assert "Kristianna" in result.content
    assert 'font-family="Font 5"' in result.content
    assert '<path d="M0 0h10v10z" fill="#00aa00"/>' in result.content
    assert "selection_1" not in result.content


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
