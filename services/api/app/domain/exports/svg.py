from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import re
from typing import Any, Literal

from app.domain import DomainError


ExportBackground = Literal["canvas", "transparent"]
MIME_TYPE = "image/svg+xml"
HELPER_LAYER_MARKERS = {
    "debug",
    "debug-bounds",
    "editor-overlay",
    "guide",
    "guides",
    "handle",
    "handles",
    "selection",
    "selection-box",
    "selection-handle",
    "selection_box",
    "selection_handle",
    "snap-line",
    "snap-lines",
}


@dataclass(frozen=True)
class SvgExportResult:
    file_name: str
    mime_type: str
    content: str
    metadata: dict[str, str]


def export_svg(
    document: dict[str, Any],
    *,
    background: ExportBackground | None = None,
    exported_at: str | None = None,
) -> SvgExportResult:
    _validate_document(document)
    metadata = _metadata(document, exported_at or _utc_now())
    resolved_background = background or _default_background(document)
    content = _build_svg(document, metadata, resolved_background)
    file_name = (
        f"{_file_part(metadata['templateId'])}_"
        f"{_file_part(metadata['orderId'] or 'no-order')}_"
        f"{_file_part(metadata['exportedAt'])}.svg"
    )
    return SvgExportResult(
        file_name=file_name,
        mime_type=MIME_TYPE,
        content=content,
        metadata=metadata,
    )


def _validate_document(document: dict[str, Any]) -> None:
    if not isinstance(document, dict):
        raise DomainError(
            code="VALIDATION_ERROR",
            message="Layer document must be an object.",
            details={},
            recoverable=True,
        )
    if document.get("schemaVersion") != "1.0":
        raise DomainError(
            code="UNSUPPORTED_SCHEMA_VERSION",
            message="Layer document schema version is not supported.",
            details={"schemaVersion": document.get("schemaVersion")},
            recoverable=True,
        )
    canvas = document.get("canvas")
    if not isinstance(canvas, dict):
        raise DomainError(
            code="VALIDATION_ERROR",
            message="Layer document must include canvas settings.",
            details={"field": "canvas"},
            recoverable=True,
        )
    for field in ("width", "height"):
        if _positive_float(canvas.get(field)) is None:
            raise DomainError(
                code="VALIDATION_ERROR",
                message="Layer document canvas dimensions must be positive numbers.",
                details={"field": f"canvas.{field}"},
                recoverable=True,
            )
    if not isinstance(document.get("layers"), list):
        raise DomainError(
            code="VALIDATION_ERROR",
            message="Layer document must include layers.",
            details={"field": "layers"},
            recoverable=True,
        )


def _build_svg(
    document: dict[str, Any],
    metadata: dict[str, str],
    background: ExportBackground,
) -> str:
    canvas = document["canvas"]
    width = _number(canvas["width"])
    height = _number(canvas["height"])
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">'
        ),
        (
            '  <metadata id="flower-export-metadata">'
            f"{escape(json.dumps(metadata, ensure_ascii=False), quote=False)}</metadata>"
        ),
    ]
    background_rect = _background_rect(canvas, background)
    if background_rect:
        lines.append(f"  {background_rect}")
    lines.extend(_indent(_render_layers(document.get("layers", [])), "  "))
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _render_layers(layers: list[dict[str, Any]]) -> list[str]:
    rendered: list[str] = []
    for layer in sorted(layers, key=lambda item: float(item.get("zIndex", 0) or 0)):
        if not _is_exportable(layer):
            continue
        content = _render_layer(layer)
        if content:
            rendered.extend(content.splitlines())
    return rendered


