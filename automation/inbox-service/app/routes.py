from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError

from app.authorization import (
    ACTION_MARK,
    ACTION_SCRAPE,
    action_allowed,
    is_authorized,
    now_naive,
    order_in_scope,
    paid_in_time_window,
)
from app.batch_exporter import export_pool_to_xlsx
from app.db import session_scope
from app.inbox_writer import InboxWriteError, write_order_file
from app.models import (
    AI_STATUS_RECOGNIZED,
    MARK_ACTION_DONE,
    MARK_ACTION_UNRECOGNIZED,
    STATUS_WRITE_FAILED,
    STATUS_WRITTEN,
    ScrapeControl,
    utcnow,
)
from app.refund_gate import STAGE_LABELS, decide
from app.run_mode import (
    VALID_MODES,
    clear_dir_files,
    effective_batches_dir,
    effective_inbox_dir,
)
from app.repository import (
    count_orders,
    delete_order,
    enqueue_mark_job,
    get_order,
    get_scrape_control,
    has_active_mark_done,
    heartbeat_scrape_task,
    oldest_pending_order,
    pending_mark_jobs,
    purge_orders_older_than,
    recent_mark_jobs,
    recent_orders,
    recent_refund_checks,
    reconcile_ai_status,
    record_refund_check,
    resolve_mark_job,
    set_ai_status,
    start_scrape_task,
    stop_scrape_task,
    supersede_mark_job,
    upsert_order,
    upsert_scrape_control,
)
from app.scheduler import (
    advance_checkpoint,
    due_for_recheck,
    get_checkpoint,
    resolve_window,
    select_due_orders,
)
from app.scrape_planner import ManifestEntry, diff_manifest, parse_paid_at
from app.schemas import (
    AiReconcileBody,
    IngestBatchRequest,
    IngestResponse,
    MarkRequestBody,
    MarkResultBody,
    OrderPayload,
    PurgeRequest,
    RecheckRequest,
    RecheckResponse,
    RescrapeRequestBody,
    RescrapeResultBody,
    RunModeUpdate,
    ScanRequest,
    ScrapeControlUpdate,
    ScrapeDiffRequest,
    ScrapeTaskHeartbeat,
    ScrapeTaskStart,
    ScrapeTaskStop,
)

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


