from fastapi.testclient import TestClient

from app.main import app


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
    assert flower_layer["assetRef"] == {
        "assetId": "flower-june-rose",
        "path": "assets/flowers/june-rose.svg",
    }
    assert flower_layer["preserveVector"] is True


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
