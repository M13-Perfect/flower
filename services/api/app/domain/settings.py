from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain import DomainError


SETTINGS_FILE_NAME = ".flower-local-settings.json"
DEFAULT_ASSET_DIRECTORIES = ("assets",)
DEFAULT_FONT_DIRECTORIES = ("assets/fonts", "BirthMonth flowers")


@dataclass(frozen=True)
class PathSettings:
    asset_directories: tuple[str, ...]
    font_directories: tuple[str, ...]
    output_directory: str | None = None


def get_path_settings(root: Path | None = None) -> PathSettings:
    project_root = _project_root(root)
    raw = _read_settings_file(project_root)
    if raw is None:
        return _default_path_settings(project_root)

    return PathSettings(
        asset_directories=tuple(raw.get("assetDirectories", [])),
        font_directories=tuple(raw.get("fontDirectories", [])),
        output_directory=raw.get("outputDirectory"),
    )


def update_path_settings(
    *,
    asset_directories: list[str],
    font_directories: list[str],
    output_directory: str | None,
    root: Path | None = None,
) -> PathSettings:
    project_root = _project_root(root)
    settings = PathSettings(
        asset_directories=tuple(
            str(_normalize_existing_directory(path, "assetDirectories", project_root))
            for path in asset_directories
        ),
        font_directories=tuple(
            str(_normalize_existing_directory(path, "fontDirectories", project_root))
            for path in font_directories
        ),
        output_directory=(
            str(_normalize_output_directory(output_directory, project_root))
            if output_directory
            else None
        ),
    )
    _settings_file(project_root).write_text(
        json.dumps(
            {
                "assetDirectories": list(settings.asset_directories),
                "fontDirectories": list(settings.font_directories),
                "outputDirectory": settings.output_directory,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return settings


def has_saved_path_settings(root: Path | None = None) -> bool:
    return _settings_file(_project_root(root)).is_file()


def _default_path_settings(project_root: Path) -> PathSettings:
    return PathSettings(
        asset_directories=tuple(str((project_root / path).resolve()) for path in DEFAULT_ASSET_DIRECTORIES),
        font_directories=tuple(str((project_root / path).resolve()) for path in DEFAULT_FONT_DIRECTORIES),
        output_directory=str((project_root / "outputs").resolve()),
    )


def _read_settings_file(project_root: Path) -> dict[str, Any] | None:
    path = _settings_file(project_root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DomainError(
            code="SETTINGS_READ_FAILED",
            message="Path settings could not be read.",
            details={"errorType": exc.__class__.__name__},
            recoverable=True,
        ) from exc
    if not isinstance(payload, dict):
        raise DomainError(
            code="SETTINGS_INVALID",
            message="Path settings file must contain an object.",
            details={},
            recoverable=True,
        )
    return payload


def _normalize_existing_directory(value: str, field: str, project_root: Path) -> Path:
    path = _normalize_path(value, project_root)
    if not path.exists():
        raise DomainError(
            code="DIRECTORY_NOT_FOUND",
            message="Selected directory does not exist.",
            details={"field": field, "path": str(path)},
            recoverable=True,
        )
    if not path.is_dir():
        raise DomainError(
            code="PATH_NOT_DIRECTORY",
            message="Selected path is not a directory.",
            details={"field": field, "path": str(path)},
            recoverable=True,
        )
    return path


def _normalize_output_directory(value: str, project_root: Path) -> Path:
    path = _normalize_path(value, project_root)
    if path.exists() and not path.is_dir():
        raise DomainError(
            code="PATH_NOT_DIRECTORY",
            message="Output path is not a directory.",
            details={"field": "outputDirectory", "path": str(path)},
            recoverable=True,
        )
    return path


def _normalize_path(value: str, project_root: Path) -> Path:
    if not value or not value.strip():
        raise DomainError(
            code="DIRECTORY_REQUIRED",
            message="Directory path must not be empty.",
            details={},
            recoverable=True,
        )
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _settings_file(project_root: Path) -> Path:
    return project_root / SETTINGS_FILE_NAME


def _project_root(root: Path | None = None) -> Path:
    if root is not None:
        return root.resolve()
    default_root = Path(__file__).resolve().parents[4]
    return Path(os.environ.get("FLOWER_PROJECT_ROOT", default_root)).resolve()
