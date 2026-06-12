from __future__ import annotations

import json
from dataclasses import dataclass

from app.domain import DomainError
from app.domain.templates.engine import _load_template, _project_root


@dataclass(frozen=True)
class PhysicalSize:
    width_mm: float
    height_mm: float
    # True 表示模板未显式存 heightMm,高度由画布宽高比推导(等比锁定状态)。
    height_derived: bool
    canvas_width: float
    canvas_height: float


def get_physical_size(template_id: str) -> PhysicalSize:
    template = _load_template(template_id)
    canvas = template["canvas"]
    canvas_width = float(canvas["width"])
    canvas_height = float(canvas["height"])
    physical = (template.get("exportSettings") or {}).get("physical") or {}
    width = float(physical.get("widthMm") or 0)
    if width <= 0:
        raise DomainError(
            code="PHYSICAL_SIZE_MISSING",
            message="Template has no physical width configured.",
            details={"templateId": template_id, "field": "exportSettings.physical.widthMm"},
            recoverable=True,
        )
    raw_height = physical.get("heightMm")
    if raw_height:
        return PhysicalSize(width, float(raw_height), False, canvas_width, canvas_height)
    return PhysicalSize(
        width, width * canvas_height / canvas_width, True, canvas_width, canvas_height
    )


def update_physical_size(
    template_id: str,
    width_mm: float,
    height_mm: float | None = None,
) -> PhysicalSize:
    """写回模板文件本身——UI 与批量引擎共用同一数据源,禁止另存本地副本。

    height_mm 为 None 表示等比锁定:删除显式 heightMm,高度恢复按画布比例推导。
    """
    if width_mm <= 0:
        raise DomainError(
            code="VALIDATION_ERROR",
            message="Physical width must be positive.",
            details={"field": "widthMm"},
            recoverable=True,
        )
    if height_mm is not None and height_mm <= 0:
        raise DomainError(
            code="VALIDATION_ERROR",
            message="Physical height must be positive when unlocked.",
            details={"field": "heightMm"},
            recoverable=True,
        )
    template = _load_template(template_id)
    export_settings = template.setdefault("exportSettings", {})
    physical = export_settings.setdefault("physical", {})
    physical["widthMm"] = width_mm
    if height_mm is None:
        physical.pop("heightMm", None)
    else:
        physical["heightMm"] = height_mm
    path = _project_root() / "templates" / "products" / f"{template_id}.json"
    path.write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return get_physical_size(template_id)
