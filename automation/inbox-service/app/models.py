from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# 订单在系统中的状态（见计划「状态机」）。
STATUS_RECEIVED = "RECEIVED"
STATUS_WRITTEN = "WRITTEN_TO_INBOX"
STATUS_WRITE_FAILED = "WRITE_FAILED"
STATUS_QUEUED = "QUEUED_FOR_BATCH"
STATUS_DONE = "DONE"  # 批量已完成（report.xlsx 中 EXPORTED）
STATUS_CANNOT_AUTOGEN = "CANNOT_AUTOGEN"  # 无法自动生成（需人工核验）

# 标记回写队列（扩展模拟网页操作给店小秘订单打自定义标记）的动作 / 状态。
MARK_ACTION_UNRECOGNIZED = "mark_unrecognized"  # 打「AI未识别」（待处理）
MARK_ACTION_DONE = "mark_done"  # 打「AI已处理」+ 取消「AI未识别」
MARK_ACTIONS = (MARK_ACTION_UNRECOGNIZED, MARK_ACTION_DONE)
MARK_STATUS_PENDING = "pending"  # 待扩展去店小秘打标
MARK_STATUS_DONE = "done"  # 扩展已打成功
MARK_STATUS_FAILED = "failed"  # 重试超上限，放弃

# AI 识别状态对账（2026-06-22）：orders.ai_status 是「AI 识别状态」的**唯一权威**，
# mark_jobs 退化为「把权威态写回店小秘标记」的执行队列。扩展读到订单号 → 查/原子建此状态 → 据此同步页面标记。
# 不变式：页面「AI未识别」与「AI已处理」不得共存；权威态 recognized/locked 同步页面时绝不自动降级回未识别。
AI_STATUS_PENDING = "pending"  # 待 AI 识别（页面对应「AI未识别」icon_brush_bill）；新单默认
AI_STATUS_RECOGNIZED = "recognized"  # AI 已识别（页面对应「AI已处理」icon_change_order）；生成完置此
AI_STATUS_CONFLICT = "conflict"  # 复核冲突（新单/待识别单却已带「AI已处理」标记）；人工裁决前冻结，扩展不动其标记
AI_STATUS_LOCKED = "locked"  # 人工锁定（保留值，本期不设触发）；语义同 recognized，永不自动降级
AI_STATUSES = (AI_STATUS_PENDING, AI_STATUS_RECOGNIZED, AI_STATUS_CONFLICT, AI_STATUS_LOCKED)
# 同步页面标记时只升级到「AI已处理」、绝不打回「AI未识别」的权威态（防自动降级）。
AI_STATUS_NO_DOWNGRADE = (AI_STATUS_RECOGNIZED, AI_STATUS_LOCKED)

# GIMP 模板绑定状态：订单持久携带的「用哪套 GIMP 模板生产」绑定。
# flower 桌面端读 Order.to_dict() 拿 template_id/version/sha256 传给 GIMP 编辑器。
# unbound=未绑定（新单默认 / 老单迁移值）；bound=已绑定有效模板；invalid=曾绑定但校验失败（如 sha256 不符）。
TEMPLATE_BINDING_UNBOUND = "unbound"
TEMPLATE_BINDING_BOUND = "bound"
TEMPLATE_BINDING_INVALID = "invalid"
TEMPLATE_BINDING_STATUSES = (TEMPLATE_BINDING_UNBOUND, TEMPLATE_BINDING_BOUND, TEMPLATE_BINDING_INVALID)


