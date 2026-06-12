from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any

from app.domain import DomainError
from app.domain.orders.issues import ReviewIssue


PROJECT_ROOT = Path(__file__).resolve().parents[5]
LISTING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")


@dataclass(frozen=True)
class FontOptionResolution:
    option_no: int
    label: str
    font_id: str | None
    source_path: str | None
    issues: list[ReviewIssue] = field(default_factory=list)


def resolve_font_option(
    listing_id: str,
    listing_version: str | None,
    option_no: int | None,
) -> FontOptionResolution:
    if option_no is None:
        return FontOptionResolution(
            option_no=0,
            label="",
            font_id=None,
            source_path=None,
            issues=[
                ReviewIssue(
                    code="FONT_OPTION_MISSING",
                    severity="warning",
                    field="font",
                    message="Font option number is missing.",
                    requires_manual_action=True,
                )
            ],
        )

    mapping = _load_mapping(listing_id)
    _validate_listing_version(listing_id, listing_version, mapping)
    options = _validated_font_options(listing_id, mapping)
    for option in options:
        mapped_option_no = _validate_option_no(listing_id, option)
        if mapped_option_no != option_no:
            continue
        source_path = str(option.get("sourcePath") or "")
        resolved_path = _resolve_project_path(source_path)
        if not source_path or not resolved_path.is_file():
            return FontOptionResolution(
                option_no=option_no,
                label=str(option.get("label") or f"Font {option_no}"),
                font_id=None,
                source_path=source_path or None,
                issues=[
                    ReviewIssue(
                        code="FONT_ASSET_MISSING",
                        severity="warning",
                        field="font",
                        message=f"Mapped font file is missing for Font {option_no}.",
                        raw_value=str(option_no),
                        suggested_value=str(option.get("fontId") or ""),
                        requires_manual_action=True,
                    )
                ],
            )
        font_id = str(option.get("fontId") or "").strip()
        if not font_id:
            return FontOptionResolution(
                option_no=option_no,
                label=str(option.get("label") or f"Font {option_no}"),
                font_id=None,
                source_path=source_path,
                issues=[
                    ReviewIssue(
                        code="FONT_OPTION_UNMAPPED",
                        severity="warning",
                        field="font",
                        message=f"mapped font id is missing for Font {option_no}.",
                        raw_value=str(option_no),
                        requires_manual_action=True,
                    )
                ],
            )
        return FontOptionResolution(
            option_no=option_no,
            label=str(option.get("label") or f"Font {option_no}"),
            font_id=font_id,
            source_path=source_path,
            issues=[],
        )

    return FontOptionResolution(
        option_no=option_no,
        label=f"Font {option_no}",
        font_id=None,
        source_path=None,
        issues=[
            ReviewIssue(
                code="FONT_OPTION_UNMAPPED",
                severity="warning",
                field="font",
                message=f"Font option is not mapped for this listing: Font {option_no}.",
                raw_value=str(option_no),
                requires_manual_action=True,
            )
        ],
    )


def _load_mapping(listing_id: str) -> dict:
    _validate_listing_id(listing_id)
    mapping_dir = _resolve_project_path("templates/font-options")
    mapping_path = (mapping_dir / f"{listing_id}.json").resolve()
    if mapping_path.parent != mapping_dir:
        raise DomainError(
            code="FONT_OPTION_LISTING_INVALID",
            message="Font option listing id is invalid.",
            details={"listingId": listing_id},
            recoverable=True,
        )
    if not mapping_path.is_file():
        raise DomainError(
            code="FONT_OPTION_MAPPING_MISSING",
            message="Font option mapping file was not found.",
            details={"listingId": listing_id},
            recoverable=True,
        )
    try:
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DomainError(
            code="FONT_OPTION_MAPPING_INVALID",
            message="Font option mapping JSON is invalid.",
            details={"listingId": listing_id},
            recoverable=True,
        ) from exc
    if not isinstance(mapping, dict):
        raise DomainError(
            code="FONT_OPTION_MAPPING_INVALID",
            message="Font option mapping JSON must be an object.",
            details={"listingId": listing_id},
            recoverable=True,
        )
    return mapping


def _validate_listing_id(listing_id: str) -> None:
    if not LISTING_ID_PATTERN.fullmatch(listing_id):
        raise DomainError(
            code="FONT_OPTION_LISTING_INVALID",
            message="Font option listing id is invalid.",
            details={"listingId": listing_id},
            recoverable=True,
        )


def _validate_listing_version(
    listing_id: str, requested_version: str | None, mapping: dict[str, Any]
) -> None:
    mapping_version = str(mapping.get("listingVersion") or "")
    if requested_version is not None and mapping_version and requested_version != mapping_version:
        raise DomainError(
            code="FONT_OPTION_VERSION_MISMATCH",
            message="Font option mapping version does not match the requested listing version.",
            details={
                "listingId": listing_id,
                "requestedVersion": requested_version,
                "mappingVersion": mapping_version,
            },
            recoverable=True,
        )


def _validated_font_options(listing_id: str, mapping: dict[str, Any]) -> list[dict[str, Any]]:
    raw_options = mapping.get("fontOptions", [])
    if not isinstance(raw_options, list):
        raise DomainError(
            code="FONT_OPTION_MAPPING_INVALID",
            message="Font option mapping must contain a fontOptions list.",
            details={"listingId": listing_id},
            recoverable=True,
        )
    options: list[dict[str, Any]] = []
    for option in raw_options:
        if not isinstance(option, dict):
            raise DomainError(
                code="FONT_OPTION_MAPPING_INVALID",
                message="Font option entries must be objects.",
                details={"listingId": listing_id},
                recoverable=True,
            )
        _validate_option_no(listing_id, option)
        options.append(option)
    return options


def _validate_option_no(listing_id: str, option: dict[str, Any]) -> int:
    raw_option_no = option.get("optionNo")
    if isinstance(raw_option_no, bool):
        raise _invalid_option_no(listing_id)
    if isinstance(raw_option_no, int):
        return raw_option_no
    if isinstance(raw_option_no, str) and raw_option_no.isdigit():
        return int(raw_option_no)
    raise _invalid_option_no(listing_id)


def _invalid_option_no(listing_id: str) -> DomainError:
    return DomainError(
        code="FONT_OPTION_MAPPING_INVALID",
        message="Font option number must be an integer.",
        details={"listingId": listing_id},
        recoverable=True,
    )


def _resolve_project_path(relative_path: str) -> Path:
    raw_path = Path(relative_path)
    path = raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path
    resolved = path.resolve()
    root = PROJECT_ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise DomainError(
            code="PATH_TRAVERSAL_BLOCKED",
            message="Font option path is outside the project root.",
            details={"path": relative_path},
            recoverable=True,
        )
    return resolved
