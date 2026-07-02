"""add scrape_control.retention_days

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-19

订单保留天数：后台清理线程按此把 received_at 早于 (now - N 天) 的订单删除。0=关（默认，永不自动删）。
新库由 create_all 自动建；本迁移负责给**已存在的**库补列。
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scrape_control",
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("scrape_control", "retention_days")
