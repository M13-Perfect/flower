from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import itertools
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
    render_scale_x: float = 1.0
    render_scale_y: float = 1.0


SAFE_MARGIN_X = 120
SAFE_MARGIN_Y = 70
MESSAGE_MIN_FONT_SIZE = 36
NAME_MIN_FONT_SIZE = 48
LINE_HEIGHT_RATIO = 1.18
# 名字墨迹高度占文本框高度的比例：让不同订单的名字视觉大小一致（而不是各自撑满框）。
NAME_HEIGHT_RATIO = 0.62
# 量字基准字号：在该字号下测墨迹，再线性换算到目标字号，避免反复栅格化。
_REF_FONT_SIZE = 200
# 名字自动断行（图1 升级）：长名按词均衡断成多行，让字号放大、居中、不贴边。
NAME_MAX_LINES = 2  # 名字最多自动断 2 行（再多影响雕刻可读性）
NAME_WRAP_GAIN = 0.08  # 多一行至少要让字号大 8% 才换行（短名不无谓换行）
NAME_BLOCK_HEIGHT_RATIO = 0.86  # 多行名字墨迹块占框高比例（比单行 0.62 更满）
NAME_SIDE_PAD_RATIO = 0.04  # 名字两侧安全边距占框宽比例（不贴边）


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


@dataclass(frozen=True)
class BoxTextFit:
    """文本框内统一排版结果（box 本地坐标）。预览/PNG/矢量导出共用同一份，保证所见即所得。"""

    font_size: int
    lines: tuple[str, ...]
    # 每行 (pen_x, baseline_y)：anchor="ls"（左侧+基线）绘制锚点；矢量端把笔位放这里逐字推进。
    origins: tuple[tuple[float, float], ...]
    did_fit: bool
    warnings: tuple[str, ...]
    ink_bounds: Bounds | None


def fit_text_box(
    text: str,
    box_width: float,
    box_height: float,
    font_path: Path | str | None = None,
    *,
    personalization_type: str = "auto",
    font_size_cap: float | None = None,
    align: str = "center",
    vertical_align: str = "middle",
    line_spacing: float = LINE_HEIGHT_RATIO,
    letter_spacing: float = 0.0,
) -> BoxTextFit:
    """文本框内统一适配：选最大等比字号 + 断行 + 每行基线锚点（box 本地像素）。

    这是“排版只算一次”的单一入口：TextRenderer（Pillow 预览/PNG）与桌面导出（烘给
    dxf/svg 矢量端）都调用它，拿到同一组 font_size/lines/origins，从而预览==导出。
    返回的 origins 与 lines 严格一一对应（零墨迹行也占一个锚点）。
    """
    box_w = max(1.0, float(box_width))
    box_h = max(1.0, float(box_height))
    raw = "" if text is None else str(text)
    clean = raw.strip()
    ptype = _resolved_personalization_type(clean, personalization_type)
    if ptype == "message":
        font_size, lines = _fit_message_box(raw, box_w, box_h, font_path, font_size_cap)
    else:
        font_size, lines = _fit_name_layout(raw, box_w, box_h, font_path, font_size_cap)
    origins, ink_union = _placement_origins_ls(
        lines, font_size, box_w, box_h, font_path,
        align=align, vertical_align=vertical_align, line_spacing=line_spacing,
        letter_spacing=letter_spacing,
    )
    # ink_union 为 None 表示没有可见墨迹（空白/不可见字符）——视为已适配，不报警告。
    did_fit = ink_union is None or (
        ink_union.left >= -0.5
        and ink_union.top >= -0.5
        and ink_union.right <= box_w + 0.5
        and ink_union.bottom <= box_h + 0.5
    )
    warnings: tuple[str, ...] = () if did_fit else ("文字超出文本框，请缩短文字或调整文本框。",)
    return BoxTextFit(int(max(1, font_size)), tuple(lines), tuple(origins), bool(did_fit), warnings, ink_union)


def _fit_name_font_size(
    text: str,
    box_w: float,
    box_h: float,
    font_path: Path | str | None,
    cap: float | None = None,
) -> int:
    """单行名字的等比字号：墨迹高度取框高的 NAME_HEIGHT_RATIO，太宽则等比缩到框宽。"""
    box_w = max(1.0, float(box_w))
    box_h = max(1.0, float(box_h))
    if not str(text).strip():
        return max(1, min(NAME_MIN_FONT_SIZE, int(box_h / LINE_HEIGHT_RATIO) or 1))
    ink = measure_text_ink_bbox(text, _REF_FONT_SIZE, font_path)
    if ink.width <= 0 or ink.height <= 0:
        return max(1, min(NAME_MIN_FONT_SIZE, int(box_h / LINE_HEIGHT_RATIO) or 1))
    fit_by_height = _REF_FONT_SIZE * (box_h * NAME_HEIGHT_RATIO) / ink.height
    fit_by_width = _REF_FONT_SIZE * box_w / ink.width
    size = min(fit_by_height, fit_by_width)
    if cap and cap > 0:
        size = min(size, float(cap))
    # 下限优先保证装得下：宽度受限的长名字可以低于 NAME_MIN_FONT_SIZE。
    size = max(size, min(float(NAME_MIN_FONT_SIZE), fit_by_width))
    size = max(1, int(size))
    # 栅格化/线性外推有误差：按真实墨迹校正，确保最终字号下墨迹仍装进框（宁可略小，绝不溢出）。
    for _ in range(8):
        ink_now = measure_text_ink_bbox(text, size, font_path)
        if ink_now.width <= box_w and ink_now.height <= box_h:
            break
        shrink = min(box_w / max(1.0, ink_now.width), box_h / max(1.0, ink_now.height))
        next_size = max(1, int(size * shrink))
        size = next_size if next_size < size else size - 1
        if size <= 1:
            break
    return max(1, size)


