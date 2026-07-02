"""末尾爱心「独立图层·锚定文字」的解析与维护——单一真源。

爱心从旧的「死贴在文字墨迹后」(textLayout.endingHeart) 改造为独立 AnchoredHeartLayer：
面板可单独选中、可调 mm 间距/上下偏移/大小，但仍锚定文字、每单自动跟随。

本模块负责把锚定关系「解析」成画布绝对几何：
- ``resolve_anchored_hearts``：幂等纯函数（只读锚定文字、只写爱心图层 x/y/width/height +
  锚定文字的 ending_heart_detached 标志）。须在「预览重绘前 / 订单 seed 后 / 导出前」统一调用，
  保证 PNG 预览 / 矢量 SVG / DXF 三端落点一致。
- ``ensure_anchored_hearts`` / ``ensure_anchored_heart_for`` / ``remove_anchored_heart_for``：
  按文字图层的 ending_heart 标志自动补建 / 移除爱心图层（选 Font 4 / 旧存档迁移共用）。

零回归：gap_mm / size_mm 为 None 时回落旧 ratio（ENDING_HEART_*_RATIO * 字号），且文字 fit 仍按
ENDING_HEART_ADVANCE_RATIO 给爱心让位——名字位置与旧路径不变，爱心几何与旧 place_ending_heart
逐像素一致（见 tests/test_text_wysiwyg_consistency.py 的零回归护栏）。
"""
from __future__ import annotations

from glyph_service import rebuild_render_text
from heart_symbol import HEART_ASPECT
from models import (
    AnchoredHeartLayer,
    Document,
    TextLayer,
    add_anchored_heart_layer,
)
from text_layout import (
    ENDING_HEART_ADVANCE_RATIO,
    ENDING_HEART_GAP_RATIO,
    ENDING_HEART_SIZE_RATIO,
    fit_text_box,
    place_ending_heart,
)

# 画布像素→物理 mm 的默认基准，**必须**与 desktop_export.DEFAULT_PHYSICAL_WIDTH_MM 一致，
# 否则用户填的 mm 间距在 PNG 预览与 DXF 导出之间会对不上。
DEFAULT_PHYSICAL_WIDTH_MM = 80.0


def compute_text_fit(layer: TextLayer):
    """统一计算文字图层的排版结果（BoxTextFit）：resolve 与 desktop_export._text_layer 共用，杜绝漂移。

    与导出端逐字段对齐：render_text 现算（rebuild_render_text）、box 用 text_box_*、font_size 作 cap、
    ending_heart 时按 ENDING_HEART_ADVANCE_RATIO 给末尾爱心预留推进量（名字+爱心一起适配）。
    """
    source_text = layer.original_text or layer.text or ""
    try:
        render_text, _overrides, _warnings = rebuild_render_text(
            source_text,
            layer.glyph_overrides or {},
            font_path=layer.font_path,
            text_layer_id=str(layer.id),
        )
    except Exception:
        render_text = getattr(layer, "render_text", "") or source_text
    box_width = float(getattr(layer, "text_box_width", layer.width) or layer.width)
    box_height = float(getattr(layer, "text_box_height", layer.height) or layer.height)
    advance = ENDING_HEART_ADVANCE_RATIO if bool(getattr(layer, "ending_heart", False)) else 0.0
    return fit_text_box(
        render_text,
        box_width,
        box_height,
        layer.font_path,
        personalization_type="auto",
        font_size_cap=float(layer.font_size or 0) or None,
        align=(layer.align or "center").casefold(),
        vertical_align=(getattr(layer, "vertical_align", "middle") or "middle").casefold(),
        line_spacing=float(layer.line_spacing or 1),
        letter_spacing=float(layer.letter_spacing or layer.tracking or 0),
        ending_advance_ratio=advance,
    )


