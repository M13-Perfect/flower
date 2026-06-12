from __future__ import annotations

import shutil
import zipfile
import xml.etree.ElementTree as ET
import json
from pathlib import Path

import pytest

from app.domain.orders.batch_generate import generate_batch
from app.domain.orders.batch_import import import_orders
from app.domain.orders.batch_store import save_batch


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "orders"
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_generate_batch_from_real_dianxiaomi_fixture_writes_assets_and_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_project_root(tmp_path)
    monkeypatch.setenv("FLOWER_PROJECT_ROOT", str(tmp_path))
    save_batch(import_orders(FIXTURE_DIR / "test.xlsx", batch_id="batch_real"))

    result = generate_batch("batch_real")

    assert [item.status for item in result.items] == ["EXPORTED", "EXPORTED", "EXPORTED"]
    for order_id in ("4087956129", "4087958577", "4087970477"):
        order_dir = tmp_path / "outputs" / order_id
        assert (order_dir / "order.json").is_file()
        document = json.loads((order_dir / "order.json").read_text(encoding="utf-8"))
        assert document["metadata"]["pngExport"]["status"] == "skipped"
        assert "<svg" in (order_dir / f"{order_id}.svg").read_text(encoding="utf-8")
        dxf_text = (order_dir / f"{order_id}.dxf").read_text(encoding="utf-8")
        assert "SECTION" in dxf_text
        assert "EOF" in dxf_text
        assert not (order_dir / f"{order_id}.png").exists()

    report_path = tmp_path / "outputs" / "reports" / "batch_real-report.xlsx"
    rows = _read_xlsx_rows(report_path)
    assert rows[0] == ["订单号", "状态", "是否需人工核验", "原因汇总", "素材文件路径"]
    assert rows[1][0:3] == ["4087956129", "EXPORTED", "否"]
    assert rows[2][0:3] == ["4087958577", "EXPORTED", "否"]
    assert rows[3][0:3] == ["4087970477", "EXPORTED", "否"]
    assert "4087956129.svg" in rows[1][4]


def test_generate_batch_reports_my_own_design_as_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_project_root(tmp_path)
    monkeypatch.setenv("FLOWER_PROJECT_ROOT", str(tmp_path))
    csv_path = tmp_path / "my-own-design.csv"
    csv_path.write_text(
        "orderId,orderNote\n"
        '9001,"Choose Your Birth Flower: My Own Design\n'
        "Font Design: My Own Design\n"
        'Personalization: Make the flower hydrangea for Kristianna"\n',
        encoding="utf-8",
    )
    save_batch(import_orders(csv_path, batch_id="batch_blocked"))

    result = generate_batch("batch_blocked")

    assert result.items[0].status == "BLOCKED"
    assert result.items[0].needs_manual_review is True
    assert "My Own Design" in result.items[0].reason_summary
    assert not (tmp_path / "outputs" / "9001" / "9001.svg").exists()

    rows = _read_xlsx_rows(tmp_path / "outputs" / "reports" / "batch_blocked-report.xlsx")
    assert rows[1][0:3] == ["9001", "BLOCKED", "是"]
    assert "My Own Design" in rows[1][3]
    review_csv = tmp_path / "outputs" / "reports" / "batch_blocked-review.csv"
    assert review_csv.read_bytes().startswith(b"\xef\xbb\xbf")


def _prepare_project_root(project_root: Path) -> None:
    template_dir = project_root / "templates" / "products"
    asset_dir = project_root / "BirthMonth flowers"
    template_dir.mkdir(parents=True)
    asset_dir.mkdir()
    shutil.copy2(REPO_ROOT / "templates" / "products" / "birth-flower-card.json", template_dir / "birth-flower-card.json")
    for name in ("AsterSeptember .svg", "JuneRose.svg", "SnowdropJanuary .svg"):
        (asset_dir / name).write_text(
            '<svg viewBox="0 0 10 10"><path d="M0 0 L10 0 L10 10 L0 0"/></svg>',
            encoding="utf-8",
        )
    font_source = REPO_ROOT / "Birthmonth_font.ttf"
    if not font_source.is_file():
        pytest.skip("Birthmonth_font.ttf is required for local DXF text path generation.")
    shutil.copy2(font_source, project_root / "Birthmonth_font.ttf")


def _read_xlsx_rows(path: Path) -> list[list[str]]:
    namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", namespace):
                shared_strings.append("".join(node.text or "" for node in item.findall(".//a:t", namespace)))
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows: list[list[str]] = []
    for row in sheet.findall(".//a:sheetData/a:row", namespace):
        values: list[str] = []
        for cell in row.findall("a:c", namespace):
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                values.append("".join(node.text or "" for node in cell.findall(".//a:t", namespace)))
                continue
            raw = cell.findtext("a:v", default="", namespaces=namespace)
            values.append(shared_strings[int(raw)] if cell_type == "s" and raw else raw)
        rows.append(values)
    return rows
