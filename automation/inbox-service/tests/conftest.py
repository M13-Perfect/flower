from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.config import Settings  # noqa: E402
from app.factory import create_app  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    """每个用例独立的临时收件夹 / 报告夹 / 批次夹 / SQLite，互不干扰，也不碰真实 outputs/。"""
    return Settings(
        inbox_dir=tmp_path / "inbox",
        reports_dir=tmp_path / "reports",
        batches_dir=tmp_path / "batches",
        db_path=tmp_path / "inbox.db",
        sandbox_dir=tmp_path / "sandbox",
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


# 任务租约（P0 2026-06-22）：自动抓取/打标的副作用端点现在要求**有效任务授权**。
# 测试里用这个 helper 先「开始一个宽时间窗的采集任务」（覆盖一切 paid_at），让 batch/diff/mark 正常工作。
WIDE_TASK_FROM = "2000-01-01 00:00"  # 足够早的下界，任何 paid_at 都在窗内


def start_task(test_client, *, scrape_from: str = WIDE_TASK_FROM, scrape_to: str | None = None, **extra):
    body = {"flower_instance_id": "test-flower", "scrape_from": scrape_from, **extra}
    if scrape_to is not None:
        body["scrape_to"] = scrape_to
    resp = test_client.post("/inbox/scrape/task/start", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def activate_task(client):
    """返回一个可调用，按需在当前 client 上激活采集任务（默认宽时间窗）。"""

    def _activate(**kwargs):
        return start_task(client, **kwargs)

    return _activate
