"""把桌面端多图层 Document 桥接到 services/api 的真实矢量导出(export_dxf/export_svg)。

桌面端历史上用 renderer.py 自己的 render_dxf(花朵拍平成折线、文字写成 DXF TEXT 实体),
导出的 DXF 在 EzCad2 里「可选中但改不动尺寸」。这里改为复用与批量/Web 端一致的导出权威:
- DXF:R2018 + SPLINE 轮廓 + 单层色 7 + mm 单位(实体可在 EzCad2 编辑)。
- SVG:文字转路径 + 素材内联矢量(纯矢量,CAD 可编辑)。

转换在一处完成(_document_to_layer_document),DXF 和矢量 SVG 共用同一份图层文档。
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from glyph_service import rebuild_render_text
from models import Document, ImageLayer, Layer, TextLayer, layer_text_style
from text_layout import fit_text_box

# services/api(导出权威所在)未必已安装为包,确保它在 sys.path 上,
# 这样下面函数里惰性 import app.domain.exports.* 一定可用(否则按钮点击会 ImportError 崩溃)。
_SERVICES_API_DIR = Path(__file__).resolve().parent / "services" / "api"
if _SERVICES_API_DIR.is_dir():
    _api_path = str(_SERVICES_API_DIR)
    if _api_path not in sys.path:
        sys.path.insert(0, _api_path)

# 桌面画布只有像素、无物理尺寸概念;按产品实际宽度(模板 birth-flower-card 即 80mm)
# 映射画布宽,高度按画布比例派生。导出后可在 EzCad2 里按需缩放。
DEFAULT_PHYSICAL_WIDTH_MM = 80.0

# 位图素材无法转矢量轮廓,DXF/纯矢量 SVG 都无意义,需提前给出可读错误。
BITMAP_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}

_DIMENSION_RE = re.compile(r"^\s*([0-9.]+)\s*(?:px)?\s*$")


def render_document_dxf(
    document: Document,
    output_path: Path | str,
    *,
    physical_width_mm: float | None = None,
    text_fill: str = "solid",
) -> Path:
    """按多图层 Document 导出可在 CAD 编辑的 DXF(R2018+SPLINE),走 services/api 权威管线。

    text_fill='solid'(默认,文字 HATCH 实心,对齐标准件)| 'outline'(文字空心轮廓)。"""
    from app.domain import DomainError
    from app.domain.exports.dxf import export_dxf

    layer_document = _document_to_layer_document(
        document, physical_width_mm=physical_width_mm, text_fill=text_fill
    )
    try:
        result = export_dxf(layer_document)
    except DomainError as exc:
        # 转成 ValueError,让 UI 的“生成失败”对话框显示可读信息,而不是抛栈崩溃。
        raise ValueError(exc.message) from exc
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(result.content_base64))
    return path


def render_document_vector_svg(
    document: Document,
    output_path: Path | str,
    *,
    physical_width_mm: float | None = None,
    text_fill: str = "solid",
) -> Path:
    """按多图层 Document 导出纯矢量 SVG(文字转路径、素材内联矢量),走 services/api 权威管线。"""
    from app.domain import DomainError
    from app.domain.exports.svg import export_svg

    layer_document = _document_to_layer_document(
        document, physical_width_mm=physical_width_mm, text_fill=text_fill
    )
    try:
        result = export_svg(layer_document)
    except DomainError as exc:
        raise ValueError(exc.message) from exc
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.content, encoding="utf-8")
    return path


def _document_to_layer_document(
    document: Document,
    *,
    physical_width_mm: float | None = None,
    text_fill: str = "solid",
) -> dict[str, Any]:
    """桌面 Document → services/api 图层文档 dict(export_dxf/export_svg 共用的输入)。"""
    # 物理宽度优先用调用方(按钮)从产品模板读到的值;缺省退回 80mm。
    width_mm = float(physical_width_mm) if physical_width_mm and physical_width_mm > 0 else DEFAULT_PHYSICAL_WIDTH_MM
    fill_mode = "outline" if str(text_fill).lower() == "outline" else "solid"
    layers: list[dict[str, Any]] = []
    for layer in document.flat_render_layers():
        if not getattr(layer, "visible", True):
            continue
        if isinstance(layer, ImageLayer):
            layers.append(_image_layer(layer))
        elif isinstance(layer, TextLayer):
            layers.append(_text_layer(layer))
        # 其它图层(GlyphLayer 等)暂不支持矢量导出,静默跳过,保持向后兼容。
    if not layers:
        raise ValueError("当前文档没有可导出为矢量的图层。")

    canvas_width = int(document.canvas_width)
    canvas_height = int(document.canvas_height)
    return {
        "schemaVersion": "1.0",
        "metadata": {"templateId": "desktop", "orderId": "", "appVersion": ""},
        "canvas": {
            "width": canvas_width,
            "height": canvas_height,
            "unit": "px",
            "background": {"type": "transparent"},
        },
        "exportSettings": {
            "schemaVersion": "1.0",
            # 画布像素映射为实宽(mm),DXF 才能写出 mm 坐标(INSUNITS=4);高度由画布比例派生。
            "physical": {"widthMm": width_mm},
            "svg": {"preserveText": False, "preserveVector": True, "includeMetadata": True},
            "png": {"scale": 1, "background": "transparent"},
            "dxf": {"textMode": "paths", "units": "mm"},
            # 文字填充:solid=实心 HATCH(默认,跟标准件)| outline=空心轮廓。
            "text": {"fill": fill_mode},
        },
        "layers": layers,
    }


def _image_layer(layer: ImageLayer) -> dict[str, Any]:
    path = layer.path
    if path is None or not Path(path).exists():
        raise ValueError(f"素材文件不存在:{path}")
    asset_path = Path(path)
    suffix = asset_path.suffix.casefold()
    if suffix in BITMAP_SUFFIXES:
        raise ValueError(
            f"位图素材「{asset_path.name}」无法导出为矢量 DXF/SVG;请改用纯矢量 SVG 素材。"
        )
    if suffix != ".svg":
        raise ValueError(f"不支持的素材类型 {suffix or '(无后缀)'};矢量导出仅支持 SVG 素材。")
    inline_svg = asset_path.read_text(encoding="utf-8")
    schema = _layer_base(layer, "svg")
    schema["inlineSvg"] = inline_svg
    schema["preserveVector"] = True
    # 让导出定位与画布预览/PNG 完全一致(所见即所得);失败时退回声明 viewBox。见 _apply_canvas_fit。
    _apply_canvas_fit(schema, layer, asset_path, inline_svg)
    return schema


def _apply_canvas_fit(
    schema: dict[str, Any],
    layer: ImageLayer,
    asset_path: Path,
    inline_svg: str,
) -> None:
    """把画布预览的素材摆放(真实墨迹 bbox + 等比 contain 居中)烘焙进导出图层 dict。

    桌面预览/PNG 走 renderer 的 fit:用素材**真实墨迹 bbox**(去掉 viewBox 留白),按
    USE_VISUAL_BBOX_FOR_SVG/SVG_FIT_MODE 等比塞进框 Rect(x, y, w*scaleX, h*scaleY) 并居中。
    而导出端(dxf.py/svg.py)是把**声明 viewBox 非等比拉伸铺满框、左上对齐**——两套算法不一致,
    导致"画布上摆好的位置,导出后对不上"。这里复用 renderer 同一份 fit,把结果写进 viewBox 与
    x/y/width/height(scaleX/Y 归 1),让导出端的 viewBox→框映射恰好重现预览定位。所见即所得。
    """
    try:
        from renderer import SVG_FIT_MODE, USE_VISUAL_BBOX_FOR_SVG, _svg_geometry
        from visual_layout import Rect, fit_content_bbox_to_target_rect
    except Exception:
        # 取不到 renderer/visual_layout 时退回原行为(声明 viewBox + 拉伸铺满),至少不崩。
        schema["viewBox"] = _asset_view_box(inline_svg)
        return

    target_w = float(layer.width) * float(layer.scale_x)
    target_h = float(layer.height) * float(layer.scale_y)
    try:
        geometry = _svg_geometry(asset_path)
        declared = geometry.view_box  # 导出端按"声明 viewBox"映射,这里必须沿用同一个 viewBox
        content = geometry.visual_bbox if USE_VISUAL_BBOX_FOR_SVG else geometry.view_box
        if (
            content.width <= 0 or content.height <= 0
            or declared.width <= 0 or declared.height <= 0
            or target_w <= 0 or target_h <= 0
        ):
            raise ValueError("empty content or target box")
        fit = fit_content_bbox_to_target_rect(
            content,
            Rect(float(layer.x), float(layer.y), target_w, target_h),
            mode=SVG_FIT_MODE,
            align=(0.5, 0.5),
        )
    except Exception:
        schema["viewBox"] = _asset_view_box(inline_svg)
        return

    # 导出端把"声明 viewBox"映射到 layer 框:q = layer_origin + scale*(p - viewBox_origin)。
    # 预览 fit(基于真实墨迹 bbox)是:q = fit.draw + fit.scale*p。两式相等 ⇒
    #   layer_scale = fit.scale,  layer_origin = fit.draw + fit.scale*viewBox_origin,
    #   layer_size  = fit.scale * 声明viewBox尺寸。
    # 这样无论导出取声明 viewBox 还是 layer viewBox(此处设为同一个),定位都与预览一致。
    schema["viewBox"] = {
        "x": float(declared.x),
        "y": float(declared.y),
        "width": float(declared.width),
        "height": float(declared.height),
    }
    schema["x"] = fit.draw_x + fit.scale_x * float(declared.x)
    schema["y"] = fit.draw_y + fit.scale_y * float(declared.y)
    schema["width"] = fit.scale_x * float(declared.width)
    schema["height"] = fit.scale_y * float(declared.height)
    # 缩放/位置已折算进 x/y/width/height 与 viewBox,这里清 1 防重复缩放。
    schema["scaleX"] = 1.0
    schema["scaleY"] = 1.0


def _text_layer(layer: TextLayer) -> dict[str, Any]:
    schema = _layer_base(layer, "text")
    # 文字对齐框用 text_box_*(对齐计算依赖图层宽度)。
    box_width = float(getattr(layer, "text_box_width", layer.width) or layer.width)
    box_height = float(getattr(layer, "text_box_height", layer.height) or layer.height)
    schema["width"] = box_width
    schema["height"] = box_height
    # 传 original_text + glyphOverrides,让导出端按索引重放字形替换(与预览一致)。
    schema["text"] = layer.original_text or layer.text or ""
    schema["fontRef"] = _font_ref(layer)
    align = (layer.align or "center").casefold()
    vertical_align = (getattr(layer, "vertical_align", "middle") or "middle").casefold()
    line_spacing = float(layer.line_spacing or 1)
    letter_spacing = float(layer.letter_spacing or layer.tracking or 0)
    # 统一适配:和预览/PNG 共用 fit_text_box —— 把"自适应字号 + 断行 + 每行基线锚点"算一次,
    # 烘进 textLayout 让矢量端(dxf/svg)逐字复用,从而所见即所得。layer.font_size 作字号上限。
    # render_text 与 TextRenderer 同源现算(rebuild_render_text),不信任可能过期的 layer.render_text,
    # 保证两端 name/message 分类与字形替换完全一致。
    source_text = layer.original_text or layer.text or ""
    try:
        render_text, _clean_overrides, _rebuild_warnings = rebuild_render_text(
            source_text,
            layer.glyph_overrides or {},
            font_path=layer.font_path,
            text_layer_id=str(layer.id),
        )
    except Exception:
        render_text = layer.render_text or source_text
    fit = fit_text_box(
        render_text,
        box_width,
        box_height,
        layer.font_path,
        personalization_type="auto",
        font_size_cap=float(layer.font_size or 0) or None,
        align=align,
        vertical_align=vertical_align,
        line_spacing=line_spacing,
        letter_spacing=letter_spacing,
    )
    # 字体样式（加粗/下划线）解析后烘进 style，供 svg/dxf 矢量端消费（与预览同一套 layer_text_style）。
    tstyle = layer_text_style(layer)
    schema["style"] = {
        "fontSize": float(fit.font_size),
        "fill": layer.fill_color or layer.color or "#111111",
        "align": align,
        "lineHeight": line_spacing,
        "letterSpacing": letter_spacing,
        "bold": tstyle.bold,
        "underline": tstyle.underline,
        "boldStrength": tstyle.bold_strength,
    }
    schema["layout"] = {"mode": "box", "overflow": "visible", "verticalAlign": vertical_align}
    # textLayout: 每行最终文本(字形替换已并入 render_text) + 每行 anchor='ls' 锚点(box 本地像素)。
    schema["textLayout"] = {
        "fontSize": int(fit.font_size),
        "lineHeight": line_spacing,
        "lines": list(fit.lines),
        "origins": [[float(origin_x), float(origin_y)] for (origin_x, origin_y) in fit.origins],
    }
    overrides = _glyph_overrides(layer)
    if overrides:
        schema["glyphOverrides"] = overrides
    return schema


def _font_ref(layer: TextLayer) -> dict[str, Any]:
    font_ref: dict[str, Any] = {}
    font_path = getattr(layer, "font_path", None)
    if font_path:
        relative = _project_relative(Path(font_path))
        if relative:
            # 项目内字体:让导出用用户实际选择的字体文件(经 _safe_project_path 校验)。
            font_ref["path"] = relative
            font_ref["family"] = Path(font_path).stem
    if not font_ref:
        # 项目外字体无法安全引用,退回内置字体族解析。
        font_ref["family"] = "Birthmonth"
    return font_ref


def _glyph_overrides(layer: TextLayer) -> list[dict[str, Any]]:
    raw = getattr(layer, "glyph_overrides", None)
    if not isinstance(raw, dict):
        return []
    overrides: list[dict[str, Any]] = []
    for index, value in sorted(raw.items(), key=lambda item: item[0]):
        if not isinstance(value, dict):
            continue
        # 桌面 override 的 base_char/replacement_char/codepoint 正好是导出端识别的键。
        overrides.append({"index": int(index), **value})
    return overrides


def _layer_base(layer: Layer, layer_type: str) -> dict[str, Any]:
    return {
        "id": str(layer.id),
        "type": layer_type,
        "name": layer.name,
        "visible": True,
        "locked": False,
        "exportable": True,
        "zIndex": int(layer.z_index),
        "opacity": float(layer.opacity),
        "x": float(layer.x),
        "y": float(layer.y),
        "width": float(layer.width),
        "height": float(layer.height),
        "scaleX": float(layer.scale_x),
        "scaleY": float(layer.scale_y),
        "rotation": float(layer.rotation),
        "tags": [],
    }


def _project_relative(font_path: Path) -> str | None:
    """把绝对字体路径化为项目内相对 posix 路径;项目外返回 None(退回字体族解析)。"""
    try:
        from app.domain.exports.dxf import _project_root

        return font_path.resolve().relative_to(_project_root().resolve()).as_posix()
    except (ValueError, OSError):
        return None


def _asset_view_box(inline_svg: str) -> dict[str, float]:
    """与 templates/engine.py 一致:优先 viewBox,其次 width/height,再退默认 512。"""
    default = {"x": 0.0, "y": 0.0, "width": 512.0, "height": 512.0}
    try:
        root = ElementTree.fromstring(inline_svg)
    except ElementTree.ParseError:
        return default
    raw = root.get("viewBox")
    if raw:
        parts = raw.replace(",", " ").split()
        if len(parts) == 4:
            try:
                x, y, width, height = (float(part) for part in parts)
            except ValueError:
                return default
            if width > 0 and height > 0:
                return {"x": x, "y": y, "width": width, "height": height}
    width = _svg_dimension(root.get("width"))
    height = _svg_dimension(root.get("height"))
    if width and height:
        return {"x": 0.0, "y": 0.0, "width": width, "height": height}
    return default


def _svg_dimension(value: str | None) -> float | None:
    if not value:
        return None
    match = _DIMENSION_RE.match(value)
    if not match:
        return None
    number = float(match.group(1))
    return number if number > 0 else None