def _ingest_one(
    session, payload: OrderPayload, settings, inbox_dir, control: ScrapeControl | None,
    enqueue_mark: bool = True,
) -> tuple[IngestResponse, str | None]:
    """单条入库核心（单条/批量共用）：去重 upsert → 原子写 {order_id}.json → 成功则确保「AI未识别」标记任务。

    返回 (IngestResponse, write_error)；write_error 非空表示文件写失败（不抛，由调用方决定 500/记录），
    DB 提交由外层 session_scope 负责（批量=一事务多单，少 fsync、提吞吐）。

    ⚠️ P0：自动入队「AI未识别」打标只在订单落在**当前任务授权范围**内才做（order_in_scope）——
    否则历史 / 范围外订单会被自动打标。
    ``enqueue_mark=False``：手动「→Flower」单笔路径专用——服务端**绝不入队 mark_job**（不留打标痕迹，
    用户决策 2026-06-22），打标由扩展按条件决策表纯页面完成；避免「手动单恰落活跃任务范围内 → 服务端旁路打标」。
    """
    raw_json = payload.model_dump_json()
    file_payload = payload.model_dump()
    order, dedup, content_same, created = upsert_order(session, payload, raw_json)
    # 内容与上次逐字节一致且此前已成功落收件夹 → 真·no-op：不重写文件、不重触发 flower 监听、
    # 不重入队标记、不动生命周期状态（避免把已 DONE/QUEUED 的单打回、或重复生成）。
    noop = content_same and order.inbox_path is not None and order.status != STATUS_WRITE_FAILED
    if noop:
        return (
            IngestResponse(
                order_id=order.order_id, status=order.status, dedup=dedup,
                inbox_path=order.inbox_path, unchanged=True, created=False,
            ),
            None,
        )
    final_path = None
    write_error: str | None = None
    try:
        final_path = write_order_file(inbox_dir, payload.order_id, file_payload)
    except InboxWriteError as exc:
        order.status = STATUS_WRITE_FAILED
        order.error = str(exc)
        write_error = str(exc)
    else:
        order.status = STATUS_WRITTEN
        order.error = None
        order.inbox_path = str(final_path)
        order.written_at = utcnow()
        # 标准2：上传成功 → 确保「AI未识别」标记任务（除非该单已/将「AI已处理」）。幂等：扩展跳过已标记的。
        # ⚠️ P0：仅当订单在**当前任务授权范围**内才入队（无任务/范围外/未授权 → 不打标，防历史订单被误标）。
        if (
            enqueue_mark
            and settings.mark_enqueue_unrecognized
            and order_in_scope(control, paid_at=order.paid_at, shop=order.shop)
            and not has_active_mark_done(session, order.order_id)
        ):
            enqueue_mark_job(session, order.order_id, MARK_ACTION_UNRECOGNIZED)
    return (
        IngestResponse(
            order_id=order.order_id, status=order.status, dedup=dedup,
            inbox_path=str(final_path) if final_path is not None else None,
            unchanged=False, created=created,
        ),
        write_error,
    )


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
    factory = request.app.state.session_factory
    # D3：按运行模式选收件夹（test_reset → sandbox，绝不碰生产 outputs/）。
    inbox_dir = effective_inbox_dir(settings, request.app.state.run_mode)
    # 单端=手动「→Flower」路径：始终允许上传（人主动点一单），不要求任务授权。
    # ?manual=1（扩展手动按钮）：服务端不入队 mark_job（不留打标痕迹，打标由扩展按条件决策表纯页面完成，2026-06-22）；
    # 不带该参数的单条上传（如定向重抓 FLOWER_SEND_ORDER）维持原入队行为不变。
    manual = request.query_params.get("manual") in ("1", "true", "True")
    with session_scope(factory) as session:
        control = get_scrape_control(session)
        response, write_error = _ingest_one(
            session, payload, settings, inbox_dir, control, enqueue_mark=not manual
        )
    if write_error is not None:
        raise HTTPException(status_code=500, detail=f"写收件夹失败：{write_error}")
    return response


@router.post("/inbox/orders/batch")
def ingest_orders_batch(payload: IngestBatchRequest, request: Request) -> dict:
    """批量入库（阶段二抓取吞吐）：一次回传多单、一个事务提交（少 fsync）。

    每单独立处理：schema 不符 / 文件写失败只记进该单结果、不连累整批；返回逐单 results + 写成/失败计数。
    """
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    inbox_dir = effective_inbox_dir(settings, request.app.state.run_mode)
    results: list[dict] = []
    written = 0
    failed = 0
    with session_scope(factory) as session:
        control = get_scrape_control(session)
        # ⚠️ P0：批量入库=扩展自动抓取路径，必须有有效任务授权（scrape 操作）。否则整批拒绝（fail-closed）。
        if not action_allowed(control, ACTION_SCRAPE):
            raise HTTPException(
                status_code=403,
                detail="无有效任务授权（任务缺失/已过期/已停止），拒绝自动入库。请在 Flower 创建采集任务。",
            )
        for order_payload in payload.orders:
            if order_payload.schema_version != settings.schema_version:
                results.append({
                    "order_id": order_payload.order_id, "status": "schema_mismatch",
                    "dedup": False, "inbox_path": None, "unchanged": False,
                    "error": f"schema_version 不符（收到 {order_payload.schema_version!r}，期望 {settings.schema_version!r}）",
                })
                failed += 1
                continue
            # 范围闸（第二处校验）：即使扩展回传了范围外/历史订单，也在入库前拦掉，不写不打标。
            paid_at = parse_paid_at(order_payload.extras.get("paid_at"))
            if not order_in_scope(control, paid_at=paid_at, shop=order_payload.shop):
                results.append({
                    "order_id": order_payload.order_id, "status": "out_of_scope",
                    "dedup": False, "inbox_path": None, "unchanged": False,
                    "error": "订单不在当前任务时间/店铺范围内（已拦截，未入库）",
                })
                failed += 1
                continue
            response, write_error = _ingest_one(session, order_payload, settings, inbox_dir, control)
            item = response.model_dump()
            if write_error is not None:
                item["error"] = write_error
                failed += 1
            else:
                written += 1
            results.append(item)
    return {"results": results, "count": len(results), "written": written, "failed": failed}


