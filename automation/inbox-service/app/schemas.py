from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 与 automation/contracts/order.schema.json 的 order_id 正则一致（文件名安全）。
ORDER_ID_PATTERN = r"^[A-Za-z0-9_.\-]+$"


class OrderItemPayload(BaseModel):
    """订单行项目，对齐 contracts/order.schema.json 的 items[]。

    扩展只抓「结构 + 原始备注」，**不做语义拆分**（一条备注 N 个名字 → N 个定制单元交给 Flower GPT 解析层）。
    """

    model_config = ConfigDict(extra="forbid")

    line_index: int = Field(ge=0)
    product_sku: str | None = Field(default=None, max_length=1000)
    is_target_box: bool = True
    quantity: int = Field(default=1, ge=1)
    personalization_raw: str | None = Field(default=None, max_length=5000)
    extras: dict[str, Any] = Field(default_factory=dict)


class OrderPayload(BaseModel):
    """扩展 → 服务的订单报文，对齐 contracts/order.schema.json（snake_case + additionalProperties:false）。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    order_id: str = Field(min_length=1, max_length=120, pattern=ORDER_ID_PATTERN)
    # remark 自 2026-06-19 改为可选、可空串（D-1）：列表页无定制备注的标品单 remark 为空，数据走 items[]。
    # 始终归一成「已 strip 的字符串」（None/缺省 → ""；纯空白 → ""，修 D-2），存进 Order.remark(Text NOT NULL) 不破 DB。
    remark: str = Field(default="", max_length=5000)
    shop: str | None = Field(default=None, max_length=200)
    spec: str | None = Field(default=None, max_length=1000)
    source_url: str | None = Field(default=None, max_length=2000)
    scraped_at: str | None = None
    # 店小秘实时状态（退款拦截，可选）；缺省 None=未抓到/旧扩展。
    refund_status: str | None = Field(default=None, max_length=64)
    # 行项目（可选）；缺省空列表=按 remark 走旧单件逻辑，老扩展零影响。
    items: list[OrderItemPayload] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)

    @field_validator("remark", mode="before")
    @classmethod
    def _normalize_remark(cls, value: Any) -> str:
        """空 remark 归一：None/非字符串 → ""；字符串 strip（修 D-2：纯空白不再当有效备注）。

        在 max_length 校验前跑（mode=before），strip 后仍超 5000 才报错。
        """
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return value


class IngestResponse(BaseModel):
    order_id: str
    status: str
    dedup: bool
    inbox_path: str | None = None
    # 内容与上次逐字节一致 → 本次未覆盖任何字段、未重写收件夹文件（no-op）。
    unchanged: bool = False
    # 本次是否**新建了订单行或复活了软删行**（=「数据库原来没有该活跃订单」）。
    # 手动「→Flower」条件打标据此判 CREATED_NEW（dedup 含软删，无法区分复活，故单列；2026-06-22）。
    created: bool = False


class IngestBatchRequest(BaseModel):
    """批量入库（扩展一次回传多单，减少网络往返；阶段二抓取吞吐用）。

    一次最多 500 单（一屏列表远小于此，留余量）；每单独立处理，单条文件写失败不连累整批。
    """

    model_config = ConfigDict(extra="forbid")

    orders: list[OrderPayload] = Field(default_factory=list, max_length=500)


class RecheckRequest(BaseModel):
    """生产阶段退款检查请求（flower 排版前 / Ezcad 雕刻前 / 发货前调用）。"""

    model_config = ConfigDict(extra="forbid")

    # 生产阶段：决定 D4 容错强度（排版前=warn 可继续；雕刻/发货前=block）。
    stage: Literal["typesetting", "engraving", "shipping"] = "typesetting"
    # 扩展刚重抓到的新状态（可选）；提供则先刷新 Order.refund_status 再判定。
    # 缺省=用库里「最后已知状态」判定（本服务自身无法抓店小秘）。
    refund_status: str | None = Field(default=None, max_length=64)
    operator: str | None = Field(default=None, max_length=120)


class RecheckResponse(BaseModel):
    order_id: str
    stage: str
    stage_label: str
    queried_status: str | None
    # 退款状态原文（= queried_status 的别名键）。调用方（Ezcad inbox_client._parse）按 refund_status 读，
    # 故响应必须同时带它，否则下游 from_raw(None)=NONE 会把退款单误判放行（2026-06-19 真机踩到）。
    refund_status: str | None = None
    # 订单行项目（供「其他商品」配货提醒）；契约承诺「同一 /recheck 响应携带 items[]」。
    items: list[dict[str, Any]] = Field(default_factory=list)
    # 是否已生成素材（= 存在 AI已处理标记回写任务 pending/done）。EzCad 雕刻前据此对未生成单软警告（标准·EzCad）。
    ai_processed: bool = False
    blocked: bool
    action: str  # allow / warn / block
    reason: str
    check_id: int
    checked_at: str


class ManifestEntryPayload(BaseModel):
    """扩展上报的列表页轻清单条目：只带 order_id + 付款时间（不含全量字段）。"""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=120, pattern=ORDER_ID_PATTERN)
    paid_at: str | None = Field(default=None, max_length=64)  # 店小秘付款时间原文（墙钟）


class ScrapeDiffRequest(BaseModel):
    """扩展把列表页可见订单清单交给服务算差异，得到该重抓的统一 worklist。"""

    model_config = ConfigDict(extra="forbid")

    orders: list[ManifestEntryPayload] = Field(default_factory=list)
    recheck_interval: float | None = Field(default=None, ge=0)  # 覆盖退款刷新阈值（缺省取配置）
    scope: str = Field(default="order_scrape", max_length=64)


class RunModeUpdate(BaseModel):
    """切换运行模式（D3 测试重置 vs 生产重试隔离）。"""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["production_retry", "test_reset"]
    reset_sandbox: bool = False  # 切到/停留 test_reset 时是否清空 sandbox 旧文件（清旧）


class ScrapeControlUpdate(BaseModel):
    """flower「设置时间重新开始的开关」：部分更新（缺省字段不动）。"""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    interval_seconds: int | None = Field(default=None, ge=1)
    # 从此付款时间往后重抓（= 重置游标）。传 restart_from 才更新；传 null 可清空。
    restart_from: str | None = None
    clear_restart_from: bool = False  # 显式清空 scrape_from
    # 订单保留天数：后台按此删旧单。0=关（默认，永不自动删）；传才更新。
    retention_days: int | None = Field(default=None, ge=0)


class ScrapeTaskStart(BaseModel):
    """flower「开始采集」下发任务（P0 任务租约）。scrape_from 必填——缺订单时间范围一律拒绝执行。"""

    model_config = ConfigDict(extra="forbid")

    flower_instance_id: str = Field(min_length=1, max_length=64)  # flower 当前运行实例标识
    scrape_from: str = Field(min_length=1)  # 订单时间范围下界（付款时间，墙钟），必填
    scrape_to: str | None = None  # 订单时间范围上界（可空=无上界）
    interval_seconds: int | None = Field(default=None, ge=1)
    lease_seconds: float | None = Field(default=None, gt=0)  # 租约时长（缺省取服务配置）
    allowed_actions: list[Literal["scrape", "mark"]] | None = None  # 允许操作；缺省=[scrape, mark]
    shop_scope: list[str] | None = None  # 允许店铺/账号；缺省=不限店铺


class ScrapeTaskHeartbeat(BaseModel):
    """flower 心跳续约：只续当前任务。task_id 不符 → 409。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=64)
    flower_instance_id: str = Field(min_length=1, max_length=64)
    lease_seconds: float | None = Field(default=None, gt=0)


