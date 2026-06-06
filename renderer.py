from __future__ import annotations

import base64
from dataclasses import dataclass
from html import escape
import math
import mimetypes
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from glyph_service import GlyphCandidate, render_glyph_thumbnail
from models import BirthFlowerDesign, EngravingLayout
from text_layout import LINE_HEIGHT_RATIO, TextLayoutResult, layout_personalization_text
from visual_layout import FitTransform, Rect, fit_content_bbox_to_target_rect


MONTH_NAMES = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}

FONT_FAMILIES = {
    1: "serif",
    2: "sans-serif",
    3: "cursive",
    4: "monospace",
}

DEFAULT_LAYOUT = EngravingLayout()
USE_VISUAL_BBOX_FOR_SVG = True
SVG_FIT_MODE = "contain"
DEBUG_VISUAL_BBOX = False
BITMAP_ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


@dataclass(frozen=True)
class PathPolyline:
    points: tuple[tuple[float, float], ...]
    stroke_width: float = 0.0


@dataclass(frozen=True)
class SvgGeometry:
    view_box: Rect
    visual_bbox: Rect
    polylines: tuple[PathPolyline, ...]


_SVG_GEOMETRY_CACHE: dict[tuple[Path, float], SvgGeometry] = {}


class PreviewCache:
    """缓存实时画板预览线段，避免拖拽时重复解析未变化的 SVG。"""

    def __init__(self) -> None:
        self._cache: dict[tuple[Path, float, EngravingLayout, bool], list[list[tuple[float, float]]]] = {}

    def polylines(self, asset_path: Path | str, layout: EngravingLayout) -> list[list[tuple[float, float]]]:
        path = Path(asset_path)
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = 0.0
        key = (path, modified, layout, USE_VISUAL_BBOX_FOR_SVG)
        if key not in self._cache:
            self._cache[key] = flower_preview_polylines(path, layout)
        return self._cache[key]

    def clear(self) -> None:
        self._cache.clear()


def render_svg(design: BirthFlowerDesign, output_path: Path | str) -> Path:
    """生成雕刻用 SVG；选择了花朵素材时会嵌入该 SVG 的矢量内容。"""
    _validate_design(design)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    flower_markup = _selected_flower_markup(design) if design.flower_asset_path else _fallback_flower_markup()
    font_face = _font_face_markup(design.font_path)
    font_family = "BirthFlowerSelected" if design.font_path else FONT_FAMILIES[design.font]
    month_name = MONTH_NAMES[design.month]
    layout = design.layout
    text_layout = layout_personalization_text(design.text, layout, design.personalization_type, design.font_path)
    text_markup = _svg_text_markup(design, font_family, text_layout)

    # TODO: 当前 SVG 姓名仍使用 <text>，PUA 字符依赖字体文件；后续如需雕刻稳定性，应增加文字转路径。
    glyph_metadata = _glyph_override_metadata(design)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{layout.canvas_width}" height="{layout.canvas_height}" viewBox="0 0 {layout.canvas_width} {layout.canvas_height}" role="img" aria-label="Birth Flower {escape(design.text)}">
  <title>{escape(month_name)} {escape(design.flower_name or "Birth Flower")} - {escape(design.text)}</title>
  <metadata>该 SVG 依赖字体文件和 PUA 字符，换环境可能显示异常。{glyph_metadata}</metadata>
  <defs>
{font_face}
  </defs>
{flower_markup}
{text_markup}
</svg>
"""
    path.write_text(svg, encoding="utf-8")
    return path


def render_dxf(design: BirthFlowerDesign, output_path: Path | str) -> Path:
    """生成雕刻用 DXF；花朵 SVG path 转为折线，文字用 TEXT 实体保留。"""
    _validate_design(design)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    entities: list[str] = []
    if design.flower_asset_path is not None:
        flower_path = Path(design.flower_asset_path)
        if _is_bitmap_asset(flower_path):
            raise ValueError("位图素材无法导出 DXF；请改用 SVG/PNG，或导入纯矢量 SVG。")
        for polyline in _flower_polylines(flower_path, design.layout):
            if len(polyline) >= 2:
                entities.append(_dxf_polyline(polyline, "FLOWER"))
    text_layout = layout_personalization_text(design.text, design.layout, design.personalization_type, design.font_path)
    entities.extend(_dxf_text_entities(design, text_layout))
    path.write_text(_dxf_document(entities), encoding="utf-8")
    return path


def render_png(design: BirthFlowerDesign, output_path: Path | str) -> Path:
    """PNG 是可选能力；缺 Pillow 时给出友好错误，不强行下载依赖。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("当前环境未安装 Pillow；请先生成 SVG，或安装可用的 Pillow 后再生成 PNG。") from exc

    _validate_design(design)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    layout = design.layout
    output_width = layout.canvas_width
    output_height = layout.canvas_height
    image = Image.new("RGBA", (output_width, output_height), "#FFF8F0")
    draw = ImageDraw.Draw(image)
    if design.flower_asset_path is not None:
        flower_path = Path(design.flower_asset_path)
        if _is_bitmap_asset(flower_path):
            _draw_png_bitmap_flower(image, Image, flower_path, layout)
        else:
            _draw_png_svg_flower(draw, flower_path, layout)
    else:
        _draw_png_fallback_flower(draw, design.flower)

    text_layout = layout_personalization_text(design.text, layout, design.personalization_type, design.font_path)
    scale = min(output_width / layout.canvas_width, output_height / layout.canvas_height)
    offset_x = (output_width - layout.canvas_width * scale) / 2
    offset_y = (output_height - layout.canvas_height * scale) / 2
    # 不内置商业字体；如果用户选择了字体文件，PNG 使用同一字体以接近最终字形效果。
    font = _png_font(ImageFont, design.font_path, max(8, round(text_layout.final_font_size * scale)))
    if text_layout.line_count == 1 and text_layout.lines:
        line = text_layout.lines[0]
        if not _draw_png_fitted_text_line(image, Image, ImageDraw, line, font, design, text_layout, scale, offset_x, offset_y):
            _draw_png_text_line(image, draw, line, 0, offset_x + text_layout.draw_x * scale, offset_y + text_layout.draw_y * scale, font, design)
    else:
        line_start = 0
        for index, line in enumerate(text_layout.lines):
            if index < len(text_layout.line_origins):
                line_x, line_y = text_layout.line_origins[index]
            else:
                line_x = text_layout.draw_x
                line_y = text_layout.draw_y + index * text_layout.final_font_size * LINE_HEIGHT_RATIO
            _draw_png_text_line(
                image,
                draw,
                line,
                line_start,
                offset_x + line_x * scale,
                offset_y + line_y * scale,
                font,
                design,
            )
            line_start += len(line)
    image.save(path)
    return path


