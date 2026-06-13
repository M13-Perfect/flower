from __future__ import annotations

import base64
import importlib
import json
import logging
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from app.domain import DomainError


SUPPORTED_UNITS = {"px", "mm", "in"}
INSUNITS = {"px": 0, "in": 1, "mm": 4}
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
UNSUPPORTED_SVG_TAGS = {
    "clipPath",
    "defs",
    "filter",
    "image",
    "linearGradient",
    "mask",
    "pattern",
    "radialGradient",
    "style",
    "symbol",
    "text",
    "use",
}
PATH_TOKEN_RE = re.compile(
    r"[MmLlHhVvCcQqZz]|[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?"
)
TRANSFORM_RE = re.compile(r"([A-Za-z]+)\(([^)]*)\)")


@dataclass(frozen=True)
class DxfWarning:
    code: str
    message: str
    layer_id: str | None = None

    def to_dict(self) -> dict[str, str]:
        result = {"code": self.code, "message": self.message}
        if self.layer_id is not None:
            result["layerId"] = self.layer_id
        return result


@dataclass(frozen=True)
class DxfExportResult:
    file_name: str
    mime_type: str
    content_base64: str
    metadata: dict[str, str]
    warnings: tuple[DxfWarning, ...]


@dataclass(frozen=True)
class Matrix:
    a: float = 1
    b: float = 0
    c: float = 0
    d: float = 1
    e: float = 0
    f: float = 0


@dataclass
class PathShape:
    layer_id: str
    points: list[tuple[float, float]]
    closed: bool = False


@dataclass
class ExportContext:
    document: dict[str, Any]
    target_units: str
    exported_at: str
    warnings: list[DxfWarning] = field(default_factory=list)


