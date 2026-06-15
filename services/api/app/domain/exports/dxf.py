from __future__ import annotations

import base64
import importlib
import json
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
    # 几何收集阶段已构建 ezdxf.path.Path,提前确认 ezdxf 可用,缺失时报友好错误。
    _load_ezdxf()
    paths = _collect_layer_paths(document.get("layers", []), root_matrix, context)
    if not any(_path_has_geometry(item.path) for item in paths):
        raise DomainError(
            code="DXF_NO_GEOMETRY",
            message="DXF export did not produce any path geometry.",
            details={},
            recoverable=True,
        )

    metadata = _metadata(document, context.exported_at)
    dxf_text = _write_dxf(paths, context, metadata)
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


@dataclass
class _LayerPath:
    """一条导出几何;fill 标记文字闭合字形(信息性)。所有路径都按可编辑 SPLINE/POLYLINE 输出,
    DXF 内不做填充——实心由 EzCad 导入后原生「填充」完成。"""

    path: Any
    fill: bool = False


def _collect_layer_paths(
    layers: list[dict[str, Any]],
    parent_matrix: Matrix,
    context: ExportContext,
) -> list[_LayerPath]:
    """收集所有可导出图层的几何为带"是否填充"标记的 Path 列表(已变换到 DXF 坐标系)。"""
    result: list[_LayerPath] = []
    for layer in sorted(layers, key=lambda item: float(item.get("zIndex", 0))):
        if not _is_exportable(layer):
            continue
        matrix = compose(parent_matrix, layer_matrix(layer))
        layer_type = layer.get("type")
        if layer_type == "group":
            children = layer.get("children")
            if not isinstance(children, list):
                raise _unsupported_layer(layer, "Group layer children must be an array.")
            result.extend(_collect_layer_paths(children, matrix, context))
        elif layer_type == "path":
            result.extend(
                _LayerPath(path)
                for path in _parse_path_objects(
                    str(layer.get("pathData", "")),
                    matrix,
                    str(layer.get("id", "path")),
                )
            )
        elif layer_type == "svg":
            result.extend(_LayerPath(path) for path in _svg_layer_paths(layer, matrix, context))
        elif layer_type == "text":
            # 文字字形输出闭合 SPLINE/POLYLINE 轮廓;DXF 内不填充,实心由 EzCad 导入后原生填充完成。
            result.extend(
                _LayerPath(path, fill=True)
                for path in _text_layer_paths(layer, matrix, context)
            )
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


def _svg_render_context(
    layer: dict[str, Any],
    matrix: Matrix,
    context: ExportContext,
) -> tuple[ElementTree.Element, Matrix, str]:
    """解析 SVG 图层、计算 viewBox→图层尺寸的视口矩阵,返回 (根, 基矩阵, 图层id)。"""
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
    return root, compose(matrix, viewport_matrix), str(layer.get("id", "svg"))


def _svg_path_leaves(
    element: ElementTree.Element,
    matrix: Matrix,
    layer_id: str,
    context: ExportContext,
) -> list[tuple[str, Matrix]]:
    """递归走查 SVG 元素树,产出每个 <path> 的 (d, 累计矩阵),并记录不支持元素告警。

    点集导出(PNG 预览)与 Path 导出(DXF)共用此走查,告警逻辑单一来源。
    """
    tag = _local_name(element.tag)
    element_matrix = compose(matrix, _svg_transform(element.get("transform"), layer_id, context))
    leaves: list[tuple[str, Matrix]] = []

    if tag in UNSUPPORTED_SVG_TAGS:
        context.warnings.append(
            DxfWarning(
                code="SVG_UNSUPPORTED_FEATURE",
                message=f"Unsupported SVG element <{tag}> was ignored during DXF export.",
                layer_id=layer_id,
            )
        )
        return leaves

    if "url(" in element.get("fill", ""):
        context.warnings.append(
            DxfWarning(
                code="SVG_UNSUPPORTED_FEATURE",
                message="SVG paint servers such as gradients are not preserved in DXF.",
                layer_id=layer_id,
            )
        )

    if tag == "path":
        leaves.append((str(element.get("d", "")), element_matrix))
    elif tag not in {"g", "svg"}:
        context.warnings.append(
            DxfWarning(
                code="SVG_UNSUPPORTED_FEATURE",
                message=f"Unsupported SVG element <{tag}> was ignored during DXF export.",
                layer_id=layer_id,
            )
        )

    for child in list(element):
        leaves.extend(_svg_path_leaves(child, element_matrix, layer_id, context))
    return leaves