def flower_preview_polylines(asset_path: Path | str, layout: EngravingLayout) -> list[list[tuple[float, float]]]:
    """给 UI 预览使用的 SVG 轮廓坐标；坐标系保持 SVG 画布方向。"""
    return [[(x, layout.canvas_height - y) for x, y in polyline] for polyline in _flower_polylines(Path(asset_path), layout)]


def flower_debug_bboxes(asset_path: Path | str, layout: EngravingLayout) -> dict[str, Rect]:
    """返回目标框、原始 viewBox 框和真实 visual bbox 框在画布坐标中的位置。"""
    path = Path(asset_path)
    geometry = _svg_geometry(path)
    fit = _svg_fit_transform(path, layout, USE_VISUAL_BBOX_FOR_SVG, SVG_FIT_MODE)

    def transformed(rect: Rect) -> Rect:
        x1, y1 = fit.apply(rect.left, rect.top)
        x2, y2 = fit.apply(rect.right, rect.bottom)
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        return Rect(left, top, right - left, bottom - top)

    return {
        "target": Rect(layout.flower_x, layout.flower_y, layout.flower_width, layout.flower_height),
        "layout": transformed(geometry.view_box),
        "visual": transformed(geometry.visual_bbox),
    }


def _validate_design(design: BirthFlowerDesign) -> None:
    if not design.text.strip():
        raise ValueError("文字不能为空")
    if design.month not in MONTH_NAMES:
        raise ValueError("月份必须是 1-12")
    if design.font < 1 or (design.font not in FONT_FAMILIES and design.font_path is None):
        raise ValueError("font 必须是 1-4，或选择一个实际字体文件")
    if design.flower < 1 or (design.flower not in {1, 2} and design.flower_asset_path is None):
        raise ValueError("flower 必须是 1-2，或选择一个实际素材文件")
    if design.flower_asset_path is not None and not Path(design.flower_asset_path).exists():
        raise ValueError(f"素材文件不存在：{design.flower_asset_path}")
    if design.font_path is not None and not Path(design.font_path).exists():
        raise ValueError(f"字体文件不存在：{design.font_path}")


def _glyph_override_metadata(design: BirthFlowerDesign) -> str:
    unmapped = [
        f"位置 {index}: {override.get('glyph_name')} glyph_id={override.get('glyph_id')}"
        for index, override in sorted((design.glyph_overrides or {}).items())
        if not override.get("codepoint")
    ]
    if not unmapped:
        return ""
    return " 未映射 glyph 可预览但暂不支持导出：" + "；".join(unmapped)