def export_dxf(
    document: dict[str, Any],
    *,
    units: str | None = None,
    exported_at: str | None = None,
) -> DxfExportResult:
    _validate_document(document)
    target_units = (
        units
        or _nested(document, "exportSettings", "dxf", "units")
        or ("mm" if _physical_size_mm(document) is not None else None)
        or document["canvas"]["unit"]
    )
    if target_units not in SUPPORTED_UNITS:
        raise DomainError(
            code="VALIDATION_ERROR",
            message="DXF units must be px, mm, or in.",
            details={"units": target_units},
            recoverable=True,
        )

    context = ExportContext(
        document=document,
        target_units=target_units,
        exported_at=exported_at or _utc_now(),
    )
    canvas_unit = str(document["canvas"]["unit"])
    unit_scale = _unit_scale(canvas_unit, target_units, context)
    # 画布是 Y 向下(SVG 约定),DXF 是 Y 向上;翻转 Y 让导入 CAD 后与 SVG 视觉一致
    # (否则整图上下镜像、花朵头朝下)。绕画布高度翻转:y' = (H - y) * scale。
    canvas_height = float(document["canvas"]["height"])
    root_matrix = compose(
        translate(0.0, canvas_height * unit_scale),
        scale(unit_scale, -unit_scale),
    )
    shapes = _collect_layer_shapes(document.get("layers", []), root_matrix, context)
    if not any(shape.points for shape in shapes):
        raise DomainError(
            code="DXF_NO_GEOMETRY",
            message="DXF export did not produce any path geometry.",
            details={},
            recoverable=True,
        )

    metadata = _metadata(document, context.exported_at)
    dxf_text = _write_dxf(shapes, context, metadata)
    return DxfExportResult(
        file_name=(
            f"{_file_part(metadata['templateId'])}_"
            f"{_file_part(metadata['orderId'] or 'no-order')}_"
            f"{_file_part(metadata['exportedAt'])}.dxf"
        ),
        mime_type="application/dxf",
        content_base64=base64.b64encode(dxf_text.encode("utf-8")).decode("ascii"),
        metadata=metadata,
        warnings=tuple(context.warnings),
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
    if not isinstance(document.get("layers"), list):
        raise DomainError(
            code="VALIDATION_ERROR",
            message="Layer document must include layers.",
            details={"field": "layers"},
            recoverable=True,
        )
    canvas = document.get("canvas")
    if not isinstance(canvas, dict) or canvas.get("unit") not in SUPPORTED_UNITS:
        raise DomainError(
            code="VALIDATION_ERROR",
            message="Layer document canvas unit must be px, mm, or in.",
            details={"field": "canvas.unit"},
            recoverable=True,
        )
    if _nested(document, "exportSettings", "dxf", "textMode") != "paths":
        raise DomainError(
            code="VALIDATION_ERROR",
            message="DXF textMode must be paths.",
            details={"field": "exportSettings.dxf.textMode"},
            recoverable=True,
        )


def _collect_layer_shapes(
    layers: list[dict[str, Any]],
    parent_matrix: Matrix,
    context: ExportContext,
) -> list[PathShape]:
    result: list[PathShape] = []
    for layer in sorted(layers, key=lambda item: float(item.get("zIndex", 0))):
        if not _is_exportable(layer):
            continue
        matrix = compose(parent_matrix, layer_matrix(layer))
        layer_type = layer.get("type")
        if layer_type == "group":
            children = layer.get("children")
            if not isinstance(children, list):
                raise _unsupported_layer(layer, "Group layer children must be an array.")
            result.extend(_collect_layer_shapes(children, matrix, context))
        elif layer_type == "path":
            result.extend(
                _parse_path_shapes(
                    str(layer.get("pathData", "")),
                    matrix,
                    str(layer.get("id", "path")),
                )
            )
        elif layer_type == "svg":
            result.extend(_svg_layer_shapes(layer, matrix, context))
        elif layer_type == "text":
            result.extend(_text_layer_shapes(layer, matrix, context))
        else:
            raise _unsupported_layer(
                layer,
                f"DXF export does not support layer type {layer_type!r}.",
            )
    return result


def _is_exportable(layer: dict[str, Any]) -> bool:
    if layer.get("visible") is False or layer.get("exportable") is not True:
        return False
    markers = [str(layer.get("name", "")), *(str(tag) for tag in layer.get("tags", []))]
    return not any(marker.strip().casefold() in HELPER_LAYER_MARKERS for marker in markers)


def _unsupported_layer(layer: dict[str, Any], message: str) -> DomainError:
    return DomainError(
        code="EXPORT_UNSUPPORTED_LAYER",
        message=message,
        details={"layerId": layer.get("id"), "layerType": layer.get("type")},
        recoverable=True,
    )


def _svg_layer_shapes(
    layer: dict[str, Any],
    matrix: Matrix,
    context: ExportContext,
) -> list[PathShape]:
    svg_text = layer.get("inlineSvg")
    if not svg_text:
        svg_text = _read_svg_asset(layer)
    try:
        root = ElementTree.fromstring(str(svg_text))
    except ElementTree.ParseError as exc:
        raise DomainError(
            code="SVG_PARSE_FAILED",
            message="SVG asset could not be parsed for DXF export.",
            details={"layerId": layer.get("id")},
            recoverable=True,
        ) from exc

    view_box = _svg_view_box(root, layer)
    if view_box[2] <= 0 or view_box[3] <= 0:
        raise DomainError(
            code="SVG_PARSE_FAILED",
            message="SVG viewBox must have positive width and height.",
            details={"layerId": layer.get("id")},
            recoverable=True,
        )
    x_scale = float(layer.get("width", view_box[2])) / view_box[2]
    y_scale = float(layer.get("height", view_box[3])) / view_box[3]
    viewport_matrix = compose(scale(x_scale, y_scale), translate(-view_box[0], -view_box[1]))
    return _svg_element_shapes(
        root,
        compose(matrix, viewport_matrix),
        str(layer.get("id", "svg")),
        context,
    )


def _read_svg_asset(layer: dict[str, Any]) -> str:
    asset_ref = layer.get("assetRef")
    if not isinstance(asset_ref, dict) or not asset_ref.get("path"):
        raise DomainError(
            code="ASSET_NOT_FOUND",
            message="SVG layer must include inlineSvg or assetRef.path for DXF export.",
            details={"layerId": layer.get("id")},
            recoverable=True,
        )
    path = _safe_project_path(str(asset_ref["path"]))
    if path.suffix.casefold() != ".svg" or not path.is_file():
        raise DomainError(
            code="ASSET_NOT_FOUND",
            message="SVG asset file was not found.",
            details={"layerId": layer.get("id"), "path": asset_ref["path"]},
            recoverable=True,
        )
    return path.read_text(encoding="utf-8")


def _svg_element_shapes(
    element: ElementTree.Element,
    matrix: Matrix,
    layer_id: str,
    context: ExportContext,
) -> list[PathShape]:
    tag = _local_name(element.tag)
    element_matrix = compose(matrix, _svg_transform(element.get("transform"), layer_id, context))
    shapes: list[PathShape] = []

    if tag in UNSUPPORTED_SVG_TAGS:
        context.warnings.append(
            DxfWarning(
                code="SVG_UNSUPPORTED_FEATURE",
                message=f"Unsupported SVG element <{tag}> was ignored during DXF export.",
                layer_id=layer_id,
            )
        )
        return shapes

    fill = element.get("fill", "")
    if "url(" in fill:
        context.warnings.append(
            DxfWarning(
                code="SVG_UNSUPPORTED_FEATURE",
                message="SVG paint servers such as gradients are not preserved in DXF.",
                layer_id=layer_id,
            )
        )

    if tag == "path":
        shapes.extend(_parse_path_shapes(str(element.get("d", "")), element_matrix, layer_id))
    elif tag not in {"g", "svg"}:
        context.warnings.append(
            DxfWarning(
                code="SVG_UNSUPPORTED_FEATURE",
                message=f"Unsupported SVG element <{tag}> was ignored during DXF export.",
                layer_id=layer_id,
            )
        )

    for child in list(element):
        shapes.extend(_svg_element_shapes(child, element_matrix, layer_id, context))
    return shapes


def _text_layer_shapes(
    layer: dict[str, Any],
    matrix: Matrix,
    context: ExportContext,
) -> list[PathShape]:
    font_path = _resolve_font_path(layer, context)
    try:
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        raise DomainError(
            code="FONT_LOAD_FAILED",
            message="fontTools is required to convert text to paths for DXF export.",
            details={"layerId": layer.get("id")},
            recoverable=False,
        ) from exc

    try:
        font = TTFont(str(font_path))
    except Exception as exc:
        raise DomainError(
            code="FONT_LOAD_FAILED",
            message="Font could not be loaded for DXF text path export.",
            details={"layerId": layer.get("id"), "path": _relative_project_path(font_path)},
            recoverable=True,
        ) from exc

    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap() or {}
    hmtx: dict[str, Any] = font["hmtx"].metrics if "hmtx" in font else {}
    units_per_em = float(font["head"].unitsPerEm if "head" in font else 1000)
    raw_style = layer.get("style")
    style: dict[str, Any] = raw_style if isinstance(raw_style, dict) else {}
    font_size = _positive_float(style.get("fontSize"), 1)
    line_height = _positive_float(style.get("lineHeight"), 1)
    letter_spacing = float(style.get("letterSpacing") or 0)
    text = _text_with_glyph_overrides(layer)
    lines = re.split(r"\r\n|\n|\r", text)
    shapes: list[PathShape] = []

    for line_index, line in enumerate(lines):
        cursor = _aligned_text_offset(
            line,
            style,
            layer,
            cmap,
            hmtx,
            units_per_em,
            font_size,
            letter_spacing,
        )
        baseline_y = line_index * font_size * line_height
        for char in line:
            codepoint = ord(char)
            glyph_name = cmap.get(codepoint)
            if glyph_name is None or glyph_name not in glyph_set:
                raise DomainError(
                    code="GLYPH_MISSING",
                    message="Font does not contain a required glyph for DXF text path export.",
                    details={"layerId": layer.get("id"), "codepoint": f"U+{codepoint:04X}"},
                    recoverable=True,
                )
            glyph_shapes = _glyph_shapes(
                glyph_set[glyph_name],
                glyph_name,
                cursor,
                baseline_y,
                font_size / units_per_em,
                matrix,
                str(layer.get("id", "text")),
            )
            shapes.extend(glyph_shapes)
            advance = float((hmtx.get(glyph_name) or (units_per_em, 0))[0])
            cursor += advance * font_size / units_per_em + letter_spacing
    return shapes


def _resolve_font_path(layer: dict[str, Any], context: ExportContext) -> Path:
    raw_font_ref = layer.get("fontRef")
    font_ref: dict[str, Any] = raw_font_ref if isinstance(raw_font_ref, dict) else {}
    asset_id = str(font_ref.get("assetId") or "")
    candidates: list[Path] = []
    option_no = _font_option_no(font_ref)
    if option_no is not None:
        candidates.extend(_business_font_candidates(option_no))
    if asset_id:
        safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "-", asset_id).strip("-")
        for suffix in (".ttf", ".otf"):
            candidates.append(_project_root() / "assets" / "fonts" / f"{safe_id}{suffix}")
    family = str(font_ref.get("family") or "")
    if family:
        safe_family = re.sub(r"[^a-zA-Z0-9._-]+", "-", family).strip("-")
        for suffix in (".ttf", ".otf"):
            candidates.append(_project_root() / "assets" / "fonts" / f"{safe_family}{suffix}")
            candidates.append(
                _project_root() / "assets" / "fonts" / f"{safe_family.casefold()}{suffix}"
            )
    candidates.append(_project_root() / "Birthmonth_font.ttf")

    for candidate in candidates:
        if candidate.is_file() and _is_project_path(candidate):
            return candidate

    discovered = sorted((_project_root() / "assets" / "fonts").glob("*.ttf"))
    if discovered:
        context.warnings.append(
            DxfWarning(
                code="FONT_FALLBACK_USED",
                message="Requested font was not found; the first discovered local font was used.",
                layer_id=str(layer.get("id", "text")),
            )
        )
        return discovered[0]

    raise DomainError(
        code="FONT_LOAD_FAILED",
        message="No usable font file was found for DXF text path export.",
        details={"layerId": layer.get("id")},
        recoverable=True,
    )


