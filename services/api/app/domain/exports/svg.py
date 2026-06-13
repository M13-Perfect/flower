from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import re
from typing import Any, Literal
from xml.etree import ElementTree

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
    # 绑定物理尺寸:width/height 用 mm、viewBox 保留像素坐标系,二者一起规定真实大小。
    # 缺物理配置时退回无单位像素(旧行为),避免破坏非生产用途。
    physical = _physical_size_mm(document)
    if physical is not None:
        width_attr = f"{_number(physical[0])}mm"
        height_attr = f"{_number(physical[1])}mm"
    else:
        width_attr = str(width)
        height_attr = str(height)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_attr}" '
            f'height="{height_attr}" viewBox="0 0 {width} {height}">'
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
    from app.domain.exports.dxf import (
        ExportContext,
        Matrix,
        _aligned_text_offset,
        _glyph_shapes,
        _resolve_font_path,
        _text_with_glyph_overrides as dxf_text_with_glyph_overrides,
    )

    try:
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        raise DomainError(
            code="FONT_LOAD_FAILED",
            message="fontTools is required to convert text to paths for SVG export.",
            details={"layerId": layer.get("id")},
            recoverable=False,
        ) from exc

    raw_style = layer.get("style")
    style: dict[str, Any] = raw_style if isinstance(raw_style, dict) else {}
    context = ExportContext(document={}, target_units="px", exported_at="")
    font_path = _resolve_font_path(layer, context)
    try:
        font = TTFont(str(font_path))
    except Exception as exc:
        raise DomainError(
            code="FONT_LOAD_FAILED",
            message="Font could not be loaded for SVG text path export.",
            details={"layerId": layer.get("id")},
            recoverable=True,
        ) from exc

    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap() or {}
    hmtx: dict[str, Any] = font["hmtx"].metrics if "hmtx" in font else {}
    units_per_em = float(font["head"].unitsPerEm if "head" in font else 1000)
    font_size = _number(style.get("fontSize") or 16)
    font_size_value = float(font_size)
    line_height = float(style.get("lineHeight") or 1)
    letter_spacing = float(style.get("letterSpacing") or 0)
    fill = str(style.get("fill") or "#000000")
    stroke = str(style.get("stroke") or "")
    stroke_width = float(style.get("strokeWidth") or 0)
    text = dxf_text_with_glyph_overrides(layer)
    paths: list[str] = []

    for line_index, line in enumerate(re.split(r"\r\n|\n|\r", text)):
        cursor = _aligned_text_offset(
            line,
            style,
            layer,
            cmap,
            hmtx,
            units_per_em,
            font_size_value,
            letter_spacing,
        )
        baseline_y = line_index * font_size_value * line_height
        for char in line:
            codepoint = ord(char)
            glyph_name = cmap.get(codepoint)
            if glyph_name is None or glyph_name not in glyph_set:
                raise DomainError(
                    code="GLYPH_MISSING",
                    message="Font does not contain a required glyph for SVG text path export.",
                    details={"layerId": layer.get("id"), "codepoint": f"U+{codepoint:04X}"},
                    recoverable=True,
                )
            for shape in _glyph_shapes(
                glyph_set[glyph_name],
                glyph_name,
                cursor,
                baseline_y,
                font_size_value / units_per_em,
                Matrix(),
                str(layer.get("id", "text")),
            ):
                path_data = _shape_path_data(shape.points, shape.closed)
                if not path_data:
                    continue
                attrs = [
                    f'd="{_attr(path_data)}"',
                    f'fill="{_attr(fill)}"',
                    f'data-layer-id="{_attr(str(layer.get("id") or ""))}"',
                ]
                if stroke and stroke_width > 0:
                    attrs.append(f'stroke="{_attr(stroke)}"')
                    attrs.append(f'stroke-width="{_number(stroke_width)}"')
                paths.append(f'<path {" ".join(attrs)}/>')
            advance = float((hmtx.get(glyph_name) or (units_per_em, 0))[0])
            cursor += advance * font_size_value / units_per_em + letter_spacing
    return "\n".join(paths)


