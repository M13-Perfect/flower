from __future__ import annotations

import base64
from dataclasses import dataclass
from html import escape
import io
import json
import os
from pathlib import Path
from typing import Any

from app.domain import DomainError
from app.domain.exports import export_dxf
from app.domain.exports.png import png_rasterizer_available
from app.domain.orders.batch_import import BatchOrderItem
from app.domain.orders.batch_store import load_batch
from app.domain.orders.workflow import generate_batch_outputs, parse_order_batch
from app.domain.orders.parser import parse_order_note
from app.domain.orders.report import write_batch_report, write_review_csv
from app.domain.output_store import save_outputs
from app.domain.templates import apply_template


@dataclass
class GeneratedBatchItem:
    order_id: str
    status: str
    needs_manual_review: bool
    reason_summary: str
    output_paths: list[str]


@dataclass
class BatchGenerateResult:
    batch_id: str
    items: list[GeneratedBatchItem]
    report_path: Path
    review_csv_path: Path


def generate_batch(batch_id: str) -> BatchGenerateResult:
    batch = parse_order_batch(batch_id)
    # 桌面按钮路径与 CLI 同规则:栅格化可用即产 PNG,不可用降级跳过。
    workflow_result = generate_batch_outputs(
        batch.batch_id, include_png=png_rasterizer_available()
    )
    generated_items, report_path, review_csv_path = write_reports_for_workflow_result(
        batch.batch_id, workflow_result
    )
    return BatchGenerateResult(
        batch_id=batch.batch_id,
        items=generated_items,
        report_path=report_path,
        review_csv_path=review_csv_path,
    )


def write_reports_for_workflow_result(
    batch_id: str,
    workflow_result: object,
) -> tuple[list[GeneratedBatchItem], Path, Path]:
    """由 workflow 生成结果写出批次报告;CLI 直调 workflow 时也必须出报告。"""
    generated_by_job = {
        item.order_job_id: item for item in getattr(workflow_result, "items", ())
    }
    final_batch = load_batch(batch_id)
    generated_items = [
        _generated_item_from_batch_item(item, generated_by_job.get(item.order_job_id))
        for item in final_batch.items
    ]
    report_rows = [_report_row(item) for item in generated_items]
    report_path = write_batch_report(batch_id, report_rows)
    review_csv_path = write_review_csv(batch_id, report_rows)
    return generated_items, report_path, review_csv_path


def _generated_item_from_batch_item(item: BatchOrderItem, generated: object | None) -> GeneratedBatchItem:
    if generated is not None:
        return GeneratedBatchItem(
            order_id=item.order_id,
            status=getattr(generated, "status"),
            needs_manual_review=False,
            reason_summary="",
            output_paths=list(getattr(generated, "files")),
        )
    return GeneratedBatchItem(
        order_id=item.order_id,
        status=item.status,
        needs_manual_review=item.status in {"BLOCKED", "NEEDS_REVIEW", "FAILED"},
        reason_summary="; ".join(issue.message for issue in item.issues),
        output_paths=[],
    )


def _generate_item(item: BatchOrderItem) -> GeneratedBatchItem:
    if item.issues:
        return _blocked_item(item, "; ".join(issue.message for issue in item.issues))
    if "my own design" in item.order_note.casefold():
        return _blocked_item(item, "My Own Design requires manual flower/font resolution.")

    try:
        parsed_order = parse_order_note(item.order_note, item.order_id)
        document = apply_template(
            item.listing_id,
            parsed_order,
            job_id=item.order_job_id,
        )
        svg = _render_document_svg(document)
        png_data_url = _render_document_png_data_url(document)
        dxf = export_dxf(document)
        saved = save_outputs(
            order_name=item.order_id,
            document=document,
            svg=svg,
            png_data_url=png_data_url,
            dxf_content_base64=dxf.content_base64,
        )
    except DomainError as exc:
        return _blocked_item(item, _domain_error_reason(exc))
    except Exception as exc:
        return GeneratedBatchItem(
            order_id=item.order_id,
            status="FAILED",
            needs_manual_review=True,
            reason_summary=exc.__class__.__name__,
            output_paths=[],
        )

    output_paths = [file.relative_path for file in saved.files if file.kind != "json"]
    return GeneratedBatchItem(
        order_id=item.order_id,
        status="READY",
        needs_manual_review=False,
        reason_summary="",
        output_paths=output_paths,
    )


def _blocked_item(item: BatchOrderItem, reason: str) -> GeneratedBatchItem:
    return GeneratedBatchItem(
        order_id=item.order_id,
        status="BLOCKED",
        needs_manual_review=True,
        reason_summary=reason,
        output_paths=[],
    )


def _report_row(item: GeneratedBatchItem) -> dict[str, object]:
    return {
        "orderId": item.order_id,
        "status": item.status,
        "needsManualReview": item.needs_manual_review,
        "reasonSummary": item.reason_summary,
        "assetPaths": "\n".join(item.output_paths),
    }


