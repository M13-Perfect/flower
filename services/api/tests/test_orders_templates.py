import pytest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


REAL_ORDER_NOTES = [
    pytest.param(
        "Choose Your Birth Flower  ：Sep - Aster\n"
        "Font Design  ：Font 3\n"
        "Personalization  ：Lacey",
        ("Lacey", 9, "Aster", "Font 3"),
        id="sep-aster-font-3-lacey",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Jun - Rose\n"
        "Font Design  ：Font 3\n"
        "Personalization  ：Hend",
        ("Hend", 6, "Rose", "Font 3"),
        id="jun-rose-font-3-hend",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Jan - Snowdrop\n"
        "Font Design  ：Font 2\n"
        "Personalization  ：Veronica",
        ("Veronica", 1, "Snowdrop", "Font 2"),
        id="jan-snowdrop-font-2-veronica",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Oct - Cosmos\n"
        "Font Design  ：Font 3\n"
        "Personalization  ：Grace",
        ("Grace", 10, "Cosmos", "Font 3"),
        id="oct-cosmos-font-3-grace",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Feb - Violet\n"
        "Font Design  ：Font 4\n"
        "Personalization  ：Gemma",
        ("Gemma", 2, "Violet", "Font 4"),
        id="feb-violet-font-4-gemma",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Nov - Peony\n"
        "Font Design  ：Font 3\n"
        "Personalization  ：Katie",
        ("Katie", 11, "Peony", "Font 3"),
        id="nov-peony-font-3-katie",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Jun - Honeysuckle\n"
        "Font Design  ：Font 3\n"
        "Personalization  ：Kristin",
        ("Kristin", 6, "Honeysuckle", "Font 3"),
        id="jun-honeysuckle-font-3-kristin",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Mar - Daffodil\n"
        "Font Design  ：Font 3\n"
        "Personalization  ：Elisabeth",
        ("Elisabeth", 3, "Daffodil", "Font 3"),
        id="mar-daffodil-font-3-elisabeth",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Jun - Honeysuckle\n"
        "Font Design  ：Font 3\n"
        "Personalization  ：Jenna",
        ("Jenna", 6, "Honeysuckle", "Font 3"),
        id="jun-honeysuckle-font-3-jenna",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Jun - Honeysuckle\n"
        "Font Design  ：Font 3\n"
        "Personalization  ：Zoe",
        ("Zoe", 6, "Honeysuckle", "Font 3"),
        id="jun-honeysuckle-font-3-zoe",
    ),
]


