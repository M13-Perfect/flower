from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import math
import re
import unicodedata

from models import EngravingLayout


@dataclass(frozen=True)
class Bounds:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top


@dataclass(frozen=True)
class TextLayoutResult:
    did_fit: bool
    final_font_size: int
    line_count: int
    text_bounds: Bounds
    safe_area_bounds: Bounds
    layout_confidence: float
    warnings: list[str]
    lines: tuple[str, ...]
    personalization_type: str
    draw_x: float = 0.0
    draw_y: float = 0.0
    ink_bounds: Bounds | None = None
    line_origins: tuple[tuple[float, float], ...] = ()


SAFE_MARGIN_X = 120
SAFE_MARGIN_Y = 70
MESSAGE_MIN_FONT_SIZE = 36
NAME_MIN_FONT_SIZE = 48
LINE_HEIGHT_RATIO = 1.18


def layout_personalization_text(
    text: str,
    layout: EngravingLayout,
    personalization_type: str = "unknown",
    font_path: Path | str | None = None,
) -> TextLayoutResult:
    """计算雕刻文字布局；预览、SVG、DXF、PNG 共用，避免导出与画板不一致。"""
    raw_text = "" if text is None else str(text)
    clean_text = raw_text.strip()
    safe_area = _safe_area(layout)
    clean_type = _resolved_personalization_type(clean_text, personalization_type)
    if clean_type == "message":
        return _layout_message(clean_text, layout, safe_area, font_path)
    return _layout_name(raw_text, layout, safe_area, font_path)


def _safe_area(layout: EngravingLayout) -> Bounds:
    return Bounds(
        SAFE_MARGIN_X,
        SAFE_MARGIN_Y,
        layout.canvas_width - SAFE_MARGIN_X,
        layout.canvas_height - SAFE_MARGIN_Y,
    )


def _layout_name(
    text: str,
    layout: EngravingLayout,
    safe_area: Bounds,
    font_path: Path | str | None,
) -> TextLayoutResult:
    slot = _name_slot(layout, safe_area)
    min_size = min(8, max(1, int(slot.height / LINE_HEIGHT_RATIO)))
    max_size = max(min_size, int(slot.height / LINE_HEIGHT_RATIO))
    font_size = _largest_single_line_font(text, max_size, min_size, slot, font_path)
    ink_bounds = measure_text_ink_bbox(text, font_size, font_path)
    bounds, draw_x, draw_y = _position_ink_bounds_in_slot(ink_bounds, slot)
    warnings: list[str] = []
    did_fit = _bounds_within(bounds, safe_area)
    if not did_fit:
        warnings.append("文字超出安全区域，请缩短文字或手动调整布局。")
    return TextLayoutResult(
        did_fit=did_fit,
        final_font_size=font_size,
        line_count=1,
        text_bounds=bounds,
        safe_area_bounds=safe_area,
        layout_confidence=_layout_confidence(did_fit, warnings),
        warnings=warnings,
        lines=(text,),
        personalization_type="name",
        draw_x=draw_x,
        draw_y=draw_y,
        ink_bounds=ink_bounds,
        line_origins=((draw_x, draw_y),),
    )


def _layout_message(
    text: str,
    layout: EngravingLayout,
    safe_area: Bounds,
    font_path: Path | str | None,
) -> TextLayoutResult:
    slot = _message_slot(layout, safe_area)
    best_lines: tuple[str, ...] = (text,)
    best_font = MESSAGE_MIN_FONT_SIZE
    low, high = MESSAGE_MIN_FONT_SIZE, min(int(slot.height / LINE_HEIGHT_RATIO), 160)
    while low <= high:
        candidate = (low + high) // 2
        lines = _wrap_text(text, candidate, slot.width, font_path)
        if _lines_fit(lines, candidate, slot, font_path):
            best_font = candidate
            best_lines = tuple(lines)
            low = candidate + 1
        else:
            high = candidate - 1

    bounds, line_origins = _multiline_bounds(best_lines, best_font, slot, font_path)
    did_fit = _bounds_within(bounds, slot) and _bounds_within(bounds, safe_area)
    warnings: list[str] = []
    if not did_fit:
        warnings.append("长文本已缩到最小字号但仍超出安全区域，请缩短内容或手动调整布局。")
    return TextLayoutResult(
        did_fit=did_fit,
        final_font_size=best_font,
        line_count=len(best_lines),
        text_bounds=bounds,
        safe_area_bounds=safe_area,
        layout_confidence=_layout_confidence(did_fit, warnings),
        warnings=warnings,
        lines=best_lines,
        personalization_type="message",
        draw_x=line_origins[0][0] if line_origins else bounds.left,
        draw_y=line_origins[0][1] if line_origins else bounds.top,
        ink_bounds=bounds,
        line_origins=line_origins,
    )


