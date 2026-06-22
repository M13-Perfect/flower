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
# 测试重置(test_reset)模式的 sandbox 根：刻意放在 SERVICE_ROOT 下、与生产 outputs/ 完全分离，
# 保证「测试绝不碰生产 outputs/」（计划 §8 / D3）。
DEFAULT_SANDBOX_DIR = SERVICE_ROOT / "sandbox"
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
    # 退款重抓调度（后台线程）
    refund_scan_interval: float = 60.0  # 后台线程 tick 间隔（秒）
    refund_recheck_interval: float = 600.0  # 订单两次退款检查的最小间隔（秒）；决定「该重抓」
    refund_scan_limit: int = 200  # 单轮 due 清单上限，避免一次圈太多压垮扩展/店小秘
    # 定向重抓握手（option B）请求的 TTL（秒）：pending 超此时长视为过期（扩展没跑/没开店小秘）。
    refund_rescrape_ttl: float = 60.0
    # 标记回写队列（扩展给店小秘打 AI未识别/AI已处理）：失败重试上限、单轮拉取上限、新单是否自动入队 AI未识别。
    mark_max_attempts: int = 5
    mark_pending_limit: int = 50
    mark_enqueue_unrecognized: bool = True
    # AI 识别状态对账（2026-06-22）：扩展读到订单号 → POST /inbox/ai/reconcile 原子 get-or-create + 判定。
    # 关掉（=False）则端点对所有单返回 desired_tag=none（不创建、不改标签），作为总开关/止血阀。
    ai_reconcile_enabled: bool = True
    # 任务租约（P0 2026-06-22）：flower「开始采集」下发任务后须每 lease/3 左右心跳续约一次；
    # 超过 scrape_lease_seconds 没收到心跳 → 租约过期 → authorized=false → 扩展自动停（flower 关掉/崩溃即停）。
    scrape_lease_seconds: float = 90.0
    # 测试重置(test_reset)模式的 sandbox 根（与生产 outputs/ 分离）。
    sandbox_dir: Path = DEFAULT_SANDBOX_DIR

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def sandbox_inbox_dir(self) -> Path:
        return self.sandbox_dir / "inbox"

    @property
    def sandbox_batches_dir(self) -> Path:
        return self.sandbox_dir / "batches"


def settings_from_env() -> Settings:
    inbox = os.environ.get("FLOWER_INBOX_DIR")
    reports = os.environ.get("FLOWER_REPORTS_DIR")
    batches = os.environ.get("FLOWER_BATCHES_DIR")
    db = os.environ.get("FLOWER_INBOX_DB")
    sandbox = os.environ.get("FLOWER_SANDBOX_DIR")
    return Settings(
        host=os.environ.get("FLOWER_INBOX_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLOWER_INBOX_PORT", "8770")),
        inbox_dir=Path(inbox) if inbox else DEFAULT_INBOX_DIR,
        reports_dir=Path(reports) if reports else DEFAULT_REPORTS_DIR,
        batches_dir=Path(batches) if batches else DEFAULT_BATCHES_DIR,
        db_path=Path(db) if db else DEFAULT_DB_PATH,
        refund_scan_interval=float(os.environ.get("FLOWER_REFUND_SCAN_INTERVAL", "60")),
        refund_recheck_interval=float(os.environ.get("FLOWER_REFUND_RECHECK_INTERVAL", "600")),
        refund_scan_limit=int(os.environ.get("FLOWER_REFUND_SCAN_LIMIT", "200")),
        refund_rescrape_ttl=float(os.environ.get("FLOWER_REFUND_RESCRAPE_TTL", "60")),
        mark_max_attempts=int(os.environ.get("FLOWER_MARK_MAX_ATTEMPTS", "5")),
        mark_pending_limit=int(os.environ.get("FLOWER_MARK_PENDING_LIMIT", "50")),
        mark_enqueue_unrecognized=os.environ.get("FLOWER_MARK_ENQUEUE_UNRECOGNIZED", "1")
        not in ("0", "false", "False", ""),
        ai_reconcile_enabled=os.environ.get("FLOWER_AI_RECONCILE_ENABLED", "1")
        not in ("0", "false", "False", ""),
        scrape_lease_seconds=float(os.environ.get("FLOWER_SCRAPE_LEASE_SECONDS", "90")),
        sandbox_dir=Path(sandbox) if sandbox else DEFAULT_SANDBOX_DIR,
    )
