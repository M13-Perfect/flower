from __future__ import annotations

import base64
import csv
from dataclasses import dataclass, replace
from io import StringIO
import io
import os
from pathlib import Path
import tempfile
from typing import Any

from app.domain import DomainError
from app.domain.exports import export_dxf, export_svg, rasterize_svg_to_png
from app.domain.exports.dxf import apply_svg_contain_fit
from app.domain.orders.batch_import import BatchImport, BatchOrderItem, import_batch_csv, import_orders
from app.domain.orders.batch_store import (
    find_item,
    list_batches,
    load_batch,
    replace_item,
    save_batch,
)
from app.domain.orders.issues import ReviewIssue
from app.domain.orders.review import apply_review_decision, review_imported_item
from app.domain.orders.review_csv import export_review_csv, import_review_csv
from app.domain.output_store import SaveOutputsResult, save_outputs
from app.domain.templates import apply_template


PNG_SKIPPED_REASON = (
    "PNG skipped by default: cairosvg needs the native Cairo runtime on Windows. "
    "This run delivers production SVG/DXF only."
)


@dataclass(frozen=True)
class GeneratedBatchItem:
    order_job_id: str
    order_id: str | None
    status: str
    output_dir: str | None = None
    files: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class BatchGenerateResult:
    batch_id: str
    items: tuple[GeneratedBatchItem, ...]

    @property
    def generated_count(self) -> int:
        return sum(1 for item in self.items if item.status == "EXPORTED")

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.items if item.status == "FAILED")


@dataclass(frozen=True)
class OrderOutputResult:
    item: BatchOrderItem
    document: dict[str, Any]
    saved: SaveOutputsResult


def import_orders_file(
    path: Path | str,
    *,
    adapter_name: str | None = None,
    batch_id: str | None = None,
    default_listing_id: str = "birth-flower-card",
) -> BatchImport:
    source_path = Path(path)
    batch = import_orders(
        source_path,
        adapter_name=adapter_name,
        batch_id=batch_id,
        default_listing_id=default_listing_id,
    )
    save_batch(batch)
    return parse_order_batch(batch.batch_id)


def import_orders_csv_file(path: Path | str, *, source_name: str | None = None) -> BatchImport:
    csv_path = Path(path)
    try:
        csv_content = csv_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DomainError(
            code="CSV_LOAD_FAILED",
            message="Orders CSV could not be read.",
            details={"path": str(csv_path)},
            recoverable=True,
        ) from exc
    batch = import_batch_csv(csv_content, source_name=source_name or csv_path.name)
    save_batch(batch)
    return parse_order_batch(batch.batch_id)


def import_order_batch_csv_content(
    csv_content: str,
    *,
    source_name: str = "orders.csv",
) -> BatchImport:
    return save_batch(import_batch_csv(csv_content, source_name=source_name))


def parse_order_batch(batch_id: str) -> BatchImport:
    batch = load_batch(batch_id)
    batch.items = [review_imported_item(item) for item in batch.items]
    return save_batch(batch)


def export_review_csv_file(batch_id: str, output_path: Path | str | None = None) -> Path:
    batch = load_batch(batch_id)
    csv_content = export_review_csv(batch)
    if output_path:
        path = Path(output_path)
        if not path.is_absolute():
            path = _project_root() / path
    else:
        path = _project_root() / "outputs" / "reviews" / f"{batch_id}-review.csv"
    _ensure_project_output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(csv_content, encoding="utf-8")
    except OSError as exc:
        raise DomainError(
            code="REVIEW_CSV_SAVE_FAILED",
            message="Review CSV could not be written.",
            details={"path": _relative_project_path(path)},
            recoverable=True,
        ) from exc
    return path


def import_review_csv_file(path: Path | str) -> BatchImport:
    csv_path = Path(path)
    try:
        csv_content = csv_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DomainError(
            code="REVIEW_CSV_LOAD_FAILED",
            message="Review CSV could not be read.",
            details={"path": str(csv_path)},
            recoverable=True,
        ) from exc
    batch = _batch_for_review_csv(csv_content)
    return import_batch_review_csv(batch.batch_id, csv_content)


def import_batch_review_csv(batch_id: str, csv_content: str) -> BatchImport:
    batch = load_batch(batch_id)
    reviewed_batch = import_review_csv(batch, csv_content)
    return save_batch(reviewed_batch)


def review_order_job_decision(order_job_id: str, **decision: Any) -> BatchOrderItem:
    item = find_item(order_job_id)
    reviewed = apply_review_decision(
        item,
        customer_name=decision.get("customer_name"),
        month=decision.get("month"),
        flower=decision.get("flower"),
        color=decision.get("color"),
        font_option_no=decision.get("font_option_no"),
        font_id=decision.get("font_id"),
        personalization_role=decision.get("personalization_role"),
    )
    return replace_item(reviewed)


