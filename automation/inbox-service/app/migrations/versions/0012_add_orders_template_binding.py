"""add orders template binding columns (GIMP 模板绑定)

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-24

GIMP 模板绑定（生产阻断修复）：订单持久携带「用哪套 GIMP 模板生产」的绑定，
flower 桌面端读 Order.to_dict() 拿 template_id/template_version/template_sha256 传给 GIMP 编辑器。
- 新库由 create_all 自动建这些列；本迁移负责给**已存在的**库补列 + 绑定状态索引。
- 老行迁移后：template_id/version/sha256 = NULL，template_binding_status = 'unbound'
  （server_default 保证既有行回填成 unbound，与模型 default 一致）。
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("template_id", sa.String(length=120), nullable=True))
    op.add_column("orders", sa.Column("template_version", sa.String(length=64), nullable=True))
    op.add_column("orders", sa.Column("template_sha256", sa.String(length=64), nullable=True))
    op.add_column(
        "orders",
        sa.Column(
            "template_binding_status",
            sa.String(length=32),
            nullable=False,
            server_default="unbound",
        ),
    )
    op.create_index("ix_orders_template_binding_status", "orders", ["template_binding_status"])


def downgrade() -> None:
    op.drop_index("ix_orders_template_binding_status", table_name="orders")
    op.drop_column("orders", "template_binding_status")
    op.drop_column("orders", "template_sha256")
    op.drop_column("orders", "template_version")
    op.drop_column("orders", "template_id")
