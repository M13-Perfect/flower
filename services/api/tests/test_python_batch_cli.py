from __future__ import annotations

import base64
import csv
import json
from io import StringIO
import os
from pathlib import Path
import shutil
import struct
import sys
from types import SimpleNamespace
import types
import xml.etree.ElementTree as ET
import zlib

from app.cli import main as cli_main
from app.domain.orders import batch_store
from app.domain.orders.workflow import (
    export_review_csv_file,
    generate_batch_outputs,
    import_orders_file,
    import_orders_csv_file,
    import_review_csv_file,
)
from app.domain.exports.png import read_png_size


EXPORTED_AT = "2026-06-12T12:00:00.000Z"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "orders"
REPO_ROOT = Path(__file__).resolve().parents[3]
NOTE_A = (
    "Choose Your Birth Flower: My Own Design / Font Design: My Own Design / "
    "Personalization: Make the flower a hydrangea and the name on the box should be "
    "Kristianna. Use the same font as the bottom box shown in the first picture."
)
NOTE_B = "Choose You Flower: May - Lily of the valley / Color: Green / Personalization: 5-14-22"


def test_python_batch_workflow_generates_golden_svg_dxf_and_optional_png(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path
    prepare_project_root(project_root)
    monkeypatch.setenv("FLOWER_PROJECT_ROOT", str(project_root))
    monkeypatch.setattr(batch_store, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(
        "app.domain.orders.workflow.export_dxf",
        lambda document, exported_at=None, units=None: fake_dxf(document),
    )
    monkeypatch.setitem(sys.modules, "cairosvg", types.SimpleNamespace(svg2png=fake_svg2png))
    orders_csv = project_root / "orders.csv"
    orders_csv.write_text(orders_csv_text(), encoding="utf-8")

    batch = import_orders_csv_file(orders_csv)

    assert batch.batch_id.startswith("batch_")
    statuses = {item.order_id: item.status for item in batch.items}
    assert statuses["A1001"] == "BLOCKED"
    assert statuses["B1001"] == "NEEDS_REVIEW"

    review_path = export_review_csv_file(batch.batch_id)
    filled_path = fill_review_csv(review_path)
    reviewed = import_review_csv_file(filled_path)

    assert {item.order_id: item.status for item in reviewed.items} == {
        "A1001": "READY",
        "B1001": "READY",
    }

    result = generate_batch_outputs(batch.batch_id, include_png=True, exported_at=EXPORTED_AT)

    assert result.generated_count == 2
    assert result.failed_count == 0
    output_a = project_root / "outputs" / "A1001"
    output_b = project_root / "outputs" / "B1001"
    svg_a = (output_a / "A1001.svg").read_text(encoding="utf-8")
    svg_b = (output_b / "B1001.svg").read_text(encoding="utf-8")
    dxf_a = (output_a / "A1001.dxf").read_text(encoding="utf-8")
    dxf_b = (output_b / "B1001.dxf").read_text(encoding="utf-8")
    assert_production_svg(svg_a)
    assert_production_svg(svg_b)
    assert svg_a == golden("real_note_a.svg", svg_a)
    assert dxf_a == golden("real_note_a.dxf", dxf_a)
    assert svg_b == golden("real_note_b.svg", svg_b)
    assert dxf_b == golden("real_note_b.dxf", dxf_b)
    assert read_png_size((output_a / "A1001.png").read_bytes()) == (3000, 3000)
    assert read_png_size((output_b / "B1001.png").read_bytes()) == (3000, 3000)


def test_python_batch_workflow_imports_xlsx_without_review_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepare_xlsx_project_root(tmp_path)
    monkeypatch.setenv("FLOWER_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(batch_store, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "app.domain.orders.workflow.export_dxf",
        lambda document, exported_at=None, units=None: fake_dxf(document),
    )
    monkeypatch.setitem(sys.modules, "cairosvg", types.SimpleNamespace(svg2png=fake_svg2png))

    batch = import_orders_file(FIXTURE_DIR / "test.xlsx", batch_id="batch_xlsx")

    assert [item.status for item in batch.items] == ["READY", "READY", "READY"]
    review_path = export_review_csv_file(batch.batch_id)
    assert review_path.read_text(encoding="utf-8").count("\n") == 1

    result = generate_batch_outputs(batch.batch_id, exported_at=EXPORTED_AT)

    assert result.generated_count == 3
    for order_id in ("4087956129", "4087958577", "4087970477"):
        output_dir = tmp_path / "outputs" / order_id
        document = json.loads((output_dir / "order.json").read_text(encoding="utf-8"))
        assert document["metadata"]["pngExport"]["status"] == "skipped"
        assert "Cairo" in document["metadata"]["pngExport"]["reason"]
        assert_production_svg((output_dir / f"{order_id}.svg").read_text(encoding="utf-8"))
        assert (output_dir / f"{order_id}.dxf").is_file()
        assert not (output_dir / f"{order_id}.png").exists()


def test_python_batch_cli_runs_review_loop_commands(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    prepare_project_root(tmp_path)
    monkeypatch.setenv("FLOWER_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(batch_store, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "app.domain.orders.workflow.export_dxf",
        lambda document, exported_at=None, units=None: fake_dxf(document),
    )
    monkeypatch.setitem(sys.modules, "cairosvg", types.SimpleNamespace(svg2png=fake_svg2png))
    orders_csv = tmp_path / "orders.csv"
    orders_csv.write_text(orders_csv_text(), encoding="utf-8")

    assert cli_main(["import-orders", "--source", str(orders_csv), "--batch-id", "cli_batch"]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["summary"]["blocked"] == 1
    assert imported["summary"]["needsReview"] == 1

    review_path = tmp_path / "outputs" / "reviews" / "cli-review.csv"
    assert cli_main(["export-review", "--batch-id", "cli_batch", "--output", str(review_path)]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert Path(exported["path"]) == review_path

    filled_path = fill_review_csv(review_path)
    assert cli_main(["import-review", "--source", str(filled_path)]) == 0
    reviewed = json.loads(capsys.readouterr().out)
    assert reviewed["summary"]["ready"] == 2

    assert cli_main(["generate", "--batch-id", "cli_batch", "--exported-at", EXPORTED_AT]) == 0
    generated = json.loads(capsys.readouterr().out)
    assert generated["generated"] == 2
    # 测试环境注入了假 cairosvg,自动探测应判定可用并默认产出 PNG
    assert generated["png"]["enabled"] is True
    assert generated["png"]["skippedReason"] is None
    assert {item["status"] for item in generated["items"]} == {"EXPORTED"}
    assert all(
        any(file.endswith(".png") for file in item["files"]) for item in generated["items"]
    )


def prepare_project_root(project_root: Path) -> None:
    template_dir = project_root / "templates" / "products"
    flower_dir = project_root / "assets" / "flowers"
    template_dir.mkdir(parents=True)
    flower_dir.mkdir(parents=True)
    (template_dir / "birth-flower-card.json").write_text(
        """
        {
          "schemaVersion": "1.0",
          "templateId": "birth-flower-card",
          "version": "1.0.0",
          "productType": "birth-flower",
          "displayName": "Birth Flower Card",
          "canvas": {
            "width": 3000,
            "height": 3000,
            "unit": "px",
            "background": { "type": "solid", "color": "#ffffff" }
          },
          "exportSettings": {
            "physical": { "widthMm": 80 },
            "dxf": { "textMode": "paths", "units": "mm" }
          },
          "slots": [
            { "slotId": "customer_name", "kind": "text", "required": true },
            { "slotId": "flower", "kind": "svg", "required": true }
          ]
        }
        """,
        encoding="utf-8",
    )
    (flower_dir / "may-hydrangea.svg").write_text(
        '<svg viewBox="0 0 10 10"><path d="M0 0 L10 0 L10 10 Z"/></svg>',
        encoding="utf-8",
    )
    (flower_dir / "may-lily-of-the-valley.svg").write_text(
        '<svg viewBox="0 0 10 10"><path d="M1 1 L9 1 L5 9 Z"/></svg>',
        encoding="utf-8",
    )
    copy_test_font(project_root)


def prepare_xlsx_project_root(project_root: Path) -> None:
    template_dir = project_root / "templates" / "products"
    asset_dir = project_root / "BirthMonth flowers"
    template_dir.mkdir(parents=True)
    asset_dir.mkdir()
    (template_dir / "birth-flower-card.json").write_text(
        (REPO_ROOT / "templates" / "products" / "birth-flower-card.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    for name in ("AsterSeptember .svg", "JuneRose.svg", "SnowdropJanuary .svg"):
        (asset_dir / name).write_text(
            '<svg viewBox="0 0 10 10"><path d="M0 0 L10 0 L10 10 L0 0"/></svg>',
            encoding="utf-8",
        )
    copy_test_font(project_root)


def copy_test_font(project_root: Path) -> None:
    font_source = REPO_ROOT / "Birthmonth_font.ttf"
    if font_source.is_file():
        shutil.copy2(font_source, project_root / "Birthmonth_font.ttf")


def orders_csv_text() -> str:
    output = StringIO()
    fieldnames = [
        "orderId",
        "listingId",
        "listingVersion",
        "orderNote",
        "personalization",
        "variation",
    ]
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerow(
        {
            "orderId": "A1001",
            "listingId": "birth-flower-card",
            "listingVersion": "2026-06",
            "orderNote": NOTE_A,
            "personalization": (
                "Make the flower a hydrangea and the name on the box should be Kristianna."
            ),
            "variation": "Font Design: My Own Design",
        }
    )
    writer.writerow(
        {
            "orderId": "B1001",
            "listingId": "birth-flower-card",
            "listingVersion": "2026-06",
            "orderNote": NOTE_B,
            "personalization": "5-14-22",
            "variation": "Color: Green",
        }
    )
    return output.getvalue()


def fill_review_csv(review_path: Path) -> Path:
    rows = list(csv.DictReader(StringIO(review_path.read_text(encoding="utf-8"))))
    for row in rows:
        if row["orderId"] == "A1001":
            row.update(
                {
                    "customerName": "Kristianna",
                    "month": "5",
                    "flower": "hydrangea",
                    "fontOptionNo": "5",
                    "fontId": "lovely-script",
                    "personalizationRole": "name",
                }
            )
        if row["orderId"] == "B1001":
            row.update(
                {
                    "customerName": "5-14-22",
                    "month": "5",
                    "flower": "Lily of the Valley",
                    "color": "Green",
                    "fontOptionNo": "5",
                    "fontId": "lovely-script",
                    "personalizationRole": "date",
                }
            )
    filled_path = review_path.with_name("filled-review.csv")
    with filled_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return filled_path


def fake_dxf(document: dict, exported_at: str | None = None) -> SimpleNamespace:
    order_id = document["metadata"]["orderId"]
    content = f"DXF {order_id}\n"
    return SimpleNamespace(
        content_base64=base64.b64encode(content.encode("utf-8")).decode("ascii"),
        warnings=[],
    )


def fake_svg2png(
    *,
    bytestring: bytes,
    write_to: str,
    output_width: int,
    output_height: int,
) -> None:
    assert b"<svg" in bytestring
    assert b"<text" not in bytestring
    assert b"<image" not in bytestring
    assert b'data-layer-id="layer_flower"' in bytestring
    assert b'data-layer-id="layer_customer_name"' in bytestring
    Path(write_to).write_bytes(tiny_png(output_width, output_height))


def tiny_png(width: int, height: int) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"\x00" + b"\x00\x00\x00\x00" * width
    idat = zlib.compress(raw * height)
    return signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def golden(name: str, actual: str | None = None) -> str:
    # 快照更新模式:FLOWER_UPDATE_GOLDEN=1 时写入新基准(仅在产物经断言确认后使用)。
    path = Path(__file__).parent / "golden" / name
    if actual is not None and os.environ.get("FLOWER_UPDATE_GOLDEN"):
        path.write_text(actual, encoding="utf-8")
        return actual
    return path.read_text(encoding="utf-8")


def assert_production_svg(svg: str) -> None:
    assert svg.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert svg.count("<?xml") == 1
    assert "<text" not in svg
    assert "<image" not in svg
    assert ET.fromstring(svg) is not None


def test_apply_layout_overrides_uses_desktop_layout():
    """批量按桌面 layout_defaults 覆盖画布与花朵/文字框(单一布局来源),与桌面单单一致。"""
    from app.domain.orders.workflow import _apply_layout_overrides

    document = {
        "canvas": {"width": 3000, "height": 3000, "unit": "px"},
        "exportSettings": {"physical": {"widthMm": 80, "heightMm": 80}},
        "layers": [
            {"type": "svg", "x": 900, "y": 420, "width": 1200, "height": 1400, "scaleX": 1, "scaleY": 1},
            {"type": "text", "x": 600, "y": 2200, "width": 1800, "height": 260, "style": {"fontSize": 180}},
        ],
    }
    layout = {
        "canvas_width": 1732, "canvas_height": 1280,
        "flower_x": 310, "flower_y": 40, "flower_width": 1060, "flower_height": 1060,
        "text_x": 700, "text_y": 830, "text_width": 804, "text_height": 260, "text_size": 190,
    }
    _apply_layout_overrides(document, layout)

    assert (document["canvas"]["width"], document["canvas"]["height"]) == (1732, 1280)
    # 去掉写死 heightMm → 导出按画布比例派生 mm 高度(等比、不变形)。
    assert "heightMm" not in document["exportSettings"]["physical"]
    flower = document["layers"][0]
    assert (flower["x"], flower["y"], flower["width"], flower["height"]) == (310, 40, 1060, 1060)
    text = document["layers"][1]
    assert (text["x"], text["y"], text["width"], text["height"]) == (700, 830, 804, 260)
    assert text["style"]["fontSize"] == 190
