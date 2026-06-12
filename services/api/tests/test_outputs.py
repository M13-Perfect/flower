from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


TINY_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/luzD7wAAAABJRU5ErkJggg=="
)


def test_save_outputs_writes_order_files_under_sanitized_order_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FLOWER_PROJECT_ROOT", str(tmp_path))
    document = _document(order_id="4087956129")
    dxf_text = "0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n"

    response = TestClient(app).post(
        "/outputs/save",
        json={
            "orderName": "Lacey",
            "document": document,
            "svg": '<svg xmlns="http://www.w3.org/2000/svg"><metadata>{}</metadata></svg>',
            "pngDataUrl": TINY_PNG_DATA_URL,
            "dxfContentBase64": base64.b64encode(dxf_text.encode("utf-8")).decode("ascii"),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["outputDir"] == "outputs/4087956129"
    assert {item["kind"] for item in payload["files"]} == {"json", "png", "svg", "dxf"}

    output_dir = tmp_path / "outputs" / "4087956129"
    assert json.loads((output_dir / "order.json").read_text(encoding="utf-8")) == document
    assert (output_dir / "4087956129.svg").read_text(encoding="utf-8").startswith("<svg")
    assert (output_dir / "4087956129.png").read_bytes().startswith(b"\x89PNG")
    assert (output_dir / "4087956129.dxf").read_text(encoding="utf-8") == dxf_text


def test_save_outputs_keeps_order_directory_inside_outputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FLOWER_PROJECT_ROOT", str(tmp_path))

    response = TestClient(app).post(
        "/outputs/save",
        json={
            "orderName": "../bad customer",
            "document": _document(order_id="order-bad"),
            "svg": "<svg></svg>",
            "pngDataUrl": TINY_PNG_DATA_URL,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["outputDir"] == "outputs/order-bad"
    output_dir = (tmp_path / payload["outputDir"]).resolve()
    assert output_dir.is_dir()
    assert tmp_path.resolve() in output_dir.parents


def test_save_outputs_can_write_to_selected_output_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FLOWER_PROJECT_ROOT", str(tmp_path))
    selected_root = tmp_path / "selected-exports"

    response = TestClient(app).post(
        "/outputs/save",
        json={
            "orderName": "Lacey",
            "document": _document(order_id="4087956129"),
            "svg": "<svg></svg>",
            "pngDataUrl": TINY_PNG_DATA_URL,
            "outputDirectory": str(selected_root),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["outputDir"] == str((selected_root / "4087956129").resolve())
    assert (selected_root / "4087956129" / "order.json").is_file()


def test_save_outputs_returns_structured_error_when_output_directory_is_unwritable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FLOWER_PROJECT_ROOT", str(tmp_path))
    original_mkdir = Path.mkdir

    def deny_order_dir(self: Path, *args, **kwargs) -> None:
        if self.name == "order-lacey":
            raise PermissionError("denied")
        original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", deny_order_dir)

    response = TestClient(app).post(
        "/outputs/save",
        json={
            "orderName": "Lacey",
            "document": _document(order_id="order-lacey"),
            "svg": "<svg></svg>",
            "pngDataUrl": TINY_PNG_DATA_URL,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "OUTPUT_WRITE_FAILED"


def _document(*, order_id: str) -> dict:
    return {
        "schemaVersion": "1.0",
        "documentId": "doc-1",
        "projectId": "project-1",
        "jobId": "job-1",
        "metadata": {
            "orderId": order_id,
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
        "layers": [],
    }