def _balanced_wrap(words: list[str], line_count: int, font_path: Path | str | None) -> list[str]:
    """把词切成 line_count 行（单词不拆），最小化最宽行的墨迹宽度（行更均衡，字号能更大）。"""
    n = len(words)
    line_count = max(1, min(line_count, n))
    if line_count == 1:
        return [" ".join(words)]

    def line_width(start: int, end: int) -> float:
        return measure_text_ink_bbox(" ".join(words[start:end]), _REF_FONT_SIZE, font_path).width

    best_cuts: tuple[int, ...] = tuple(range(1, line_count))  # 兜底：每行至少一词
    best_max = float("inf")
    for cuts in itertools.combinations(range(1, n), line_count - 1):
        bounds = (0, *cuts, n)
        widest = max(line_width(bounds[i], bounds[i + 1]) for i in range(line_count))
        if widest < best_max:
            best_max, best_cuts = widest, cuts
    bounds = (0, *best_cuts, n)
    return [" ".join(words[bounds[i]:bounds[i + 1]]) for i in range(line_count)]


def _fit_lines_name_size(
    lines: list[str], box_w: float, box_h: float, font_path: Path | str | None, cap: float | None = None
) -> int:
    """多行名字的等比字号：最宽行装进框宽，墨迹块高占框高 NAME_BLOCK_HEIGHT_RATIO。"""
    box_w = max(1.0, float(box_w))
    box_h = max(1.0, float(box_h))
    measured = [measure_text_ink_bbox(line, _REF_FONT_SIZE, font_path) for line in lines]
    widths = [m.width for m in measured if m.width > 0]
    heights = [m.height for m in measured if m.height > 0]
    if not widths or not heights:
        return _fit_name_font_size(" ".join(lines), box_w, box_h, font_path, cap)
    line_count = len(lines)
    block_h_ref = (line_count - 1) * _REF_FONT_SIZE * LINE_HEIGHT_RATIO + max(heights)
    fit_by_width = _REF_FONT_SIZE * box_w / max(widths)
    fit_by_height = _REF_FONT_SIZE * (box_h * NAME_BLOCK_HEIGHT_RATIO) / block_h_ref
    size = min(fit_by_width, fit_by_height)
    if cap and cap > 0:
        size = min(size, float(cap))
    return max(1, int(size))


def _fit_name_layout(
    text: str, box_w: float, box_h: float, font_path: Path | str | None, cap: float | None = None
) -> tuple[int, list[str]]:
    """名字排版（图1 升级）：在 1..NAME_MAX_LINES 行里挑能放最大字号的均衡断行方案。

    单词/空名只能单行；多行仅当字号比上一方案大 NAME_WRAP_GAIN 才采用（短名不无谓换行）。
    宽度留 NAME_SIDE_PAD_RATIO 安全边距；最终按真实墨迹 clamp 到全框，绝不溢出。
    """
    box_w = max(1.0, float(box_w))
    box_h = max(1.0, float(box_h))
    raw = str(text)
    words = raw.split()
    usable_w = max(1.0, box_w * (1.0 - 2 * NAME_SIDE_PAD_RATIO))
    if len(words) <= 1:
        return _fit_name_font_size(raw, usable_w, box_h, font_path, cap), [raw]

    best_size = -1.0
    best_lines: list[str] = [raw]
    for line_count in range(1, min(NAME_MAX_LINES, len(words)) + 1):
        if line_count == 1:
            lines = [raw]
            size = float(_fit_name_font_size(raw, usable_w, box_h, font_path, cap))
        else:
            lines = _balanced_wrap(words, line_count, font_path)
            size = float(_fit_lines_name_size(lines, usable_w, box_h, font_path, cap))
        # 从单行起步，多一行需比当前最优大 NAME_WRAP_GAIN 才采用（短名不乱换行）。
        if size > best_size * (1.0 + NAME_WRAP_GAIN):
            best_size, best_lines = size, lines

    # 最终按真实全框（不含边距）clamp，宁可略小绝不溢出。
    slot = Bounds(0.0, 0.0, box_w, box_h)
    size_int = max(1, int(best_size))
    while size_int > 1 and not _lines_fit(best_lines, size_int, slot, font_path):
        size_int -= 1
    return size_int, best_lines


