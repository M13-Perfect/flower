from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import OrderPayload

# tests → inbox-service → automation；合同在 automation/contracts/。
CONTRACT_PATH = Path(__file__).resolve().parents[2] / "contracts" / "order.schema.json"


def _load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_required_matches_pydantic():
    """防漂移：JSON Schema 的 required 必须与 Pydantic 的必填字段完全一致。"""
    schema = _load_contract()
    schema_required = set(schema["required"])
    pydantic_required = {name for name, field in OrderPayload.model_fields.items() if field.is_required()}
    assert schema_required == pydantic_required


def test_contract_properties_match_pydantic_fields():
    schema = _load_contract()
    assert set(schema["properties"]) == set(OrderPayload.model_fields)
    # additionalProperties:false 对齐 Pydantic 的 extra="forbid"。
    assert schema.get("additionalProperties") is False


def test_pydantic_accepts_minimal_valid_doc():
    OrderPayload(**{"schema_version": "1.0", "order_id": "ORD-1", "remark": "hi"})


def test_pydantic_rejects_unknown_field():
    with pytest.raises(ValidationError):
        OrderPayload(**{"schema_version": "1.0", "order_id": "ORD-1", "remark": "hi", "bogus": 1})
