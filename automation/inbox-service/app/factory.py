from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, settings_from_env
from app.db import init_db, make_engine, make_session_factory
from app.report_watcher import ReportWatcher
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
    app.state.report_watcher = ReportWatcher(session_factory, settings.reports_dir)
    app.include_router(router)
    return app