def generate_order_job_outputs(
    order_job_id: str,
    *,
    include_png: bool = False,
    exported_at: str | None = None,
) -> OrderOutputResult:
    item = find_item(order_job_id)
    if item.status != "READY" or item.parsed_order is None:
        raise DomainError(
            code="ORDER_REVIEW_REQUIRED",
            message="Order must be reviewed before generation.",
            details={"orderJobId": order_job_id, "status": item.status},
            recoverable=True,
        )
    document = apply_template(
        item.listing_id or "birth-flower-card",
        item.parsed_order,
        job_id=item.order_job_id,
    )
    _apply_review_font_ref(document, item)
    saved = _save_document_outputs(item, document, include_png=include_png, exported_at=exported_at)
    exported = replace(item, status="EXPORTED")
    replace_item(exported)
    return OrderOutputResult(item=exported, document=document, saved=saved)


def generate_order_job_draft(
    order_job_id: str,
    *,
    template_applicator=apply_template,
) -> tuple[BatchOrderItem, dict[str, Any]]:
    item = find_item(order_job_id)
    if item.status != "READY" or item.parsed_order is None:
        raise DomainError(
            code="ORDER_REVIEW_REQUIRED",
            message="Order must be reviewed before draft generation.",
            details={"orderJobId": order_job_id, "status": item.status},
            recoverable=True,
        )
    document = template_applicator("birth-flower-card", item.parsed_order, job_id=item.order_job_id)
    _apply_review_font_ref(document, item)
    generated = replace(item, status="GENERATED_DRAFT")
    replace_item(generated)
    return generated, document


def generate_batch_outputs(
    batch_id: str,
    *,
    include_png: bool = False,
    exported_at: str | None = None,
    layout: dict[str, Any] | None = None,
) -> BatchGenerateResult:
    batch = load_batch(batch_id)
    result_items: list[GeneratedBatchItem] = []
    items = list(batch.items)
    for index, item in enumerate(items):
        if item.status != "READY":
            continue
        try:
            document = apply_template(
                item.listing_id or "birth-flower-card",
                item.parsed_order,
                job_id=item.order_job_id,
            )
            _apply_review_font_ref(document, item)
            if layout:
                _apply_layout_overrides(document, layout)
            saved = _save_document_outputs(
                item,
                document,
                include_png=include_png,
                exported_at=exported_at,
            )
            exported = replace(item, status="EXPORTED")
            items[index] = exported
            result_items.append(
                GeneratedBatchItem(
                    order_job_id=item.order_job_id,
                    order_id=item.order_id,
                    status="EXPORTED",
                    output_dir=saved.output_dir,
                    files=tuple(file.relative_path for file in saved.files),
                )
            )
        except DomainError as exc:
            failed = replace(
                item,
                status="FAILED",
                issues=[
                    *item.issues,
                    ReviewIssue(
                        code=exc.code,
                        severity="blocking",
                        field="export",
                        message=exc.message,
                        requires_manual_action=True,
                    ),
                ],
            )
            items[index] = failed
            result_items.append(
                GeneratedBatchItem(
                    order_job_id=item.order_job_id,
                    order_id=item.order_id,
                    status="FAILED",
                    error=exc.message,
                )
            )
    save_batch(replace(batch, items=items))
    return BatchGenerateResult(batch_id=batch_id, items=tuple(result_items))


def _save_document_outputs(
    item: BatchOrderItem,
    document: dict[str, Any],
    *,
    include_png: bool,
    exported_at: str | None,
) -> SaveOutputsResult:
    # 与桌面导出一致:先把 SVG 素材做等比 contain-fit+居中+裁留白,避免模板写死框导致的拉伸变形。
    apply_svg_contain_fit(document)
    svg_export = export_svg(document, exported_at=exported_at)
    dxf_export = export_dxf(
        document,
        units=_nested(document, "exportSettings", "dxf", "units"),
        exported_at=exported_at,
    )
    if include_png:
        png_data_url = _png_data_url(svg_export.content, document)
        _mark_png_export(document, status="generated", reason=None)
    else:
        png_data_url = None
        _mark_png_export(document, status="skipped", reason=PNG_SKIPPED_REASON)
    return save_outputs(
        order_name=item.order_id or item.customer_name or item.order_job_id,
        document=document,
        svg=svg_export.content,
        png_data_url=png_data_url,
        dxf_content_base64=dxf_export.content_base64,
    )


