from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from glyph_service import rebuild_render_text
from heart_symbol import HEART_ASPECT
from models import TextLayer, layer_text_style
from text_layout import (
    ENDING_HEART_ADVANCE_RATIO,
    ENDING_HEART_GAP_RATIO,
    ENDING_HEART_SIZE_RATIO,
    fit_text_box,
)

# 下划线几何（占字号比例）：粗细与文字底间隙。预览与矢量端用同一组比例，保证一致。
UNDERLINE_THICKNESS_RATIO = 0.05
UNDERLINE_GAP_RATIO = 0.12


@lru_cache(maxsize=64)
def _rasterize_heart(fill: str, width_px: int, height_px: int):
    """用 cairosvg 把独立实心爱心栅格化成 RGBA 图（按 (fill,宽,高) 缓存）。失败返回 None。"""
    try:
        from io import BytesIO

        import cairosvg
        from PIL import Image

        from heart_symbol import heart_svg_markup

        png = cairosvg.svg2png(
            bytestring=heart_svg_markup(fill).encode("utf-8"),
            output_width=max(1, int(width_px)),
            output_height=max(1, int(height_px)),
        )
        return Image.open(BytesIO(png)).convert("RGBA")
    except Exception:
        return None


@dataclass(frozen=True)
class InkBounds:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class TextRenderResult:
    image: Any
    render_text: str
    glyph_overrides: dict[int, dict[str, Any]]
    ink_bbox: InkBounds | None
    warnings: list[str]