def _png_font(image_font_module, font_path: Path | None, font_size: int):
    if font_path is None:
        return image_font_module.load_default()
    try:
        return image_font_module.truetype(str(font_path), font_size)
    except Exception:
        # 字体损坏或 Pillow 不支持时保留友好降级，不让 PNG 生成崩溃。
        return image_font_module.load_default()


def _is_bitmap_asset(path: Path) -> bool:
    return path.suffix.casefold() in BITMAP_ASSET_SUFFIXES


def _draw_png_bitmap_flower(image, image_module, asset_path: Path, layout: EngravingLayout) -> None:
    """位图素材只能作为图片贴入 PNG；SVG 会明确标注它不是纯矢量。"""
    try:
        bitmap = image_module.open(asset_path).convert("RGBA")
    except Exception as exc:
        raise RuntimeError(f"位图素材读取失败：{asset_path}") from exc
    target_size = (max(1, int(layout.flower_width)), max(1, int(layout.flower_height)))
    resampling = getattr(getattr(image_module, "Resampling", image_module), "LANCZOS", 1)
    bitmap.thumbnail(target_size, resampling)
    x = int(layout.flower_x + (layout.flower_width - bitmap.width) / 2)
    y = int(layout.flower_y + (layout.flower_height - bitmap.height) / 2)
    if hasattr(image, "alpha_composite"):
        image.alpha_composite(bitmap, (x, y))
    else:
        image.paste(bitmap, (x, y), bitmap)


def _draw_png_svg_flower(draw, asset_path: Path, layout: EngravingLayout) -> None:
    """PNG 使用与实时预览一致的 SVG path 解析结果，避免导出时变成占位花。"""
    line_width = max(2, round(min(layout.flower_width, layout.flower_height) / 300))
    for polyline in flower_preview_polylines(asset_path, layout):
        if len(polyline) >= 2:
            draw.line(polyline, fill="#111111", width=line_width, joint="curve")


def _draw_png_fallback_flower(draw, flower: int) -> None:
    """没有选择素材时才绘制内置占位花形。"""
    draw.ellipse((270, 190, 930, 850), fill="#F8E9E4")
    color = "#D96C75" if flower == 1 else "#7B8FD4"
    for box in _png_petal_boxes(flower):
        draw.ellipse(box, fill=color)
    draw.ellipse((534, 454, 666, 586), fill="#F2C166")


def _draw_png_text_line(image, draw, line: str, line_start: int, origin_x: float, origin_y: float, font, design: BirthFlowerDesign) -> None:
    unmapped_indexes = {
        int(index): override
        for index, override in (design.glyph_overrides or {}).items()
        if not override.get("codepoint")
    }
    if not unmapped_indexes or design.font_path is None:
        draw.text((origin_x, origin_y), line, fill="#2E2A27", font=font)
        return

    # 无 Unicode 映射的 glyph 无法放进字符串，只能按字符拆开并用 glyph_id 单独贴图。
    line_width = draw.textlength(line, font=font)
    cursor_x = origin_x
    for offset, char in enumerate(line):
        absolute_index = line_start + offset
        char_width = max(1, draw.textlength(char, font=font))
        override = unmapped_indexes.get(absolute_index)
        if override:
            _paste_unmapped_png_glyph(image, design, override, cursor_x, origin_y, char_width)
        else:
            draw.text((cursor_x, origin_y), char, fill="#2E2A27", font=font)
        cursor_x += char_width


def _draw_png_fitted_text_line(
    image,
    image_module,
    image_draw_module,
    line: str,
    font,
    design: BirthFlowerDesign,
    text_layout: TextLayoutResult,
    scale: float,
    offset_x: float,
    offset_y: float,
) -> bool:
    """单行文字按真实墨迹裁剪并非等比铺满目标框；失败时交回普通文本渲染。"""
    if not line or not hasattr(image, "alpha_composite"):
        return False
    if any(not override.get("codepoint") for override in (design.glyph_overrides or {}).values()):
        return False
    ink_bounds = text_layout.ink_bounds
    if ink_bounds is None or ink_bounds.width <= 0 or ink_bounds.height <= 0:
        return False
    width = max(1, math.ceil(ink_bounds.width) + 1)
    height = max(1, math.ceil(ink_bounds.height) + 1)
    try:
        text_image = image_module.new("RGBA", (width, height), (0, 0, 0, 0))
        text_draw = image_draw_module.Draw(text_image)
        text_draw.text((-ink_bounds.left, -ink_bounds.top), line, fill="#2E2A27", font=font)
        alpha_bbox = text_image.getbbox()
    except Exception:
        return False
    if alpha_bbox is None:
        return False
    target_size = (
        max(1, round(text_layout.text_bounds.width * scale)),
        max(1, round(text_layout.text_bounds.height * scale)),
    )
    try:
        resampling = getattr(getattr(image_module, "Resampling", image_module), "LANCZOS", 1)
        fitted = text_image.crop(alpha_bbox).resize(target_size, resampling)
    except Exception:
        return False
    x = round(offset_x + text_layout.text_bounds.left * scale)
    y = round(offset_y + text_layout.text_bounds.top * scale)
    image.alpha_composite(fitted, (x, y))
    return True


