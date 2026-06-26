"""add refund_checks table

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-19

退款拦截审计表：每次生产前（排版/雕刻/发货）对订单实时状态做的一次检查记录。
新库由 create_all 自动建；本迁移负责给**已存在的**库补表。
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refund_checks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "order_id",
            sa.String(length=120),
            sa.ForeignKey("orders.order_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("queried_status", sa.String(length=64), nullable=True),
        sa.Column("blocked_action", sa.String(length=16), nullable=False),
        sa.Column("operator", sa.String(length=120), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("refund_checks")
