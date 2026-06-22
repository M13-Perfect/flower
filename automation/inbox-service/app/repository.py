from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AI_STATUS_CONFLICT,
    AI_STATUS_NO_DOWNGRADE,
    AI_STATUS_PENDING,
    MARK_ACTION_DONE,
    MARK_STATUS_DONE,
    MARK_STATUS_FAILED,
    MARK_STATUS_PENDING,
    STATUS_RECEIVED,
    MarkJob,
    Order,
    OrderItem,
    RefundCheck,
    ScrapeControl,
    utcnow,
)
from app.scrape_planner import parse_paid_at
from app.schemas import OrderPayload


def get_order(session: Session, order_id: str) -> Order | None:
    return session.get(Order, order_id)


def _remove_inbox_file(inbox_path: str | None) -> None:
    """删除订单对应的收件夹 JSON 文件（软删时调）。路径为空 / 文件已不在 → 静默跳过（幂等、不抛）。

    只删 inbox_path 指向的那一个文件（订单入库成功时写下的原始路径）。已被操作员生成后移入 processed/ 的副本
    不在收件夹根、不被文件轮询 glob，无需处理；故此路径缺失（unlink missing_ok）属正常，不报错。
    文件占用/权限等 OSError 也吞掉：DB 软删已是事实，文件删不掉留给下轮 purge / 手动清理，绝不阻断软删本身。
    """
    if not inbox_path:
        return
    try:
        Path(inbox_path).unlink(missing_ok=True)
    except OSError:
        pass


def delete_order(session: Session, order_id: str) -> bool:
    """软删单个订单：标记 deleted（不真删 DB 行、不删子表），并物理删除其收件夹 JSON 文件。
    订单不存在 / 已是软删态 → 返回 False（对外 404、幂等）。

    删文件而非保留：旧文件轮询（ui_app._poll_inbox_once）只 glob 收件夹文件、不查 DB deleted 标记，留着会把
    已软删的单又当成在册单捞进操作员端，导致收件夹与 DB 对不上。误删可经「重新导入」（扩展重抓 → upsert_order
    复活成 deleted=False）找回——复活时会重写收件夹文件，故删文件不破坏可恢复性（DB 行始终在、只是标 deleted）。
    """
    order = session.get(Order, order_id)
    if order is None or order.deleted:
        return False
    order.deleted = True
    order.deleted_at = utcnow()
    _remove_inbox_file(order.inbox_path)
    return True