def _paste_unmapped_png_glyph(image, design: BirthFlowerDesign, override: dict, cursor_x: float, center_y: float, char_width: float) -> None:
    if design.font_path is None:
        return
    glyph_id = int(override.get("glyph_id", -1))
    if glyph_id < 0:
        return
    size = max(24, round(char_width * 2.2))
    try:
        glyph_image = render_glyph_thumbnail(
            design.font_path,
            GlyphCandidate(
                glyph_name=str(override.get("glyph_name") or f"glyph-{glyph_id}"),
                glyph_id=glyph_id,
                unicode=None,
                char=None,
                is_pua=False,
                is_mapped=False,
            ),
            image_size=size,
            font_size=size,
        )
    except Exception:
        return
    x = max(0, min(image.width - size, round(cursor_x - (size - char_width) / 2)))
    y = max(0, min(image.height - size, round(center_y - size / 2)))
    image.alpha_composite(glyph_image, (x, y))


def _svg_text_markup(design: BirthFlowerDesign, font_family: str, text_layout: TextLayoutResult) -> str:
    if text_layout.line_count == 1:
        if text_layout.ink_bounds is not None and text_layout.ink_bounds.width > 0 and text_layout.ink_bounds.height > 0:
            transform = _svg_text_fill_transform(text_layout)
            text = (
                f'    <g transform="{transform}">\n'
                f'      <text x="0" y="0" font-family="{font_family}" font-size="{text_layout.final_font_size}" '
                f'fill="#111111" xml:space="preserve">{escape(text_layout.lines[0])}</text>\n'
                f"    </g>"
            )
        else:
            text = (
                f'    <text x="{text_layout.draw_x:g}" y="{text_layout.draw_y:g}" '
                f'font-family="{font_family}" font-size="{text_layout.final_font_size}" fill="#111111" xml:space="preserve">'
                f"{escape(text_layout.lines[0])}</text>"
            )
        return f'  <g id="text-art">\n{text}\n  </g>'

    line_height = text_layout.final_font_size * LINE_HEIGHT_RATIO
    lines: list[str] = []
    for index, line in enumerate(text_layout.lines):
        if index < len(text_layout.line_origins):
            x, y = text_layout.line_origins[index]
        else:
            x = text_layout.draw_x
            y = text_layout.draw_y + index * line_height
        lines.append(
            f'    <text x="{x:g}" y="{y:g}" font-family="{font_family}" '
            f'font-size="{text_layout.final_font_size}" fill="#111111" xml:space="preserve">{escape(line)}</text>'
        )
    return "  <g id=\"text-art\">\n" + "\n".join(lines) + "\n  </g>"


def _svg_text_fill_transform(text_layout: TextLayoutResult) -> str:
    ink_bounds = text_layout.ink_bounds
    if ink_bounds is None:
        return ""
    return (
        f"translate({text_layout.text_bounds.left:g} {text_layout.text_bounds.top:g}) "
        f"scale({text_layout.render_scale_x:g} {text_layout.render_scale_y:g}) "
        f"translate({-ink_bounds.left:g} {-ink_bounds.top:g})"
    )


def _dxf_text_entities(design: BirthFlowerDesign, text_layout: TextLayoutResult) -> list[str]:
    layout = design.layout
    if text_layout.line_count == 1:
        center_x = (text_layout.text_bounds.left + text_layout.text_bounds.right) / 2
        center_y = (text_layout.text_bounds.top + text_layout.text_bounds.bottom) / 2
        vertical_scale = max(0.0001, text_layout.render_scale_y)
        text_size = text_layout.final_font_size * vertical_scale
        width_factor = text_layout.render_scale_x / vertical_scale
        return [_dxf_text(text_layout.lines[0], center_x, layout.canvas_height - center_y, text_size, "TEXT", width_factor)]

    center_x = (text_layout.text_bounds.left + text_layout.text_bounds.right) / 2
    entities: list[str] = []
    for index, line in enumerate(text_layout.lines):
        svg_y = text_layout.text_bounds.top + text_layout.final_font_size + index * text_layout.final_font_size * LINE_HEIGHT_RATIO
        entities.append(_dxf_text(line, center_x, layout.canvas_height - svg_y, text_layout.final_font_size, "TEXT"))
    return entities


