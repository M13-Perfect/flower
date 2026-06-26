from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from app.db import session_scope
from app.models import utcnow
from app.repository import get_scrape_control, purge_orders_older_than
from app.scheduler import due_for_recheck

logger = logging.getLogger("flower.refund_scheduler")

# 后台线程可选「驱动器」：拿到 due 清单后真正去触发重抓。
# 默认 None=拉模式（扩展自己来 GET /inbox/refund/pending 拉清单逐单重抓）；
# 未来接入自动抓取器（如 Playwright 二期）时，传一个 driver(ids) 即可由本线程主动驱动。
Driver = Callable[[list[str]], None]


class RefundScheduler:
    """退款重抓后台线程（仿 report_watcher）：周期性算出「该重抓退款状态」的在产订单。

    本服务不抓店小秘——线程只负责**周期性刷新 due 队列快照 + 记日志（+可选驱动器）**，
    实际重抓由扩展拉 `/inbox/refund/pending` 后逐单做、回 `/recheck`。
    与 report_watcher 一致：仅生产入口 main.py 起线程；测试用 create_app 不起线程，可直接调 tick_once()。
    """

    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        interval: float = 60.0,
        recheck_interval_seconds: float = 600.0,
        limit: int = 200,
        driver: Driver | None = None,
    ) -> None:
        self._factory = factory
        self._interval = interval
        self._recheck_interval = recheck_interval_seconds
        self._limit = limit
        self._driver = driver
        self._stop = threading.Event()
        # 可观测快照（最近一次 tick 的结果）。
        self.last_run_at: datetime | None = None
        self.pending_count: int = 0
        self.pending_ids: list[str] = []

    def tick_once(self) -> list[str]:
        """跑一轮：算 due 清单、刷新快照、记日志、（若有）驱动重抓。返回 due 的 order_id 列表。

        顺手做「订单保留清理」：读 scrape_control.retention_days，>0 则删 received_at 早于
        (now - N 天) 的订单（无人值守也跑；0=关，默认不删）。
        """
        with session_scope(self._factory) as session:
            self._purge_by_retention(session)
            due = due_for_recheck(
                session,
                now=utcnow(),
                interval_seconds=self._recheck_interval,
                limit=self._limit,
            )
            ids = [order.order_id for order in due]
        self.last_run_at = utcnow()
        self.pending_count = len(ids)
        self.pending_ids = ids
        if ids:
            logger.info("退款重抓：本轮 %d 单待重抓 %s", len(ids), ids[:20])
        if self._driver is not None and ids:
            try:
                self._driver(ids)
            except Exception:  # 驱动失败不影响线程存活，下轮再来
                logger.exception("退款重抓驱动器执行失败")
        return ids

    def _purge_by_retention(self, session) -> int:
        """读 retention_days 删旧单（无人值守清理）；0/缺省=关，返回删除条数。异常不杀线程。"""
        try:
            control = get_scrape_control(session)
            retention = control.retention_days if control else 0
            if not retention or retention <= 0:
                return 0
            removed = purge_orders_older_than(session, retention)
            if removed:
                logger.info("订单保留清理：删除 %d 单（仅保留最近 %d 天）", removed, retention)
            return removed
        except Exception:  # 清理失败不影响退款 tick / 线程存活
            logger.exception("订单保留清理失败")
            return 0

    def snapshot(self) -> dict:
        return {
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "pending_count": self.pending_count,
            "pending_ids": self.pending_ids,
            "interval": self._interval,
            "recheck_interval_seconds": self._recheck_interval,
        }

    def run_forever(self, interval: float | None = None) -> None:
        tick = interval if interval is not None else self._interval
        while not self._stop.wait(tick):
            try:
                self.tick_once()
            except Exception:  # 单轮异常不杀线程
                logger.exception("退款重抓 tick 失败")

    def stop(self) -> None:
        self._stop.set()