def _font_option_no(font_ref: dict[str, Any]) -> int | None:
    raw_values = (
        font_ref.get("optionNo"),
        font_ref.get("option_no"),
        font_ref.get("assetId"),
        font_ref.get("family"),
    )
    for raw in raw_values:
        match = re.search(r"\bfont[-\s_]*([1-9][0-9]?)\b", str(raw), flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        if isinstance(raw, int):
            return raw
    return None


def _business_font_candidates(option_no: int) -> list[Path]:
    font_dir = _project_root() / "BirthMonth flowers"
    if not font_dir.is_dir():
        return []
    fonts = [
        path
        for path in font_dir.iterdir()
        if path.is_file() and path.suffix.casefold() in {".ttf", ".otf"}
    ]
    groups = (("malovelyscript", 1), ("adorabella", 3))
    for group_key, start_index in groups:
        group = sorted(
            (font for font in fonts if _compact_name(font.stem) == group_key),
            key=lambda font: (_file_size(font), font.suffix.casefold(), font.name.casefold()),
        )
        offset = option_no - start_index
        if 0 <= offset < len(group[:2]):
            return [group[offset]]
    return []


def _glyph_shapes(
    glyph: Any,
    glyph_name: str,
    cursor_x: float,
    baseline_y: float,
    scale_factor: float,
    matrix: Matrix,
    layer_id: str,
) -> list[PathShape]:
    from fontTools.pens.recordingPen import RecordingPen

    pen = RecordingPen()
    glyph.draw(pen)
    shapes: list[PathShape] = []
    points: list[tuple[float, float]] = []
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    # 字形在字体单位空间扁平化,经 scale_factor 再经 matrix 变换到 mm。
    tol = _local_tolerance(matrix, scale_factor)

    def convert(point: tuple[float, float]) -> tuple[float, float]:
        x = cursor_x + point[0] * scale_factor
        y = baseline_y - point[1] * scale_factor
        return apply_matrix(matrix, (x, y))

    for command, args in pen.value:
        if command == "moveTo":
            if points:
                shapes.append(PathShape(layer_id=layer_id, points=points, closed=False))
            current = args[0]
            start = current
            points = [convert(current)]
        elif command == "lineTo":
            current = args[0]
            points.append(convert(current))
        elif command == "qCurveTo":
            raw_points = [point for point in args if point is not None]
            if raw_points:
                control = raw_points[0]
                end = raw_points[-1]
                for point in _flatten_quadratic(current, control, end, tol):
                    points.append(convert(point))
                current = end
        elif command == "curveTo":
            control_1, control_2, end = args
            for point in _flatten_cubic(current, control_1, control_2, end, tol):
                points.append(convert(point))
            current = end
        elif command == "closePath":
            if points and points[0] != points[-1]:
                points.append(convert(start))
            if points:
                shapes.append(PathShape(layer_id=layer_id, points=points, closed=True))
            points = []
        elif command == "endPath":
            if points:
                shapes.append(PathShape(layer_id=layer_id, points=points, closed=False))
            points = []
        else:
            raise DomainError(
                code="GLYPH_UNSUPPORTED",
                message="Font glyph contains unsupported outline commands.",
                details={"layerId": layer_id, "glyphName": glyph_name, "command": command},
                recoverable=True,
            )
    if points:
        shapes.append(PathShape(layer_id=layer_id, points=points, closed=False))
    return shapes


def _parse_path_shapes(path_data: str, matrix: Matrix, layer_id: str) -> list[PathShape]:
    tokens = PATH_TOKEN_RE.findall(path_data)
    shapes: list[PathShape] = []
    points: list[tuple[float, float]] = []
    cursor = (0.0, 0.0)
    start = (0.0, 0.0)
    index = 0
    command = ""

    def has_number() -> bool:
        return index < len(tokens) and not re.fullmatch(r"[A-Za-z]", tokens[index])

    def number() -> float:
        nonlocal index
        if index >= len(tokens) or re.fullmatch(r"[A-Za-z]", tokens[index]):
            raise DomainError(
                code="SVG_PARSE_FAILED",
                message="SVG path data ended unexpectedly.",
                details={"layerId": layer_id},
                recoverable=True,
            )
        value = float(tokens[index])
        index += 1
        return value

    tol = _local_tolerance(matrix)

    def add_point(point: tuple[float, float]) -> None:
        points.append(apply_matrix(matrix, point))

    while index < len(tokens):
        if re.fullmatch(r"[A-Za-z]", tokens[index]):
            command = tokens[index]
            index += 1
        if not command:
            break
        absolute = command.isupper()
        cmd = command.upper()

        if cmd == "M":
            first = True
            while has_number():
                x, y = number(), number()
                cursor = (x, y) if absolute else (cursor[0] + x, cursor[1] + y)
                if first:
                    if points:
                        shapes.append(PathShape(layer_id=layer_id, points=points, closed=False))
                    points = []
                    start = cursor
                    add_point(cursor)
                    first = False
                else:
                    add_point(cursor)
            command = "L" if absolute else "l"
        elif cmd == "L":
            while has_number():
                x, y = number(), number()
                cursor = (x, y) if absolute else (cursor[0] + x, cursor[1] + y)
                add_point(cursor)
        elif cmd == "H":
            while has_number():
                x = number()
                cursor = (x, cursor[1]) if absolute else (cursor[0] + x, cursor[1])
                add_point(cursor)
        elif cmd == "V":
            while has_number():
                y = number()
                cursor = (cursor[0], y) if absolute else (cursor[0], cursor[1] + y)
                add_point(cursor)
        elif cmd == "Q":
            while has_number():
                c = _point(number(), number(), cursor, absolute)
                end = _point(number(), number(), cursor, absolute)
                for point in _flatten_quadratic(cursor, c, end, tol):
                    add_point(point)
                cursor = end
        elif cmd == "C":
            while has_number():
                c1 = _point(number(), number(), cursor, absolute)
                c2 = _point(number(), number(), cursor, absolute)
                end = _point(number(), number(), cursor, absolute)
                for point in _flatten_cubic(cursor, c1, c2, end, tol):
                    add_point(point)
                cursor = end
        elif cmd == "Z":
            if points and points[0] != apply_matrix(matrix, start):
                add_point(start)
            if points:
                shapes.append(PathShape(layer_id=layer_id, points=points, closed=True))
            points = []
            cursor = start
            command = ""
        else:
            raise DomainError(
                code="SVG_UNSUPPORTED_PATH_COMMAND",
                message=f"SVG path command {command!r} is not supported for DXF export.",
                details={"layerId": layer_id, "command": command},
                recoverable=True,
            )
    if points:
        shapes.append(PathShape(layer_id=layer_id, points=points, closed=False))
    return [shape for shape in shapes if len(shape.points) >= 2]


def _point(x: float, y: float, cursor: tuple[float, float], absolute: bool) -> tuple[float, float]:
    return (x, y) if absolute else (cursor[0] + x, cursor[1] + y)


# 自适应扁平化:近直的曲线只产少量点,弯曲处自动加密;容差以最终 mm 计,
# 0.05mm 远低于激光精度,既保形又避免旧固定步数导致的过密(单条线 5000+ 点)。
_FLATTEN_TOLERANCE_MM = 0.05
_FLATTEN_MAX_DEPTH = 20


def _matrix_scale(matrix: Matrix) -> float:
    sx = math.hypot(matrix.a, matrix.b)
    sy = math.hypot(matrix.c, matrix.d)
    average = (sx + sy) / 2
    return average if average > 1e-9 else 1.0


def _local_tolerance(matrix: Matrix, extra_scale: float = 1.0) -> float:
    """把 mm 容差换算到曲线自身坐标系:effective = matrix 缩放 × 额外缩放。"""
    effective = _matrix_scale(matrix) * (extra_scale or 1.0)
    if effective <= 1e-9:
        return _FLATTEN_TOLERANCE_MM
    return _FLATTEN_TOLERANCE_MM / effective


def _midpoint(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def _distance_to_line(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    segment_sq = dx * dx + dy * dy
    if segment_sq <= 1e-12:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    return abs((point[0] - start[0]) * dy - (point[1] - start[1]) * dx) / math.sqrt(segment_sq)


def _flatten_quadratic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    tol: float | None = None,
    steps: int = 12,
) -> list[tuple[float, float]]:
    if tol is None:  # 兼容无容差调用,退回固定步数
        return _flatten_quadratic_fixed(p0, p1, p2, steps)
    result: list[tuple[float, float]] = []
    _subdivide_quadratic(p0, p1, p2, tol, 0, result)
    return result


def _flatten_cubic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    tol: float | None = None,
    steps: int = 16,
) -> list[tuple[float, float]]:
    if tol is None:
        return _flatten_cubic_fixed(p0, p1, p2, p3, steps)
    result: list[tuple[float, float]] = []
    _subdivide_cubic(p0, p1, p2, p3, tol, 0, result)
    return result


def _subdivide_quadratic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    tol: float,
    depth: int,
    out: list[tuple[float, float]],
) -> None:
    if depth >= _FLATTEN_MAX_DEPTH or _distance_to_line(p1, p0, p2) <= tol:
        out.append(p2)
        return
    p01 = _midpoint(p0, p1)
    p12 = _midpoint(p1, p2)
    mid = _midpoint(p01, p12)
    _subdivide_quadratic(p0, p01, mid, tol, depth + 1, out)
    _subdivide_quadratic(mid, p12, p2, tol, depth + 1, out)


