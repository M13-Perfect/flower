from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.batch_exporter import export_pool_to_xlsx
from app.db import session_scope
from app.inbox_writer import InboxWriteError, write_order_file
from app.models import STATUS_WRITE_FAILED, STATUS_WRITTEN, utcnow
from app.repository import get_order, recent_orders, upsert_order
from app.schemas import IngestResponse, OrderPayload

router = APIRouter()


@router.get("/healthz")
def healthz(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "service": "flower-inbox",
        "inbox_dir": str(settings.inbox_dir),
        "db_path": str(settings.db_path),
        "schema_version": settings.schema_version,
    }


@router.post("/inbox/orders", response_model=IngestResponse)
def ingest_order(payload: OrderPayload, request: Request) -> IngestResponse:
    """闸 1：校验通过 → SQLite 去重 upsert → 原子写 {order_id}.json 到收件夹。"""
    settings = request.app.state.settings
    if payload.schema_version != settings.schema_version:
        raise HTTPException(
            status_code=422,
            detail=(
                f"schema_version 不符（收到 {payload.schema_version!r}，"
                f"期望 {settings.schema_version!r}）；请更新扩展。"
            ),
        )
    raw_json = payload.model_dump_json()
    file_payload = payload.model_dump()
    factory = request.app.state.session_factory

    write_error: str | None = None
    final_path = None
    with session_scope(factory) as session:
        order, dedup = upsert_order(session, payload, raw_json)
        try:
            final_path = write_order_file(settings.inbox_dir, payload.order_id, file_payload)
        except InboxWriteError as exc:
            order.status = STATUS_WRITE_FAILED
            order.error = str(exc)
            write_error = str(exc)
        else:
            order.status = STATUS_WRITTEN
            order.error = None
            order.inbox_path = str(final_path)
            order.written_at = utcnow()
        response = IngestResponse(
            order_id=order.order_id,
            status=order.status,
            dedup=dedup,
            inbox_path=str(final_path) if final_path is not None else None,
        )
    if write_error is not None:
        raise HTTPException(status_code=500, detail=f"写收件夹失败：{write_error}")
    return response


@router.get("/inbox/orders")
def list_orders(request: Request) -> dict:
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        orders = recent_orders(session)
        return {"orders": [order.to_dict() for order in orders], "count": len(orders)}


@router.get("/inbox/orders/{order_id}")
def get_order_status(order_id: str, request: Request) -> dict:
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        order = get_order(session, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail=f"未找到订单 {order_id!r}")
        return order.to_dict()


@router.post("/inbox/batch/export")
def export_batch(request: Request) -> dict:
    """把池中待生成订单导出成店小秘格式 xlsx，供操作员用 Flower 现有「导入」跑批量生成。"""
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    path, count = export_pool_to_xlsx(factory, settings.batches_dir)
    return {"path": str(path) if path is not None else None, "count": count}


@router.post("/inbox/batch/sync")
def sync_reports(request: Request) -> dict:
    """扫描 outputs/reports 的批量报告，把每单状态回写为 已完成 / 无法自动生成。"""
    watcher = request.app.state.report_watcher
    applied = watcher.scan_once()
    return {"applied": [path.name for path in applied], "count": len(applied)}
