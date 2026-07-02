"""add orders.deleted / deleted_at (soft delete)

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-22

逻辑删除（软删）：立即清理 / 单删只把订单标记 deleted=True（不真删行、不删子表、不删收件夹文件）。
查询默认过滤 deleted=True；同一 order_id 重新导入时复活成 deleted=False。
新库由 create_all 自动建这两列；本迁移负责给**已存在的**库补列 + deleted 索引。
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("orders", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_index("ix_orders_deleted", "orders", ["deleted"])


def downgrade() -> None:
    op.drop_index("ix_orders_deleted", table_name="orders")
    op.drop_column("orders", "deleted_at")
    op.drop_column("orders", "deleted")
