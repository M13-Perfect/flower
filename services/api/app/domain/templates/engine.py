from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.domain import DomainError
from app.schemas.orders import ParsedOrder


APP_VERSION = "0.1.0"
SUPPORTED_TEMPLATE_SCHEMA_VERSION = "1.0"
MONTH_NAMES = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}
MONTH_SHORT_NAMES = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}


def apply_template(
    template_id: str,
    parsed_order: ParsedOrder,
    project_id: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    missing_fields = _missing_order_fields(parsed_order)
    if missing_fields:
        # 模板套用只能使用已经结构化确认的字段；缺字段时停在人工确认环节。
        raise DomainError(
            code="TEMPLATE_APPLY_FAILED",
            message="Template cannot be applied until required order fields are present.",
            details={"missingFields": missing_fields},
            recoverable=True,
        )

    template = _load_template(template_id)
    timestamp = _utc_now()
    document_id = f"doc_{uuid4().hex}"
    resolved_project_id = project_id or "project_local"
    resolved_job_id = job_id or f"job_{uuid4().hex}"

    return {
        "schemaVersion": "1.0",
        "documentId": document_id,
        "projectId": resolved_project_id,
        "jobId": resolved_job_id,
        "metadata": {
            "orderId": parsed_order.order_id,
            "templateId": template["templateId"],
            "templateVersion": template["version"],
            "appVersion": APP_VERSION,
            "createdAt": timestamp,
            "updatedAt": timestamp,
        },
        "canvas": template["canvas"],
        "exportSettings": _default_export_settings(template["canvas"]["unit"]),
        "layers": _build_layers(parsed_order),
    }


def _load_template(template_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", template_id):
        raise DomainError(
            code="TEMPLATE_INVALID",
            message="Template id is invalid.",
            details={"field": "templateId"},
            recoverable=True,
        )
    template_path = _project_root() / "templates" / "products" / f"{template_id}.json"
    try:
        resolved = template_path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise DomainError(
            code="TEMPLATE_NOT_FOUND",
            message="Template file was not found.",
            details={"templateId": template_id},
            recoverable=True,
        ) from exc
    if _project_root() not in resolved.parents:
        raise DomainError(
            code="PATH_TRAVERSAL_BLOCKED",
            message="Template path is outside the project root.",
            details={"templateId": template_id},
            recoverable=True,
        )
    try:
        template = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DomainError(
            code="TEMPLATE_INVALID",
            message="Template JSON is invalid.",
            details={"templateId": template_id},
            recoverable=True,
        ) from exc
    _validate_template(template, template_id)
    return template


def _validate_template(template: dict[str, Any], requested_template_id: str) -> None:
    required_fields = ("schemaVersion", "templateId", "version", "canvas", "slots")
    missing = [field for field in required_fields if field not in template]
    if missing:
        raise DomainError(
            code="TEMPLATE_INVALID",
            message="Template is missing required fields.",
            details={"missingFields": missing},
            recoverable=True,
        )
    if template["schemaVersion"] != SUPPORTED_TEMPLATE_SCHEMA_VERSION:
        raise DomainError(
            code="UNSUPPORTED_SCHEMA_VERSION",
            message="Template schema version is not supported.",
            details={"schemaVersion": template["schemaVersion"]},
            recoverable=True,
        )
    if template["templateId"] != requested_template_id:
        raise DomainError(
            code="TEMPLATE_INVALID",
            message="Template id does not match the requested id.",
            details={"templateId": template["templateId"]},
            recoverable=True,
        )
    slot_ids = [slot.get("slotId") for slot in template.get("slots", []) if isinstance(slot, dict)]
    for required_slot in ("customer_name", "flower"):
        if required_slot not in slot_ids:
            raise DomainError(
                code="TEMPLATE_INVALID",
                message="Template is missing a required slot.",
                details={"slotId": required_slot},
                recoverable=True,
            )


def _build_layers(parsed_order: ParsedOrder) -> list[dict[str, Any]]:
    assert parsed_order.customer_name is not None
    assert parsed_order.month is not None
    assert parsed_order.flower is not None
    assert parsed_order.font_preference is not None

    flower_asset_id, flower_path = _resolve_flower_asset_ref(
        parsed_order.month,
        parsed_order.month_name,
        parsed_order.flower.name,
    )

    return [
        _text_layer(parsed_order.customer_name, parsed_order.font_preference.label),
        _flower_layer(parsed_order.flower.name, flower_asset_id, flower_path),
    ]


def _resolve_flower_asset_ref(
    month: int,
    month_name: str | None,
    flower_name: str,
) -> tuple[str, str]:
    month_slug = _slug(month_name or str(month))
    flower_slug = _slug(flower_name)
    asset_id = f"flower-{month_slug}-{flower_slug}"
    default_path = Path("assets") / "flowers" / f"{month_slug}-{flower_slug}.svg"

    if (_project_root() / default_path).is_file():
        return asset_id, default_path.as_posix()

    legacy_asset = _find_legacy_flower_asset(month, month_name, flower_name)
    if legacy_asset is not None:
        return asset_id, _relative_project_path(legacy_asset)

    return asset_id, default_path.as_posix()


def _find_legacy_flower_asset(
    month: int,
    month_name: str | None,
    flower_name: str,
) -> Path | None:
    legacy_dir = _project_root() / "BirthMonth flowers"
    if not legacy_dir.is_dir():
        return None

    # 业务素材目录来自店铺原始文件包，文件名不是统一 slug，只能按花名和月份做确定性匹配。
    month_keys = {_compact(month_name or ""), _compact(MONTH_NAMES[month]), _compact(MONTH_SHORT_NAMES[month])}
    flower_keys = _flower_match_keys(flower_name)
    for asset_path in sorted(legacy_dir.glob("*.svg"), key=lambda path: path.name.casefold()):
        compact_stem = _compact(asset_path.stem)
        has_month = any(month_key and month_key in compact_stem for month_key in month_keys)
        has_flower = any(flower_key and flower_key in compact_stem for flower_key in flower_keys)
        if has_month and has_flower:
            return asset_path
    return None


def _flower_match_keys(flower_name: str) -> set[str]:
    compact_name = _compact(flower_name)
    words = re.findall(r"[a-z0-9]+", flower_name.casefold())
    return {compact_name, *(word for word in words if word)}


def _text_layer(text: str, font_label: str) -> dict[str, Any]:
    return {
        **_layer_base(
            layer_id="layer_customer_name",
            layer_type="text",
            name="Customer name",
            slot_id="customer_name",
            z_index=2,
            x=600,
            y=2200,
            width=1800,
            height=260,
            tags=["customer-text"],
        ),
        "text": text,
        "fontRef": {
            "family": font_label,
            "source": "asset",
            "assetId": _slug(font_label),
            "fallbackFamilies": ["serif"],
        },
        "style": {
            "fontSize": 180,
            "fill": "#1f2933",
            "stroke": "#ffffff",
            "strokeWidth": 0,
            "align": "center",
            "lineHeight": 1.1,
            "letterSpacing": 0,
        },
        "layout": {
            "mode": "box",
            "overflow": "shrink-to-fit",
        },
    }


def _flower_layer(flower_name: str, asset_id: str, asset_path: str) -> dict[str, Any]:
    return {
        **_layer_base(
            layer_id="layer_flower",
            layer_type="svg",
            name=f"Birth flower - {flower_name}",
            slot_id="flower",
            z_index=1,
            x=900,
            y=420,
            width=1200,
            height=1400,
            tags=["flower", "asset"],
        ),
        "assetRef": {
            "assetId": asset_id,
            "path": asset_path,
        },
        "viewBox": {
            "x": 0,
            "y": 0,
            "width": 512,
            "height": 512,
        },
        "preserveVector": True,
    }


def _layer_base(
    *,
    layer_id: str,
    layer_type: str,
    name: str,
    slot_id: str,
    z_index: int,
    x: int,
    y: int,
    width: int,
    height: int,
    tags: list[str],
) -> dict[str, Any]:
    return {
        "id": layer_id,
        "type": layer_type,
        "name": name,
        "visible": True,
        "locked": False,
        "exportable": True,
        "zIndex": z_index,
        "opacity": 1,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "scaleX": 1,
        "scaleY": 1,
        "rotation": 0,
        "slotId": slot_id,
        "tags": tags,
    }


def _default_export_settings(unit: str) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "defaultFormats": ["svg", "png"],
        "svg": {
            "preserveText": True,
            "preserveVector": True,
            "includeMetadata": True,
        },
        "png": {
            "scale": 1,
            "background": "canvas",
        },
        "dxf": {
            "textMode": "paths",
            "units": unit,
        },
    }


def _missing_order_fields(parsed_order: ParsedOrder) -> list[str]:
    missing: list[str] = []
    if not parsed_order.customer_name:
        missing.append("customerName")
    if parsed_order.month is None:
        missing.append("month")
    if parsed_order.flower is None:
        missing.append("flower")
    if parsed_order.font_preference is None:
        missing.append("fontPreference")
    return missing


def _project_root() -> Path:
    default_root = Path(__file__).resolve().parents[5]
    return Path(os.environ.get("FLOWER_PROJECT_ROOT", default_root)).resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _relative_project_path(path: Path) -> str:
    resolved = path.resolve()
    root = _project_root()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise DomainError(
            code="PATH_TRAVERSAL_BLOCKED",
            message="Template asset path is outside the project root.",
            details={"path": str(path)},
            recoverable=True,
        ) from exc
