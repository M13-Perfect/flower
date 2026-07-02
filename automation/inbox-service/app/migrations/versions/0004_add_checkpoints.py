"""add checkpoints table

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-19

调度断点表：退款重抓调度按 scope 记「上次成功扫到的时间游标」，支持规则 B 断点续跑。
新库由 create_all 自动建；本迁移负责给**已存在的**库补表。
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "checkpoints",
        sa.Column("scope", sa.String(length=64), primary_key=True),
        sa.Column("cursor", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("checkpoints")