def _subdivide_cubic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    tol: float,
    depth: int,
    out: list[tuple[float, float]],
) -> None:
    flat = _distance_to_line(p1, p0, p3) <= tol and _distance_to_line(p2, p0, p3) <= tol
    if depth >= _FLATTEN_MAX_DEPTH or flat:
        out.append(p3)
        return
    p01 = _midpoint(p0, p1)
    p12 = _midpoint(p1, p2)
    p23 = _midpoint(p2, p3)
    p012 = _midpoint(p01, p12)
    p123 = _midpoint(p12, p23)
    mid = _midpoint(p012, p123)
    _subdivide_cubic(p0, p01, p012, mid, tol, depth + 1, out)
    _subdivide_cubic(mid, p123, p23, p3, tol, depth + 1, out)


def _flatten_quadratic_fixed(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    steps: int,
) -> list[tuple[float, float]]:
    result = []
    for index in range(1, steps + 1):
        t = index / steps
        mt = 1 - t
        result.append(
            (
                mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0],
                mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1],
            )
        )
    return result


def _flatten_cubic_fixed(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    steps: int,
) -> list[tuple[float, float]]:
    result = []
    for index in range(1, steps + 1):
        t = index / steps
        mt = 1 - t
        result.append(
            (
                mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0],
                mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1],
            )
        )
    return result