def _render_layer(layer: dict[str, Any]) -> str:
    layer_type = layer.get("type")
    if layer_type == "text":
        return _wrap_layer(layer, _render_text_layer(layer))
    if layer_type == "svg":
        return _wrap_layer(layer, _render_svg_layer(layer))
    if layer_type == "path":
        return _wrap_layer(layer, _render_path_layer(layer))
    if layer_type == "image":
        return _wrap_layer(layer, _render_image_layer(layer))
    if layer_type == "group":
        children = layer.get("children")
        if not isinstance(children, list):
            raise DomainError(
                code="VALIDATION_ERROR",
                message="Group layer children must be an array.",
                details={"layerId": layer.get("id")},
                recoverable=True,
            )
        child_lines = _render_layers(children)
        return _wrap_layer(layer, "\n".join(child_lines)) if child_lines else ""
    raise DomainError(
        code="EXPORT_UNSUPPORTED_LAYER",
        message=f"SVG export does not support layer type {layer_type!r}.",
        details={"layerId": layer.get("id"), "layerType": layer_type},
        recoverable=True,
    )


def _render_text_layer(layer: dict[str, Any]) -> str:
    raw_style = layer.get("style")
    style: dict[str, Any] = raw_style if isinstance(raw_style, dict) else {}
    raw_font_ref = layer.get("fontRef")
    font_ref: dict[str, Any] = raw_font_ref if isinstance(raw_font_ref, dict) else {}
    text = _text_with_glyph_overrides(layer)
    text_x = _aligned_text_x(layer, style)
    anchor = _text_anchor(str(style.get("align") or "left"))
    font_size = _number(style.get("fontSize") or 16)
    line_height = float(style.get("lineHeight") or 1)
    lines = re.split(r"\r\n|\n|\r", text)
    tspans = []
    for index, line in enumerate(lines):
        dy = 0 if index == 0 else float(style.get("fontSize") or 16) * line_height
        tspans.append(f'<tspan x="{_number(text_x)}" dy="{_number(dy)}">{escape(line)}</tspan>')
    attrs = [
        f'font-family="{_attr(str(font_ref.get("family") or "serif"))}"',
        f'font-size="{font_size}"',
        f'fill="{_attr(str(style.get("fill") or "#000000"))}"',
        f'text-anchor="{anchor}"',
        'dominant-baseline="text-before-edge"',
        f'data-layer-id="{_attr(str(layer.get("id") or ""))}"',
    ]
    if float(style.get("letterSpacing") or 0):
        attrs.append(f'letter-spacing="{_number(style.get("letterSpacing"))}"')
    if style.get("stroke"):
        attrs.append(f'stroke="{_attr(str(style.get("stroke")))}"')
    if style.get("strokeWidth") is not None:
        attrs.append(f'stroke-width="{_number(style.get("strokeWidth"))}"')
    return f'<text x="0" y="0" {" ".join(attrs)}>{"".join(tspans)}</text>'


def _render_svg_layer(layer: dict[str, Any]) -> str:
    inline_svg = layer.get("inlineSvg")
    if not inline_svg:
        asset_ref = layer.get("assetRef")
        path = asset_ref.get("path") if isinstance(asset_ref, dict) else ""
        if path:
            inline_svg = _read_svg_asset(str(path), layer)
    if not inline_svg:
        asset_ref = layer.get("assetRef")
        path = asset_ref.get("path") if isinstance(asset_ref, dict) else ""
        return (
            f'<image width="{_number(layer.get("width", 0))}" '
            f'height="{_number(layer.get("height", 0))}" '
            f'href="{_attr(str(path))}" preserveAspectRatio="xMidYMid meet" '
            f'data-layer-id="{_attr(str(layer.get("id") or ""))}"/>'
        )
    inner, view_box = _parse_inline_svg(str(inline_svg), layer)
    return "\n".join(
        [
            (
                f'<svg width="{_number(layer.get("width", 0))}" '
                f'height="{_number(layer.get("height", 0))}" '
                f'viewBox="{_attr(view_box)}" preserveAspectRatio="xMidYMid meet" '
                f'data-layer-id="{_attr(str(layer.get("id") or ""))}">'
            ),
            *_indent(inner.splitlines(), "  "),
            "</svg>",
        ]
    )