def _resolved_personalization_type(text: str, personalization_type: str) -> str:
    clean_type = (personalization_type or "unknown").strip().casefold()
    if clean_type in {"name", "message"}:
        return clean_type
    words = re.findall(r"[\w']+", text, flags=re.UNICODE)
    sentence_punctuation = re.search(r"[.!?;\u3002\uff01\uff1f\u2026]", text)
    if len(words) >= 5 or (sentence_punctuation and len(words) >= 3):
        return "message"
    return "name"


def _name_slot(layout: EngravingLayout, safe_area: Bounds) -> Bounds:
    # text_x/text_y 是用户方框左上角；真实字形墨迹在方框内居中适配。
    requested = Bounds(
        layout.text_x,
        layout.text_y,
        layout.text_x + layout.text_width,
        layout.text_y + layout.text_height,
    )
    return _clip_bounds(requested, safe_area)


def _message_slot(layout: EngravingLayout, safe_area: Bounds) -> Bounds:
    requested = Bounds(
        layout.text_x,
        layout.text_y,
        layout.text_x + layout.text_width,
        layout.text_y + layout.text_height,
    )
    return _clip_bounds(requested, safe_area)


def _clip_bounds(bounds: Bounds, safe_area: Bounds) -> Bounds:
    left = max(safe_area.left, bounds.left)
    top = max(safe_area.top, bounds.top)
    right = min(safe_area.right, bounds.right)
    bottom = min(safe_area.bottom, bounds.bottom)
    if right <= left:
        right = min(safe_area.right, left + 1)
    if bottom <= top:
        bottom = min(safe_area.bottom, top + 1)
    return Bounds(left, top, right, bottom)


def _largest_single_line_font(
    text: str,
    max_size: int,
    min_size: int,
    slot: Bounds,
    font_path: Path | str | None,
) -> int:
    if not text.strip():
        return min_size
    low, high = min_size, max_size
    best = min_size
    while low <= high:
        candidate = (low + high) // 2
        bbox = measure_text_ink_bbox(text, candidate, font_path)
        if bbox.width <= slot.width and bbox.height <= slot.height:
            best = candidate
            low = candidate + 1
        else:
            high = candidate - 1
    return best


def _wrap_text(text: str, font_size: int, max_width: float, font_path: Path | str | None) -> list[str]:
    tokens = _wrap_tokens(text)
    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = _join_token(current, token)
        if current and _measure_text(candidate, font_size, font_path) > max_width:
            lines.append(current.rstrip())
            current = token.lstrip()
        else:
            current = candidate
    if current:
        lines.append(current.rstrip())
    return lines or [""]


def _wrap_tokens(text: str) -> list[str]:
    return re.findall(r"\S+\s*", text)


def _join_token(current: str, token: str) -> str:
    if not current:
        return token
    return current + token


def _lines_fit(lines: list[str], font_size: int, slot: Bounds, font_path: Path | str | None) -> bool:
    if _line_height(font_size) * len(lines) > slot.height:
        return False
    return all(measure_text_ink_bbox(line, font_size, font_path).width <= slot.width for line in lines)


def _multiline_bounds(
    lines: tuple[str, ...],
    font_size: int,
    slot: Bounds,
    font_path: Path | str | None,
) -> tuple[Bounds, tuple[tuple[float, float], ...]]:
    line_bboxes = [measure_text_ink_bbox(line, font_size, font_path) for line in lines]
    width = max((bbox.width for bbox in line_bboxes), default=0.0)
    height = _line_height(font_size) * len(lines)
    left = slot.left + (slot.width - width) / 2
    top = slot.top + (slot.height - height) / 2
    origins: list[tuple[float, float]] = []
    for index, bbox in enumerate(line_bboxes):
        line_left = slot.left + (slot.width - bbox.width) / 2
        line_top = top + index * _line_height(font_size)
        origins.append((line_left - bbox.left, line_top - bbox.top))
    return Bounds(left, top, left + width, top + height), tuple(origins)


def _position_ink_bounds_in_slot(ink_bounds: Bounds, slot: Bounds) -> tuple[Bounds, float, float]:
    center_x = (slot.left + slot.right) / 2
    center_y = (slot.top + slot.bottom) / 2
    if ink_bounds.width <= 0 or ink_bounds.height <= 0:
        draw_x = center_x - ink_bounds.left
        draw_y = center_y - ink_bounds.top
        return Bounds(center_x, center_y, center_x, center_y), draw_x, draw_y
    left = slot.left + (slot.width - ink_bounds.width) / 2
    top = slot.top + (slot.height - ink_bounds.height) / 2
    draw_x = left - ink_bounds.left
    draw_y = top - ink_bounds.top
    return Bounds(left, top, left + ink_bounds.width, top + ink_bounds.height), draw_x, draw_y


