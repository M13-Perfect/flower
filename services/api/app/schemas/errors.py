from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ErrorBody(ApiModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = Field(default_factory=lambda: f"trace_{uuid4().hex}", alias="traceId")
    recoverable: bool = True


class ErrorEnvelope(ApiModel):
    error: ErrorBody

