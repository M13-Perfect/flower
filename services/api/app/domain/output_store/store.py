from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.domain import DomainError


OutputKind = Literal["json", "png", "svg", "dxf"]


@dataclass(frozen=True)
class SavedOutputFile:
    kind: OutputKind
    file_name: str
    relative_path: str
    bytes_written: int


@dataclass(frozen=True)
class SaveOutputsResult:
    output_dir: str
    files: tuple[SavedOutputFile, ...]


def save_outputs(
    *,
    order_name: str,
    document: dict[str, Any],
    svg: str,
    png_data_url: str | None = None,
    dxf_content_base64: str | None = None,
    output_directory: str | None = None,
) -> SaveOutputsResult:
    output_id = _output_order_id(order_name, document)
    output_dir = _safe_output_dir(output_id, output_directory)
    selected_output_root = output_directory is not None and bool(output_directory.strip())
    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        files = [
            _write_text(output_dir, "order.json", json.dumps(document, ensure_ascii=False, indent=2), "json"),
            _write_text(output_dir, f"{output_id}.svg", svg, "svg"),
        ]
        if png_data_url:
            files.append(_write_bytes(output_dir, f"{output_id}.png", _decode_png_data_url(png_data_url), "png"))
        if dxf_content_base64:
            files.append(_write_bytes(output_dir, f"{output_id}.dxf", _decode_base64(dxf_content_base64, "dxf"), "dxf"))
    except OSError as exc:
        # 文件系统错误必须转成业务错误，避免前端只收到 500 或浏览器级 Failed to fetch。
        raise DomainError(
            code="OUTPUT_WRITE_FAILED",
            message="Output files could not be written.",
            details={
                "orderName": _sanitize_order_name(order_name),
                "errorType": exc.__class__.__name__,
            },
            recoverable=True,
        ) from exc

    return SaveOutputsResult(
        output_dir=str(output_dir) if selected_output_root else _relative_project_path(output_dir),
        files=tuple(files),
    )


def _write_text(output_dir: Path, file_name: str, content: str, kind: OutputKind) -> SavedOutputFile:
    encoded = content.encode("utf-8")
    return _write_bytes(output_dir, file_name, encoded, kind)


def _write_bytes(output_dir: Path, file_name: str, content: bytes, kind: OutputKind) -> SavedOutputFile:
    path = _safe_child_path(output_dir, file_name)
    path.write_bytes(content)
    return SavedOutputFile(
        kind=kind,
        file_name=file_name,
        relative_path=_relative_project_path(path),
        bytes_written=len(content),
    )


def _decode_png_data_url(value: str) -> bytes:
    prefix = "data:image/png;base64,"
    if not value.startswith(prefix):
        raise DomainError(
            code="OUTPUT_INVALID_CONTENT",
            message="PNG content must be a base64 data URL.",
            details={"field": "pngDataUrl"},
            recoverable=True,
        )
    return _decode_base64(value[len(prefix) :], "pngDataUrl")


def _decode_base64(value: str, field: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise DomainError(
            code="OUTPUT_INVALID_CONTENT",
            message="Output content is not valid base64.",
            details={"field": field},
            recoverable=True,
        ) from exc


def _safe_output_dir(order_name: str, output_directory: str | None = None) -> Path:
    outputs_root = _resolve_output_root(output_directory)
    order_dir = (outputs_root / _sanitize_order_name(order_name)).resolve()
    if outputs_root != order_dir and outputs_root not in order_dir.parents:
        raise DomainError(
            code="PATH_TRAVERSAL_BLOCKED",
            message="Output directory is outside the outputs root.",
            details={"orderName": order_name},
            recoverable=True,
        )
    return order_dir


def _resolve_output_root(output_directory: str | None) -> Path:
    if output_directory is None or not output_directory.strip():
        return (_project_root() / "outputs").resolve()

    root = Path(output_directory).expanduser()
    if not root.is_absolute():
        root = _project_root() / root
    root = root.resolve()
    if root.exists() and not root.is_dir():
        raise DomainError(
            code="PATH_NOT_DIRECTORY",
            message="Output path is not a directory.",
            details={"path": str(root)},
            recoverable=True,
        )
    return root


def _safe_child_path(output_dir: Path, file_name: str) -> Path:
    path = (output_dir / file_name).resolve()
    if output_dir.resolve() not in path.parents:
        raise DomainError(
            code="PATH_TRAVERSAL_BLOCKED",
            message="Output file path is outside the order output directory.",
            details={"fileName": file_name},
            recoverable=True,
        )
    return path


def _sanitize_order_name(value: str) -> str:
    leaf = Path((value or "").strip()).name
    cleaned = "".join(char if char.isalnum() or char in {" ", "-", "_"} else "-" for char in leaf)
    collapsed = re.sub(r"[\s_-]+", "-", cleaned).strip("-._ ")
    return (collapsed or "order")[:80]


def _output_order_id(order_name: str, document: dict[str, Any]) -> str:
    metadata = document.get("metadata")
    raw_order_id = metadata.get("orderId") if isinstance(metadata, dict) else None
    return _sanitize_order_name(str(raw_order_id or order_name))


def _relative_project_path(path: Path) -> str:
    resolved = path.resolve()
    root = _project_root()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return str(resolved)


def _project_root() -> Path:
    default_root = Path(__file__).resolve().parents[5]
    return Path(os.environ.get("FLOWER_PROJECT_ROOT", default_root)).resolve()