def purge_orders_older_than(session: Session, days: int, *, now: datetime | None = None) -> int:
    """软删 received_at 早于 (now - days 天) 的订单：标记 deleted（不删 DB 行、不删子表），并物理删除其收件夹 JSON 文件。
    days<=0 视为不删，返回 0。返回**本次新软删**的订单条数（已是软删态的不重复计、不再触碰）。

    先 SELECT 出待删行的 inbox_path（只取这一列、不整行入内存），再批量 UPDATE 标 deleted，最后逐个删文件。
    与 delete_order 同因：留着旧文件会被文件轮询误捞成在册单。误删可经「重新导入」找回（复活时重写收件夹文件）。
    调用方负责确认 days>0（后台清理只在 retention_days>0 时调用）。
    """
    if days <= 0:
        return 0
    cutoff = (now or utcnow()) - timedelta(days=days)
    # 先抓路径（仍是 deleted=False 的待删行），再标删；顺序不能反，否则 where 条件已变、抓不到。
    paths = session.execute(
        select(Order.inbox_path).where(Order.received_at < cutoff, Order.deleted.is_(False))
    ).scalars().all()
    result = session.execute(
        update(Order)
        .where(Order.received_at < cutoff, Order.deleted.is_(False))
        .values(deleted=True, deleted_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    for path in paths:
        _remove_inbox_file(path)
    return int(result.rowcount or 0)


def upsert_order(session: Session, payload: OrderPayload, raw_json: str) -> tuple[Order, bool, bool, bool]:
    """按 order_id UPSERT；返回 (order, dedup, content_same, created)。

    - ``dedup``：这单之前已收过（幂等重发；含软删行——语义不变，勿改，见 tests/test_dedup.py）。
    - ``content_same``：新报文与库里**逐字节一致**（``raw_json`` 相同）→ 本次不覆盖任何字段/行项目，
      调用方据此跳过重写收件夹文件、不重触发下游（见 routes.ingest_order）。
    - ``created``：本次上传**新建了订单行，或复活了软删行**（=「数据库原来没有该（活跃）订单」）。
      手动「→Flower」条件打标据此判 CREATED_NEW（dedup 含软删无法区分复活，故单列此位，2026-06-22）。

    两条「不必覆盖」的检测（2026-06-20）：
    1. 内容逐字节一致 → 整单 no-op，只刷新 ``updated_at`` 保「新鲜」（自动抓循环靠它判 refund_refresh，
       否则同一单每轮被重复重推，见 scrape_planner）；refund_status / items / 生命周期状态全保留。
    2. 内容有变但 ``refund_status`` 为空（列表页重抓常无此列）→ **不拿 None 抹掉**库里已知「已退款」。

    行项目（items）整树替换：以最新一份报文为准，避免旧行项目残留。
    """
    existing = session.get(Order, payload.order_id)
    dedup = existing is not None
    if existing is not None and existing.raw_json == raw_json and not existing.deleted:
        # 检测 1：内容一致且**未被软删** → 不必覆盖。仅刷新 updated_at（保「新鲜」、防每轮重推），其余一概不动。
        # 被软删的单即使内容逐字节一致也不在此返回，要走下面的复活 + 重写路径（content_same=False）。
        existing.updated_at = utcnow()
        return existing, dedup, True, False  # no-op：既非新建也非复活 → created=False
    if existing is None:
        # 新单：AI 权威态默认「待识别」（与列 default 一致，显式写避免 flush 前的 None 窗口）。
        # 注意只在**新建**时置，已存在单的 ai_status 一概不动（防 recognized/conflict 被重发抹回 pending）。
        order = Order(order_id=payload.order_id, status=STATUS_RECEIVED, ai_status=AI_STATUS_PENDING)
        session.add(order)
        created = True  # 全新行
    else:
        order = existing
        # 复活：被软删的单又被导入（扩展重抓到同一单）→ 清掉删除标记，重新纳入正常流程。
        # 这是误删找回的唯一途径（UI 不做回收站）；配合上面的条件，复活时会重写收件夹文件、重入队打标。
        # 复活按「新单」对待（created=True）：手动条件打标视复活单为 CREATED_NEW（用户确认 2026-06-22）。
        created = bool(order.deleted)
        if order.deleted:
            order.deleted = False
            order.deleted_at = None
    order.remark = payload.remark
    order.shop = payload.shop
    order.spec = payload.spec
    order.source_url = payload.source_url
    # 检测 2：refund_status 仅在新报文带非空值时才覆盖；为空则保留库里最后已知，避免误清已退款状态。
    if payload.refund_status is not None:
        order.refund_status = payload.refund_status
    order.paid_at = parse_paid_at(payload.extras.get("paid_at"))  # 付款时间走 extras 兜底
    order.raw_json = raw_json

    order.items.clear()  # delete-orphan 清掉旧行项目
    for item in payload.items:
        order.items.append(
            OrderItem(
                line_index=item.line_index,
                product_sku=item.product_sku,
                is_target_box=item.is_target_box,
                quantity=item.quantity,
                personalization_raw=item.personalization_raw,
                extras_json=json.dumps(item.extras, ensure_ascii=False) if item.extras else None,
            )
        )
    return order, dedup, False, created


def recent_orders(session: Session, limit: int = 100, offset: int = 0) -> list[Order]:
    """按 received_at 倒序取一页订单。eager-load items + mark_jobs 消 N+1
    （订单表行视图要用它们算件数/标签；原来逐订单触发关系加载，100 条≈200+ 次 SQL）。"""
    stmt = (
        select(Order)
        .where(Order.deleted.is_(False))  # 软删的单不进列表（订单表只看在册单）
        .options(selectinload(Order.items), selectinload(Order.mark_jobs))
        .order_by(Order.received_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(stmt))


def oldest_pending_order(session: Session) -> Order | None:
    """取「最旧的待生成订单」（FIFO 队首）：未软删 + ``ai_status=pending``，按 received_at 升序第一条。

    操作员端「库驱动载单」轮询用：生成完的单 ai_status→recognized（见 routes mark_done）自动掉出本查询，
    队首即前进到下一条**未生成**单（recognized/conflict/locked 都不算待生成、不会被取到）。
    eager-load items + mark_jobs（载单要拼备注、行视图免 N+1）。无待生成单 → None。
    """
    stmt = (
        select(Order)
        .where(Order.deleted.is_(False), Order.ai_status == AI_STATUS_PENDING)
        .options(selectinload(Order.items), selectinload(Order.mark_jobs))
        .order_by(Order.received_at.asc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def count_orders(session: Session) -> int:
    """未删订单总数（订单表「共 N 单」用真实总数，不再等于当前页条数；软删的不计入）。"""
    return int(
        session.scalar(select(func.count()).select_from(Order).where(Order.deleted.is_(False))) or 0
    )


def record_refund_check(
    session: Session,
    order_id: str,
    stage: str,
    queried_status: str | None,
    blocked_action: str,
    operator: str | None = None,
) -> RefundCheck:
    """追加一条退款检查审计（append-only）。调用前需确认订单存在。"""
    check = RefundCheck(
        order_id=order_id,
        stage=stage,
        queried_status=queried_status,
        blocked_action=blocked_action,
        operator=operator,
    )
    session.add(check)
    session.flush()  # 取到自增 id / checked_at，便于即时返回
    return check


def recent_refund_checks(session: Session, order_id: str, limit: int = 50) -> list[RefundCheck]:
    stmt = (
        select(RefundCheck)
        .where(RefundCheck.order_id == order_id)
        .order_by(RefundCheck.checked_at.asc(), RefundCheck.id.asc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def enqueue_mark_job(session: Session, order_id: str, action: str) -> MarkJob:
    """入队/重置一条标记回写任务。(order_id, action) 唯一：已存在则重置为 pending、attempts 归零（幂等重入队）。

    调用方需先确认订单存在（order_id 有 FK）；服务用 SQLite 默认不强制 FK，故路由层显式 404 兜底。
    """
    job = session.scalars(
        select(MarkJob).where(MarkJob.order_id == order_id, MarkJob.action == action)
    ).first()
    if job is None:
        job = MarkJob(order_id=order_id, action=action, status=MARK_STATUS_PENDING)
        session.add(job)
    else:
        job.status = MARK_STATUS_PENDING
        job.attempts = 0
        job.last_error = None
    session.flush()
    return job


def pending_mark_jobs(session: Session, limit: int, max_attempts: int) -> list[MarkJob]:
    """扩展拉取：pending 且 attempts<max 的任务，按入队时间升序。"""
    stmt = (
        select(MarkJob)
        .where(MarkJob.status == MARK_STATUS_PENDING, MarkJob.attempts < max_attempts)
        .order_by(MarkJob.created_at.asc(), MarkJob.id.asc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def resolve_mark_job(
    session: Session,
    order_id: str,
    action: str,
    *,
    ok: bool,
    detail: str | None,
    max_attempts: int,
) -> MarkJob | None:
    """扩展回填：ok→done；否则 attempts+1，超 max→failed 否则留 pending。任务不存在→None。"""
    job = session.scalars(
        select(MarkJob).where(MarkJob.order_id == order_id, MarkJob.action == action)
    ).first()
    if job is None:
        return None
    if ok:
        job.status = MARK_STATUS_DONE
        job.last_error = None
    else:
        job.attempts += 1
        job.last_error = detail
        job.status = MARK_STATUS_FAILED if job.attempts >= max_attempts else MARK_STATUS_PENDING
    session.flush()
    return job


def has_active_mark_done(session: Session, order_id: str) -> bool:
    """该单是否已有「AI已处理」任务（pending 或 done）。用于标准2：已/将已处理的单不再回打 AI未识别。"""
    job = session.scalars(
        select(MarkJob).where(MarkJob.order_id == order_id, MarkJob.action == MARK_ACTION_DONE)
    ).first()
    return job is not None and job.status in (MARK_STATUS_PENDING, MARK_STATUS_DONE)


def supersede_mark_job(session: Session, order_id: str, action: str) -> MarkJob | None:
    """作废同单某动作仍 pending 的任务（被互斥的新动作取代）：置 done 使其掉出 pending。

    用于 mark_done 入队时取消尚未执行的 mark_unrecognized——避免「已处理订单又被打回 AI未识别」的回退窗口
    + 省掉一次「先打 AI未识别 再立刻清」的多余弹窗写（封号风险）。仅动 pending 的（failed/done 不碰）。
    """
    job = session.scalars(
        select(MarkJob).where(MarkJob.order_id == order_id, MarkJob.action == action)
    ).first()
    if job is None or job.status != MARK_STATUS_PENDING:
        return None
    job.status = MARK_STATUS_DONE
    job.last_error = None
    session.flush()
    return job


def recent_mark_jobs(
    session: Session, order_id: str | None = None, limit: int = 100
) -> list[MarkJob]:
    """审计/可观测：按入队时间倒序列任务（可按订单过滤）。"""
    stmt = select(MarkJob)
    if order_id is not None:
        stmt = stmt.where(MarkJob.order_id == order_id)
    stmt = stmt.order_by(MarkJob.created_at.desc(), MarkJob.id.desc()).limit(limit)
    return list(session.scalars(stmt))


def set_ai_status(session: Session, order_id: str, ai_status: str) -> Order | None:
    """直接置某单 AI 权威态（**显式覆盖原语**，不做降级守卫）。订单不存在→None（no-op）。

    ⚠️ 防自动降级是**调用方**的责任：自动流程绝不能用本函数把 recognized/locked 改回 pending/conflict。
    当前自动调用仅 mark_request 的「生成完→recognized」（升级，安全）。本函数故意不加硬守卫，
    因为人工裁决解冲突时可能需要合法地把 conflict 改成 recognized 或 pending（降级），加守卫会误伤。
    """
    order = session.get(Order, order_id)
    if order is None:
        return None
    order.ai_status = ai_status
    session.flush()
    return order


def _reconcile_result(ai_status: str, desired_tag: str, *, conflict: bool, created: bool) -> dict:
    """对账返回：desired_tag ∈ {pending, recognized, none}（扩展据此同步页面标记；none=不动标签）。"""
    return {
        "ai_status": ai_status,
        "desired_tag": desired_tag,
        "conflict": conflict,
        "created": created,
    }


def reconcile_ai_status(
    session: Session,
    order_id: str,
    *,
    page_ai_done: bool,
    page_ai_unrecognized: bool,
) -> dict:
    """AI 识别状态对账（**原子** get-or-create + 判定）。扩展读到订单行 → 上报页面是否带
    「AI已处理」(page_ai_done) / 「AI未识别」(page_ai_unrecognized) → 本函数以 DB ai_status 为唯一权威，
    返回扩展应把页面同步成的目标标记 desired_tag。判定忠实需求：

    订单已存在：
      - recognized / locked → desired=recognized（同步为「AI已处理」，**绝不降级回未识别**）。
      - pending：页面已带「AI已处理」(page_ai_done) = 数据冲突（边缘 A：库 pending 却页面已处理 / 脏数据 B）
                 → 置 conflict、desired=none（冻结，不动标签，等人工裁决）；
                 否则 desired=pending（确保唯一「AI未识别」）。
      - conflict → desired=none（复核中，扩展不动标签）。
    订单不存在（含软删，原子创建/复活）：
      - 页面已带「AI已处理」→ 建 conflict、desired=none（数据冲突进复核，**不直接改为未识别**）。
      - 否则 → 建 pending、desired=pending（确保唯一「AI未识别」）。

    软删的单：**不自动复活**（尊重操作员删除/保留期清理）→ desired=none、不动标签、不创建；
    要恢复请重新上传（走 upsert_order 复活并补全数据）。这样也避免「空桩单被被动复活成空数据」。
    返回 {ai_status, desired_tag, conflict, created}。page_ai_unrecognized 目前不参与判定
    （仅作审计/未来扩展），保留入参以贴合「上报页面现状」契约。

    并发：新单创建是 check-then-insert；同一 order_id 的并发 reconcile 可能竞争 INSERT。
    flush 时第二个请求会 IntegrityError——由路由层 ai_reconcile 捕获并重试（重试时订单已存在，走存在分支），
    使「原子 get-or-create」语义对调用方成立。
    """
    order = session.get(Order, order_id)
    if order is not None and order.deleted:
        # 软删单 → 冻结：不复活、不动标签（desired=none）。恢复需重新上传走 upsert_order。
        return _reconcile_result(order.ai_status or AI_STATUS_PENDING, "none", conflict=False, created=False)
    if order is not None:
        # 存在（未删）→ 以 DB 权威态同步页面标记。
        status = order.ai_status or AI_STATUS_PENDING  # 历史空值兜底当 pending
        if status in AI_STATUS_NO_DOWNGRADE:
            return _reconcile_result(status, "recognized", conflict=False, created=False)
        if status == AI_STATUS_CONFLICT:
            return _reconcile_result(status, "none", conflict=True, created=False)
        # pending：页面已是「AI已处理」→ 冲突进复核（不自动降级）；否则确保「AI未识别」。
        if page_ai_done:
            order.ai_status = AI_STATUS_CONFLICT
            session.flush()
            return _reconcile_result(AI_STATUS_CONFLICT, "none", conflict=True, created=False)
        return _reconcile_result(AI_STATUS_PENDING, "pending", conflict=False, created=False)
    # 不存在 → 原子创建桩订单（仅 order_id + 权威态；remark/raw_json 非空约束给空值占位，真实上传时 upsert 补全）。
    order = Order(order_id=order_id, status=STATUS_RECEIVED, remark="", raw_json="{}")
    session.add(order)
    if page_ai_done:
        # 新单却已带「AI已处理」→ 数据冲突进复核，不直接改为未识别。
        order.ai_status = AI_STATUS_CONFLICT
        session.flush()
        return _reconcile_result(AI_STATUS_CONFLICT, "none", conflict=True, created=True)
    order.ai_status = AI_STATUS_PENDING
    session.flush()
    return _reconcile_result(AI_STATUS_PENDING, "pending", conflict=False, created=True)


def get_scrape_control(session: Session, scope: str = "order_scrape") -> ScrapeControl | None:
    return session.get(ScrapeControl, scope)


def upsert_scrape_control(
    session: Session,
    scope: str = "order_scrape",
    *,
    enabled: bool | None = None,
    interval_seconds: int | None = None,
    scrape_from: datetime | None = None,
    set_scrape_from: bool = False,
    retention_days: int | None = None,
) -> ScrapeControl:
    """flower 写自动抓取配置：部分更新（None=该字段不动）。

    ⚠️ 注意（P0 2026-06-22）：经此把 enabled 设 true **不再等于授权**——授权要靠任务租约（见
    start_scrape_task / app.authorization）。本函数保留给「间隔 / 保留天数 / 重抓起点」这类纯配置更新。
    scrape_from 需用 set_scrape_from=True 显式开启更新（以便区分「不动」与「清空成 None」）。
    """
    control = session.get(ScrapeControl, scope)
    if control is None:
        control = ScrapeControl(scope=scope)
        session.add(control)
    if enabled is not None:
        control.enabled = enabled
    if interval_seconds is not None:
        control.interval_seconds = interval_seconds
    if set_scrape_from:
        control.scrape_from = scrape_from
    if retention_days is not None:
        control.retention_days = max(0, retention_days)
    session.flush()
    return control


def start_scrape_task(
    session: Session,
    *,
    scope: str = "order_scrape",
    task_id: str,
    flower_instance_id: str,
    scrape_from: datetime,
    scrape_to: datetime | None,
    interval_seconds: int | None,
    lease_seconds: float,
    allowed_actions: str,
    shop_scope: str | None,
    now: datetime,
) -> ScrapeControl:
    """flower「开始采集」：创建/覆盖当前任务 + 起一段租约。enabled=true，授权随租约有效而成立。

    覆盖式（同一 scope 只有一个 active 任务）：新任务直接替换旧任务字段。``now`` 为 naive UTC，
    ``lease_expires_at = now + lease_seconds``。``scrape_from`` 必填（订单时间范围下界）。
    """
    control = session.get(ScrapeControl, scope)
    if control is None:
        control = ScrapeControl(scope=scope)
        session.add(control)
    control.enabled = True
    control.task_id = task_id
    control.flower_instance_id = flower_instance_id
    control.task_issued_at = now
    control.lease_expires_at = now + timedelta(seconds=lease_seconds)
    control.scrape_from = scrape_from
    control.scrape_to = scrape_to
    control.allowed_actions = allowed_actions
    control.shop_scope = shop_scope
    if interval_seconds is not None:
        control.interval_seconds = interval_seconds
    session.flush()
    return control


def heartbeat_scrape_task(
    session: Session,
    *,
    scope: str = "order_scrape",
    task_id: str,
    flower_instance_id: str,
    lease_seconds: float,
    now: datetime,
) -> tuple[ScrapeControl | None, bool]:
    """flower 心跳续约：仅当 task_id 与当前任务匹配才延长租约。返回 (control, ok)。

    不匹配（任务已被替换 / 已停止 / 实例不符）→ ok=False，调用方据此回 409，让旧实例停手（防多 flower 抢同一任务）。
    """
    control = session.get(ScrapeControl, scope)
    if control is None or not control.task_id:
        return control, False
    if control.task_id != task_id or (
        control.flower_instance_id and control.flower_instance_id != flower_instance_id
    ):
        return control, False
    control.lease_expires_at = now + timedelta(seconds=lease_seconds)
    session.flush()
    return control, True


def stop_scrape_task(
    session: Session,
    *,
    scope: str = "order_scrape",
    task_id: str | None = None,
) -> ScrapeControl | None:
    """flower「停止采集」/ 关闭：释放当前任务租约 → enabled=false、清空任务字段 → 立即未授权。

    幂等。若传了 task_id 且与当前不符 → 不动（避免旧实例误停新实例刚建的任务）。无任务 → 直接返回。
    """
    control = session.get(ScrapeControl, scope)
    if control is None:
        return None
    if task_id is not None and control.task_id and control.task_id != task_id:
        return control  # 别人的任务，不动
    control.enabled = False
    control.task_id = None
    control.flower_instance_id = None
    control.lease_expires_at = None
    control.task_issued_at = None
    control.scrape_to = None
    control.allowed_actions = None
    control.shop_scope = None
    session.flush()
    return control