def _render_path_layer(layer: dict[str, Any]) -> str:
    attrs = [
        f'd="{_attr(str(layer.get("pathData") or ""))}"',
        f'fill="{_attr(str(layer.get("fill") or "none"))}"',
        f'data-layer-id="{_attr(str(layer.get("id") or ""))}"',
    ]
    if layer.get("stroke"):
        attrs.append(f'stroke="{_attr(str(layer.get("stroke")))}"')
    if layer.get("strokeWidth") is not None:
        attrs.append(f'stroke-width="{_number(layer.get("strokeWidth"))}"')
    return f'<path {" ".join(attrs)}/>'


def _render_image_layer(layer: dict[str, Any]) -> str:
    asset_ref = layer.get("assetRef")
    path = asset_ref.get("path") if isinstance(asset_ref, dict) else ""
    preserve_aspect = _image_aspect(str(layer.get("fit") or "contain"))
    return (
        f'<image width="{_number(layer.get("width", 0))}" '
        f'height="{_number(layer.get("height", 0))}" '
        f'href="{_attr(str(path))}" preserveAspectRatio="{preserve_aspect}" '
        f'data-layer-id="{_attr(str(layer.get("id") or ""))}"/>'
    )


def _wrap_layer(layer: dict[str, Any], content: str) -> str:
    attrs = [
        f'id="{_attr(str(layer.get("id") or ""))}"',
        f'data-layer-name="{_attr(str(layer.get("name") or ""))}"',
        f'transform="{_attr(_layer_transform(layer))}"',
    ]
    opacity = float(layer.get("opacity", 1) or 1)
    if opacity < 1:
        attrs.append(f'opacity="{_number(opacity)}"')
    return "\n".join(["<g " + " ".join(attrs) + ">", *_indent(content.splitlines(), "  "), "</g>"])


def _is_exportable(layer: dict[str, Any]) -> bool:
    if layer.get("visible") is False or layer.get("exportable") is not True:
        return False
    markers = [str(layer.get("name", "")), *(str(tag) for tag in layer.get("tags", []))]
    return not any(marker.strip().casefold() in HELPER_LAYER_MARKERS for marker in markers)


def _parse_inline_svg(svg: str, layer: dict[str, Any]) -> tuple[str, str]:
    sanitized = _strip_unsafe_svg_markup(svg).strip()
    fallback = _fallback_view_box(layer)
    match = re.search(r"<svg\b([^>]*)>([\s\S]*?)</svg>", sanitized, flags=re.IGNORECASE)
    if not match:
        return sanitized, fallback
    view_box_match = re.search(r"\sviewBox=(['\"])(.*?)\1", match.group(1), flags=re.IGNORECASE)
    return match.group(2).strip(), view_box_match.group(2) if view_box_match else fallback


def _strip_unsafe_svg_markup(svg: str) -> str:
    return re.sub(
        r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*')",
        "",
        re.sub(
            r"<script\b[\s\S]*?</script>",
            "",
            re.sub(
                r"<!doctype[\s\S]*?>",
                "",
                re.sub(r"<\?xml[\s\S]*?\?>", "", svg, flags=re.I),
                flags=re.I,
            ),
            flags=re.I,
        ),
        flags=re.I,
    )


def _fallback_view_box(layer: dict[str, Any]) -> str:
    raw = layer.get("viewBox")
    view_box: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return " ".join(
        _number(view_box.get(key, fallback))
        for key, fallback in (
            ("x", 0),
            ("y", 0),
            ("width", layer.get("width", 1)),
            ("height", layer.get("height", 1)),
        )
    )


def _read_svg_asset(relative_path: str, layer: dict[str, Any]) -> str:
    path = _safe_project_path(relative_path)
    if path.suffix.casefold() != ".svg" or not path.is_file():
        raise DomainError(
            code="ASSET_NOT_FOUND",
            message="SVG asset file was not found.",
            details={"layerId": layer.get("id"), "path": relative_path},
            recoverable=True,
        )
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DomainError(
            code="ASSET_LOAD_FAILED",
            message="SVG asset could not be read.",
            details={"layerId": layer.get("id"), "path": relative_path},
            recoverable=True,
        ) from exc


