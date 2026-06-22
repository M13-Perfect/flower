from __future__ import annotations

# 自动抓取的「缓存 + 完整性」核心：缓存=DB，完整性校验=manifest-diff。
#
# 交互（已与用户敲定「扩展上报清单、服务算差异」）：
#   扩展定时抓店小秘列表 → 把 (order_id + 付款时间) 轻清单 POST /inbox/scrape/diff
#   → 服务比对 DB（缓存），回「该重抓哪些 + 为什么」的**统一 worklist**：
#       new            —— DB 里没有 → 新单，全量抓。
#       incomplete     —— DB 里有但不全（缺 items[] 或 refund_status）→ 重抓覆盖。
#       refund_refresh —— 完整但退款状态过期 → 刷新（与退款重抓统一进这一份清单）。
#       （完整且新鲜的单不进清单 = 命中缓存、跳过 = “从该时间往后”。）
#   扩展按 worklist 逐单全量抓 → POST /inbox/orders（付款时间随 extras.paid_at）。
#
# 「完整」判据（用户定）：items[] 非空 且 refund_status 有值。

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Order, RefundCheck

REASON_NEW = "new"
REASON_INCOMPLETE = "incomplete"
REASON_REFUND_REFRESH = "refund_refresh"

# 容错解析的付款时间格式（店小秘列表页形如 "2026-06-19 02:25"）。
_PAID_AT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M")


def parse_paid_at(value: object) -> datetime | None:
    """把 extras.paid_at 解析成 datetime（店小秘墙钟、不带时区）。解析不了返回 None，不抛。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)  # ISO 优先
    except ValueError:
        pass
    for fmt in _PAID_AT_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def is_order_complete(order: Order) -> bool:
    """完整 = 抓到了行项目 且 有退款状态（用户定的判据）。"""
    return bool(order.items) and bool(order.refund_status)


def _ingested_within(order: Order, cutoff_naive: datetime) -> bool:
    """订单是否在 cutoff 之后被（重）入库过。自动循环重推一单 = 刚重抓过它的退款状态，
    故近期 updated_at 即视为「状态新鲜」，不必立刻再 refund_refresh（否则每轮全量重推）。"""
    ts = order.updated_at
    if ts is None:
        return False
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts >= cutoff_naive


@dataclass(frozen=True)
class WorkItem:
    order_id: str
    reason: str  # new / incomplete / refund_refresh
    paid_at: datetime | None

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "reason": self.reason,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
        }


@dataclass(frozen=True)
class ManifestEntry:
    order_id: str
    paid_at: datetime | None


def diff_manifest(
    session: Session,
    entries: list[ManifestEntry],
    *,
    now: datetime,
    recheck_interval_seconds: float,
) -> list[WorkItem]:
    """对扩展上报的清单逐条比对缓存（DB），产出统一 worklist。完整且新鲜的单不进清单（命中缓存）。

    「新鲜」= 近 recheck_interval 内有过退款检查(RefundCheck) **或** 被重新入库(updated_at)；
    后者保证自动循环重推一单后、interval 内不再反复 refund_refresh 重推（真机发现①的修复）。
    """
    now_aware = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    cutoff = now_aware - timedelta(seconds=recheck_interval_seconds)  # aware，给 SQL 比较
    cutoff_naive = cutoff.replace(tzinfo=None)  # naive，给 updated_at（SQLite 读回 naive）比较
    ids = [entry.order_id for entry in entries]
    # 批量取订单（含 items 判完整）：一次 IN 查询代替逐条 session.get（洪峰/翻页后清单可达数百，省 N 次往返）。
    orders_by_id: dict[str, Order] = {}
    if ids:
        rows = session.scalars(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.order_id.in_(ids), Order.deleted.is_(False))  # 软删单当「不存在」→ 判 REASON_NEW → 扩展重抓触发复活
        )
        orders_by_id = {order.order_id: order for order in rows}
    # 批量取「近 interval 内有过退款检查」的 order_id 集：一次查代替逐条 count（同 SQL 比较，避免 naive/aware 混比）。
    complete_ids = [oid for oid, order in orders_by_id.items() if is_order_complete(order)]
    recent_checked: set[str] = set()
    if complete_ids:
        recent_checked = set(
            session.scalars(
                select(RefundCheck.order_id)
                .where(RefundCheck.checked_at >= cutoff, RefundCheck.order_id.in_(complete_ids))
                .distinct()
            )
        )
    worklist: list[WorkItem] = []
    for entry in entries:
        order = orders_by_id.get(entry.order_id)
        if order is None:
            worklist.append(WorkItem(entry.order_id, REASON_NEW, entry.paid_at))
            continue
        paid_at = entry.paid_at or order.paid_at
        if not is_order_complete(order):
            worklist.append(WorkItem(entry.order_id, REASON_INCOMPLETE, paid_at))
        elif not (entry.order_id in recent_checked or _ingested_within(order, cutoff_naive)):
            worklist.append(WorkItem(entry.order_id, REASON_REFUND_REFRESH, paid_at))
        # else: 完整 + 近期已检查/已重抓入库 → 命中缓存，跳过。
    return worklist


# ── 抓取控制（flower 开关）helpers ──────────────────────────────────


def as_naive_paid(value: datetime | None) -> datetime | None:
    """scrape_from 与付款时间同域（店小秘墙钟）；带时区的统一去掉 tz，避免与 paid_at 混比。"""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value