def _apply_layout_overrides(document: dict[str, Any], layout: dict[str, Any]) -> None:
    """用桌面布局(birth_flower_config.json 的 layout_defaults)覆盖批量文档的画布与花朵/文字框,
    让批量产出与桌面单单一致 —— 布局单一来源。覆盖后由 _save_document_outputs 的 contain-fit
    把花朵等比塞进新的花朵框。layout 用普通 dict(键同 EngravingLayout),services/api 不依赖桌面类型。"""
    canvas = document.setdefault("canvas", {})
    if layout.get("canvas_width"):
        canvas["width"] = int(layout["canvas_width"])
    if layout.get("canvas_height"):
        canvas["height"] = int(layout["canvas_height"])
    # 画布比例变了:去掉写死的 heightMm,让导出按新画布比例派生 mm 高度(等比、不变形)。
    export_settings = document.setdefault("exportSettings", {})
    physical = export_settings.setdefault("physical", {})
    if isinstance(physical, dict):
        physical.pop("heightMm", None)
    for layer in document.get("layers", []):
        if not isinstance(layer, dict):
            continue
        if layer.get("type") == "svg":
            layer["x"] = float(layout.get("flower_x", layer.get("x", 0)))
            layer["y"] = float(layout.get("flower_y", layer.get("y", 0)))
            layer["width"] = float(layout.get("flower_width", layer.get("width", 0)))
            layer["height"] = float(layout.get("flower_height", layer.get("height", 0)))
            layer["scaleX"] = 1.0
            layer["scaleY"] = 1.0
        elif layer.get("type") == "text":
            layer["x"] = float(layout.get("text_x", layer.get("x", 0)))
            layer["y"] = float(layout.get("text_y", layer.get("y", 0)))
            layer["width"] = float(layout.get("text_width", layer.get("width", 0)))
            layer["height"] = float(layout.get("text_height", layer.get("height", 0)))
            style = layer.get("style")
            if not isinstance(style, dict):
                style = {}
                layer["style"] = style
            if layout.get("text_size"):
                style["fontSize"] = float(layout["text_size"])


def _mark_png_export(document: dict[str, Any], *, status: str, reason: str | None) -> None:
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        document["metadata"] = metadata
    payload: dict[str, Any] = {"status": status}
    if reason:
        payload["reason"] = reason
    metadata["pngExport"] = payload


def _apply_review_font_ref(document: dict[str, Any], item: BatchOrderItem) -> None:
    if item.font_option_no is None and not item.font_id:
        return
    for layer in document.get("layers", []):
        if not isinstance(layer, dict) or layer.get("type") != "text":
            continue
        raw_font_ref = layer.get("fontRef")
        font_ref: dict[str, Any] = raw_font_ref if isinstance(raw_font_ref, dict) else {}
        if item.font_option_no is not None:
            font_ref["optionNo"] = item.font_option_no
        if item.font_id:
            font_ref["assetId"] = item.font_id
        layer["fontRef"] = font_ref


def _png_data_url(svg: str, document: dict[str, Any]) -> str:
    canvas = document["canvas"]
    scale = float(_nested(document, "exportSettings", "png", "scale") or 1)
    width = round(float(canvas["width"]) * scale)
    height = round(float(canvas["height"]) * scale)
    with tempfile.TemporaryDirectory() as temp_dir:
        png_path = Path(temp_dir) / "preview.png"
        rasterize_svg_to_png(svg, width=width, height=height, output_path=png_path)
        return "data:image/png;base64," + base64.b64encode(png_path.read_bytes()).decode("ascii")


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
    image = Image.new("RGBA", (width, height), _canvas_background(canvas))
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


def _batch_for_review_csv(csv_content: str) -> BatchImport:
    reader = csv.DictReader(StringIO(csv_content.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise DomainError(
            code="REVIEW_CSV_INVALID",
            message="Review CSV has no header row.",
            recoverable=True,
        )
    order_job_ids: set[str] = set()
    order_ids: set[str] = set()
    for row in reader:
        if row.get("orderJobId"):
            order_job_ids.add(str(row["orderJobId"]).strip())
        if row.get("orderId"):
            order_ids.add(str(row["orderId"]).strip())

    matches = []
    for batch in list_batches():
        item_job_ids = {item.order_job_id for item in batch.items}
        item_order_ids = {item.order_id for item in batch.items if item.order_id}
        if order_job_ids and order_job_ids <= item_job_ids:
            matches.append(batch)
        elif not order_job_ids and order_ids and order_ids <= item_order_ids:
            matches.append(batch)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise DomainError(
            code="REVIEW_CSV_BATCH_AMBIGUOUS",
            message="Review CSV matches multiple batches; use a CSV with orderJobId values.",
            recoverable=True,
        )
    raise DomainError(
        code="REVIEW_CSV_BATCH_NOT_FOUND",
        message="Review CSV does not match any saved batch.",
        recoverable=True,
    )


def _ensure_project_output_path(path: Path) -> None:
    resolved = path.resolve()
    root = (_project_root() / "outputs").resolve()
    if root != resolved and root not in resolved.parents:
        raise DomainError(
            code="PATH_TRAVERSAL_BLOCKED",
            message="Review CSV path is outside the outputs directory.",
            details={"path": str(path)},
            recoverable=True,
        )


def _relative_project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(_project_root()).as_posix()
    except ValueError:
        return path.name


def _project_root() -> Path:
    default_root = Path(__file__).resolve().parents[5]
    return Path(os.environ.get("FLOWER_PROJECT_ROOT", default_root)).resolve()


def _nested(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