def _centered_bounds(center_x: float, center_y: float, width: float, height: float) -> Bounds:
    return Bounds(center_x - width / 2, center_y - height / 2, center_x + width / 2, center_y + height / 2)


def _bounds_within(inner: Bounds, outer: Bounds) -> bool:
    return (
        inner.left >= outer.left
        and inner.right <= outer.right
        and inner.top >= outer.top
        and inner.bottom <= outer.bottom
    )


def _line_height(font_size: int) -> float:
    return font_size * LINE_HEIGHT_RATIO


def measure_text_ink_bbox(text: str, font_size: int, font_path: Path | str | None = None) -> Bounds:
    return _measure_text_ink_bbox_cached(text or "", max(1, int(font_size)), _font_path_key(font_path))


@lru_cache(maxsize=2048)
def _measure_text_ink_bbox_cached(text: str, font_size: int, font_path_key: str) -> Bounds:
    if text == "":
        return Bounds(0.0, 0.0, 0.0, 0.0)
    try:
        from PIL import Image, ImageDraw, ImageFont

        font = _load_pillow_font(ImageFont, font_path_key, font_size)
        draw = ImageDraw.Draw(Image.new("L", (1, 1), 0))
        left, top, right, bottom = (float(value) for value in draw.textbbox((0, 0), text, font=font))
        if right > left and bottom > top:
            raster_bounds = _rasterized_ink_bbox(Image, ImageDraw, font, text, Bounds(left, top, right, bottom), font_size)
            if raster_bounds is not None:
                return raster_bounds
            return Bounds(left, top, right, bottom)
        if text.strip():
            length = float(draw.textlength(text, font=font))
            ascent, descent = _font_metrics(font, font_size)
            return Bounds(0.0, -ascent, max(1.0, length), descent)
        return Bounds(0.0, 0.0, max(0.0, float(draw.textlength(text, font=font))), 0.0)
    except Exception:
        if not text.strip():
            return Bounds(0.0, 0.0, 0.0, 0.0)
        return Bounds(0.0, 0.0, _measure_text(text, font_size), _line_height(font_size))


def _rasterized_ink_bbox(image_module, image_draw_module, font, text: str, bbox: Bounds, font_size: int) -> Bounds | None:
    """把文字实际绘制到透明蒙版后取非透明像素 bbox，确保布局按黑色字形墨迹而不是字体行框计算。"""
    margin = max(4, math.ceil(font_size * 0.08))
    width = max(1, math.ceil(bbox.width) + margin * 2)
    height = max(1, math.ceil(bbox.height) + margin * 2)
    mask = image_module.new("L", (width, height), 0)
    draw = image_draw_module.Draw(mask)
    origin_x = margin - bbox.left
    origin_y = margin - bbox.top
    draw.text((origin_x, origin_y), text, font=font, fill=255)
    ink = mask.getbbox()
    if ink is None:
        return None
    left, top, right, bottom = (float(value) for value in ink)
    return Bounds(left - origin_x, top - origin_y, right - origin_x, bottom - origin_y)


def _load_pillow_font(image_font_module, font_path_key: str, font_size: int):
    if font_path_key:
        try:
            return image_font_module.truetype(font_path_key, font_size)
        except Exception:
            pass
    try:
        return image_font_module.load_default(size=font_size)
    except TypeError:
        return image_font_module.load_default()


def _font_metrics(font, font_size: int) -> tuple[float, float]:
    try:
        ascent, descent = font.getmetrics()
        return float(ascent), float(descent)
    except Exception:
        return float(font_size), font_size * 0.25


def _font_path_key(font_path: Path | str | None) -> str:
    return str(Path(font_path)) if font_path else ""


def _measure_text(text: str, font_size: int, font_path: Path | str | None = None) -> float:
    if font_path is not None:
        return max(0.0, measure_text_ink_bbox(text, font_size, font_path).width)
    return sum(_char_width(char) for char in text) * font_size


def _char_width(char: str) -> float:
    if char.isspace():
        return 0.32
    if unicodedata.category(char).startswith("P"):
        return 0.34
    if unicodedata.east_asian_width(char) in {"W", "F"}:
        return 0.95
    if unicodedata.category(char).startswith("S"):
        return 0.95
    return 0.52


def _layout_confidence(did_fit: bool, warnings: list[str]) -> float:
    if did_fit and not warnings:
        return 1.0
    if did_fit:
        return 0.85
    return 0.45
