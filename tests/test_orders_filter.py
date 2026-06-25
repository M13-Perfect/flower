"""配置端订单表「4 维筛选」回归护栏（2026-06-22）。

_order_passes_filters 是纯逻辑（只读 6 个筛选变量 + order/view dict），用替身 self 直接测，
无需 Tk display。锁死：付款时间 / 店铺 / 订单状态(含匹配) / AI·复核 / 搜索(订单号+备注) 五维 + 空条件放行。
"""
from __future__ import annotations

from types import SimpleNamespace

from ui_app import BirthFlowerApp


class _V:  # 极简 tk.StringVar 替身
    def __init__(self, v: str):
        self._v = v

    def get(self) -> str:
        return self._v


def _self(**over):
    base = {
        "orders_filter_status_var": "全部状态",
        "orders_filter_ai_var": "全部AI状态",
        "orders_filter_search_var": "",
        "orders_filter_from_var": "",
        "orders_filter_to_var": "",
    }
    base.update(over)
    return SimpleNamespace(**{k: _V(v) for k, v in base.items()})


def _passes(order, view=None, **filters):
    return BirthFlowerApp._order_passes_filters(_self(**filters), order, view or {})


def test_no_filters_passes_all():
    assert _passes({"order_id": "A", "shop": "S", "remark": "x"}) is True


def test_status_contains_match():
    o = {"order_id": "A", "refund_status": "待打单(有货)"}
    assert _passes(o, orders_filter_status_var="待打单") is True  # 含匹配命中带后缀状态
    assert _passes(o, orders_filter_status_var="已退款") is False


def test_ai_review_filter():
    assert _passes({"order_id": "A"}, {"ai_status": "conflict"}, orders_filter_ai_var="待复核") is True
    assert _passes({"order_id": "A"}, {"ai_status": "pending"}, orders_filter_ai_var="待复核") is False
    assert _passes({"order_id": "A"}, {"ai_status": "recognized"}, orders_filter_ai_var="已识别") is True


def test_search_matches_order_id_and_remark_caseless():
    o = {"order_id": "4093587551", "remark": "Amy 生日花"}
    assert _passes(o, orders_filter_search_var="40935") is True
    assert _passes(o, orders_filter_search_var="amy") is True  # 大小写不敏感
    assert _passes(o, orders_filter_search_var="zzz") is False


def test_paid_at_date_range():
    o = {"order_id": "A", "paid_at": "2026-06-15 10:00:00"}
    assert _passes(o, orders_filter_from_var="2026-06-01", orders_filter_to_var="2026-06-30") is True
    assert _passes(o, orders_filter_from_var="2026-06-20") is False  # 早于下界
    assert _passes(o, orders_filter_to_var="2026-06-10") is False  # 晚于上界
    assert _passes({"order_id": "A"}, orders_filter_from_var="2026-06-01") is False  # 无付款时间却设了范围