class ScrapeTaskStop(BaseModel):
    """flower「停止采集」/ 关闭：释放当前任务租约。task_id 缺省=强制释放；给定且不符=不动（别人的任务）。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str | None = Field(default=None, max_length=64)
    flower_instance_id: str | None = Field(default=None, max_length=64)


class PurgeRequest(BaseModel):
    """手动清理：删除 received_at 早于 (now - older_than_days 天) 的订单。要求 >=1（不提供删全部的危险路径）。"""

    model_config = ConfigDict(extra="forbid")

    older_than_days: int = Field(ge=1)


class RescrapeRequestBody(BaseModel):
    """Ezcad 入队：请扩展去店小秘按订单号搜索并重抓该单退款状态（option B 定向重抓）。"""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=120, pattern=ORDER_ID_PATTERN)


class RescrapeResultBody(BaseModel):
    """扩展回填定向重抓结果：found=True 带回实时 refund_status；False=店小秘搜不到该单。"""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=120, pattern=ORDER_ID_PATTERN)
    found: bool
    refund_status: str | None = Field(default=None, max_length=64)


class ScanRequest(BaseModel):
    """退款重抓调度：算出该轮要让扩展重抓退款状态的订单清单（不抓取，只圈范围）。"""

    model_config = ConfigDict(extra="forbid")

    rule: Literal["A", "B", "C"] = "B"
    scope: str = Field(default="refund_recheck", max_length=64)
    window_seconds: int | None = Field(default=None, ge=1)  # 规则 A 窗口长度
    start: datetime | None = None  # 规则 C 必填
    end: datetime | None = None  # 规则 C 必填
    active_only: bool = True  # 排除已完成订单
    advance: bool = True  # 扫完把 checkpoint 推进到窗口 end（规则 B 续跑）


class MarkRequestBody(BaseModel):
    """入队一条标记回写任务（flower 生成成功后调它入队 mark_done）。"""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=120, pattern=ORDER_ID_PATTERN)
    action: Literal["mark_unrecognized", "mark_done"]


class MarkResultBody(BaseModel):
    """扩展回填标记回写结果：ok=True 成功打标；ok=False 失败（记 attempts，超上限→failed）。"""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=120, pattern=ORDER_ID_PATTERN)
    action: Literal["mark_unrecognized", "mark_done"]
    ok: bool
    detail: str | None = Field(default=None, max_length=500)


class AiReconcileBody(BaseModel):
    """AI 识别状态对账：扩展读到订单行后上报页面是否带「AI已处理」/「AI未识别」标记，
    服务以 DB ai_status 为唯一权威做原子 get-or-create + 判定，返回 desired_tag。"""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=120, pattern=ORDER_ID_PATTERN)
    ai_done: bool  # 页面是否已带「AI已处理」标记（icon_change_order）
    ai_unrecognized: bool = False  # 页面是否已带「AI未识别」标记（icon_brush_bill）；审计用