def _fit_message_box(
    text: str,
    box_w: float,
    box_h: float,
    font_path: Path | str | None,
    cap: float | None = None,
) -> tuple[int, list[str]]:
    """多行祝福语：二分最大字号 + 分词换行（沿用既有逻辑，box 即 slot）。cap 为字号上限。"""
    slot = Bounds(0.0, 0.0, max(1.0, float(box_w)), max(1.0, float(box_h)))
    best_lines: tuple[str, ...] = (text,)
    best_font = MESSAGE_MIN_FONT_SIZE
    high_limit = min(int(slot.height / LINE_HEIGHT_RATIO), 160)
    if cap and cap > 0:
        high_limit = min(high_limit, int(cap))
    low, high = MESSAGE_MIN_FONT_SIZE, max(MESSAGE_MIN_FONT_SIZE, high_limit)
    while low <= high:
        candidate = (low + high) // 2
        lines = _wrap_text(text, candidate, slot.width, font_path)
        if _lines_fit(lines, candidate, slot, font_path):
            best_font = candidate
            best_lines = tuple(lines)
            low = candidate + 1
        else:
            high = candidate - 1
    return best_font, list(best_lines)


def _placement_origins_ls(
    lines: list[str],
    font_size: int,
    box_w: float,
    box_h: float,
    font_path: Path | str | None,
    *,
    align: str = "center",
    vertical_align: str = "middle",
    line_spacing: float = LINE_HEIGHT_RATIO,
    letter_spacing: float = 0.0,
) -> tuple[list[tuple[float, float]], Bounds | None]:
    """按真实墨迹把多行文本居中放进框，返回**每行**一个 anchor='ls' 锚点 (pen_x, baseline_y)。

    锚点与 lines 严格一一对应（零墨迹行也占位），矢量端按位置取用不会错位。
    letter_spacing!=0 时字间距让墨迹整体变宽，居中按补偿后的总宽计算，避免导出右偏。
    """
    box_w = max(1.0, float(box_w))
    box_h = max(1.0, float(box_h))
    font_size = max(1, int(font_size))
    ascent, _descent = _font_ascent_descent(font_path, font_size)
    line_height = font_size * line_spacing
    per_line: list[tuple[float, float]] = []  # 每行 (pen_x, baseline_la)，与 lines 一一对应
    union_left = union_top = float("inf")
    union_right = union_bottom = float("-inf")
    for index, line in enumerate(lines):
        baseline_la = ascent + index * line_height  # 基线在 la 空间（顶端=0）
        ink = measure_text_ink_bbox(line, font_size, font_path)
        if ink.width <= 0 or ink.height <= 0:
            # 零墨迹行（空行/不可见字符）：仍占一个锚点，保持 lines↔origins 一一对应。
            default_pen = 0.0 if align == "left" else (box_w if align == "right" else box_w / 2)
            per_line.append((default_pen, baseline_la))
            continue
        spacing_pad = max(0, len(line) - 1) * float(letter_spacing)
        spread_width = ink.width + spacing_pad
        if align == "center":
            pen_x = (box_w - spread_width) / 2 - ink.left
        elif align == "right":
            pen_x = box_w - ink.right - spacing_pad
        else:
            pen_x = -ink.left
        per_line.append((pen_x, baseline_la))
        union_left = min(union_left, pen_x + ink.left)
        union_right = max(union_right, pen_x + ink.left + spread_width)
        union_top = min(union_top, ink.top + index * line_height)
        union_bottom = max(union_bottom, ink.bottom + index * line_height)
    if union_bottom <= union_top:  # 全部为零墨迹行：无需竖直居中
        return [(pen_x, baseline_la) for (pen_x, baseline_la) in per_line], None
    block_height = union_bottom - union_top
    if vertical_align in ("middle", "center"):
        shift_y = (box_h - block_height) / 2 - union_top
    elif vertical_align == "bottom":
        shift_y = box_h - block_height - union_top
    else:
        shift_y = -union_top
    origins = [(pen_x, baseline_la + shift_y) for (pen_x, baseline_la) in per_line]
    ink_union = Bounds(union_left, union_top + shift_y, union_right, union_bottom + shift_y)
    return origins, ink_union


def _font_ascent_descent(font_path: Path | str | None, font_size: int) -> tuple[float, float]:
    try:
        from PIL import ImageFont

        font = _load_pillow_font(ImageFont, _font_path_key(font_path), max(1, int(font_size)))
        ascent, descent = font.getmetrics()
        return float(ascent), float(descent)
    except Exception:
        return float(font_size), float(font_size) * 0.25


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
    # 等比适配：选最大字号让真实墨迹放进文本框（绝不非等比拉伸花体），再把墨迹居中。
    font_size = _fit_name_font_size(text, slot.width, slot.height, font_path)
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
        render_scale_x=1.0,
        render_scale_y=1.0,
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
