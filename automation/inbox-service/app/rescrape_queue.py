from __future__ import annotations

# 定向重抓握手（option B）：Ezcad 确认导入前要某订单的**新鲜**退款状态，但本服务不抓店小秘。
# 流程：Ezcad 入队 order_id → flower 扩展（在店小秘搜索页）拉队列 → 按单号搜索+重抓 → 回填结果
#       → Ezcad 轮询拿到 done/未找到/过期，再 /recheck 判定。
#
# 这是**秒级临时态**（默认 60s 过期），不需要跨重启持久化（重启=请求作废，Ezcad 超时按 D4 从严阻断），
# 故用内存 + 锁，不建 DB 表 / 不加迁移。线程安全（后台线程不碰它，但端点可能并发）。

import threading
from dataclasses import dataclass
from datetime import datetime

from app.models import utcnow

STATE_PENDING = "pending"   # 已入队，等扩展重抓
STATE_DONE = "done"         # 扩展已重抓到该单（refund_status 已刷新）
STATE_NOT_FOUND = "not_found"  # 扩展在店小秘搜不到该单
STATE_EXPIRED = "expired"   # 超过 TTL 没被处理/取走（扩展没在跑 / 没开店小秘）
STATE_ABSENT = "absent"     # 从没入过队


@dataclass
class _Entry:
    state: str
    requested_at: datetime
    resolved_at: datetime | None = None
    refund_status: str | None = None  # 扩展回填的实时状态原文（仅 done 时有意义）


class RescrapeQueue:
    """订单定向重抓请求的内存队列（按 order_id 去重，TTL 过期自清）。"""

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._items: dict[str, _Entry] = {}

    def _stale_pending(self, entry: _Entry, now: datetime) -> bool:
        # pending 超过 TTL = 没人来取/处理（扩展没跑/没开店小秘）→ 视为 expired。
        return entry.state == STATE_PENDING and (now - entry.requested_at).total_seconds() > self._ttl

    def _too_old(self, entry: _Entry, now: datetime) -> bool:
        # 物理清理硬上限：从锚点起超过 2×TTL 才真正删除（让 status() 在 [TTL,2TTL] 内还能报 expired）。
        anchor = entry.resolved_at or entry.requested_at
        return (now - anchor).total_seconds() > self._ttl * 2

    def _sweep(self, now: datetime) -> None:
        dead = [oid for oid, e in self._items.items() if self._too_old(e, now)]
        for oid in dead:
            del self._items[oid]

    def request(self, order_id: str, *, now: datetime | None = None) -> _Entry:
        """入队（或重置）一条 pending 请求；同单重复请求=刷新计时、重回 pending。"""
        now = now or utcnow()
        with self._lock:
            self._sweep(now)
            entry = _Entry(state=STATE_PENDING, requested_at=now)
            self._items[order_id] = entry
            return entry

    def pending(self, *, now: datetime | None = None) -> list[str]:
        """扩展拉取：仍在 pending 且未过期的 order_id 列表（按入队时间升序）。"""
        now = now or utcnow()
        with self._lock:
            self._sweep(now)
            items = [
                (oid, e.requested_at)
                for oid, e in self._items.items()
                if e.state == STATE_PENDING and not self._stale_pending(e, now)
            ]
        items.sort(key=lambda x: x[1])
        return [oid for oid, _ in items]

    def resolve(
        self,
        order_id: str,
        *,
        found: bool,
        refund_status: str | None = None,
        now: datetime | None = None,
    ) -> _Entry:
        """扩展回填：found=True→done（带回 refund_status）；found=False→not_found。

        即便该单未在队列里（已过期被清/或服务重启），也记一条 resolved 条目，
        让 Ezcad 的轮询能拿到结果而不是一直 pending/absent。
        """
        now = now or utcnow()
        # 纵深防御：found=True 但没带回有效状态 → 降级 not_found，绝不让「拿不到状态」当 done 误放行
        # （与扩展 rescrape.ts「搜到单没抓到状态也算 not_found」一致；服务侧硬不变量：done ⟺ 有 refund_status）。
        status = (refund_status or "").strip()
        resolved_found = bool(found and status)
        with self._lock:
            self._sweep(now)
            entry = _Entry(
                state=STATE_DONE if resolved_found else STATE_NOT_FOUND,
                requested_at=self._items.get(order_id, _Entry(STATE_PENDING, now)).requested_at,
                resolved_at=now,
                refund_status=status if resolved_found else None,
            )
            self._items[order_id] = entry
            return entry

    def status(self, order_id: str, *, now: datetime | None = None) -> dict:
        """Ezcad 轮询：返回 {order_id, state, refund_status}。pending 超 TTL → expired。"""
        now = now or utcnow()
        with self._lock:
            self._sweep(now)
            entry = self._items.get(order_id)
            if entry is None:
                return {"order_id": order_id, "state": STATE_ABSENT, "refund_status": None}
            state = STATE_EXPIRED if self._stale_pending(entry, now) else entry.state
            return {"order_id": order_id, "state": state, "refund_status": entry.refund_status}