# 雕花与刻字是同一道激光工序,所有几何用统一颜色,激光软件视为一次操作。
_ENGRAVE_COLOR = 7  # ACI 7 = 黑/白中性色
# 输出 DXF R12(AC1009)+ POLYLINE:EzCad2 等激光软件对 R2000+ 的 LWPOLYLINE
# 支持不全,会导入成"可选中但改不动"的状态;R12+POLYLINE 才是原生可编辑曲线。
# R12 不支持 $INSUNITS/线宽,EzCad 本就按 mm 解析坐标,不影响尺寸。
_DXF_VERSION = "R12"


def _write_dxf(shapes: list[PathShape], context: ExportContext, metadata: dict[str, str]) -> str:
    ezdxf = _load_ezdxf()
    # 抑制 ezdxf 对 R12 不导出 $INSUNITS 的告警(EzCad 按 mm 解析坐标,无影响)。
    ezdxf_logger = logging.getLogger("ezdxf")
    previous_level = ezdxf_logger.level
    ezdxf_logger.setLevel(logging.ERROR)
    try:
        doc = ezdxf.new(dxfversion=_DXF_VERSION)
        doc.header["$INSUNITS"] = INSUNITS[context.target_units]
        _write_dxf_metadata(doc, metadata)
        modelspace = doc.modelspace()

        # 先把用到的图层登记进图层表(原先实体引用未声明的图层,依赖 CAD 自动建层)。
        declared: set[str] = set()
        for shape in shapes:
            layer_name = _dxf_layer_name(shape.layer_id)
            if layer_name not in declared:
                _ensure_layer(doc, layer_name)
                declared.add(layer_name)

        for shape in shapes:
            cleaned = _dedupe_points(shape.points)
            if len(cleaned) < 2:
                continue
            polyline = modelspace.add_polyline2d(
                cleaned,
                dxfattribs={"layer": _dxf_layer_name(shape.layer_id)},
            )
            if shape.closed and hasattr(polyline, "close"):
                polyline.close(True)

        stream = StringIO()
        doc.write(stream)
        return stream.getvalue()
    finally:
        ezdxf_logger.setLevel(previous_level)