def test_parse_order_note_returns_normalized_fields_and_manual_confirmation() -> None:
    client = TestClient(app)

    response = client.post(
        "/orders/parse",
        json={
            "orderNote": (
                "Customer Name: Ava Chen\n"
                "Birth Month: June\n"
                "Flower: Rose\n"
                "Font Design: Font 2\n"
                "Special Notes: Please keep the name centered."
            ),
            "orderId": "order-1001",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["requiresManualConfirmation"] is True
    assert payload["warnings"] == []
    assert payload["parsedOrder"] == {
        "orderId": "order-1001",
        "customerName": "Ava Chen",
        "month": 6,
        "monthName": "June",
        "flower": {
            "choice": 1,
            "name": "Rose",
        },
        "fontPreference": {
            "choice": 2,
            "label": "Font 2",
        },
        "specialNotes": "Please keep the name centered.",
    }


@pytest.mark.parametrize(("order_note", "expected"), REAL_ORDER_NOTES)
def test_parse_order_note_accepts_supplied_real_birth_flower_notes(
    order_note: str,
    expected: tuple[str, int, str, str],
) -> None:
    client = TestClient(app)
    expected_name, expected_month, expected_flower, expected_font = expected

    response = client.post(
        "/orders/parse",
        json={"orderNote": order_note, "orderId": f"real-{expected_name.casefold()}"},
    )

    assert response.status_code == 200
    payload = response.json()
    parsed = payload["parsedOrder"]
    assert payload["requiresManualConfirmation"] is True
    assert payload["warnings"] == []
    assert parsed["customerName"] == expected_name
    assert parsed["month"] == expected_month
    assert parsed["flower"]["name"] == expected_flower
    assert parsed["fontPreference"]["label"] == expected_font


def test_parse_order_note_returns_structured_error_when_required_fields_are_uncertain(
    caplog,
) -> None:
    client = TestClient(app)
    raw_note = "Customer Name: Rose\nSpecial Notes: customer mentioned June maybe"

    response = client.post("/orders/parse", json={"orderNote": raw_note})

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "ORDER_PARSE_FAILED"
    assert payload["error"]["recoverable"] is True
    assert payload["error"]["details"]["missingFields"] == [
        "month",
        "flower",
        "fontPreference",
    ]
    assert raw_note not in caplog.text


def test_apply_template_returns_editable_layer_document() -> None:
    client = TestClient(app)
    parsed_order = {
        "orderId": "order-1001",
        "customerName": "Ava Chen",
        "month": 6,
        "monthName": "June",
        "flower": {
            "choice": 1,
            "name": "Rose",
        },
        "fontPreference": {
            "choice": 2,
            "label": "Font 2",
        },
        "specialNotes": "Please keep the name centered.",
    }

    response = client.post(
        "/templates/apply",
        json={
            "templateId": "birth-flower-card",
            "projectId": "project-1001",
            "jobId": "job-1001",
            "parsedOrder": parsed_order,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["requiresManualConfirmation"] is True
    assert payload["warnings"] == []

    document = payload["document"]
    assert document["schemaVersion"] == "1.0"
    assert document["projectId"] == "project-1001"
    assert document["jobId"] == "job-1001"
    assert document["metadata"]["orderId"] == "order-1001"
    assert document["metadata"]["templateId"] == "birth-flower-card"
    assert document["metadata"]["templateVersion"] == "1.0.0"
    assert document["canvas"]["width"] == 3000
    assert document["canvas"]["height"] == 3000

    text_layer = next(layer for layer in document["layers"] if layer["slotId"] == "customer_name")
    flower_layer = next(layer for layer in document["layers"] if layer["slotId"] == "flower")

    assert text_layer["type"] == "text"
    assert text_layer["text"] == "Ava Chen"
    assert text_layer["fontRef"]["family"] == "Font 2"
    assert text_layer["exportable"] is True
    assert flower_layer["type"] == "svg"
    assert flower_layer["assetRef"]["assetId"] == "flower-june-rose"
    assert flower_layer["assetRef"]["path"].endswith(".svg")
    assert not flower_layer["assetRef"]["path"].startswith("/")
    assert flower_layer["preserveVector"] is True


def test_apply_template_resolves_birth_month_flower_asset_from_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path
    template_dir = project_root / "templates" / "products"
    asset_dir = project_root / "BirthMonth flowers"
    template_dir.mkdir(parents=True)
    asset_dir.mkdir()
    (template_dir / "birth-flower-card.json").write_text(
        """
        {
          "schemaVersion": "1.0",
          "templateId": "birth-flower-card",
          "version": "1.0.0",
          "productType": "birth-flower",
          "displayName": "Birth Flower Card",
          "canvas": {
            "width": 3000,
            "height": 3000,
            "unit": "px",
            "background": { "type": "solid", "color": "#ffffff" }
          },
          "slots": [
            { "slotId": "customer_name", "kind": "text", "required": true },
            { "slotId": "flower", "kind": "svg", "required": true }
          ]
        }
        """,
        encoding="utf-8",
    )
    (asset_dir / "AsterSeptember .svg").write_text(
        '<svg viewBox="0 0 10 10"><path d="M0 0 L10 0 L10 10 Z"/></svg>',
        encoding="utf-8",
    )
    monkeypatch.setenv("FLOWER_PROJECT_ROOT", str(project_root))
    client = TestClient(app)

    response = client.post(
        "/templates/apply",
        json={
            "templateId": "birth-flower-card",
            "parsedOrder": {
                "orderId": "order-lacey",
                "customerName": "Lacey",
                "month": 9,
                "monthName": "September",
                "flower": {"choice": 1, "name": "Aster"},
                "fontPreference": {"choice": 3, "label": "Font 3"},
                "specialNotes": "",
            },
        },
    )

    assert response.status_code == 200
    document = response.json()["document"]
    flower_layer = next(layer for layer in document["layers"] if layer["slotId"] == "flower")
    assert flower_layer["assetRef"] == {
        "assetId": "flower-september-aster",
        "path": "BirthMonth flowers/AsterSeptember .svg",
    }


def test_apply_template_returns_structured_error_for_missing_required_order_data() -> None:
    client = TestClient(app)

    response = client.post(
        "/templates/apply",
        json={
            "templateId": "birth-flower-card",
            "parsedOrder": {
                "customerName": "Ava Chen",
                "month": 6,
                "monthName": "June",
                "flower": {
                    "choice": 1,
                    "name": "Rose",
                },
                "fontPreference": None,
                "specialNotes": "",
            },
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "TEMPLATE_APPLY_FAILED"
    assert payload["error"]["recoverable"] is True
    assert payload["error"]["details"]["missingFields"] == ["fontPreference"]
