"""add orders.ai_status (AI 识别状态对账权威列)

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-22

AI 识别状态对账（需求 2026-06-22）：orders.ai_status 成为「AI 识别状态」唯一权威
（pending/recognized/conflict/locked），mark_jobs 退化为把权威态写回店小秘标记的执行队列。
- 新库由 create_all 自动建该列；本迁移给**已存在**的库补列 + 回填 + 索引。
- 回填：已有 active（pending/done）的 mark_done 任务的单 → recognized；其余保持 pending。
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("ai_status", sa.String(32), nullable=False, server_default="pending"),
    )
    op.create_index("ix_orders_ai_status", "orders", ["ai_status"])
    # 回填：已有「AI已处理」(mark_done) 任务且未失败（pending/done）的单视为 recognized；其余保持 pending。
    op.execute(
        """
        UPDATE orders SET ai_status = 'recognized'
        WHERE order_id IN (
            SELECT order_id FROM mark_jobs
            WHERE action = 'mark_done' AND status IN ('pending', 'done')
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_orders_ai_status", table_name="orders")
    op.drop_column("orders", "ai_status")
