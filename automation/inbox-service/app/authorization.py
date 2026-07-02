from __future__ import annotations

# 任务授权（统一守卫，P0 2026-06-22）。
#
# 背景：原来扩展是否执行只看 ScrapeControl.enabled 一个布尔，而它存在独立常驻的 inbox-service DB——
# flower 关掉后仍永久 true，扩展每次开店小秘页就误以为已授权，自动抓取+打标历史订单（副作用失控）。
#
# 修复：enabled 不再等于授权。授权 = 存在**未过期的任务租约**（flower 持续心跳续约）。这里是
# 「当前是否有有效授权 / 某订单是否在授权范围内」的唯一判定处——服务端各副作用端点都调它，扩展也读
# GET /scrape/control 返回的 authorized（由本模块算）。fail-closed：任何字段缺失/过期/无法判定 → 拒绝。

from datetime import datetime, timezone

from app.models import ScrapeControl

ACTION_SCRAPE = "scrape"
ACTION_MARK = "mark"


def now_naive() -> datetime:
    """当前 UTC（naive）。租约/付款时间都按 naive UTC 存比，避免与 SQLite 读回的 naive 值混 tz。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def lease_valid(control: ScrapeControl | None, now: datetime | None = None) -> bool:
    """是否存在**未过期**的任务租约（有 task_id 且 lease_expires_at 在未来）。

    这是服务端「现在是否有 flower 在管」的核心判据——副作用端点据它 fail-closed。
    不看 enabled / scrape_from（那些归 is_authorized）；租约本身在不在、过没过期是第一道闸。
    """
    if control is None:
        return False
    if not control.task_id:
        return False
    expires = _as_naive(control.lease_expires_at)
    if expires is None:
        return False
    return (now or now_naive()) < expires


def is_authorized(control: ScrapeControl | None, now: datetime | None = None) -> bool:
    """扩展是否被授权执行自动抓取/打标。

    = enabled 且 租约有效 且 scrape_from 有值（订单时间范围必填——规范：缺时间范围必须拒绝）。
    """
    if control is None or not control.enabled:
        return False
    if not lease_valid(control, now):
        return False
    if control.scrape_from is None:  # 没有订单时间范围 → 拒绝（绝不默认全量）
        return False
    return True


def allowed_action_set(control: ScrapeControl | None) -> set[str]:
    """任务允许的操作集合。无任务/未配置 → 空集（什么都不允许，fail-closed）。"""
    if control is None or not control.allowed_actions:
        return set()
    return {a.strip() for a in control.allowed_actions.split(",") if a.strip()}


def action_allowed(control: ScrapeControl | None, action: str, now: datetime | None = None) -> bool:
    """某具体操作（scrape/mark）当前是否被授权：先要整体授权，再看该操作在 allowed_actions 里。"""
    if not is_authorized(control, now):
        return False
    return action in allowed_action_set(control)


def shop_scope_set(control: ScrapeControl | None) -> set[str] | None:
    """允许的店铺集合；None=不限店铺。空白 → None。"""
    if control is None or not control.shop_scope:
        return None
    shops = {s.strip() for s in control.shop_scope.split(",") if s.strip()}
    return shops or None


def paid_in_time_window(control: ScrapeControl | None, paid_at: datetime | None) -> bool:
    """仅按**付款时间窗** [scrape_from, scrape_to] 判定（不看店铺）。

    供 /scrape/diff 规划阶段用（清单只有 order_id+付款时间、没有店铺）；店铺过滤留到入库 order_in_scope。
    fail-closed：未授权 / paid_at 缺失 / 不在窗内 → False。
    """
    if not is_authorized(control):
        return False
    assert control is not None
    paid = _as_naive(paid_at)
    if paid is None:
        return False
    start = _as_naive(control.scrape_from)
    if start is not None and paid < start:
        return False
    end = _as_naive(control.scrape_to)
    if end is not None and paid > end:
        return False
    return True


def order_in_scope(
    control: ScrapeControl | None,
    *,
    paid_at: datetime | None,
    shop: str | None = None,
) -> bool:
    """订单是否落在当前任务的范围内（付款时间窗 [scrape_from, scrape_to] + 店铺）。

    fail-closed：
    - 未授权 → False。
    - paid_at 缺失（无法按时间判定）→ False（绝不把无付款时间的单当「在范围内」，防历史/未付款单混入）。
    - paid_at < scrape_from 或 > scrape_to → False。
    - shop_scope 非空且订单店铺不在其中 → False。
    """
    if not is_authorized(control):
        return False
    assert control is not None  # is_authorized 已保证
    paid = _as_naive(paid_at)
    if paid is None:
        return False
    start = _as_naive(control.scrape_from)
    if start is not None and paid < start:
        return False
    end = _as_naive(control.scrape_to)
    if end is not None and paid > end:
        return False
    shops = shop_scope_set(control)
    if shops is not None and (shop or "") not in shops:
        return False
    return True
