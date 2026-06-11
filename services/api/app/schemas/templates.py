from __future__ import annotations

from typing import Any

from pydantic import Field

from app.schemas.errors import ApiModel
from app.schemas.orders import ParsedOrder


class ApplyTemplateRequest(ApiModel):
    template_id: str = Field(alias="templateId", min_length=1, max_length=120)
    parsed_order: ParsedOrder = Field(alias="parsedOrder")
    project_id: str | None = Field(default=None, alias="projectId", max_length=120)
    job_id: str | None = Field(default=None, alias="jobId", max_length=120)


class ApplyTemplateResponse(ApiModel):
    document: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    requires_manual_confirmation: bool = Field(default=True, alias="requiresManualConfirmation")