def _svg_layer_shapes(
    layer: dict[str, Any],
    matrix: Matrix,
    context: ExportContext,
) -> list[PathShape]:
    """SVG 图层 → 扁平点集 PathShape(供 PNG 预览,不依赖 ezdxf)。"""
    root, base_matrix, layer_id = _svg_render_context(layer, matrix, context)
    shapes: list[PathShape] = []
    for path_data, leaf_matrix in _svg_path_leaves(root, base_matrix, layer_id, context):
        shapes.extend(_parse_path_shapes(path_data, leaf_matrix, layer_id))
    return shapes


def _svg_layer_paths(
    layer: dict[str, Any],
    matrix: Matrix,
    context: ExportContext,
) -> list[Any]:
    """SVG 图层 → ezdxf.path.Path 列表(供 DXF 导出,贝塞尔不扁平)。"""
    root, base_matrix, layer_id = _svg_render_context(layer, matrix, context)
    paths: list[Any] = []
    for path_data, leaf_matrix in _svg_path_leaves(root, base_matrix, layer_id, context):
        paths.extend(_parse_path_objects(path_data, leaf_matrix, layer_id))
    return paths


def _svg_content_visual_bbox(
    layer: dict[str, Any],
    context: ExportContext,
) -> tuple[float, float, float, float] | None:
    """SVG 内容在其自身坐标系(viewBox 空间)里的可见墨迹 bbox:(x, y, w, h)。

    用单位基矩阵走查 path(只保留 SVG 内部 transform),得到内容真实包围盒——
    与桌面预览/PNG 用的"真实墨迹 bbox"同义,供 contain-fit 裁掉 viewBox 留白。"""
    svg_text = layer.get("inlineSvg") or _read_svg_asset(layer)
    try:
        root = ElementTree.fromstring(str(svg_text))
    except ElementTree.ParseError:
        return None
    layer_id = str(layer.get("id", "svg"))
    xs: list[float] = []
    ys: list[float] = []
    for path_data, leaf_matrix in _svg_path_leaves(root, Matrix(), layer_id, context):
        for shape in _parse_path_shapes(path_data, leaf_matrix, layer_id):
            for x, y in shape.points:
                xs.append(x)
                ys.append(y)
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def apply_svg_contain_fit(document: dict[str, Any]) -> None:
    """把 SVG 图层从"viewBox 非等比拉满框"改成"等比 contain-fit + 居中 + 裁留白",原地改图层几何。

    桌面端导出(desktop_export)对画布素材做了同样的 contain-fit,这里让批量/其它走 export_* 的路径
    也得到一致结果:既不变形、也按真实墨迹裁掉留白。做法与桌面一致——保留声明 viewBox 不动,把 fit
    折进图层的 x/y/width/height(因为 export 端按声明 viewBox 映射框):
        layer_size  = fit.scale * 声明viewBox尺寸
        layer_origin= 目标框居中量 + fit.scale * (声明viewBox原点 - 内容bbox原点)
    """
    context = ExportContext(document=document, target_units="px", exported_at="")
    for layer in document.get("layers", []):
        if not isinstance(layer, dict) or layer.get("type") != "svg":
            continue
        declared = layer.get("viewBox")
        if not isinstance(declared, dict):
            continue
        view_x = float(declared.get("x", 0) or 0)
        view_y = float(declared.get("y", 0) or 0)
        view_w = float(declared.get("width", 0) or 0)
        view_h = float(declared.get("height", 0) or 0)
        content = _svg_content_visual_bbox(layer, context)
        if content is None:
            continue
        content_x, content_y, content_w, content_h = content
        target_w = float(layer.get("width", 0) or 0) * float(layer.get("scaleX", 1) or 1)
        target_h = float(layer.get("height", 0) or 0) * float(layer.get("scaleY", 1) or 1)
        target_x = float(layer.get("x", 0) or 0)
        target_y = float(layer.get("y", 0) or 0)
        if min(view_w, view_h, content_w, content_h, target_w, target_h) <= 0:
            continue
        scale = min(target_w / content_w, target_h / content_h)  # contain(等比)
        layer["x"] = target_x + (target_w - content_w * scale) / 2 + scale * (view_x - content_x)
        layer["y"] = target_y + (target_h - content_h * scale) / 2 + scale * (view_y - content_y)
        layer["width"] = scale * view_w
        layer["height"] = scale * view_h
        layer["scaleX"] = 1.0
        layer["scaleY"] = 1.0
        # 声明 viewBox 保持不变(export 端会优先用它来映射框)。


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