def _selected_flower_markup(design: BirthFlowerDesign) -> str:
    asset_path = Path(design.flower_asset_path or "")
    if _is_bitmap_asset(asset_path):
        return _selected_bitmap_flower_markup(design, asset_path)
    raw_svg = asset_path.read_text(encoding="utf-8")
    attrs, inner = _extract_svg_parts(raw_svg)
    view_box = _svg_content_view_box(asset_path, USE_VISUAL_BBOX_FOR_SVG)
    namespace_attrs = _namespace_attrs(attrs)
    title = escape(design.flower_name or asset_path.stem)
    layout = design.layout
    # 位置按 user 实际产物参考：横向画布，花是主视觉，姓名在右下。
    return f"""  <g id="flower-art">
    <title>{title}</title>
    <svg x="{layout.flower_x}" y="{layout.flower_y}" width="{layout.flower_width}" height="{layout.flower_height}" viewBox="{escape(view_box)}" preserveAspectRatio="xMidYMid meet" {namespace_attrs}>
{inner}
    </svg>
  </g>"""


def _selected_bitmap_flower_markup(design: BirthFlowerDesign, asset_path: Path) -> str:
    layout = design.layout
    mime_type = mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(asset_path.read_bytes()).decode("ascii")
    title = escape(design.flower_name or asset_path.stem)
    return f"""  <g id="flower-art">
    <title>{title}</title>
    <metadata>位图素材以图片嵌入，不是纯矢量；如需 DXF 或纯矢量 SVG，请导入矢量 SVG。</metadata>
    <image x="{layout.flower_x}" y="{layout.flower_y}" width="{layout.flower_width}" height="{layout.flower_height}" href="data:{escape(mime_type)};base64,{encoded}" preserveAspectRatio="xMidYMid meet" />
  </g>"""


def _fallback_flower_markup() -> str:
    return """  <g id="flower-art" fill="none" stroke="#111111" stroke-width="5" stroke-linecap="round" stroke-linejoin="round">
    <path d="M610 765 C585 650 590 525 655 385"/>
    <path d="M655 385 C600 355 575 305 605 255 C665 270 692 325 655 385"/>
    <path d="M625 555 C550 525 520 475 545 425 C620 435 655 485 625 555"/>
    <path d="M650 505 C725 470 765 500 760 560 C705 585 665 560 650 505"/>
    <path d="M610 640 C555 615 520 640 505 700 C565 725 600 705 610 640"/>
  </g>"""


def _font_face_markup(font_path: Path | None) -> str:
    if font_path is None:
        return ""
    path = Path(font_path)
    format_name = "opentype" if path.suffix.casefold() == ".otf" else "truetype"
    font_url = path.as_posix().replace("'", "%27")
    return f"""    <style>
      @font-face {{
        font-family: 'BirthFlowerSelected';
        src: url('{escape(font_url)}') format('{format_name}');
      }}
    </style>"""


