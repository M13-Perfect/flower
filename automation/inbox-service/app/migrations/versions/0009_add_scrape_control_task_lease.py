"""add scrape_control task-lease columns (P0 uncontrolled-side-effect fix)

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-22

P0 修复：自动抓取/打标失控。原 scrape_control 只有布尔 enabled，且常驻 DB 永不过期 →
flower 关掉后扩展仍误判已授权。改为任务租约：加 task_id / flower_instance_id / lease_expires_at /
task_issued_at / scrape_to / allowed_actions / shop_scope。授权 = enabled 且租约未过期 且有 scrape_from。

新库由 create_all 自动建（models 已加这些列）；本迁移负责给**已存在的**库补列。全部可空、无 server_default，
对既有行天然为 NULL（= 无任务 = 未授权），正好是安全默认（fail-closed）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


_NEW_COLUMNS = (
    ("task_id", sa.String(length=64)),
    ("flower_instance_id", sa.String(length=64)),
    ("lease_expires_at", sa.DateTime()),
    ("task_issued_at", sa.DateTime()),
    ("scrape_to", sa.DateTime()),
    ("allowed_actions", sa.String(length=128)),
    ("shop_scope", sa.String(length=500)),
)


def upgrade() -> None:
    for name, type_ in _NEW_COLUMNS:
        op.add_column("scrape_control", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_NEW_COLUMNS):
        op.drop_column("scrape_control", name)