class TextRenderer:
    """文本层统一渲染器；预览和 PNG 导出都必须通过这里生成透明文字图。"""

    def render_layer(self, layer: TextLayer) -> TextRenderResult:
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as exc:
            raise RuntimeError("当前环境未安装 Pillow，无法渲染文本图层。") from exc

        warnings: list[str] = []
        box_width = self._positive_int(getattr(layer, "text_box_width", layer.width) or layer.width, "文本框宽度", warnings)
        box_height = self._positive_int(getattr(layer, "text_box_height", layer.height) or layer.height, "文本框高度", warnings)
        font_size = self._positive_int(getattr(layer, "font_size", 0), "字号", warnings)
        font_path = self._valid_font_path(getattr(layer, "font_path", None), warnings)
        text = self._source_text(layer)
        if getattr(layer, "original_text", "") != text:
            layer.original_text = text
        if getattr(layer, "raw_text", "") != text:
            layer.raw_text = text

        glyph_warnings = self._raw_glyph_warnings(getattr(layer, "glyph_overrides", {}) or {})
        render_text, clean_overrides, rebuild_warnings = rebuild_render_text(
            text,
            getattr(layer, "glyph_overrides", {}) or {},
            font_path=font_path,
            text_layer_id=getattr(layer, "id", ""),
        )
        warnings.extend(glyph_warnings)
        warnings.extend(rebuild_warnings)

        image = Image.new("RGBA", (box_width, box_height), (0, 0, 0, 0))
        if not render_text:
            warnings.append("空文本：已渲染透明文本图层。")
            return TextRenderResult(image, render_text, clean_overrides, None, warnings)

        align = str(getattr(layer, "align", "center") or "center").casefold()
        vertical_align = str(getattr(layer, "vertical_align", "middle") or "middle").casefold()
        line_spacing = self._line_spacing(layer)
        tracking = self._tracking(layer)
        # Font 4 等：末尾要缀独立爱心时，在末行右侧预留推进量，名字+爱心一起适配字号、不溢出框。
        wants_heart = bool(getattr(layer, "ending_heart", False))
        # 末尾爱心已交给独立 AnchoredHeartLayer（resolve 置位）时，此处不再贴爱心，但仍保留推进量
        # 预留（advance 不变 → 名字位置与旧路径一致），爱心改由独立图层在同一落点绘制。
        detached = bool(getattr(layer, "ending_heart_detached", False))
        ending_advance_ratio = ENDING_HEART_ADVANCE_RATIO if wants_heart else 0.0
        # 统一适配：等比选字号 + 断行，与矢量导出共用同一套 fit_text_box（不再非等比拉伸铺满框）。
        # layer.font_size 作为字号上限（cap），真实字号由文本框大小自适应得出。
        fit = fit_text_box(
            render_text,
            box_width,
            box_height,
            font_path,
            personalization_type="auto",
            font_size_cap=font_size,
            align=align,
            vertical_align=vertical_align,
            line_spacing=line_spacing,
            letter_spacing=tracking,
            ending_advance_ratio=ending_advance_ratio,
        )
        if fit.warnings:
            warnings.extend(fit.warnings)
        font = self._load_font(ImageFont, font_path, fit.font_size, warnings)
        fill = self._fill_color(layer)
        # 字体样式（新增）：加粗=Pillow stroke_width(faux-bold)，下划线=文字下方画线。
        # 强度按字号等比，stroke=0/underline=False 时与原渲染逐像素一致（现有图层零回归）。
        style = layer_text_style(layer)
        stroke = round(style.bold_strength * fit.font_size) if style.bold else 0
        underline = style.underline
        lines = list(fit.lines) or render_text.splitlines() or [render_text]
        line_images = [
            self._render_line(Image, ImageDraw, font, line, fill, tracking, stroke, underline, fit.font_size)
            for line in lines
        ]
        non_empty_lines = [line_image for line_image in line_images if line_image is not None]
        if not non_empty_lines:
            warnings.append("文本没有可见墨迹：已渲染透明文本图层。")
            return TextRenderResult(image, render_text, clean_overrides, None, warnings)

        # Font 4 等：把独立实心爱心缀到最后一行墨迹右侧（与导出端 place_ending_heart 同一几何）。
        # 走“增广末行图像 + 现有 compose/居中”，单行/多行都与导出的末行整体居中一致。
        # detached=True（已有独立爱心图层）时跳过——爱心由 renderer._composite_anchored_heart 单独绘制。
        if wants_heart and not detached:
            augmented = self._append_ending_heart(Image, non_empty_lines[-1], fit.font_size, fill, warnings)
            if augmented is not None:
                non_empty_lines[-1] = augmented

        text_image = self._compose_text_image(Image, non_empty_lines, layer, fit.font_size, line_spacing)
        if text_image is None:
            warnings.append("文本没有可见墨迹：已渲染透明文本图层。")
            return TextRenderResult(image, render_text, clean_overrides, None, warnings)
        image = self._place_text_in_box(Image, text_image, box_width, box_height, align, vertical_align)

        ink = image.getbbox()
        ink_bbox = InkBounds(*ink) if ink else None
        if ink_bbox is None:
            warnings.append("文本没有可见墨迹：已渲染透明文本图层。")
        return TextRenderResult(image, render_text, clean_overrides, ink_bbox, warnings)

    def _valid_font_path(self, font_path: Path | str | None, warnings: list[str]) -> Path | None:
        if not font_path:
            return None
        path = Path(font_path)
        if not path.is_file():
            warnings.append(f"字体文件不存在：{path}，已使用默认字体降级渲染。")
            return None
        return path

    def _load_font(self, image_font_module, font_path: Path | None, font_size: int, warnings: list[str]):
        if font_path is not None:
            try:
                return image_font_module.truetype(str(font_path), font_size)
            except Exception as exc:
                warnings.append(f"字体加载失败：{font_path}，已使用默认字体降级渲染。原因：{exc}")
        try:
            return image_font_module.load_default(size=font_size)
        except TypeError:
            return image_font_module.load_default()

    def _render_line(
        self,
        image_module,
        image_draw_module,
        font,
        line: str,
        fill: str,
        tracking: float,
        stroke: int = 0,
        underline: bool = False,
        font_size: int = 0,
    ):
        if line == "":
            return None
        stroke = max(0, int(stroke))
        ul_th = max(1, round(UNDERLINE_THICKNESS_RATIO * font_size)) if underline and font_size > 0 else 0
        ul_gap = round(UNDERLINE_GAP_RATIO * font_size) if ul_th else 0
        extra_bottom = ul_gap + ul_th  # 下划线占用的额外底部高度（无下划线时为 0）
        if abs(tracking) < 0.001:
            probe = image_module.new("RGBA", (1, 1), (0, 0, 0, 0))
            draw = image_draw_module.Draw(probe)
            bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke)
            width = max(1, int(round(bbox[2] - bbox[0])))
            height = max(1, int(round(bbox[3] - bbox[1])))
            image = image_module.new("RGBA", (width, height + extra_bottom), (0, 0, 0, 0))
            line_draw = image_draw_module.Draw(image)
            line_draw.text((-bbox[0], -bbox[1]), line, font=font, fill=fill, stroke_width=stroke, stroke_fill=fill)
            if ul_th:
                y0 = height + ul_gap
                line_draw.rectangle([0, y0, width - 1, y0 + ul_th - 1], fill=fill)
            cropped = image.getbbox()
            return image.crop(cropped) if cropped else None

        probe = image_module.new("RGBA", (1, 1), (0, 0, 0, 0))
        draw = image_draw_module.Draw(probe)
        positions: list[tuple[str, float, tuple[int, int, int, int]]] = []
        cursor = 0.0
        left = top = 10**9
        right = bottom = -10**9
        for char in line:
            bbox = draw.textbbox((cursor, 0), char, font=font, stroke_width=stroke)
            positions.append((char, cursor, bbox))
            left = min(left, bbox[0])
            top = min(top, bbox[1])
            right = max(right, bbox[2])
            bottom = max(bottom, bbox[3])
            cursor += float(draw.textlength(char, font=font)) + tracking
        if right <= left or bottom <= top:
            return None
        width = max(1, int(round(right - left)))
        height = max(1, int(round(bottom - top)))
        image = image_module.new("RGBA", (width, height + extra_bottom), (0, 0, 0, 0))
        line_draw = image_draw_module.Draw(image)
        for char, cursor, _bbox in positions:
            line_draw.text((cursor - left, -top), char, font=font, fill=fill, stroke_width=stroke, stroke_fill=fill)
        if ul_th:
            y0 = height + ul_gap
            line_draw.rectangle([0, y0, width - 1, y0 + ul_th - 1], fill=fill)
        cropped = image.getbbox()
        return image.crop(cropped) if cropped else None

    def _append_ending_heart(self, image_module, line_image, font_size: int, fill: str, warnings: list[str]):
        """把独立实心爱心缀到（最后一行）墨迹右侧，竖直居中于该行墨迹。失败返回 None（沿用原行）。

        几何与 text_layout.place_ending_heart / 矢量导出一致：高=ENDING_HEART_SIZE_RATIO*字号，
        与末字水平间隙=ENDING_HEART_GAP_RATIO*字号；爱心比该行墨迹高时画布上下自动扩展。
        """
        try:
            heart_h = max(1, round(ENDING_HEART_SIZE_RATIO * font_size))
            heart_w = max(1, round(heart_h * HEART_ASPECT))
            gap = max(0, round(ENDING_HEART_GAP_RATIO * font_size))
            heart_img = _rasterize_heart(fill, heart_w, heart_h)
            if heart_img is None:
                warnings.append("爱心符号栅格化失败（cairosvg）：预览已跳过末尾爱心。")
                return None
            lw, lh = line_image.width, line_image.height
            heart_top = lh / 2.0 - heart_h / 2.0  # 竖直居中于该行墨迹
            top = min(0.0, heart_top)
            bottom = max(float(lh), heart_top + heart_h)
            aug_w = lw + gap + heart_w
            aug_h = max(1, int(round(bottom - top)))
            canvas = image_module.new("RGBA", (aug_w, aug_h), (0, 0, 0, 0))
            canvas.alpha_composite(line_image, (0, int(round(-top))))
            canvas.alpha_composite(heart_img, (lw + gap, int(round(heart_top - top))))
            return canvas
        except Exception as exc:
            warnings.append(f"末尾爱心渲染失败：{exc}")
            return None

    def _compose_text_image(self, image_module, line_images: list[Any], layer: TextLayer, font_size: int, line_spacing: float):
        line_gap = max(0, int(round(font_size * max(0.0, line_spacing - 1.0))))
        width = max((line_image.width for line_image in line_images), default=0)
        height = sum(line_image.height for line_image in line_images) + line_gap * max(0, len(line_images) - 1)
        if width <= 0 or height <= 0:
            return None
        image = image_module.new("RGBA", (width, height), (0, 0, 0, 0))
        y = 0
        for line_image in line_images:
            x = self._horizontal_offset(layer, width, line_image.width)
            image.alpha_composite(line_image, (x, y))
            y += line_image.height + line_gap
        ink = image.getbbox()
        return image.crop(ink) if ink else None

    def _place_text_in_box(self, image_module, text_image, box_width: int, box_height: int, align: str, vertical_align: str):
        """把真实墨迹按等比尺寸居中贴进文本框：保留花体横竖比例，不再非等比 resize 铺满。

        与 text_layout/矢量导出一致——都按墨迹居中。fit_text_box 已保证装得下，这里仅在
        极端情况（1px 溢出）兜底等比缩小。"""
        box = image_module.new("RGBA", (max(1, box_width), max(1, box_height)), (0, 0, 0, 0))
        if text_image.width <= 0 or text_image.height <= 0:
            return box
        scale = min(1.0, box_width / text_image.width, box_height / text_image.height)
        if scale < 1.0:
            resampling = getattr(getattr(image_module, "Resampling", image_module), "LANCZOS", 1)
            new_size = (max(1, int(text_image.width * scale)), max(1, int(text_image.height * scale)))
            text_image = text_image.resize(new_size, resampling)
        if align == "left":
            offset_x = 0
        elif align == "right":
            offset_x = box_width - text_image.width
        else:
            offset_x = (box_width - text_image.width) // 2
        if vertical_align == "top":
            offset_y = 0
        elif vertical_align == "bottom":
            offset_y = box_height - text_image.height
        else:
            offset_y = (box_height - text_image.height) // 2
        box.alpha_composite(text_image, (max(0, int(offset_x)), max(0, int(offset_y))))
        return box

    def _horizontal_offset(self, layer: TextLayer, box_width: int, line_width: int) -> int:
        align = str(getattr(layer, "align", "center") or "center").casefold()
        if align == "left":
            return 0
        if align == "right":
            return max(0, box_width - line_width)
        return max(0, int(round((box_width - line_width) / 2)))

    def _positive_int(self, value: Any, label: str, warnings: list[str]) -> int:
        try:
            number = int(round(float(value)))
        except (TypeError, ValueError):
            warnings.append(f"{label}无效：{value}，已降级为 1。")
            return 1
        if number <= 0:
            warnings.append(f"{label}必须大于 0：{value}，已降级为 1。")
            return 1
        return number

    def _line_spacing(self, layer: TextLayer) -> float:
        try:
            return max(0.5, float(getattr(layer, "line_spacing", 1.2)))
        except (TypeError, ValueError):
            return 1.2

    def _tracking(self, layer: TextLayer) -> float:
        value = getattr(layer, "tracking", None)
        if value in (None, 0, 0.0):
            value = getattr(layer, "letter_spacing", 0.0)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _fill_color(self, layer: TextLayer) -> str:
        return str(getattr(layer, "fill_color", "") or getattr(layer, "color", "") or "#111111")

    def _source_text(self, layer: TextLayer) -> str:
        original = str(getattr(layer, "original_text", "") or "")
        current = str(getattr(layer, "text", "") or "")
        render_text = str(getattr(layer, "render_text", "") or "")
        # 兼容旧调用方：历史代码可能只写 layer.text，没有同步 original_text。
        if current != original and current != render_text:
            return current
        return original or current

    def _raw_glyph_warnings(self, overrides: Any) -> list[str]:
        warnings: list[str] = []
        if not isinstance(overrides, dict):
            return ["字形覆盖配置无效，已回退普通字符。"]
        for index, override in overrides.items():
            if not isinstance(override, dict):
                warnings.append(f"字形覆盖位置 {index} 配置无效，已回退普通字符。")
                continue
            if "glyph_id" not in override:
                continue
            try:
                glyph_id = int(override.get("glyph_id"))
            except (TypeError, ValueError):
                warnings.append(f"字形 glyph_id 无效：{override.get('glyph_id')}，已回退普通字符。")
                continue
            if glyph_id < 0:
                warnings.append(f"字形 glyph_id 无效：{glyph_id}，已回退普通字符。")
        return warnings