class Order(Base):
    __tablename__ = "orders"
    # 复合索引（性能·阶段一）：调度常按「status 过滤 + received_at 区间/排序」扫；
    # leftmost 前缀也覆盖纯 status 查，故不再单独给 status 建索引。received_at/refund_status 单列索引见各列 index=True。
    __table_args__ = (Index("ix_orders_status_received_at", "status", "received_at"),)

    order_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    remark: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=STATUS_RECEIVED)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # 无法自动生成的原因汇总
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[str] = mapped_column(Text)  # 全量 payload，审计 / 重放
    inbox_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    shop: Mapped[str | None] = mapped_column(String(200), nullable=True)
    spec: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 店小秘订单实时状态（退款拦截用）；首次抓取写入，Phase 2 关键节点重抓刷新。取值待店小秘详情页确认。
    refund_status: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # AI 识别状态（**权威**，2026-06-22）：见 AI_STATUS_* 常量（pending/recognized/conflict/locked）。
    # reconcile_ai_status 维护；扩展据此把店小秘标记同步到位。新单默认 pending；生成完置 recognized；
    # 新单/待识别单却已带「AI已处理」→ conflict（进复核，扩展冻结其标记，等人工裁决）。
    ai_status: Mapped[str] = mapped_column(String(32), default=AI_STATUS_PENDING, nullable=False, index=True)
    # GIMP 模板绑定（订单持久携带，flower 桌面端据此把订单交给对应 GIMP 模板编辑器）。
    # 老单/新单默认 unbound + template_* 全 None；扩展重抓重导入时**保留**已有绑定（见 upsert_order）。
    template_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    template_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    template_binding_status: Mapped[str] = mapped_column(
        String(32), default=TEMPLATE_BINDING_UNBOUND, nullable=False, index=True
    )
    # 店小秘付款时间（自动抓取的时间基准）；扩展放 extras.paid_at，入库时取出。店小秘墙钟时间、非 UTC。
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    written_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 逻辑删除（软删，2026-06-22）：立即清理/单删只「标记」不真删行——查询默认过滤掉 deleted=True 的单，
    # 但行与子表（items/refund_checks/mark_jobs）保留。同一 order_id 被重新导入（扩展重抓）时
    # 在 upsert_order 里复活成 deleted=False（误删可经「重新导入」找回，见计划/AGENTS）。
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 行项目（打破「一单一件」）。幂等重发时整树替换，故 delete-orphan。
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItem.line_index",
    )
    # 退款拦截审计（append-only）：每次生产前重抓/检查记一行。删单时随单清掉，重发不清空。
    refund_checks: Mapped[list["RefundCheck"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="RefundCheck.checked_at",
    )
    # 标记回写任务（给店小秘打 AI未识别/AI已处理）。删单时随单清掉。
    mark_jobs: Mapped[list["MarkJob"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="MarkJob.created_at",
    )

    def to_dict(self) -> dict:
        def iso(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        return {
            "order_id": self.order_id,
            "remark": self.remark,
            "status": self.status,
            "reason": self.reason,
            "error": self.error,
            "inbox_path": self.inbox_path,
            "shop": self.shop,
            "spec": self.spec,
            "source_url": self.source_url,
            "refund_status": self.refund_status,
            # AI 识别状态（权威）：配置端/管理员端订单表据此显示标签 + 「复核」筛选。
            "ai_status": self.ai_status,
            # GIMP 模板绑定：flower 桌面端读这些字段把订单交给对应 GIMP 模板编辑器。
            "template_id": self.template_id,
            "template_version": self.template_version,
            "template_sha256": self.template_sha256,
            "template_binding_status": self.template_binding_status,
            "paid_at": iso(self.paid_at),
            "items": [item.to_dict() for item in self.items],
            # 标记回写任务摘要（供配置端订单表「标签状态」列派生：未识别/已处理 + 待写/已写/失败）。
            "mark_jobs": [{"action": j.action, "status": j.status} for j in self.mark_jobs],
            "received_at": iso(self.received_at),
            "updated_at": iso(self.updated_at),
            "written_at": iso(self.written_at),
            "done_at": iso(self.done_at),
            "deleted": self.deleted,
            "deleted_at": iso(self.deleted_at),
        }


class OrderItem(Base):
    """订单行项目：同一订单可有多个目标盒子 + 其他商品。

    语义拆分（一条备注 N 个名字 → N 个定制单元）不在这里做，交给 Flower GPT 解析层；
    本表只承载扩展从店小秘详情页结构化抓到的「行项目 + 原始备注」。
    """

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.order_id", ondelete="CASCADE"), index=True
    )
    line_index: Mapped[int] = mapped_column(Integer)  # 订单内行项目序号，从 0 起
    product_sku: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_target_box: Mapped[bool] = mapped_column(Boolean, default=True)  # 是否本系统负责生产
    quantity: Mapped[int] = mapped_column(Integer, default=1)  # 该行件数（店小秘 ×N）
    personalization_raw: Mapped[str | None] = mapped_column(Text, nullable=True)  # 该行原始定制备注
    extras_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 该行店小秘特定字段（图片/链接等）

    order: Mapped["Order"] = relationship(back_populates="items")

    def to_dict(self) -> dict:
        return {
            "line_index": self.line_index,
            "product_sku": self.product_sku,
            "is_target_box": self.is_target_box,
            "quantity": self.quantity,
            "personalization_raw": self.personalization_raw,
            "extras": json.loads(self.extras_json) if self.extras_json else {},
        }


class RefundCheck(Base):
    """退款拦截审计：某个生产阶段对订单实时状态做的一次检查。

    实时状态由扩展重抓后推送；本表只记「在某阶段拿到了什么状态、判定阻断/警告/放行」（计划 §7 / §10.5）。
    """

    __tablename__ = "refund_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.order_id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(32))  # typesetting / engraving / shipping
    queried_status: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 检查时的状态原文
    blocked_action: Mapped[str] = mapped_column(String(16))  # allow / warn / block
    operator: Mapped[str | None] = mapped_column(String(120), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    order: Mapped["Order"] = relationship(back_populates="refund_checks")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "order_id": self.order_id,
            "stage": self.stage,
            "queried_status": self.queried_status,
            "blocked_action": self.blocked_action,
            "blocked": self.blocked_action == "block",
            "operator": self.operator,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
        }


class Checkpoint(Base):
    """调度断点：按 scope 记「上次成功扫到的时间游标（半开区间上界）」。

    退款重抓调度用：规则 B（从上次成功位置续）读它做下一个窗口的 start，扫完推进到窗口 end；
    服务中断后恢复不漏单（计划 §3.5）。
    """

    __tablename__ = "checkpoints"

    scope: Mapped[str] = mapped_column(String(64), primary_key=True)  # 如 "refund_recheck"
    cursor: Mapped[datetime] = mapped_column(DateTime)  # 上次成功扫描的上界（半开区间 end）
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict:
        return {
            "scope": self.scope,
            "cursor": self.cursor.isoformat() if self.cursor else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ScrapeControl(Base):
    """自动抓取控制 = **任务租约**（flower 是唯一控制面，扩展只读这里决定是否执行）。

    ⚠️ P0 修复（2026-06-22）：原来只有一个布尔 ``enabled``，且存在独立常驻的 inbox-service DB 里——
    flower 关掉后 ``enabled=true`` 仍永久留存，扩展每次开店小秘页都误以为「已授权」自动抓取+打标。
    现改为**任务租约 + 心跳**：``enabled=true`` 本身不再等于授权，必须同时有未过期的租约（flower 持续心跳续约）。
    flower 一关 / 崩溃 / 点停止 → 不再续约 → 租约到期 → 服务端算出的 ``authorized`` 自动变 false → 扩展停。

    授权判据（服务端时钟权威，见 app/authorization.py is_authorized）：
        enabled 且 task_id 非空 且 lease_expires_at 在未来 且 scrape_from 有值（订单时间范围必填）。

    scrape_from / scrape_to 用店小秘付款时间（墙钟）界定**订单时间范围**，扩展据此过滤、防把历史订单纳入。
    """

    __tablename__ = "scrape_control"

    scope: Mapped[str] = mapped_column(String(64), primary_key=True)  # 默认 "order_scrape"
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # 自动抓总开关（≠授权，见类注释）
    interval_seconds: Mapped[int] = mapped_column(Integer, default=300)  # 扩展自动抓间隔
    scrape_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 订单时间范围下界（付款时间，必填才授权）
    # ── 任务租约字段（P0，2026-06-22）。无任务时全为 NULL / 空。 ──
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 当前任务 id（uuid hex）；NULL=无任务
    flower_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 下发任务的 flower 实例标识
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 租约失效时间（naive UTC）；过期=未授权
    task_issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 任务下发时间（naive UTC）
    scrape_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 订单时间范围上界（付款时间，可空=无上界）
    allowed_actions: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 允许操作 csv，如 "scrape,mark"
    shop_scope: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 允许店铺/账号 csv；NULL=不限店铺
    # 订单保留天数：后台按此把 received_at 早于 (now - N 天) 的单删除。0=关（永不自动删，默认）。
    retention_days: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict:
        return {
            "scope": self.scope,
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "scrape_from": self.scrape_from.isoformat() if self.scrape_from else None,
            "scrape_to": self.scrape_to.isoformat() if self.scrape_to else None,
            "task_id": self.task_id,
            "flower_instance_id": self.flower_instance_id,
            "lease_expires_at": self.lease_expires_at.isoformat() if self.lease_expires_at else None,
            "task_issued_at": self.task_issued_at.isoformat() if self.task_issued_at else None,
            "allowed_actions": self.allowed_actions,
            "shop_scope": self.shop_scope,
            "retention_days": self.retention_days,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class MarkJob(Base):
    """标记回写任务：让扩展去店小秘给某订单打/清自定义标记（店小秘无 API，只能模拟网页操作）。

    持久化（区别于秒级内存的 rescrape_queue）：打标是异步的——flower 生成完那一刻扩展可能没开着店小秘，
    任务要能等几分钟/几小时。(order_id, action) 唯一，重入队=重置为 pending（幂等）。
    """

    __tablename__ = "mark_jobs"
    __table_args__ = (UniqueConstraint("order_id", "action", name="uq_mark_jobs_order_action"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.order_id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(32))  # mark_unrecognized / mark_done
    status: Mapped[str] = mapped_column(String(16), default=MARK_STATUS_PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    order: Mapped["Order"] = relationship(back_populates="mark_jobs")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "order_id": self.order_id,
            "action": self.action,
            "status": self.status,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "source_url": self.order.source_url if self.order else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
