"""add orders.paid_at and scrape_control table

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-19

自动抓取：orders.paid_at（店小秘付款时间，自动抓取时间基准，扩展放 extras.paid_at 入库时取出）
+ scrape_control 表（flower「设置时间重新开始的开关」：enabled/interval/scrape_from）。
新库由 create_all 自动建；本迁移负责给**已存在的**库补列/补表。
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("paid_at", sa.DateTime(), nullable=True))
    op.create_index("ix_orders_paid_at", "orders", ["paid_at"])
    op.create_table(
        "scrape_control",
        sa.Column("scope", sa.String(length=64), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("scrape_from", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("scrape_control")
    op.drop_index("ix_orders_paid_at", table_name="orders")
    op.drop_column("orders", "paid_at")