def resolve_anchored_hearts(document: Document, *, physical_width_mm: float | None = None) -> None:
    """就地把每个 AnchoredHeartLayer 的 x/y/width/height 按其锚定文字图层重算写回（幂等）。

    并把「已被独立爱心接管」的锚定文字图层标记 ending_heart_detached=True，
    使其预览/导出不再自己贴/烘爱心（但仍按 ending_advance 让位，名字位置不变）。
    """
    width_mm = float(physical_width_mm) if physical_width_mm and physical_width_mm > 0 else DEFAULT_PHYSICAL_WIDTH_MM
    canvas_width = max(1, int(getattr(document, "canvas_width", 0) or 1))
    px_per_mm = canvas_width / width_mm

    detached_text_ids: set[str] = set()
    for heart in document.iter_all_layers():
        if not isinstance(heart, AnchoredHeartLayer):
            continue
        anchor = document.layer_by_id(heart.anchor_layer_id)
        if not isinstance(anchor, TextLayer) or not getattr(anchor, "visible", True):
            # 锚定文字缺失/不可见：藏起爱心，避免乱飘（不影响其它图层）。
            heart.visible = False
            continue

        fit = compute_text_fit(anchor)
        # 爱心高（像素）：size_mm>0 用显式 mm；否则回落旧 ratio*字号（零回归）。
        if heart.size_mm is not None and float(heart.size_mm) > 0:
            heart_h_px = float(heart.size_mm) * px_per_mm
        else:
            heart_h_px = ENDING_HEART_SIZE_RATIO * fit.font_size
        heart_h_px = max(1.0, heart_h_px)

        # 复用 place_ending_heart 拿 box 本地「末行墨迹右缘 + 竖直顶点」（gap 交由 mm 接管，故传 0）。
        size_ratio = heart_h_px / float(max(1, fit.font_size))
        placement = place_ending_heart(fit, anchor.font_path, size_ratio=size_ratio, gap_ratio=0.0)
        # 锚定文字一旦存在爱心图层，无论末行有无墨迹都抑制其自烘爱心（避免双爱心）。
        detached_text_ids.add(anchor.id)
        if placement is None:
            heart.visible = False  # 末行无墨迹（空名）→ 无处可缀
            continue

        x_local, y_top_local, _scale = placement
        gap_px = float(heart.gap_mm) * px_per_mm if heart.gap_mm is not None else ENDING_HEART_GAP_RATIO * fit.font_size
        offset_y_px = float(heart.offset_y_mm or 0.0) * px_per_mm
        heart_w_px = heart_h_px * HEART_ASPECT
        local_x = x_local + gap_px
        local_y = y_top_local + offset_y_px

        # box 本地 → 画布绝对（文字图层 box→canvas 为平移 + 缩放，与导出端文字矩阵同构）。
        heart.x = float(anchor.x + local_x * float(anchor.scale_x or 1.0))
        heart.y = float(anchor.y + local_y * float(anchor.scale_y or 1.0))
        heart.width = float(heart_w_px)
        heart.height = float(heart_h_px)
        heart.scale_x = 1.0  # 几何已折进 width/height
        heart.scale_y = 1.0
        heart.visible = True
        heart.fill_color = getattr(anchor, "fill_color", "") or getattr(anchor, "color", "") or "#111111"

    for layer in document.iter_all_layers():
        if isinstance(layer, TextLayer):
            layer.ending_heart_detached = layer.id in detached_text_ids


def _heart_for(document: Document, text_layer_id: str) -> AnchoredHeartLayer | None:
    return next(
        (
            layer
            for layer in document.iter_all_layers()
            if isinstance(layer, AnchoredHeartLayer) and layer.anchor_layer_id == text_layer_id
        ),
        None,
    )


def ensure_anchored_heart_for(document: Document, text_layer: TextLayer) -> AnchoredHeartLayer:
    """文字图层若还没有锚定爱心则补建一个（颜色随文字色），已有则原样返回。"""
    existing = _heart_for(document, text_layer.id)
    if existing is not None:
        return existing
    fill = getattr(text_layer, "fill_color", "") or getattr(text_layer, "color", "") or "#111111"
    return add_anchored_heart_layer(document, anchor_layer_id=text_layer.id, fill_color=fill)


def remove_anchored_heart_for(document: Document, text_layer_id: str) -> bool:
    """移除锚定到该文字图层的爱心图层（切走 Font 4 时调）。返回是否有删除。"""
    before = len(document.layers)
    document.layers = [
        layer
        for layer in document.layers
        if not (isinstance(layer, AnchoredHeartLayer) and layer.anchor_layer_id == text_layer_id)
    ]
    removed = len(document.layers) != before
    if removed:
        if document.selected_layer_id and document.layer_by_id(document.selected_layer_id) is None:
            document.selected_layer_id = text_layer_id  # 选择回落到锚定文字
        document.normalize_z_indexes()
    text = document.layer_by_id(text_layer_id)
    if isinstance(text, TextLayer):
        text.ending_heart_detached = False
    return removed


def ensure_anchored_hearts(document: Document) -> None:
    """迁移/兜底：给所有 ending_heart=True 但还没有爱心图层的文字图层补建锚定爱心。

    旧存档（只有 ending_heart 标志、没有爱心图层）载入或订单 seed 后调用一次即可无感升级。
    """
    for layer in list(document.iter_all_layers()):
        if isinstance(layer, TextLayer) and bool(getattr(layer, "ending_heart", False)):
            ensure_anchored_heart_for(document, layer)