def _domain_error_reason(exc: DomainError) -> str:
    if exc.details:
        return f"{exc.code}: {json.dumps(exc.details, ensure_ascii=False, sort_keys=True)}"
    return exc.code


def _render_document_svg(document: dict[str, Any]) -> str:
    canvas = document["canvas"]
    width = canvas["width"]
    height = canvas["height"]
    metadata = escape(json.dumps(document.get("metadata", {}), ensure_ascii=False, sort_keys=True))
    body: list[str] = [f"<metadata>{metadata}</metadata>"]
    for layer in sorted(document.get("layers", []), key=lambda value: value.get("zIndex", 0)):
        if layer.get("visible") is False or layer.get("exportable") is False:
            continue
        if layer.get("type") == "svg":
            inline_svg = str(layer.get("inlineSvg") or "")
            if inline_svg:
                body.append(f'<g transform="{_layer_transform(layer)}">{inline_svg}</g>')
        elif layer.get("type") == "text":
            style = layer.get("style") if isinstance(layer.get("style"), dict) else {}
            font_size = float(style.get("fontSize") or 120)
            text = escape(str(layer.get("text") or ""))
            body.append(
                f'<text transform="{_layer_transform(layer)}" x="0" y="{font_size:.3f}" '
                f'font-size="{font_size:.3f}" text-anchor="middle">{text}</text>'
            )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n'
        + "\n".join(body)
        + "\n</svg>\n"
    )


def _render_document_png_data_url(document: dict[str, Any]) -> str:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise DomainError(
            code="DEPENDENCY_MISSING",
            message="Pillow is required to render PNG batch previews.",
            details={"package": "Pillow"},
            recoverable=False,
        ) from exc

    canvas = document["canvas"]
    width = int(canvas["width"])
    height = int(canvas["height"])
    background = _canvas_background(canvas)
    image = Image.new("RGBA", (width, height), background)
    draw = ImageDraw.Draw(image)
    for layer in sorted(document.get("layers", []), key=lambda value: value.get("zIndex", 0)):
        if layer.get("visible") is False or layer.get("exportable") is False:
            continue
        if layer.get("type") == "svg":
            _draw_svg_layer(draw, layer)
        elif layer.get("type") == "text":
            _draw_text_layer(draw, ImageFont, layer)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _canvas_background(canvas: dict[str, Any]) -> str:
    background = canvas.get("background")
    if isinstance(background, dict) and background.get("type") == "solid":
        return str(background.get("color") or "#ffffff")
    return "#ffffff"


def _draw_svg_layer(draw: Any, layer: dict[str, Any]) -> None:
    try:
        from app.domain.exports.dxf import ExportContext, layer_matrix, _svg_layer_shapes

        context = ExportContext(document={}, target_units="px", exported_at="")
        shapes = _svg_layer_shapes(layer, layer_matrix(layer), context)
    except Exception:
        _draw_svg_placeholder(draw, layer)
        return

    for shape in shapes:
        if len(shape.points) >= 2:
            draw.line(shape.points, fill="#111111", width=3)


def _draw_svg_placeholder(draw: Any, layer: dict[str, Any]) -> None:
    x = float(layer.get("x") or 0)
    y = float(layer.get("y") or 0)
    width = float(layer.get("width") or 0)
    height = float(layer.get("height") or 0)
    draw.rectangle((x, y, x + width, y + height), outline="#7a9c64", width=4)
    draw.line((x, y + height, x + width, y), fill="#7a9c64", width=3)
    draw.line((x, y, x + width, y + height), fill="#7a9c64", width=3)


def _draw_text_layer(draw: Any, image_font: Any, layer: dict[str, Any]) -> None:
    raw_style = layer.get("style")
    style: dict[str, Any] = raw_style if isinstance(raw_style, dict) else {}
    text = str(layer.get("text") or "")
    font_size = int(float(style.get("fontSize") or 120))
    font = _png_font(image_font, font_size)
    x = float(layer.get("x") or 0)
    y = float(layer.get("y") or 0)
    width = float(layer.get("width") or 0)
    height = float(layer.get("height") or 0)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    draw.text(
        (x + (width - text_width) / 2, y + (height - text_height) / 2),
        text,
        fill=str(style.get("fill") or "#111111"),
        font=font,
    )


def _png_font(image_font: Any, font_size: int) -> Any:
    font_path = _project_root() / "Birthmonth_font.ttf"
    if font_path.is_file():
        return image_font.truetype(str(font_path), font_size)
    return image_font.load_default()


def _layer_transform(layer: dict[str, Any]) -> str:
    x = float(layer.get("x") or 0)
    y = float(layer.get("y") or 0)
    scale_x = float(layer.get("scaleX") or 1)
    scale_y = float(layer.get("scaleY") or 1)
    rotation = float(layer.get("rotation") or 0)
    return f"translate({x:.3f} {y:.3f}) rotate({rotation:.3f}) scale({scale_x:.6f} {scale_y:.6f})"


def _project_root() -> Path:
    default_root = Path(__file__).resolve().parents[5]
    return Path(os.environ.get("FLOWER_PROJECT_ROOT", default_root)).resolve()
