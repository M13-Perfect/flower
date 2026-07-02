from __future__ import annotations

# 退款拦截判定：把店小秘「订单实时状态」(refund_status) + 生产阶段 → 放行/警告/阻断。
#
# 背景：店小秘 API 不开放，实时状态由 Chrome 扩展重抓后推送，本服务只拿到「最后已知状态」。
# 本模块不做抓取，只在生产阶段闸门上对已知状态做判定（计划 §7 / D4）。
#
# 三类判定结果（写入 RefundCheck.blocked_action）：
#   allow —— 放行（状态为正常的真实订单状态）。
#   warn  —— 警告但可继续（仅排版前；状态无法确认是否退款）。
#   block —— 阻断（确认退款/取消；或不可逆阶段[雕刻/发货前]仍无法确认）。
#
# D4（已与用户敲定）：退款查询失败/状态缺失时——排版前=可继续(仅警告)；雕刻/发货前=阻断。

# ⚠️ 判断点（保守默认，可调）：
#   1) REFUND_KEYWORDS / RISK_KEYWORDS 的取值——按真实样例(已退款/风控中等)归纳，待更多真单补全。
#   2) 「风控中」归入 caution（未确认安全），不是无条件 block——即排版前仍放行、仅雕刻/发货前阻断。
REFUND_KEYWORDS = ("退款", "退货", "已取消", "取消", "拒收", "拒签", "关闭")
REFUND_KEYWORDS_EN = ("refund", "cancel", "canceled", "cancelled", "chargeback", "void")
RISK_KEYWORDS = ("风控", "冻结", "异常")
RISK_KEYWORDS_EN = ("risk", "hold", "fraud", "frozen")
# 状态缺失/查询失败的等价值（视作「无可用状态」→ caution → 走 D4）。
MISSING_VALUES = {"", "unknown", "error", "query_failed", "na", "n/a", "none", "null"}

STAGE_LABELS = {
    "typesetting": "排版前",
    "engraving": "雕刻前",
    "shipping": "发货前",
}
# 不可逆阶段：caution（无法确认未退款）也按 D4 阻断。
HARD_STAGES = {"engraving", "shipping"}

ACTION_ALLOW = "allow"
ACTION_WARN = "warn"
ACTION_BLOCK = "block"


def classify_status(status: str | None) -> str:
    """把店小秘状态原文归为 refund / caution / normal。

    - refund —— 确认退款/取消（无条件阻断）。
    - caution —— 风控/冻结，或状态缺失/查询失败（未确认安全，走 D4）。
    - normal —— 其它真实订单状态（已审核/待打单/已发货…）放行。
    """
    if status is None:
        return "caution"
    text = status.strip()
    if text.lower() in MISSING_VALUES:
        return "caution"
    low = text.lower()
    if any(k in text for k in REFUND_KEYWORDS) or any(k in low for k in REFUND_KEYWORDS_EN):
        return "refund"
    if any(k in text for k in RISK_KEYWORDS) or any(k in low for k in RISK_KEYWORDS_EN):
        return "caution"
    return "normal"


def decide(status: str | None, stage: str) -> tuple[str, str]:
    """返回 (action, reason)。action ∈ {allow, warn, block}。"""
    label = STAGE_LABELS.get(stage, stage)
    category = classify_status(status)
    shown = status if (status and status.strip()) else "缺失"
    if category == "refund":
        return ACTION_BLOCK, f"{label}：订单状态「{shown}」判定为退款/取消，阻断生产。"
    if category == "normal":
        return ACTION_ALLOW, f"{label}：订单状态「{shown}」正常，放行。"
    # caution：风控/冻结 或 状态缺失 —— 按 D4 分阶段。
    if stage in HARD_STAGES:
        return ACTION_BLOCK, f"{label}：无法确认订单未退款（状态「{shown}」），按 D4 阻断（不可逆阶段）。"
    return ACTION_WARN, f"{label}：无法确认订单状态（「{shown}」），按 D4 仅警告、可继续。"