def _ensure_layer(doc: Any, name: str) -> None:
    layers = getattr(doc, "layers", None)
    if layers is None or not hasattr(layers, "add"):
        return  # 测试替身可能不实现图层表;实体仍带 layer 属性
    try:
        if hasattr(layers, "has_entry") and layers.has_entry(name):
            return
        # R12 图层只支持颜色;统一色 7 即可表达"同一道工序"。
        layers.add(name=name, color=_ENGRAVE_COLOR)
    except Exception:
        return  # 重名或 API 差异不应阻断导出


def _write_dxf_metadata(doc: Any, metadata: dict[str, str]) -> None:
    rootdict = getattr(doc, "rootdict", None)
    if rootdict is None or not hasattr(rootdict, "add_xrecord"):
        return
    try:
        rootdict.add_xrecord(
            "FLOWER_EXPORT_METADATA",
            [(1, json.dumps(metadata, ensure_ascii=False))],
        )
    except Exception:
        return


def _load_ezdxf() -> Any:
    try:
        return importlib.import_module("ezdxf")
    except ImportError as exc:
        raise DomainError(
            code="DXF_DEPENDENCY_MISSING",
            message="ezdxf is required to generate DXF files.",
            details={"dependency": "ezdxf"},
            recoverable=False,
        ) from exc


