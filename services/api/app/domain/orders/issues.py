from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReviewIssue:
    code: str
    severity: str
    field: str | None
    message: str
    raw_value: str | None = None
    suggested_value: str | None = None
    requires_manual_action: bool = True