def _text_layer_paths(
    layer: dict[str, Any],
    matrix: Matrix,
    context: ExportContext,
) -> list[Any]:
    """文字图层 → ezdxf.path.Path 列表(字形闭合轮廓,贝塞尔不扁平,输出 SPLINE/POLYLINE)。"""
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
    line_specs = _resolve_text_line_specs(
        layer, style, cmap, hmtx, units_per_em, font_size, line_height, letter_spacing
    )
    paths: list[Any] = []

    for line, cursor, baseline_y in line_specs:
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
            paths.extend(
                _glyph_paths(
                    glyph_set[glyph_name],
                    glyph_name,
                    cursor,
                    baseline_y,
                    font_size / units_per_em,
                    matrix,
                    str(layer.get("id", "text")),
                )
            )
            advance = float((hmtx.get(glyph_name) or (units_per_em, 0))[0])
            cursor += advance * font_size / units_per_em + letter_spacing
    return paths


def _resolve_font_path(layer: dict[str, Any], context: ExportContext) -> Path:
    raw_font_ref = layer.get("fontRef")
    font_ref: dict[str, Any] = raw_font_ref if isinstance(raw_font_ref, dict) else {}
    # 显式字体路径(项目内相对路径)优先:桌面端可任选字体文件,需用所选字体导出。
    # 经 _safe_project_path 校验,杜绝越界读取任意磁盘字体(API 也走这条入口)。
    explicit_path = font_ref.get("path")
    if explicit_path:
        try:
            candidate = _safe_project_path(str(explicit_path))
        except DomainError:
            candidate = None
        if candidate is not None and candidate.is_file() and candidate.suffix.casefold() in {
            ".ttf",
            ".otf",
        }:
            return candidate
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


def _pt(point: Any) -> tuple[float, float]:
    return (float(point[0]), float(point[1]))