def layer_matrix(layer: dict[str, Any]) -> Matrix:
    matrix = translate(float(layer.get("x", 0)), float(layer.get("y", 0)))
    rotation = float(layer.get("rotation", 0) or 0)
    if rotation:
        matrix = compose(matrix, rotate(rotation))
    matrix = compose(matrix, scale(float(layer.get("scaleX", 1)), float(layer.get("scaleY", 1))))
    return matrix


def _svg_transform(value: str | None, layer_id: str, context: ExportContext) -> Matrix:
    if not value:
        return Matrix()
    matrix = Matrix()
    for name, raw_args in TRANSFORM_RE.findall(value):
        args = [float(part) for part in re.split(r"[\s,]+", raw_args.strip()) if part]
        if name == "translate":
            x_offset = args[0] if args else 0
            y_offset = args[1] if len(args) > 1 else 0
            matrix = compose(matrix, translate(x_offset, y_offset))
        elif name == "scale":
            x_scale = args[0] if args else 1
            y_scale = args[1] if len(args) > 1 else x_scale
            matrix = compose(matrix, scale(x_scale, y_scale))
        elif name == "rotate":
            if len(args) >= 3:
                matrix = compose(matrix, translate(args[1], args[2]))
                matrix = compose(matrix, rotate(args[0]))
                matrix = compose(matrix, translate(-args[1], -args[2]))
            else:
                matrix = compose(matrix, rotate(args[0] if args else 0))
        elif name == "matrix" and len(args) == 6:
            matrix = compose(matrix, Matrix(*args))
        else:
            context.warnings.append(
                DxfWarning(
                    code="SVG_UNSUPPORTED_FEATURE",
                    message=f"Unsupported SVG transform {name!r} was ignored.",
                    layer_id=layer_id,
                )
            )
    return matrix


def translate(x: float, y: float) -> Matrix:
    return Matrix(e=x, f=y)


def scale(x: float, y: float) -> Matrix:
    return Matrix(a=x, d=y)


def rotate(degrees: float) -> Matrix:
    radians = math.radians(degrees)
    cos_value = math.cos(radians)
    sin_value = math.sin(radians)
    return Matrix(a=cos_value, b=sin_value, c=-sin_value, d=cos_value)


def compose(parent: Matrix, child: Matrix) -> Matrix:
    return Matrix(
        a=parent.a * child.a + parent.c * child.b,
        b=parent.b * child.a + parent.d * child.b,
        c=parent.a * child.c + parent.c * child.d,
        d=parent.b * child.c + parent.d * child.d,
        e=parent.a * child.e + parent.c * child.f + parent.e,
        f=parent.b * child.e + parent.d * child.f + parent.f,
    )


def apply_matrix(matrix: Matrix, point: tuple[float, float]) -> tuple[float, float]:
    return (
        matrix.a * point[0] + matrix.c * point[1] + matrix.e,
        matrix.b * point[0] + matrix.d * point[1] + matrix.f,
    )


def _svg_view_box(
    root: ElementTree.Element,
    layer: dict[str, Any],
) -> tuple[float, float, float, float]:
    raw = root.get("viewBox")
    if raw:
        parts = [float(part) for part in re.split(r"[\s,]+", raw.strip()) if part]
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


def _text_with_glyph_overrides(layer: dict[str, Any]) -> str:
    chars = list(str(layer.get("text") or ""))
    overrides = layer.get("glyphOverrides")
    if not isinstance(overrides, list):
        return "".join(chars)
    for override in sorted(
        overrides,
        key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0,
    ):
        if not isinstance(override, dict):
            continue
        index = override.get("index")
        if not isinstance(index, int) or index < 0 or index >= len(chars):
            continue
        original = (
            override.get("originalText")
            or override.get("base_char")
            or override.get("original_char")
        )
        if chars[index] != original:
            continue
        replacement = (
            override.get("replacement")
            or override.get("replacement_char")
            or override.get("char")
        )
        codepoint = override.get("codepoint")
        parsed_codepoint = _parse_codepoint(codepoint)
        if parsed_codepoint is not None and not _is_control_codepoint(parsed_codepoint):
            replacement = chr(parsed_codepoint)
        if (
            isinstance(replacement, str)
            and replacement
            and not _contains_unicode_control_character(replacement)
            and not _is_control_codepoint_string(codepoint)
        ):
            chars[index] = replacement
    return "".join(chars)


