from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from app.report_watcher import apply_report_file

REPORT_HEADERS = ["订单号", "状态", "是否需人工核验", "原因汇总", "素材文件路径"]


def _write_report(reports_dir: Path, batch_id: str, rows: list[tuple]) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{batch_id}-report.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(REPORT_HEADERS)
    for row in rows:
        sheet.append(list(row))
    workbook.save(path)
    return path


def test_report_writeback_marks_done_and_cannot_autogen(client, app, settings):
    for order_id in ("ORD-1", "ORD-2", "ORD-3"):
        client.post(
            "/inbox/orders",
            json={"schema_version": "1.0", "order_id": order_id, "remark": f"{order_id} remark"},
        )

    report = _write_report(
        settings.reports_dir,
        "batch-xyz",
        [
            ("ORD-1", "EXPORTED", "否", "", "outputs/orders/ORD-1/flower.dxf"),
            ("ORD-2", "BLOCKED", "是", "ORDER_PARSE_FAILED: missingFields=['month']", ""),
            ("ORD-3", "NEEDS_REVIEW", "是", "CUSTOM_FLOWER_REQUIRED", ""),
            ("ZZZ-unknown", "EXPORTED", "否", "", ""),  # 不在池中 → 跳过
        ],
    )

    summary = apply_report_file(app.state.session_factory, report)
    assert summary == {"done": 1, "cannot_autogen": 2, "unknown": 0, "skipped": 1}

    done = client.get("/inbox/orders/ORD-1").json()
    assert done["status"] == "DONE"
    assert done["done_at"] is not None

    blocked = client.get("/inbox/orders/ORD-2").json()
    assert blocked["status"] == "CANNOT_AUTOGEN"
    assert "ORDER_PARSE_FAILED" in blocked["reason"]

    review = client.get("/inbox/orders/ORD-3").json()
    assert review["status"] == "CANNOT_AUTOGEN"
    assert review["reason"] == "CUSTOM_FLOWER_REQUIRED"


def test_sync_endpoint_applies_reports(client, settings):
    client.post("/inbox/orders", json={"schema_version": "1.0", "order_id": "ORD-9", "remark": "x"})
    _write_report(settings.reports_dir, "batch-9", [("ORD-9", "EXPORTED", "否", "", "out.dxf")])

    body = client.post("/inbox/batch/sync").json()
    assert body["count"] == 1
    assert client.get("/inbox/orders/ORD-9").json()["status"] == "DONE"
