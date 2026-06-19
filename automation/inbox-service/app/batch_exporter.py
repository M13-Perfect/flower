from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db import session_scope
from app.models import STATUS_QUEUED, STATUS_WRITTEN, Order

# 待导出 = 已写入收件夹、尚未跑过批量（或已排队但还没出报告）。已完成/无法自动生成的不再导出。
EXPORTABLE_STATUSES = (STATUS_WRITTEN, STATUS_QUEUED)
# 对齐 services/api 的 dianxiaomi-xlsx 适配器：A 列=order_id，B 列=备注，首行表头（被跳过）。
BATCH_HEADERS = ["订单号", "备注"]


def _pending_orders(session: Session) -> list[Order]:
    stmt = select(Order).where(Order.status.in_(EXPORTABLE_STATUSES)).order_by(Order.received_at.asc())
    return list(session.scalars(stmt))


def export_pool_to_xlsx(
    factory: sessionmaker[Session], batches_dir: Path, *, now: datetime | None = None
) -> tuple[Path | None, int]:
    """把池中待生成订单导出成店小秘格式 xlsx，并标记为 QUEUED_FOR_BATCH。

    无待导出订单时返回 (None, 0)。操作员随后用 Flower 现有「导入」对这个 xlsx 跑批量生成。
    """
    now = now or datetime.now()
    with session_scope(factory) as session:
        orders = _pending_orders(session)
        if not orders:
            return None, 0
        batches_dir = Path(batches_dir)
        batches_dir.mkdir(parents=True, exist_ok=True)
        stamp = now.strftime("%Y%m%d-%H%M%S")
        path = batches_dir / f"pooled-{stamp}-{len(orders)}.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(BATCH_HEADERS)
        for order in orders:
            sheet.append([order.order_id, order.remark])
        workbook.save(path)
        for order in orders:
            order.status = STATUS_QUEUED
        return path, len(orders)
