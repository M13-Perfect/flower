from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> Engine:
    # SQLite + 多线程（uvicorn worker）需关掉 check_same_thread。
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, future=True, connect_args=connect_args)
    if database_url.startswith("sqlite"):
        _enable_sqlite_pragmas(engine)
    return engine


def _enable_sqlite_pragmas(engine: Engine) -> None:
    """每条 SQLite 连接开 WAL + NORMAL + busy_timeout（性能·阶段一 DB 地基）：

    - journal_mode=WAL：**写不堵读**（洪峰入库时 UI 轮询/调度照常读），并发写少撞锁。WAL 持久于库文件、重复设无害。
    - synchronous=NORMAL：WAL 下安全的折中，少一次每事务 fsync，写入更快（崩溃最多丢最后一笔未 checkpoint 的事务，订单可重抓，可接受）。
    - busy_timeout=5000：拿不到锁时排队等 5s 再报错，替代立刻 SQLITE_BUSY。
    synchronous/busy_timeout 是连接级，须每条连接设，故挂 connect 事件。
    """
    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    from app import models  # noqa: F401  确保 ORM 模型已注册到 Base.metadata

    Base.metadata.create_all(engine)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """事务作用域：正常退出提交，异常回滚，最后关闭。"""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