def _extract_svg_parts(raw_svg: str) -> tuple[str, str]:
    cleaned = re.sub(r"<\?xml[^>]*\?>", "", raw_svg, flags=re.IGNORECASE)
    cleaned = re.sub(r"<!DOCTYPE[^>]*(?:\[[\s\S]*?\]\s*)?>", "", cleaned, flags=re.IGNORECASE)
    match = re.search(r"<svg\b([^>]*)>", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError("花朵文件不是有效 SVG")
    end_index = cleaned.lower().rfind("</svg>")
    if end_index < 0:
        raise ValueError("花朵 SVG 缺少结束标签")
    return match.group(1), cleaned[match.end() : end_index].strip()


def _extract_view_box(attrs: str) -> str | None:
    match = re.search(r'viewBox\s*=\s*["\']([^"\']+)["\']', attrs, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _view_box_from_size(attrs: str) -> str | None:
    width = _extract_svg_length(attrs, "width")
    height = _extract_svg_length(attrs, "height")
    if width is None or height is None:
        return None
    return f"0 0 {width:g} {height:g}"


def _extract_svg_length(attrs: str, name: str) -> float | None:
    match = re.search(rf'{name}\s*=\s*["\']([0-9.]+)(?:px)?["\']', attrs, flags=re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def _namespace_attrs(attrs: str) -> str:
    matches = re.findall(r'(xmlns(?::[A-Za-z_][\w.-]*)?\s*=\s*["\'][^"\']+["\'])', attrs)
    return " ".join(matches)


def _flower_polylines(asset_path: Path, layout: EngravingLayout) -> list[list[tuple[float, float]]]:
    geometry = _svg_geometry(asset_path)
    content_bbox = geometry.visual_bbox if USE_VISUAL_BBOX_FOR_SVG else geometry.view_box
    fit = _fit_svg_bbox(content_bbox, layout, SVG_FIT_MODE)
    return [
        [_source_to_dxf_point(point, fit, layout) for point in polyline.points]
        for polyline in geometry.polylines
        if len(polyline.points) >= 2
    ]


def _svg_content_view_box(asset_path: Path, use_visual_bbox: bool) -> str:
    geometry = _svg_geometry(asset_path)
    bbox = geometry.visual_bbox if use_visual_bbox else geometry.view_box
    return f"{bbox.x:g} {bbox.y:g} {bbox.width:g} {bbox.height:g}"


def _svg_fit_transform(
    asset_path: Path,
    layout: EngravingLayout,
    use_visual_bbox: bool = USE_VISUAL_BBOX_FOR_SVG,
    mode: str = SVG_FIT_MODE,
) -> FitTransform:
    geometry = _svg_geometry(asset_path)
    content_bbox = geometry.visual_bbox if use_visual_bbox else geometry.view_box
    return _fit_svg_bbox(content_bbox, layout, mode)


def _fit_svg_bbox(content_bbox: Rect, layout: EngravingLayout, mode: str) -> FitTransform:
    return fit_content_bbox_to_target_rect(
        content_bbox,
        Rect(layout.flower_x, layout.flower_y, layout.flower_width, layout.flower_height),
        mode=mode,
    )


def _svg_geometry(asset_path: Path) -> SvgGeometry:
    path = Path(asset_path)
    try:
        modified = path.stat().st_mtime
    except OSError:
        modified = 0.0
    key = (path, modified)
    cached = _SVG_GEOMETRY_CACHE.get(key)
    if cached is not None:
        return cached

    root = _read_svg_root(path)
    attrs = " ".join(f'{name}="{value}"' for name, value in root.attrib.items())
    view_box = _parse_view_box_rect(_extract_view_box(attrs) or _view_box_from_size(attrs)) or Rect(0.0, 0.0, 3000.0, 3000.0)
    polylines: list[PathPolyline] = []
    _collect_path_polylines(root, _identity_matrix(), polylines, inherited_stroke_width=0.0, inherited_stroke_visible=False)
    visual_bbox = _visual_bbox_from_polylines(polylines) or view_box
    geometry = SvgGeometry(view_box=view_box, visual_bbox=visual_bbox, polylines=tuple(polylines))
    _SVG_GEOMETRY_CACHE[key] = geometry
    return geometry


def _parse_view_box_rect(view_box: str | None) -> Rect | None:
    if not view_box:
        return None
    try:
        values = [float(part) for part in re.split(r"[\s,]+", view_box.strip()) if part]
    except ValueError:
        return None
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        return None
    return Rect(values[0], values[1], values[2], values[3])


def _visual_bbox_from_polylines(polylines: list[PathPolyline]) -> Rect | None:
    bounds: list[Rect] = []
    for polyline in polylines:
        if not polyline.points:
            continue
        xs = [point[0] for point in polyline.points]
        ys = [point[1] for point in polyline.points]
        pad = max(0.0, polyline.stroke_width / 2)
        left = min(xs) - pad
        top = min(ys) - pad
        right = max(xs) + pad
        bottom = max(ys) + pad
        if right > left and bottom > top:
            bounds.append(Rect(left, top, right - left, bottom - top))
    if not bounds:
        return None
    left = min(rect.left for rect in bounds)
    top = min(rect.top for rect in bounds)
    right = max(rect.right for rect in bounds)
    bottom = max(rect.bottom for rect in bounds)
    if right <= left or bottom <= top:
        return None
    return Rect(left, top, right - left, bottom - top)


def _read_svg_root(asset_path: Path) -> ET.Element:
    raw_svg = asset_path.read_text(encoding="utf-8")
    cleaned = re.sub(r"<\?xml[^>]*\?>", "", raw_svg, flags=re.IGNORECASE)
    cleaned = re.sub(r"<!DOCTYPE[^>]*(?:\[[\s\S]*?\]\s*)?>", "", cleaned, flags=re.IGNORECASE)
    try:
        return ET.fromstring(cleaned)
    except ET.ParseError as exc:
        raise ValueError(f"花朵 SVG 解析失败：{asset_path}") from exc


def _collect_path_polylines(
    element: ET.Element,
    parent_matrix: tuple[float, float, float, float, float, float],
    polylines: list[PathPolyline],
    inherited_stroke_width: float,
    inherited_stroke_visible: bool,
) -> None:
    matrix = _multiply_matrix(parent_matrix, _parse_transform(element.attrib.get("transform", "")))
    stroke_width = _element_stroke_width(element, inherited_stroke_width)
    stroke_visible = _element_stroke_visible(element, inherited_stroke_visible)
    if _tag_name(element.tag) == "path" and element.attrib.get("d"):
        effective_stroke_width = stroke_width * _matrix_scale_factor(matrix) if stroke_visible else 0.0
        for polyline in _path_to_polylines(element.attrib["d"], matrix):
            polylines.append(PathPolyline(points=tuple(polyline), stroke_width=effective_stroke_width))
    for child in list(element):
        _collect_path_polylines(child, matrix, polylines, stroke_width, stroke_visible)


def _element_stroke_width(element: ET.Element, inherited: float) -> float:
    value = element.attrib.get("stroke-width")
    if value is None:
        style = _style_map(element.attrib.get("style", ""))
        value = style.get("stroke-width")
    if value is None:
        return inherited if inherited > 0 else 1.0
    parsed = _parse_svg_number(value)
    return inherited if parsed is None else max(0.0, parsed)


def _element_stroke_visible(element: ET.Element, inherited: bool) -> bool:
    value = element.attrib.get("stroke")
    if value is None:
        style = _style_map(element.attrib.get("style", ""))
        value = style.get("stroke")
    if value is None:
        return inherited
    return value.strip().casefold() not in {"", "none", "transparent"}


def _style_map(style: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for chunk in style.split(";"):
        if ":" not in chunk:
            continue
        name, value = chunk.split(":", 1)
        result[name.strip()] = value.strip()
    return result


def _parse_svg_number(value: str) -> float | None:
    match = re.search(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _matrix_scale_factor(matrix: tuple[float, float, float, float, float, float]) -> float:
    a, b, c, d, _e, _f = matrix
    scale_x = math.hypot(a, b)
    scale_y = math.hypot(c, d)
    if scale_x <= 0:
        return scale_y if scale_y > 0 else 1.0
    if scale_y <= 0:
        return scale_x
    return (scale_x + scale_y) / 2


def _path_to_polylines(
    path_data: str,
    matrix: tuple[float, float, float, float, float, float],
) -> list[list[tuple[float, float]]]:
    tokens = re.findall(r"[AaCcHhLlMmQqSsTtVvZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", path_data)
    index = 0
    command = ""
    x = y = 0.0
    start_x = start_y = 0.0
    current: list[tuple[float, float]] = []
    polylines: list[list[tuple[float, float]]] = []

    def has_number(offset: int = 0) -> bool:
        return index + offset < len(tokens) and not re.fullmatch(r"[A-Za-z]", tokens[index + offset])

    def has_numbers(count: int) -> bool:
        return all(has_number(offset) for offset in range(count))

    def read_number() -> float:
        nonlocal index
        value = float(tokens[index])
        index += 1
        return value

    def add_point(px: float, py: float) -> None:
        current.append(_apply_matrix(matrix, px, py))

    def flush() -> None:
        nonlocal current
        if len(current) >= 2:
            polylines.append(current)
        current = []

    while index < len(tokens):
        if re.fullmatch(r"[A-Za-z]", tokens[index]):
            command = tokens[index]
            index += 1
        if not command:
            break

        relative = command.islower()
        op = command.upper()

        if op == "M":
            first = True
            while has_numbers(2):
                nx = read_number()
                ny = read_number()
                if relative:
                    nx += x
                    ny += y
                if first:
                    flush()
                    x, y = nx, ny
                    start_x, start_y = x, y
                    add_point(x, y)
                    first = False
                else:
                    x, y = nx, ny
                    add_point(x, y)
            command = "l" if relative else "L"
        elif op == "L":
            while has_numbers(2):
                nx = read_number()
                ny = read_number()
                if relative:
                    nx += x
                    ny += y
                x, y = nx, ny
                add_point(x, y)
        elif op == "H":
            while has_number():
                nx = read_number()
                if relative:
                    nx += x
                x = nx
                add_point(x, y)
        elif op == "V":
            while has_number():
                ny = read_number()
                if relative:
                    ny += y
                y = ny
                add_point(x, y)
        elif op == "C":
            while has_numbers(6):
                x1, y1, x2, y2, x3, y3 = read_number(), read_number(), read_number(), read_number(), read_number(), read_number()
                if relative:
                    x1, y1, x2, y2, x3, y3 = x + x1, y + y1, x + x2, y + y2, x + x3, y + y3
                for step in range(1, 13):
                    t = step / 12
                    add_point(*_cubic_point(x, y, x1, y1, x2, y2, x3, y3, t))
                x, y = x3, y3
        elif op == "Q":
            while has_numbers(4):
                x1, y1, x2, y2 = read_number(), read_number(), read_number(), read_number()
                if relative:
                    x1, y1, x2, y2 = x + x1, y + y1, x + x2, y + y2
                for step in range(1, 9):
                    t = step / 8
                    add_point(*_quadratic_point(x, y, x1, y1, x2, y2, t))
                x, y = x2, y2
        elif op == "Z":
            add_point(start_x, start_y)
            flush()
        else:
            break

    flush()
    return polylines


def _source_to_dxf_point(point: tuple[float, float], fit: FitTransform, layout: EngravingLayout) -> tuple[float, float]:
    svg_x, svg_y = fit.apply(point[0], point[1])
    return svg_x, layout.canvas_height - svg_y


def _dxf_document(entities: list[str]) -> str:
    body = "\n".join(entities)
    return f"""0
999
DXF TEXT 依赖字体文件和 PUA 字符，换环境可能显示异常。
0
SECTION
2
HEADER
9
$ACADVER
1
AC1009
0
ENDSEC
0
SECTION
2
ENTITIES
{body}
0
ENDSEC
0
EOF
"""


def _dxf_polyline(points: list[tuple[float, float]], layer: str) -> str:
    vertices = "\n".join(
        f"""0
VERTEX
8
{layer}
10
{x:.4f}
20
{y:.4f}
30
0.0"""
        for x, y in points
    )
    return f"""0
POLYLINE
8
{layer}
66
1
70
0
{vertices}
0
SEQEND"""


def _dxf_text(text: str, x: float, y: float, size: float, layer: str, width_factor: float = 1.0) -> str:
    clean_text = text.replace("\r", " ").replace("\n", " ").replace("\\", "/")
    width_factor_markup = ""
    if width_factor > 0 and abs(width_factor - 1.0) > 0.0001:
        width_factor_markup = f"\n41\n{width_factor:.4f}"
    return f"""0
TEXT
8
{layer}
10
{x:.4f}
20
{y:.4f}
30
0.0
40
{size:.4f}{width_factor_markup}
1
{clean_text}
7
STANDARD
72
1
11
{x:.4f}
21
{y:.4f}"""


def _identity_matrix() -> tuple[float, float, float, float, float, float]:
    return 1.0, 0.0, 0.0, 1.0, 0.0, 0.0


def _parse_transform(value: str) -> tuple[float, float, float, float, float, float]:
    matrix = _identity_matrix()
    for name, raw_args in re.findall(r"([a-zA-Z]+)\(([^)]*)\)", value):
        args = [float(part) for part in re.split(r"[\s,]+", raw_args.strip()) if part]
        local = _identity_matrix()
        if name == "matrix" and len(args) == 6:
            local = tuple(args)  # type: ignore[assignment]
        elif name == "translate" and args:
            local = (1.0, 0.0, 0.0, 1.0, args[0], args[1] if len(args) > 1 else 0.0)
        elif name == "scale" and args:
            sy = args[1] if len(args) > 1 else args[0]
            local = (args[0], 0.0, 0.0, sy, 0.0, 0.0)
        elif name == "rotate" and args:
            angle = math.radians(args[0])
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            local = (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)
            if len(args) == 3:
                cx, cy = args[1], args[2]
                local = _multiply_matrix(
                    _multiply_matrix((1.0, 0.0, 0.0, 1.0, cx, cy), local),
                    (1.0, 0.0, 0.0, 1.0, -cx, -cy),
                )
        matrix = _multiply_matrix(matrix, local)
    return matrix


def _multiply_matrix(
    left: tuple[float, float, float, float, float, float],
    right: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    a1, b1, c1, d1, e1, f1 = left
    a2, b2, c2, d2, e2, f2 = right
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _apply_matrix(matrix: tuple[float, float, float, float, float, float], x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return a * x + c * y + e, b * x + d * y + f


def _cubic_point(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    x3: float,
    y3: float,
    t: float,
) -> tuple[float, float]:
    mt = 1 - t
    return (
        mt**3 * x0 + 3 * mt**2 * t * x1 + 3 * mt * t**2 * x2 + t**3 * x3,
        mt**3 * y0 + 3 * mt**2 * t * y1 + 3 * mt * t**2 * y2 + t**3 * y3,
    )


def _quadratic_point(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    t: float,
) -> tuple[float, float]:
    mt = 1 - t
    return (
        mt**2 * x0 + 2 * mt * t * x1 + t**2 * x2,
        mt**2 * y0 + 2 * mt * t * y1 + t**2 * y2,
    )


def _tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _png_petal_boxes(flower: int) -> list[tuple[int, int, int, int]]:
    if flower == 1:
        return [
            (515, 170, 685, 430),
            (515, 600, 685, 860),
            (300, 435, 560, 605),
            (640, 435, 900, 605),
        ]
    return [
        (495, 165, 705, 375),
        (725, 315, 935, 525),
        (725, 585, 935, 795),
        (495, 665, 705, 875),
        (265, 585, 475, 795),
        (265, 315, 475, 525),
    ]