def _safe_project_path(relative_path: str) -> Path:
    if Path(relative_path).is_absolute():
        raise DomainError(
            code="PATH_TRAVERSAL_BLOCKED",
            message="Asset path must be relative to the project root.",
            details={"path": relative_path},
            recoverable=True,
        )
    path = (_project_root() / relative_path).resolve()
    root = _project_root().resolve()
    if path != root and root not in path.parents:
        raise DomainError(
            code="PATH_TRAVERSAL_BLOCKED",
            message="Asset path is outside the project root.",
            details={"path": relative_path},
            recoverable=True,
        )
    return path


def _text_with_glyph_overrides(layer: dict[str, Any]) -> str:
    chars = list(str(layer.get("text") or ""))
    overrides = layer.get("glyphOverrides")
    if not isinstance(overrides, list):
        return "".join(chars)
    sorted_overrides = sorted(
        overrides,
        key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0,
    )
    for override in sorted_overrides:
        if not isinstance(override, dict):
            continue
        index = override.get("index")
        if not isinstance(index, int) or index < 0 or index >= len(chars):
            continue
        replacement = override.get("replacement")
        if chars[index] == override.get("originalText") and isinstance(replacement, str):
            chars[index] = replacement
    return "".join(chars)


def _aligned_text_x(layer: dict[str, Any], style: dict[str, Any]) -> float:
    align = style.get("align")
    if align == "center":
        return float(layer.get("width", 0) or 0) / 2
    if align == "right":
        return float(layer.get("width", 0) or 0)
    return 0


def _text_anchor(align: str) -> str:
    if align == "center":
        return "middle"
    if align == "right":
        return "end"
    return "start"


def _image_aspect(fit: str) -> str:
    if fit == "cover":
        return "xMidYMid slice"
    if fit == "stretch":
        return "none"
    if fit == "none":
        return "xMinYMin"
    return "xMidYMid meet"


def _layer_transform(layer: dict[str, Any]) -> str:
    transforms = [f'translate({_number(layer.get("x", 0))} {_number(layer.get("y", 0))})']
    if float(layer.get("rotation", 0) or 0):
        transforms.append(f'rotate({_number(layer.get("rotation", 0))})')
    if float(layer.get("scaleX", 1) or 1) != 1 or float(layer.get("scaleY", 1) or 1) != 1:
        transforms.append(
            f'scale({_number(layer.get("scaleX", 1))} {_number(layer.get("scaleY", 1))})'
        )
    return " ".join(transforms)


def _background_rect(canvas: dict[str, Any], background: ExportBackground) -> str:
    raw_background = canvas.get("background")
    canvas_background: dict[str, Any] = raw_background if isinstance(raw_background, dict) else {}
    if background == "canvas" and canvas_background.get("type") == "solid":
        return (
            f'<rect width="{_number(canvas["width"])}" height="{_number(canvas["height"])}" '
            f'fill="{_attr(str(canvas_background.get("color") or "#ffffff"))}" '
            'data-export-background="canvas"/>'
        )
    return ""


def _default_background(document: dict[str, Any]) -> ExportBackground:
    raw_background = document["canvas"].get("background")
    canvas_background: dict[str, Any] = raw_background if isinstance(raw_background, dict) else {}
    return "transparent" if canvas_background.get("type") == "transparent" else "canvas"


def _metadata(document: dict[str, Any], exported_at: str) -> dict[str, str]:
    raw_metadata = document.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    return {
        "templateId": str(metadata.get("templateId") or ""),
        "orderId": str(metadata.get("orderId") or ""),
        "exportedAt": exported_at,
        "appVersion": str(metadata.get("appVersion") or ""),
    }


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _number(value: Any) -> str:
    number = float(value or 0)
    if abs(number) < 0.0000005:
        number = 0
    text = f"{number:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _file_part(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value)
    return cleaned.replace(":", "-").replace(".", "-").strip("-") or "export"


def _indent(lines: list[str], prefix: str) -> list[str]:
    return [prefix + line if line else prefix.rstrip() for line in lines]


def _attr(value: str) -> str:
    return escape(value, quote=True)


def _project_root() -> Path:
    default_root = Path(__file__).resolve().parents[5]
    return Path(os.environ.get("FLOWER_PROJECT_ROOT", default_root)).resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