def _render_svg_layer(layer: dict[str, Any]) -> str:
    inline_svg = layer.get("inlineSvg")
    if not inline_svg:
        asset_ref = layer.get("assetRef")
        path = asset_ref.get("path") if isinstance(asset_ref, dict) else ""
        if path:
            inline_svg = _read_svg_asset(str(path), layer)
    if not inline_svg:
        raise DomainError(
            code="ASSET_NOT_FOUND",
            message="SVG layer must include inlineSvg or assetRef.path for SVG export.",
            details={"layerId": layer.get("id")},
            recoverable=True,
        )
    children, view_box = _parse_inline_svg(str(inline_svg), layer)
    x_min, y_min, source_width, source_height = view_box
    x_scale = float(layer.get("width", source_width) or source_width) / source_width
    y_scale = float(layer.get("height", source_height) or source_height) / source_height
    view_box_text = " ".join(_number(value) for value in view_box)
    transform = (
        f"scale({_number(x_scale)} {_number(y_scale)}) "
        f"translate({_number(-x_min)} {_number(-y_min)})"
    )
    return "\n".join(
        [
            (
                f'<g data-layer-id="{_attr(str(layer.get("id") or ""))}" '
                f'data-source-viewBox="{_attr(view_box_text)}" '
                f'transform="{_attr(transform)}">'
            ),
            *_indent(children, "  "),
            "</g>",
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


def _parse_inline_svg(svg: str, layer: dict[str, Any]) -> tuple[list[str], tuple[float, float, float, float]]:
    sanitized = _strip_unsafe_svg_markup(svg).strip()
    try:
        root = ElementTree.fromstring(sanitized)
    except ElementTree.ParseError as exc:
        raise DomainError(
            code="SVG_PARSE_FAILED",
            message="SVG asset could not be parsed for SVG export.",
            details={"layerId": layer.get("id")},
            recoverable=True,
        ) from exc
    if _local_name(root.tag) != "svg":
        raise DomainError(
            code="SVG_PARSE_FAILED",
            message="SVG asset root element must be <svg>.",
            details={"layerId": layer.get("id")},
            recoverable=True,
        )
    view_box = _svg_view_box(root, layer)
    if view_box[2] <= 0 or view_box[3] <= 0:
        raise DomainError(
            code="SVG_PARSE_FAILED",
            message="SVG viewBox must have positive width and height.",
            details={"layerId": layer.get("id")},
            recoverable=True,
        )
    _sanitize_svg_tree(root)
    children = [
        ElementTree.tostring(deepcopy(child), encoding="unicode", short_empty_elements=True)
        for child in list(root)
    ]
    return children, view_box


def _strip_unsafe_svg_markup(svg: str) -> str:
    without_xml = re.sub(r"^\s*<\?xml[^>]*\?>", "", svg, flags=re.IGNORECASE)
    return re.sub(
        r"<!DOCTYPE[^>]*(?:\[[\s\S]*?\]\s*)?>",
        "",
        without_xml,
        flags=re.IGNORECASE,
    )


def _svg_view_box(
    root: ElementTree.Element,
    layer: dict[str, Any],
) -> tuple[float, float, float, float]:
    raw = root.get("viewBox")
    if raw:
        try:
            parts = [float(part) for part in re.split(r"[\s,]+", raw.strip()) if part]
        except ValueError as exc:
            raise DomainError(
                code="SVG_PARSE_FAILED",
                message="SVG viewBox contains invalid numbers.",
                details={"layerId": layer.get("id")},
                recoverable=True,
            ) from exc
        if len(parts) == 4:
            return parts[0], parts[1], parts[2], parts[3]
    raw_view_box = layer.get("viewBox")
    view_box: dict[str, Any] = raw_view_box if isinstance(raw_view_box, dict) else {}
    return (
        float(view_box.get("x", 0)),
        float(view_box.get("y", 0)),
        float(view_box.get("width", layer.get("width", 1))),
        float(view_box.get("height", layer.get("height", 1))),
    )


def _sanitize_svg_tree(element: ElementTree.Element) -> None:
    element.tag = _local_name(element.tag)
    for attr_name in list(element.attrib):
        clean_name = _local_name(attr_name)
        if clean_name.casefold().startswith("on"):
            del element.attrib[attr_name]
            continue
        if clean_name != attr_name:
            element.attrib[clean_name] = element.attrib.pop(attr_name)
    for child in list(element):
        if _local_name(child.tag) == "script":
            element.remove(child)
            continue
        _sanitize_svg_tree(child)


def _shape_path_data(points: list[tuple[float, float]], closed: bool) -> str:
    if len(points) < 2:
        return ""
    commands = [f"M {_number(points[0][0])} {_number(points[0][1])}"]
    commands.extend(f"L {_number(x)} {_number(y)}" for x, y in points[1:])
    if closed:
        commands.append("Z")
    return " ".join(commands)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


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


def _physical_size_mm(document: dict[str, Any]) -> tuple[float, float] | None:
    """宽松读取 exportSettings.physical;缺失或非法时返回 None(SVG 退回像素)。"""
    export_settings = document.get("exportSettings")
    if not isinstance(export_settings, dict):
        return None
    physical = export_settings.get("physical")
    if not isinstance(physical, dict):
        return None
    width = _positive_float(physical.get("widthMm"))
    if width is None:
        return None
    canvas = document.get("canvas")
    if not isinstance(canvas, dict):
        return None
    canvas_width = _positive_float(canvas.get("width"))
    canvas_height = _positive_float(canvas.get("height"))
    if canvas_width is None or canvas_height is None:
        return None
    height = _positive_float(physical.get("heightMm"))
    if height is None:
        height = width * canvas_height / canvas_width
    return width, height


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
