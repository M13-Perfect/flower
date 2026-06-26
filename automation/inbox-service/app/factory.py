from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, settings_from_env
from app.db import init_db, make_engine, make_session_factory
from app.refund_scheduler import RefundScheduler
from app.report_watcher import ReportWatcher
from app.rescrape_queue import RescrapeQueue
from app.routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    """构造 FastAPI 应用。测试传入临时 Settings；生产由 main.py 用环境变量构造。

    只创建 ReportWatcher 对象，不在此启动后台线程——测试用本函数构造时不该有线程副作用；
    生产入口 main.py 负责起线程。
    """
    settings = settings or settings_from_env()
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)

    app = FastAPI(title="Flower Inbox Service", version="0.1.0")
    # 只允许扩展（chrome-extension://）与本机 localhost 来源。
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(chrome-extension://.*|http://(127\.0\.0\.1|localhost):\d+)$",
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.session_factory = session_factory
    # 运行模式（D3）：默认生产重试；test_reset 时改写到 sandbox。重启回落默认=安全（不会误留测试态）。
    app.state.run_mode = "production_retry"
    app.state.report_watcher = ReportWatcher(session_factory, settings.reports_dir)
    # 退款重抓调度器：仅造对象，不起线程（同 report_watcher）；生产入口 main.py 负责起线程。
    app.state.refund_scheduler = RefundScheduler(
        session_factory,
        interval=settings.refund_scan_interval,
        recheck_interval_seconds=settings.refund_recheck_interval,
        limit=settings.refund_scan_limit,
    )
    # 定向重抓握手（option B）：Ezcad 入队某单 → 扩展拉取重抓 → 回填 → Ezcad 轮询。内存态、秒级 TTL。
    app.state.rescrape_queue = RescrapeQueue(ttl_seconds=settings.refund_rescrape_ttl)
    app.include_router(router)
    return app
