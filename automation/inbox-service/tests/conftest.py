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
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client