@router.get("/inbox/orders")
def list_orders(
    request: Request,
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """列订单（按 received_at 倒序分页）。count=真实总数，returned=本页条数（订单表「共 N 单」用 count）。

    默认 limit=100（当前 UI 未虚拟化前别一次灌太多）；阶段三虚拟列表就位后由调用方放大 limit。
    """
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        total = count_orders(session)
        orders = recent_orders(session, limit=limit, offset=offset)
        return {
            "orders": [order.to_dict() for order in orders],
            "count": total,
            "returned": len(orders),
            "limit": limit,
            "offset": offset,
        }


@router.get("/inbox/orders/next")
def next_pending_order(request: Request) -> dict:
    """取「最旧的待生成订单」（FIFO 队首：未软删 + ai_status=pending）；操作员端「库驱动载单」轮询用。

    返回 ``{"order": {...}}`` 或 ``{"order": null}``（无待生成单）。生成完的单 ai_status→recognized
    自动掉出本查询，故轮询天然只拿到未生成单、生成后前进到下一条。**须声明在 /{order_id} 之前**，
    否则 ``next`` 会被当成 order_id。
    """
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        order = oldest_pending_order(session)
        return {"order": order.to_dict() if order is not None else None}


@router.get("/inbox/orders/{order_id}")
def get_order_status(order_id: str, request: Request) -> dict:
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        order = get_order(session, order_id)
        if order is None or order.deleted:  # 软删的单对外不可见 → 404（get_order 内部 getter 仍能看到软删行）
            raise HTTPException(status_code=404, detail=f"未找到订单 {order_id!r}")
        return order.to_dict()


@router.delete("/inbox/orders/{order_id}")
def delete_order_route(order_id: str, request: Request) -> dict:
    """删除单个订单（含级联 items/退款检查/标记任务）。订单不存在→404。"""
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        if not delete_order(session, order_id):
            raise HTTPException(status_code=404, detail=f"未找到订单 {order_id!r}")
        return {"deleted": order_id}


@router.post("/inbox/orders/purge")
def purge_orders_route(body: PurgeRequest, request: Request) -> dict:
    """手动清理：删除 received_at 早于 (now - older_than_days 天) 的订单，返回删除条数。"""
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        count = purge_orders_older_than(session, body.older_than_days)
        return {"deleted_count": count, "older_than_days": body.older_than_days}


@router.post("/inbox/orders/{order_id}/recheck", response_model=RecheckResponse)
def recheck_order(order_id: str, body: RecheckRequest, request: Request) -> RecheckResponse:
    """生产阶段退款拦截闸门：按订单「最后已知实时状态」+ 阶段判定放行/警告/阻断，并落审计。

    本服务自身不抓店小秘：实时状态由扩展重抓后推送。若调用方刚重抓到新状态，可在 body.refund_status
    传入，本接口会先刷新 Order.refund_status 再判定。缺省则用库里最后已知状态（计划 §7 / D4）。
    """
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        order = get_order(session, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail=f"未找到订单 {order_id!r}")
        if body.refund_status is not None:
            order.refund_status = body.refund_status  # 记录扩展刚重抓到的新状态
        status = order.refund_status
        action, reason = decide(status, body.stage)
        check = record_refund_check(
            session,
            order_id=order_id,
            stage=body.stage,
            queried_status=status,
            blocked_action=action,
            operator=body.operator,
        )
        return RecheckResponse(
            order_id=order_id,
            stage=body.stage,
            stage_label=STAGE_LABELS.get(body.stage, body.stage),
            queried_status=status,
            refund_status=status,  # 别名键：下游 Ezcad 按 refund_status 读，必须带（否则退款单误放行）
            items=[item.to_dict() for item in order.items],  # 其他商品提醒数据随判定一并返回
            ai_processed=has_active_mark_done(session, order_id),  # 已生成=有 AI已处理任务；EzCad 据此软警告未生成单
            blocked=action == "block",
            action=action,
            reason=reason,
            check_id=check.id,
            checked_at=check.checked_at.isoformat(),
        )


@router.get("/inbox/orders/{order_id}/refund-checks")
def list_refund_checks(order_id: str, request: Request) -> dict:
    """订单退款检查审计历史（按时间升序）。"""
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        order = get_order(session, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail=f"未找到订单 {order_id!r}")
        checks = recent_refund_checks(session, order_id)
        return {
            "order_id": order_id,
            "refund_status": order.refund_status,
            "checks": [check.to_dict() for check in checks],
            "count": len(checks),
        }


@router.post("/inbox/refund/scan")
def scan_refund_due(body: ScanRequest, request: Request) -> dict:
    """退款重抓调度：按规则 A/B/C + 半开区间算出该轮要重抓退款状态的订单清单。

    本服务不抓店小秘——返回的 due 清单供扩展逐单重抓后回 /recheck。规则 B 扫完推进 checkpoint 续跑。
    纯查询不改订单，同窗重复扫描无副作用。
    """
    factory = request.app.state.session_factory
    try:
        with session_scope(factory) as session:
            cp = get_checkpoint(session, body.scope)
            window = resolve_window(
                body.rule,
                now=utcnow(),
                checkpoint_cursor=cp.cursor if cp else None,
                window_seconds=body.window_seconds,
                start=body.start,
                end=body.end,
            )
            orders = select_due_orders(session, window, active_only=body.active_only)
            due = [
                {
                    "order_id": o.order_id,
                    "refund_status": o.refund_status,
                    "status": o.status,
                    "received_at": o.received_at.isoformat() if o.received_at else None,
                }
                for o in orders
            ]
            advanced = False
            if body.advance:
                advance_checkpoint(session, body.scope, window.end)
                advanced = True
            return {
                "rule": body.rule,
                "scope": body.scope,
                "window": window.to_dict(),
                "due": due,
                "count": len(due),
                "checkpoint_advanced": advanced,
            }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/inbox/run-mode")
def get_run_mode_route(request: Request) -> dict:
    """当前运行模式 + 生效的收件夹/批次目录（D3）。"""
    settings = request.app.state.settings
    mode = request.app.state.run_mode
    return {
        "mode": mode,
        "inbox_dir": str(effective_inbox_dir(settings, mode)),
        "batches_dir": str(effective_batches_dir(settings, mode)),
        "production_inbox_dir": str(settings.inbox_dir),
    }


@router.put("/inbox/run-mode")
def put_run_mode_route(body: RunModeUpdate, request: Request) -> dict:
    """切运行模式。test_reset（或 reset_sandbox=true）会清空 sandbox 旧文件（清旧）；生产目录绝不动。"""
    settings = request.app.state.settings
    if body.mode not in VALID_MODES:
        raise HTTPException(status_code=422, detail=f"未知运行模式：{body.mode!r}")
    request.app.state.run_mode = body.mode
    cleared = 0
    if body.mode == "test_reset" or body.reset_sandbox:
        cleared = clear_dir_files(settings.sandbox_inbox_dir) + clear_dir_files(settings.sandbox_batches_dir)
    return {
        "mode": body.mode,
        "inbox_dir": str(effective_inbox_dir(settings, body.mode)),
        "batches_dir": str(effective_batches_dir(settings, body.mode)),
        "sandbox_cleared_files": cleared,
    }


def _control_payload(control: ScrapeControl | None, settings) -> dict:
    """统一 control 响应：含服务端时钟算出的权威 ``authorized``（扩展据此 fail-closed）。"""
    if control is None:
        return {
            "scope": "order_scrape",
            "enabled": False,
            "interval_seconds": int(settings.refund_scan_interval),
            "scrape_from": None,
            "scrape_to": None,
            "task_id": None,
            "flower_instance_id": None,
            "lease_expires_at": None,
            "task_issued_at": None,
            "allowed_actions": None,
            "shop_scope": None,
            "retention_days": 0,
            "updated_at": None,
            "authorized": False,
        }
    data = control.to_dict()
    data["authorized"] = is_authorized(control)
    return data


@router.get("/inbox/scrape/control")
def get_scrape_control_route(request: Request) -> dict:
    """扩展读：当前是否被授权执行（authorized=enabled+租约未过期+有时间范围）、间隔、订单时间范围、任务信息。

    ⚠️ P0：扩展只信本响应里的 ``authorized``（服务端时钟算），不信任何本地缓存的 enabled/running。
    """
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        control = get_scrape_control(session)
        return _control_payload(control, settings)


@router.post("/inbox/scrape/task/start")
def scrape_task_start(body: ScrapeTaskStart, request: Request) -> dict:
    """flower「开始采集」：下发一个有租约的任务。scrape_from 必填（缺时间范围拒绝）。返回含 task_id + authorized。"""
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    scrape_from = parse_paid_at(body.scrape_from)
    if scrape_from is None:
        raise HTTPException(status_code=422, detail=f"scrape_from 时间无法解析：{body.scrape_from!r}")
    scrape_to = parse_paid_at(body.scrape_to) if body.scrape_to else None
    if body.scrape_to and scrape_to is None:
        raise HTTPException(status_code=422, detail=f"scrape_to 时间无法解析：{body.scrape_to!r}")
    actions = body.allowed_actions if body.allowed_actions is not None else [ACTION_SCRAPE, ACTION_MARK]
    lease = body.lease_seconds if body.lease_seconds is not None else settings.scrape_lease_seconds
    task_id = uuid.uuid4().hex
    with session_scope(factory) as session:
        control = start_scrape_task(
            session,
            task_id=task_id,
            flower_instance_id=body.flower_instance_id,
            scrape_from=scrape_from,
            scrape_to=scrape_to,
            interval_seconds=body.interval_seconds,
            lease_seconds=lease,
            allowed_actions=",".join(actions),
            shop_scope=",".join(body.shop_scope) if body.shop_scope else None,
            now=now_naive(),
        )
        data = _control_payload(control, settings)
    data["lease_seconds"] = lease
    return data


@router.post("/inbox/scrape/task/heartbeat")
def scrape_task_heartbeat(body: ScrapeTaskHeartbeat, request: Request) -> dict:
    """flower 心跳续约（须每 lease/3 左右调一次）。task_id 不符（任务被替换/已停）→ 409，旧实例据此停手。"""
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    lease = body.lease_seconds if body.lease_seconds is not None else settings.scrape_lease_seconds
    with session_scope(factory) as session:
        control, ok = heartbeat_scrape_task(
            session,
            task_id=body.task_id,
            flower_instance_id=body.flower_instance_id,
            lease_seconds=lease,
            now=now_naive(),
        )
        if not ok:
            raise HTTPException(
                status_code=409,
                detail="任务已失效（被替换/停止/实例不符），心跳被拒。请重新创建采集任务。",
            )
        data = _control_payload(control, settings)
    data["lease_seconds"] = lease
    return data


@router.post("/inbox/scrape/task/stop")
def scrape_task_stop(body: ScrapeTaskStop, request: Request) -> dict:
    """flower「停止采集」/ 关闭：释放任务租约 → 立即未授权。幂等；给定 task_id 与当前不符则不动（别人的任务）。"""
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        control = stop_scrape_task(session, task_id=body.task_id)
        return _control_payload(control, settings)


@router.put("/inbox/scrape/control")
def put_scrape_control_route(body: ScrapeControlUpdate, request: Request) -> dict:
    """flower 写「设置时间重新开始的开关」：开/关 + 间隔 + 从 T 重抓（部分更新）。"""
    factory = request.app.state.session_factory
    scrape_from = None
    set_from = body.clear_restart_from or body.restart_from is not None
    if body.restart_from is not None:
        scrape_from = parse_paid_at(body.restart_from)
        if scrape_from is None:
            raise HTTPException(status_code=422, detail=f"restart_from 时间无法解析：{body.restart_from!r}")
    with session_scope(factory) as session:
        control = upsert_scrape_control(
            session,
            enabled=body.enabled,
            interval_seconds=body.interval_seconds,
            scrape_from=scrape_from,
            set_scrape_from=set_from,
            retention_days=body.retention_days,
        )
        return control.to_dict()


@router.post("/inbox/scrape/diff")
def scrape_diff_route(body: ScrapeDiffRequest, request: Request) -> dict:
    """缓存/完整性核心：扩展上报列表清单 → 服务比对缓存(DB) → 回统一 worklist。

    new=新单 / incomplete=不全(缺 items[] 或 refund_status)需重抓覆盖 / refund_refresh=完整但退款状态过期。
    完整且新鲜的单不进清单（命中缓存、跳过=从该时间往后）。
    """
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    interval = body.recheck_interval if body.recheck_interval is not None else settings.refund_recheck_interval
    entries = [ManifestEntry(order_id=e.order_id, paid_at=parse_paid_at(e.paid_at)) for e in body.orders]
    with session_scope(factory) as session:
        control = get_scrape_control(session, body.scope)
        # ⚠️ P0：diff 是扩展自动抓取的规划入口，必须有有效任务授权（scrape）。否则拒绝（fail-closed）。
        if not action_allowed(control, ACTION_SCRAPE):
            raise HTTPException(
                status_code=403,
                detail="无有效任务授权（任务缺失/已过期/已停止），拒绝抓取规划。请在 Flower 创建采集任务。",
            )
        # 范围闸（翻页/抓取前的第一处校验）：只对**落在任务付款时间窗内**的清单条目算 worklist，
        # 时间窗外（历史订单）直接不进 worklist → 扩展不会去抓它们。
        in_scope = [e for e in entries if paid_in_time_window(control, e.paid_at)]
        dropped = len(entries) - len(in_scope)
        work = diff_manifest(session, in_scope, now=utcnow(), recheck_interval_seconds=interval)
        counts: dict[str, int] = {}
        for item in work:
            counts[item.reason] = counts.get(item.reason, 0) + 1
        return {
            "worklist": [item.to_dict() for item in work],
            "count": len(work),
            "counts": counts,
            "out_of_scope_dropped": dropped,
            "scrape_from": control.scrape_from.isoformat() if control and control.scrape_from else None,
            "scrape_to": control.scrape_to.isoformat() if control and control.scrape_to else None,
        }


@router.get("/inbox/refund/pending")
def refund_pending(
    request: Request,
    limit: int | None = Query(default=None, ge=1),
    recheck_interval: float | None = Query(default=None, ge=0),
    active_only: bool = Query(default=True),
) -> dict:
    """触发器（拉模式）：扩展拉取「现在该重抓退款状态」的在产订单，逐单重抓后回 /recheck。

    新鲜度判定：从没查过、或上次查距今超过 recheck_interval（缺省取服务配置）。回了 /recheck 即自动掉出。
    """
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    interval = recheck_interval if recheck_interval is not None else settings.refund_recheck_interval
    cap = limit if limit is not None else settings.refund_scan_limit
    with session_scope(factory) as session:
        due = due_for_recheck(
            session,
            now=utcnow(),
            interval_seconds=interval,
            limit=cap,
            active_only=active_only,
        )
        pending = [
            {
                "order_id": o.order_id,
                "refund_status": o.refund_status,
                "status": o.status,
                "source_url": o.source_url,
                "received_at": o.received_at.isoformat() if o.received_at else None,
            }
            for o in due
        ]
        return {
            "recheck_interval_seconds": interval,
            "pending": pending,
            "count": len(pending),
        }


@router.get("/inbox/refund/status")
def refund_scheduler_status(request: Request) -> dict:
    """退款重抓后台线程的最近一次 tick 快照（可观测性）。"""
    scheduler = request.app.state.refund_scheduler
    return scheduler.snapshot()


@router.post("/inbox/refund/tick")
def refund_scheduler_tick(request: Request) -> dict:
    """按需手动跑一轮后台调度（不依赖线程；便于运维/排障/测试）。"""
    scheduler = request.app.state.refund_scheduler
    ids = scheduler.tick_once()
    return {"ticked": True, "pending_count": len(ids), "pending_ids": ids}


@router.post("/inbox/refund/rescrape/request")
def rescrape_request(body: RescrapeRequestBody, request: Request) -> dict:
    """定向重抓入队（option B）：Ezcad 确认导入前请扩展去店小秘搜该单、重抓退款状态。

    本服务不抓店小秘——只记一条 pending 请求，扩展拉 /rescrape/queue 取走逐单重抓后回 /rescrape/result。
    Ezcad 轮询 /rescrape/status/{id} 拿 done/not_found/expired，再 /recheck 判定。
    """
    queue = request.app.state.rescrape_queue
    queue.request(body.order_id)
    return queue.status(body.order_id)


@router.get("/inbox/refund/rescrape/queue")
def rescrape_queue_pending(request: Request) -> dict:
    """扩展拉取：当前待定向重抓的 order_id 列表（pending 且未过期）。"""
    queue = request.app.state.rescrape_queue
    ids = queue.pending()
    return {"order_ids": ids, "count": len(ids)}


@router.post("/inbox/refund/rescrape/result")
def rescrape_result(body: RescrapeResultBody, request: Request) -> dict:
    """扩展回填定向重抓结果。found=True 时把实时状态刷进 Order.refund_status（供随后 /recheck 用）。"""
    queue = request.app.state.rescrape_queue
    if body.found and body.refund_status is not None:
        factory = request.app.state.session_factory
        with session_scope(factory) as session:
            order = get_order(session, body.order_id)
            if order is not None:
                order.refund_status = body.refund_status
    queue.resolve(body.order_id, found=body.found, refund_status=body.refund_status)
    return queue.status(body.order_id)


@router.get("/inbox/refund/rescrape/status/{order_id}")
def rescrape_status(order_id: str, request: Request) -> dict:
    """Ezcad 轮询：pending / done(带新鲜 refund_status) / not_found / expired / absent。"""
    queue = request.app.state.rescrape_queue
    return queue.status(order_id)


@router.post("/inbox/mark/request")
def mark_request(body: MarkRequestBody, request: Request) -> dict:
    """入队一条标记回写任务（flower 生成成功后调它入队 mark_done）。

    店小秘无 API → 只记一条 pending 任务，扩展拉 /inbox/mark/pending 取走，去店小秘模拟网页操作打标后回
    /inbox/mark/result。(order_id, action) 唯一，重入队=重置 pending（幂等）。订单不存在→404。
    """
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        if get_order(session, body.order_id) is None:
            raise HTTPException(status_code=404, detail=f"未找到订单 {body.order_id!r}")
        # 标准2 护栏（与 _ingest_one 一致）：已/将「AI已处理」的单不回打「AI未识别」。
        # 手动上传后扩展会调本端确保未识别打标任务（force 打标用）——这里同样拦住已处理单，避免把它打回未识别。
        if body.action == MARK_ACTION_UNRECOGNIZED and has_active_mark_done(session, body.order_id):
            return {"order_id": body.order_id, "action": body.action, "status": "skipped_done"}
        job = enqueue_mark_job(session, body.order_id, body.action)
        if body.action == MARK_ACTION_DONE:
            # mark_done 取代「待处理」：作废同单仍 pending 的 mark_unrecognized（避免已处理单被打回未识别 + 多余写）。
            supersede_mark_job(session, body.order_id, MARK_ACTION_UNRECOGNIZED)
            # AI 权威态：生成完 = 已识别。reconcile 据此把页面同步成「AI已处理」（且永不降级）。
            set_ai_status(session, body.order_id, AI_STATUS_RECOGNIZED)
        return job.to_dict()


@router.post("/inbox/ai/reconcile")
def ai_reconcile(body: AiReconcileBody, request: Request) -> dict:
    """AI 识别状态对账：扩展读到订单行 → 上报页面标记现状 → 服务以 DB ai_status 为唯一权威做
    **原子** get-or-create + 判定，返回 desired_tag（扩展据此把店小秘标记同步到位）。

    - 总开关关 / 未授权（mark）→ desired_tag=none（不创建、不改标签），fail-closed。
    - 判定逻辑见 repository.reconcile_ai_status：库里存在按权威态同步（recognized/locked 不降级）、
      不存在原子建 pending、新单/待识别单已带「AI已处理」→ conflict 进复核。
      本端点本身不写店小秘——只回 desired_tag，真正打标由扩展模拟网页操作（受其自身授权 gate）。
    """
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    no_op = {
        "desired_tag": "none",
        "ai_status": None,
        "conflict": False,
        "created": False,
        "authorized": False,
    }
    # 并发同单创建会让第二个请求在 flush 时 IntegrityError → 重试一次（届时订单已存在，走存在分支），
    # 使「原子 get-or-create」对调用方成立。任何其他 DB 异常 → fail-closed no-op（需求：查询失败不得改标签）。
    for attempt in range(2):
        try:
            with session_scope(factory) as session:
                control = get_scrape_control(session)
                if not settings.ai_reconcile_enabled or not action_allowed(control, ACTION_MARK):
                    return no_op  # 未授权 / 总开关关 → no-op（不创建桩单、不改标签）
                result = reconcile_ai_status(
                    session,
                    body.order_id,
                    page_ai_done=body.ai_done,
                    page_ai_unrecognized=body.ai_unrecognized,
                )
                result["authorized"] = True
                return result
        except IntegrityError:
            if attempt == 0:
                continue  # 并发建单竞争：重试，第二次订单已存在
            return no_op  # 仍冲突（极罕见）→ fail-closed
        except Exception:
            return no_op  # 任何 DB/查询失败 → fail-closed（端点级，不依赖扩展容错）
    return no_op


@router.get("/inbox/mark/pending")
def mark_pending(
    request: Request,
    limit: int | None = Query(default=None, ge=1),
) -> dict:
    """扩展拉取：待打标的任务（pending 且未超重试上限），按入队时间升序。含 source_url 便于定位。

    ⚠️ P0：这是扩展唯一的打标来源。无有效任务授权（mark）→ 返回空（扩展拿不到任务→零打标）。
    并按当前任务**订单范围**过滤——即便库里残留旧/范围外的 pending 任务（历史误标 backlog），也不下发、
    不会被写到店小秘（不做清理也不绕过，满足「旧队列不能绕过授权」）。
    """
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    cap = limit if limit is not None else settings.mark_pending_limit
    with session_scope(factory) as session:
        control = get_scrape_control(session)
        if not action_allowed(control, ACTION_MARK):
            return {"jobs": [], "count": 0, "authorized": False}
        jobs = pending_mark_jobs(session, limit=cap, max_attempts=settings.mark_max_attempts)
        items = [
            {"order_id": j.order_id, "action": j.action, "source_url": j.order.source_url if j.order else None}
            for j in jobs
            if j.order is not None
            and not j.order.deleted  # 软删的单不再下发打标
            and order_in_scope(control, paid_at=j.order.paid_at, shop=j.order.shop)
        ]
        return {"jobs": items, "count": len(items), "authorized": True}


@router.post("/inbox/mark/result")
def mark_result(body: MarkResultBody, request: Request) -> dict:
    """扩展回填打标结果：ok→done（掉出 pending）；失败→attempts+1，超上限→failed 否则下轮重试。"""
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        job = resolve_mark_job(
            session,
            body.order_id,
            body.action,
            ok=body.ok,
            detail=body.detail,
            max_attempts=settings.mark_max_attempts,
        )
        if job is None:
            raise HTTPException(
                status_code=404,
                detail=f"未找到标记任务 {body.order_id!r}/{body.action!r}（可能已被删单清掉）",
            )
        return job.to_dict()


@router.get("/inbox/mark/jobs")
def mark_jobs(
    request: Request,
    order_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1),
) -> dict:
    """审计/可观测：标记回写任务列表（可按订单过滤），按入队时间倒序。"""
    factory = request.app.state.session_factory
    with session_scope(factory) as session:
        jobs = recent_mark_jobs(session, order_id=order_id, limit=limit)
        return {"jobs": [j.to_dict() for j in jobs], "count": len(jobs)}


@router.post("/inbox/batch/export")
def export_batch(request: Request) -> dict:
    """把池中待生成订单导出成店小秘格式 xlsx，供操作员用 Flower 现有「导入」跑批量生成。"""
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    # D3：按运行模式选批次目录（test_reset → sandbox）。
    batches_dir = effective_batches_dir(settings, request.app.state.run_mode)
    path, count = export_pool_to_xlsx(factory, batches_dir)
    return {"path": str(path) if path is not None else None, "count": count}


@router.post("/inbox/batch/sync")
def sync_reports(request: Request) -> dict:
    """扫描 outputs/reports 的批量报告，把每单状态回写为 已完成 / 无法自动生成。"""
    watcher = request.app.state.report_watcher
    applied = watcher.scan_once()
    return {"applied": [path.name for path in applied], "count": len(applied)}
