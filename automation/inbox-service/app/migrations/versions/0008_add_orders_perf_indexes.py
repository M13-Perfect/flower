"""add orders perf indexes (received_at, refund_status, status+received_at)

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-20

性能·阶段一 DB 地基：订单表原来只有 paid_at 有索引，调度每 60s 按 received_at/status 全表扫、
退款按 refund_status 查也全表扫。补三个索引消除全表扫。
新库由 create_all 自动建（models 已加 index=True / __table_args__）；本迁移负责给**已存在的**库补索引。
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_orders_received_at", "orders", ["received_at"])
    op.create_index("ix_orders_refund_status", "orders", ["refund_status"])
    op.create_index("ix_orders_status_received_at", "orders", ["status", "received_at"])


def downgrade() -> None:
    op.drop_index("ix_orders_status_received_at", table_name="orders")
    op.drop_index("ix_orders_refund_status", table_name="orders")
    op.drop_index("ix_orders_received_at", table_name="orders")
