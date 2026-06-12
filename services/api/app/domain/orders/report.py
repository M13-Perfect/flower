from __future__ import annotations

import csv
import os
from pathlib import Path

from app.domain import DomainError


REPORT_HEADERS = ["订单号", "状态", "是否需人工核验", "原因汇总", "素材文件路径"]


def write_batch_report(batch_id: str, rows: list[dict[str, object]]) -> Path:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise DomainError(
            code="DEPENDENCY_MISSING",
            message="openpyxl is required to write batch reports.",
            details={"package": "openpyxl"},
            recoverable=False,
        ) from exc

    report_dir = _report_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{batch_id}-report.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Report"
    worksheet.append(REPORT_HEADERS)
    for row in rows:
        worksheet.append(
            [
                str(row.get("orderId") or ""),
                str(row.get("status") or ""),
                "是" if row.get("needsManualReview") else "否",
                str(row.get("reasonSummary") or ""),
                str(row.get("assetPaths") or ""),
            ]
        )
    workbook.save(path)
    return path


def write_review_csv(batch_id: str, rows: list[dict[str, object]]) -> Path:
    report_dir = _report_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{batch_id}-review.csv"
    review_rows = [row for row in rows if row.get("needsManualReview")]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_HEADERS)
        writer.writeheader()
        for row in review_rows:
            writer.writerow(
                {
                    "订单号": str(row.get("orderId") or ""),
                    "状态": str(row.get("status") or ""),
                    "是否需人工核验": "是",
                    "原因汇总": str(row.get("reasonSummary") or ""),
                    "素材文件路径": str(row.get("assetPaths") or ""),
                }
            )
    return path


def _report_dir() -> Path:
    return (_project_root() / "outputs" / "reports").resolve()


def _project_root() -> Path:
    default_root = Path(__file__).resolve().parents[5]
    return Path(os.environ.get("FLOWER_PROJECT_ROOT", default_root)).resolve()