def _parse_codepoint(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(?:U\+|0x)?([0-9a-fA-F]{4,6})", value.strip())
    if not match:
        return None
    codepoint = int(match.group(1), 16)
    return codepoint if 0 <= codepoint <= 0x10FFFF else None


def _contains_unicode_control_character(value: str) -> bool:
    return any(_is_control_codepoint(ord(char)) for char in value)


def _is_control_codepoint_string(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    match = re.fullmatch(r"(?:U\+|0x)?([0-9a-fA-F]{4,6})", value.strip())
    return bool(match and _is_control_codepoint(int(match.group(1), 16)))


def _is_control_codepoint(codepoint: int) -> bool:
    return 0x0000 <= codepoint <= 0x001F or 0x007F <= codepoint <= 0x009F


def _aligned_text_offset(
    line: str,
    style: dict[str, Any],
    layer: dict[str, Any],
    cmap: dict[int, str],
    hmtx: dict[str, Any],
    units_per_em: float,
    font_size: float,
    letter_spacing: float,
) -> float:
    width = 0.0
    for char in line:
        glyph_name = cmap.get(ord(char))
        advance = float((hmtx.get(glyph_name) or (units_per_em, 0))[0]) if glyph_name else units_per_em
        width += advance * font_size / units_per_em + letter_spacing
    if line:
        width -= letter_spacing
    align = style.get("align")
    if align == "center":
        return (float(layer.get("width", 0)) - width) / 2
    if align == "right":
        return float(layer.get("width", 0)) - width
    return 0.0


def _positive_float(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


def _unit_scale(source: str, target: str, context: ExportContext) -> float:
    if source == target:
        return 1.0
    if source == "mm" and target == "in":
        return 1 / 25.4
    if source == "in" and target == "mm":
        return 25.4
    physical_size = _physical_size_mm(context.document)
    if source == "px" and physical_size is not None:
        canvas = context.document["canvas"]
        canvas_width = float(canvas["width"])
        scale_mm = physical_size[0] / canvas_width
        if target == "mm":
            return scale_mm
        if target == "in":
            return scale_mm / 25.4
    context.warnings.append(
        DxfWarning(
            code="UNIT_SCALE_ASSUMED",
            message=(
                "Pixel units have no physical DXF scale; coordinate values were left "
                "unchanged."
            ),
        )
    )
    return 1.0


def _physical_size_mm(document: dict[str, Any]) -> tuple[float, float] | None:
    physical = _nested(document, "exportSettings", "physical")
    if not isinstance(physical, dict) or physical.get("widthMm") is None:
        return None
    width = _positive_float(physical.get("widthMm"), 0)
    canvas = document.get("canvas")
    if not isinstance(canvas, dict):
        return None
    canvas_width = _positive_float(canvas.get("width"), 0)
    canvas_height = _positive_float(canvas.get("height"), 0)
    if width <= 0 or canvas_width <= 0 or canvas_height <= 0:
        raise DomainError(
            code="VALIDATION_ERROR",
            message="Physical export width and canvas dimensions must be positive.",
            details={"field": "exportSettings.physical.widthMm"},
            recoverable=True,
        )
    height = _positive_float(physical.get("heightMm"), 0)
    if height <= 0:
        height = width * canvas_height / canvas_width
    return width, height


def _dedupe_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for point in points:
        rounded = (round(point[0], 6), round(point[1], 6))
        if not result or rounded != result[-1]:
            result.append(rounded)
    return result


def _dxf_layer_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_$-]+", "_", value).strip("_")[:255] or "layer"


def _metadata(document: dict[str, Any], exported_at: str) -> dict[str, str]:
    raw_metadata = document.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    return {
        "templateId": str(metadata.get("templateId") or ""),
        "orderId": str(metadata.get("orderId") or ""),
        "exportedAt": exported_at,
        "appVersion": str(metadata.get("appVersion") or ""),
    }


def _file_part(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-") or "export"


def _nested(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _safe_project_path(relative_path: str) -> Path:
    if Path(relative_path).is_absolute():
        raise DomainError(
            code="PATH_TRAVERSAL_BLOCKED",
            message="Asset path must be relative to the project root.",
            details={"path": relative_path},
            recoverable=True,
        )
    path = (_project_root() / relative_path).resolve()
    if not _is_project_path(path):
        raise DomainError(
            code="PATH_TRAVERSAL_BLOCKED",
            message="Asset path is outside the project root.",
            details={"path": relative_path},
            recoverable=True,
        )
    return path


def _is_project_path(path: Path) -> bool:
    root = _project_root().resolve()
    resolved = path.resolve()
    return resolved == root or root in resolved.parents


def _relative_project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(_project_root().resolve()).as_posix()
    except ValueError:
        return path.name


def _project_root() -> Path:
    default_root = Path(__file__).resolve().parents[5]
    return Path(os.environ.get("FLOWER_PROJECT_ROOT", default_root)).resolve()


def _compact_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
