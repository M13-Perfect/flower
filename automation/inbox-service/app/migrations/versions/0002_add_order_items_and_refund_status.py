"""add order_items table and orders.refund_status

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-19

打破「一单一件」：新增 order_items 行项目表 + orders.refund_status 实时状态列（退款拦截用）。
order_items 表对新库由 create_all 自动建；本迁移负责给**已存在的** orders 表补 refund_status 列。
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("refund_status", sa.String(length=64), nullable=True))
    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "order_id",
            sa.String(length=120),
            sa.ForeignKey("orders.order_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("line_index", sa.Integer(), nullable=False),
        sa.Column("product_sku", sa.Text(), nullable=True),
        sa.Column("is_target_box", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("personalization_raw", sa.Text(), nullable=True),
        sa.Column("extras_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_column("orders", "refund_status")
