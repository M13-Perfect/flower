from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.schemas.errors import ApiModel


class DxfExportRequest(ApiModel):
    document: dict[str, Any]
    units: Literal["px", "mm", "in"] | None = None
    exported_at: str | None = Field(default=None, alias="exportedAt")


class ExportWarningBody(ApiModel):
    code: str
    message: str
    layer_id: str | None = Field(default=None, alias="layerId")


class DxfExportResponse(ApiModel):
    file_name: str = Field(alias="fileName")
    mime_type: str = Field(alias="mimeType")
    content_base64: str = Field(alias="contentBase64")
    metadata: dict[str, str]
    warnings: list[ExportWarningBody] = Field(default_factory=list)