def _midpoint(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def _quadratic_segments(current: tuple[float, float], args: tuple[Any, ...]) -> list[tuple]:
    """把一次 TrueType qCurveTo（可含多个离曲线控制点）正确展开成多段二次贝塞尔。

    TrueType 约定：相邻离曲线控制点之间有「隐含在线锚点」=两者中点；末参数为 ``None``
    表示整条 contour 全是离曲线点（隐含起点=末控制点与首控制点的中点，已由 moveTo 落到
    ``current``）。**旧实现把整段塌缩成单段 quad(首控制点, 末端点)，丢掉所有中间隐含锚点**
    → 平滑字形（如大写 A、&）被压成实心块/错位轮廓（预览用 Pillow 真字体则正常，故只坏矢量）。
    """
    points = [(_pt(point) if point is not None else None) for point in args]
    if not points:
        return []
    if points[-1] is None:  # 全离曲线闭合 contour：依次取相邻中点，末段回到隐含起点 current
        offs = [point for point in points[:-1] if point is not None]
        if not offs:
            return []
        ends = [_midpoint(offs[i], offs[i + 1]) for i in range(len(offs) - 1)]
        ends.append(current)
        return [("quad", ctrl, end) for ctrl, end in zip(offs, ends)]
    end = points[-1]
    offs = [point for point in points[:-1] if point is not None]
    if not offs:  # 没有控制点 → 退化成直线
        return [("line", end)]
    ends = [_midpoint(offs[i], offs[i + 1]) for i in range(len(offs) - 1)]
    ends.append(end)
    return [("quad", ctrl, segment_end) for ctrl, segment_end in zip(offs, ends)]


def _glyph_contours(glyph: Any, glyph_name: str, layer_id: str) -> list[tuple]:
    """把字形走查成中性轮廓:(起点, 段列表, 是否闭合),坐标在字体单位空间。

    段为 ("line", end) | ("quad", ctrl, end) | ("cubic", c1, c2, end)。
    SVG 导出(点集)与 DXF 导出(ezdxf Path)共用此走查器,避免重复解析。
    """
    from fontTools.pens.recordingPen import RecordingPen

    pen = RecordingPen()
    glyph.draw(pen)
    contours: list[tuple] = []
    start = (0.0, 0.0)
    current = (0.0, 0.0)
    segments: list[tuple] = []
    open_contour = False

    def flush(closed: bool) -> None:
        nonlocal segments, open_contour
        if open_contour and segments:
            contours.append((start, segments, closed))
        segments = []
        open_contour = False

    for command, args in pen.value:
        if command == "moveTo":
            flush(False)
            start = current = _pt(args[0])
            open_contour = True
        elif command == "lineTo":
            current = _pt(args[0])
            segments.append(("line", current))
        elif command == "qCurveTo":
            for segment in _quadratic_segments(current, args):
                segments.append(segment)
                current = segment[-1]
        elif command == "curveTo":
            control_1, control_2, end = (_pt(value) for value in args)
            segments.append(("cubic", control_1, control_2, end))
            current = end
        elif command == "closePath":
            flush(True)
        elif command == "endPath":
            flush(False)
        else:
            raise DomainError(
                code="GLYPH_UNSUPPORTED",
                message="Font glyph contains unsupported outline commands.",
                details={"layerId": layer_id, "glyphName": glyph_name, "command": command},
                recoverable=True,
            )
    flush(False)
    return contours


def _glyph_shapes(
    glyph: Any,
    glyph_name: str,
    cursor_x: float,
    baseline_y: float,
    scale_factor: float,
    matrix: Matrix,
    layer_id: str,
) -> list[PathShape]:
    """字形 → 扁平点集 PathShape(供 SVG 导出与 PNG 预览,不依赖 ezdxf)。"""
    # 字形在字体单位空间扁平化,经 scale_factor 再经 matrix 变换到目标单位。
    tol = _local_tolerance(matrix, scale_factor)

    def convert(point: tuple[float, float]) -> tuple[float, float]:
        x = cursor_x + point[0] * scale_factor
        y = baseline_y - point[1] * scale_factor
        return apply_matrix(matrix, (x, y))

    shapes: list[PathShape] = []
    for start, segments, closed in _glyph_contours(glyph, glyph_name, layer_id):
        points: list[tuple[float, float]] = [convert(start)]
        previous = start
        for segment in segments:
            kind = segment[0]
            if kind == "line":
                points.append(convert(segment[1]))
                previous = segment[1]
            elif kind == "quad":
                for point in _flatten_quadratic(previous, segment[1], segment[2], tol):
                    points.append(convert(point))
                previous = segment[2]
            else:  # cubic
                for point in _flatten_cubic(previous, segment[1], segment[2], segment[3], tol):
                    points.append(convert(point))
                previous = segment[3]
        if closed and points and points[0] != points[-1]:
            points.append(convert(start))
        if len(points) >= 2:
            shapes.append(PathShape(layer_id=layer_id, points=points, closed=closed))
    return shapes


def _glyph_paths(
    glyph: Any,
    glyph_name: str,
    cursor_x: float,
    baseline_y: float,
    scale_factor: float,
    matrix: Matrix,
    layer_id: str,
) -> list[Any]:
    """字形 → ezdxf.path.Path(供 DXF 导出,贝塞尔不扁平,输出 SPLINE)。"""
    from ezdxf import path as ezpath

    def convert(point: tuple[float, float]) -> tuple[float, float]:
        x = cursor_x + point[0] * scale_factor
        y = baseline_y - point[1] * scale_factor
        return apply_matrix(matrix, (x, y))

    paths: list[Any] = []
    for start, segments, closed in _glyph_contours(glyph, glyph_name, layer_id):
        path = ezpath.Path(convert(start))
        for segment in segments:
            kind = segment[0]
            if kind == "line":
                path.line_to(convert(segment[1]))
            elif kind == "quad":
                path.curve3_to(convert(segment[2]), convert(segment[1]))
            else:  # cubic
                path.curve4_to(convert(segment[3]), convert(segment[1]), convert(segment[2]))
        if closed:
            path.close()
        if _path_has_geometry(path):
            paths.append(path)
    return paths


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


def _path_has_geometry(path: Any) -> bool:
    return bool(path.has_lines or path.has_curves)


def _parse_path_objects(path_data: str, matrix: Matrix, layer_id: str) -> list[Any]:
    """解析 SVG path 的 d → ezdxf.path.Path 列表(贝塞尔不扁平,经 matrix 变换)。

    每个子路径(M…Z 或 M…M)产出一个独立 Path;直线段保持直线、贝塞尔保持曲线,
    输出阶段由 render_splines_and_polylines 转成 POLYLINE/SPLINE。
    """
    from ezdxf import path as ezpath

    tokens = PATH_TOKEN_RE.findall(path_data)
    paths: list[Any] = []
    current: Any = None
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

    def tx(point: tuple[float, float]) -> tuple[float, float]:
        return apply_matrix(matrix, point)

    def finish(close: bool) -> None:
        nonlocal current
        if current is not None and _path_has_geometry(current):
            if close:
                current.close()
            paths.append(current)
        current = None

    def line(point: tuple[float, float]) -> None:
        nonlocal current
        if current is None:
            current = ezpath.Path(tx(point))
        else:
            current.line_to(tx(point))

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
                    finish(False)
                    start = cursor
                    current = ezpath.Path(tx(cursor))
                    first = False
                else:
                    line(cursor)
            command = "L" if absolute else "l"
        elif cmd == "L":
            while has_number():
                x, y = number(), number()
                cursor = (x, y) if absolute else (cursor[0] + x, cursor[1] + y)
                line(cursor)
        elif cmd == "H":
            while has_number():
                x = number()
                cursor = (x, cursor[1]) if absolute else (cursor[0] + x, cursor[1])
                line(cursor)
        elif cmd == "V":
            while has_number():
                y = number()
                cursor = (cursor[0], y) if absolute else (cursor[0], cursor[1] + y)
                line(cursor)
        elif cmd == "Q":
            while has_number():
                control = _point(number(), number(), cursor, absolute)
                end = _point(number(), number(), cursor, absolute)
                if current is None:
                    current = ezpath.Path(tx(cursor))
                current.curve3_to(tx(end), tx(control))
                cursor = end
        elif cmd == "C":
            while has_number():
                control_1 = _point(number(), number(), cursor, absolute)
                control_2 = _point(number(), number(), cursor, absolute)
                end = _point(number(), number(), cursor, absolute)
                if current is None:
                    current = ezpath.Path(tx(cursor))
                current.curve4_to(tx(end), tx(control_1), tx(control_2))
                cursor = end
        elif cmd == "Z":
            finish(True)
            cursor = start
            command = ""
        else:
            raise DomainError(
                code="SVG_UNSUPPORTED_PATH_COMMAND",
                message=f"SVG path command {command!r} is not supported for DXF export.",
                details={"layerId": layer_id, "command": command},
                recoverable=True,
            )
    finish(False)
    return paths


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


# 雕花与刻字是同一道激光工序,所有几何放在同一图层、同一颜色,激光软件视为一次操作。
_ENGRAVE_COLOR = 7  # ACI 7 = 黑/白中性色
# 单内容层:与标准样件一致(样件名"图层 1"),花/字同层同色;ezdxf 另自带 0/Defpoints。
_ENGRAVE_LAYER = "图层 1"
# 输出 DXF R2018(AC1032):EzCad2"选中改不动"的根因是实体类型(LWPOLYLINE 不可编辑),
# 而非版本新旧——标准样件正是 R2018+SPLINE 且可编辑。R2018 还能找回 $INSUNITS(mm)。
# 几何用 ezdxf.path.render_splines_and_polylines 输出:曲线→SPLINE,直线段→POLYLINE(均可编辑)。
_DXF_VERSION = "R2018"
# 把一条轮廓的连续贝塞尔段合并成一条 SPLINE,而非每段一条:
# render_splines_and_polylines 默认只在切线连续(G1)处合并,会把字形/花朵的尖角处
# 拆成成百上千条单段 SPLINE;调大 g1_tol 让相邻三次贝塞尔合并为一条三次 B 样条
# (尖角由内部节点重数精确保留,几何不变),实体数大幅下降,贴近标准样件
# (样件正是每轮廓一条 7/10/13… 控制点的 SPLINE)。
_SPLINE_JOIN_G1_TOL = 1e9


def _write_dxf(
    paths: list[_LayerPath],
    context: ExportContext,
    metadata: dict[str, str],
) -> str:
    ezdxf = _load_ezdxf()
    from ezdxf import path as ezpath

    doc = ezdxf.new(dxfversion=_DXF_VERSION)
    doc.header["$INSUNITS"] = INSUNITS[context.target_units]
    _write_dxf_metadata(doc, metadata)
    modelspace = doc.modelspace()
    _ensure_layer(doc, _ENGRAVE_LAYER)

    renderable = [item for item in paths if _path_has_geometry(item.path)]
    # 实体显式着色 ACI 7:EzCad 等激光软件对 BYLAYER(256)解析不全会显示成红色默认笔;
    # 显式色 7 才稳定,并与标准样件同色(同一道工序)。颜色"变黑"放在 Ezcad 自动导入项目处理。
    dxfattribs = {"layer": _ENGRAVE_LAYER, "color": _ENGRAVE_COLOR}

    # 花朵/SVG 描边 + 文字闭合字形 → SPLINE/POLYLINE(EzCad 可编辑,非 LWPOLYLINE)。
    # 文字只输出闭合轮廓、DXF 内不做填充:EzCad 不认 DXF HATCH,实心由 Ezcad 自动导入项目在导入后
    # 用 EzCad 原生「填充」完成(与点黑色块同一步)。闭合轮廓正好可被 EzCad 选中填充。
    outlines = [item.path for item in renderable]
    if outlines:
        ezpath.render_splines_and_polylines(
            modelspace,
            outlines,
            g1_tol=_SPLINE_JOIN_G1_TOL,
            dxfattribs=dxfattribs,
        )

    stream = StringIO()
    doc.write(stream)
    return stream.getvalue()


def _ensure_layer(doc: Any, name: str) -> None:
    layers = getattr(doc, "layers", None)
    if layers is None or not hasattr(layers, "add"):
        return  # 防御:无图层表时实体仍带 layer 属性,CAD 自动建层
    try:
        if hasattr(layers, "has_entry") and layers.has_entry(name):
            return
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


def _resolve_text_line_specs(
    layer: dict[str, Any],
    style: dict[str, Any],
    cmap: dict[int, str],
    hmtx: dict[str, Any],
    units_per_em: float,
    font_size: float,
    line_height: float,
    letter_spacing: float,
) -> list[tuple[str, float, float]]:
    """每行 (文本, 笔位 cursor, 基线 baseline_y)，box 本地像素。

    桌面端把 text_layout.fit_text_box 的结果烘进 layer['textLayout']（lines + origins，
    origins 为每行 anchor='ls' 的 (pen_x, baseline_y)）；此时直接复用，保证矢量导出与预览/PNG
    逐字落点一致。无 textLayout（web 批量/金标）时回退到原“按对齐+行号”排版，行为不变。
    """
    box_layout = layer.get("textLayout")
    if (
        isinstance(box_layout, dict)
        and isinstance(box_layout.get("lines"), list)
        and isinstance(box_layout.get("origins"), list)
    ):
        lines = [str(item) for item in box_layout["lines"]]
        origins = box_layout["origins"]
        specs: list[tuple[str, float, float]] = []
        for index, line in enumerate(lines):
            origin = origins[index] if index < len(origins) else None
            if isinstance(origin, (list, tuple)) and len(origin) == 2:
                specs.append((line, float(origin[0]), float(origin[1])))
            else:
                cursor = _aligned_text_offset(
                    line, style, layer, cmap, hmtx, units_per_em, font_size, letter_spacing
                )
                specs.append((line, cursor, index * font_size * line_height))
        return specs
    text = _text_with_glyph_overrides(layer)
    return [
        (
            line,
            _aligned_text_offset(
                line, style, layer, cmap, hmtx, units_per_em, font_size, letter_spacing
            ),
            line_index * font_size * line_height,
        )
        for line_index, line in enumerate(re.split(r"\r\n|\n|\r", text))
    ]


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
