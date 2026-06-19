from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# app/config.py → app → inbox-service → automation → flower 仓库根。
SERVICE_ROOT = Path(__file__).resolve().parents[1]
FLOWER_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INBOX_DIR = FLOWER_ROOT / "outputs" / "inbox"
DEFAULT_REPORTS_DIR = FLOWER_ROOT / "outputs" / "reports"
DEFAULT_BATCHES_DIR = FLOWER_ROOT / "outputs" / "inbox-batches"
DEFAULT_DB_PATH = SERVICE_ROOT / "inbox.db"
SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class Settings:
    """服务配置；默认从环境变量读取，测试可直接构造覆盖。"""

    host: str = "127.0.0.1"
    port: int = 8770
    inbox_dir: Path = DEFAULT_INBOX_DIR
    reports_dir: Path = DEFAULT_REPORTS_DIR  # Flower 批量报告 outputs/reports
    batches_dir: Path = DEFAULT_BATCHES_DIR  # 服务导出的待批量 xlsx 落点
    db_path: Path = DEFAULT_DB_PATH
    schema_version: str = SCHEMA_VERSION

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"


def settings_from_env() -> Settings:
    inbox = os.environ.get("FLOWER_INBOX_DIR")
    reports = os.environ.get("FLOWER_REPORTS_DIR")
    batches = os.environ.get("FLOWER_BATCHES_DIR")
    db = os.environ.get("FLOWER_INBOX_DB")
    return Settings(
        host=os.environ.get("FLOWER_INBOX_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLOWER_INBOX_PORT", "8770")),
        inbox_dir=Path(inbox) if inbox else DEFAULT_INBOX_DIR,
        reports_dir=Path(reports) if reports else DEFAULT_REPORTS_DIR,
        batches_dir=Path(batches) if batches else DEFAULT_BATCHES_DIR,
        db_path=Path(db) if db else DEFAULT_DB_PATH,
    )
