from __future__ import annotations

# 退款重抓调度：按时间窗 + Checkpoint 算出「哪些在产订单该重抓退款状态」的待办清单。
#
# 职责边界（与全仓决策一致）：本服务**不抓**店小秘。scheduler 只决定 *范围*——
# 「这一轮该让扩展去重抓哪些订单的退款状态」，扫完把游标推进，断点续跑不漏不重。
# 实际重抓由扩展逐单完成、回 POST /inbox/orders/{id}/recheck（带新状态）。
#
# 三种规则（计划 §3.4）+ 半开区间 [start, end)（§3.6，避免边界订单被相邻窗口重复扫到）：
#   A 当前窗口     —— [now - window, now)
#   B 从上次成功续 —— [checkpoint.cursor, now)；无 checkpoint=从头（start=None）
#   C 固定区间     —— [start, end)（显式传入）
#
# 窗口对齐的是订单 received_at（到件时间）——对应「12:30 断、14:00 恢复，规则 B 不漏 12:30–14:00」。

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import STATUS_DONE, Checkpoint, Order, RefundCheck

RULE_A = "A"
RULE_B = "B"
RULE_C = "C"

DEFAULT_WINDOW_SECONDS = 3600  # 规则 A 默认窗口：近 1 小时
# 「已不需要重抓退款」的终态：已完成的订单不再纳入重抓清单（active_only 时排除）。
TERMINAL_STATUSES = frozenset({STATUS_DONE})


def as_utc(value: datetime) -> datetime:
    """统一成带时区的 UTC，避免 naive/aware 混比。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Window:
    start: datetime | None  # None = 不设下界（规则 B 首跑/从头）
    end: datetime

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat(),
        }


def resolve_window(
    rule: str,
    *,
    now: datetime,
    checkpoint_cursor: datetime | None = None,
    window_seconds: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Window:
    now = as_utc(now)
    if rule == RULE_A:
        seconds = window_seconds or DEFAULT_WINDOW_SECONDS
        return Window(start=now - timedelta(seconds=seconds), end=now)
    if rule == RULE_B:
        cur = as_utc(checkpoint_cursor) if checkpoint_cursor is not None else None
        return Window(start=cur, end=now)
    if rule == RULE_C:
        if start is None or end is None:
            raise ValueError("规则 C 需显式提供 start 与 end")
        return Window(start=as_utc(start), end=as_utc(end))
    raise ValueError(f"未知调度规则 {rule!r}（应为 A/B/C）")


def select_due_orders(session: Session, window: Window, *, active_only: bool = True) -> list[Order]:
    """选出 received_at ∈ [start, end) 的订单（半开），按到件时间升序。

    active_only=True 时排除终态（已完成）订单。纯查询、不改库 → 同窗重复扫描无副作用。
    """
    stmt = select(Order).where(Order.received_at < window.end, Order.deleted.is_(False))
    if window.start is not None:
        stmt = stmt.where(Order.received_at >= window.start)
    if active_only:
        stmt = stmt.where(Order.status.notin_(TERMINAL_STATUSES))
    return list(session.scalars(stmt.order_by(Order.received_at.asc())))


def due_for_recheck(
    session: Session,
    *,
    now: datetime,
    interval_seconds: float,
    limit: int | None = None,
    active_only: bool = True,
) -> list[Order]:
    """「新鲜度」模型：选出**该重抓退款状态**的在产订单 = 从没查过、或上次查距今超过 interval。

    供触发器端点（扩展拉取）和后台线程用。一旦扩展回了 /recheck（记一条 RefundCheck），
    该单在 interval 内就自动掉出清单——天然自清、不会反复刷同一单（限频，避免触发店小秘风控）。

    与 select_due_orders（按 received_at 时间窗 + Checkpoint）是两种用途：
      - due_for_recheck —— 「现在哪些单该刷新退款状态」（live 队列，按检查新鲜度）。
      - select_due_orders —— 「某到件时间窗内的单」（显式/回补，按 received_at + 断点续跑）。
    """
    now = as_utc(now)
    cutoff = now - timedelta(seconds=interval_seconds)
    recent = select(RefundCheck.order_id).where(RefundCheck.checked_at >= cutoff)
    stmt = select(Order).where(Order.order_id.not_in(recent), Order.deleted.is_(False))
    if active_only:
        stmt = stmt.where(Order.status.notin_(TERMINAL_STATUSES))
    stmt = stmt.order_by(Order.received_at.asc())
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


def get_checkpoint(session: Session, scope: str) -> Checkpoint | None:
    return session.get(Checkpoint, scope)


def advance_checkpoint(session: Session, scope: str, cursor: datetime) -> Checkpoint:
    """把 scope 的游标推进到 cursor（upsert）。规则 B 扫完调用以续跑。"""
    cursor = as_utc(cursor)
    cp = session.get(Checkpoint, scope)
    if cp is None:
        cp = Checkpoint(scope=scope, cursor=cursor)
        session.add(cp)
    else:
        cp.cursor = cursor
    session.flush()
    return cp
