"""add mark_jobs table

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-20

标记回写队列：让扩展去店小秘给订单打/清自定义标记（AI未识别 / AI已处理）。店小秘无 API，只能模拟网页操作。
持久化（区别于秒级内存的 rescrape）：打标异步，扩展当时可能没开店小秘，任务要能等。
新库由 create_all 自动建；本迁移负责给**已存在的**库补表。
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mark_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "order_id",
            sa.String(length=120),
            sa.ForeignKey("orders.order_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("order_id", "action", name="uq_mark_jobs_order_action"),
    )


def downgrade() -> None:
    op.drop_table("mark_jobs")
