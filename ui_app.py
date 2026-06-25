from __future__ import annotations
import ctypes
import dataclasses
import datetime
import json
import logging
import math
import os
import re
from pathlib import Path
import struct
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable, Mapping
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import customtkinter as ctk
except ImportError:  # 引导解释器（如 MSYS .venv）可能没装 ctk；容忍导入，交给 _reexec 切到 .venv-win
    ctk = None  # type: ignore[assignment]
from typing import TypeVar

import datetime_picker  # 时间选择器控件（模块级导入；ctk 缺失时类不定义，仅 GUI 期使用）
from asset_resolver import scan_flower_assets, scan_font_assets
from canvas_text_item import CanvasTextItem, FloatingTextEditor
import config_store
from config_store import (
    AIProfile,
    AppConfig,
    LayerPin,
    ProductConfig,
    active_ai_profile,
    active_product,
    has_admin_password,
    load_config,
    normalize_output_path,
    save_config,
    unique_product_id,
    verify_admin_password,
    with_added_product,
    with_admin_password,
    with_product_defaults,
    with_product_library_dirs,
    with_product_layer_pins,
    with_product_reference_fields,
)
from prompt_references import (
    DuplicateReferenceNameError,
    PromptReferenceError,
    ReferenceConflictError,
    ReferenceField,
    SYSTEM_SOURCE_LABELS,
    active_reference_fields,
    create_reference_field,
    default_prompt_template,
    field_token,
    find_template_references,
    iter_template_segments,
    reference_fields_from_legacy,
    resolve_prompt_template,
    set_reference_field_enabled,
    slash_query_at_cursor,
    soft_delete_reference_field,
    system_token,
    update_reference_field_prompt,
    rename_reference_field,
)
from generation_readiness import GenerationReadiness, build_generation_readiness
from glyph_service import (
    GlyphApplyResult,
    GlyphBindingsConfig,
    GlyphMapConfig,
    GlyphRulesConfig,
    apply_automatic_glyph_rules,
    apply_glyph_to_text_layer,
    build_glyph_catalog,
    check_runtime_dependencies,
    codepoint_to_char,
    font_uses_symbol_heart,
    normalize_codepoint,
    rebuild_render_text,
    recommended_glyph_variants,
    remove_glyph_override,
    resolve_glyph,
)
from models import (
    AIParseConfig,
    AnchoredHeartLayer,
    AutoLayoutGroupLayer,
    BirthFlowerDesign,
    Document,
    EngravingLayout,
    FlowerAsset,
    FontAsset,
    GroupLayer,
    HistoryManager,
    ImageLayer,
    ParsePromptTrace,
    TextLayer,
    ParseResult,
    add_image_layer,
    add_text_layer,
    add_universal_layer,
    auto_layout_group_layers,
    convert_group_to_auto_layout,
    delete_layer,
    duplicate_layer,
    group_layers,
    hit_test,
    move_layer,
    reparent_layer,
    resolve_auto_layout,
    ungroup_layer,
)
from providers import get_provider
from order_importer import load_order_from_file, load_order_remark_from_file, order_from_payload
from parse_pipeline import parse_orders_auto
import inbox_service_client as inbox_client
import line_icons
from order_catalog import LibraryBundle
from production import ProductionParams, resolve_chain
from gpt_parser import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_MODEL,
    parse_order_remark_with_gpt,
)
from renderer import DEBUG_VISUAL_BBOX, PreviewCache, flower_debug_bboxes, render_document_png, render_dxf, render_png, render_svg
from desktop_export import render_document_dxf, render_document_vector_svg
from text_layout import (
    measure_text_ink_bbox,
    layout_personalization_text,
    text_box_size_for_font,
    SAFE_MARGIN_X,
    SAFE_MARGIN_Y,
    ENDING_HEART_ADVANCE_RATIO,
    ENDING_HEART_GAP_RATIO,
)
from anchor_resolve import (
    compute_text_fit,
    ensure_anchored_heart_for,
    remove_anchored_heart_for,
    resolve_anchored_hearts,
)


DEFAULT_FLOWER_DIR = Path("BirthMonth flowers")
DEFAULT_FONT_SOURCE = Path("Birthmonth_font.ttf")
IMPORTABLE_FONT_SUFFIXES = {".ttf", ".otf"}
IMPORTABLE_VECTOR_SUFFIXES = {".svg"}
IMPORTABLE_BITMAP_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
IMPORTABLE_ASSET_SUFFIXES = IMPORTABLE_VECTOR_SUFFIXES | IMPORTABLE_BITMAP_SUFFIXES
SINGLE_REMARK_SUFFIXES = {".txt", ".json", ".csv"}


def collect_importable_files(
    root: Path | str, suffixes: set[str], *, recursive: bool = False
) -> tuple[list[Path], list[Path]]:
    """把「一个路径」（文件或文件夹）统一展开成 ``(受支持文件, 跳过的不支持文件)``。

    这是素材库/字体库导入的统一过滤步骤（见 ``_add_library_folder``）：
    - root 是文件：后缀命中 ``suffixes`` → ``([root], [])``，否则 ``([], [root])``；
    - root 是文件夹：遍历其中文件（``recursive=True`` 时连子目录），按后缀分流；
    - root 不存在：``([], [])``。

    后缀比较不分大小写；两个返回列表都按文件名稳定排序，便于去重与展示。
    本函数只看后缀、不读取文件内容，所以**永远不会因坏文件抛异常**。
    """
    root = Path(root)
    allowed = {suffix.casefold() for suffix in suffixes}
    if root.is_file():
        return ([root], []) if root.suffix.casefold() in allowed else ([], [root])
    if not root.is_dir():
        return [], []
    valid: list[Path] = []
    skipped: list[Path] = []
    for path in (root.rglob("*") if recursive else root.iterdir()):
        if not path.is_file():
            continue
        (valid if path.suffix.casefold() in allowed else skipped).append(path)
    valid.sort(key=lambda item: item.name.casefold())
    skipped.sort(key=lambda item: item.name.casefold())
    return valid, skipped


def _paths_equal(left: Path | str, right: Path | str) -> bool:
    """库目录去重用：尽量按规范化绝对路径比较，无法解析时回退字符串比较。"""
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return Path(left) == Path(right)
PREVIEW_ZOOM_MIN = 0.2
PREVIEW_ZOOM_MAX = 8.0
PREVIEW_ZOOM_STEP = 0.05  # 每次滚轮线性缩放 5 个百分点：上滚 +0.05，下滚 -0.05
# 画布内联编辑文字时按墨迹反推文本框用的「不封顶」上限：远大于任何画布，
# 使 text_box_size_for_font 永不 clamp、字号守恒（框随墨迹自由长大、可越界）。
UNBOUNDED_BOX_SIZE = 10_000_000.0
DB_ORDER_POLL_INTERVAL_MS = 3000  # 库驱动载单轮询间隔：每 3s 查一次「最旧未删订单」，第一条变了才覆盖订单信息框
RULER_THICKNESS = 28
RULER_TICK_COLOR = "#b7bec8"
RULER_TEXT_COLOR = "#4b5563"
RULER_GUIDE_COLOR = "#3a7afe"
# 三态大小写切换:点击循环 默认→大写→小写;影响"识别内容"的输出大小写。
TEXT_CASE_ORDER = ("default", "upper", "lower")
TEXT_CASE_LABELS = {"default": "默认", "upper": "大写", "lower": "小写"}
SERVICES_API_DIR = Path(__file__).resolve().parent / "services" / "api"

# Packet 1 回滚开关：默认走非模态属性栏 overlay；置 0（或环境变量 INSPECTOR_OVERLAY=0）
# 退回旧 grab_set 模态对话框（已去掉 grab_set，仍可作回滚路径）。
INSPECTOR_OVERLAY = os.environ.get("INSPECTOR_OVERLAY", "1").strip().lower() not in {"0", "false", "off", "no"}

# 深色工作台配色（CustomTkinter 迁移，阶段1）。画板本身保持浅色（代表浅色木料，
# 雕刻预览是深灰折线 + 黑墨字），故 preview_canvas 仍用白底，不读这里的 panel 色。
APP_COLORS = {
    "background": "#1b1b1b",
    "panel": "#242424",
    "border": "#3a3a3a",
    "text": "#e9e9e9",
    "muted": "#9aa0a6",
    "warning": "#e0b04a",
    "accent": "#3a7afe",
    "accent_soft": "#26354f",
    "input": "#2b2b2b",
}
# 全局深色外观（CustomTkinter）；模块导入即设定，App 与离线冒烟脚本都生效。
if ctk is not None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
# 产品切换列（方案2）收起/展开两种宽度（像素）。
PRODUCT_RAIL_COLLAPSED_WIDTH = 48
PRODUCT_RAIL_EXPANDED_WIDTH = 168
# 主窗口最小尺寸；产品列外推时用常量而非 root.minsize() 读回（ctk.CTk 的无参 minsize 会抛 TypeError）。
MIN_WINDOW_WIDTH = 760
MIN_WINDOW_HEIGHT = 560

# ===== 三端视图（2026-06-19 拍板：入口选端，无账号）=====
# 把原本挤在一个功能区里的卡片，按角色拆成三端；启动选端、顶部可切端。共享画布与解析逻辑不变。
# 这是对 2026-06-17「单视图 + 仅提示词配置上锁」的演进：端分离取代单把锁做主隔离（密码门日后可加）。
VIEW_OPERATOR = "operator"          # 操作员端：日常量产（粘单/解析/画布/生成 + 解析可观测①③）
VIEW_OPERATOR_CONFIG = "operator_config"  # 操作员配置端：产线配置（资源库等，非 IP）
VIEW_ADMIN = "admin"                # 管理员端：识别规则·IP（提示词配置 + 解析可观测②提示词全文）
VIEW_ORDER = (VIEW_OPERATOR, VIEW_OPERATOR_CONFIG, VIEW_ADMIN)
VIEW_LABELS = {
    VIEW_OPERATOR: "操作员端",
    VIEW_OPERATOR_CONFIG: "操作员配置端",
    VIEW_ADMIN: "管理员端",
}
# ===== 选端页（门厅）专属皮肤：B「精炼深空」+ C 门口状态条 =====
# 启动选端遮罩页用这套独立深色「门厅」配色：比 App 内部 APP_COLORS 更黑，用青/蓝/琥珀给三端做色编码；
# 进入某端后回到 App 现有深色（门厅 vs 内部的有意色差）。图标走 line_icons（Tabler/MIT，cairosvg 渲染）。
ENTRY_COLORS = {
    "bg": "#101218",
    "card": "#171a22",
    "card_hover": "#1b1f29",
    "border": "#232734",
    "text": "#eef0f6",
    "muted": "#8b91a0",
    "dim": "#5a6070",
    "teal": "#2fd4a8",
    "blue": "#7aa2ff",
    "amber": "#e3b34a",
    "green": "#34d399",
    "danger": "#e88a84",
}


def _blend_hex(fg: str, bg: str, alpha: float) -> str:
    """把 fg 按 alpha 压在不透明 bg 上，返回等效不透明 hex（Tk widget 无真透明度，用预混兜底；底色纯平时像素级一致）。"""
    fr, fgc, fb = int(fg[1:3], 16), int(fg[3:5], 16), int(fg[5:7], 16)
    br, bgc, bb = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
    r = round(fr * alpha + br * (1 - alpha))
    g = round(fgc * alpha + bgc * (1 - alpha))
    b = round(fb * alpha + bb * (1 - alpha))
    return f"#{r:02x}{g:02x}{b:02x}"


# 三端 →（图标名, 强调色, 门厅短标题, 一句话描述）。操作员端=hero 大卡，其余两端并排小卡。
ENTRY_ROLE_META = {
    VIEW_OPERATOR: ("wand", "#2fd4a8", "操作员端", "粘单 · 解析 · 排版 · 生成 —— 日常量产主台"),
    VIEW_OPERATOR_CONFIG: ("gauge", "#7aa2ff", "配置端", "抓取调度 · 订单监控"),
    VIEW_ADMIN: ("adjustments", "#e3b34a", "管理员端", "AI 识别规则 · 需密码"),
}
# 每端展示哪些功能区卡片、按什么顺序（卡片 key 见 _build_function_panel 的 self._function_cards）。
# 中心区按端切换（_apply_view）：operator/admin 显示「实时画板」编辑器；operator_config 显示「实时订单表」
#   （2026-06-19 改：配置端不编辑、只监控调度，故中间换成订单表，不挂 production/画布）。
# 「画布 + 图层面板 production」只对 operator/admin 两端开放（它俩共享同一编辑器，能力零差异）。
# 订单信息/解析结果在 operator 与 admin 两端都挂：管理员调规则需「粘单→看②提示词→看③结果」闭环。
# 输出（输出设置 + 生成）在 operator 与 admin 两端都挂：管理员调规则后要能直接生成验证端到端。
_VIEW_CARD_ORDER = {
    VIEW_OPERATOR: ("order", "result", "production", "output"),
    VIEW_OPERATOR_CONFIG: ("fetch", "library"),
    VIEW_ADMIN: ("order", "result", "production", "fields", "background", "prompt_obs", "output"),
}


def view_cards_for_role(role: str) -> list[str]:
    """返回某端要展示的功能区卡片 key（有序）。未知端回退操作员端。纯函数，便于单测端↔卡片映射。"""
    return list(_VIEW_CARD_ORDER.get(role, _VIEW_CARD_ORDER[VIEW_OPERATOR]))


# 内部处理状态机（本地 SQLite，status 字段）→ 中文标签：仅在订单详情里展示（非订单表主状态列）。
# 注意：订单表「状态」列显示的是店小秘订单状态（refund_status 原文），不是这个内部状态——见 shop_status_style。
ORDER_STATUS_STYLE = {
    "RECEIVED": ("已抓取", "#2c3036", "#9aa4ae"),
    "WRITTEN_TO_INBOX": ("已入收件夹", "#22324a", "#7fa6e6"),
    "QUEUED_FOR_BATCH": ("待批量", "#22324a", "#7fa6e6"),
    "DONE": ("已完成", "#1f3d2c", "#7ed4a0"),
    "CANNOT_AUTOGEN": ("人工审核", "#3d3220", "#e7b85c"),
    "WRITE_FAILED": ("写入失败", "#3d2422", "#e88a84"),
}

# 店小秘订单状态（refund_status 原文，如 已审核/已发货/待打单(有货)/已退款/已忽略/风控中）上色用关键词。
# 与 inbox-service refund_gate 的分类口径一致（退款/取消=拦截、风控=警示），但此处只管显示着色。
_SHOP_REFUND_KW_CN = ("退款", "退货", "已取消", "取消", "拒收", "拒签", "关闭")
_SHOP_REFUND_KW_EN = ("refund", "cancel", "chargeback", "void")
_SHOP_RISK_KW_CN = ("风控", "冻结", "异常")
_SHOP_RISK_KW_EN = ("risk", "hold", "fraud", "frozen")


def shop_status_style(text: str | None) -> tuple[str, str, str]:
    """店小秘订单状态原文 → (显示文本, 药丸底色, 字色)。纯函数，便于单测。

    退款/取消→红（生产拦截）；风控/冻结→黄（警示）；已忽略/未抓到→灰；其它真实状态（已审核/已发货/待打单）→绿。
    """
    raw = (text or "").strip()
    if not raw:
        return ("未抓取", "#2c3036", "#9aa4ae")
    low = raw.lower()
    if any(k in raw for k in _SHOP_REFUND_KW_CN) or any(k in low for k in _SHOP_REFUND_KW_EN):
        return (raw, "#3d2422", "#e88a84")
    if any(k in raw for k in _SHOP_RISK_KW_CN) or any(k in low for k in _SHOP_RISK_KW_EN):
        return (raw, "#3d3220", "#e7b85c")
    if "已忽略" in raw:
        return (raw, "#2c3036", "#9aa4ae")
    return (raw, "#1f3d2c", "#7ed4a0")


def mark_status_style(mark_jobs: list[dict] | None) -> tuple[str, str, str]:
    """标记回写任务摘要(mark_jobs=[{action,status}]) → (显示文本, 药丸底色, 字色)。配置端「标签」列用（纯函数可测）。

    优先反映 AI已处理（生成后回写）：done→绿✓ / pending→蓝(待写) / failed→红。
    其次 AI未识别（抓单回写）：done→紫 / pending→蓝(待写) / failed→红。两者皆无→灰 —。
    """
    by: dict[str, str] = {}
    for job in mark_jobs or []:
        action = job.get("action")
        if action:
            by[action] = job.get("status") or ""
    done = by.get("mark_done")
    if done == "done":
        return ("AI已处理 ✓", "#1f3d2c", "#7ed4a0")
    if done == "pending":
        return ("AI已处理·待写", "#22323d", "#74c7ec")
    if done == "failed":
        return ("AI已处理·失败", "#3d2422", "#e88a84")
    unrec = by.get("mark_unrecognized")
    if unrec == "done":
        return ("AI未识别", "#332a40", "#c89be8")
    if unrec == "pending":
        return ("AI未识别·待写", "#22323d", "#74c7ec")
    if unrec == "failed":
        return ("AI未识别·失败", "#3d2422", "#e88a84")
    return ("—", "#2c3036", "#9aa4ae")


def ai_status_style(ai_status: str | None) -> tuple[str, str, str] | None:
    """AI 识别状态（DB 权威）→ (标签, 底色, 字色)；仅对**需醒目提示**的态返回，否则 None（回退 mark_status_style）。

    - conflict（复核）：订单 AI 标记与库内状态冲突（如新单已带「AI已处理」），需人工裁决 → 琥珀，最优先显示。
    - locked（人工锁定）：保留态，本期无触发，预留显示。
    其余（pending/recognized）回 None，由 mark_status_style 显示「AI未识别/AI已处理 + 待写/已写/失败」写状态细节。
    """
    if ai_status == "conflict":
        return ("复核", "#3d3220", "#e8c06a")
    if ai_status == "locked":
        return ("人工锁定", "#332a40", "#c89be8")
    return None


def _short_dt(iso: str | None) -> str:
    """ISO 时间串 `2026-06-19T02:25:00+00:00` → 紧凑 `06-19 02:25`；空/异常回退原值或 —。"""
    if not iso:
        return "—"
    try:
        date, _sep, rest = str(iso).partition("T")
        return f"{date[5:]} {rest[:5]}".strip() or str(iso)
    except Exception:
        return str(iso)


def target_box_piece_count(order: dict) -> int:
    """库订单需雕刻的「件数」= 各目标盒子行 quantity 之和（每行至少计 1 件）。

    其他商品（is_target_box=False，如赠品/卡片）不雕刻、不计；items 缺失 → 0（未知，按单件处理）。
    >1 时表示一单多件，文件名需加「-k」后缀（见 _with_piece_suffix），避免逐件生成互相覆盖。
    """
    total = 0
    for it in order.get("items") or []:
        if it.get("is_target_box", True):
            total += max(int(it.get("quantity") or 0), 1)
    return total


def order_row_view(order: dict) -> dict:
    """把 inbox-service 的 order dict 压成订单表一行（纯函数，便于单测）。

    状态列=**店小秘订单状态**（refund_status 原文，上色见 shop_status_style）——这是操作员关心的"能否继续生产"。
    内部处理状态机（status: 已入收件夹/人工审核/已完成…）只进详情，不占订单表主状态列。
    件数=各行 quantity 之和（§9.4；items 空=扩展暂未抓详情页 → 0 表未知，UI 显 —）；
    其他商品=存在 is_target_box=False 的行（§8.3）；付款时间优先 paid_at、回退 received_at。
    """
    items = order.get("items") or []
    qty = sum(int(it.get("quantity") or 0) for it in items)
    has_other = any(not it.get("is_target_box", True) for it in items)
    shop = (order.get("refund_status") or "").strip()
    label, bg, fg = shop_status_style(shop)
    internal = order.get("status") or ""
    internal_label = ORDER_STATUS_STYLE.get(internal, (internal or "—",))[0]
    # AI 权威态优先：conflict/locked 醒目显示并覆盖 mark 写状态；其余回退 mark_status_style（写状态细节）。
    ai_status = order.get("ai_status") or "pending"
    ai_style = ai_status_style(ai_status)
    if ai_style is not None:
        mark_label, mark_bg, mark_fg = ai_style
    else:
        mark_label, mark_bg, mark_fg = mark_status_style(order.get("mark_jobs"))
        if mark_label == "—":
            # 无打标历史时用 AI 权威态兜底：避免 recognized/pending 都退化成「—」（ai_status 才是真相，
            # 尤其 reconcile 建的 pending 桩单还没 mark 任务）。有打标历史则保留其「待写/已写/失败」细节。
            if ai_status == "recognized":
                mark_label, mark_bg, mark_fg = ("AI已处理", "#1f3d2c", "#7ed4a0")
            else:  # pending（默认态）
                mark_label, mark_bg, mark_fg = ("待识别", "#2c3036", "#9aa4ae")
    return {
        "order_id": order.get("order_id") or "—",
        "paid_at": _short_dt(order.get("paid_at") or order.get("received_at")),
        "status_label": label,           # = 店小秘订单状态（原"退款"列内容，现升为主状态）
        "status_bg": bg,
        "status_fg": fg,
        "mark_label": mark_label,        # = AI 权威态/标记回写状态（复核/人工锁定 优先；否则 AI未识别/AI已处理+写状态）
        "mark_bg": mark_bg,
        "mark_fg": mark_fg,
        "ai_status": ai_status,          # DB 权威 AI 识别状态（pending/recognized/conflict/locked）
        "needs_review": ai_status == "conflict",  # 复核冲突：配置端「只看复核」筛选 + 整行琥珀
        "quantity": qty,
        "shop_status": shop,             # 店小秘状态原文（详情用）
        "internal_status": internal,     # 内部处理状态原文（详情用）
        "internal_label": internal_label,  # 内部处理状态中文（详情用）
        "has_other_products": has_other,
    }


GLYPH_HELP_TEXT = (
    "Font 2 已内置 a-z 26 个结尾字形：a=U+E068，z=U+E081，中间按字母顺序连续递增。\n\n"
    "默认模式 replace_last_letter 会用配置的 PUA 字形替换最后一个英文字母，例如 Jazmin -> Jazmi + n.005。\n\n"
    "人工绑定：编辑 -> 管理字形绑定，选择 Font 2，筛选 PUA only；单个绑定时选择映射字母、"
    "输入 U+E068 这类 codepoint，再点绑定到映射字母。\n\n"
    "批量绑定：按 a-z 顺序粘贴 26 个 PUA 字符，再点按 a-z 绑定。\n\n"
    "按位置替换只影响当前订单；映射绑定会保存到 glyph_maps/glyph_maps.json。\n\n"
    "SVG 和 DXF 当前仍依赖字体文件显示 PUA 字符，换环境可能显示异常。"
)


def product_initial(name: str) -> str:
    """产品收起时显示的单字图标：取首个非空字符，无则问号。"""
    text = (name or "").strip()
    return text[0].upper() if text else "?"


def _coerce_int(value: object, default: int) -> int:
    """把库标签里的 month/flower/index 容错转 int；缺失或非法回落 default。"""
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return result or default


def parse_missing_field_hints(result) -> list[tuple[str, str]]:
    """从解析结果推断「需人工确认」的字段 + 操作提示（解析失败弹窗用，纯函数可测）。

    判据=该字段为 None/空（自动识别没确定）；返回 (字段名, 一句话操作提示) 列表。
    """
    hints: list[tuple[str, str]] = []
    if not str(getattr(result, "text", "") or "").strip():
        hints.append(("内容", "未识别刻字内容 → 手填内容"))
    if getattr(result, "month", None) is None:
        hints.append(("月份", "未识别出生花月份 → 手选素材月份"))
    if getattr(result, "font", None) is None:
        hints.append(("字体", "未识别字体编号 → 手选字体"))
    if getattr(result, "flower", None) is None:
        hints.append(("花材", "未识别花材序号 → 手选素材"))
    return hints


def product_rail_items(config: "AppConfig") -> list[dict[str, object]]:
    """产品切换列的展示数据（纯函数，便于单测，不依赖 Tkinter）。"""
    active_id = active_product(config).id
    items: list[dict[str, object]] = []
    for product in config.products:
        items.append(
            {
                "id": product.id,
                "name": product.name,
                "active": product.id == active_id,
                "initial": product_initial(product.name),
            }
        )
    return items
T = TypeVar("T")
LOGGER = logging.getLogger(__name__)


def _attach_tooltip(widget: tk.Widget, text: str) -> None:
    """给收起态的产品图标加悬浮提示，显示完整产品名（轻量实现，无第三方依赖）。"""
    state: dict[str, tk.Toplevel | None] = {"win": None}

    def show(_event: object = None) -> None:
        if state["win"] is not None or not text:
            return
        x = widget.winfo_rootx() + widget.winfo_width() + 6
        y = widget.winfo_rooty()
        win = tk.Toplevel(widget)
        win.wm_overrideredirect(True)
        win.wm_geometry(f"+{x}+{y}")
        tk.Label(win, text=text, bg=APP_COLORS["text"], fg="#ffffff", padx=6, pady=2).pack()
        state["win"] = win

    def hide(_event: object = None) -> None:
        win = state["win"]
        if win is not None:
            win.destroy()
            state["win"] = None

    widget.bind("<Enter>", show)
    widget.bind("<Leave>", hide)
    widget.bind("<Destroy>", hide)


def _enable_dark_titlebar(window: tk.Misc) -> None:
    """Windows 10/11：把原生标题栏改成深色（DWM immersive dark mode）。非 Windows 或失败静默跳过。"""
    try:
        import ctypes

        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20（Win10 20H1+ / Win11）；旧版本用 19。
        for attribute in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            ) == 0:
                break
        # 属性已设但标题栏需重绘才生效：SetWindowPos(FRAMECHANGED) 对已显示的复杂窗不一定触发，
        # 再用 1px 几何微调兜底强制重绘（实测复杂对话框靠这个才真正变深）。
        flags = 0x0001 | 0x0002 | 0x0004 | 0x0020  # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, flags)
        window.update_idletasks()
        w, h = window.winfo_width(), window.winfo_height()
        if w > 1 and h > 1:
            window.geometry(f"{w + 1}x{h}")
            window.update_idletasks()
            window.geometry(f"{w}x{h}")
    except Exception:
        pass


def ensure_services_api_import_path() -> Path:
    if not SERVICES_API_DIR.is_dir():
        raise RuntimeError(f"services/api not found: {SERVICES_API_DIR}")
    api_path = str(SERVICES_API_DIR)
    if api_path not in sys.path:
        sys.path.insert(0, api_path)
    return SERVICES_API_DIR


def import_dianxiaomi_xlsx_batch(path: Path | str, layout: dict | None = None) -> object:
    ensure_services_api_import_path()
    from app.domain.orders.batch_generate import generate_batch
    from app.domain.orders.batch_import import import_orders
    from app.domain.orders.batch_store import save_batch

    batch = import_orders(Path(path), adapter_name="dianxiaomi-xlsx")
    save_batch(batch)
    # layout(桌面 layout_defaults)非空时,批量按桌面布局产出,与单单一致(单一布局来源)。
    return generate_batch(batch.batch_id, layout=layout)


# 当前产品线唯一模板;多产品后改为按当前模板选择。
PHYSICAL_TEMPLATE_ID = "birth-flower-card"

def load_template_physical_size() -> object:
    """物理尺寸的唯一数据源是模板文件;UI 只读写它,禁止本地另存副本。"""
    ensure_services_api_import_path()
    from app.domain.templates.physical import get_physical_size

    return get_physical_size(PHYSICAL_TEMPLATE_ID)


def save_template_physical_size(width_mm: float, height_mm: float | None) -> object:
    ensure_services_api_import_path()
    from app.domain.templates.physical import update_physical_size

    return update_physical_size(PHYSICAL_TEMPLATE_ID, width_mm, height_mm)


def summarize_xlsx_batch_result(result: object) -> tuple[int, int, int, Path]:
    items = list(getattr(result, "items", []))
    total = len(items)
    manual = sum(
        1
        for item in items
        if bool(getattr(item, "needs_manual_review", False))
        or str(getattr(item, "status", "")) in {"BLOCKED", "NEEDS_REVIEW", "FAILED"}
    )
    success = sum(
        1
        for item in items
        if str(getattr(item, "status", "")) == "EXPORTED"
        and not bool(getattr(item, "needs_manual_review", False))
    )
    return total, success, manual, Path(getattr(result, "report_path"))


def show_xlsx_batch_import_summary(root: tk.Misc, result: object) -> None:
    total, success, manual, report_path = summarize_xlsx_batch_result(result)
    dialog = ctk.CTkToplevel(root)
    dialog.after(60, lambda: _enable_dark_titlebar(dialog))
    dialog.title("批量导入完成")
    dialog.resizable(False, False)
    dialog.transient(root)

    frame = ttk.Frame(dialog, padding=16)
    frame.grid(row=0, column=0, sticky="nsew")
    ttk.Label(frame, text=f"总数：{total}").grid(row=0, column=0, sticky="w")
    ttk.Label(frame, text=f"成功：{success}").grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Label(frame, text=f"需人工核验：{manual}").grid(row=2, column=0, sticky="w", pady=(6, 0))
    ttk.Label(frame, text=f"报告：{report_path}").grid(row=3, column=0, sticky="w", pady=(10, 0))

    button_row = ttk.Frame(frame)
    button_row.grid(row=4, column=0, sticky="e", pady=(14, 0))
    ttk.Button(button_row, text="打开报告", command=lambda: open_report_file(report_path)).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(button_row, text="关闭", command=dialog.destroy).grid(row=0, column=1)


def open_report_file(path: Path | str) -> None:
    report_path = Path(path)
    if sys.platform.startswith("win"):
        os.startfile(str(report_path))  # type: ignore[attr-defined]
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, str(report_path)])


def batch_import_error_message(exc: Exception) -> str:
    message = str(getattr(exc, "message", "") or exc)
    code = getattr(exc, "code", "")
    if code:
        return f"{code}: {message}"
    return message


def run_background(
    root,
    work: Callable[[], T],
    on_success: Callable[[T], None],
    on_error: Callable[[Exception], None],
) -> threading.Thread:
    """耗时任务放到后台线程，所有 Tk UI 更新都通过 root.after 回到主线程。"""

    def runner() -> None:
        try:
            result = work()
        except Exception as exc:
            root.after(0, lambda exc=exc: on_error(exc))
        else:
            root.after(0, lambda result=result: on_success(result))

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    return thread


def build_design_from_values(
    text: str,
    month: str,
    font: str,
    flower: str,
    flower_asset_path: str | Path | None = None,
    font_path: str | Path | None = None,
    flower_name: str = "",
    layout: EngravingLayout | None = None,
    personalization_type: str = "unknown",
    glyph_overrides: dict[int, dict[str, object]] | None = None,
) -> BirthFlowerDesign:
    """把 UI 中人工确认后的字段转换为最终生成参数。"""
    clean_text = text.strip()
    if not clean_text:
        raise ValueError("文字不能为空")

    try:
        month_number = int(month)
    except ValueError as exc:
        raise ValueError("月份必须是 1-12") from exc
    try:
        font_number = int(font)
    except ValueError as exc:
        raise ValueError("font 必须是 1-4") from exc
    try:
        flower_number = int(flower)
    except ValueError as exc:
        raise ValueError("flower 必须是 1-2") from exc

    if month_number < 1 or month_number > 12:
        raise ValueError("月份必须是 1-12")
    if font_number < 1 or (font_number > 4 and not font_path):
        raise ValueError("font 必须是 1-4，或选择一个实际字体文件")
    if flower_number < 1 or (flower_number > 2 and not flower_asset_path):
        raise ValueError("flower 必须是 1-2，或选择一个实际素材文件")
    return BirthFlowerDesign(
        text=clean_text,
        month=month_number,
        font=font_number,
        flower=flower_number,
        flower_asset_path=Path(flower_asset_path) if flower_asset_path else None,
        font_path=Path(font_path) if font_path else None,
        flower_name=flower_name,
        layout=layout or EngravingLayout(),
        personalization_type=personalization_type,
        glyph_overrides=glyph_overrides or {},
    )


def build_readiness_parse_result_from_values(
    text: str,
    font: str,
    flower_asset_path: str | Path | None = None,
    font_path: str | Path | None = None,
    personalization_type: str = "unknown",
    flower_name: str = "",
) -> ParseResult:
    clean_text = text.strip()
    parse_warnings: list[str] = []
    asset_warnings: list[str] = []

    font_number = _readiness_int(font)
    if not clean_text:
        parse_warnings.append("Missing personalization")
    if font_number is None or font_number < 1:
        parse_warnings.append("Invalid font design")
        font_number = None

    selected_flower_asset = _existing_asset_path(flower_asset_path)
    selected_font_asset = _existing_asset_path(font_path)
    if selected_flower_asset is None:
        asset_warnings.append("Missing flower asset")
    if font_number is not None and selected_font_asset is None:
        asset_warnings.append("Missing font asset")

    clean_flower_name = (flower_name or "").strip()
    has_flower = bool(selected_flower_asset or clean_flower_name)
    parse_confidence = _manual_parse_confidence(clean_text, font_number, has_flower, parse_warnings)
    asset_confidence = _manual_asset_confidence(selected_flower_asset, selected_font_asset, asset_warnings)
    return ParseResult(
        text=clean_text,
        font=font_number,
        flower_name=clean_flower_name or None,
        warnings=[*parse_warnings, *asset_warnings],
        confidence=parse_confidence,
        font_design=f"Font {font_number}" if font_number is not None else None,
        personalization_raw=clean_text or None,
        personalization_type=personalization_type or "unknown",
        selected_flower_asset=selected_flower_asset,
        selected_font_asset=selected_font_asset,
        parse_confidence=parse_confidence,
        asset_confidence=asset_confidence,
    )


def _readiness_int(value: str) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _existing_asset_path(value: str | Path | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    return str(path) if path.exists() else None


def _manual_parse_confidence(
    text: str,
    font: int | None,
    has_flower: bool,
    warnings: list[str],
) -> float:
    score = 1.0
    if not has_flower:
        score -= 0.35
    if font is None:
        score -= 0.25
    if not text:
        score -= 0.30
    if warnings:
        score = min(score, 0.99)
    return round(max(0.0, min(1.0, score)), 2)


def _manual_asset_confidence(
    selected_flower_asset: str | None,
    selected_font_asset: str | None,
    warnings: list[str],
) -> float:
    score = 1.0
    if selected_flower_asset is None:
        score -= 0.45
    if selected_font_asset is None:
        score -= 0.35
    if warnings:
        score = min(score, 0.99)
    return round(max(0.0, min(1.0, score)), 2)


def dxf_path_for_svg(svg_path: Path | str) -> Path:
    return Path(svg_path).with_suffix(".dxf")


def format_readiness_summary(readiness: GenerationReadiness) -> str:
    return (
        f"{readiness.status}: "
        f"parse {readiness.parse_confidence:.2f} | "
        f"asset {readiness.asset_confidence:.2f} | "
        f"layout {readiness.layout_confidence:.2f} | "
        f"overall {readiness.overall_confidence:.2f}"
    )


def format_glyph_detail(result: GlyphApplyResult | None) -> dict[str, str]:
    if result is None:
        return {
            "status": "未启用",
            "letter": "-",
            "codepoint": "-",
            "apply_mode": "-",
            "reason": "未识别",
        }
    status_map = {"none": "未启用", "auto": "自动", "manual": "人工"}
    mode_map = {"replace_last_letter": "替换最后字母", "append_suffix": "追加后缀", "manual_per_character": "按位置手动替换"}
    return {
        "status": status_map.get(result.glyph_source, "未启用"),
        "letter": result.source_letter or "-",
        "codepoint": result.glyph_codepoint or "-",
        "apply_mode": mode_map.get(result.apply_mode, result.apply_mode or "-"),
        "reason": result.reason or ("需要人工确认" if result.needs_review else "-"),
    }


def _unmapped_glyph_override_labels(glyph_overrides: dict[int, dict[str, object]]) -> list[str]:
    return [
        f"{index}: {override.get('glyph_name')} glyph_id={override.get('glyph_id')}"
        for index, override in sorted((glyph_overrides or {}).items())
        if not override.get("codepoint")
    ]


def format_font_asset_label(asset: FontAsset) -> str:
    design = asset.font_design or f"Font {asset.index}"
    size = asset.file_size or _safe_file_size(asset.path)
    size_text = _format_file_size(size)
    # 末尾装饰按真实形态区分：Font 4 是独立爱心 SVG（无字形映射），其余带装饰的是字体内末尾字形。
    if asset.has_ending_glyphs:
        ending = "末尾爱心" if font_uses_symbol_heart(design) else "末尾字形"
    else:
        ending = "常规"
    return f"{design} - {asset.name} - {asset.path.name} - {size_text} - {ending}"


def output_path_for_format(base_path: Path | str, output_format: str) -> Path:
    clean_format = output_format.strip().casefold()
    if clean_format not in {"png", "svg", "dxf"}:
        raise ValueError(f"不支持的输出格式：{output_format}")
    return Path(base_path).with_suffix(f".{clean_format}")


# Windows 非法文件名字符（含控制符）；保留设备名命中时加下划线避让。
_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_FILENAME_STEMS = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def sanitize_filename_stem(name: str | None) -> str:
    """把用户填写 / 订单号清成安全的文件名主干（不含扩展名）。

    去掉非法字符与首尾空格、点（Windows 不允许结尾点/空格），命中保留设备名时前缀下划线。
    清成空串则返回 ''，由调用方按优先级回退。
    """
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("", str(name or "")).strip().strip(" .").strip()
    if not cleaned:
        return ""
    if cleaned.casefold() in _RESERVED_FILENAME_STEMS:
        cleaned = f"_{cleaned}"
    return cleaned


def validate_output_formats(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    selected: list[str] = []
    for value in values:
        item = str(value).strip().casefold()
        if item in {"png", "svg", "dxf"} and item not in selected:
            selected.append(item)
    if not selected:
        raise ValueError("至少选择一种输出格式")
    return tuple(selected)


def _safe_file_size(path: Path) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def _format_file_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    return f"{size / 1024:.1f} KB"


def _default_field_defs() -> list[dict]:
    """前台「字段」区的默认提取规则（birth-flower-card）。规则在前台可编辑、按产品持久化。

    每个字段 = 一条提取规则；规则正文直接写明要填后端 schema 的哪个字段（text/month/flower/font）。
    业务规则（月→花对照表、字体编号）放这里而非写死在 gpt_parser，确保「提示词规则全在前台」。
    """
    return [
        {
            "key": "field1",
            "name": "刻字内容",
            "type": "文本",
            "instruction": (
                "填 text：取订单 Personalization 字段（要雕刻的名字 / 文字），"
                "保留大小写、标点、特殊字符（& # ! 等）；去首尾空白，"
                "并把中间连续的多个空格合并成一个空格（多余空格属无效、不影响生产，不要为此写 warning）；"
                "不要把 GiftMessage 当作 text；缺失填空串。"
            ),
        },
        {
            "key": "field2",
            "name": "出生花",
            "type": "素材",
            "instruction": (
                "填 month / flower / flower_name：订单写「月份 - 花名」（如 Dec - Narcissus）。"
                "month = 英文月份转 1-12；flower_name = 原文花名；flower = 该月第几朵(1 或 2)，按下表："
                "1月 1=Snowdrop 2=Carnation；2月 1=Violet 2=Primrose；3月 1=Daffodil 2=Cherry Blossom；"
                "4月 1=Daisy 2=Sweetpea；5月 1=Lily of the Valley 2=Hawthorn；6月 1=Rose 2=Honeysuckle；"
                "7月 1=Waterlily 2=Larkspur；8月 1=Poppy 2=Gladiolus；9月 1=Aster 2=Morning Glory；"
                "10月 1=Marigold 2=Cosmos；11月 1=Chrysanthemum 2=Peony；12月 1=Holly 2=Narcissus。"
                "拼写差异(Sweet Pea/Sweetpea、Water Lily/Waterlily、大小写)按表归一；查不到填 null。"
            ),
        },
        {
            "key": "field3",
            "name": "字体",
            "type": "字体",
            "instruction": (
                "填 font：取「Font N」的数字。Font 1=Malovely Script 常规，2=Malovely Script 末尾字形，"
                "3=AdoraBella 常规，4=AdoraBella 末尾爱心（末尾附加独立爱心符号，非字体字形）；"
                "客户写字体名 / 外观（如「Malovely」「带爱心」）可据此映射到编号；"
                "只有 1-4 有效，超出或拿不准填 null。"
            ),
        },
    ]


def build_ai_parse_config(
    profile: AIProfile,
    session_api_key: str = "",
    environ: Mapping[str, str] | None = None,
) -> AIParseConfig:
    env = environ or os.environ
    api_key = session_api_key.strip() or env.get(profile.api_key_env_var)
    return AIParseConfig(
        enabled=profile.enabled,
        prefer_ai=profile.prefer_ai,
        api_key=api_key,
        model=profile.model,
        project=env.get(profile.project_env_var),
        organization=env.get(profile.org_env_var),
        provider=profile.provider,
        base_url=profile.base_url or None,
    )


def build_ai_profile_from_settings(
    base_profile: AIProfile,
    provider: str,
    model: str,
    base_url: str,
    api_key_env_var: str,
    project_env_var: str,
    org_env_var: str,
    prefer_ai: bool,
) -> AIProfile:
    clean_provider = provider.strip().casefold() or base_profile.provider or "openai"
    default_model = DEFAULT_DEEPSEEK_MODEL if clean_provider == "deepseek" else DEFAULT_MODEL
    default_key_env = "DEEPSEEK_API_KEY" if clean_provider == "deepseek" else "OPENAI_API_KEY"
    clean_base_url = base_url.strip()
    if clean_provider == "deepseek" and not clean_base_url:
        clean_base_url = DEFAULT_DEEPSEEK_BASE_URL

    # DeepSeek 不需要 OpenAI Project/Org 路由；OpenAI 保留默认环境变量名。
    clean_project_env = project_env_var.strip()
    clean_org_env = org_env_var.strip()
    if clean_provider != "deepseek":
        clean_project_env = clean_project_env or "OPENAI_PROJECT"
        clean_org_env = clean_org_env or "OPENAI_ORG_ID"

    return AIProfile(
        name=base_profile.name,
        provider=clean_provider,
        model=model.strip() or default_model,
        base_url=clean_base_url,
        api_key_env_var=api_key_env_var.strip() or default_key_env,
        project_env_var=clean_project_env,
        org_env_var=clean_org_env,
        enabled=bool(prefer_ai),
        prefer_ai=bool(prefer_ai),
    )


def layout_from_values(values: dict[str, tk.StringVar | str]) -> EngravingLayout:
    defaults = EngravingLayout()

    def value(name: str) -> int:
        raw = values.get(name, str(getattr(defaults, name)))
        text = raw.get() if hasattr(raw, "get") else str(raw)
        try:
            number = int(float(text))
        except ValueError as exc:
            raise ValueError(f"{name} 必须是数字") from exc
        if number < 0:
            raise ValueError(f"{name} 不能小于 0")
        return number

    layout = EngravingLayout(
        canvas_width=value("canvas_width"),
        canvas_height=value("canvas_height"),
        flower_x=value("flower_x"),
        flower_y=value("flower_y"),
        flower_width=value("flower_width"),
        flower_height=value("flower_height"),
        text_x=value("text_x"),
        text_y=value("text_y"),
        text_width=value("text_width"),
        text_height=value("text_height"),
        text_size=value("text_size"),
    )
    if layout.canvas_width <= 0 or layout.canvas_height <= 0:
        raise ValueError("画布宽高必须大于 0")
    if layout.flower_width <= 0 or layout.flower_height <= 0:
        raise ValueError("花朵宽高必须大于 0")
    if layout.text_width <= 0 or layout.text_height <= 0:
        raise ValueError("文字宽高必须大于 0")
    if layout.text_size <= 0:
        raise ValueError("文字大小必须大于 0")
    return layout


def _clamp_sashes(
    fractions: tuple[float, ...],
    total: int,
    min_rail: int = PRODUCT_RAIL_COLLAPSED_WIDTH,
    min_center: int = 360,
    min_func: int = 300,
) -> tuple[int, int]:
    """把存的 2 个比例还原成 2 条 sash 的 x 像素，保证：左≥min_rail、中≥min_center、右≥min_func、x0<x1。

    约束：x0=左列宽、x1-x0=中列宽、total-x1=右列宽。当 total 够大（≥三者之和）时三约束都满足；
    窗口被拖到比 minsize 之和还小时尽力而为（中列优先让位），不抛错。
    """
    hi1 = total - min_func  # x1 上界：右列至少 min_func
    x0 = min(max(fractions[0] * total, min_rail), hi1 - min_center)  # 左列在 [min_rail, 留够中+右]
    x1 = min(max(fractions[1] * total, x0 + min_center), hi1)        # 右 sash 至少离左 sash min_center
    return int(x0), int(x1)


def _error_text(exc: BaseException) -> str:
    """领域异常友好文案（EditorError 带 .friendly），否则回落 str。"""
    return getattr(exc, "friendly", None) or str(exc) or exc.__class__.__name__


class BirthFlowerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Birth Flower MVP")
        self.root.geometry("980x960")
        self.config = load_config()
        # 方案2 产品切换列：收/展状态来自配置（默认收起），列容器在 _build_layout 创建。
        self.products_collapsed = bool(self.config.products_panel_collapsed)
        self.product_rail: ttk.Frame | None = None

        self.remark_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.month_var = tk.StringVar(value="1")
        self.font_var = tk.StringVar(value="1")
        self.flower_var = tk.StringVar(value="1")
        self.confidence_var = tk.StringVar(value="Readiness: -")
        # 三态大小写:default=不改、upper=全大写输出、lower=全小写输出。
        self.text_case_var = tk.StringVar(value="default")
        self.personalization_type_var = tk.StringVar(value="unknown")
        self.output_var = tk.StringVar(value=str(normalize_output_path(self.config.output_path)))
        self.flower_dir_var = tk.StringVar(value=str(self.config.flower_dir or DEFAULT_FLOWER_DIR))
        self.font_source_var = tk.StringVar(value=str(self.config.font_source or DEFAULT_FONT_SOURCE))
        self.flower_asset_var = tk.StringVar()
        self.font_asset_var = tk.StringVar()
        # 增量3：人工确认面板改为「素材库 + 素材 / 字体库 + 字体」选择器；月份降为只读 chip。
        # month_var/flower_var/font_var 保留为内部派生态（随选中素材/字体设置），导出/金标/批量零变化。
        self.image_library_var = tk.StringVar()
        self.font_library_var = tk.StringVar()
        self.month_chip_var = tk.StringVar(value="—")
        self._image_lib_by_label: dict[str, object] = {}
        self._font_lib_by_label: dict[str, object] = {}
        self.image_library_combo = None
        self.font_library_combo = None
        self.warning_var = tk.StringVar(value="等待解析")
        self.status_var = tk.StringVar(value="等待解析")
        self.output_format_vars = {
            "png": tk.BooleanVar(value="png" in self.config.output_formats),
            "svg": tk.BooleanVar(value="svg" in self.config.output_formats),
            "dxf": tk.BooleanVar(value="dxf" in self.config.output_formats),
        }
        # PNG 底:transparent=镂空(默认)| white=正常白底;只影响 PNG 导出。
        self.png_background_var = tk.StringVar(value=self.config.png_background)
        # === P1 字段提取引擎（前端骨架）===
        # 字段 = 一条想让 AI 从订单提取的信息：name/type/instruction + 实时值(result)。
        # type ∈ 文本/素材/字体（见 docs/.../2026-06-16-field-engine-redesign.md）。
        # 结果(result)在 P1 为占位 mock，P3 接 GPT 真填；各字段挂自己的 StringVar 以便跨重渲染保值。
        self.field_results: dict[str, str] = {"field1": "", "field2": "", "field3": ""}
        # 字段定义 = 前台可编辑的「提取规则」（默认完整规则，按产品从配置载入覆盖）。是发给 API 提示词的唯一规则来源。
        self.field_defs: list[dict] = []
        self.field_seq = 0
        self._load_field_defs_into_self()  # 设 field_defs + field_seq（默认或产品已存的编辑值）
        for _f in self.field_defs:
            self._ensure_field_vars(_f)
        self.fields_body = None  # 合并后的「字段」卡 body（一字段一卡）
        self.filename_template_var = tk.StringVar(value="")
        self.background_prompt_text = None
        self.generated_prompt_text = None
        self._slash_popup = None
        self._slash_candidates: list[dict[str, str]] = []
        self._slash_selected_index = 0
        self._slash_start_index = ""
        # 多订单识别队列：一次粘贴可含多笔订单，逐笔载入编辑器确认/生成。
        self.parsed_orders: list[ParseResult] = []
        self._parsed_order_index = 0
        self.current_order_number = ""
        self.order_queue_label = None
        self.order_prev_button = None
        self.order_next_button = None
        # 三端视图状态（2026-06-19）：启动停在操作员端，由选端遮罩页/顶部切端下拉切换。
        self.active_view = VIEW_OPERATOR
        self.active_view_var = tk.StringVar(value=VIEW_LABELS[VIEW_OPERATOR])
        self._function_cards: dict[str, ctk.CTkBaseClass] = {}  # 卡片 key → 卡片 widget（建一次，按端 grid/grid_remove）
        self._view_overlay = None          # 选端遮罩页（place 覆盖全窗）
        self._admin_gate = None            # 管理员密码门遮罩（scrim + 模态卡）
        self._admin_authed = False         # 本次运行是否已通过管理员密码（过一次后切端不再问）
        self._entry_chips = {}             # 门口状态条 chips：service/scrape/backlog → CTkLabel
        self._entry_hero_count = None      # hero 卡「待处理」数字 CTkLabel（积压数回填）
        self._view_switch_menu = None      # 顶部切端下拉
        self.parse_result_box = None       # 操作员/管理员端「③ 结构化结果」只读框
        self._last_parse_trace = None      # 最近一次解析「实际发出的提示词」（②，见 ParsePromptTrace）
        # 图层卡：真实动态行容器（单行紧凑：拖柄 + 状态 + 库/素材或字体下拉）。
        self.layers_rows_box = None
        self._layer_rows: dict[str, dict] = {}        # layer_id → 该行控件引用（增量复用，避免反复销毁 CTkOptionMenu）
        self._layers_empty_hint = None                # 无图层时的占位提示
        self._layer_row_widgets: list = []            # (row_card, layer_id)，拖动落点命中用
        self._drag_layer_id: str | None = None        # 当前拖动中的图层 id
        self._tree_drag_source_id: str | None = None
        self._tree_drag_started = False
        self._drop_indicator = None                   # 拖动时的蓝色落点指示线（place 覆盖在图层容器上）
        self._drop_insert_index: int | None = None    # 当前落点：插到第几个显示行之前
        self._render_layers_scheduled = False         # 图层行渲染 after_idle 去重标记
        self.session_api_key_var = tk.StringVar()
        self.flower_assets: list[FlowerAsset] = []
        self.font_assets: list[FontAsset] = []
        self.flower_label_map: dict[str, FlowerAsset] = {}
        self.font_label_map: dict[str, FontAsset] = {}
        # 当前产品的素材库/字体库集合，供解析把订单落到具体 material_key（见 order_catalog）。
        self.active_bundle: LibraryBundle = LibraryBundle()
        self.preview_font_family_cache: dict[Path, str] = {}
        self.preview_loaded_fonts: set[Path] = set()
        self.preview_cache = PreviewCache()
        # 保存 PhotoImage 引用，避免 Tk 垃圾回收后预览文字消失。
        self.preview_text_images: list[object] = []
        default_layout = active_product(self.config).defaults
        # 多图层文档是画布的真实数据源；旧版字段继续保留，保证订单解析和月份/字体选择兼容。
        self.document = Document(default_layout.canvas_width, default_layout.canvas_height)
        self.history_manager = HistoryManager()
        self.layers_tree: ttk.Treeview | None = None
        self._tree_text_edit: dict | None = None   # 图层行内文字编辑：{entry, layer_id}；空=无进行中编辑
        # 增量5：设置窗口里「产品素材库/字体库目录列表」编辑器（打开设置时建，保存时读回）。
        self.settings_image_listbox: tk.Listbox | None = None
        self.settings_font_listbox: tk.Listbox | None = None
        self.layer_detail_var = tk.StringVar(value="未选择图层")
        self.layer_text_var = tk.StringVar()
        self.layer_font_size_var = tk.StringVar(value=str(default_layout.text_size))
        self.layer_color_var = tk.StringVar(value="#111111")
        # 增量4：图层级生产参数（几何）编辑——选中图层时显示有效值，应用时写回 layer.production。
        self.layer_x_var = tk.StringVar()
        self.layer_y_var = tk.StringVar()
        self.layer_w_var = tk.StringVar()
        self.layer_h_var = tk.StringVar()
        self.layout_vars = {
            "canvas_width": tk.StringVar(value=str(default_layout.canvas_width)),
            "canvas_height": tk.StringVar(value=str(default_layout.canvas_height)),
            "flower_x": tk.StringVar(value=str(default_layout.flower_x)),
            "flower_y": tk.StringVar(value=str(default_layout.flower_y)),
            "flower_width": tk.StringVar(value=str(default_layout.flower_width)),
            "flower_height": tk.StringVar(value=str(default_layout.flower_height)),
            "text_x": tk.StringVar(value=str(default_layout.text_x)),
            "text_y": tk.StringVar(value=str(default_layout.text_y)),
            "text_width": tk.StringVar(value=str(default_layout.text_width)),
            "text_height": tk.StringVar(value=str(default_layout.text_height)),
            "text_size": tk.StringVar(value=str(default_layout.text_size)),
        }
        # 字体样式全局默认（新增）：独立存放，避免破坏 layout_vars 的「全 StringVar + str() 统一」处理。
        self.font_bold_var = tk.BooleanVar(value=default_layout.bold)
        self.font_underline_var = tk.BooleanVar(value=default_layout.underline)
        self.bold_strength_var = tk.StringVar(value=str(default_layout.bold_strength))
        self.letter_spacing_var = tk.StringVar(value=str(default_layout.letter_spacing))
        # 图层级字体样式（per-layer override，写在「文本属性」面板 → 应用到选中文本图层）。
        self.layer_bold_var = tk.BooleanVar(value=False)
        self.layer_underline_var = tk.BooleanVar(value=False)
        self.layer_letter_spacing_var = tk.StringVar(value="0")
        self.preview_canvas: tk.Canvas | None = None
        self.preview_ruler_corner: tk.Canvas | None = None
        self.preview_ruler_x: tk.Canvas | None = None
        self.preview_ruler_y: tk.Canvas | None = None
        self.preview_pointer: tuple[float, float] | None = None
        self.remark_text: tk.Text | None = None
        self.confirm_button: ttk.Button | None = None
        self.inline_text_entry: tk.Text | None = None
        self.inline_text_window: int | None = None
        self.inline_text_layer_id: str | None = None
        self.inline_text_original_text: str = ""
        self.inline_text_history_pushed: bool = False
        # 进入内联编辑时快照文本框几何，Esc 取消时连同文字一并还原（编辑中框会随墨迹变动）。
        self.inline_text_original_box: tuple[float, float, float, float, float, float] | None = None
        self.inline_text_render_after_id: str | None = None
        self.inline_text_is_closing = False
        self.floating_text_editor: FloatingTextEditor | None = None
        self.section_frames: dict[str, tk.Widget] = {}
        # Packet 1：非模态属性栏 overlay 状态。
        self._inspector_frame = None
        self._inspector_entries: list = []
        self._inspector_traces: list = []
        self._inspector_layer_id: str | None = None
        self._inspector_suppress_trace: bool = False
        self._drag_target: str | None = None
        self._drag_start: tuple[int, int] | None = None
        self._drag_mode: str = "move"
        self._drag_history_pushed = False
        self.selected_preview_item: str | None = None
        # 画板视图状态：默认等比适配；滚轮缩放时只改变视图，不改 Document/export 坐标。
        self.preview_zoom = 1.0
        self.preview_pan_x = 0.0
        self.preview_pan_y = 0.0
        self.preview_zoom_status_var = tk.StringVar(value=self._preview_zoom_percent_text())
        self.preview_canvas_size_var = tk.StringVar(value=self._preview_canvas_size_text(default_layout))
        # 素材下拉框的当前值先作为待添加素材保存；只有点击“添加素材”才真正创建 ImageLayer。
        self.pending_flower_asset_label: str = ""
        # 初始化、刷新列表、解析订单等程序化更新期间，不让控件事件触发业务写入。
        self._is_programmatic_update = False
        self._is_loading = True
        self.last_parse_result: ParseResult | None = None
        self.glyph_config = GlyphMapConfig.load()
        self.glyph_bindings = GlyphBindingsConfig.load()
        self.glyph_rules = GlyphRulesConfig.load()
        self.current_glyph_result: GlyphApplyResult | None = None
        self.current_manual_glyph_override: dict[str, str] | None = None
        self.current_glyph_overrides: dict[int, dict[str, object]] = {}
        self.selected_glyph_position: int | None = None
        self.runtime_dependency_status = check_runtime_dependencies()
        # 收件夹文件监听（automation 一期，2026-06-22 起对「订单信息框」停用）：订单信息改由「库驱动载单」承担
        # （见 _start_db_order_poller）。下面这些字段保留供手动导入/旧路径引用，启动不再起文件轮询。
        self._inbox_active: Path | None = None  # 旧：当前已载入的收件夹订单文件（库驱动后恒为 None）
        self._inbox_after_id: str | None = None
        self._inbox_dir: Path | None = None
        self._inbox_processed_dir: Path | None = None
        # 库驱动载单（2026-06-22）：后台每 DB_ORDER_POLL_INTERVAL_MS 轮询 inbox-service，取「库中最旧的待生成订单」
        # （未软删 + ai_status=pending＝ FIFO 队首），队首变了才覆盖订单信息框 + 文件名框；不冲掉操作员正在编辑的内容。
        # 生成成功后该单 ai_status→recognized 自动掉出队列（订单不删，留表里带「AI已处理」标），队首前进到下一单。
        self._db_order_active_id: str | None = None  # 当前已载入的库订单号（reload-on-change 守卫，避免每轮重刷同一单）
        self._db_order_after_id: str | None = None   # 库轮询的 Tk after 句柄
        self._db_order_piece_count: int = 0  # 当前库订单需雕刻件数（items[] 目标盒子和），>1 时文件名加「-k」后缀防覆盖
        # 「抓取订单」面板（操作员配置端，2026-06-19）：驱动 inbox-service 的自动抓开关 ScrapeControl。
        self.fetch_status_var: tk.StringVar | None = None
        self.scrape_from_var: tk.StringVar | None = None
        self.fetch_switch = None                                # 自动抓总开关（实时拨动，取代原开始/停止按钮）
        self.fetch_switch_var: tk.BooleanVar | None = None      # 开关勾选态（=服务真实 enabled）
        # 「自动识别」开关：与「自动抓取」并列但语义/状态完全独立。纯本地——新订单进 GUI 后是否自动 parse_remark()。
        # 默认关（见 config_store.inbox_autoparse 迁移）；用户拨动即写回 config 并立即生效，不依赖服务连接。
        self.autoparse_switch = None
        self.autoparse_switch_var: tk.BooleanVar | None = None
        # flower→inbox-service 地址：优先用 config 持久化值，空则回落客户端默认（127.0.0.1:8770）。可在抓取设置里改并存回 config。
        self._inbox_service_url = self.config.inbox_service_url or inbox_client.DEFAULT_BASE_URL
        self._scrape_connected = False                          # 最近一次探活结果
        self._scrape_control: dict | None = None               # 最近一次读到的自动抓任务租约 {enabled,authorized,scrape_from,task_id,...}
        self._scrape_probed = False                            # 是否已查过服务（进入配置端/点刷新才查，避免每次构造都探网）
        # ── 任务租约 + 心跳（P0 2026-06-22）：flower 是唯一控制面，「开始采集」= 下发任务 + 周期心跳续约；
        # 「停止」/关闭 App = 释放租约 → 扩展立即未授权（flower 一关/崩溃，租约到期，扩展自动停）。──
        self._flower_instance_id = uuid.uuid4().hex             # 本次运行的 flower 实例标识（每次启动新生成，不持久化）
        self._scrape_task_id: str | None = None                # 当前持有的采集任务 id（start 返回；停止/失效后清空）
        self._heartbeat_after_id: str | None = None            # 心跳 after 句柄
        # 「实时订单」表（阶段三，2026-06-20）：ttk.Treeview 原生虚拟化，扛 1700+ 行；iid=order_id。
        self.orders_tree = None                   # ttk.Treeview
        self._orders_data: dict[str, dict] = {}   # order_id → 原始订单 dict（双击看详情用）

        self._build_menu()
        self._build_layout()
        self._scan_assets(show_errors=False)
        self._bind_preview_updates()
        self._is_loading = False
        self._redraw_preview()
        if not self.runtime_dependency_status.ok:
            self.warning_var.set(self.runtime_dependency_status.message)
        for warning in (self.glyph_config.load_warning, self.glyph_bindings.load_warning, self.glyph_rules.load_warning):
            if warning:
                self.root.after(0, lambda warning=warning: messagebox.showwarning("字形配置", warning))
        # 启动「库驱动载单」轮询（订单信息统一由库驱动；取代旧的收件夹文件轮询对订单信息框的覆盖）。
        self._start_db_order_poller()
        self._refresh_fetch_status()  # 让「抓取订单」面板反映启动后的监听态
        # 关闭 App 时释放任务租约（P0）：否则扩展会以为还被授权，直到租约自然到期才停。
        try:
            self.root.protocol("WM_DELETE_WINDOW", self._on_app_close)
        except Exception:
            LOGGER.debug("无法绑定 WM_DELETE_WINDOW（非 Tk 根？）", exc_info=True)

    def _build_menu(self) -> None:
        # 菜单数据驱动；弹窗用原生 tk.Menu（_open_dropdown），点击落地可靠。
        # 原「导入」子菜单拍平为顶层两项，用分隔线保留分组。
        self._menus = [
            ("文件", [
                {"label": "导入备注...", "command": self.import_remark_file},
                {"label": "导入素材...", "command": self.import_asset_file},
                {"type": "separator"},
                {"label": "打开输出目录", "command": self.open_output_dir},
                {"type": "separator"},
                {"label": "设置...", "command": self.open_settings},
                {"type": "separator"},
                {"label": "退出", "command": self.root.destroy},
            ]),
            ("编辑", [
                {"label": "布局设置...", "command": self.open_layout_settings},
                {"label": "字形...", "command": self.open_glyph_panel},
            ]),
            ("查看", [
                {"label": "刷新预览", "command": self._redraw_preview},
            ]),
            ("帮助", [
                {"label": "字形使用说明", "command": self.show_glyph_help},
            ]),
        ]
        self.root.bind("<Control-comma>", lambda _event: self.open_settings())
        self.root.bind("<Delete>", lambda _event: self._delete_selected_layer())
        self.root.bind("<BackSpace>", lambda _event: self._delete_selected_layer())
        self.root.bind("<Left>", lambda _event: self._nudge_selected_layer(-1, 0))
        self.root.bind("<Right>", lambda _event: self._nudge_selected_layer(1, 0))
        self.root.bind("<Up>", lambda _event: self._nudge_selected_layer(0, -1))
        self.root.bind("<Down>", lambda _event: self._nudge_selected_layer(0, 1))
        self.root.bind("<Control-z>", self._on_undo_key)
        self.root.bind("<Control-y>", self._on_redo_key)
        self.root.bind("<Control-Shift-Z>", self._on_redo_key)

    def _build_menubar(self, parent) -> ctk.CTkFrame:
        """顶部深色菜单条：每个按钮弹出原生 tk.Menu（深色配色，见 _open_dropdown）。"""
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        for label, items in self._menus:
            button = ctk.CTkButton(
                bar,
                text=label,
                width=52,
                height=28,
                corner_radius=6,
                fg_color="transparent",
                hover_color=APP_COLORS["accent_soft"],
                text_color=APP_COLORS["text"],
            )
            button.configure(command=lambda b=button, it=items: self._open_dropdown(b, it))
            button.pack(side="left", padx=(0, 4))
        # 顶部「切端」下拉：随时在三端间切换（解析可观测②按端显隐；启动先走选端遮罩页）。
        self._view_switch_menu = ctk.CTkOptionMenu(
            bar, values=[VIEW_LABELS[r] for r in VIEW_ORDER],
            variable=self.active_view_var, width=128, command=self._on_switch_view,
            fg_color=APP_COLORS["input"], button_color=APP_COLORS["input"],
            button_hover_color=APP_COLORS["accent_soft"], text_color=APP_COLORS["text"],
        )
        self._view_switch_menu.pack(side="right", padx=(4, 0))
        ctk.CTkLabel(bar, text="切端", text_color=APP_COLORS["muted"]).pack(side="right", padx=(0, 6))
        return bar

    def _open_dropdown(self, button: tk.Widget, items: list[dict]) -> None:
        # 原生 tk.Menu + tk_popup：Tk 自带 grab 收放，点击落地可靠。
        # 不用自绘 overrideredirect 弹窗——后者在 Windows 上「按下即丢焦点 → <FocusOut> → 自毁」，
        # 菜单在 ButtonRelease 前就没了，命令永远点不到（真机插桩证实，见 AGENTS.md）。
        menu = tk.Menu(
            self.root, tearoff=0, bg=APP_COLORS["panel"], fg=APP_COLORS["text"],
            activebackground=APP_COLORS["accent"], activeforeground="#ffffff",
        )
        for item in items:
            if item.get("type") == "separator":
                menu.add_separator()
                continue
            menu.add_command(
                label=item["label"],
                command=item.get("command"),
                state="normal" if item.get("enabled", True) else "disabled",
            )
        x = button.winfo_rootx()
        y = button.winfo_rooty() + button.winfo_height() + 2
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _themed_toplevel(self) -> ctk.CTkToplevel:
        """建带深色标题栏的对话框：CTkToplevel 自带的深色标题栏不稳（实测仍白），用 DWM 兜底。"""
        window = ctk.CTkToplevel(self.root)
        # 复杂对话框 60ms 时常还没完成映射→DWM 设不上（实测仍白）；60ms 与 350ms 各补一次。
        window.after(60, lambda: _enable_dark_titlebar(window))
        window.after(350, lambda: _enable_dark_titlebar(window))
        return window

    def _add_row(self, parent, row: int, label: str, widget) -> None:
        ctk.CTkLabel(parent, text=label, anchor="w").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
        widget.grid(row=row, column=1, sticky="ew", pady=4)
        parent.columnconfigure(1, weight=1)

    def _add_path_row(self, parent, row: int, label: str, var: tk.StringVar, command) -> None:
        ctk.CTkLabel(parent, text=label, anchor="w").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
        row_frame = ctk.CTkFrame(parent, fg_color="transparent")
        row_frame.grid(row=row, column=1, sticky="ew", pady=4)
        row_frame.columnconfigure(0, weight=1)
        ctk.CTkEntry(row_frame, textvariable=var).grid(row=0, column=0, sticky="ew")
        self._btn(row_frame, "选择", command).grid(row=0, column=1, padx=(8, 0))
        parent.columnconfigure(1, weight=1)

    def _configure_styles(self) -> None:
        """深色工作台风格：CustomTkinter 负责新控件，ttk 经 clam 主题统一刷深色。"""
        bg = APP_COLORS["background"]
        panel = APP_COLORS["panel"]
        text = APP_COLORS["text"]
        field = APP_COLORS["input"]
        border = APP_COLORS["border"]
        accent = APP_COLORS["accent"]
        self.root.configure(bg=bg)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            ".",
            background=panel,
            foreground=text,
            bordercolor=border,
            fieldbackground=field,
            lightcolor=panel,
            darkcolor=panel,
        )
        style.configure("App.TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel)
        style.configure("TFrame", background=panel)
        style.configure("TLabel", background=panel, foreground=text)
        style.configure("Panel.TLabelframe", background=panel, bordercolor=border, relief="solid")
        style.configure("Panel.TLabelframe.Label", background=panel, foreground=text)
        style.configure("TLabelframe", background=panel, bordercolor=border)
        style.configure("TLabelframe.Label", background=panel, foreground=text)
        style.configure("Status.TLabel", foreground=APP_COLORS["muted"], background=panel)
        style.configure("Warning.TLabel", foreground=APP_COLORS["warning"], background=panel)

        for entry_style in ("TEntry", "TSpinbox", "TCombobox"):
            style.configure(
                entry_style,
                fieldbackground=field,
                foreground=text,
                background=field,
                bordercolor=border,
                arrowcolor=text,
                insertcolor=text,
            )
            style.map(
                entry_style,
                fieldbackground=[("readonly", field), ("disabled", panel)],
                foreground=[("disabled", APP_COLORS["muted"])],
            )

        style.configure("TButton", background=field, foreground=text, bordercolor=border, relief="flat", padding=6)
        style.map("TButton", background=[("active", APP_COLORS["accent_soft"])])
        style.configure("Primary.TButton", background=accent, foreground="#ffffff")
        style.map("Primary.TButton", background=[("active", "#5b8def")])
        style.configure("TCheckbutton", background=panel, foreground=text)
        style.map("TCheckbutton", background=[("active", panel)])
        # Radiobutton 与 Checkbutton 同源刷主题:clam 默认 hover 是纯白高亮,会盖住深色文字;
        # 把 active 背景压回 panel(取自 APP_COLORS,非硬编码),将来切主题重跑本方法即自动跟随。
        style.configure("TRadiobutton", background=panel, foreground=text)
        style.map(
            "TRadiobutton",
            background=[("active", panel)],
            foreground=[("disabled", APP_COLORS["muted"])],
        )
        style.configure("TScrollbar", background=field, troughcolor=bg, bordercolor=border, arrowcolor=text)
        # 订单表（ttk.Treeview，阶段三）深色：行/表头/选中态。状态彩色靠 tag_configure(foreground)（见 _build_orders_table_panel）。
        style.configure(
            "Treeview", background=field, fieldbackground=field, foreground=text,
            bordercolor=border, borderwidth=0, rowheight=26,
        )
        style.map("Treeview", background=[("selected", accent)], foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background=panel, foreground=APP_COLORS["muted"], relief="flat", borderwidth=0)
        style.map("Treeview.Heading", background=[("active", APP_COLORS["accent_soft"])])
        style.configure("TNotebook", background=panel, bordercolor=border)
        style.configure("TNotebook.Tab", background=field, foreground=text, padding=(10, 4))
        style.map("TNotebook.Tab", background=[("selected", panel)], foreground=[("selected", text)])

        # ttk Combobox 下拉列表用经典 Listbox，需经 option database 刷深色。
        self.root.option_add("*TCombobox*Listbox.background", field)
        self.root.option_add("*TCombobox*Listbox.foreground", text)
        self.root.option_add("*TCombobox*Listbox.selectBackground", accent)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    def _ctk_card(self, parent, title: str, *, badge: str | None = None) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
        """深色圆角卡片 + 顶部标题；返回 (card, body)，内容 grid 进 body（替代 ttk.LabelFrame）。

        配置锁已删除（2026-06-19）：IP 隔离改由三端分离承担（提示词配置归管理员端），不再有 🔒 卡。
        badge：可选右上角琥珀小标（如管理员端 IP 卡的「仅管理员 · IP」），仅作视觉提示、不锁。
        """
        card = ctk.CTkFrame(
            parent,
            corner_radius=10,
            fg_color=APP_COLORS["panel"],
            border_width=1,
            border_color=APP_COLORS["border"],
        )
        if badge:
            head = ctk.CTkFrame(card, fg_color="transparent")
            head.pack(fill="x", padx=12, pady=(8, 0))
            ctk.CTkLabel(
                head, text=title, anchor="w",
                text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=12),
            ).pack(side="left")
            ctk.CTkLabel(
                head, text=f"  {badge}  ", fg_color="#3d3220", text_color="#e7b85c",
                corner_radius=4, font=ctk.CTkFont(size=10),
            ).pack(side="right")
        else:
            ctk.CTkLabel(
                card, text=title, anchor="w",
                text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=12),
            ).pack(fill="x", padx=12, pady=(8, 0))
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(4, 10))
        body.columnconfigure(0, weight=1)
        return card, body

    def _btn(self, parent, text: str, command, *, primary: bool = False, **kwargs) -> ctk.CTkButton:
        """统一的 CTk 按钮：primary=蓝色主按钮，否则中性深色。"""
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            corner_radius=8,
            height=30,
            fg_color=APP_COLORS["accent"] if primary else APP_COLORS["input"],
            hover_color=APP_COLORS["accent_soft"],
            text_color="#ffffff" if primary else APP_COLORS["text"],
            **kwargs,
        )

    def _build_layout(self) -> None:
        self.root.geometry("1120x760")
        self.root.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self._configure_styles()

        frame = ttk.Frame(self.root, padding=8, style="App.TFrame")
        frame.pack(fill="both", expand=True)

        menubar = self._build_menubar(frame)
        menubar.pack(side="top", fill="x", pady=(0, 6))

        # 原底部「生产输出」栏已删除：格式/目录/选择并入功能区「输出设置」卡，
        # 「生成」按钮 + 状态也移入该卡（见 _build_output_settings_panel）。
        # 腾出的底部空间由 body（预览 + 功能区）自动 fill 撑满 → 画布更高、功能区更长。

        # 三列横向布局用 tk.PanedWindow：分隔条（sash）自带拖拽，三列都能拉宽缩窄，不用自己写鼠标拖动。
        # 选 tk 版而非 ttk：每 pane 的 minsize 是原生的（ttk 版只有 weight，得自己钳最小宽 = 多代码）。
        paned = tk.PanedWindow(
            frame, orient="horizontal", bg=APP_COLORS["border"],
            sashwidth=6, sashrelief="flat", bd=0, showhandle=False, opaqueresize=True,
        )
        paned.pack(fill="both", expand=True)
        self._paned = paned

        # 左列：产品切换列。宽度仍由「收/展」按钮设（_toggle_product_rail 吸附 sash），现在也能直接拖。
        self.product_rail = ctk.CTkFrame(
            paned, width=PRODUCT_RAIL_COLLAPSED_WIDTH, corner_radius=0, fg_color=APP_COLORS["panel"]
        )
        self.product_rail.pack_propagate(False)
        self._render_product_rail()

        # 中列：预览/订单两块叠在同一容器 grid，按端 grid_remove 切换（逻辑不变，父容器从 body 换成 center）。
        center = ttk.Frame(paned, style="App.TFrame")
        center.columnconfigure(0, weight=1)
        center.rowconfigure(0, weight=1)
        preview_panel = self._build_preview_panel(center)
        orders_panel = self._build_orders_table_panel(center)
        preview_panel.grid(row=0, column=0, sticky="nsew")
        orders_panel.grid(row=0, column=0, sticky="nsew")

        # 右列：功能区。CTkScrollableFrame 是 frame→canvas→scrollableframe 复合体，其真身不是 paned 的
        # 直接子节点，不能直接 add 进 PanedWindow；包一层普通 frame 当 pane，功能区 pack 满它。
        right = ttk.Frame(paned, style="App.TFrame")
        function_panel, order_panel, production_panel = self._build_function_panel(right)
        function_panel.pack(fill="both", expand=True)

        # 装三列：左/右固定不拉伸、中列吸收窗口缩放；minsize 沿用原 body 的 360/300 + 产品列收起宽。
        paned.add(self.product_rail, minsize=PRODUCT_RAIL_COLLAPSED_WIDTH, stretch="never", sticky="nsew")
        paned.add(center, minsize=360, stretch="always", sticky="nsew")
        paned.add(right, minsize=300, stretch="never", sticky="nsew")

        self._preview_panel = preview_panel
        self._orders_panel = orders_panel
        orders_panel.grid_remove()  # 默认操作员端：先藏订单表，由 _apply_center_for_view 决定
        # 还原上次拖好的列宽：须等窗口有真实宽度才能按比例放 sash，故 after_idle。
        self.root.after_idle(self._restore_pane_sashes)

        self.section_frames = {
            "order_panel": order_panel,
            "preview_panel": preview_panel,
            "orders_panel": orders_panel,
            "function_panel": function_panel,
            "production_panel": production_panel,
            "product_rail": self.product_rail,
        }
        self._apply_center_for_view(self.active_view)
        self._set_warnings(["等待解析；识别结果不会自动生成最终文件。"])
        # ctk.CTk 根窗自带深色标题栏；仅当回退到 tk.Tk（测试/缺 ctk）时用 DWM 兜底。
        if ctk is None or not isinstance(self.root, ctk.CTk):
            _enable_dark_titlebar(self.root)
        # 启动停在操作员端，先弹「选择进入」遮罩页让用户选端（无账号）。
        self._show_view_chooser()

    def _render_product_rail(self) -> None:
        """按收/展状态重建产品切换列内容（方案2，CustomTkinter 深色圆角风格）。"""
        rail = self.product_rail
        if rail is None:
            return
        for child in rail.winfo_children():
            child.destroy()
        collapsed = self.products_collapsed
        rail.configure(
            width=PRODUCT_RAIL_COLLAPSED_WIDTH if collapsed else PRODUCT_RAIL_EXPANDED_WIDTH
        )

        header = ctk.CTkFrame(rail, fg_color="transparent")
        header.pack(fill="x", padx=6, pady=(8, 6))
        ctk.CTkButton(
            header,
            # 收起→指向外(«，下次点击展开)；展开→指向内(»，下次点击收起)。
            text="«" if collapsed else "»",
            width=28,
            height=28,
            command=self._toggle_product_rail,
            fg_color="transparent",
            hover_color=APP_COLORS["accent_soft"],
            text_color=APP_COLORS["muted"],
        ).pack(side="left")
        if not collapsed:
            ctk.CTkLabel(header, text="产品", text_color=APP_COLORS["text"]).pack(side="left", padx=(6, 0))

        # 新建按钮固定底部；产品列表从上往下填充。
        ctk.CTkButton(
            rail,
            text="+" if collapsed else "+ 新建产品",
            height=30,
            command=self._open_new_product_dialog,
            fg_color="transparent",
            hover_color=APP_COLORS["accent_soft"],
            text_color=APP_COLORS["accent"],
            anchor="center" if collapsed else "w",
        ).pack(side="bottom", fill="x", padx=6, pady=8)

        for item in product_rail_items(self.config):
            self._build_product_button(rail, item, collapsed)

    def _build_product_button(self, rail: tk.Widget, item: dict[str, object], collapsed: bool) -> None:
        active = bool(item["active"])
        button = ctk.CTkButton(
            rail,
            text=str(item["initial"]) if collapsed else str(item["name"]),
            command=lambda pid=str(item["id"]): self._switch_product(pid),
            height=34,
            corner_radius=8,
            fg_color=APP_COLORS["accent"] if active else "transparent",
            hover_color=APP_COLORS["accent_soft"],
            text_color="#ffffff" if active else APP_COLORS["text"],
            anchor="center" if collapsed else "w",
        )
        button.pack(fill="x", padx=6, pady=3)
        # 右键 = 产品菜单（启用/停用/删除）。
        button.bind("<Button-3>", lambda e, pid=str(item["id"]): self._show_product_template_menu(e, pid))
        if collapsed:
            # 收起时只显示首字，用悬浮提示补全产品名。
            _attach_tooltip(button, str(item["name"]))

    def _toggle_product_rail(self) -> None:
        """收/展产品列：翻状态→存盘→重建内容→把左分隔条吸附到收起/展开宽。按钮与拖拽并存。"""
        self.products_collapsed = not self.products_collapsed
        self.config = dataclasses.replace(
            self.config, products_panel_collapsed=self.products_collapsed
        )
        save_config(self.config)
        self._render_product_rail()
        # 把左 sash 吸附到目标宽；中列吸收差值（paned 天然行为，比旧的整窗加宽更简单、与拖拽一致）。
        target = PRODUCT_RAIL_COLLAPSED_WIDTH if self.products_collapsed else PRODUCT_RAIL_EXPANDED_WIDTH
        paned = getattr(self, "_paned", None)
        if paned is not None:
            paned.update_idletasks()
            paned.sash_place(0, target, 0)

    def _restore_pane_sashes(self) -> None:
        """按上次存的比例还原 2 条分隔条位置；无存值用默认列宽。须在窗口已实化（有真实宽度）后调用。"""
        fractions = self.config.pane_sash_fractions
        paned = getattr(self, "_paned", None)
        if paned is None or len(fractions) != 2:
            return
        paned.update_idletasks()
        total = paned.winfo_width()
        if total <= 1:
            # 窗口还没真正实化，winfo_width 仍是占位的 1，再等一拍。
            # ponytail: 一次重试就够；还拿不到就放弃还原、用默认列宽
            self.root.after(50, self._restore_pane_sashes)
            return
        x0, x1 = _clamp_sashes(fractions, total)
        paned.sash_place(0, x0, 0)
        paned.sash_place(1, x1, 0)

    def _save_pane_sashes(self) -> None:
        """关窗前把 2 条分隔条位置按「占总宽比例」存盘；下次启动 _restore_pane_sashes 折算还原。"""
        paned = getattr(self, "_paned", None)
        if paned is None:
            return
        try:
            total = paned.winfo_width()
            if total <= 1:
                return
            fractions = tuple(paned.sash_coord(i)[0] / total for i in range(2))
        except Exception:
            LOGGER.debug("保存分隔条位置失败（忽略）", exc_info=True)
            return
        if fractions != tuple(self.config.pane_sash_fractions):
            self.config = dataclasses.replace(self.config, pane_sash_fractions=fractions)
            save_config(self.config)

    def _switch_product(self, product_id: str) -> None:
        """切换激活产品：持久化 + 把该产品的素材/字体库灌进扫描入口并重扫。"""
        if product_id == active_product(self.config).id:
            return
        self._persist_prompts()  # 先把当前产品的提示词存盘，再切走
        self.config = dataclasses.replace(self.config, active_product_id=product_id)
        save_config(self.config)
        product = active_product(self.config)
        # 切产品=切其素材/字体库目录；接进现有扫描入口（字段级联待 Phase 2）。
        if product.image_library_dirs:
            self.flower_dir_var.set(str(product.image_library_dirs[0]))
        if product.font_library_dirs:
            self.font_source_var.set(str(product.font_library_dirs[0]))
        self._scan_assets(show_errors=False)
        self._apply_layout_defaults(product.defaults)
        self._clear_document_history()
        self._load_prompts_into_widgets()  # 载入新产品的提示词
        self._render_product_rail()
        self._refresh_layers_panel()
        self._redraw_preview()
        self.status_var.set(f"已切换产品：{product.name}")

    def _open_new_product_dialog(self) -> None:
        """新建产品：填名称/ID + 选图像库/字体库目录，创建后切过去。"""
        window = self._themed_toplevel()
        window.title("新建产品")
        window.transient(self.root)
        frame = ctk.CTkFrame(window, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        frame.columnconfigure(1, weight=1)

        name_var = tk.StringVar()
        id_var = tk.StringVar()
        image_dir_var = tk.StringVar()
        font_dir_var = tk.StringVar()
        existing_ids = [product.id for product in self.config.products]
        auto_state = {"value": ""}

        def on_name_changed(*_args: object) -> None:
            # ID 默认跟随产品名自动生成；一旦用户手动改过 ID 就不再自动覆盖。
            if id_var.get().strip() and id_var.get() != auto_state["value"]:
                return
            auto = unique_product_id(name_var.get(), existing_ids)
            auto_state["value"] = auto
            id_var.set(auto)

        name_var.trace_add("write", on_name_changed)

        ctk.CTkLabel(frame, text="产品名", anchor="w").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 8))
        ctk.CTkEntry(frame, textvariable=name_var).grid(row=0, column=1, sticky="ew", pady=4)
        ctk.CTkLabel(frame, text="产品 ID", anchor="w").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 8))
        ctk.CTkEntry(frame, textvariable=id_var).grid(row=1, column=1, sticky="ew", pady=4)
        self._add_path_row(frame, 2, "图像库目录", image_dir_var, lambda: self._choose_dir_into(image_dir_var))
        self._add_path_row(frame, 3, "字体库目录", font_dir_var, lambda: self._choose_dir_into(font_dir_var))

        button_row = ctk.CTkFrame(frame, fg_color="transparent")
        button_row.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self._btn(button_row, "取消", window.destroy).grid(row=0, column=0, padx=(0, 8))
        self._btn(
            button_row,
            "创建",
            lambda: self._create_product_from_dialog(
                window, name_var, id_var, image_dir_var, font_dir_var,
            ),
            primary=True,
        ).grid(row=0, column=1)

    def _choose_dir_into(self, var: tk.StringVar) -> None:
        path = filedialog.askdirectory()
        if path:
            var.set(path)

    def _choose_file_into(self, var: tk.StringVar, filetypes=None) -> None:
        path = filedialog.askopenfilename(filetypes=filetypes or [("所有文件", "*.*")])
        if path:
            var.set(path)

    def _create_product_from_dialog(
        self,
        window: tk.Toplevel,
        name_var: tk.StringVar,
        id_var: tk.StringVar,
        image_dir_var: tk.StringVar,
        font_dir_var: tk.StringVar,
    ) -> None:
        name = name_var.get().strip()
        if not name:
            messagebox.showwarning("新建产品", "请填写产品名。")
            return
        existing_ids = [product.id for product in self.config.products]
        product_id = id_var.get().strip() or unique_product_id(name, existing_ids)
        if product_id in existing_ids:
            messagebox.showwarning("新建产品", f"产品 ID 已存在：{product_id}")
            return
        image_dirs = (Path(image_dir_var.get()),) if image_dir_var.get().strip() else ()
        font_dirs = (Path(font_dir_var.get()),) if font_dir_var.get().strip() else ()
        product = ProductConfig(
            id=product_id,
            name=name,
            image_library_dirs=image_dirs,
            font_library_dirs=font_dirs,
            defaults=self._active_layout_defaults(),
        )
        # 先追加（不激活）再走切换逻辑，复用切换里的重扫/重绘/持久化。
        self.config = with_added_product(self.config, product, activate=False)
        save_config(self.config)
        window.destroy()
        self._switch_product(product_id)

    # ---- 产品 右键菜单 ------------------------------------
    def _product_by_id(self, product_id: str):
        return next((p for p in self.config.products if p.id == product_id), None)

    def _show_product_template_menu(self, event, product_id: str) -> None:
        product = self._product_by_id(product_id)
        if product is None:
            return
        menu = tk.Menu(self.root, tearoff=0)
        if product.status == "active":
            menu.add_command(label="停用产品", command=lambda: self._product_set_status(product_id, "disabled"))
        else:
            menu.add_command(label="启用产品", command=lambda: self._product_set_status(product_id, "active"))
        menu.add_command(label="删除产品…", command=lambda: self._product_delete(product_id))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _product_set_status(self, product_id: str, status: str) -> None:
        self.config = config_store.with_product_status(self.config, status, product_id=product_id)
        save_config(self.config)
        self._render_product_rail()
        self.status_var.set(f"产品已{'停用' if status == 'disabled' else '启用'}。")

    def _product_delete(self, product_id: str) -> None:
        """删除产品：二次确认 → 从配置移除（不可恢复）。"""
        product = self._product_by_id(product_id)
        if product is None:
            return
        if len(self.config.products) <= 1:
            messagebox.showwarning("删除产品", "至少保留一个产品，无法删除最后一个。")
            return
        if not messagebox.askyesno("删除产品",
                                   f"确定删除产品「{product.name}」？\n此操作不可恢复。"):
            return
        remaining = tuple(p for p in self.config.products if p.id != product_id)
        new_active = self.config.active_product_id
        if new_active == product_id:
            new_active = remaining[0].id
        self.config = dataclasses.replace(self.config, products=remaining, active_product_id=new_active)
        save_config(self.config)
        self._switch_product(new_active)
        self.status_var.set(f"已删除产品「{product.name}」。")

    def _build_function_panel(self, parent):
        # CTkScrollableFrame 自带滚动，替代原来手搓的 tk.Canvas + Scrollbar。
        panel = ctk.CTkScrollableFrame(
            parent,
            width=320,
            label_text="功能区",
            corner_radius=10,
            fg_color=APP_COLORS["panel"],
            label_fg_color=APP_COLORS["panel"],
        )
        panel.columnconfigure(0, weight=1)

        # 三端视图：所有卡片建一次存进 self._function_cards（key→widget），再按当前端 grid（见 _apply_view）。
        # 卡片 key 与端归属见 _VIEW_CARD_ORDER；订单信息/解析结果在 operator 与 admin 两端共用同一 widget。
        # 图层卡在 _build_production_panel 内使用 ttk.Treeview；旧 _build_layers_panel 仅保留兼容入口。
        order_panel = self._build_order_panel(panel)
        production_panel = self._build_production_panel(panel)  # 「图层」卡，真实动态行 + 保留隐藏全局选择器联动
        self._function_panel = panel
        self._function_cards = {
            "order": order_panel,
            "result": self._build_parse_result_panel(panel),     # ③ 结构化结果只读框（解析可观测）
            "fetch": self._build_fetch_panel(panel),             # 「抓取订单」面板骨架（操作员配置端）
            "fields": self._build_fields_panel(panel),
            "background": self._build_background_prompt_panel(panel),
            "production": production_panel,
            "library": self._build_library_panel(panel),
            "prompt_obs": self._build_generate_prompt_panel(panel),  # ② 本次提示词全文（解析后自动刷新）
            "output": self._build_output_settings_panel(panel),
        }
        self._apply_view(self.active_view)
        return panel, order_panel, production_panel

    def _build_parse_result_panel(self, parent) -> ctk.CTkFrame:
        """「解析结果」卡（解析可观测 ③）：解析后只读展示本单识别出的结构化结果，异常单才走弹窗。"""
        panel, body = self._ctk_card(parent, "解析结果")
        body.columnconfigure(0, weight=1)
        self.parse_result_box = ctk.CTkTextbox(
            body, height=110, fg_color="#161616", text_color=APP_COLORS["text"],
            border_width=1, border_color=APP_COLORS["border"], wrap="word",
        )
        self.parse_result_box.grid(row=0, column=0, sticky="ew")
        self.parse_result_box.insert("1.0", "（点「解析」后显示本单识别结果）")
        self.parse_result_box.configure(state="disabled")
        return panel

    def _build_fetch_panel(self, parent) -> ctk.CTkFrame:
        """「抓取订单」面板（操作员配置端，2026-06-19）：驱动 inbox-service 的自动抓开关 `ScrapeControl`。

        拓扑：flower → inbox-service（写开关）→ 扩展（读开关去抓）。flower 只写这一个开关。
        - 自动抓取开关 = `PUT /inbox/scrape/control {enabled}`（自动抓总开关，配置端可实时拨动）。
        - 设置 = 抓取间隔 `interval_seconds` + 服务地址（本地存）。
        - 定时锁（从某付款时间重抓）= `PUT restart_from`（把游标设到该时间，扩展从此往后重抓）/ 清空。
        - 状态行 = 服务连接(/healthz) + 自动抓态(GET control) + 收件夹当前单。
        收件夹消费（轮询载单进编辑器）照常后台跑，不在本面板按钮里。
        """
        panel, body = self._ctk_card(parent, "抓取订单")
        body.columnconfigure(0, weight=1)
        self.fetch_status_var = tk.StringVar(value="状态：加载中…")
        ctk.CTkLabel(
            body, textvariable=self.fetch_status_var, anchor="w", justify="left",
            text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11), wraplength=290,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 8))

        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.grid(row=1, column=0, sticky="ew")
        btn_row.columnconfigure(2, weight=1)  # 两个开关靠左、设置/刷新靠右，中间留弹性空白
        # 自动抓总开关：单个实时开关取代原「开始/停止」两按钮——勾选态=服务真实 enabled，可直接拨动（PUT control）。
        self.fetch_switch_var = tk.BooleanVar(value=False)
        self.fetch_switch = ctk.CTkSwitch(
            btn_row, text="自动抓取", variable=self.fetch_switch_var,
            onvalue=True, offvalue=False, command=self._on_fetch_switch_toggle,
            progress_color=APP_COLORS["accent"], font=ctk.CTkFont(size=12),
        )
        self.fetch_switch.grid(row=0, column=0, sticky="w")
        # 自动识别开关：与自动抓取并列、互相独立。纯本地配置（inbox_autoparse），拨动即持久化 + 立即生效，无需服务连接。
        self.autoparse_switch_var = tk.BooleanVar(value=bool(self.config.inbox_autoparse))
        self.autoparse_switch = ctk.CTkSwitch(
            btn_row, text="自动识别", variable=self.autoparse_switch_var,
            onvalue=True, offvalue=False, command=self._on_autoparse_switch_toggle,
            progress_color=APP_COLORS["accent"], font=ctk.CTkFont(size=12),
        )
        self.autoparse_switch.grid(row=0, column=1, sticky="w", padx=(14, 0))
        self._btn(btn_row, "设置", self._open_fetch_settings, width=58).grid(row=0, column=3, padx=(0, 6))
        self._btn(btn_row, "刷新", self._refresh_scrape_status, width=58).grid(row=0, column=4)

        lock_row = ctk.CTkFrame(body, fg_color="transparent")
        lock_row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        lock_row.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            lock_row, text="定时抓取 · 重抓起点", anchor="w", text_color=APP_COLORS["warning"],
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self.scrape_from_var = tk.StringVar(value="")
        # 原手填文本框 → 日期/时间选择器（仍写回 scrape_from_var，「应用/清空」逻辑不变）。
        datetime_picker.CTkDateTimePicker(
            lock_row, self.scrape_from_var, APP_COLORS,
            toplevel_factory=self._themed_toplevel, placeholder="选择付款时间",
        ).grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self._btn(lock_row, "应用", self._on_scrape_restart_from, width=58).grid(row=1, column=1, padx=(0, 6))
        self._btn(lock_row, "清空", self._on_scrape_clear_from, width=58).grid(row=1, column=2)

        ctk.CTkLabel(
            body,
            text=(
                "自动抓取＝是否自动从店小秘抓单（总开关，配置端可实时拨动）；"
                "自动识别＝新订单进来后是否自动解析识别（默认关，仅本机生效，与自动抓取互不影响）。"
                "两者都不会自动「生成」，仍需人工点「生成」。定时抓取＝把抓取游标设到所选付款时间，从此往后重抓。"
            ),
            anchor="w", justify="left", text_color=APP_COLORS["muted"],
            font=ctk.CTkFont(size=10), wraplength=290,
        ).grid(row=3, column=0, sticky="ew", pady=(10, 0))
        # 不在构造时探网：进入操作员配置端（_apply_view）或点「刷新」才查服务，省得每次起 App 都连一次。
        self._render_fetch_status()
        return panel

    @staticmethod
    def _format_scrape_status(connected: bool, base_url: str, control: dict | None, active_name: str | None) -> str:
        """抓取面板状态文案（纯函数便于测）：服务连接 + 自动抓态 + 收件夹当前单。"""
        if not connected:
            return f"服务：未连接 {base_url}\n（请确认 inbox-service 已在该地址启动）"
        if not control:
            return f"服务：已连接 {base_url}\n自动抓：状态未知"
        on = "开" if control.get("enabled") else "关"
        # authorized = 扩展是否真被授权执行（服务端据任务租约 + 时钟算）。开关「开」但「授权 否」=
        # 任务已过期/未心跳（如 flower 异常退出后残留），此时扩展实际已停——据此提示操作员重开。
        auth = "是" if control.get("authorized") else "否"
        interval = control.get("interval_seconds")
        scrape_from = control.get("scrape_from") or "—"
        scrape_to = control.get("scrape_to") or "—"
        return (
            f"服务：已连接 {base_url}\n"
            f"自动抓：{on}（授权 {auth}）　间隔 {interval}s\n"
            f"订单范围：{scrape_from} 起 至 {scrape_to}\n"
            f"收件夹当前单：{active_name or '—'}"
        )

    @staticmethod
    def _scrape_switch_state(probed: bool, connected: bool, control: dict | None) -> tuple[bool, bool]:
        """(开关勾选态, 是否可点)。未探活/未连接/状态未知 → 不可点；已知 → 勾选=enabled。纯函数便于测。"""
        known = bool(probed and connected and control is not None)
        checked = bool(control and control.get("enabled")) if known else False
        return checked, known

    def _set_switch_state(self, *, checked: bool, clickable: bool) -> None:
        """把开关刷成目标态。variable.set 只更新视觉、不触发 command（command 仅用户点击时才发），故无递归。"""
        if getattr(self, "fetch_switch", None) is None:
            return
        if self.fetch_switch_var is not None:
            self.fetch_switch_var.set(checked)
        self.fetch_switch.configure(state="normal" if clickable else "disabled")

    def _render_fetch_status(self) -> None:
        """据缓存的连接/开关态 + 当前单渲染状态文案与开关态（不发 HTTP）。"""
        if getattr(self, "fetch_status_var", None) is None:
            return
        if not self._scrape_probed:
            self.fetch_status_var.set("服务：进入本端自动查询（或点「刷新」）")
            self._set_switch_state(checked=False, clickable=False)
            return
        # 「当前单」优先取库驱动载入的订单号；回退旧收件夹文件名（库驱动后通常为 None）。
        active = self._db_order_active_id or (self._inbox_active.name if self._inbox_active else None)
        self.fetch_status_var.set(
            self._format_scrape_status(self._scrape_connected, self._inbox_service_url, self._scrape_control, active)
        )
        checked, clickable = self._scrape_switch_state(
            self._scrape_probed, self._scrape_connected, self._scrape_control
        )
        self._set_switch_state(checked=checked, clickable=clickable)

    # 收件夹轮询载单后调它更新「当前单」（沿用旧名，_auto_load_order 调用；纯渲染、不发 HTTP）。
    def _refresh_fetch_status(self) -> None:
        self._render_fetch_status()

    def _refresh_scrape_status(self) -> None:
        """后台探活 + 读自动抓开关，回主线程刷新面板（服务不可达则显示未连接）。"""
        if getattr(self, "fetch_status_var", None) is None:
            return
        url = self._inbox_service_url

        def work():
            if inbox_client.health(url) is None:
                return (False, None)
            try:
                return (True, inbox_client.get_scrape_control(url))
            except Exception:
                return (True, None)

        def done(result):
            self._scrape_probed = True
            self._scrape_connected, self._scrape_control = result
            if self._scrape_control and self._scrape_control.get("scrape_from") and self.scrape_from_var is not None:
                self.scrape_from_var.set(str(self._scrape_control["scrape_from"]))
            self._render_fetch_status()

        def err(_exc):
            self._scrape_probed = True
            self._scrape_connected, self._scrape_control = False, None
            self._render_fetch_status()

        run_background(self.root, work, done, err)

    def _put_scrape_then_refresh(self, **kwargs) -> None:
        """后台 PUT 自动抓开关，成功后刷新状态；失败把错误显进状态行。"""
        url = self._inbox_service_url
        run_background(
            self.root,
            lambda: inbox_client.put_scrape_control(url, **kwargs),
            lambda _res: self._refresh_scrape_status(),
            lambda exc: self.fetch_status_var.set(f"操作失败：{exc}") if self.fetch_status_var is not None else None,
        )

    # 心跳间隔（秒）：服务端默认租约 90s，这里每 30s 续一次（≈lease/3，容 2 次丢包）。
    _HEARTBEAT_SECONDS = 30

    def _resolve_task_scrape_from(self) -> str:
        """「开始采集」要下发的订单时间范围下界（付款时间，墙钟）。

        操作员在「定时抓取·重抓起点」选了就用它（可回溯到该时间）；没选则默认=**现在**——
        只抓此刻之后付款的新单，绝不回溯历史（P0 历史订单保护的安全默认）。
        """
        val = (self.scrape_from_var.get() or "").strip() if self.scrape_from_var is not None else ""
        if val:
            return val
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _on_fetch_switch_toggle(self) -> None:
        """实时开关回调（仅用户点击触发）：开=下发采集任务 + 起心跳；关=释放任务租约。失败回弹+提示。

        ⚠️ P0：「开始」不再只是 PUT enabled，而是创建一个**有租约的任务**（task/start）并周期心跳续约；
        flower 一关/崩溃 → 不再续约 → 租约到期 → 扩展自动停（这是「唯一控制面」语义的落地）。
        """
        if getattr(self, "fetch_switch", None) is None or self.fetch_switch_var is None:
            return
        desired = bool(self.fetch_switch_var.get())
        # 未连接/状态未知本不该可点（开关已 disabled），双保险：回弹并提示先启动服务。
        if not (self._scrape_probed and self._scrape_connected and self._scrape_control is not None):
            self.fetch_switch_var.set(not desired)
            if self.fetch_status_var is not None:
                self.fetch_status_var.set("服务未连接，无法切换。请先确认 inbox-service 已启动，再点「刷新」。")
            return
        self.fetch_switch.configure(state="disabled")  # 切换中禁用，避免连点/与回填竞态
        url = self._inbox_service_url

        def revert(exc):
            if self.fetch_switch_var is not None:
                self.fetch_switch_var.set(not desired)  # 回弹到切换前
            if getattr(self, "fetch_switch", None) is not None:
                self.fetch_switch.configure(state="normal")
            if self.fetch_status_var is not None:
                self.fetch_status_var.set(f"切换失败：{exc}")

        if desired:
            scrape_from = self._resolve_task_scrape_from()

            def start_work():
                return inbox_client.start_scrape_task(
                    url, flower_instance_id=self._flower_instance_id, scrape_from=scrape_from
                )

            def start_done(res):
                self._scrape_task_id = res.get("task_id") if isinstance(res, dict) else None
                self._start_heartbeat()
                self._refresh_scrape_status()

            run_background(self.root, start_work, start_done, revert)
        else:
            task_id = self._scrape_task_id
            self._stop_heartbeat()
            self._scrape_task_id = None

            def stop_done(_res):
                self._refresh_scrape_status()

            run_background(
                self.root,
                lambda: inbox_client.stop_scrape_task(url, task_id=task_id),
                stop_done,
                revert,
            )

    def _start_heartbeat(self) -> None:
        """起/重置心跳 after 循环（幂等：先取消旧的，避免叠加多个循环）。"""
        self._stop_heartbeat()
        self._heartbeat_after_id = self.root.after(self._HEARTBEAT_SECONDS * 1000, self._heartbeat_tick)

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_after_id is not None:
            try:
                self.root.after_cancel(self._heartbeat_after_id)
            except Exception:
                pass
            self._heartbeat_after_id = None

    def _heartbeat_tick(self) -> None:
        """周期续约：成功 → 排下一次；409（任务失效）→ 停心跳 + 回弹开关；瞬时网络错误 → 重排重试。"""
        self._heartbeat_after_id = None
        task_id = self._scrape_task_id
        if task_id is None:
            return  # 已停止/已释放，不再续
        url = self._inbox_service_url

        def work():
            return inbox_client.heartbeat_scrape_task(
                url, task_id=task_id, flower_instance_id=self._flower_instance_id
            )

        def done(_res):
            if self._scrape_task_id == task_id:  # 期间没被停掉 → 排下一次
                self._heartbeat_after_id = self.root.after(self._HEARTBEAT_SECONDS * 1000, self._heartbeat_tick)

        def err(exc):
            if isinstance(exc, inbox_client.LeaseLostError):
                # 任务已失效（被别处替换/停止）→ 停心跳、清任务、回弹开关到关。
                self._scrape_task_id = None
                self._stop_heartbeat()
                if self.fetch_switch_var is not None:
                    self.fetch_switch_var.set(False)
                if self.fetch_status_var is not None:
                    self.fetch_status_var.set("采集任务已失效（被替换或停止），已停止。请重新点「自动抓取」。")
                self._refresh_scrape_status()
            elif self._scrape_task_id == task_id:
                # 瞬时网络错误：重排重试（租约还没到期；若持续失败，服务端到期后扩展自停，安全）。
                self._heartbeat_after_id = self.root.after(self._HEARTBEAT_SECONDS * 1000, self._heartbeat_tick)

        run_background(self.root, work, done, err)

    def _on_app_close(self) -> None:
        """关闭 App：释放任务租约（best-effort，短超时）+ 停心跳/收件夹轮询，再销毁窗口。

        不释放的话，扩展会一直以为还被授权，直到租约自然到期（最多 lease 秒）才停——尽量主动释放。
        """
        self._save_pane_sashes()  # 先把拖好的列宽存盘，再走清理/销毁
        self._stop_heartbeat()
        task_id = self._scrape_task_id
        self._scrape_task_id = None
        if task_id is not None:
            try:
                inbox_client.stop_scrape_task(self._inbox_service_url, task_id=task_id, timeout=2.0)
            except Exception:
                LOGGER.debug("关闭时释放采集任务租约失败（忽略，租约会自然到期）", exc_info=True)
        try:
            self._stop_inbox_poller()
            self._stop_db_order_poller()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _on_autoparse_switch_toggle(self) -> None:
        """「自动识别」开关回调（仅用户点击触发）：写回本地 config 并标记为用户显式设置，立即生效 + 持久化。

        纯本地、不发任何 HTTP，与「自动抓取」（驱动 inbox-service）完全独立。生效路径：后续来单的
        _auto_load_order 读 self.config.inbox_autoparse 决定是否自动 parse_remark()；绝不自动「生成」。
        """
        if self.autoparse_switch_var is None:
            return
        desired = bool(self.autoparse_switch_var.get())
        # inbox_autoparse_user_set=True：从此采信存储值（不再被安全迁移回落），见 config_store.load_config。
        self.config = dataclasses.replace(
            self.config, inbox_autoparse=desired, inbox_autoparse_user_set=True
        )
        try:
            save_config(self.config)
        except OSError as exc:
            LOGGER.exception("保存自动识别开关失败")
            if getattr(self, "status_var", None) is not None:
                self.status_var.set(f"自动识别保存失败：{exc}")
            return
        if getattr(self, "status_var", None) is not None:
            self.status_var.set(
                "自动识别已开启：新订单将自动解析识别（仍需人工点「生成」）"
                if desired
                else "自动识别已关闭：新订单仅载入，不自动解析"
            )

    def _on_scrape_restart_from(self) -> None:
        value = (self.scrape_from_var.get() or "").strip() if self.scrape_from_var is not None else ""
        if not value:
            if self.fetch_status_var is not None:
                self.fetch_status_var.set("请先选择付款时间（点上方选择器选日期+时分）再点应用。")
            return
        self._put_scrape_then_refresh(restart_from=value)

    def _on_scrape_clear_from(self) -> None:
        if self.scrape_from_var is not None:
            self.scrape_from_var.set("")
        self._put_scrape_then_refresh(clear_restart_from=True)

    def _open_fetch_settings(self) -> None:
        """抓取设置弹窗：间隔(PUT interval_seconds) + 服务地址(本地存) + 收件夹(只读，主设置里改)。"""
        win = self._themed_toplevel()
        win.title("抓取设置")
        win.transient(self.root)
        win.geometry("380x240")
        frame = ctk.CTkFrame(win, fg_color=APP_COLORS["panel"])
        frame.pack(fill="both", expand=True, padx=12, pady=12)
        frame.columnconfigure(1, weight=1)
        interval_default = ""
        if self._scrape_control and self._scrape_control.get("interval_seconds") is not None:
            interval_default = str(self._scrape_control["interval_seconds"])
        interval_var = tk.StringVar(value=interval_default)
        url_var = tk.StringVar(value=self._inbox_service_url)
        ctk.CTkLabel(frame, text="抓取间隔(秒)", anchor="w").grid(row=0, column=0, sticky="w", pady=6, padx=(0, 8))
        ctk.CTkEntry(frame, textvariable=interval_var).grid(row=0, column=1, sticky="ew", pady=6)
        ctk.CTkLabel(frame, text="服务地址", anchor="w").grid(row=1, column=0, sticky="w", pady=6, padx=(0, 8))
        ctk.CTkEntry(frame, textvariable=url_var).grid(row=1, column=1, sticky="ew", pady=6)
        ctk.CTkLabel(frame, text="收件夹", anchor="w").grid(row=2, column=0, sticky="w", pady=6, padx=(0, 8))
        ctk.CTkLabel(
            frame, text=str(self.config.inbox_folder) or "（未配置，菜单 文件→设置 改）",
            anchor="w", justify="left", text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=10), wraplength=210,
        ).grid(row=2, column=1, sticky="w", pady=6)

        def save() -> None:
            url = (url_var.get() or "").strip()
            if url and url != self._inbox_service_url:
                self._inbox_service_url = url
                # 持久化服务地址到 config，重启不丢（缺口修复 2026-06-19）。
                self.config = dataclasses.replace(self.config, inbox_service_url=url)
                save_config(self.config)
            interval_text = (interval_var.get() or "").strip()
            interval_val: int | None = None
            if interval_text:
                try:
                    interval_val = int(interval_text)
                    if interval_val < 1:
                        raise ValueError
                except ValueError:
                    messagebox.showerror("抓取设置", "间隔需为 ≥1 的整数秒")
                    return
            win.destroy()
            if interval_val is not None:
                self._put_scrape_then_refresh(interval_seconds=interval_val)
            else:
                self._refresh_scrape_status()

        action = ctk.CTkFrame(frame, fg_color="transparent")
        action.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self._btn(action, "取消", win.destroy, width=70).grid(row=0, column=0, padx=(0, 8))
        self._btn(action, "保存", save, primary=True, width=70).grid(row=0, column=1)

    def _apply_view(self, role: str) -> None:
        """按端重排功能区卡片：grid_remove 全部、再按该端有序 grid（不重建、不丢状态）。"""
        if role not in VIEW_ORDER:
            role = VIEW_OPERATOR
        self.active_view = role
        self.active_view_var.set(VIEW_LABELS[role])
        # 切端控件着色：管理员端（含 IP）染琥珀，作「你在 IP 端」的视觉提示；其余端中性。
        if getattr(self, "_view_switch_menu", None) is not None:
            is_admin = role == VIEW_ADMIN
            self._view_switch_menu.configure(
                text_color="#e7b85c" if is_admin else APP_COLORS["text"],
                button_color="#5a4a1f" if is_admin else APP_COLORS["input"],
            )
        if not self._function_cards:
            return
        for card in self._function_cards.values():
            try:
                card.grid_remove()
            except Exception:
                pass
        for row, key in enumerate(view_cards_for_role(role)):
            card = self._function_cards.get(key)
            if card is not None:
                card.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        # 中心区：配置端=订单表、其余端=画板（构造期面板未就绪时此调用安全 no-op）。
        self._apply_center_for_view(role)
        # 进入操作员配置端：查一次 inbox-service 自动抓开关（懒探，不在构造/别的端探网）。
        if role == VIEW_OPERATOR_CONFIG:
            self._refresh_scrape_status()

    def _apply_center_for_view(self, role: str) -> None:
        """中心区按端切换：配置端显示「实时订单表」、隐藏画板；其余端显示画板、隐藏订单表。

        面板在 _build_layout 后才存在；构造期（_build_function_panel 内首次 _apply_view）此处 no-op。
        """
        preview = getattr(self, "_preview_panel", None)
        orders = getattr(self, "_orders_panel", None)
        if preview is None or orders is None:
            return
        if role == VIEW_OPERATOR_CONFIG:
            preview.grid_remove()
            orders.grid()
            self._refresh_orders_table()
        else:
            orders.grid_remove()
            preview.grid()

    def _enter_view(self, role: str) -> None:
        """从选端遮罩页进入某端：应用该端并关掉遮罩。"""
        self._apply_view(role)
        if self._view_overlay is not None:
            self._view_overlay.destroy()
            self._view_overlay = None

    def _on_switch_view(self, label: str) -> None:
        """顶部切端下拉回调：中文端名→角色再应用；切到管理员端且本次未鉴权时一律先过密码门。

        注意：判定用 `not self._admin_authed`（而非 `_needs_admin_gate`）——否则**未设密码**时
        `_needs_admin_gate` 为 False 会让下拉直接进管理员端、绕过设密码（门厅入口走 `_enter_admin_view`
        无此洞）。两条路径必须一致：未鉴权就交给 `_enter_admin_view`（无密码→引导设置 / 有密码→校验）。
        """
        role = next((r for r, text in VIEW_LABELS.items() if text == label), None)
        if role is None:
            return
        if role == VIEW_ADMIN and not self._admin_authed:
            # 回弹下拉到当前端（没鉴权不该显示在管理员端），再走统一的 _enter_admin_view 把关。
            current = getattr(self, "active_view", VIEW_OPERATOR)
            self.active_view_var.set(VIEW_LABELS.get(current, label))
            self._enter_admin_view()
            return
        self._apply_view(role)

    def _show_view_chooser(self) -> None:
        """启动选端遮罩页（门厅）：操作员端=hero 大卡 + 门口实时状态条 + 两张次端小卡；管理员端走密码门。"""
        if ctk is None or self._view_overlay is not None:
            return
        C = ENTRY_COLORS
        overlay = ctk.CTkFrame(self.root, fg_color=C["bg"], corner_radius=0)
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._view_overlay = overlay
        overlay.bind("<Return>", lambda _e: self._enter_view(VIEW_OPERATOR))
        overlay.focus_set()

        panel = ctk.CTkFrame(overlay, fg_color="transparent")
        panel.place(relx=0.5, rely=0.5, anchor="center")
        # 0 高定宽撑条固定门厅宽度（CTkFrame 默认按内容收缩）。
        ctk.CTkFrame(panel, fg_color="transparent", width=620, height=1).pack()

        # —— 顶栏：品牌 + 门口实时状态条（C）——
        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", pady=(0, 16))
        brand_img = line_icons.icon_ctk("flower", C["teal"], 18)
        brand = ctk.CTkLabel(
            top, text="", image=brand_img, fg_color=_blend_hex(C["teal"], C["bg"], 0.16),
            corner_radius=8, width=30, height=30,
        )
        if brand_img is not None:
            brand._entry_img = brand_img
        brand.pack(side="left")
        ctk.CTkLabel(top, text="  flower", text_color=C["text"], font=ctk.CTkFont(size=16)).pack(side="left")
        ctk.CTkLabel(top, text="雕刻素材工作台", text_color=C["dim"], font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(8, 0)
        )
        chips = ctk.CTkFrame(top, fg_color="transparent")
        chips.pack(side="right")
        self._entry_chips = {
            "service": self._make_entry_chip(chips, "plug-connected", "服务 —", C["dim"]),
            "scrape": self._make_entry_chip(chips, "broadcast", "抓取 —", C["dim"]),
            "backlog": self._make_entry_chip(chips, "inbox", "积压 —", C["dim"]),
        }
        for key in ("service", "scrape", "backlog"):  # side=right 逆序 → 视觉左→右：积压/抓取/服务
            self._entry_chips[key].pack(side="right", padx=(6, 0))

        ctk.CTkLabel(panel, text="选择工作台", text_color=C["muted"], font=ctk.CTkFont(size=13)).pack(
            anchor="w", pady=(0, 10)
        )

        self._build_entry_hero(panel)

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x")
        self._entry_role_card(row, VIEW_OPERATOR_CONFIG).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._entry_role_card(row, VIEW_ADMIN).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=1)

        # —— 页脚：切端提示 + 已上线产品（多产品信号，取自真实 config.products）——
        ctk.CTkFrame(panel, fg_color="#1d212b", height=1).pack(fill="x", pady=(16, 10))
        footer = ctk.CTkFrame(panel, fg_color="transparent")
        footer.pack(fill="x")
        ctk.CTkLabel(
            footer, text="进入后顶部「切端」可随时切换", text_color=C["dim"], font=ctk.CTkFont(size=12),
        ).pack(side="left")
        prods = "、".join(p.name for p in self.config.products) or "生日花卡"
        ctk.CTkLabel(
            footer, text=f"已上线产品：{prods}", text_color=C["dim"], font=ctk.CTkFont(size=12),
        ).pack(side="right")

        # 门口状态条：进门后做一次 best-effort 后台探活（服务没起则保持「—/未连」，不阻塞、不抛）。
        self.root.after(80, self._refresh_entry_status)

    def _make_entry_chip(self, parent, icon: str, text: str, color: str):
        """门口状态 chip：圆角 + 预混半透明底 + 同色字 + 小图标（纯 CTkLabel，无依赖）。"""
        C = ENTRY_COLORS
        img = line_icons.icon_ctk(icon, color, 13)
        kwargs = dict(
            text=f"  {text}  ", text_color=color, fg_color=_blend_hex(color, C["bg"], 0.14),
            corner_radius=6, font=ctk.CTkFont(size=12),
        )
        if img is not None:
            kwargs["image"] = img
            kwargs["compound"] = "left"
        chip = ctk.CTkLabel(parent, **kwargs)
        if img is not None:
            chip._entry_img = img
        return chip

    def _set_entry_chip(self, key: str, icon: str, text: str, color: str) -> None:
        chip = self._entry_chips.get(key)
        if chip is None:
            return
        chip.configure(text=f"  {text}  ", text_color=color, fg_color=_blend_hex(color, ENTRY_COLORS["bg"], 0.14))
        img = line_icons.icon_ctk(icon, color, 13)
        if img is not None:
            chip.configure(image=img)
            chip._entry_img = img

    def _refresh_entry_status(self) -> None:
        """门口状态条 best-effort 探活：服务连接 + 自动抓开关 + 积压数；服务没起则显示未连/—，不阻塞、不抛。"""
        if self._view_overlay is None or not self._entry_chips:
            return
        url = getattr(self, "_inbox_service_url", None) or inbox_client.DEFAULT_BASE_URL

        def work():
            if inbox_client.health(url) is None:
                return None
            try:
                control = inbox_client.get_scrape_control(url)
            except Exception:
                control = None
            try:
                backlog = int(inbox_client.list_orders(url, limit=1).get("count", 0))
            except Exception:
                backlog = None
            return (control, backlog)

        def done(result):
            if self._view_overlay is None:  # 期间已进入某端、遮罩没了
                return
            C = ENTRY_COLORS
            if result is None:
                self._set_entry_chip("service", "plug-connected", "服务 未连", C["dim"])
                self._set_entry_chip("scrape", "broadcast", "抓取 —", C["dim"])
                self._set_entry_chip("backlog", "inbox", "积压 —", C["dim"])
                return
            control, backlog = result
            self._set_entry_chip("service", "plug-connected", "服务 已连", C["green"])
            enabled = bool(control.get("enabled")) if isinstance(control, dict) else False
            self._set_entry_chip(
                "scrape", "broadcast", "抓取 开" if enabled else "抓取 关",
                C["green"] if enabled else C["dim"],
            )
            if backlog is None:
                self._set_entry_chip("backlog", "inbox", "积压 —", C["dim"])
            else:
                self._set_entry_chip("backlog", "inbox", f"积压 {backlog}", C["amber"])
                if self._entry_hero_count is not None:
                    self._entry_hero_count.configure(text=str(backlog))

        run_background(self.root, work, done, lambda _e: None)

    def _build_entry_hero(self, parent) -> None:
        """操作员端 hero 大卡：青色描边、图标 + 标题 + 描述 + 待处理数 + 进入；整卡可点、回车直达。"""
        C = ENTRY_COLORS
        icon, accent, title, desc = ENTRY_ROLE_META[VIEW_OPERATOR]
        hero = ctk.CTkFrame(parent, fg_color=C["card"], border_width=1, border_color=accent, corner_radius=11)
        hero.pack(fill="x", pady=(0, 12))
        inner = ctk.CTkFrame(hero, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=16)
        inner.columnconfigure(1, weight=1)
        tile_img = line_icons.icon_ctk(icon, accent, 24)
        tile = ctk.CTkLabel(
            inner, text="", image=tile_img, fg_color=_blend_hex(accent, C["card"], 0.16),
            corner_radius=11, width=46, height=46,
        )
        if tile_img is not None:
            tile._entry_img = tile_img
        tile.grid(row=0, column=0, rowspan=2)
        ctk.CTkLabel(inner, text=title, text_color=C["text"], font=ctk.CTkFont(size=16)).grid(
            row=0, column=1, sticky="w", padx=(14, 0)
        )
        ctk.CTkLabel(inner, text=desc, text_color=C["muted"], font=ctk.CTkFont(size=13)).grid(
            row=1, column=1, sticky="w", padx=(14, 0)
        )
        cnt = ctk.CTkFrame(inner, fg_color="transparent")
        cnt.grid(row=0, column=2, rowspan=2, padx=(8, 14))
        self._entry_hero_count = ctk.CTkLabel(cnt, text="—", text_color=C["text"], font=ctk.CTkFont(size=20))
        self._entry_hero_count.pack()
        ctk.CTkLabel(cnt, text="待处理", text_color=C["dim"], font=ctk.CTkFont(size=12)).pack()
        arrow_img = line_icons.icon_ctk("arrow-right", "#06281f", 14)
        enter = ctk.CTkLabel(
            inner, text="进入  ", image=arrow_img, compound="right", fg_color=accent,
            text_color="#06281f", corner_radius=8, font=ctk.CTkFont(size=14), width=84, height=34,
        )
        if arrow_img is not None:
            enter._entry_img = arrow_img
        enter.grid(row=0, column=3, rowspan=2)
        self._bind_card_click(hero, lambda _e=None: self._enter_view(VIEW_OPERATOR))
        self._bind_card_hover(hero, (accent, C["card"]), (accent, C["card_hover"]))

    def _entry_role_card(self, parent, role: str):
        """次端小卡（配置端/管理员端）：图标 tile + 标题(+IP 标) + 描述 + 尾图标；整卡可点、悬停描边亮起。"""
        C = ENTRY_COLORS
        icon, accent, title, desc = ENTRY_ROLE_META[role]
        card = ctk.CTkFrame(parent, fg_color=C["card"], border_width=1, border_color=C["border"], corner_radius=11)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=14)
        inner.columnconfigure(1, weight=1)
        tile_img = line_icons.icon_ctk(icon, accent, 20)
        tile = ctk.CTkLabel(
            inner, text="", image=tile_img, fg_color=_blend_hex(accent, C["card"], 0.14),
            corner_radius=10, width=40, height=40,
        )
        if tile_img is not None:
            tile._entry_img = tile_img
        tile.grid(row=0, column=0, rowspan=2)
        titlerow = ctk.CTkFrame(inner, fg_color="transparent")
        titlerow.grid(row=0, column=1, sticky="w", padx=(12, 0))
        ctk.CTkLabel(titlerow, text=title, text_color=C["text"], font=ctk.CTkFont(size=15)).pack(side="left")
        if role == VIEW_ADMIN:
            badge_img = line_icons.icon_ctk("lock", C["amber"], 11)
            badge = ctk.CTkLabel(
                titlerow, text=" IP", image=badge_img, compound="left",
                fg_color=_blend_hex(C["amber"], C["card"], 0.12), text_color=C["amber"],
                corner_radius=4, font=ctk.CTkFont(size=10),
            )
            if badge_img is not None:
                badge._entry_img = badge_img
            badge.pack(side="left", padx=(6, 0))
        ctk.CTkLabel(inner, text=desc, text_color=C["muted"], font=ctk.CTkFont(size=12)).grid(
            row=1, column=1, sticky="w", padx=(12, 0)
        )
        tail_img = line_icons.icon_ctk("lock" if role == VIEW_ADMIN else "arrow-right", C["dim"], 16)
        tail = ctk.CTkLabel(inner, text="", image=tail_img)
        if tail_img is not None:
            tail._entry_img = tail_img
        tail.grid(row=0, column=2, rowspan=2, sticky="e")
        if role == VIEW_ADMIN:
            self._bind_card_click(card, lambda _e=None: self._enter_admin_view())
        else:
            self._bind_card_click(card, lambda _e=None, r=role: self._enter_view(r))
        self._bind_card_hover(card, (C["border"], C["card"]), (accent, C["card_hover"]))
        return card

    def _widget_descendants(self, widget):
        out = []
        try:
            children = widget.winfo_children()
        except Exception:
            return out
        for child in children:
            out.append(child)
            out.extend(self._widget_descendants(child))
        return out

    def _bind_card_click(self, card, command) -> None:
        """整张卡（含所有子控件）点击 = 触发 command；门厅卡都是「整卡可点」。"""
        for w in (card, *self._widget_descendants(card)):
            w.bind("<Button-1>", command, add="+")

    def _bind_card_hover(self, card, normal: tuple, hover: tuple) -> None:
        """悬停整卡换 (描边, 底色)；移到子控件不误判离开（winfo_containing 沿 master 链回溯）。"""
        def on_enter(_e=None):
            card.configure(border_color=hover[0], fg_color=hover[1])

        def on_leave(_e=None):
            try:
                x, y = card.winfo_pointerxy()
                node = card.winfo_containing(x, y)
            except Exception:
                node = None
            while node is not None:
                if node == card:
                    return
                node = getattr(node, "master", None)
            card.configure(border_color=normal[0], fg_color=normal[1])

        for w in (card, *self._widget_descendants(card)):
            w.bind("<Enter>", on_enter, add="+")
            w.bind("<Leave>", on_leave, add="+")

    def _enter_admin_view(self) -> None:
        """进管理员端：本次已鉴权→直接进；未设密码→引导设置；已设未鉴权→验密码。"""
        if self._admin_authed:
            self._admin_gate_success()
        elif not has_admin_password(self.config):
            self._show_admin_gate(setup=True)
        else:
            self._show_admin_gate(setup=False)

    def _show_admin_gate(self, *, setup: bool) -> None:
        """管理员密码门：scrim 暗幕 + 居中模态卡；setup=首次设密码（双输入），否则校验。"""
        if ctk is None or self._admin_gate is not None:
            return
        C = ENTRY_COLORS
        scrim = ctk.CTkFrame(self.root, fg_color=_blend_hex("#08090c", C["bg"], 0.72), corner_radius=0)
        scrim.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._admin_gate = scrim
        card = ctk.CTkFrame(scrim, fg_color=C["card"], border_width=1, border_color="#2a2e3a", corner_radius=12)
        card.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkFrame(card, fg_color="transparent", width=300, height=1).pack(padx=18)
        lock_img = line_icons.icon_ctk("lock", C["amber"], 15)
        head = ctk.CTkLabel(
            card, text="  管理员端 · IP 敏感", image=lock_img, compound="left",
            text_color=C["text"], font=ctk.CTkFont(size=14),
        )
        if lock_img is not None:
            head._entry_img = lock_img
        head.pack(anchor="w", padx=18, pady=(16, 2))
        hint = "首次进入：设置一个管理员密码（至少 4 位）" if setup else "输入管理员密码进入识别规则配置"
        ctk.CTkLabel(
            card, text=hint, text_color=C["muted"], font=ctk.CTkFont(size=12), wraplength=280, justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 10))
        pw1 = tk.StringVar()
        pw2 = tk.StringVar()
        e1 = ctk.CTkEntry(
            card, textvariable=pw1, show="•", placeholder_text="密码",
            fg_color="#0e0f13", border_color="#2a2e3a", text_color=C["text"],
        )
        e1.pack(fill="x", padx=18)
        e2 = None
        if setup:
            e2 = ctk.CTkEntry(
                card, textvariable=pw2, show="•", placeholder_text="再次输入",
                fg_color="#0e0f13", border_color="#2a2e3a", text_color=C["text"],
            )
            e2.pack(fill="x", padx=18, pady=(8, 0))
        err = ctk.CTkLabel(card, text="", text_color=C["danger"], font=ctk.CTkFont(size=11))
        err.pack(anchor="w", padx=18, pady=(6, 0))

        def submit(_e=None):
            p1 = pw1.get()
            if setup:
                if len(p1) < 4:
                    err.configure(text="密码至少 4 位")
                    return
                if p1 != pw2.get():
                    err.configure(text="两次输入不一致")
                    return
                self.config = with_admin_password(self.config, p1)
                save_config(self.config)
                self._close_admin_gate()
                self._admin_gate_success()
            elif verify_admin_password(self.config, p1):
                self._close_admin_gate()
                self._admin_gate_success()
            else:
                err.configure(text="密码错误")
                pw1.set("")
                e1.focus_set()

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=18, pady=(12, 16))
        ctk.CTkButton(
            btns, text="进入", command=submit, fg_color=C["amber"], hover_color="#caa03f",
            text_color="#3a2c08", corner_radius=7, height=32,
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            btns, text="取消", command=self._close_admin_gate, fg_color="transparent", border_width=1,
            border_color="#2a2e3a", text_color=C["muted"], hover_color=C["card_hover"],
            corner_radius=7, height=32, width=72,
        ).pack(side="left", padx=(8, 0))
        e1.bind("<Return>", submit)
        if e2 is not None:
            e2.bind("<Return>", submit)
        scrim.bind("<Escape>", lambda _e: self._close_admin_gate())
        e1.focus_set()

    def _close_admin_gate(self) -> None:
        if self._admin_gate is not None:
            self._admin_gate.destroy()
            self._admin_gate = None

    def _admin_gate_success(self) -> None:
        """密码通过：标记本次已鉴权，进入管理员端（从门厅则连遮罩一起关，从切端则原地切）。"""
        self._admin_authed = True
        if self._view_overlay is not None:
            self._enter_view(VIEW_ADMIN)
        else:
            self._apply_view(VIEW_ADMIN)


    def _build_layers_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        """兼容旧调用名；真实图层面板已迁到 _build_production_panel 的 Treeview。"""
        return self._build_production_panel(parent)

    def _build_order_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        panel, body = self._ctk_card(parent, "订单信息")
        body.columnconfigure(0, weight=1)

        header = ctk.CTkFrame(body, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="订单信息", anchor="w").grid(row=0, column=0, sticky="w")
        # 配置锁已删除（2026-06-19）：原此处的 🔒 锁按钮移除，IP 隔离改由三端分离承担。
        self.remark_text = ctk.CTkTextbox(
            body,
            height=84,
            fg_color=APP_COLORS["input"],
            text_color=APP_COLORS["text"],
            border_width=1,
            border_color=APP_COLORS["border"],
        )
        self.remark_text.grid(row=1, column=0, sticky="ew", pady=(6, 8))
        if self.remark_var.get():
            self.remark_text.insert("1.0", self.remark_var.get())

        action_row = ctk.CTkFrame(body, fg_color="transparent")
        action_row.grid(row=2, column=0, sticky="ew")
        action_row.columnconfigure(0, weight=1)
        self._btn(action_row, "导入", self.import_remark_file).grid(row=0, column=1, padx=(0, 8))
        self._btn(action_row, "解析", self.parse_remark, primary=True).grid(row=0, column=2, padx=(0, 8))
        self._btn(action_row, "清空", self.clear_remark).grid(row=0, column=3)

        # 多订单队列导航：一次粘贴多笔订单时，逐笔载入编辑器确认/生成（单笔时隐藏）。
        queue_row = ctk.CTkFrame(body, fg_color="transparent")
        queue_row.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        queue_row.columnconfigure(0, weight=1)
        self.order_queue_label = ctk.CTkLabel(
            queue_row, text="", anchor="w", text_color=APP_COLORS["muted"],
            font=ctk.CTkFont(size=11),
        )
        self.order_queue_label.grid(row=0, column=0, sticky="w")
        self.order_prev_button = self._btn(queue_row, "‹ 上一笔", self._show_prev_order, width=70)
        self.order_prev_button.grid(row=0, column=1, padx=(0, 6))
        self.order_next_button = self._btn(queue_row, "下一笔 ›", self._show_next_order, width=70)
        self.order_next_button.grid(row=0, column=2)
        self.order_prev_button.grid_remove()
        self.order_next_button.grid_remove()



        return panel

    def _build_preview_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        panel, body = self._ctk_card(parent, "实时画板")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        status_row = ctk.CTkFrame(body, fg_color="transparent")
        status_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        status_row.columnconfigure(1, weight=1)
        self._size_status_row = status_row
        self._size_edit_frame = None  # 内联编辑画布尺寸时复用；None=未在编辑
        self.preview_size_label = ctk.CTkLabel(
            status_row,
            textvariable=self.preview_canvas_size_var,
            anchor="w",
            text_color=APP_COLORS["muted"],
            font=ctk.CTkFont(size=11),
            cursor="hand2",  # 提示这行可点击编辑
        )
        self.preview_size_label.grid(row=0, column=0, sticky="w")
        self.preview_size_label.bind("<Button-1>", lambda _e: self._begin_canvas_size_edit())
        ctk.CTkLabel(
            status_row,
            text=" | ",
            anchor="w",
            text_color=APP_COLORS["muted"],
            font=ctk.CTkFont(size=11),
        ).grid(row=0, column=1, sticky="w", padx=4)
        ctk.CTkLabel(
            status_row,
            textvariable=self.preview_zoom_status_var,
            anchor="e",
            text_color=APP_COLORS["muted"],
            font=ctk.CTkFont(size=11),
        ).grid(row=0, column=2, sticky="e")

        # 画板保持白底：代表浅色木料，雕刻预览是深灰折线 + 黑墨字，翻黑会看不见。
        # 上/左刻度尺固定显示物理 mm，跟随同一个 document→screen 变换。
        ruler_frame = tk.Frame(body, bg="white", highlightthickness=1, highlightbackground=APP_COLORS["border"])
        ruler_frame.grid(row=1, column=0, sticky="nsew")
        ruler_frame.columnconfigure(1, weight=1)
        ruler_frame.rowconfigure(1, weight=1)
        self.preview_ruler_corner = tk.Canvas(
            ruler_frame, width=RULER_THICKNESS, height=RULER_THICKNESS, bg="#f8fafc", highlightthickness=0
        )
        self.preview_ruler_corner.grid(row=0, column=0, sticky="nsew")
        self.preview_ruler_x = tk.Canvas(
            ruler_frame, height=RULER_THICKNESS, bg="#f8fafc", highlightthickness=0
        )
        self.preview_ruler_x.grid(row=0, column=1, sticky="ew")
        self.preview_ruler_y = tk.Canvas(
            ruler_frame, width=RULER_THICKNESS, bg="#f8fafc", highlightthickness=0
        )
        self.preview_ruler_y.grid(row=1, column=0, sticky="ns")
        self.preview_canvas = tk.Canvas(
            ruler_frame,
            width=720,
            height=532,
            bg="white",
            highlightthickness=0,
        )
        self.preview_canvas.grid(row=1, column=1, sticky="nsew")
        self.preview_canvas.bind("<Button-1>", self._on_canvas_press)
        self.preview_canvas.bind("<Double-Button-1>", self._on_canvas_double_click)
        self.preview_canvas.bind("<Button-3>", self._show_canvas_context_menu)
        self.preview_canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.preview_canvas.bind("<Configure>", lambda _event: self._redraw_preview())
        self.preview_canvas.bind("<Motion>", self._on_canvas_motion)
        self.preview_canvas.bind("<Leave>", self._on_canvas_leave)
        self.preview_canvas.bind("<MouseWheel>", self._on_canvas_mousewheel)
        self.preview_canvas.bind("<Button-4>", self._on_canvas_mousewheel)
        self.preview_canvas.bind("<Button-5>", self._on_canvas_mousewheel)
        self.preview_canvas.bind("<Delete>", lambda _event: self._delete_selected_layer())
        self.preview_canvas.bind("<BackSpace>", lambda _event: self._delete_selected_layer())
        return panel

    def _build_orders_table_panel(self, parent) -> ctk.CTkFrame:
        """「实时订单」面板（操作员配置端中心区，2026-06-19）：列扩展抓取、已入库的订单。

        替代该端的实时画板——配置端不编辑、只监控调度与订单（数据=GET /inbox/orders）。
        表用 ttk.Treeview（阶段三：原生虚拟化，扛 1700+ 行秒开）；双击看详情、选中后 ✕/Delete/右键删除。
        件数/退款/其他商品由 order_row_view 从 items/refund_status 聚合；扩展暂只抓列表页时
        items 为空 → 件数显 —（待 Phase 1 详情页抓取补全）。
        """
        panel, body = self._ctk_card(parent, "实时订单 · 扩展抓取已入库")
        body.rowconfigure(4, weight=1)  # 表格行（row0=head / row1=clean / row2=复核提示 / row3=筛选 / row4=表）
        body.columnconfigure(0, weight=1)
        head = ctk.CTkFrame(body, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        head.columnconfigure(0, weight=1)
        self.orders_status_var = tk.StringVar(value="进入本端自动加载（或点「刷新」）")
        ctk.CTkLabel(
            head, textvariable=self.orders_status_var, anchor="w", justify="left",
            text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11), wraplength=460,
        ).grid(row=0, column=0, sticky="w")
        self._btn(head, "✕ 删除选中", self._on_delete_selected_orders, width=92).grid(row=0, column=1, padx=(6, 6))
        self._btn(head, "刷新", self._refresh_orders_table, width=64).grid(row=0, column=2)

        # 清理栏：保留最近 N 天 + 立即清理（手动） + 自动（后台无人值守删，存服务端 retention_days）。
        clean = ctk.CTkFrame(body, fg_color="transparent")
        clean.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(clean, text="保留最近", text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11)).pack(side="left")
        self.retention_days_var = tk.StringVar(value="")
        retention_entry = ctk.CTkEntry(clean, textvariable=self.retention_days_var, width=52, placeholder_text="如 30")
        retention_entry.pack(side="left", padx=4)
        retention_entry.bind("<FocusOut>", lambda _e: self._on_retention_entry_changed())
        ctk.CTkLabel(clean, text="天", text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11)).pack(side="left")
        self._btn(clean, "立即清理", self._on_purge_orders_now, width=72).pack(side="left", padx=(8, 0))
        self.retention_auto_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            clean, text="自动删（后台无人值守）", variable=self.retention_auto_var,
            command=self._on_apply_retention, checkbox_width=18, checkbox_height=18,
            fg_color=APP_COLORS["accent"], hover_color=APP_COLORS["accent_soft"],
            text_color=APP_COLORS["warning"], font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(10, 0))
        # 复核筛选（用户要求：表里要有「复核」筛选值 + 提示）：勾上只看 AI 标记与库状态冲突、待人工裁决的单。
        self.orders_filter_review_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            clean, text="只看复核", variable=self.orders_filter_review_var,
            command=self._on_orders_filter_changed, checkbox_width=18, checkbox_height=18,
            fg_color=APP_COLORS["accent"], hover_color=APP_COLORS["accent_soft"],
            text_color="#e8c06a", font=ctk.CTkFont(size=11),
        ).pack(side="right")

        # 复核提示行：解释「复核」是什么 + 实时待裁决条数（用户要求的「相应的提示」）。
        review_hint = ctk.CTkFrame(body, fg_color="transparent")
        review_hint.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        self.orders_review_var = tk.StringVar(
            value="复核 = 订单 AI 标记与库内状态冲突（如新单已带「AI已处理」），需人工裁决；勾「只看复核」筛出。"
        )
        ctk.CTkLabel(
            review_hint, textvariable=self.orders_review_var, anchor="w", justify="left",
            text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11), wraplength=520,
        ).grid(row=0, column=0, sticky="w")

        # 筛选行（付款时间 / 订单状态 / AI·复核 / 搜索）——前端即时过滤已加载订单，
        # 与「只看复核」开关共用 _render_orders_rows 过滤管线（2026-06-22）。复核档不另起列：AI 态已折进「标签」列。
        self.orders_filter_from_var = tk.StringVar(value="")
        self.orders_filter_to_var = tk.StringVar(value="")
        self.orders_filter_status_var = tk.StringVar(value="全部状态")
        self.orders_filter_ai_var = tk.StringVar(value="全部AI状态")
        self.orders_filter_search_var = tk.StringVar(value="")
        flt = ctk.CTkFrame(body, fg_color="transparent")
        flt.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(flt, text="付款", text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11)).pack(side="left")
        _f_from = ctk.CTkEntry(flt, textvariable=self.orders_filter_from_var, width=88, placeholder_text="从 Y-M-D")
        _f_from.pack(side="left", padx=(4, 2))
        _f_to = ctk.CTkEntry(flt, textvariable=self.orders_filter_to_var, width=88, placeholder_text="到 Y-M-D")
        _f_to.pack(side="left", padx=(0, 8))
        for _e in (_f_from, _f_to):
            _e.bind("<Return>", lambda _ev: self._on_orders_filter_changed())
            _e.bind("<FocusOut>", lambda _ev: self._on_orders_filter_changed())
        ctk.CTkOptionMenu(
            flt, variable=self.orders_filter_status_var, width=104,
            values=["全部状态", "已审核", "已发货", "待打单", "已退款", "风控中", "已忽略"],
            command=lambda _v: self._on_orders_filter_changed(),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkOptionMenu(
            flt, variable=self.orders_filter_ai_var, width=104,
            values=["全部AI状态", "待识别", "已识别", "待复核"],
            command=lambda _v: self._on_orders_filter_changed(),
        ).pack(side="left", padx=(0, 6))
        _f_search = ctk.CTkEntry(flt, textvariable=self.orders_filter_search_var, width=148, placeholder_text="搜索订单号 / 备注")
        _f_search.pack(side="left", padx=(0, 6))
        _f_search.bind("<KeyRelease>", lambda _ev: self._on_orders_filter_changed())
        self._btn(flt, "重置", self._on_orders_filter_reset, width=52).pack(side="left")

        # ttk.Treeview（原生虚拟化，1700+ 行秒开）+ 滚动条。状态/退款用整行着色(tag)；删除靠选中+✕/Delete/右键，详情靠双击。
        table = ctk.CTkFrame(body, fg_color=APP_COLORS["background"])
        table.grid(row=4, column=0, sticky="nsew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        columns = ("order_id", "paid_at", "status", "mark", "qty")
        self.orders_tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="extended")
        for col, title, width, anchor, stretch in (
            ("order_id", "订单号", 140, "w", True),
            ("paid_at", "付款时间", 130, "w", False),
            ("status", "状态（店小秘）", 96, "w", False),
            ("mark", "标签", 72, "w", False),
            ("qty", "件数", 50, "center", False),
        ):
            self.orders_tree.heading(col, text=title)
            self.orders_tree.column(col, width=width, anchor=anchor, stretch=stretch)
        vsb = ttk.Scrollbar(table, orient="vertical", command=self.orders_tree.yview)
        self.orders_tree.configure(yscrollcommand=vsb.set)
        self.orders_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        # 整行着色（Treeview 只能按行着色）：退款/取消=红、风控/含其他商品=琥珀、复核冲突=橙（区别于风控）。
        self.orders_tree.tag_configure("refund", foreground="#e88a84")
        self.orders_tree.tag_configure("risk", foreground="#e7b85c")
        self.orders_tree.tag_configure("conflict", foreground="#f0a85a")  # 复核冲突专用橙，与风控琥珀区分
        self.orders_tree.bind("<Double-1>", self._on_orders_tree_open_detail)
        self.orders_tree.bind("<Delete>", lambda _e: self._on_delete_selected_orders())
        self.orders_tree.bind("<Button-3>", self._on_orders_tree_context_menu)
        return panel

    def _refresh_orders_table(self) -> None:
        """后台探活 + 拉订单列表，回主线程渲染；服务不可达显示未连接、清空表。"""
        if getattr(self, "orders_tree", None) is None:
            return
        url = self._inbox_service_url
        self.orders_status_var.set("加载中…")

        def work():
            if inbox_client.health(url) is None:
                return None
            # 阶段三虚拟化后可一次拉全量（Treeview 扛得住）：limit 给足覆盖洪峰 1700+；超出则状态行提示「显示最近 N」。
            orders = inbox_client.list_orders(url, limit=2000)
            try:
                control = inbox_client.get_scrape_control(url)
            except Exception:
                control = None
            return (orders, control)

        def done(result):
            if result is None:
                self.orders_status_var.set(f"inbox-service 未连接 {url}\n（请确认服务已在该地址启动）")
                self._render_orders_rows([])
                return
            orders_result, control = result
            orders = orders_result.get("orders") or []
            total = orders_result.get("count", len(orders))
            shown = len(orders)
            hint = f"共 {total} 单" + (f"（显示最近 {shown}）" if shown < total else "")
            self.orders_status_var.set(f"{hint} · {url}")
            self._render_orders_rows(orders)
            if control is not None:
                self._populate_retention(control)

        def err(exc):
            self.orders_status_var.set(f"加载失败：{exc}")
            self._render_orders_rows([])

        run_background(self.root, work, done, err)

    def _render_orders_rows(self, orders: list[dict]) -> None:
        """增量渲染订单表（ttk.Treeview，iid=order_id）：删消失行、建新增行、存活行原位更新、按序重排。

        Treeview 原生虚拟化，1700+ 行也秒开、内存低；增量更新保留滚动位置与选中。
        """
        tree = getattr(self, "orders_tree", None)
        if tree is None:
            return
        self._orders_last = orders  # 缓存原始列表：切「只看复核」/改筛选时无需重新拉取即可重渲染
        review_only = bool(
            getattr(self, "orders_filter_review_var", None) and self.orders_filter_review_var.get()
        )
        views, seen = [], set()
        review_count = 0
        for order in orders:
            view = order_row_view(order)
            oid = view["order_id"]
            if oid in seen:
                continue
            seen.add(oid)
            if view.get("needs_review"):
                review_count += 1
            if review_only and not view.get("needs_review"):
                continue  # 筛选：只保留复核冲突单
            if not self._order_passes_filters(order, view):
                continue  # 4 维筛选（付款时间/店铺/订单状态/AI·复核/搜索），与「只看复核」AND 关系
            views.append((oid, view, order))
        self._update_orders_review_hint(review_count)
        new_ids = {oid for oid, _, _ in views}
        for iid in tree.get_children(""):
            if iid not in new_ids:
                tree.delete(iid)
                self._orders_data.pop(iid, None)
        for index, (oid, view, raw) in enumerate(views):
            self._orders_data[oid] = raw
            values = self._orders_tree_values(view)
            tags = self._orders_tree_tags(view)
            if tree.exists(oid):
                tree.item(oid, values=values, tags=tags)
                tree.move(oid, "", index)
            else:
                tree.insert("", index, iid=oid, values=values, tags=tags)

    @staticmethod
    def _orders_tree_values(view: dict) -> tuple:
        """一行五列：订单号 / 付款时间(含其他商品标注) / 店小秘状态 / 标记 / 件数。"""
        qty = view["quantity"]
        paid = view["paid_at"] + ("　·含其他" if view["has_other_products"] else "")
        return (view["order_id"], paid, view["status_label"], view["mark_label"], (f"×{qty}" if qty else "—"))

    @staticmethod
    def _orders_tree_tags(view: dict) -> tuple:
        """整行着色 tag（Treeview 只能按行）：复核冲突/退款/取消=红、风控/含其他商品=琥珀，其余默认。
        类别由 status_bg 反推（见 shop_status_style：退款 #3d2422 / 风控 #3d3220）。"""
        if view.get("needs_review"):
            return ("conflict",)  # 复核冲突：整行橙色专用 tag，与风控琥珀区分，提醒人工裁决
        if view["status_bg"] == "#3d2422":
            return ("refund",)
        if view["status_bg"] == "#3d3220" or view["has_other_products"]:
            return ("risk",)
        return ()

    def _update_orders_review_hint(self, review_count: int) -> None:
        """刷新复核提示行：有冲突单时显示待裁决条数，否则显示「复核」解释（用户要求的提示）。"""
        var = getattr(self, "orders_review_var", None)
        if var is None:
            return
        if review_count > 0:
            var.set(
                f"⚠ {review_count} 单待复核：AI 标记与库内状态冲突（如新单已带「AI已处理」），"
                "需人工裁决；勾「只看复核」筛出。"
            )
        else:
            var.set(
                "复核 = 订单 AI 标记与库内状态冲突（如新单已带「AI已处理」），需人工裁决；勾「只看复核」筛出。"
            )

    def _on_orders_filter_changed(self) -> None:
        """「只看复核」勾选切换 / 任一筛选条件变化 → 用缓存的订单列表重渲染（不重新拉取）。"""
        self._render_orders_rows(getattr(self, "_orders_last", []) or [])

    def _order_passes_filters(self, order: dict, view: dict) -> bool:
        """前端即时过滤（付款时间 / 店铺 / 订单状态 / AI·复核 / 搜索）。任一不匹配 → 该单不进表。
        与「只看复核」是独立 AND 关系（都在 _render_orders_rows 逐单判定）。空条件=该维不限。"""
        st_sel = (getattr(self, "orders_filter_status_var", None) and self.orders_filter_status_var.get()) or ""
        if st_sel and st_sel != "全部状态" and st_sel not in (order.get("refund_status") or ""):
            return False  # 含匹配：选「待打单」也命中「待打单(有货)」
        ai_sel = (getattr(self, "orders_filter_ai_var", None) and self.orders_filter_ai_var.get()) or ""
        ai_map = {"待识别": "pending", "已识别": "recognized", "待复核": "conflict"}
        if ai_sel in ai_map and view.get("ai_status") != ai_map[ai_sel]:
            return False
        kw = ((getattr(self, "orders_filter_search_var", None) and self.orders_filter_search_var.get()) or "").strip().lower()
        if kw and kw not in f"{order.get('order_id', '')} {order.get('remark', '')}".lower():
            return False
        pf = ((getattr(self, "orders_filter_from_var", None) and self.orders_filter_from_var.get()) or "").strip()
        pt = ((getattr(self, "orders_filter_to_var", None) and self.orders_filter_to_var.get()) or "").strip()
        if pf or pt:
            d = (order.get("paid_at") or order.get("received_at") or "")[:10]  # YYYY-MM-DD（ISO 字典序=时序）
            if not d or (pf and d < pf) or (pt and d > pt):
                return False
        return True

    def _on_orders_filter_reset(self) -> None:
        """清空 4 维筛选（不动「只看复核」开关），重渲染。"""
        for var, default in (
            (getattr(self, "orders_filter_from_var", None), ""),
            (getattr(self, "orders_filter_to_var", None), ""),
            (getattr(self, "orders_filter_status_var", None), "全部状态"),
            (getattr(self, "orders_filter_ai_var", None), "全部AI状态"),
            (getattr(self, "orders_filter_search_var", None), ""),
        ):
            if var is not None:
                var.set(default)
        self._on_orders_filter_changed()

    def _selected_order_ids(self) -> list[str]:
        tree = getattr(self, "orders_tree", None)
        return list(tree.selection()) if tree is not None else []

    def _on_orders_tree_open_detail(self, _event=None) -> None:
        """双击行 → 看详情（其他商品/多文件/原文/行项目）。"""
        ids = self._selected_order_ids()
        raw = self._orders_data.get(ids[0]) if ids else None
        if raw is not None:
            self._show_order_detail(raw)

    def _on_orders_tree_context_menu(self, event) -> None:
        """右键：未选中行先选中它，再弹「查看详情 / 删除选中」（深色 tk.Menu，同图层右键菜单）。"""
        tree = getattr(self, "orders_tree", None)
        if tree is None:
            return
        iid = tree.identify_row(event.y)
        if iid and iid not in tree.selection():
            tree.selection_set(iid)
        if not tree.selection():
            return
        menu = tk.Menu(
            tree, tearoff=0, bg=APP_COLORS["panel"], fg=APP_COLORS["text"],
            activebackground=APP_COLORS["accent"], activeforeground="#ffffff",
        )
        menu.add_command(label="查看详情", command=self._on_orders_tree_open_detail)
        menu.add_command(label="删除选中", command=self._on_delete_selected_orders)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _on_delete_selected_orders(self) -> None:
        """删除 Treeview 选中的订单（可多选）：确认一次 → 后台逐单删 → 本地移除（不整表重拉）。"""
        ids = self._selected_order_ids()
        if not ids:
            if getattr(self, "orders_status_var", None) is not None:
                self.orders_status_var.set("请先在表里选中要删除的订单（按住 Ctrl/Shift 可多选）。")
            return
        prompt = (
            f"确认删除订单 {ids[0]}？（不可逆）" if len(ids) == 1
            else f"确认删除选中的 {len(ids)} 个订单？（不可逆）"
        )
        if not messagebox.askyesno("删除订单", prompt):
            return
        url = self._inbox_service_url

        def work():
            done, failed = [], []
            for oid in ids:
                try:
                    inbox_client.delete_order(url, oid)
                    done.append(oid)
                except Exception as exc:  # 单个失败不连累其余
                    failed.append((oid, str(exc)))
            return done, failed

        def ok(result):
            done, failed = result
            for oid in done:
                self._remove_order_row_local(oid)
            msg = f"已删除 {len(done)} 单"
            if failed:
                msg += f"，{len(failed)} 单失败：{failed[0][1]}"
            self.orders_status_var.set(f"{msg} · 共 {len(self._orders_data)} 单")

        run_background(self.root, work, ok, lambda exc: self.orders_status_var.set(f"删除失败：{exc}"))

    # ── 订单删除 / 清理 / 保留设置 ────────────────────────────────────
    def _parse_retention_days(self) -> int | None:
        """读「保留天数」输入框，返回正整数；空/非法/<=0 返回 None。"""
        raw = (self.retention_days_var.get() or "").strip() if getattr(self, "retention_days_var", None) else ""
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _populate_retention(self, control: dict) -> None:
        """据服务端 retention_days 回填清理栏：>0 → 填天数 + 勾自动；0 → 取消勾选（不清用户已输入的天数）。"""
        if getattr(self, "retention_auto_var", None) is None:
            return
        days = 0
        try:
            days = int(control.get("retention_days") or 0)
        except (TypeError, ValueError):
            days = 0
        if days > 0:
            self.retention_days_var.set(str(days))
            self.retention_auto_var.set(True)
        else:
            self.retention_auto_var.set(False)

    def _on_retention_entry_changed(self) -> None:
        """天数框失焦：若「自动」已开，把新天数静默同步到服务端（已确认过一次，不再弹窗）。"""
        if getattr(self, "retention_auto_var", None) is not None and self.retention_auto_var.get():
            days = self._parse_retention_days()
            if days is not None:
                self._put_retention(days)

    def _on_apply_retention(self) -> None:
        """应用「自动删」设置：勾选则把保留天数写进服务端 retention_days（后台无人值守删）；取消则置 0。"""
        if getattr(self, "retention_auto_var", None) is None:
            return
        if self.retention_auto_var.get():
            days = self._parse_retention_days()
            if days is None:
                messagebox.showwarning("自动删除", "请先在「保留最近 __ 天」填一个正整数（如 30）再开启自动删除。")
                self.retention_auto_var.set(False)
                return
            if not messagebox.askyesno(
                "开启自动删除",
                f"将开启后台无人值守删除：inbox-service 会持续把超过 {days} 天的订单删掉，"
                f"含未完成/人工审核单，且 flower 关闭时也照删。\n\n确认开启？",
            ):
                self.retention_auto_var.set(False)
                return
            self._put_retention(days)
        else:
            self._put_retention(0)

    def _put_retention(self, days: int) -> None:
        """后台 PUT retention_days，成功后刷新订单表状态行。"""
        url = self._inbox_service_url
        run_background(
            self.root,
            lambda: inbox_client.put_scrape_control(url, retention_days=days),
            lambda _res: self.orders_status_var.set(
                f"已开启自动删除：保留最近 {days} 天" if days > 0 else "已关闭自动删除"
            ),
            lambda exc: self.orders_status_var.set(f"设置自动删除失败：{exc}"),
        )

    def _on_purge_orders_now(self) -> None:
        """「立即清理」：删除 N 天前的订单（手动，确认后台执行）。"""
        days = self._parse_retention_days()
        if days is None:
            messagebox.showwarning("立即清理", "请先在「保留最近 __ 天」填一个正整数（如 30）。")
            return
        if not messagebox.askyesno(
            "立即清理", f"将删除所有超过 {days} 天的订单（不可逆，含未完成单）。\n\n确认删除？"
        ):
            return
        url = self._inbox_service_url
        run_background(
            self.root,
            lambda: inbox_client.purge_orders(url, days),
            lambda res: (self.orders_status_var.set(f"已清理 {res.get('deleted_count', 0)} 单"), self._refresh_orders_table()),
            lambda exc: self.orders_status_var.set(f"清理失败：{exc}"),
        )

    def _confirm_delete_order(self, order_id: str, *, on_done=None) -> None:
        """删除单个订单（确认后台执行）。成功后**只删该行**（Level 1，不整表重拉重建）。
        on_done 用于详情弹窗删完关窗。"""
        if not messagebox.askyesno("删除订单", f"确认删除订单 {order_id}？（不可逆）"):
            return
        url = self._inbox_service_url

        def ok(_res):
            self._remove_order_row_local(order_id)
            self.orders_status_var.set(f"已删除 {order_id} · 共 {len(self._orders_data)} 单 · {url}")
            if on_done is not None:
                on_done()

        run_background(
            self.root,
            lambda: inbox_client.delete_order(url, order_id),
            ok,
            lambda exc: self.orders_status_var.set(f"删除失败：{exc}"),
        )

    def _remove_order_row_local(self, order_id: str) -> None:
        """删除成功后只移除该行 Treeview item + 缓存（不整表重拉）。"""
        tree = getattr(self, "orders_tree", None)
        if tree is not None and tree.exists(order_id):
            tree.delete(order_id)
        self._orders_data.pop(order_id, None)

    def _show_order_detail(self, order: dict) -> None:
        """点订单行弹出详情：状态/付款时间/退款 + 行项目（含其他商品）+ 原始备注（§8.2/§8.3）。"""
        view = order_row_view(order)
        win = self._themed_toplevel()
        win.title(f"订单详情 · {view['order_id']}")
        win.configure(fg_color=APP_COLORS["background"])
        win.geometry("460x420")
        wrap = ctk.CTkFrame(win, fg_color=APP_COLORS["panel"], corner_radius=10)
        wrap.pack(fill="both", expand=True, padx=12, pady=12)
        lines = [
            f"订单号：{view['order_id']}",
            f"店小秘状态：{view['shop_status'] or '未抓取'}",
            f"内部处理状态：{view['internal_label']}",
            f"付款时间：{view['paid_at']}",
            f"件数合计：{('×' + str(view['quantity'])) if view['quantity'] else '— （扩展暂未抓详情页行项目）'}",
            f"其他商品：{'有，请配货' if view['has_other_products'] else '无'}",
            "",
            "行项目：",
        ]
        items = order.get("items") or []
        if items:
            for it in items:
                tag = "目标盒子" if it.get("is_target_box", True) else "其他商品"
                sku = it.get("product_sku") or "（无 SKU）"
                lines.append(f"  · 行{it.get('line_index', '?')} [{tag}] ×{it.get('quantity', 1)} {sku}")
                pr = (it.get("personalization_raw") or "").strip()
                if pr:
                    lines.append(f"      备注：{pr}")
        else:
            lines.append("  （无行项目；Phase 1 详情页抓取后补全 件数/文件数/其他商品）")
        lines += ["", "原始备注（remark）：", (order.get("remark") or "—")]
        box = ctk.CTkTextbox(
            wrap, fg_color="#161616", text_color=APP_COLORS["text"],
            border_width=1, border_color=APP_COLORS["border"], wrap="word",
        )
        box.pack(fill="both", expand=True, padx=10, pady=10)
        box.insert("1.0", "\n".join(lines))
        box.configure(state="disabled")
        foot = ctk.CTkFrame(wrap, fg_color="transparent")
        foot.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(
            foot, text="删除此单", width=88, height=28, corner_radius=6,
            command=lambda oid=view["order_id"]: self._confirm_delete_order(oid, on_done=win.destroy),
            fg_color="#3d2422", hover_color="#5a2f2a", text_color="#e88a84", font=ctk.CTkFont(size=12),
        ).pack(side="right")

    def _build_production_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        # 「图层」卡属画布编辑器（实时画板 + 图层面板）：对三端开放（见 _VIEW_CARD_ORDER 的 production）。
        panel, body = self._ctk_card(parent, "图层")
        body.columnconfigure(0, weight=1)

        header = ctk.CTkFrame(body, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text="行内点 资源/👁/🔒/🗑 · 双击文字改内容 · 右键设属性", anchor="e",
            text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=10),
        ).grid(row=0, column=0, sticky="e")

        tree_wrap = ttk.Frame(body)
        tree_wrap.grid(row=1, column=0, sticky="ew")
        tree_wrap.columnconfigure(0, weight=1)
        self.layers_tree = ttk.Treeview(
            tree_wrap,
            columns=("asset", "visible", "pin", "delete"),
            show="tree headings",
            height=7,
            selectmode="extended",
        )
        # 「类型」列删掉：行首图标(T/▣/♥)已表类型；省下的宽度让内容列长出来、锁/删按钮永远靠右可见。
        # 「资源」列：图片层显素材名 / 文字层显字体名，点它弹库+素材/字体选择菜单（见 _open_layer_resource_picker）。
        self.layers_tree.heading("#0", text="图层")
        self.layers_tree.heading("asset", text="资源")
        self.layers_tree.heading("visible", text="👁")
        self.layers_tree.heading("pin", text="🔒")
        self.layers_tree.heading("delete", text="🗑")
        # #0 内容列 minwidth 调小，窄面板时优先压缩它，绝不挤掉右侧固定的 资源/👁/🔒/🗑。
        self.layers_tree.column("#0", width=140, minwidth=50, stretch=True)
        self.layers_tree.column("asset", width=78, minwidth=46, stretch=False, anchor="w")
        self.layers_tree.column("visible", width=34, minwidth=30, stretch=False, anchor="center")
        self.layers_tree.column("pin", width=38, minwidth=34, stretch=False, anchor="center")
        self.layers_tree.column("delete", width=38, minwidth=34, stretch=False, anchor="center")
        self.layers_tree.tag_configure("hidden", foreground=APP_COLORS["muted"])
        self.layers_tree.tag_configure("locked", foreground=APP_COLORS["muted"])
        self.layers_tree.tag_configure("pinned", foreground="#e3b34a")
        self.layers_tree.grid(row=0, column=0, sticky="ew")
        scrollbar = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.layers_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.layers_tree.configure(yscrollcommand=scrollbar.set)
        self.layers_tree.bind("<<TreeviewSelect>>", self._on_layers_tree_select)
        self.layers_tree.bind("<ButtonPress-1>", self._on_layers_tree_button_press)
        self.layers_tree.bind("<B1-Motion>", self._on_layers_tree_drag_motion)
        self.layers_tree.bind("<ButtonRelease-1>", self._on_layers_tree_button_release)
        self.layers_tree.bind("<Double-Button-1>", self._on_layer_list_double_click)
        self.layers_tree.bind("<Button-3>", self._show_layers_tree_context_menu)
        self.layers_tree.bind("<Button-2>", self._show_layers_tree_context_menu)
        self.layers_rows_box = None
        self._render_layers()

        action_row = ctk.CTkFrame(body, fg_color="transparent")
        action_row.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        action_row.columnconfigure(0, weight=1)
        # 暂时隐藏「通用图层」入口（不删功能，_add_universal_layer 保留，需要时取消注释即可恢复）。
        # self._btn(
        #     action_row, "+ 通用图层", self._add_universal_layer, primary=True
        # ).grid(row=0, column=1, padx=(0, 6))
        # Packet 2：合并「+ 文字图层 / + 图片图层」为单一「+ 添加图层」入口（修 P3 入口割裂）。
        # 点击弹原生 tk.Menu（文字/图片素材/空白内容层/普通组合/自动布局组合），各项复用现有
        # add_* / group_layers 处理器，不另写逻辑。组合项 <2 选层时置灰（复用右键同款 guard）。
        self._btn(
            action_row, "+ 添加图层", self._show_add_layer_menu, primary=True
        ).grid(row=0, column=3)

        library_box = ctk.CTkFrame(body, fg_color="transparent")
        library_box.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        library_box.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            library_box, text="资源库", anchor="w",
            text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11),
        ).grid(row=0, column=0, sticky="w")
        self._production_library_rows_frame = ctk.CTkFrame(library_box, fg_color="transparent")
        self._production_library_rows_frame.grid(row=1, column=0, sticky="ew")
        self._production_library_rows_frame.columnconfigure(0, weight=1)

        # 隐藏容器承载原四个全局选择器：parse/扫描/选库 全部联动仍依赖它们。
        # P1 暂不显示（已收进图层行示意）；P2 把库/素材/字体选择真正做进每个图层行后移除。
        hidden = ctk.CTkFrame(body, fg_color="transparent")
        self.image_library_combo = ctk.CTkOptionMenu(
            hidden, variable=self.image_library_var, values=["（无素材库）"],
            command=lambda _choice: self._on_image_library_selected(),
            fg_color=APP_COLORS["input"], button_color=APP_COLORS["accent"],
            button_hover_color=APP_COLORS["accent_soft"], text_color=APP_COLORS["text"],
        )
        self.flower_combo = ctk.CTkOptionMenu(
            hidden, variable=self.flower_asset_var, values=["（请扫描素材）"],
            command=lambda _choice: self._on_flower_combo_selected(),
            fg_color=APP_COLORS["input"], button_color=APP_COLORS["accent"],
            button_hover_color=APP_COLORS["accent_soft"], text_color=APP_COLORS["text"],
        )
        self.font_library_combo = ctk.CTkOptionMenu(
            hidden, variable=self.font_library_var, values=["（无字体库）"],
            command=lambda _choice: self._on_font_library_selected(),
            fg_color=APP_COLORS["input"], button_color=APP_COLORS["accent"],
            button_hover_color=APP_COLORS["accent_soft"], text_color=APP_COLORS["text"],
        )
        self.font_combo = ctk.CTkOptionMenu(
            hidden, variable=self.font_asset_var, values=["（请扫描字体）"],
            command=lambda _choice: self._on_font_combo_selected(),
            fg_color=APP_COLORS["input"], button_color=APP_COLORS["accent"],
            button_hover_color=APP_COLORS["accent_soft"], text_color=APP_COLORS["text"],
        )
        # 不 grid hidden：控件存在、可被 configure，但不出现在界面。
        return panel

    def _mini_option(self, parent, var, values):
        return ctk.CTkOptionMenu(
            parent, variable=var, values=values or ["—"], height=26, font=ctk.CTkFont(size=11),
            fg_color=APP_COLORS["background"], button_color=APP_COLORS["accent"],
            button_hover_color=APP_COLORS["accent_soft"], text_color=APP_COLORS["text"],
        )

    # ===== P1 字段提取引擎：辅助 =====
    def _ensure_field_vars(self, field: dict) -> None:
        """给字段挂上 StringVar（name/type/instruction/result），跨重渲染保值。"""
        if "name_var" in field:
            return
        field["name_var"] = tk.StringVar(value=field.get("name", ""))
        field["type_var"] = tk.StringVar(value=field.get("type", "文本"))
        field["inst_var"] = tk.StringVar(value=field.get("instruction", ""))
        field["result_var"] = tk.StringVar(value=self.field_results.get(field["key"], ""))

    def _field_chip(self, parent, text: str):
        # 序号短（#1~#99），窄 chip 贴合文字即可；padx 也收窄，把空间让给名称/结果框。
        return ctk.CTkLabel(
            parent, text=text, fg_color=APP_COLORS["accent_soft"], text_color="#7fa8ff",
            corner_radius=6, width=30, font=ctk.CTkFont(size=11),
        )

    def _build_fields_panel(self, parent) -> ctk.CTkFrame:
        """合并后的「字段」卡：一字段一张子卡（结果 + 提取规则）。只在管理员端显示（IP）。"""
        panel, body = self._ctk_card(parent, "字段", badge="仅管理员 · IP")
        self.fields_body = body
        self._render_fields()
        return panel

    def _render_fields(self) -> None:
        body = self.fields_body
        if body is None:
            return
        for child in body.winfo_children():
            child.destroy()
        body.columnconfigure(0, weight=1)
        for i, field in enumerate(self.field_defs):
            self._ensure_field_vars(field)
            card = ctk.CTkFrame(
                body, fg_color=APP_COLORS["input"], corner_radius=7,
                border_width=1, border_color=APP_COLORS["border"],
            )
            card.grid(row=i + 1, column=0, sticky="ew", pady=(0, 7))
            card.columnconfigure(0, weight=1)
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.grid(row=0, column=0, sticky="ew", padx=7, pady=(7, 3))
            # 名称(col1)与结果(col2)同 uniform 组，按 2:3 权重分剩余宽度 → 拉伸/缩窄比例不变，名称不再挤占结果。
            top.columnconfigure(1, weight=2, uniform="fieldrow")
            top.columnconfigure(2, weight=3, uniform="fieldrow")
            # chip 显示不可修改的固定序号；引用名称单独编辑，不能再依赖位置编号。
            self._field_chip(top, f"#{field.get('sequence_number', i + 1)}").grid(row=0, column=0, padx=(0, 4))
            name_entry = ctk.CTkEntry(
                top, textvariable=field["name_var"], width=60,
                fg_color=APP_COLORS["background"], border_color=APP_COLORS["border"],
                text_color=APP_COLORS["text"],
            )
            name_entry.grid(row=0, column=1, sticky="ew", padx=(0, 6))
            original_name = field["name_var"].get()
            name_entry.bind(
                "<Return>",
                lambda _e, key=field["key"], var=field["name_var"], original=original_name:
                self._save_reference_field_name(key, var, original, silent=False),
            )
            name_entry.bind(
                "<Escape>",
                lambda _e, var=field["name_var"], original=original_name: var.set(original),
            )
            name_entry.bind(
                "<FocusOut>",
                lambda _e, key=field["key"], var=field["name_var"], original=original_name:
                self._save_reference_field_name(key, var, original),
            )
            # 字段类型不再用下拉框选择；类型/约束统一写进下方「提取规则」提示词里。
            # 结果框只读：只显示 AI 解析回填的值（见 _apply_results_to_fields，映射 B「填X」），本就不可手输。
            result = ctk.CTkEntry(
                top, textvariable=field["result_var"], state="readonly", width=60,
                fg_color=APP_COLORS["background"],
                border_color=APP_COLORS["border"], text_color=APP_COLORS["text"],
            )
            # error 哨兵：结果为 error（不区分大小写）→ 标红（禁用「生成」的联动在 P3 接真值时做）。
            if field["result_var"].get().strip().lower() == "error":
                result.configure(border_color=APP_COLORS["warning"], text_color=APP_COLORS["warning"])
            result.grid(row=0, column=2, sticky="ew")
            # 去掉空壳「更多」选项：变量留空 → 按钮只显示 ↓ 箭头；选完动作把变量复位回空，文字不残留。
            more_var = tk.StringVar(value="")
            ctk.CTkOptionMenu(
                top,
                width=36,
                variable=more_var,
                values=("停用" if field.get("enabled", True) else "启用", "删除"),
                # 整控件并入卡片底色（input），按钮段不再用默认蓝 → 只剩 ↓ 图标；hover 时才提示可点。
                fg_color=APP_COLORS["input"], button_color=APP_COLORS["input"],
                button_hover_color=APP_COLORS["accent_soft"], text_color=APP_COLORS["text"],
                command=lambda action, key=field["key"], var=more_var:
                    (self._on_reference_field_more_action(key, action), var.set("")),
            ).grid(row=0, column=3, padx=(6, 0))
            # 规则较长（含对照表），用多行 Textbox 编辑；KeyRelease 同步进 inst_var、FocusOut 落盘。
            inst_box = ctk.CTkTextbox(
                card, height=78, fg_color=APP_COLORS["background"], wrap="word",
                border_width=1, border_color=APP_COLORS["border"], text_color=APP_COLORS["text"],
            )
            inst_box.grid(row=1, column=0, sticky="ew", padx=7, pady=(0, 7))
            inst_box.insert("1.0", field["inst_var"].get())
            inst_box.bind(
                "<KeyRelease>",
                lambda _e, f=field, b=inst_box: f["inst_var"].set(b.get("1.0", "end-1c")),
            )
            inst_box.bind("<FocusOut>", lambda _e: self._persist_prompts())
        self._btn(body, "添加字段 +", self._add_field).grid(
            row=len(self.field_defs) + 1, column=0, sticky="w", pady=(8, 0)
        )

    def _add_field(self) -> None:
        # 编号基于「现有字段数量」+1（chip 实时按位置显示 infoN），不再按点击次数累加。
        product = active_product(self.config)
        try:
            fields, seq_max, created = create_reference_field(
                product.reference_fields,
                field_seq_max=product.field_seq_max,
                scope_id=product.id,
                reference_name=f"字段{product.field_seq_max + 1}",
                prompt="",
            )
        except ValueError as exc:
            messagebox.showerror("添加字段", str(exc))
            return
        self.config = with_product_reference_fields(
            self.config,
            reference_fields=fields,
            field_seq_max=seq_max,
            prompt_template=self._append_field_to_template_if_empty(created),
            extraction_prompt=self._serialize_field_defs(),
            background_prompt=self._current_prompt_template_text(),
        )
        self._load_field_defs_into_self()
        self._on_field_changed()

    def _delete_field(self, key: str) -> None:
        self._on_reference_field_more_action(key, "删除")

    def _on_field_changed(self) -> None:
        # 字段增删 → 重渲染字段卡 + 落盘（字段就是提示词规则，改动要持久化）。
        self._render_fields()
        self._persist_prompts()

    def _save_reference_field_name(self, key: str, var: tk.StringVar, original: str, *, silent: bool = True) -> None:
        if var.get().strip() == original.strip():
            return
        product = active_product(self.config)
        try:
            updated_fields = rename_reference_field(
                product.reference_fields,
                key,
                var.get(),
                scope_id=product.id,
            )
        except DuplicateReferenceNameError as exc:
            var.set(original)
            self.status_var.set(f"字段名称未保存：{exc}")
            if silent:
                return
            self.status_var.set("字段名称保存失败")
            messagebox.showerror("字段名称", str(exc))
            return
        except ValueError as exc:
            var.set(original)
            self.status_var.set(f"字段名称未保存：{exc}")
            if silent:
                return
            self.status_var.set("字段名称保存失败")
            messagebox.showerror("字段名称", str(exc))
            return
        self.config = with_product_reference_fields(
            self.config,
            reference_fields=updated_fields,
            field_seq_max=product.field_seq_max,
            prompt_template=self._current_prompt_template_text(),
            extraction_prompt=self._serialize_field_defs(),
            background_prompt=self._current_prompt_template_text(),
        )
        self.status_var.set("字段名称已保存")
        self._load_field_defs_into_self()
        self._render_fields()
        save_config(self.config)

    def _on_reference_field_more_action(self, key: str, action: str) -> None:
        if action == "更多":
            return
        product = active_product(self.config)
        try:
            if action == "删除":
                updated_fields = soft_delete_reference_field(
                    product.reference_fields,
                    key,
                    templates=(self._current_prompt_template_text(),),
                )
            elif action in {"停用", "启用"}:
                updated_fields = set_reference_field_enabled(
                    product.reference_fields,
                    key,
                    action == "启用",
                    scope_id=product.id,
                )
            else:
                return
        except ReferenceConflictError as exc:
            messagebox.showerror("字段删除", f"字段仍被 {exc.reference_count} 个模板引用，不能删除。")
            return
        except ValueError as exc:
            messagebox.showerror("字段", str(exc))
            return
        self.config = with_product_reference_fields(
            self.config,
            reference_fields=updated_fields,
            field_seq_max=product.field_seq_max,
            prompt_template=self._current_prompt_template_text(),
            extraction_prompt=self._serialize_field_defs(),
            background_prompt=self._current_prompt_template_text(),
        )
        self.status_var.set("字段已更新")
        self._load_field_defs_into_self()
        self._render_fields()
        save_config(self.config)

    def _build_library_panel(self, parent) -> ctk.CTkFrame:
        # 「字体库 / 素材库」=资源库：归操作员配置端（见 _VIEW_CARD_ORDER 的 library）。
        # 「点击上传」位置不变，但逻辑改为「当场弹文件夹 → 当场导入 → 当场刷新」（见 upload_into_library），
        # 不再打开模态设置窗口，故可连续多次重新选择、切换文件夹而无需关窗口。
        panel, body = self._ctk_card(parent, "字体库 / 素材库")
        body.columnconfigure(0, weight=1)
        self._library_rows_frame = ctk.CTkFrame(body, fg_color="transparent")
        self._library_rows_frame.grid(row=0, column=0, sticky="ew")
        self._library_rows_frame.columnconfigure(0, weight=1)
        self._library_status_var = tk.StringVar(value="")
        ctk.CTkLabel(
            body, textvariable=self._library_status_var, anchor="w", justify="left",
            text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11), wraplength=290,
        ).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self._render_library_rows()
        return panel

    def _render_library_rows(self) -> None:
        """按当前 active_bundle 逐库渲染；同一份数据挂到配置卡和图层卡下方。"""
        frames = [
            frame for frame in (
                getattr(self, "_library_rows_frame", None),
                getattr(self, "_production_library_rows_frame", None),
            )
            if frame is not None
        ]
        if not frames:
            return
        groups = (
            ("font", "字体库", self.active_bundle.font_libraries),
            ("image", "素材库", self.active_bundle.image_libraries),
        )
        for frame in frames:
            for child in frame.winfo_children():
                child.destroy()
            row = 0
            for kind, prefix, libraries in groups:
                ctk.CTkLabel(
                    frame, text=prefix, anchor="w",
                    text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11, weight="bold"),
                ).grid(row=row, column=0, sticky="w", pady=(6 if row else 0, 2))
                row += 1
                if not libraries:
                    ctk.CTkLabel(frame, text=f"暂无{prefix}", anchor="w", text_color=APP_COLORS["muted"]).grid(
                        row=row, column=0, sticky="w", pady=1
                    )
                    row += 1
                for lib in libraries:
                    line = ctk.CTkFrame(frame, fg_color="transparent")
                    line.grid(row=row, column=0, sticky="ew", pady=1)
                    line.columnconfigure(0, weight=1)
                    name = Path(getattr(lib, "root", "")).name or getattr(lib, "name", "") or prefix
                    count = len(getattr(lib, "entries", ()))
                    ctk.CTkLabel(line, text=f"📁 {name}", anchor="w").grid(row=0, column=0, sticky="w")
                    ctk.CTkLabel(line, text=f"{count} 个", anchor="e", text_color=APP_COLORS["muted"]).grid(
                        row=0, column=1, sticky="e", padx=(8, 0)
                    )
                    row += 1
                self._btn(frame, f"+ 添加{prefix}", lambda k=kind: self.upload_into_library(k), width=110).grid(
                    row=row, column=0, sticky="w", pady=(3, 4)
                )
                row += 1

    def upload_into_library(self, kind: str) -> None:
        """卡片「点击上传」入口：选一个文件夹（库=文件夹），累加并入当前产品的对应库。

        kind: ``"font"`` | ``"image"``。只选文件夹（符合「库」语义），文件夹内支持的
        字体/素材/图片全部批量导入、不支持的自动跳过；选完即刷新、可连续再选。
        """
        title = "选择字体库文件夹" if kind == "font" else "选择素材库文件夹"
        path = filedialog.askdirectory(title=title)
        if path:
            self._add_library_folder(kind, Path(path))

    def _add_library_folder(self, kind: str, folder: Path | str) -> dict:
        """把一个文件夹累加并入当前产品的素材库/字体库（按路径去重），重扫并刷新 UI。

        统一导入流程：过滤有效文件 → 注册（写进产品库目录、落盘）→ 重扫 → 刷新。
        无支持文件时只提示、不改配置；底层扫描自带容错，坏文件不会中断整个流程。
        返回 ``{"imported", "skipped", "already"}`` 摘要，便于测试与状态展示。
        """
        folder = Path(folder)
        is_font = kind == "font"
        suffixes = IMPORTABLE_FONT_SUFFIXES if is_font else IMPORTABLE_ASSET_SUFFIXES
        kind_label = "字体" if is_font else "素材"
        valid, skipped = collect_importable_files(folder, suffixes)
        if not valid:
            messagebox.showwarning("导入", f"「{folder.name or folder}」下没有找到支持的{kind_label}文件。")
            self.status_var.set(f"未导入：该文件夹没有支持的{kind_label}文件")
            return {"imported": 0, "skipped": len(skipped), "already": False}

        product = active_product(self.config)
        image_dirs = list(product.image_library_dirs) or [Path(self.flower_dir_var.get())]
        font_dirs = list(product.font_library_dirs) or [Path(self.font_source_var.get())]
        target = font_dirs if is_font else image_dirs
        already = any(_paths_equal(folder, existing) for existing in target)
        if not already:
            target.append(folder)

        # 导入数按「真正进入候选的增量」算（与底层扫描的扩展名口径一致，避免口径漂移多报）。
        before = {asset.path for asset in (self.font_assets if is_font else self.flower_assets)}
        self.config = with_product_library_dirs(self.config, image_dirs, font_dirs)
        # 顶层单目录入口与首库对齐（_scan_assets 读它作 index0；首库保持原主目录，故这里是幂等同步）。
        self.flower_dir_var.set(str(image_dirs[0]))
        self.font_source_var.set(str(font_dirs[0]))
        save_config(self.config)
        self._scan_assets(show_errors=False)
        after = {asset.path for asset in (self.font_assets if is_font else self.flower_assets)}
        imported = len(after - before)
        self._render_library_rows()

        parts = [f"已导入 {imported} 个{kind_label}文件" if imported else f"未新增{kind_label}（可能已在库中）"]
        if skipped:
            parts.append(f"跳过 {len(skipped)} 个不支持的文件")
        if already:
            parts.append("该文件夹此前已添加，已重新扫描")
        summary = "；".join(parts)
        self.status_var.set(summary)
        if hasattr(self, "_library_status_var"):
            self._library_status_var.set(summary)
        return {"imported": imported, "skipped": len(skipped), "already": already}

    def _build_output_settings_panel(self, parent) -> ctk.CTkFrame:
        panel, body = self._ctk_card(parent, "输出设置")
        # 本卡是「标签 + 输入」两栏布局：标签列固定窄宽、不拉伸，输入列独占剩余宽度。
        # _ctk_card 默认给 col0 weight=1（适配单栏卡），此处必须改回 0；否则 col0/col1
        # 各分一半宽度 → 标签与控件之间出现大空档、输入框被挤窄、整排看着错位（间隔太宽）。
        body.columnconfigure(0, weight=0, minsize=64)
        body.columnconfigure(1, weight=1)
        ctk.CTkLabel(body, text="输出目录", anchor="w").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 8))
        dir_row = ctk.CTkFrame(body, fg_color="transparent")
        dir_row.grid(row=0, column=1, sticky="ew", pady=4)
        dir_row.columnconfigure(0, weight=1)
        ctk.CTkEntry(dir_row, textvariable=self.output_var).grid(row=0, column=0, sticky="ew")
        self._btn(dir_row, "选择", self.choose_output).grid(row=0, column=1, padx=(8, 0))
        ctk.CTkLabel(body, text="输出格式", anchor="w").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 8))
        fmt_row = ctk.CTkFrame(body, fg_color="transparent")
        fmt_row.grid(row=1, column=1, sticky="w", pady=4)
        for output_format, label in (("png", "PNG"), ("svg", "SVG"), ("dxf", "DXF")):
            # width=56：CTkCheckBox 默认整框宽 100，而「□ PNG」可见内容仅约 48，
            # 多出的 50 余像素全是框内死空白 → 三项被撑得很开。收到贴合内容的 56，
            # 配 padx=(0,8) 让 PNG/SVG/DXF 紧凑成一组、间距适中且清晰可见。
            ctk.CTkCheckBox(
                fmt_row, text=label, width=56, variable=self.output_format_vars[output_format],
                onvalue=True, offvalue=False, checkbox_width=18, checkbox_height=18,
                fg_color=APP_COLORS["accent"], hover_color=APP_COLORS["accent_soft"],
            ).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(body, text="文件名", anchor="w").grid(row=2, column=0, sticky="w", pady=4, padx=(0, 8))
        ctk.CTkEntry(
            body, textvariable=self.filename_template_var, placeholder_text="可填 GPT 识别的订单号字段",
        ).grid(row=2, column=1, sticky="ew", pady=4)
        # 状态 + 主操作「生成」：原底部「生产输出」栏已删，这里承接其唯一不重复的两项。
        action_row = ctk.CTkFrame(body, fg_color="transparent")
        action_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        action_row.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            action_row, textvariable=self.status_var, text_color=APP_COLORS["muted"], anchor="w",
            font=ctk.CTkFont(size=11), wraplength=200, justify="left",
        ).grid(row=0, column=0, sticky="ew")
        # 「生成」是主操作动作；输出卡在操作员与管理员两端都挂（管理员调规则后可直接生成验证）。
        self.confirm_button = self._btn(action_row, "生成", self.confirm_and_generate, primary=True, width=90)
        self.confirm_button.grid(row=0, column=1, sticky="e", padx=(8, 0))
        return panel

    def _build_background_prompt_panel(self, parent) -> ctk.CTkFrame:
        panel, body = self._ctk_card(parent, "背景提示词", badge="仅管理员 · IP")  # 只在管理员端显示（IP）
        body.columnconfigure(0, weight=1)
        self.background_prompt_text = ctk.CTkTextbox(
            body, height=54, fg_color=APP_COLORS["input"], text_color=APP_COLORS["text"],
            border_width=1, border_color=APP_COLORS["border"],
            undo=True, autoseparators=True, maxundo=-1,
        )
        self.background_prompt_text.grid(row=0, column=0, sticky="ew")
        saved = self._stored_prompt_template()
        if saved:
            self._render_template_into_editor(saved)
        self.background_prompt_text.bind("<FocusOut>", lambda _e: self._persist_prompts())
        self.background_prompt_text.bind("<KeyRelease>", self._on_prompt_template_keyrelease)
        self.background_prompt_text.bind("<Up>", self._on_prompt_template_up)
        self.background_prompt_text.bind("<Down>", self._on_prompt_template_down)
        self.background_prompt_text.bind("<Return>", self._on_prompt_template_return)
        self.background_prompt_text.bind("<Escape>", self._hide_slash_popup)
        return panel

    def _stored_prompt_template(self) -> str:
        product = active_product(self.config)
        return product.prompt_template or default_prompt_template(product.reference_fields, product.background_prompt)

    def _tag_prompt_reference(self, kind: str, ref_id: str, start: str, end: str) -> None:
        box = self.background_prompt_text
        if box is None:
            return
        raw = getattr(box, "_textbox", box)
        tag = ("ref::" if kind == "field" else "src::") + ref_id
        raw.tag_add(tag, start, end)
        raw.tag_add("chip", start, end)
        raw.tag_config("chip", foreground=APP_COLORS["accent"])

    def _render_template_into_editor(self, template: str) -> None:
        box = self.background_prompt_text
        if box is None:
            return
        box.delete("1.0", "end")
        product = active_product(self.config)
        for segment in iter_template_segments(template, fields=product.reference_fields, scope_id=product.id):
            if segment[0] == "text":
                box.insert("insert", segment[1])
                continue
            kind, ref_id, display = segment
            start = box.index("insert")
            box.insert("insert", display)
            self._tag_prompt_reference(kind, ref_id, start, box.index("insert"))
        getattr(box, "_textbox", box).edit_reset()  # 载入的模板不进 undo 栈，首个 Ctrl+Z 不会撤成空

    def _template_text_from_editor(self) -> str:
        box = self.background_prompt_text
        if box is None:
            return ""
        raw = getattr(box, "_textbox", box)
        output: list[str] = []
        active_ref: str | None = None
        for key, value, _index in raw.dump("1.0", "end-1c", tag=True, text=True):
            if key == "tagon" and (value.startswith("ref::") or value.startswith("src::")):
                if active_ref is None:
                    active_ref = value
                    if value.startswith("ref::"):
                        output.append(field_token(value.removeprefix("ref::")))
                    else:
                        output.append(system_token(value.removeprefix("src::")))
            elif key == "tagoff" and value == active_ref:
                active_ref = None
            elif key == "text" and active_ref is None:
                output.append(value)
        return "".join(output).strip()

    def _current_prompt_template_text(self) -> str:
        box = self.background_prompt_text
        if box is not None:
            return self._template_text_from_editor()
        return self._stored_prompt_template()

    def _append_field_to_template_if_empty(self, field: ReferenceField) -> str:
        current = self._current_prompt_template_text()
        if current:
            return current
        return field_token(field.id)

    def _prompt_reference_candidates(self, query: str = "") -> list[dict[str, str]]:
        product = active_product(self.config)
        query_norm = query.strip().casefold()
        source_label = "/" + SYSTEM_SOURCE_LABELS["order_information"]
        candidates = [
            {
                "label": source_label,
                "display_name": source_label,
                "ref_kind": "source",
                "ref_id": "order_information",
            }
        ]
        for field in active_reference_fields(product.reference_fields):
            candidates.append(
                {
                    "label": f"/#{field.sequence_number} {field.reference_name}",
                    "display_name": "/" + field.reference_name,
                    "ref_kind": "field",
                    "ref_id": field.id,
                }
            )
        if query_norm:
            candidates = [
                item for item in candidates
                if query_norm in item["label"].casefold() or query_norm in item["display_name"].casefold()
            ]
        return candidates

    def _on_prompt_template_keyrelease(self, event) -> None:
        if event.keysym in {"Up", "Down", "Return", "Escape"}:
            return
        self._update_slash_popup()  # 存盘交给 FocusOut，避免每键序列化+写盘

    def _slash_query_before_cursor(self) -> tuple[str, str] | None:
        # 锚定光标：只看光标下那个词（往左扫到空白/chip 边界/行首），不再 rfind 整行选错斜杠。
        box = self.background_prompt_text
        if box is None:
            return None
        line = box.get("insert linestart", "insert")
        query = slash_query_at_cursor(line, self._char_in_chip)
        if query is None:
            return None
        return f"insert - {len(query) + 1}c", query

    def _char_in_chip(self, col: int) -> bool:
        box = self.background_prompt_text
        if box is None:
            return False
        raw = getattr(box, "_textbox", box)
        return "chip" in raw.tag_names(box.index(f"insert linestart + {col} chars"))

    def _update_slash_popup(self) -> None:
        found = self._slash_query_before_cursor()
        if found is None:
            self._hide_slash_popup()
            return
        start, query = found
        self._slash_start_index = start
        self._slash_candidates = self._prompt_reference_candidates(query)
        self._slash_selected_index = min(self._slash_selected_index, max(len(self._slash_candidates) - 1, 0))
        self._render_slash_popup()

    def _render_slash_popup(self) -> None:
        box = self.background_prompt_text
        if box is None:
            return
        parent = box.master
        if self._slash_popup is not None:
            self._slash_popup.destroy()
        self._slash_popup = ctk.CTkFrame(parent, fg_color=APP_COLORS["panel"], border_width=1, border_color=APP_COLORS["border"])
        self._slash_popup.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        if not self._slash_candidates:
            ctk.CTkLabel(self._slash_popup, text="无结果", text_color=APP_COLORS["muted"]).grid(row=0, column=0, sticky="w", padx=8, pady=6)
            return
        for index, item in enumerate(self._slash_candidates[:8]):
            selected = index == self._slash_selected_index
            btn = self._btn(
                self._slash_popup,
                item["label"],
                lambda i=index: self._insert_slash_candidate(i),
                primary=selected,
                width=220,
            )
            btn.grid(row=index, column=0, sticky="ew", padx=4, pady=2)

    def _hide_slash_popup(self, _event=None):
        if self._slash_popup is not None:
            self._slash_popup.destroy()
            self._slash_popup = None
        return "break"

    def _on_prompt_template_up(self, _event=None):
        if self._slash_popup is None or not self._slash_candidates:
            return None
        self._slash_selected_index = max(0, self._slash_selected_index - 1)
        self._render_slash_popup()
        return "break"

    def _on_prompt_template_down(self, _event=None):
        if self._slash_popup is None or not self._slash_candidates:
            return None
        self._slash_selected_index = min(len(self._slash_candidates) - 1, self._slash_selected_index + 1)
        self._render_slash_popup()
        return "break"

    def _on_prompt_template_return(self, _event=None):
        if self._slash_popup is None or not self._slash_candidates:
            return None  # 无候选(含「无结果」)时放行 Enter，否则斜杠后换不了行
        self._insert_slash_candidate(self._slash_selected_index)
        return "break"

    def _insert_slash_candidate(self, index: int) -> None:
        box = self.background_prompt_text
        if box is None or not self._slash_candidates:
            return
        candidate = self._slash_candidates[max(0, min(index, len(self._slash_candidates) - 1))]
        # 先把 _slash_start_index（"insert - Nc" 相对式）锁成绝对坐标，再删；否则删完 insert 左移，
        # 二次解析会落到更左边，导致 chip 插错位并把相邻已有文字一起吃进字段标签。
        start = box.index(self._slash_start_index)
        box.delete(start, "insert")
        box.insert(start, candidate["display_name"])
        self._tag_prompt_reference(candidate["ref_kind"], candidate["ref_id"], start, box.index("insert"))
        self._hide_slash_popup()
        self._persist_prompts()

    def _build_generate_prompt_panel(self, parent) -> ctk.CTkFrame:
        # 解析可观测②：点「解析」后随本次操作自动刷新（显示实际发出的提示词全文，含 provider/model）；
        # 「预览」按钮仍可在解析前按当前字段拼一版预览。本卡只在管理员端显示（见 _VIEW_CARD_ORDER）。
        panel, body = self._ctk_card(parent, "本次提示词", badge="解析可观测②")
        body.columnconfigure(0, weight=1)
        self._btn(body, "预览", self._show_generated_prompt, primary=True).grid(
            row=0, column=0, sticky="w"
        )
        self.generated_prompt_text = ctk.CTkTextbox(
            body, height=110, fg_color="#161616", text_color=APP_COLORS["muted"],
            border_width=1, border_color=APP_COLORS["border"],
        )
        self.generated_prompt_text.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.generated_prompt_text.configure(state="disabled")
        return panel

    def _assemble_field_rules(self) -> str:
        """把「字段」区的提取规则拼成发给 API 的【提取规则】正文（每字段一行）。

        提示词规则全部来自前台可编辑的字段，本地不写死业务规则。
        """
        lines: list[str] = []
        for field in self.field_defs:
            name = (field["name_var"].get() if "name_var" in field else field.get("name", "")).strip()
            ftype = (field["type_var"].get() if "type_var" in field else field.get("type", "")).strip()
            inst = (field["inst_var"].get() if "inst_var" in field else field.get("instruction", "")).strip()
            if not inst:
                continue
            prefix = f"- {name}（{ftype}）：" if (name or ftype) else "- "
            lines.append(prefix + inst)
        return "\n".join(lines)

    @staticmethod
    def _field_dict_from_reference(field: ReferenceField) -> dict:
        return {
            "id": field.id,
            "key": field.id,
            "sequence_number": field.sequence_number,
            "name": field.reference_name,
            "type": field.field_type,
            "instruction": field.prompt,
            "enabled": field.enabled,
            "deleted_at": field.deleted_at,
            "sort_order": field.sort_order,
            "created_at": field.created_at,
            "updated_at": field.updated_at,
            "legacy_key": field.legacy_key,
        }

    @staticmethod
    def _legacy_json_from_reference_fields(fields: tuple[ReferenceField, ...]) -> str:
        items = [
            {
                "key": field.legacy_key or f"field{field.sequence_number}",
                "id": field.id,
                "name": field.reference_name,
                "type": field.field_type,
                "instruction": field.prompt,
                "sequence_number": field.sequence_number,
                "enabled": field.enabled,
                "deleted_at": field.deleted_at,
            }
            for field in fields
        ]
        return json.dumps(items, ensure_ascii=False)

    def _reference_fields_from_field_defs(self) -> tuple[ReferenceField, ...]:
        product = active_product(self.config)
        working_fields = list(product.reference_fields)
        fields: list[ReferenceField] = []
        for item in self.field_defs:
            field_id = str(item.get("id") or item.get("key") or "")
            existing = next((field for field in working_fields if field.id == field_id), None)
            if existing is None:
                continue
            name = item["name_var"].get() if "name_var" in item else str(item.get("name", ""))
            if name.strip() and name.strip() != existing.reference_name:
                try:
                    working_fields = list(rename_reference_field(tuple(working_fields), existing.id, name, scope_id=product.id))
                    existing = next(field for field in working_fields if field.id == field_id)
                except ValueError:
                    pass
            prompt = item["inst_var"].get() if "inst_var" in item else str(item.get("instruction", ""))
            field_type = item["type_var"].get() if "type_var" in item else str(item.get("type", "文本"))
            fields.append(update_reference_field_prompt((existing,), existing.id, prompt, scope_id=product.id)[0])
            fields[-1] = dataclasses.replace(fields[-1], field_type=field_type)
        # 软删字段不再回灌：删了就别回来。旧逻辑把 deleted_at 字段也 extend 回去，
        # 导致已删字段的提示词每次保存又写回配置、反复复活（用户根治诉求）。
        known = {field.id for field in fields}
        fields.extend(
            field for field in product.reference_fields
            if field.id not in known and not field.deleted_at
        )
        return tuple(sorted(fields, key=lambda field: (field.sort_order, field.sequence_number)))

    def _serialize_field_defs(self) -> str:
        """把字段定义序列化成 JSON 存进 product.extraction_prompt（admin 编辑后持久化）。"""
        items = []
        for field in self.field_defs:
            items.append({
                "key": field.get("key", ""),
                "name": field["name_var"].get() if "name_var" in field else field.get("name", ""),
                "type": field["type_var"].get() if "type_var" in field else field.get("type", "文本"),
                "instruction": field["inst_var"].get() if "inst_var" in field else field.get("instruction", ""),
            })
        return json.dumps(items, ensure_ascii=False)

    def _load_field_defs_into_self(self) -> None:
        """从当前产品配置（extraction_prompt 存的 JSON）载入字段；无/非法 JSON → 用默认完整规则。"""
        product = active_product(self.config)
        reference_fields = product.reference_fields
        if not reference_fields:
            raw = product.extraction_prompt or json.dumps(_default_field_defs(), ensure_ascii=False)
            reference_fields = reference_fields_from_legacy(raw, scope_id=product.id)
            prompt_template = product.prompt_template or default_prompt_template(reference_fields, product.background_prompt)
            self.config = with_product_reference_fields(
                self.config,
                reference_fields=reference_fields,
                field_seq_max=max((field.sequence_number for field in reference_fields), default=0),
                prompt_template=prompt_template,
                extraction_prompt=product.extraction_prompt or self._legacy_json_from_reference_fields(reference_fields),
                background_prompt=product.background_prompt,
            )
            product = active_product(self.config)
        self.field_defs = [self._field_dict_from_reference(field) for field in product.reference_fields if not field.deleted_at]
        self.field_seq = product.field_seq_max

    def _persist_prompts(self) -> None:
        """把「字段（提取规则）+ 背景提示词」存回当前产品配置并落盘（失焦/增删/切产品时触发）。"""
        reference_fields = self._reference_fields_from_field_defs()
        extraction = self._legacy_json_from_reference_fields(reference_fields)
        prompt_template = self._current_prompt_template_text()
        product = active_product(self.config)
        if (
            extraction == product.extraction_prompt
            and prompt_template == product.prompt_template
            and reference_fields == product.reference_fields
        ):
            return  # 无变化不写盘
        self.config = with_product_reference_fields(
            self.config,
            reference_fields=reference_fields,
            field_seq_max=product.field_seq_max,
            prompt_template=prompt_template,
            extraction_prompt=extraction,
            background_prompt=prompt_template,
        )
        save_config(self.config)

    def _load_prompts_into_widgets(self) -> None:
        """切产品后：把新产品的字段定义 + 背景提示词载入控件。"""
        self._load_field_defs_into_self()
        for field in self.field_defs:
            self._ensure_field_vars(field)
        if self.fields_body is not None:
            self._render_fields()
        box = self.background_prompt_text
        if box is None:
            return
        prompt_template = self._stored_prompt_template()
        if prompt_template:
            self._render_template_into_editor(prompt_template)

    def _show_generated_prompt(self) -> None:
        """预览真正会发给 API 的内容：字段规则 + 订单文本原样拼接（订单文本不再加 <order_data> 包裹）。"""
        remark = self._current_remark_text().strip()
        product = active_product(self.config)
        template = self._current_prompt_template_text()
        try:
            resolved = resolve_prompt_template(
                template,
                scope_id=product.id,
                fields=product.reference_fields,
                order_information=remark,
            )
            text = resolved.final_prompt or "（空）"
        except PromptReferenceError as exc:
            text = f"[error]\n{exc}"
        box = self.generated_prompt_text
        if box is not None:
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("1.0", text)
            box.configure(state="disabled")
        

    def _current_remark_text(self) -> str:
        if self.remark_text is not None:
            text = self.remark_text.get("1.0", "end-1c")
            self.remark_var.set(text)
            return text
        return self.remark_var.get()

    def _set_remark_text(self, value: str) -> None:
        self.remark_var.set(value)
        if self.remark_text is not None:
            self.remark_text.delete("1.0", "end")
            self.remark_text.insert("1.0", value)

    def clear_remark(self) -> None:
        self._set_remark_text("")
        self.last_parse_result = None
        self.personalization_type_var.set("unknown")
        self.confidence_var.set("Readiness: -")
        self._set_warnings(["等待解析；识别结果不会自动生成最终文件。"])

    def _start_inbox_poller(self) -> None:
        """启动收件夹监听（automation 一期）。

        外部本地服务把店小秘订单写成 {order_id}.json 投进 ``config.inbox_folder``；
        这里用 Tk ``after`` 轮询，发现新文件就自动载入备注并（按配置）解析，但**永远停在生成前**
        ——由操作员复核后手点「生成」。``inbox_folder`` 未配置时整段为空操作，对现有用户零影响。
        """
        # 幂等：若已有续约在跑（如启动已自动起、面板再点「开始」），先取消，避免叠加多个 after 循环。
        if self._inbox_after_id is not None:
            try:
                self.root.after_cancel(self._inbox_after_id)
            except Exception:
                pass
            self._inbox_after_id = None
        folder = str(self.config.inbox_folder).strip()
        # Path("") 会被规范化成 "."；空字符串与 "." 都视为「未配置/功能关」。
        if folder in ("", "."):
            return
        self._inbox_dir = Path(folder)
        self._inbox_processed_dir = self._inbox_dir / "processed"
        self._poll_inbox_once()

    def _stop_inbox_poller(self) -> None:
        """停止收件夹监听：取消待续约的 after，轮询链即断（不动 _inbox_dir，避免影响生成后放行下一单的逻辑）。"""
        if self._inbox_after_id is not None:
            try:
                self.root.after_cancel(self._inbox_after_id)
            except Exception:
                pass
            self._inbox_after_id = None

    def _poll_inbox_once(self) -> None:
        """每秒扫一次收件夹；始终载入「最新送达」的订单（按文件修改时间）。

        新文件一到即**覆盖**当前应用内订单信息与文件名（由 _auto_load_order 重写两个框）；
        被覆盖的旧当前单（未点「生成」）移入 processed/ 丢弃。操作员点「生成」后由
        _advance_inbox_after_generate 把当前单移入 processed 再放行下一单。
        """
        inbox_dir = self._inbox_dir
        if inbox_dir is None:
            return
        try:
            if inbox_dir.is_dir():
                pending = list(inbox_dir.glob("*.json"))
                if pending:
                    # 最新送达：mtime 最大，名字作并列兜底。
                    newest = max(pending, key=lambda p: (p.stat().st_mtime, p.name))
                    if self._inbox_active is None or newest != self._inbox_active:
                        # 新文件抢占：把被覆盖的旧当前单（未生成）移入 processed 丢弃。
                        if self._inbox_active is not None:
                            self._move_inbox_file_to_processed(self._inbox_active)
                        self._inbox_active = newest
                        self.root.after(0, self._auto_load_order, newest)
        except tk.TclError:
            return  # 窗口销毁中，停止续约
        except Exception:
            LOGGER.exception("收件夹轮询失败")
        try:
            self._inbox_after_id = self.root.after(1000, self._poll_inbox_once)
        except tk.TclError:
            self._inbox_after_id = None

    def _auto_load_order(self, path: Path) -> None:
        """主线程：载入收件夹里『当前这一单』的备注并（按 inbox_autoparse）解析，停在生成前。

        不移动文件——待操作员点「生成」成功后，由 _advance_inbox_after_generate 移入 processed 并放行下一单。
        """
        if not path.exists():
            self._inbox_active = None
            return
        try:
            order = load_order_from_file(path)
        except (OSError, ValueError) as exc:
            self._set_warnings([f"自动载入订单失败（{path.name}）：{exc}"])
            self._move_inbox_file_to_processed(path)  # 坏文件挪走，别堵住队列
            self._inbox_active = None
            return
        remark = " ".join(order.remark.split())
        order_id = order.order_id.strip()
        # 订单号置顶为第 1 行（对齐解析器「订单块首行=订单号」约定），其后接产品规格备注。
        self._set_remark_text(f"{order_id}\n{remark}" if order_id else remark)
        # 订单号同时写进「文件名」框（该框即导出文件名来源，按订单号命名）。
        if order_id:
            self.filename_template_var.set(order_id)
        self._set_warnings([])
        self.status_var.set(f"📥 已载入订单 {path.stem}（复核后点「生成」，将自动载入下一单）")
        self._refresh_fetch_status()  # 「抓取订单」面板的「当前单」随之更新
        if self.config.inbox_autoparse:
            self.parse_remark()  # 自动解析（后台线程）；绝不自动生成

    def _move_inbox_file_to_processed(self, path: Path) -> None:
        """把已载入的订单文件移入 inbox/processed/，避免重启后重复触发。"""
        processed_dir = self._inbox_processed_dir
        if processed_dir is None:
            return
        try:
            processed_dir.mkdir(parents=True, exist_ok=True)
            target = processed_dir / path.name
            index = 1
            while target.exists():
                target = processed_dir / f"{path.stem}-{index}{path.suffix}"
                index += 1
            path.replace(target)
        except OSError:
            LOGGER.exception("移动收件夹订单文件失败：%s", path)

    def _advance_inbox_after_generate(self) -> None:
        """生成成功后：把当前收件夹订单移入 processed/ 并放行下一单（无当前单则空操作）。"""
        active = self._inbox_active
        if active is None:
            return
        self._inbox_active = None
        self._move_inbox_file_to_processed(active)

    # ── 库驱动载单（2026-06-22）：订单信息框统一从 inbox-service 库里取「第一条未被逻辑删除的订单」（FIFO 最旧先做）──

    def _start_db_order_poller(self) -> None:
        """启动「库驱动载单」轮询：后台周期性取库中最旧的未删订单，第一条变了就覆盖订单信息框。

        幂等：已有轮询在跑则先取消，避免叠加多个 after 循环。服务未起/空库不报错，下一轮自愈。
        """
        if self._db_order_after_id is not None:
            try:
                self.root.after_cancel(self._db_order_after_id)
            except Exception:
                pass
            self._db_order_after_id = None
        # 首轮也延后一个间隔（用 after 调度，不在构造期同步起后台线程）：不抢启动资源，且 headless 测试
        # 不跑 mainloop 时这个 after 永不触发、不会泄漏线程。真机 mainloop 一转即按间隔开始轮询。
        self._schedule_next_db_poll()

    def _stop_db_order_poller(self) -> None:
        """停止库轮询：取消待续约的 after（关闭 App 时调）。"""
        if self._db_order_after_id is not None:
            try:
                self.root.after_cancel(self._db_order_after_id)
            except Exception:
                pass
            self._db_order_after_id = None

    def _poll_db_order_once(self) -> None:
        """查一次库中「最旧的待生成订单」（FIFO 队首：未软删 + ai_status=pending）；队首相对上次变了才覆盖订单信息框。

        HTTP 走后台线程不卡 UI；服务不可达/无待生成单 → 静默保持当前内容（不清空、不冲掉操作员正在编辑的单），
        下一轮再试。生成成功后该单 ai_status→recognized（DB+店小秘都打「AI已处理」）自动掉出队列，队首前进到
        下一条未生成单，本轮即载入它（订单不删除，仍留在订单表里带「AI已处理」标）。
        """
        url = self._inbox_service_url

        def work():
            return inbox_client.fetch_next_pending_order(url)

        def done(order):
            if isinstance(order, dict):
                oid = (order.get("order_id") or "").strip()
                # reload-on-change：仅当队首订单号变化才覆盖，避免每轮重刷同一单冲掉操作员编辑。
                if oid and oid != self._db_order_active_id:
                    self._load_db_order(order)
            self._schedule_next_db_poll()

        def err(_exc):
            # fetch_next_pending_order 已吞掉网络/HTTP 错误回 None，这里兜底保证轮询不中断。
            self._schedule_next_db_poll()

        run_background(self.root, work, done, err)

    def _schedule_next_db_poll(self) -> None:
        try:
            self._db_order_after_id = self.root.after(DB_ORDER_POLL_INTERVAL_MS, self._poll_db_order_once)
        except tk.TclError:
            self._db_order_after_id = None  # 窗口销毁中，停止续约

    def _load_db_order(self, order: dict) -> None:
        """把库订单 dict 载入订单信息框 + 文件名框（订单号置顶为第 1 行，对齐解析器「订单块首行=订单号」约定）。

        与旧 _auto_load_order 行为对齐：设当前订单号（供标记回写/文件名兜底）、按 inbox_autoparse 决定是否自动解析；
        绝不自动「生成」。备注取顶层 remark，空则回退 items[].personalization_raw（标品单 remark 可为空）。
        """
        imported = order_from_payload(order)
        order_id = imported.order_id.strip()
        remark = " ".join(imported.remark.split())
        self._db_order_active_id = order_id or None
        self._db_order_piece_count = target_box_piece_count(order)  # 一单多件时供文件名「-k」后缀
        # 已知库订单号 → 写进 current_order_number，供生成后标记回写 + 文件名兜底（即便不自动解析也成立）。
        if order_id:
            self.current_order_number = order_id
            self.filename_template_var.set(order_id)
            self._update_piece_filename()  # 多件库单：把文件名刷成 订单号-1，逐笔切换/生成时各自后缀
        self._set_remark_text(f"{order_id}\n{remark}" if order_id else remark)
        self._set_warnings([])
        self.status_var.set(f"📥 已从库载入订单 {order_id or '(无单号)'}（复核后点「生成」；生成成功后自动载入下一单）")
        self._refresh_fetch_status()  # 「抓取订单」面板的「当前单」随之更新
        if self.config.inbox_autoparse:
            self.parse_remark()  # 自动解析（后台线程）；绝不自动生成

    def open_settings(self) -> None:
        window = self._themed_toplevel()
        window.title("设置")
        window.transient(self.root)
        window.grab_set()
        notebook = ttk.Notebook(window)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)
        self._build_asset_settings_tab(notebook)
        self._build_font_settings_tab(notebook)
        self._build_output_settings_tab(notebook)
        self._build_ai_settings_tab(notebook)
        button_row = ttk.Frame(window)
        button_row.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(button_row, text="保存", command=lambda: self._save_settings_window(window)).pack(side="right")
        ttk.Button(button_row, text="取消", command=window.destroy).pack(side="right", padx=(0, 8))

    def _build_asset_settings_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text="素材库")
        frame.columnconfigure(1, weight=1)
        # 旧单目录入口（迁移兼容，作主库目录；单目录选择器即时生效）。
        self._add_path_row(frame, 0, "素材目录", self.flower_dir_var, self.choose_flower_dir)
        # 增量5：当前产品的素材库目录列表（多库），与上面主目录一起进 bundle。
        ttk.Label(frame, text="产品素材库目录（多库）").grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 2))
        self.settings_image_listbox = self._build_library_dirs_editor(
            frame, 2, active_product(self.config).image_library_dirs, image=True
        )
        ttk.Button(frame, text="重新扫描", command=lambda: self._scan_assets(show_errors=True)).grid(
            row=4, column=1, sticky="e", pady=8
        )

    def _build_font_settings_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text="字体库")
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="字体文件/目录").grid(row=0, column=0, sticky="w", pady=4)
        row_frame = ttk.Frame(frame)
        row_frame.grid(row=0, column=1, sticky="ew", pady=4)
        row_frame.columnconfigure(0, weight=1)
        ttk.Entry(row_frame, textvariable=self.font_source_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(row_frame, text="选择字体", command=self.choose_font_source).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(frame, text="产品字体库目录（多库）").grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 2))
        self.settings_font_listbox = self._build_library_dirs_editor(
            frame, 2, active_product(self.config).font_library_dirs, image=False
        )
        ttk.Button(frame, text="重新扫描", command=lambda: self._scan_assets(show_errors=True)).grid(
            row=4, column=1, sticky="e", pady=8
        )

    def _build_library_dirs_editor(self, parent, start_row: int, dirs, *, image: bool) -> tk.Listbox:
        """增量5：库目录列表编辑器（Listbox + 添加/删除）；返回 Listbox 供保存时读回。"""
        listbox = tk.Listbox(
            parent,
            height=4,
            exportselection=False,
            bg=APP_COLORS["input"],
            fg=APP_COLORS["text"],
            selectbackground=APP_COLORS["accent"],
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground=APP_COLORS["border"],
            relief="flat",
            borderwidth=0,
        )
        listbox.grid(row=start_row, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        for path in dirs:
            listbox.insert("end", str(path))
        btn_row = ttk.Frame(parent)
        btn_row.grid(row=start_row + 1, column=0, columnspan=2, sticky="w")
        ttk.Button(btn_row, text="添加目录", command=lambda: self._add_library_dir(listbox, image=image)).pack(side="left")
        ttk.Button(btn_row, text="删除选中", command=lambda: self._remove_library_dir(listbox)).pack(
            side="left", padx=(8, 0)
        )
        return listbox

    def _add_library_dir(self, listbox: tk.Listbox, *, image: bool) -> None:
        path = filedialog.askdirectory(title="选择素材库目录" if image else "选择字体库目录")
        if path and path not in listbox.get(0, "end"):
            listbox.insert("end", path)

    def _remove_library_dir(self, listbox: tk.Listbox) -> None:
        for index in reversed(listbox.curselection()):
            listbox.delete(index)

    def _library_listbox_dirs(self, listbox: tk.Listbox | None, fallback_var: tk.StringVar) -> list[Path]:
        """读列表框里的库目录；为空则回落到单目录入口。"""
        if listbox is None:
            return [Path(fallback_var.get())]
        dirs = [Path(value) for value in listbox.get(0, "end") if value]
        return dirs or [Path(fallback_var.get())]

    def _build_ai_settings_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text="AI 识别")
        profile = active_ai_profile(self.config)
        self.ai_provider_var = tk.StringVar(value=profile.provider)
        self.ai_model_var = tk.StringVar(value=profile.model)
        self.ai_base_url_var = tk.StringVar(value=profile.base_url)
        self.ai_api_key_env_var = tk.StringVar(value=profile.api_key_env_var)
        self.ai_project_env_var = tk.StringVar(value=profile.project_env_var)
        self.ai_org_env_var = tk.StringVar(value=profile.org_env_var)
        # 解析已全局走 AI（本地规则停用）；原「AI 优先」开关→只读说明，现按用户要求一并注释移除（保留可恢复）。
        # ttk.Label(
        #     frame, text="解析始终使用 AI 识别（本地规则已停用，请配置好下方 API Key）",
        # ).grid(row=0, column=0, columnspan=2, sticky="w", pady=4)
        provider_combo = ttk.Combobox(frame, textvariable=self.ai_provider_var, values=("openai", "deepseek"), state="readonly")
        provider_combo.bind("<<ComboboxSelected>>", self._on_ai_provider_change)
        self._add_row(frame, 1, "服务商", provider_combo)
        self._add_row(frame, 2, "模型", ttk.Entry(frame, textvariable=self.ai_model_var))
        self._add_row(frame, 3, "Base URL", ttk.Entry(frame, textvariable=self.ai_base_url_var))
        self._add_row(frame, 4, "API Key 环境变量", ttk.Entry(frame, textvariable=self.ai_api_key_env_var))
        self._add_row(frame, 5, "Project 环境变量", ttk.Entry(frame, textvariable=self.ai_project_env_var))
        self._add_row(frame, 6, "Org 环境变量", ttk.Entry(frame, textvariable=self.ai_org_env_var))
        self._add_row(frame, 7, "临时 API Key", ttk.Entry(frame, textvariable=self.session_api_key_var, show="*"))
        ttk.Button(frame, text="测试连接", command=self.test_ai_connection).grid(row=8, column=1, sticky="e", pady=8)

    def _on_ai_provider_change(self, _event=None) -> None:
        provider = self.ai_provider_var.get().strip().casefold()
        # 切换服务商时只填默认值，不写入 API Key，避免敏感信息落盘。
        if provider == "deepseek":
            if self.ai_model_var.get().strip() in {"", DEFAULT_MODEL}:
                self.ai_model_var.set(DEFAULT_DEEPSEEK_MODEL)
            if not self.ai_base_url_var.get().strip():
                self.ai_base_url_var.set(DEFAULT_DEEPSEEK_BASE_URL)
            if self.ai_api_key_env_var.get().strip() in {"", "OPENAI_API_KEY"}:
                self.ai_api_key_env_var.set("DEEPSEEK_API_KEY")
            if self.ai_project_env_var.get().strip() == "OPENAI_PROJECT":
                self.ai_project_env_var.set("")
            if self.ai_org_env_var.get().strip() == "OPENAI_ORG_ID":
                self.ai_org_env_var.set("")
        elif provider == "openai":
            if self.ai_model_var.get().strip() in {"", DEFAULT_DEEPSEEK_MODEL}:
                self.ai_model_var.set(DEFAULT_MODEL)
            if self.ai_base_url_var.get().strip() == DEFAULT_DEEPSEEK_BASE_URL:
                self.ai_base_url_var.set("")
            if self.ai_api_key_env_var.get().strip() in {"", "DEEPSEEK_API_KEY"}:
                self.ai_api_key_env_var.set("OPENAI_API_KEY")
            if not self.ai_project_env_var.get().strip():
                self.ai_project_env_var.set("OPENAI_PROJECT")
            if not self.ai_org_env_var.get().strip():
                self.ai_org_env_var.set("OPENAI_ORG_ID")

    def _build_output_settings_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text="输出设置")
        ttk.Label(frame, text="输出格式").grid(row=0, column=0, sticky="w", pady=4)
        format_row = ttk.Frame(frame)
        format_row.grid(row=0, column=1, sticky="w", pady=4)
        for output_format, label in (("png", "PNG"), ("svg", "SVG"), ("dxf", "DXF")):
            ttk.Checkbutton(format_row, text=label, variable=self.output_format_vars[output_format]).pack(
                side="left", padx=(0, 8)
            )
        self._add_path_row(frame, 1, "输出路径", self.output_var, self.choose_output)
        resolution_group = ttk.LabelFrame(frame, text="输出分辨率", padding=8)
        resolution_group.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        resolution_group.columnconfigure(1, weight=1)
        for row, (label, key) in enumerate((("画布宽", "canvas_width"), ("画布高", "canvas_height"))):
            ttk.Label(resolution_group, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(resolution_group, textvariable=self.layout_vars[key], width=12).grid(
                row=row, column=1, sticky="ew", pady=3
            )
        png_bg_group = ttk.LabelFrame(frame, text="PNG 背景", padding=8)
        png_bg_group.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        ttk.Radiobutton(
            png_bg_group,
            text="镂空（透明底，仅保留花/字墨迹，激光雕刻背景不出刀）",
            value="transparent",
            variable=self.png_background_var,
        ).grid(row=0, column=0, sticky="w", pady=2)
        ttk.Radiobutton(
            png_bg_group,
            text="正常（白色实心底，适合普通查看 / 打印）",
            value="white",
            variable=self.png_background_var,
        ).grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(
            frame,
            text="识别结果不会自动生成最终文件；确认字段后需在主界面点击「生成」按钮才会输出。",
            wraplength=420,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
        frame.columnconfigure(1, weight=1)

    def _build_layout_settings_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text="布局模板")
        ttk.Label(frame, text="当前版本提供项目默认布局恢复；多模板管理保留为后续扩展。").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Button(frame, text="恢复项目默认布局", command=self._reset_layout).grid(row=1, column=0, sticky="w")

    def _save_settings_window(self, window: tk.Toplevel) -> None:
        profile = self._settings_ai_profile()
        layout_defaults = self._active_layout_defaults()
        # 用 replace 而非整体重建，避免清空 products / active_product_id / 产品列收展状态。
        self.config = dataclasses.replace(
            self.config,
            flower_dir=Path(self.flower_dir_var.get()),
            font_source=Path(self.font_source_var.get()),
            output_path=Path(self.output_var.get()),
            output_formats=self._selected_output_formats_or_default(),
            png_background=self.png_background_var.get(),
            ai_profiles=(profile,),
            active_ai_profile=profile.name,
        )
        self.config = with_product_defaults(self.config, layout_defaults)
        # 增量5：把设置窗口里编辑的产品库目录列表写回当前产品（列表为空则回落单目录入口）。
        image_dirs = self._library_listbox_dirs(self.settings_image_listbox, self.flower_dir_var)
        font_dirs = self._library_listbox_dirs(self.settings_font_listbox, self.font_source_var)
        self.config = with_product_library_dirs(self.config, image_dirs, font_dirs)
        # 单目录入口与首库目录对齐（_scan_assets / 旧链路读它）。
        self.flower_dir_var.set(str(image_dirs[0]))
        self.font_source_var.set(str(font_dirs[0]))
        save_config(self.config)
        self._scan_assets(show_errors=True)
        self.status_var.set("设置已保存")
        window.destroy()


    def open_layout_settings(self) -> None:
        """打开全局默认布局设置；这些值只用于之后新建图层，不回写已有图层。"""
        window = self._themed_toplevel()
        window.title("布局设置")
        window.transient(self.root)
        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)
        # 显示文案用"素材/文字";"字体"一词保留给 optionNo 字体编号体系,避免混淆。
        fields = (
            ("画布宽", "canvas_width"),
            ("画布高", "canvas_height"),
            ("素材_x", "flower_x"),
            ("素材_y", "flower_y"),
            ("素材_宽", "flower_width"),
            ("素材_高", "flower_height"),
            ("文字_x", "text_x"),
            ("文字_y", "text_y"),
            ("文字_宽", "text_width"),
            ("文字_高", "text_height"),
            ("文字_字号", "text_size"),
        )
        dialog_vars = {key: tk.StringVar(value=self.layout_vars[key].get()) for _label, key in fields}
        dlg_bold = tk.BooleanVar(value=self.font_bold_var.get())
        dlg_underline = tk.BooleanVar(value=self.font_underline_var.get())
        dlg_strength = tk.StringVar(value=self.bold_strength_var.get())
        dlg_spacing = tk.StringVar(value=self.letter_spacing_var.get())
        for row, (label, key) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(frame, textvariable=dialog_vars[key], width=14).grid(row=row, column=1, sticky="ew", pady=3)

        # —— 输出物理尺寸:读写模板 exportSettings.physical,与批量生成同一数据源 ——
        base_row = len(fields)
        phys_width_var = tk.StringVar()
        phys_height_var = tk.StringVar()
        phys_unlock_var = tk.BooleanVar(value=False)
        phys_ratio = 1.0
        phys_available = True
        try:
            phys = load_template_physical_size()
            phys_ratio = phys.canvas_height / phys.canvas_width
            phys_width_var.set(f"{phys.width_mm:g}")
            phys_height_var.set(f"{phys.height_mm:g}")
            phys_unlock_var.set(not phys.height_derived)
        except Exception as exc:  # 模板缺失时布局功能仍可用,只禁用尺寸区
            phys_available = False
            LOGGER.warning("物理尺寸读取失败: %s", exc)
        ttk.Separator(frame, orient="horizontal").grid(
            row=base_row, column=0, columnspan=2, sticky="ew", pady=(10, 6)
        )
        ttk.Label(frame, text="输出宽度(mm)").grid(row=base_row + 1, column=0, sticky="w", pady=3)
        phys_width_entry = ttk.Entry(frame, textvariable=phys_width_var, width=14)
        phys_width_entry.grid(row=base_row + 1, column=1, sticky="ew", pady=3)
        ttk.Label(frame, text="输出高度(mm)").grid(row=base_row + 2, column=0, sticky="w", pady=3)
        phys_height_entry = ttk.Entry(frame, textvariable=phys_height_var, width=14)
        phys_height_entry.grid(row=base_row + 2, column=1, sticky="ew", pady=3)

        def sync_height_state(*_args) -> None:
            if phys_unlock_var.get():
                phys_height_entry.configure(state="normal")
                return
            phys_height_entry.configure(state="readonly")
            try:
                width = float(phys_width_var.get())
                phys_height_var.set(f"{width * phys_ratio:g}")
            except ValueError:
                phys_height_var.set("")

        unlock_check = ttk.Checkbutton(
            frame,
            text="解锁比例(默认高度随画布宽高比联动)",
            variable=phys_unlock_var,
            command=sync_height_state,
        )
        unlock_check.grid(row=base_row + 3, column=0, columnspan=2, sticky="w", pady=(2, 0))
        if phys_available:
            phys_width_var.trace_add("write", sync_height_state)
            sync_height_state()
        else:
            for widget in (phys_width_entry, phys_height_entry, unlock_check):
                widget.configure(state="disabled")

        ttk.Label(
            frame,
            text=(
                "保存后的全局默认值只会初始化新建图层，不会覆盖已有图层的位置和大小。\n"
                "输出物理尺寸保存进产品模板，批量生成与按钮导入立即生效。"
            ),
            style="Status.TLabel",
            wraplength=360,
        ).grid(row=base_row + 4, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        frame.columnconfigure(1, weight=1)

        def apply_values(close: bool = False) -> None:
            try:
                layout = layout_from_values(dialog_vars)
            except ValueError as exc:
                messagebox.showerror("布局设置", str(exc))
                return
            if phys_available:
                try:
                    width_mm = float(phys_width_var.get())
                    height_mm = float(phys_height_var.get()) if phys_unlock_var.get() else None
                except ValueError:
                    messagebox.showerror("布局设置", "输出物理尺寸必须是正数(毫米)。")
                    return
                try:
                    save_template_physical_size(width_mm, height_mm)
                except Exception as exc:
                    messagebox.showerror("布局设置", f"物理尺寸保存失败：{exc}")
                    return
            self._set_layout_vars(layout)
            # 字体样式默认写回（_save_current_config 经 _active_layout_defaults 读这几个变量持久化）。
            self.font_bold_var.set(bool(dlg_bold.get()))
            self.font_underline_var.set(bool(dlg_underline.get()))
            self.bold_strength_var.set(dlg_strength.get())
            self.letter_spacing_var.set(dlg_spacing.get())
            self._save_current_config()
            self.status_var.set("全局布局默认值已保存；输出物理尺寸已写入产品模板")
            if close:
                window.destroy()

        def reset_defaults() -> None:
            default = EngravingLayout()
            for key in dialog_vars:
                dialog_vars[key].set(str(getattr(default, key)))
            dlg_bold.set(default.bold)
            dlg_underline.set(default.underline)
            dlg_strength.set(str(default.bold_strength))
            dlg_spacing.set(str(default.letter_spacing))

        ttk.Separator(frame, orient="horizontal").grid(
            row=base_row + 5, column=0, columnspan=2, sticky="ew", pady=(10, 6)
        )
        ttk.Label(
            frame,
            text="字体样式默认（用于新建文本图层；加粗=轮廓外扩，下划线=基线下加线）",
            style="Status.TLabel",
            wraplength=360,
        ).grid(row=base_row + 6, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(frame, text="加粗", variable=dlg_bold).grid(row=base_row + 7, column=0, sticky="w", pady=2)
        ttk.Checkbutton(frame, text="下划线", variable=dlg_underline).grid(
            row=base_row + 7, column=1, sticky="w", pady=2
        )
        ttk.Label(frame, text="加粗强度(占字号,如0.016)").grid(row=base_row + 8, column=0, sticky="w", pady=2)
        ttk.Entry(frame, textvariable=dlg_strength, width=14).grid(row=base_row + 8, column=1, sticky="ew", pady=2)
        ttk.Label(frame, text="字间距(px)").grid(row=base_row + 9, column=0, sticky="w", pady=2)
        ttk.Entry(frame, textvariable=dlg_spacing, width=14).grid(row=base_row + 9, column=1, sticky="ew", pady=2)

        buttons = ttk.Frame(frame)
        buttons.grid(row=base_row + 10, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="恢复默认值", command=reset_defaults).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="应用", command=lambda: apply_values(False)).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="保存", command=lambda: apply_values(True)).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="取消", command=window.destroy).pack(side="left")

    def _set_layout_vars(self, layout: EngravingLayout) -> None:
        """同步全局布局变量；注意不遍历 Document.layers，避免覆盖图层独立几何。"""
        for key in self.layout_vars:
            self.layout_vars[key].set(str(getattr(layout, key)))

    def _apply_layout_defaults(self, layout: EngravingLayout) -> None:
        """把产品级默认几何灌进当前 UI 变量；不覆盖已有图层独立几何。"""
        self._set_layout_vars(layout)
        self.font_bold_var.set(bool(layout.bold))
        self.font_underline_var.set(bool(layout.underline))
        self.bold_strength_var.set(str(layout.bold_strength))
        self.letter_spacing_var.set(str(layout.letter_spacing))

    def _active_layout_defaults(self) -> EngravingLayout:
        """全局默认布局：几何取自 layout_vars，字体样式取自独立样式变量。两条保存路径与建层共用，
        确保 layout_from_values（仅几何）不会把字体样式默认丢掉。"""
        geometry = layout_from_values(self.layout_vars)
        try:
            strength = max(0.0, float(self.bold_strength_var.get()))
        except (ValueError, AttributeError):
            strength = EngravingLayout().bold_strength
        try:
            spacing = float(self.letter_spacing_var.get())
        except (ValueError, AttributeError):
            spacing = EngravingLayout().letter_spacing
        return dataclasses.replace(
            geometry,
            bold=bool(self.font_bold_var.get()),
            underline=bool(self.font_underline_var.get()),
            bold_strength=strength,
            letter_spacing=spacing,
        )

    def _clear_document_history(self) -> None:
        history = getattr(self, "history_manager", None)
        if history is not None:
            history.clear()

    def _push_document_history(self) -> None:
        history = getattr(self, "history_manager", None)
        if history is not None:
            history.push(self.document)

    def _restore_document_snapshot(self, snapshot: Document) -> None:
        self.document = snapshot
        self.selected_preview_item = self.document.selected_layer_id
        selected = self.document.selected_layer()
        if selected is not None:
            self._sync_layer_properties(selected)
        self._refresh_layers_panel()
        self._redraw_preview()

    def _focus_is_text_input(self) -> bool:
        focus = self.root.focus_get()
        if focus is None:
            return False
        # Packet 1：属性栏 overlay 的 Entry 也算文字输入，焦点在栏内时画布快捷键（Ctrl+Z/Delete）让路。
        if focus in self._inspector_entry_widgets():
            return True
        try:
            return focus.winfo_class() in {"Entry", "Text", "TEntry"} or isinstance(focus, (tk.Entry, tk.Text, ttk.Entry))
        except tk.TclError:
            return False

    def _on_undo_key(self, _event=None):
        if self._focus_is_text_input():
            return None
        snapshot = self.history_manager.undo(self.document)
        if snapshot is None:
            self.status_var.set("没有可撤销的画布编辑")
            return "break"
        self._restore_document_snapshot(snapshot)
        self.status_var.set("已撤销画布编辑")
        return "break"

    def _on_redo_key(self, _event=None):
        if self._focus_is_text_input():
            return None
        snapshot = self.history_manager.redo(self.document)
        if snapshot is None:
            self.status_var.set("没有可重做的画布编辑")
            return "break"
        self._restore_document_snapshot(snapshot)
        self.status_var.set("已重做画布编辑")
        return "break"

    def test_ai_connection(self) -> None:
        profile = self._settings_ai_profile() if hasattr(self, "ai_provider_var") else active_ai_profile(self.config)
        config = build_ai_parse_config(profile, self.session_api_key_var.get())
        self.status_var.set("AI 测试中...")

        def work():
            return parse_order_remark_with_gpt(
                "Name: Test June font 1 flower 1",
                api_key=config.api_key,
                model=config.model,
                project=config.project,
                organization=config.organization,
                provider=config.provider,
                base_url=config.base_url,
                timeout=config.timeout,
            )

        def on_success(result) -> None:
            self.status_var.set("AI 测试完成")
            messagebox.showinfo("AI 测试完成", f"confidence: {result.confidence:.2f}")

        def on_error(exc: Exception) -> None:
            self.status_var.set("AI 测试失败")
            messagebox.showerror("AI 测试失败", str(exc))

        run_background(self.root, work, on_success, on_error)

    def _current_ai_config(self, order_information: str | None = None) -> AIParseConfig:
        config = build_ai_parse_config(active_ai_profile(self.config), self.session_api_key_var.get())
        product = active_product(self.config)
        template = self._current_prompt_template_text()
        remark = self._current_remark_text() if order_information is None else order_information
        resolved = resolve_prompt_template(
            template,
            scope_id=product.id,
            fields=product.reference_fields,
            order_information=remark,
        )
        refs = find_template_references(template)
        user_content = "" if "order_information" in refs.source_keys else remark
        snapshot = tuple(
            {
                "id": field.id,
                "scope_id": field.scope_id,
                "sequence_number": str(field.sequence_number),
                "reference_name": field.reference_name,
                "prompt": field.prompt,
                "enabled": str(field.enabled),
                "updated_at": field.updated_at,
                "deleted_at": field.deleted_at,
            }
            for field in resolved.field_snapshot
        )
        return dataclasses.replace(
            config,
            system_prompt=resolved.final_prompt,
            background_prompt="",
            user_content=user_content,
            reference_snapshot=snapshot,
        )

    def _settings_ai_profile(self) -> AIProfile:
        return build_ai_profile_from_settings(
            active_ai_profile(self.config),
            provider=self.ai_provider_var.get(),
            model=self.ai_model_var.get(),
            base_url=self.ai_base_url_var.get(),
            api_key_env_var=self.ai_api_key_env_var.get(),
            project_env_var=self.ai_project_env_var.get(),
            org_env_var=self.ai_org_env_var.get(),
            prefer_ai=True,  # 全局使用 AI 解析：「AI 优先」开关已移除，恒为开。
        )

    def _selected_output_formats(self) -> tuple[str, ...]:
        return validate_output_formats([name for name, var in self.output_format_vars.items() if var.get()])

    def _selected_output_formats_or_default(self) -> tuple[str, ...]:
        try:
            return self._selected_output_formats()
        except ValueError:
            return ("svg", "dxf")

    def import_remark_file(self) -> None:
        path = filedialog.askopenfilename(
            title="导入订单备注",
            filetypes=[("Order Remark", "*.txt *.json *.csv *.xlsx"), ("All files", "*.*")],
        )
        if not path:
            return
        import_path = Path(path)
        suffix = import_path.suffix.casefold()
        if suffix == ".xlsx":
            self._import_xlsx_batch_file(import_path)
            return
        if suffix not in SINGLE_REMARK_SUFFIXES:
            messagebox.showerror("导入失败", f"不支持的文件类型：{import_path.suffix or '无后缀'}")
            return
        try:
            remark = load_order_remark_from_file(import_path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("导入失败", str(exc))
            return
        self._set_remark_text(" ".join(remark.split()))
        self._set_warnings([])

    def _import_xlsx_batch_file(self, path: Path) -> None:
        # 批量复用桌面布局(单一来源):在主线程读当前布局默认值,传进批量,产出与桌面单单一致。
        try:
            layout = dataclasses.asdict(layout_from_values(self.layout_vars))
        except (ValueError, TypeError):
            layout = None

        def work() -> object:
            return import_dianxiaomi_xlsx_batch(path, layout=layout)

        def on_success(result: object) -> None:
            show_xlsx_batch_import_summary(self.root, result)

        def on_error(exc: Exception) -> None:
            messagebox.showerror("批量导入失败", batch_import_error_message(exc))

        run_background(self.root, work, on_success, on_error)

    def import_asset_file(self) -> None:
        path = filedialog.askopenfilename(
            title="导入素材",
            filetypes=[
                ("可导入素材", "*.svg *.png *.jpg *.jpeg *.webp *.bmp *.ttf *.otf"),
                ("字体", "*.ttf *.otf"),
                ("矢量/位图", "*.svg *.png *.jpg *.jpeg *.webp *.bmp"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._import_asset_path(Path(path))

    def _import_asset_path(self, path: Path | str) -> None:
        import_path = Path(path)
        suffix = import_path.suffix.casefold()
        if suffix in IMPORTABLE_FONT_SUFFIXES:
            self._import_font_file(import_path)
            return
        if suffix in IMPORTABLE_ASSET_SUFFIXES:
            self._import_flower_file(import_path)
            return
        messagebox.showerror("导入失败", f"不支持的文件类型：{import_path.suffix or '无后缀'}")

    def _import_font_file(self, path: Path | str) -> None:
        font_path = Path(path)
        if not font_path.is_file():
            messagebox.showerror("导入失败", f"字体文件不存在：{font_path}")
            return
        fonts = scan_font_assets(font_path)
        if not fonts:
            messagebox.showerror("导入失败", f"无法识别字体文件：{font_path}")
            return
        self.font_source_var.set(str(font_path))
        self.font_assets = fonts
        self.preview_font_family_cache.clear()
        self._refresh_font_choices()
        selected = next((asset for asset in fonts if asset.path == font_path), fonts[0])
        self._select_imported_font_asset(selected)
        self._save_current_config()

    def _import_flower_file(self, path: Path | str) -> None:
        asset_path = Path(path)
        if not asset_path.is_file():
            messagebox.showerror("导入失败", f"素材文件不存在：{asset_path}")
            return
        suffix = asset_path.suffix.casefold()
        if suffix not in IMPORTABLE_ASSET_SUFFIXES:
            messagebox.showerror("导入失败", f"不支持的素材类型：{asset_path.suffix or '无后缀'}")
            return
        self.flower_dir_var.set(str(asset_path.parent))
        scanned_assets = scan_flower_assets(asset_path.parent) if suffix in IMPORTABLE_VECTOR_SUFFIXES else []
        selected = next((asset for asset in scanned_assets if asset.path == asset_path), None)
        if selected is None:
            selected = self._imported_flower_asset(asset_path)
        self.flower_assets = [asset for asset in scanned_assets if asset.path != asset_path]
        self.flower_assets.append(selected)
        self.preview_cache.clear()
        self._refresh_flower_choices()
        self._select_imported_flower_asset(selected)
        self._save_current_config()

    def _imported_flower_asset(self, path: Path) -> FlowerAsset:
        is_bitmap = path.suffix.casefold() in IMPORTABLE_BITMAP_SUFFIXES
        return FlowerAsset(
            name=path.stem,
            path=path,
            asset_key=path.stem.casefold(),
            display_name=path.stem,
            category="imported_bitmap" if is_bitmap else "imported_vector",
            is_vector_safe=not is_bitmap,
            embedded_raster_warnings=("位图素材导出 SVG 时会以图片嵌入，不是纯矢量。",) if is_bitmap else (),
        )

    def _select_imported_flower_asset(self, asset: FlowerAsset) -> None:
        label = self._flower_label(asset)
        if label not in self.flower_label_map:
            self.flower_label_map[label] = asset
            self.flower_combo.configure(values=list(self.flower_label_map))
        self._set_pending_flower_asset(label, sync_fields=True)
        if asset.embedded_raster_warnings:
            self._set_warnings(list(asset.embedded_raster_warnings))
        # 导入素材是独立的显式菜单动作，保留既有行为：导入后立即追加为新图层。
        self._add_selected_flower_to_canvas()

    def _select_imported_font_asset(self, asset: FontAsset) -> None:
        label = self._font_label(asset)
        if label not in self.font_label_map:
            self.font_label_map[label] = asset
            self.font_combo.configure(values=list(self.font_label_map))
        self.font_asset_var.set(label)
        self.current_manual_glyph_override = None
        self.current_glyph_overrides.clear()
        self.selected_glyph_position = None
        self.font_var.set(str(asset.index))
        self._add_text_layer_from_fields()

    def parse_remark(self) -> None:
        remark = self._current_remark_text()
        try:
            ai_config = self._current_ai_config(remark)
        except PromptReferenceError as exc:
            self.status_var.set("提示词引用无效")
            self._show_generated_prompt()
            messagebox.showerror("提示词引用无效", str(exc))
            return
        self.status_var.set("解析中...")
        # 解析可观测②：建空壳 trace，解析路径就地写回「实际发出的提示词全文」，回主线程后刷管理员端展示。
        trace = ParsePromptTrace()
        self._last_parse_trace = trace

        def on_error(exc: Exception) -> None:
            self.status_var.set("解析失败")
            self._refresh_prompt_obs_from_trace(trace)  # 即便失败也把已拼好的提示词显出来，便于排错
            messagebox.showerror("解析失败", str(exc))

        run_background(
            self.root,
            lambda: parse_orders_auto(remark, ai_config=ai_config, bundle=self.active_bundle, trace=trace),
            self._apply_parsed_orders,
            on_error,
        )

    def _apply_parsed_orders(self, results) -> None:
        """多订单识别结果落地：存队列、载入第 1 笔到编辑器，其余可用「上一笔/下一笔」逐笔切换。"""
        results = [r for r in (results or []) if r is not None]
        # 解析可观测②：本批提示词对全部订单一致，回主线程后刷一次管理员端「本次提示词」面板。
        self._refresh_prompt_obs_from_trace(self._last_parse_trace)
        if not results:
            self.parsed_orders = []
            self._parsed_order_index = 0
            self.status_var.set("未识别到订单")
            self._render_parse_result_box(None, 0, 0)
            messagebox.showwarning("解析", "未能从文本中识别出任何订单，请检查粘贴内容。")
            self._update_order_queue_ui()
            return
        self.parsed_orders = results
        self._parsed_order_index = 0
        self._apply_parse_result(results[0])
        self._update_order_queue_ui()
        self.status_var.set(
            f"识别到 {len(results)} 笔订单，已载入第 1 笔，逐笔确认后点「生成」"
            if len(results) > 1
            else "识别完成"
        )

    def _show_order_at(self, index: int) -> None:
        if not self.parsed_orders:
            return
        index = max(0, min(index, len(self.parsed_orders) - 1))
        self._parsed_order_index = index
        self._apply_parse_result(self.parsed_orders[index])
        self._update_order_queue_ui()

    def _show_prev_order(self) -> None:
        self._show_order_at(self._parsed_order_index - 1)

    def _show_next_order(self) -> None:
        self._show_order_at(self._parsed_order_index + 1)

    def _update_order_queue_ui(self) -> None:
        """刷新订单队列指示条：单笔时隐藏导航；多笔时显示「第 i/N 单 · 订单号」与上一/下一按钮。"""
        total = len(self.parsed_orders)
        label = self.order_queue_label
        prev_btn = self.order_prev_button
        next_btn = self.order_next_button
        if label is None:
            return
        if total <= 1:
            label.configure(text="")
            if prev_btn is not None:
                prev_btn.grid_remove()
            if next_btn is not None:
                next_btn.grid_remove()
            return
        index = self._parsed_order_index
        order_number = (self.parsed_orders[index].order_number or "—")
        label.configure(text=f"第 {index + 1}/{total} 单 · 订单号 {order_number}")
        if prev_btn is not None:
            prev_btn.grid()
            prev_btn.configure(state="normal" if index > 0 else "disabled")
        if next_btn is not None:
            next_btn.grid()
            next_btn.configure(state="normal" if index < total - 1 else "disabled")

    def open_output_dir(self) -> None:
        output_dir = normalize_output_path(self.output_var.get()).parent
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(output_dir)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(output_dir)], check=False)
            else:
                subprocess.run(["xdg-open", str(output_dir)], check=False)
        except OSError as exc:
            messagebox.showerror("打开失败", str(exc))

    def _apply_parse_result(self, result) -> None:
        self.last_parse_result = result
        # 订单号是后端按订单生成文件/写 metadata.orderId 的关键参数，识别到就记下。
        self.current_order_number = getattr(result, "order_number", "") or ""
        if result.text:
            self.name_var.set(result.text)
        if result.font is not None:
            self.font_var.set(str(result.font))
        self.personalization_type_var.set(getattr(result, "personalization_type", "unknown") or "unknown")
        self._apply_results_to_fields(result)  # 映射 B：把解析值回填进各 info 字段的只读结果框
        # 解析可观测③：本单识别结果刷进「解析结果」只读框（操作员/管理员端常驻，异常才弹窗）。
        self._render_parse_result_box(result, self._parsed_order_index, len(self.parsed_orders))
        self._update_piece_filename()  # 逐笔切换时把文件名刷成 订单号-k（一单多件防覆盖）
        self._refresh_flower_choices()
        self._select_flower_by_parse_result(result)
        self._select_font_by_current_field()
        self._replace_layers_from_parse_result(result)
        if result.warnings:
            self._show_parse_warning_dialog(result)
        self._redraw_preview()

    # ===== 解析可观测性（③ 结果 / ② 提示词）：解析后随本次操作自动刷新，无需另点按钮 =====
    @staticmethod
    def _format_parse_result(result, index: int, total: int) -> str:
        """把单条 ParseResult 渲染成人读的结构化摘要（解析结果只读框用）。

        用 getattr 容错：解析路径恒传完整 ParseResult，但护栏测试可能传部分字段的 stub，缺字段不应崩。
        """
        if result is None:
            return "（未识别到订单）"
        text = getattr(result, "text", "") or ""
        month = getattr(result, "month", None)
        font = getattr(result, "font", None)
        flower = getattr(result, "flower", None)
        flower_name = (getattr(result, "flower_name", None) or "").strip()
        order_number = getattr(result, "order_number", "") or ""
        quantity = getattr(result, "quantity", 1)
        gift_message = (getattr(result, "gift_message", None) or "").strip()
        try:
            confidence = float(getattr(result, "confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        warnings = [str(w) for w in (getattr(result, "warnings", None) or []) if str(w).strip()]
        flower_disp = f"{flower}" + (f"（{flower_name}）" if flower_name else "") if flower is not None else "—"
        lines: list[str] = []
        if total > 1:
            lines.append(f"第 {index + 1}/{total} 单")
        lines.append(f"订单号  {order_number or '—'}    数量  {quantity}")
        lines.append(f"刻字    {text or '—'}")
        lines.append(f"月份  {month if month is not None else '—'}    "
                     f"花  {flower_disp}    字体  {font if font is not None else '—'}")
        if gift_message:
            lines.append(f"留言    {gift_message}")
        lines.append(f"置信度  {confidence:.2f}")
        if warnings:
            lines.append("⚠ " + "；".join(warnings))
        return "\n".join(lines)

    def _render_parse_result_box(self, result, index: int, total: int) -> None:
        box = self.parse_result_box
        if box is None:
            return
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", self._format_parse_result(result, index, total))
        box.configure(state="disabled")

    def _refresh_prompt_obs_from_trace(self, trace) -> None:
        """把「实际发给模型的提示词全文」刷进管理员端「本次提示词」面板（解析后自动，无需另点按钮）。"""
        box = self.generated_prompt_text
        if box is None or trace is None or not getattr(trace, "filled", False):
            return
        text = (
            f"[{trace.provider} · {trace.model}]\n\n"
            f"[system]\n{trace.system_prompt or '（空）'}"
        )
        # 模板内联订单文本时 user 消息本就为空，别再展示「[user]（空）」这种内部占位。
        if (trace.user_content or "").strip():
            text += f"\n\n[user]\n{trace.user_content}"
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state="disabled")

    # ===== 映射（混合）：先认显式「填X」声明，匹配不到再按提示词中文/英文语义关键词回退 =====
    # 字段「提取规则」正文若以「填 <schema字段>」声明要填后端哪个字段（默认提示词写法），按此精确映射；
    # 多数用户用自然语言写规则（如「提取花朵的名称」），无「填X」时按 _RESULT_SEMANTIC_KEYWORDS 语义回退。
    # 一字段可命中多个 schema 字段，按可读性优先级取一个展示：花名 > 文字 > 字体 > 月份 > 第几朵。
    _RESULT_FILL_PRIORITY = ("flower_name", "text", "font", "month", "flower")
    # 语义关键词表：schema 字段 → 触发词（中文 + 英文）。元组顺序即命中优先级（高 → 低）。
    _RESULT_SEMANTIC_KEYWORDS = (
        ("flower_name", ("花名", "花朵", "出生花", "花", "flower_name", "flower")),
        ("font", ("字体", "字型", "font")),
        ("text", ("刻字", "文本", "文字", "名字", "text")),
        ("month", ("月份", "月", "month")),
    )

    def _apply_results_to_fields(self, result) -> None:
        """按各字段提示词映射把解析结果回填进只读结果框（result_var）并存进 field_results。"""
        for field in self.field_defs:
            self._ensure_field_vars(field)
            instruction = field["inst_var"].get() or field.get("instruction", "")
            key = self._field_result_target(instruction)
            value = self._result_attr_display(key, result) if key else ""
            field["result_var"].set(value)
            self.field_results[field["key"]] = value

    def _field_result_target(self, instruction: str) -> str | None:
        """返回该字段提示词指向的 ParseResult 字段名：先显式「填X」声明、再语义关键词回退；无 → None。"""
        instruction = instruction or ""
        # 1) 显式「填X」：取第一处「填」到首个冒号/句号/换行前的声明区，匹配 schema 字段名（避免正文误命中）。
        match = re.search(r"填([^：:。\n]*)", instruction)
        if match:
            segment = match.group(1)
            for key in self._RESULT_FILL_PRIORITY:
                if re.search(rf"(?<!\w){re.escape(key)}(?!\w)", segment):
                    return key
        # 2) 语义回退：整段提示词里按优先级找中文/英文关键词。
        for key, keywords in self._RESULT_SEMANTIC_KEYWORDS:
            if any(kw in instruction for kw in keywords):
                return key
        return None

    @staticmethod
    def _result_attr_display(key: str, result) -> str:
        """取 ParseResult 上 key 对应值并转成展示字符串（None/缺失 → 空串）。"""
        value = getattr(result, key, None)
        if value is None:
            return ""
        # 字体按「font4」格式展示（对齐字段提示词「font1/font2/font3」的写法）。
        if key == "font":
            return f"font{value}"
        return value.strip() if isinstance(value, str) else str(value)

    def _show_parse_warning_dialog(self, result) -> None:
        """主题化「需人工确认」弹窗（取代原生 messagebox）：醒目列缺失字段 + 折叠 AI/本地原文。"""
        warnings = [str(w) for w in (getattr(result, "warnings", []) or [])]
        hints = parse_missing_field_hints(result)
        window = self._themed_toplevel()
        window.title("需人工确认")
        window.transient(self.root)
        window.geometry("470x460")
        try:
            window.grab_set()
        except tk.TclError:
            pass

        header = ctk.CTkFrame(window, fg_color=APP_COLORS["accent_soft"], corner_radius=0)
        header.pack(fill="x")
        title = f"需人工确认 {len(hints)} 个字段" if hints else "解析提醒"
        ctk.CTkLabel(
            header, text=title, anchor="w", text_color=APP_COLORS["warning"],
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(fill="x", padx=16, pady=(12, 2))
        ctk.CTkLabel(
            header, text="自动识别没能确定下列字段，选好后再点生成", anchor="w",
            text_color=APP_COLORS["muted"],
        ).pack(fill="x", padx=16, pady=(0, 12))

        if hints:
            cards = ctk.CTkFrame(window, fg_color="transparent")
            cards.pack(fill="x", padx=16, pady=(12, 6))
            for field, hint in hints:
                row = ctk.CTkFrame(cards, fg_color="transparent")
                row.pack(fill="x", pady=4)
                ctk.CTkLabel(
                    row, text=field, width=52, corner_radius=6,
                    fg_color=APP_COLORS["accent_soft"], text_color=APP_COLORS["warning"],
                ).pack(side="left")
                ctk.CTkLabel(
                    row, text=hint, anchor="w", justify="left",
                    text_color=APP_COLORS["text"], wraplength=350,
                ).pack(side="left", padx=(10, 0))

        ctk.CTkLabel(
            window, text="识别详情（AI / 本地原文）", anchor="w", text_color=APP_COLORS["muted"],
        ).pack(fill="x", padx=16, pady=(10, 2))
        detail = ctk.CTkTextbox(
            window, height=120, fg_color=APP_COLORS["input"], text_color=APP_COLORS["muted"],
            border_width=1, border_color=APP_COLORS["border"], wrap="word",
        )
        detail.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        detail.insert("1.0", "\n".join(warnings) if warnings else "（无）")
        detail.configure(state="disabled")

        def copy_raw() -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(warnings))
            self.status_var.set("已复制识别详情")

        btns = ctk.CTkFrame(window, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(0, 12))
        self._btn(btns, "知道了，去确认", window.destroy, primary=True).pack(side="right")
        self._btn(btns, "复制原文", copy_raw).pack(side="right", padx=(0, 8))

    def _replace_layers_from_parse_result(self, result) -> None:
        if not self._parse_result_can_create_layers(result):
            return
        if self.flower_label_map.get(self.flower_asset_var.get()) is None:
            return
        # 解析新订单时旧素材/文字属于上一单输出，必须先清空再生成本单图层。
        self.document.layers = [
            layer for layer in self.document.layers if not isinstance(layer, (ImageLayer, TextLayer))
        ]
        self.document.normalize_z_indexes()
        self.document.selected_layer_id = None
        self.selected_preview_item = None
        self.current_manual_glyph_override = None
        self.current_glyph_overrides.clear()
        self.selected_glyph_position = None
        self._add_selected_flower_to_canvas()
        self._add_text_layer_from_fields()
        self._clear_document_history()

    def _parse_result_can_create_layers(self, result) -> bool:
        # 与 parse_pipeline._is_complete 同口径：text + font +（flower_name | material_key）。
        # 旧版查 month/flower 两个字段，2026-06-25 重构已从 ParseResult 删除 → getattr 恒 None、
        # 闸门永远不过、解析后从不自动建层（要手动加图层）。改回当前真实字段。
        warnings = getattr(result, "warnings", []) or []
        return (
            not warnings
            and bool((getattr(result, "text", "") or "").strip())
            and getattr(result, "font", None) is not None
            and bool(getattr(result, "flower_name", "") or getattr(result, "material_key", ""))
        )

    def choose_output(self) -> None:
        current_output = normalize_output_path(self.output_var.get())
        selected_formats = self._selected_output_formats_or_default()
        default_format = selected_formats[0] if selected_formats else "svg"
        path = filedialog.asksaveasfilename(
            title="选择输出路径",
            defaultextension=f".{default_format}",
            filetypes=[
                ("输出文件", "*.png *.svg *.dxf"),
                ("PNG", "*.png"),
                ("SVG", "*.svg"),
                ("DXF", "*.dxf"),
                ("All files", "*.*"),
            ],
            initialdir=str(current_output.parent),
            initialfile=current_output.name,
        )
        if path:
            self.output_var.set(str(normalize_output_path(path)))
            self._save_current_config()

    def choose_flower_dir(self) -> None:
        path = filedialog.askdirectory(title="选择 BirthMonth flowers 目录")
        if path:
            self.flower_dir_var.set(path)
            self._save_current_config()
            self._scan_assets(show_errors=True)

    def choose_font_source(self) -> None:
        # 库=文件夹：只选文件夹，与素材目录 choose_flower_dir 口径统一。
        # 旧版「先弹选文件、取消再弹选文件夹」的嵌套对话框在模态设置窗口里会卡住、
        # 需关窗口才能再选——故去掉嵌套，单一文件夹选择器即时生效、可反复选。
        path = filedialog.askdirectory(title="选择字体库目录")
        if path:
            self.font_source_var.set(path)
            self._save_current_config()
            self._scan_assets(show_errors=True)

    def open_glyph_panel(self) -> None:
        self._resolve_current_glyph()
        from glyph_panel import open_glyph_panel

        open_glyph_panel(self, mapping_only=False)

    def open_glyph_mapping_settings(self) -> None:
        self._resolve_current_glyph()
        from glyph_panel import open_glyph_panel

        open_glyph_panel(self, mapping_only=True)

    def clear_manual_glyph_selection(self) -> None:
        self.current_manual_glyph_override = None
        self.current_glyph_overrides.clear()
        self.selected_glyph_position = None
        self.status_var.set("已清除人工字形选择")
        self._redraw_preview()

    def reidentify_glyph(self) -> None:
        self.current_manual_glyph_override = None
        self.current_glyph_overrides.clear()
        self.selected_glyph_position = None
        self.status_var.set("已重新自动识别字形")
        self._redraw_preview()

    def select_glyph_position(self, index: int) -> None:
        text = self._current_edit_text()
        if index < 0 or index >= len(text):
            messagebox.showerror("字符位置", "请选择当前文字中的有效字符。")
            return
        self.selected_glyph_position = index
        self.status_var.set(f"已选择字符位置：{index}:{text[index]}")
        self._redraw_preview()

    def set_position_glyph_override(self, index: int, override: dict[str, object]) -> None:
        text = self._current_edit_text()
        if index < 0 or index >= len(text):
            messagebox.showerror("字形绑定失败", "请选择当前文字中的有效字符。")
            return
        self.current_manual_glyph_override = None
        self.selected_glyph_position = index
        clean_override = dict(override)
        clean_override["index"] = index
        clean_override["base_char"] = text[index]
        clean_override["original_char"] = text[index]
        clean_override["selected_char"] = text[index]
        if clean_override.get("char") and not clean_override.get("replacement_char"):
            clean_override["replacement_char"] = clean_override.get("char")
        layer = self._selected_text_layer()
        if layer is not None:
            try:
                _render_text, clean_overrides, warnings = apply_glyph_to_text_layer(layer, index, clean_override)
            except ValueError as exc:
                messagebox.showerror("字形绑定失败", str(exc))
                return
            if warnings:
                self.warning_var.set("；".join(warnings))
            layer.glyph_overrides = clean_overrides
            self.current_glyph_overrides = dict(layer.glyph_overrides)
        else:
            self.current_glyph_overrides[index] = clean_override
        codepoint = clean_override.get("codepoint") or "无 Unicode"
        self.status_var.set(f"已绑定位置 {index}:{text[index]} -> {clean_override.get('glyph_name')} ({codepoint})")
        self._refresh_layers_panel()
        self._redraw_preview()

    def clear_current_position_glyph_override(self) -> None:
        if self.selected_glyph_position is None:
            self.status_var.set("未选择字符位置")
            return
        layer = self._selected_text_layer()
        if layer is not None:
            render_text, clean_overrides, warnings = remove_glyph_override(layer.original_text, layer.glyph_overrides, self.selected_glyph_position, font_path=layer.font_path, text_layer_id=layer.id)
            layer.render_text = render_text
            layer.glyph_overrides = clean_overrides
            if warnings:
                self.warning_var.set("；".join(warnings))
            self.current_glyph_overrides = dict(clean_overrides)
        else:
            self.current_glyph_overrides.pop(self.selected_glyph_position, None)
        self.status_var.set(f"已清除位置 {self.selected_glyph_position} 的字形绑定")
        self._refresh_layers_panel()
        self._redraw_preview()

    def clear_all_position_glyph_overrides(self) -> None:
        layer = self._selected_text_layer()
        if layer is not None:
            layer.glyph_overrides.clear()
            layer.render_text = layer.original_text
        self.current_glyph_overrides.clear()
        self.status_var.set("已清除全部按位置字形绑定")
        self._refresh_layers_panel()
        self._redraw_preview()

    def set_manual_glyph_override(self, letter: str, codepoint: str, apply_mode: str) -> None:
        try:
            clean_codepoint = normalize_codepoint(codepoint)
            codepoint_to_char(clean_codepoint)
        except ValueError as exc:
            messagebox.showerror("人工字形失败", str(exc))
            return
        self.current_manual_glyph_override = {
            "letter": letter.strip().casefold(),
            "codepoint": clean_codepoint,
            "apply_mode": apply_mode,
        }
        self.current_glyph_overrides.clear()
        self.selected_glyph_position = None
        self.status_var.set(f"已应用人工字形：{letter} -> {clean_codepoint}")
        self._redraw_preview()

    def _sync_selected_glyph_position_from_inline_selection(self) -> bool:
        """把画布内联文本框的选区起点同步为字形覆盖 index。"""
        editor = self.inline_text_entry
        layer = self.document.layer_by_id(self.inline_text_layer_id)
        if editor is None or not isinstance(layer, TextLayer):
            return False
        try:
            selection_start = editor.index("sel.first")
            selected_char = editor.get("sel.first", "sel.first +1c")
            count = editor.count("1.0", selection_start, "chars")
        except tk.TclError:
            return False
        if not count:
            return False
        index = int(count[0])
        if index < 0 or index >= len(layer.original_text):
            return False
        if layer.original_text[index] != selected_char:
            LOGGER.warning(
                "inline selection index mismatch: layer_id=%s raw_text=%r index=%s selected_char=%r actual=%r",
                layer.id,
                layer.original_text,
                index,
                selected_char,
                layer.original_text[index],
            )
            messagebox.showerror("字形应用失败", "文本选择索引错位，请重新选中字母后再应用。")
            return False
        self.document.selected_layer_id = layer.id
        self.selected_preview_item = layer.id
        self.selected_glyph_position = index
        self.status_var.set(f"已选择字符位置：{index}:{layer.original_text[index]}")
        return True

    def apply_recommended_glyph_to_selection(self) -> None:
        """把当前字符的首个推荐字形直接应用；无推荐时打开完整字形面板。"""
        self._sync_selected_glyph_position_from_inline_selection()
        layer = self._selected_text_layer()
        index = self.selected_glyph_position
        if layer is None or index is None or index < 0 or index >= len(layer.original_text):
            self.open_glyph_panel()
            return
        font_path = layer.font_path or self._selected_font_path()
        if font_path is None:
            self.open_glyph_panel()
            return
        try:
            catalog = build_glyph_catalog(font_path, self._font_design_label(), self.glyph_bindings)
            variants = recommended_glyph_variants(catalog, layer.original_text[index])
        except Exception as exc:
            LOGGER.warning("推荐字形加载失败：font_path=%s index=%s error=%s", font_path, index, exc)
            self.open_glyph_panel()
            return
        if not variants:
            self.open_glyph_panel()
            return
        self.apply_glyph_variant_to_current_text(variants[0])

    def show_glyph_rules_info(self) -> None:
        enabled = "开启" if self.glyph_rules.enabled else "关闭"
        messagebox.showinfo("自动字形规则", f"自动字形规则当前：{enabled}\n配置文件：{self.glyph_rules.path}")

    def _selected_text_layer(self) -> TextLayer | None:
        layer = self.document.selected_layer()
        return layer if isinstance(layer, TextLayer) else None

    def _current_edit_text(self) -> str:
        layer = self._selected_text_layer()
        return layer.original_text if layer is not None else self.name_var.get()

    def _current_glyph_overrides(self) -> dict[int, dict[str, object]]:
        layer = self._selected_text_layer()
        return layer.glyph_overrides if layer is not None else self.current_glyph_overrides

    def _apply_text_layer_render_text(self, layer: TextLayer) -> list[str]:
        render_text, clean_overrides, warnings = rebuild_render_text(
            layer.original_text,
            layer.glyph_overrides,
            font_path=layer.font_path,
            text_layer_id=layer.id,
        )
        layer.render_text = render_text
        layer.glyph_overrides = clean_overrides
        layer.raw_text = layer.original_text
        layer.text = layer.original_text
        if warnings:
            LOGGER.warning("TextLayer 字形覆盖降级：layer_id=%s warnings=%s", layer.id, "; ".join(warnings))
            self.warning_var.set("；".join(warnings))
        return warnings

    def apply_glyph_variant_to_current_text(self, variant) -> None:
        layer = self._selected_text_layer()
        if layer is None:
            messagebox.showwarning("字形应用", "请先选择一个文本图层。")
            return
        index = self.selected_glyph_position
        if index is None:
            messagebox.showwarning("字形应用", "请先选择文本中的一个字符。")
            return
        try:
            render_text, clean_overrides, warnings = apply_glyph_to_text_layer(layer, index, variant)
        except ValueError as exc:
            LOGGER.warning(
                "字形替换失败：text_layer_id=%s original_text=%r index=%s glyph_name=%s error=%s",
                layer.id,
                layer.original_text,
                index,
                getattr(variant, "glyph_name", ""),
                exc,
            )
            messagebox.showerror("字形应用失败", str(exc))
            return
        layer.render_text = render_text
        layer.glyph_overrides = clean_overrides
        self.current_glyph_overrides = clean_overrides
        self.status_var.set("已应用特殊字形" if not warnings else "已应用特殊字形，但存在警告")
        if warnings:
            self.warning_var.set("；".join(warnings))
        self._refresh_layers_panel()
        self._redraw_preview()

    def restore_selected_glyph_override(self) -> None:
        self._sync_selected_glyph_position_from_inline_selection()
        index = self.selected_glyph_position
        if index is None:
            messagebox.showwarning("恢复普通字符", "请先选择文本中的一个字符。")
            return
        layer = self._selected_text_layer()
        if layer is not None:
            render_text, clean_overrides, warnings = remove_glyph_override(
                layer.original_text,
                layer.glyph_overrides,
                index,
                font_path=layer.font_path,
                text_layer_id=layer.id,
            )
            layer.render_text = render_text
            layer.glyph_overrides = clean_overrides
            self.current_glyph_overrides = clean_overrides
            if warnings:
                self.warning_var.set("；".join(warnings))
        else:
            self.current_glyph_overrides.pop(index, None)
        self.status_var.set("已恢复普通字符")
        self._refresh_layers_panel()
        self._redraw_preview()

    def show_glyph_help(self) -> None:
        # 原来用原生 messagebox（白底无法染色）；改成深色 CTk 窗口。
        window = self._themed_toplevel()
        window.title("字形使用说明")
        window.geometry("560x320")
        box = ctk.CTkTextbox(
            window, wrap="word", fg_color=APP_COLORS["input"], text_color=APP_COLORS["text"]
        )
        box.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        box.insert("1.0", GLYPH_HELP_TEXT)
        box.configure(state="disabled")
        self._btn(window, "关闭", window.destroy).pack(pady=(0, 12))

    def _font_design_label(self) -> str:
        try:
            return f"Font {int(self.font_var.get())}"
        except ValueError:
            return self.font_var.get().strip() or "Unknown"

    def _content_text_for_render(self) -> str:
        text = self.name_var.get()
        mode = self.text_case_var.get()
        if mode == "upper":
            return text.upper()
        if mode == "lower":
            return text.lower()
        return text  # default:不改变大小写

    def _cycle_text_case(self) -> None:
        """循环切换大小写模式 默认→大写→小写,按钮文字随之变化;改变会触发预览重绘。"""
        current = self.text_case_var.get()
        index = TEXT_CASE_ORDER.index(current) if current in TEXT_CASE_ORDER else 0
        next_mode = TEXT_CASE_ORDER[(index + 1) % len(TEXT_CASE_ORDER)]
        self.case_button.configure(text=TEXT_CASE_LABELS[next_mode])
        self.text_case_var.set(next_mode)  # 触发 trace → _on_personalization_change 重绘

    def _resolve_current_glyph(self) -> GlyphApplyResult:
        render_source = self._content_text_for_render()
        try:
            result = resolve_glyph(
                render_source,
                self._font_design_label(),
                self.glyph_config,
                self.current_manual_glyph_override,
                self.current_glyph_overrides,
            )
        except Exception as exc:
            result = GlyphApplyResult(
                original_text=render_source,
                render_text=render_source,
                font_design=self._font_design_label(),
                apply_mode="replace_last_letter",
                source_letter=None,
                source_index=None,
                glyph_codepoint=None,
                glyph_char=None,
                glyph_source="none",
                needs_review=True,
                reason=f"字形识别失败：{exc}",
            )
        self.current_glyph_result = result
        return result

    def _template_physical_width_mm(self) -> float | None:
        """读产品模板的输出物理宽度(布局设置里配置的同一数据源);失败则返回 None,
        导出端退回默认 80mm。这样「布局设置 → 输出宽度(mm)」对按钮导出立即生效。"""
        try:
            return float(load_template_physical_size().width_mm)
        except Exception as exc:
            LOGGER.warning("读取模板物理宽度失败,DXF 用默认尺寸: %s", exc)
            return None

    def _piece_index_total(self) -> tuple[int, int]:
        """(k, n)：当前是「第 k 件 / 共 n 件」。n>1 才需要文件名后缀。

        n 优先取数据库订单 items[] 目标盒子件数（仅当当前单号 == 库载入单号时可信），回退解析队列长度；
        k = 解析队列当前位置（逐笔「上一笔/下一笔」切换即换件）。手填粘贴单无库件数时用队列长度。
        """
        queue_n = len(self.parsed_orders)
        active = self._db_order_active_id
        # 库件数可信：当前单还是这条库订单（单号相同，或逐件解析把 order_number 留空时按库单号兜底）。
        db_trusted = bool(active) and (not self.current_order_number or self.current_order_number == active)
        db_n = self._db_order_piece_count if db_trusted else 0
        n = db_n if db_n > 1 else queue_n
        k = (self._parsed_order_index + 1) if queue_n else 1
        if n <= 0:
            return 1, 0
        return max(1, min(k, n)), n

    def _with_piece_suffix(self, base: str) -> str:
        """一单多件（n>1）时给文件名主干加「-k」后缀，单件原样返回。"""
        base = base.strip()
        if not base:
            return base
        k, n = self._piece_index_total()
        return f"{base}-{k}" if n > 1 else base

    def _update_piece_filename(self) -> None:
        """把「文件名」框刷成 订单号-k（多件）/ 订单号（单件）。

        仅当框还是「自动值」（订单号本身或 订单号-数字）时覆盖；操作员手改成别的名字则保留不动。
        """
        base = sanitize_filename_stem(self.current_order_number or self._db_order_active_id or "")
        if not base:
            return
        target = self._with_piece_suffix(base)
        current = self.filename_template_var.get().strip()
        if not current or re.fullmatch(rf"{re.escape(base)}(-\d+)?", current):
            if current != target:
                self.filename_template_var.set(target)

    def _resolve_output_basename(self, base_output_path: Path) -> str:
        """决定导出文件名主干（不含扩展名），按优先级回退：

        1) 「文件名」框：纯文本所见即所得（清洗非法字符）；
        2) 当前订单号：优先解析到的 current_order_number，回退 inbox 收件夹 JSON 文件名 stem；
        3) 都没有时回退「输出目录」路径里的原文件名（旧行为），保证名字永不为空。
        """
        typed = sanitize_filename_stem(self.filename_template_var.get())
        if typed:
            return typed
        order_no = sanitize_filename_stem(self.current_order_number)
        if order_no:
            return self._with_piece_suffix(order_no)  # 文件名框被清空时兜底也带「-k」防多件覆盖
        db_order_no = sanitize_filename_stem(self._db_order_active_id or "")
        if db_order_no:
            return self._with_piece_suffix(db_order_no)  # 多件库单兜底也带「-k」
        if self._inbox_active is not None:
            inbox_stem = sanitize_filename_stem(self._inbox_active.stem)
            if inbox_stem:
                return inbox_stem
        return base_output_path.stem

    def confirm_and_generate(self) -> None:
        glyph_result = self._resolve_current_glyph()
        try:
            design = build_design_from_values(
                glyph_result.render_text,
                self.month_var.get(),
                self.font_var.get(),
                self.flower_var.get(),
                self._selected_flower_path(),
                self._selected_font_path(),
                self._selected_flower_name(),
                layout_from_values(self.layout_vars),
                self.personalization_type_var.get(),
                glyph_result.glyph_overrides,
            )
        except ValueError as exc:
            messagebox.showerror("字段错误", str(exc))
            return

        # 最终文件必须由用户点击确认生成，解析按钮不会触发这里。
        try:
            selected_formats = self._selected_output_formats()
        except ValueError as exc:
            messagebox.showerror("输出格式", str(exc))
            return

        selected_flower_path = self._selected_flower_path()
        if (
            selected_flower_path is not None
            and selected_flower_path.suffix.casefold() in IMPORTABLE_BITMAP_SUFFIXES
            and "dxf" in selected_formats
        ):
            messagebox.showerror("输出格式", "位图素材无法导出 DXF；请取消 DXF，或导入纯矢量 SVG 素材。")
            return

        unmapped_glyphs = _unmapped_glyph_override_labels(glyph_result.glyph_overrides)
        if unmapped_glyphs and any(output_format in {"svg", "dxf"} for output_format in selected_formats):
            messagebox.showerror(
                "字形导出限制",
                "以下字形可预览但暂不支持导出 SVG/DXF，请只导出 PNG，或选择带 Unicode/PUA codepoint 的字形：\n"
                + "\n".join(unmapped_glyphs),
            )
            return

        glyph_warning = f"\n字形提醒：{glyph_result.reason}" if glyph_result.needs_review and glyph_result.reason else ""
        confirmed = messagebox.askyesno("确认生成", f"确认使用当前字段生成最终文件？{glyph_warning}")
        if not confirmed:
            return

        # 输出物理宽度来自产品模板(布局设置里配置),让 DXF 写出正确 mm 尺寸。
        physical_width_mm = self._template_physical_width_mm()
        generated_paths: list[Path] = []
        try:
            base_output_path = normalize_output_path(self.output_var.get())
            output_stem = self._resolve_output_basename(base_output_path)
            for output_format in selected_formats:
                # 保留目录，仅替换文件名主干 + 扩展名；不走 with_suffix，避免主干含点时被截断。
                target_path = base_output_path.with_name(f"{output_stem}.{output_format}")
                # 有图层时走 services/api 真实矢量导出:DXF/SVG 在 CAD 里可编辑、纯矢量。
                if self.document.layers and output_format == "svg":
                    generated_paths.append(
                        render_document_vector_svg(
                            self.document,
                            target_path,
                            physical_width_mm=physical_width_mm,
                        )
                    )
                elif self.document.layers and output_format == "png":
                    generated_paths.append(
                        render_document_png(
                            self.document, target_path, background=self.png_background_var.get()
                        )
                    )
                elif self.document.layers and output_format == "dxf":
                    generated_paths.append(
                        render_document_dxf(
                            self.document,
                            target_path,
                            physical_width_mm=physical_width_mm,
                        )
                    )
                elif output_format == "svg":
                    generated_paths.append(render_svg(design, target_path))
                elif output_format == "dxf":
                    generated_paths.append(render_dxf(design, target_path))
                elif output_format == "png":
                    generated_paths.append(render_png(design, target_path))
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror("生成失败", str(exc))
            return

        self.output_var.set(str(normalize_output_path(self.output_var.get())))
        self._save_current_config()
        self.status_var.set("生成完成")
        messagebox.showinfo("生成完成", "已生成：\n" + "\n".join(str(path) for path in generated_paths))
        self._enqueue_mark_done_after_generate()  # 生成成功 → 入队「AI已处理」标记回写（best-effort，须在放行前取订单号）
        self._advance_inbox_after_generate()  # 收件夹来源的订单：生成成功后放行下一单

    def _enqueue_mark_done_after_generate(self) -> None:
        """生成成功后，入队「AI已处理」标记回写任务（扩展去店小秘打 AI已处理 + 清 AI未识别）。

        best-effort：服务未起/订单未入库（手输无订单号）等失败不影响生成，只在副提示行轻提示。
        必须在 _advance_inbox_after_generate 清空 _inbox_active 之前调用（订单号要从中兜底）。
        """
        order_id = (self.current_order_number or "").strip()
        if not order_id:
            order_id = (self._db_order_active_id or "").strip()  # 库驱动载单：即便没解析到也有库订单号
        if not order_id and self._inbox_active is not None:
            order_id = self._inbox_active.stem
        if not order_id:
            return  # 无订单号（手输且未解析到）→ 无从打标
        url = self._inbox_service_url
        run_background(
            self.root,
            lambda: inbox_client.request_mark(url, order_id=order_id, action="mark_done"),
            lambda _res: None,
            lambda exc: self.warning_var.set(f"（标记回写入队失败，不影响生成：{exc}）"),
        )

    def _current_readiness_parse_result(self) -> ParseResult:
        result = build_readiness_parse_result_from_values(
            self._content_text_for_render(),
            self.font_var.get(),
            self._selected_flower_path(),
            self._selected_font_path(),
            self.personalization_type_var.get(),
            self._selected_flower_name(),
        )
        glyph_result = self.current_glyph_result
        if glyph_result is not None and glyph_result.needs_review and glyph_result.reason:
            result.warnings.append(glyph_result.reason)
            result.parse_confidence = min(result.parse_confidence or result.confidence, 0.99)
        return result

    def _set_readiness_display(self, parse_result: ParseResult, text_layout) -> GenerationReadiness:
        readiness = build_generation_readiness(parse_result, text_layout)
        self.confidence_var.set(format_readiness_summary(readiness))
        messages: list[str] = []
        if text_layout.personalization_type == "message" and text_layout.did_fit:
            messages.append("Personalization looks like a message. Auto layout applied.")
        messages.extend(readiness.warnings)
        self.status_var.set(readiness.status)
        self.warning_var.set("; ".join(messages) if messages else readiness.status)
        return readiness

    def _set_warnings(self, warnings: list[str]) -> None:
        text = "；".join(warnings) if warnings else "可生成"
        self.status_var.set(text)
        self.warning_var.set(text)



    def _layer_from_tree_event(self, event) -> object | None:
        tree = self.layers_tree
        if tree is None:
            return None
        row_id = tree.identify_row(event.y)
        if not row_id:
            return None
        layer = self.document.layer_by_id(row_id)
        if layer is None:
            return None
        self.document.selected_layer_id = layer.id
        self.selected_preview_item = layer.id
        tree.selection_set(layer.id)
        tree.focus(layer.id)
        self._sync_layer_properties(layer)
        return layer

    def _show_layer_context_menu(self, event) -> None:
        """图层列表右键菜单；文本图层暂不进入素材编辑，后续单独做文字属性编辑。"""
        layer = self._layer_from_tree_event(event)
        if layer is None:
            return
        menu = tk.Menu(self.root, tearoff=False)
        edit_state = "normal" if isinstance(layer, ImageLayer) else "disabled"
        menu.add_command(label="编辑素材...", state=edit_state, command=self.open_selected_material_editor)
        menu.add_command(label="复制图层", command=self._duplicate_selected_layer)
        menu.add_command(label="删除", command=self._delete_selected_layer)
        menu.add_command(
            label="解锁" if layer.locked else "锁定",
            command=self._toggle_selected_layer_locked,
        )
        menu.add_separator()
        menu.add_command(label="上移", command=lambda: self._move_selected_layer("up"))
        menu.add_command(label="下移", command=lambda: self._move_selected_layer("down"))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _show_canvas_context_menu(self, event) -> str:
        """画布右键菜单：命中图层后复用图层操作和字形操作。"""
        canvas = self.preview_canvas
        if canvas is None:
            return "break"
        if self.inline_text_entry is not None:
            self._commit_inline_text_edit()
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            layout = EngravingLayout()
        self._update_preview_canvas_size_status(layout)
        scale, offset_x, offset_y = self._preview_transform(layout)
        doc_x = (event.x - offset_x) / scale
        doc_y = (event.y - offset_y) / scale
        layer = hit_test(self.document, doc_x, doc_y)
        self.document.selected_layer_id = layer.id if layer else None
        self.selected_preview_item = self.document.selected_layer_id
        if layer is not None:
            self._sync_layer_properties(layer)
        canvas.focus_set()
        self._refresh_layers_panel()
        self._redraw_preview()
        menu = self._build_canvas_context_menu(layer)
        self._popup_context_menu(menu, event)
        return "break"

    def _show_inline_text_context_menu(self, event) -> str:
        """内联文本框右键：不提交编辑，直接对当前选区做字形操作。"""
        self._sync_selected_glyph_position_from_inline_selection()
        menu = self._build_canvas_context_menu(self._selected_text_layer())
        self._popup_context_menu(menu, event)
        return "break"

    def _popup_context_menu(self, menu: tk.Menu, event) -> None:
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _build_canvas_context_menu(self, layer) -> tk.Menu:
        menu = tk.Menu(self.root, tearoff=False)
        is_text = isinstance(layer, TextLayer)
        is_image = isinstance(layer, ImageLayer)
        has_layer = layer is not None
        unlocked = has_layer and not layer.locked
        if is_text:
            menu.add_command(label="编辑文本", command=lambda layer=layer: self._start_inline_text_edit(layer))
        elif is_image:
            menu.add_command(label="编辑素材...", command=self.open_selected_material_editor)
        else:
            menu.add_command(label="编辑文本", state="disabled", command=self._start_inline_text_edit)
        menu.add_command(label="删除", state="normal" if unlocked else "disabled", command=self._delete_selected_layer)
        menu.add_command(
            label="解锁" if has_layer and layer.locked else "锁定",
            state="normal" if has_layer else "disabled",
            command=self._toggle_selected_layer_locked,
        )
        menu.add_separator()
        menu.add_command(label="上移", state="normal" if has_layer else "disabled", command=lambda: self._move_selected_layer("up"))
        menu.add_command(label="下移", state="normal" if has_layer else "disabled", command=lambda: self._move_selected_layer("down"))
        menu.add_command(label="置顶", state="normal" if has_layer else "disabled", command=lambda: self._move_selected_layer("top"))
        menu.add_command(label="置底", state="normal" if has_layer else "disabled", command=lambda: self._move_selected_layer("bottom"))
        menu.add_separator()
        glyph_state = "normal" if is_text else "disabled"
        menu.add_command(label="字形...", state=glyph_state, command=self.open_glyph_panel)
        menu.add_command(label="应用推荐字形", state=glyph_state, command=self.apply_recommended_glyph_to_selection)
        menu.add_command(label="恢复普通字符", state=glyph_state, command=self.restore_selected_glyph_override)
        return menu

    def _on_layer_list_double_click(self, event) -> None:
        layer = self._layer_from_tree_event(event)
        if isinstance(layer, AnchoredHeartLayer):
            self._open_heart_anchor_dialog(layer)
        elif isinstance(layer, ImageLayer):
            self.open_selected_material_editor()
        elif isinstance(layer, TextLayer):
            # 只在内容列(#0)双击才进入文字编辑；双击 👁/🔒/🗑 仍走各自的列动作。
            tree = self.layers_tree
            column = tree.identify_column(event.x) if tree is not None else "#0"
            if column in ("#0", ""):
                self._begin_tree_text_edit(layer)

    def _begin_tree_text_edit(self, layer: TextLayer) -> None:
        """双击文字图层行 → 在 #0 单元格原地浮一个输入框；回车/失焦提交，Esc 取消。"""
        tree = self.layers_tree
        if tree is None or not tree.exists(layer.id):
            return
        self._commit_tree_text_edit()   # 有进行中的别行编辑先保存，不丢字
        tree.see(layer.id)
        bbox = tree.bbox(layer.id, "#0")
        if not bbox:                       # 行仍不可见（极端滚动态）→ 放弃，下次再编辑
            return
        x, y, w, h = bbox
        entry = tk.Entry(
            tree, bd=0, relief="flat",
            bg=APP_COLORS["input"], fg=APP_COLORS["text"],
            insertbackground=APP_COLORS["text"],
            highlightthickness=1,
            highlightbackground=APP_COLORS["accent"], highlightcolor=APP_COLORS["accent"],
        )
        entry.insert(0, layer.original_text)
        entry.select_range(0, "end")
        entry.icursor("end")
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        self._tree_text_edit = {"entry": entry, "layer_id": layer.id}
        entry.bind("<Return>", lambda _e: self._commit_tree_text_edit())
        entry.bind("<KP_Enter>", lambda _e: self._commit_tree_text_edit())
        entry.bind("<Escape>", lambda _e: self._cancel_tree_text_edit())
        entry.bind("<FocusOut>", lambda _e: self._commit_tree_text_edit())

    def _commit_tree_text_edit(self) -> None:
        state = self._tree_text_edit
        if not state:
            return
        entry = state["entry"]
        new_text = entry.get()
        layer = self.document.layer_by_id(state["layer_id"])
        # 先清状态再销毁：销毁聚焦控件会再触发 <FocusOut>，靠 None 防重入。
        self._tree_text_edit = None
        entry.destroy()
        if isinstance(layer, TextLayer):
            self._set_text_layer_content(layer, new_text)

    def _cancel_tree_text_edit(self) -> None:
        state = self._tree_text_edit
        if not state:
            return
        self._tree_text_edit = None
        state["entry"].destroy()

    def _set_text_layer_content(self, layer: TextLayer, new_text: str) -> None:
        """写回文字内容（与「文本属性」面板同一套逻辑：改内容则清字形绑定、按字号反推文本框）。"""
        if new_text == layer.original_text:
            return
        self._push_document_history()
        layer.original_text = new_text
        layer.raw_text = new_text
        layer.text = new_text
        if layer.glyph_overrides:
            LOGGER.info("文本内容变化（行内编辑），清空特殊字形绑定：layer_id=%s", layer.id)
            layer.glyph_overrides.clear()
        layer.render_text = new_text
        self._resize_text_box_to_font(layer)
        if self.document.selected_layer_id == layer.id:
            self.layer_text_var.set(new_text)   # 同步「文本属性」面板里的文本框
        self._refresh_layers_panel()
        self._redraw_preview()
        self.status_var.set("已更新文字内容")

    def open_selected_material_editor(self) -> None:
        layer = self.document.selected_layer()
        if not isinstance(layer, ImageLayer):
            self.status_var.set("当前选中图层不是素材图层")
            return
        self.open_material_editor(layer)

    def open_material_editor(self, layer: ImageLayer) -> None:
        """编辑单个素材图层；确定保留，取消恢复打开时的图层快照。"""
        snapshot = {
            "name": layer.name,
            "material_id": layer.material_id,
            "material_name": layer.material_name,
            "x": layer.x,
            "y": layer.y,
            "width": layer.width,
            "height": layer.height,
            "lock_aspect_ratio": layer.lock_aspect_ratio,
        }
        ratio = (layer.width / layer.height) if layer.height else 1.0
        window = self._themed_toplevel()
        window.title("编辑素材")
        window.transient(self.root)
        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)
        vars_map = {
            "name": tk.StringVar(value=layer.name),
            "material_id": tk.StringVar(value=layer.material_id),
            "material_name": tk.StringVar(value=layer.material_name),
            "x": tk.StringVar(value=str(layer.x)),
            "y": tk.StringVar(value=str(layer.y)),
            "width": tk.StringVar(value=str(layer.width)),
            "height": tk.StringVar(value=str(layer.height)),
            "lock_aspect_ratio": tk.BooleanVar(value=layer.lock_aspect_ratio),
        }
        fields = (("图层名称", "name"), ("material_id", "material_id"), ("material_name", "material_name"), ("x", "x"), ("y", "y"), ("width", "width"), ("height", "height"))
        for row, (label, key) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
            entry = ttk.Entry(frame, textvariable=vars_map[key], width=24)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
        # 「锁定宽高比」保留;图层整体「锁定/解锁」改由右键图层菜单负责,这里不再重复一个复选框。
        ttk.Checkbutton(frame, text="锁定宽高比", variable=vars_map["lock_aspect_ratio"]).grid(row=len(fields), column=1, sticky="w", pady=3)
        frame.columnconfigure(1, weight=1)
        applying = {"busy": False}

        def apply_live(_name=None, _index=None, _mode=None) -> None:
            if applying["busy"]:
                return
            applying["busy"] = True
            try:
                layer.name = vars_map["name"].get().strip() or snapshot["name"]
                layer.material_id = vars_map["material_id"].get().strip()
                layer.material_name = vars_map["material_name"].get().strip()
                layer.lock_aspect_ratio = bool(vars_map["lock_aspect_ratio"].get())
                x = float(vars_map["x"].get())
                y = float(vars_map["y"].get())
                width = max(1.0, float(vars_map["width"].get()))
                height = max(1.0, float(vars_map["height"].get()))
                if layer.lock_aspect_ratio and ratio > 0:
                    # 实时预览时保留初始宽高比，减少误操作造成的素材变形。
                    height = width / ratio
                    vars_map["height"].set(f"{height:g}")
                layer.x = x
                layer.y = y
                layer.width = width
                layer.height = height
                self._refresh_layers_panel()
                self._redraw_preview()
            except ValueError:
                pass
            finally:
                applying["busy"] = False

        def restore_snapshot() -> None:
            for key, value in snapshot.items():
                setattr(layer, key, value)
            self._refresh_layers_panel()
            self._redraw_preview()
            window.destroy()

        for var in vars_map.values():
            var.trace_add("write", apply_live)
        buttons = ttk.Frame(frame)
        buttons.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="确定", command=window.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="取消", command=restore_snapshot).pack(side="left")
        window.protocol("WM_DELETE_WINDOW", restore_snapshot)

    # ===== B 图层变真实：真实动态行（由 document.layers 驱动） =====
    def _schedule_render_layers(self) -> None:
        """延后到 idle 再渲染图层行（去重）。两个目的：
        1) 避免在某行控件自己的回调里把自己 destroy；
        2) 不在「画布右键菜单/重绘」等同步流程里现场创建 CTkOptionMenu
           （真实运行无碍，但测试会 monkeypatch tkinter.Menu，现场建会撞到替身）。
        """
        if getattr(self, "_render_layers_scheduled", False):
            return
        root = getattr(self, "root", None)
        if root is not None:
            self._render_layers_scheduled = True
            root.after_idle(self._run_scheduled_render_layers)

    def _run_scheduled_render_layers(self) -> None:
        self._render_layers_scheduled = False
        self._render_layers()

    def _layer_status_text(self, layer) -> str:
        """图标后的小状态标：隐藏=🚫、锁定=🔒（正常图层为空）。空文本图层的「info」走内容列显示。"""
        parts: list[str] = []
        if not layer.visible:
            parts.append("🚫")
        if layer.locked:
            parts.append("🔒")
        return " ".join(parts)

    @staticmethod
    def _abbrev(text: str, limit: int) -> str:
        """库名/素材名/内容缩写：超长截断 + 省略号（中文按字符算，够窄列用）。"""
        s = str(text or "")
        return s if len(s) <= limit else s[: max(1, limit - 1)] + "…"

    def _layer_icon_spec(self, layer) -> tuple[str, str]:
        """类型小图标：文本=蓝底 T，末尾爱心=粉底 ♥，素材/图片=绿底 ▣。"""
        if isinstance(layer, AnchoredHeartLayer):
            return ("♥", "#e0556f")
        if isinstance(layer, TextLayer):
            return ("T", APP_COLORS["accent"])
        return ("▣", "#3fb27f")

    def _layer_main_text(self, layer) -> str:
        """行内主内容：文本层=识别到的文字内容，图片层=引用的素材名称（空则返回 ''，调用方显示占位）。"""
        if isinstance(layer, TextLayer):
            for attr in ("original_text", "text", "render_text"):
                value = str(getattr(layer, attr, "") or "").strip()
                if value:
                    return value
            return ""
        # 图片层：优先显示引用的素材名称，回落到文件名 / 图层名。
        material = str(getattr(layer, "material_name", "") or "").strip()
        if material:
            return material
        path = getattr(layer, "path", None)
        if path is not None:
            return path.stem
        return str(getattr(layer, "name", "") or "").strip()

    def _layer_dim_text(self, layer) -> str:
        """右侧灰字缩写：文本层=字体·字号，素材层=素材库缩写。"""
        if isinstance(layer, TextLayer):
            font = self._font_label_for_layer(layer) \
                or self._lib_label_for_id(self.active_bundle.font_libraries, layer.font_library_id)
            parts = [self._abbrev(font, 6)] if font else []
            parts.append(str(layer.font_size))
            return " · ".join(parts)
        lib = self._lib_label_for_id(self.active_bundle.image_libraries, layer.library_id)
        return self._abbrev(lib, 8) if lib else ""

    def _bind_layer_menu(self, widget, layer) -> None:
        """递归把右键/中键弹层菜单绑到整行（含 CTkOptionMenu 内部控件）——右键图层即打开其功能菜单。"""
        widget.bind("<Button-3>", lambda e, layer_ref=layer: self._layer_menu(layer_ref, e))
        widget.bind("<Button-2>", lambda e, layer_ref=layer: self._layer_menu(layer_ref, e))
        for child in widget.winfo_children():
            self._bind_layer_menu(child, layer)

    def _lib_label_for_id(self, libraries, library_id: str) -> str:
        if not library_id:
            return ""
        lib = next((library for library in libraries if library.id == library_id), None)
        return self._library_label(lib) if lib is not None else ""

    def _flower_label_for_layer(self, layer) -> str:
        path = getattr(layer, "path", None)
        for label, asset in self.flower_label_map.items():
            if asset.path == path:
                return label
        return ""

    def _font_label_for_layer(self, layer) -> str:
        path = getattr(layer, "font_path", None)
        if path is None:
            return ""
        for label, asset in self.font_label_map.items():
            if asset.path == path:
                return label
        return ""

    def _render_layers(self) -> None:
        """按 self.document.layers 增量渲染真实图层行（顶层在上）。

        关键：**不**每次全量 destroy/recreate——只新建/删除变化的行、复用存活行、在原位更新值。
        反复销毁 CTkOptionMenu 会在 customtkinter 的 AppearanceModeTracker 里留下悬挂引用，
        下次创建下拉时崩溃（'DropdownMenu' has no attribute 'master'），故必须增量。
        """
        if self.layers_tree is not None:
            self._render_layers_tree()
            return
        box = self.layers_rows_box
        if box is None:
            return
        order = [layer.id for layer in reversed(self.document.layers)]  # z 大在上，与画布一致
        layer_by_id = {layer.id: layer for layer in self.document.layers}
        # 1) 删除已不存在图层的行（仅此时才销毁控件——频率低）
        for lid in list(self._layer_rows):
            if lid not in layer_by_id:
                self._layer_rows.pop(lid)["card"].destroy()
        # 2) 空列表占位提示
        if not order:
            if self._layers_empty_hint is None:
                self._layers_empty_hint = ctk.CTkLabel(
                    box, text="还没有图层，点下方「+ 文字图层 / + 图片图层」添加", anchor="w",
                    text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11), wraplength=270, justify="left",
                )
                self._layers_empty_hint.grid(row=0, column=0, sticky="ew", pady=4)
            self._layer_row_widgets = []
            return
        if self._layers_empty_hint is not None:
            self._layers_empty_hint.destroy()
            self._layers_empty_hint = None
        # 3) 新建缺失行 + 在原位更新所有行 + 按当前顺序重排
        selected_id = self.document.selected_layer_id
        for ui_row, lid in enumerate(order):
            layer = layer_by_id[lid]
            row = self._layer_rows.get(lid)
            if row is None:
                row = self._build_layer_row(box, layer)
                self._layer_rows[lid] = row
            self._update_layer_row(row, layer, lid == selected_id)
            row["card"].grid_configure(row=ui_row, column=0)
        self._layer_row_widgets = [(self._layer_rows[lid]["card"], lid) for lid in order]

    def _render_layers_tree(self) -> None:
        tree = self.layers_tree
        if tree is None:
            return
        tree.delete(*tree.get_children(""))

        def insert_layers(parent: str, layers: list) -> None:
            for layer in reversed(layers):
                tags = []
                pinnable, pinned = self._layer_pin_state(layer)
                if not layer.visible:
                    tags.append("hidden")
                if layer.locked:
                    tags.append("locked")
                if pinned:
                    tags.append("pinned")
                tree.insert(
                    parent,
                    "end",
                    iid=layer.id,
                    text=self._layer_tree_name(layer),
                    values=(
                        self._layer_resource_cell(layer),
                        "👁" if layer.visible else "🚫",
                        "🔒" if pinned else ("🔓" if pinnable else "·"),
                        "⊘" if layer.locked else "🗑",
                    ),
                    tags=tuple(tags),
                    open=not bool(getattr(layer, "collapsed", False)),
                )
                if isinstance(layer, GroupLayer):
                    insert_layers(layer.id, layer.children)

        insert_layers("", self.document.layers)
        selected = self.document.selected_layer()
        if selected is not None and tree.exists(selected.id):
            tree.selection_set(selected.id)
            tree.focus(selected.id)
            self.layer_detail_var.set(f"已选：{selected.name} ({selected.type})")
            self._sync_layer_properties(selected)
        else:
            self.layer_detail_var.set("未选择图层")

    def _layer_tree_name(self, layer) -> str:
        # 实时显示内容优先：文字层=文本框内容，图片层=素材名；都没有才回落到图层名。
        label = self._layer_main_text(layer) or str(getattr(layer, "name", "") or "").strip() or "Layer"
        _pinnable, pinned = self._layer_pin_state(layer)
        suffix = "  [已锁定]" if pinned else ""
        return f"{self._layer_icon_spec(layer)[0]} {label}{suffix}"

    def _layer_resource_cell(self, layer) -> str:
        """图层行「资源」格文案：图片层=当前素材名，文字层=当前字体名，其它(爱心/图组)=·。
        只读图层自身字段，不查 bundle/flower_label_map，故 headless 测试也安全。"""
        if isinstance(layer, AnchoredHeartLayer):
            return "·"
        if isinstance(layer, ImageLayer):
            name = str(getattr(layer, "material_name", "") or getattr(layer, "name", "") or "").strip()
            return self._abbrev(name, 10) if name else "（选素材）"
        if isinstance(layer, TextLayer):
            font = getattr(layer, "font_path", None)
            label = (Path(font).stem if font else "") or str(getattr(layer, "font_key", "") or "").strip()
            return self._abbrev(label, 10) if label else "（选字体）"
        return "·"

    def _build_layer_row(self, box, layer) -> dict:
        """建一行图层卡（**单行·灰字缩写**）：拖柄 + 类型图标 + 状态 + 提取内容 + 右侧灰字库缩写。

        改库/素材/字体走右键整行菜单（行内不放下拉，更整洁、信息熵更高）。返回控件引用 dict 供增量复用。
        """
        is_text = isinstance(layer, TextLayer)
        row: dict = {"is_text": is_text}
        card = ctk.CTkFrame(
            box, fg_color=APP_COLORS["input"], corner_radius=7,
            border_width=1, border_color=APP_COLORS["border"],
        )
        card.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        card.columnconfigure(0, weight=1)
        row["card"] = card

        line = ctk.CTkFrame(card, fg_color="transparent")
        line.grid(row=0, column=0, sticky="ew", padx=7, pady=6)
        line.columnconfigure(3, weight=1)  # 内容列吃掉余宽，灰字靠右
        row["line"] = line
        # 拖柄：按住拖动调序（仅此控件触发拖动，避免和整行左键选中冲突）。
        handle = ctk.CTkLabel(line, text="⠿", text_color=APP_COLORS["muted"], width=12, cursor="fleur")
        handle.grid(row=0, column=0, padx=(0, 4))
        handle.bind("<ButtonPress-1>", lambda e, layer_ref=layer: self._layer_drag_start(layer_ref, e))
        handle.bind("<B1-Motion>", self._layer_drag_motion)
        handle.bind("<ButtonRelease-1>", self._layer_drag_release)
        row["handle"] = handle
        # 类型小图标：蓝 T = 文本，绿 ▣ = 素材。
        icon = ctk.CTkLabel(
            line, text="T", width=22, height=22, corner_radius=5,
            fg_color=APP_COLORS["accent"], text_color="#ffffff",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        icon.grid(row=0, column=1, padx=(0, 6))
        row["icon"] = icon
        # 状态：隐藏=🚫、锁定=🔒（正常为空）。
        status = ctk.CTkLabel(line, text="", text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11))
        status.grid(row=0, column=2, padx=(0, 3))
        row["status"] = status
        # 提取内容（主）：文本=识别文字 / 素材=文件名；空文本层显示灰色 info。
        content = ctk.CTkLabel(line, text="", anchor="w", text_color=APP_COLORS["text"], font=ctk.CTkFont(size=12))
        content.grid(row=0, column=3, sticky="ew")
        row["content"] = content
        # 库信息缩写（右，灰字）：文本=字体·字号 / 素材=素材库缩写。
        dim = ctk.CTkLabel(line, text="", anchor="e", text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11))
        dim.grid(row=0, column=4, padx=(6, 0), sticky="e")
        row["dim"] = dim
        # 左键整行选中（拖柄除外）；右键整行（含子控件）弹功能菜单——像桌面右键图标，此处图标换成一行图层。
        for area in (card, line, icon, status, content, dim):
            area.bind("<Button-1>", lambda _e, layer_ref=layer: self._select_layer_row(layer_ref))
        self._bind_layer_menu(card, layer)
        return row

    def _update_layer_row(self, row: dict, layer, is_selected: bool) -> None:
        """在原位更新一行（图标/状态/内容/灰字 + 选中边框）；不销毁控件。
        同时把卡背景复位为常态色——拖动时被临时调暗的行，重渲染即恢复。"""
        row["card"].configure(
            fg_color=APP_COLORS["input"],
            border_width=2 if is_selected else 1,
            border_color=APP_COLORS["accent"] if is_selected else APP_COLORS["border"],
        )
        icon_text, icon_color = self._layer_icon_spec(layer)
        row["icon"].configure(text=icon_text, fg_color=icon_color)
        row["status"].configure(text=self._layer_status_text(layer))
        main = self._layer_main_text(layer)
        if main:
            row["content"].configure(text=self._abbrev(main, 18), text_color=APP_COLORS["text"])
        else:
            placeholder = "info" if row["is_text"] else "（未选素材）"
            row["content"].configure(text=placeholder, text_color=APP_COLORS["muted"])
        row["dim"].configure(text=self._layer_dim_text(layer))

    # ---- 行内交互回调（写回图层；行重建一律 after_idle 防自毁）----
    def _select_layer_row(self, layer) -> None:
        self.document.selected_layer_id = layer.id
        self.selected_preview_item = layer.id
        self._sync_layer_properties(layer)
        self._redraw_preview()
        self._schedule_render_layers()

    def _on_layers_tree_select(self, _event=None) -> None:
        tree = self.layers_tree
        if tree is None:
            return
        selection = tree.selection()
        if not selection:
            return
        layer = self.document.layer_by_id(selection[0])
        if layer is None:
            return
        self.document.selected_layer_id = layer.id
        self.selected_preview_item = layer.id
        self._sync_layer_properties(layer)
        self._redraw_preview()

    def _on_layers_tree_button_press(self, event):
        tree = self.layers_tree
        if tree is None:
            return None
        row_id = tree.identify_row(event.y)
        column = tree.identify_column(event.x)
        self._tree_drag_source_id = row_id or None
        self._tree_drag_started = False
        if not row_id:
            return None
        layer = self.document.layer_by_id(row_id)
        if layer is None:
            return None
        if column == "#1":  # 资源格：弹库 + 素材/字体选择菜单
            self._open_layer_resource_picker(layer, event)
            return "break"
        if column == "#2":  # 👁
            self.document.selected_layer_id = layer.id
            self._toggle_selected_layer_visible()
            return "break"
        if column == "#3":  # 🔒 锁定初始位置
            self._toggle_layer_initial_pin(layer)
            return "break"
        if column == "#4":  # 🗑
            self.document.selected_layer_id = layer.id
            self._delete_selected_layer()
            return "break"
        return None

    def _on_layers_tree_drag_motion(self, _event):
        if self._tree_drag_source_id:
            self._tree_drag_started = True

    def _on_layers_tree_button_release(self, event):
        tree = self.layers_tree
        source_id = self._tree_drag_source_id
        started = self._tree_drag_started
        self._tree_drag_source_id = None
        self._tree_drag_started = False
        if tree is None or not source_id or not started:
            return None
        target_id = tree.identify_row(event.y)
        if not target_id or target_id == source_id:
            return None
        position = self._tree_drop_position(target_id, event.y)
        self._reparent_tree_layer(source_id, target_id, position)
        return "break"

    def _tree_drop_position(self, target_id: str, y: int) -> str:
        """据落点 y 在目标行内的高度，定「前/后/入组」三放置区。

        面板按 z 大在上（reversed）渲染，视觉方向与列表方向相反：落在行**上缘**→视觉在目标上方→
        列表 ``after``；落在**下缘**→列表 ``before``；落在**图组中段**→放进组内 ``inside``。
        """
        tree = self.layers_tree
        target = self.document.layer_by_id(target_id)
        is_group = isinstance(target, GroupLayer)
        bbox = tree.bbox(target_id) if tree is not None else None
        if not bbox:
            return "inside" if is_group else "before"
        _x, row_y, _w, row_h = bbox
        frac = (y - row_y) / row_h if row_h else 0.5
        if is_group and 0.25 <= frac <= 0.75:
            return "inside"
        return "after" if frac < 0.5 else "before"

    def _reparent_tree_layer(self, source_id: str, target_id: str, position: str) -> None:
        """拖拽落点 → models.reparent_layer（跨组移动 + 组循环检测）。只有真移动了才留撤销点。"""
        self._push_document_history()  # 先压入移动前快照
        if reparent_layer(self.document, source_id, target_id, position):
            self.selected_preview_item = source_id
            self.status_var.set("图层已移动")
            self._refresh_layers_panel()
            self._redraw_preview()
            return
        # reparent 的所有拒绝分支都在改动文档之前 return → 文档原样未变，弹掉刚压入的多余撤销点。
        # ponytail: 极端下(先 undo、再做被拒拖拽)会顺带清掉一个待重做点，可忽略。
        history = getattr(self, "history_manager", None)
        if history is not None and history.undo_stack:
            history.undo_stack.pop()
        self.status_var.set(self._reparent_reject_hint(source_id, target_id))

    def _reparent_reject_hint(self, source_id: str, target_id: str) -> str:
        """给被拒拖拽一句人话原因（错误反馈）。"""
        _container, source = self.document.container_of(source_id)
        if source is not None and source.locked:
            return "锁定图层不能拖动，先解锁再移动"
        if isinstance(source, GroupLayer) and self._group_contains(source, target_id):
            return "不能把图组拖进它自己内部"
        return "无法移动到该位置"

    def _group_contains(self, group, target_id: str) -> bool:
        """target_id 是否落在 group 的子树内（含深层嵌套）。"""
        if not isinstance(group, GroupLayer):
            return False
        return any(
            child.id == target_id or self._group_contains(child, target_id)
            for child in group.children
        )

    def _duplicate_selected_layer(self) -> None:
        """复制当前选中图层（含整组子树），插到其上方并选中副本。"""
        layer = self.document.selected_layer()
        if layer is None:
            self.status_var.set("未选择图层")
            return
        self._push_document_history()
        copy = duplicate_layer(self.document, layer.id)
        if copy is None:
            history = getattr(self, "history_manager", None)
            if history is not None and history.undo_stack:
                history.undo_stack.pop()
            self.status_var.set("复制失败")
            return
        self.selected_preview_item = copy.id
        self.status_var.set(f"已复制：{copy.name}")
        self._refresh_layers_panel()
        self._redraw_preview()

    def _show_layers_tree_context_menu(self, event):
        tree = self.layers_tree
        if tree is None:
            return
        row_id = tree.identify_row(event.y)
        layer = self.document.layer_by_id(row_id)
        if layer is None:
            return
        self._layer_menu(layer, event)

    def _on_layer_image_lib_changed(self, layer, label: str) -> None:
        self.document.selected_layer_id = layer.id
        self._with_programmatic_update(lambda: self.image_library_var.set(label))
        self._refresh_flower_choices()  # 更新 flower_label_map + 隐藏 combo（fallback 保留）
        self._schedule_render_layers()

    def _on_layer_material_changed(self, layer, label: str) -> None:
        self.document.selected_layer_id = layer.id
        self.selected_preview_item = layer.id
        asset = self.flower_label_map.get(label)
        if asset is not None and isinstance(layer, ImageLayer):
            if not asset.path.is_file():
                messagebox.showerror("素材错误", f"素材文件不存在：{asset.path}")
            else:
                self._push_document_history()
                material_key = asset.asset_key or asset.path.stem
                found = self.active_bundle.resolve_material(material_key)
                layer.path = asset.path
                layer.name = asset.display_name or asset.name
                layer.material_id = material_key
                layer.material_key = material_key
                layer.material_name = asset.display_name or asset.name
                if found:
                    layer.library_id = found[0]
                # 保留手动几何：换素材只改引用，不清 production、不按库默认重烘位置（用户拍板）。
                self.status_var.set(f"素材 → {layer.name}")
        self._redraw_preview()
        self._schedule_render_layers()

    def _on_layer_font_lib_changed(self, layer, label: str) -> None:
        self.document.selected_layer_id = layer.id
        self._with_programmatic_update(lambda: self.font_library_var.set(label))
        self._refresh_font_choices()  # 更新 font_label_map + 隐藏 combo（fallback 保留）
        self._schedule_render_layers()

    def _on_layer_font_changed(self, layer, label: str) -> None:
        self.document.selected_layer_id = layer.id
        self.selected_preview_item = layer.id
        asset = self.font_label_map.get(label)
        if asset is not None and isinstance(layer, TextLayer):
            self._push_document_history()
            layer.font_path = asset.path
            font_found = self.active_bundle.resolve_font_by_tags(index=asset.index)
            if font_found:
                layer.font_library_id = font_found[0]
                layer.font_key = font_found[1].key
            # 保留手动几何：换字体只改引用 + 重算字形，不清 production、不按 pin 重烘位置（用户拍板）。
            self._apply_auto_glyph_rules_to_layer(layer)
            self.status_var.set(f"字体 → {asset.name}")
        self._redraw_preview()
        self._schedule_render_layers()

    def _on_layer_font_size_changed(self, layer, var) -> None:
        try:
            size = max(1, int(float(var.get())))
        except (ValueError, TypeError):
            return
        if isinstance(layer, TextLayer) and size != layer.font_size:
            self._push_document_history()
            layer.font_size = size
            self.status_var.set(f"字号 → {size}")
            self._redraw_preview()

    # ---- B4 拖动调序（动画：插入指示线）----
    # 交互：拖柄按住拖动 → 被拖行调暗「抬起」、行间出现一条蓝色落点线指示将插入的位置；
    # 松手即把图层移到该落点。落点线用 place 覆盖在图层容器上，不挤动其它行（CTk 里最稳）。
    def _layer_drag_start(self, layer, event) -> None:
        self._drag_layer_id = layer.id
        self._drop_insert_index = None
        self.document.selected_layer_id = layer.id  # 拖动即选中（不触发重渲染，避免抖动）
        row = self._layer_rows.get(layer.id)
        if row is not None:  # 被拖行「抬起」视觉：调暗背景 + 蓝边
            row["card"].configure(
                fg_color=APP_COLORS["panel"], border_color=APP_COLORS["accent"], border_width=2,
            )
        self.status_var.set("拖动调序中… 蓝线处松手放置")

    def _layer_drag_motion(self, event) -> None:
        if not self._drag_layer_id:
            return
        box = self.layers_rows_box
        rows = self._layer_row_widgets
        if box is None or not rows:
            return
        # 落点 = 指针越过哪一行的中线 → 插到那一行之前；都没越过则插到最末。
        insert_idx = len(rows)
        for i, (card, _lid) in enumerate(rows):
            try:
                top = card.winfo_rooty()
                height = card.winfo_height()
            except Exception:
                continue
            if event.y_root < top + height / 2:
                insert_idx = i
                break
        self._drop_insert_index = insert_idx
        indicator = self._ensure_drop_indicator()
        try:
            box_top = box.winfo_rooty()
            if insert_idx < len(rows):
                target_card = rows[insert_idx][0]
                gap_y = target_card.winfo_rooty() - box_top - 2
            else:
                last_card = rows[-1][0]
                gap_y = last_card.winfo_rooty() + last_card.winfo_height() - box_top
            indicator.place(x=3, y=max(0, gap_y), relwidth=0.96)
            indicator.lift()
        except Exception:
            pass

    def _layer_drag_release(self, _event) -> None:
        drag_id = self._drag_layer_id
        insert_idx = self._drop_insert_index
        self._clear_drag_visuals()
        self._drag_layer_id = None
        self._drop_insert_index = None
        if drag_id:
            self._reorder_layer_to_index(drag_id, insert_idx)

    def _ensure_drop_indicator(self):
        indicator = self._drop_indicator
        if indicator is None or not indicator.winfo_exists():
            indicator = ctk.CTkFrame(
                self.layers_rows_box, height=3, corner_radius=2, fg_color=APP_COLORS["accent"],
            )
            self._drop_indicator = indicator
        return indicator

    def _clear_drag_visuals(self) -> None:
        indicator = self._drop_indicator
        if indicator is not None and indicator.winfo_exists():
            indicator.place_forget()
        drag_id = self._drag_layer_id
        if drag_id:  # 复位被拖行背景（重渲染也会复位，这里先恢复防闪烁）
            row = self._layer_rows.get(drag_id)
            if row is not None and row["card"].winfo_exists():
                row["card"].configure(fg_color=APP_COLORS["input"])

    def _reorder_layer_to_index(self, drag_id: str, insert_idx) -> None:
        """把 drag_id 行移到「显示顺序第 insert_idx 个之前」。显示顺序是 reversed(layers)（顶层在上）。"""
        if insert_idx is None:
            return
        order_ids = [lid for (_card, lid) in self._layer_row_widgets]  # 显示顺序 上→下
        if drag_id not in order_ids:
            return
        old_pos = order_ids.index(drag_id)
        if insert_idx > old_pos:  # 移除自身后，落点索引左移一位
            insert_idx -= 1
        insert_idx = max(0, min(insert_idx, len(order_ids) - 1))
        if insert_idx == old_pos:
            return  # 落回原位，免重排
        self._push_document_history()
        order_ids.pop(old_pos)
        order_ids.insert(insert_idx, drag_id)
        layer_by_id = {doc_layer.id: doc_layer for doc_layer in self.document.layers}
        self.document.layers[:] = [layer_by_id[lid] for lid in reversed(order_ids)]  # 列表是 下→上
        self.document.normalize_z_indexes()
        self.status_var.set("图层顺序已更新")
        self._render_layers()
        self._redraw_preview()

    # ---- B5 右键/⋮ 菜单（接真实操作，复用既有逻辑）----
    def _add_resource_cascades(self, menu, layer) -> bool:
        """把「素材库/素材」(图片层) 或「字体库/字体」(文字层) 级联加进 menu；返回是否加了任何项。
        右键菜单与图层行「资源」格点击共用此函数。用原生 tk.Menu（非 CTkOptionMenu），
        规避反复销毁下拉在 customtkinter AppearanceModeTracker 留悬挂引用的崩溃。"""
        added = False
        if isinstance(layer, ImageLayer) and not isinstance(layer, AnchoredHeartLayer):
            lib_labels = list(self._image_lib_by_label)
            if lib_labels:
                lib_menu = tk.Menu(menu, tearoff=False)
                for lbl in lib_labels:
                    lib_menu.add_command(label=self._abbrev(lbl, 24),
                                         command=lambda layer_ref=layer, x=lbl: self._on_layer_image_lib_changed(layer_ref, x))
                menu.add_cascade(label="素材库", menu=lib_menu)
                added = True
            item_labels = list(self.flower_label_map)
            if item_labels:
                item_menu = tk.Menu(menu, tearoff=False)
                for lbl in item_labels:
                    item_menu.add_command(label=self._abbrev(lbl, 28),
                                          command=lambda layer_ref=layer, x=lbl: self._on_layer_material_changed(layer_ref, x))
                menu.add_cascade(label="素材", menu=item_menu)
                added = True
        if isinstance(layer, TextLayer):
            lib_labels = list(self._font_lib_by_label)
            if lib_labels:
                lib_menu = tk.Menu(menu, tearoff=False)
                for lbl in lib_labels:
                    lib_menu.add_command(label=self._abbrev(lbl, 24),
                                         command=lambda layer_ref=layer, x=lbl: self._on_layer_font_lib_changed(layer_ref, x))
                menu.add_cascade(label="字体库", menu=lib_menu)
                added = True
            font_labels = list(self.font_label_map)
            if font_labels:
                font_menu = tk.Menu(menu, tearoff=False)
                for lbl in font_labels:
                    font_menu.add_command(label=self._abbrev(lbl, 28),
                                          command=lambda layer_ref=layer, x=lbl: self._on_layer_font_changed(layer_ref, x))
                menu.add_cascade(label="字体", menu=font_menu)
                added = True
        return added

    def _open_layer_resource_picker(self, layer, event=None) -> None:
        """点图层行「资源」格 → 弹库 + 素材(图片)/字体(文字) 选择菜单，定位在点击处。"""
        if isinstance(layer, AnchoredHeartLayer) or not isinstance(layer, (ImageLayer, TextLayer)):
            self.status_var.set("该图层不支持选择素材/字体")
            return
        self._select_layer_row(layer)
        menu = tk.Menu(self.root, tearoff=False)
        if not self._add_resource_cascades(menu, layer):
            self.status_var.set("暂无可选素材库/字体库，请先在资源库添加")
            return
        try:
            x = event.x_root if event is not None else self.root.winfo_pointerx()
            y = event.y_root if event is not None else self.root.winfo_pointery()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _layer_menu(self, layer, event=None) -> None:
        self._select_layer_row(layer)
        menu = tk.Menu(self.root, tearoff=False)
        # 锚定爱心：调相对文字的 mm 参数（绝对 X/Y 每帧被 resolve 覆盖，不在此调）。
        if isinstance(layer, AnchoredHeartLayer):
            menu.add_command(label="爱心间距 / 大小…", command=lambda layer_ref=layer: self._open_heart_anchor_dialog(layer_ref))
        else:
            menu.add_command(label="位置 / 尺寸…", command=lambda layer_ref=layer: self._open_layer_geometry_dialog(layer_ref))
        # 改库 / 改素材或字体：候选来自 active_bundle，与图层行「资源」格点击共用 _add_resource_cascades。
        self._add_resource_cascades(menu, layer)
        if isinstance(layer, TextLayer):
            align_menu = tk.Menu(menu, tearoff=False)
            for key, lbl in (("left", "左对齐"), ("center", "居中"), ("right", "右对齐")):
                align_menu.add_command(label=lbl, command=lambda layer_ref=layer, k=key: self._set_layer_align(layer_ref, k))
            menu.add_cascade(label="对齐", menu=align_menu)
        group_ids = self._selected_layer_ids_for_group(layer.id)
        can_group = len(group_ids) >= 2
        menu.add_separator()
        menu.add_command(
            label="组合所选",
            command=lambda layer_id=layer.id: self._group_selected_layers(layer_id),
            state="normal" if can_group else "disabled",
        )
        menu.add_command(
            label="自动布局组合所选",
            command=lambda layer_id=layer.id: self._auto_layout_selected_layers(layer_id),
            state="normal" if can_group else "disabled",
        )
        if isinstance(layer, GroupLayer):
            menu.add_command(
                label="转换为自动布局组合",
                command=lambda group_id=layer.id: self._convert_group_to_auto_layout(group_id),
                state="disabled" if isinstance(layer, AutoLayoutGroupLayer) else "normal",
            )
            menu.add_command(label="解除组合", command=lambda group_id=layer.id: self._ungroup_layer(group_id))
        menu.add_separator()
        menu.add_command(label="隐藏" if layer.visible else "显示", command=self._toggle_selected_layer_visible)
        menu.add_command(label="解锁" if layer.locked else "锁定", command=self._toggle_selected_layer_locked)
        move_menu = tk.Menu(menu, tearoff=False)
        for act, lbl in (("up", "上移"), ("down", "下移"), ("top", "置顶"), ("bottom", "置底")):
            move_menu.add_command(label=lbl, command=lambda a=act: self._move_selected_layer(a))
        menu.add_cascade(label="调整层级", menu=move_menu)
        menu.add_separator()
        menu.add_command(label="删除图层", command=self._delete_selected_layer)
        try:
            x = event.x_root if event is not None else self.root.winfo_pointerx()
            y = event.y_root if event is not None else self.root.winfo_pointery()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _selected_layer_ids_for_group(self, fallback_id: str | None = None) -> list[str]:
        tree = self.layers_tree
        raw_ids: list[str] = []
        if tree is not None:
            try:
                raw_ids.extend(str(item) for item in tree.selection())
            except Exception:
                raw_ids = []
        if fallback_id and fallback_id not in raw_ids:
            raw_ids.append(fallback_id)
        container_key = None
        ids: list[str] = []
        for layer_id in raw_ids:
            container, layer = self.document.container_of(layer_id)
            if container is None or layer is None or layer.locked:
                continue
            if container_key is None:
                container_key = id(container)
            if id(container) != container_key:
                continue
            if layer_id not in ids:
                ids.append(layer_id)
        return ids

    def _pop_last_history_snapshot(self) -> None:
        history = getattr(self, "history_manager", None)
        if history is not None and history.undo_stack:
            history.undo_stack.pop()

    def _group_selected_layers(self, fallback_id: str | None = None) -> None:
        ids = self._selected_layer_ids_for_group(fallback_id)
        if len(ids) < 2:
            self.status_var.set("至少选择两个同级图层才能组合")
            return
        self._push_document_history()
        group = group_layers(self.document, ids, name="图组")
        if group is None:
            self._pop_last_history_snapshot()
            self.status_var.set("这些图层不能组合")
            return
        self.selected_preview_item = group.id
        self.status_var.set("已组合所选图层")
        self._refresh_layers_panel()
        self._redraw_preview()

    def _auto_layout_selected_layers(self, fallback_id: str | None = None) -> None:
        ids = self._selected_layer_ids_for_group(fallback_id)
        if len(ids) < 2:
            self.status_var.set("至少选择两个同级图层才能创建自动布局")
            return
        self._push_document_history()
        group = auto_layout_group_layers(self.document, ids, name="自动布局组", gap=16, align="center")
        if group is None:
            self._pop_last_history_snapshot()
            self.status_var.set("这些图层不能创建自动布局")
            return
        resolve_auto_layout(self.document)
        self.selected_preview_item = group.id
        self.status_var.set("已创建横向自动布局组（gap 16，垂直居中）")
        self._refresh_layers_panel()
        self._redraw_preview()

    def _convert_group_to_auto_layout(self, group_id: str | None = None) -> None:
        self._push_document_history()
        group = convert_group_to_auto_layout(self.document, group_id, gap=16, align="center")
        if group is None:
            self._pop_last_history_snapshot()
            self.status_var.set("只能把普通图组转换为自动布局")
            return
        self.selected_preview_item = group.id
        self.status_var.set("已转换为横向自动布局组")
        self._refresh_layers_panel()
        self._redraw_preview()

    def _ungroup_layer(self, group_id: str | None = None) -> None:
        self._push_document_history()
        restored = ungroup_layer(self.document, group_id)
        if not restored:
            self._pop_last_history_snapshot()
            self.status_var.set("当前图层不是图组")
            return
        self.selected_preview_item = restored[0].id
        self.status_var.set("已解除组合")
        self._refresh_layers_panel()
        self._redraw_preview()

    def _set_layer_align(self, layer, key: str) -> None:
        if isinstance(layer, TextLayer):
            self._push_document_history()
            layer.align = key
            self.status_var.set(f"对齐 → {key}")
            self._redraw_preview()

    # --- Packet 1：非模态属性栏 overlay（替换 grab_set 模态对话框，§11 状态机）---

    @staticmethod
    def _clamp_overlay_position(x: float, y: float, bar_w: float, bar_h: float,
                               win_w: float, win_h: float, margin: float = 8.0) -> tuple[float, float]:
        """把属性栏夹紧在主窗内，永不离开视口（纯坐标计算，§11）。"""
        max_x = max(margin, win_w - bar_w - margin)
        max_y = max(margin, win_h - bar_h - margin)
        return min(max(x, margin), max_x), min(max(y, margin), max_y)

    def _inspector_entry_widgets(self) -> tuple:
        """属性栏内的 Entry 控件（供 _focus_is_text_input 让出画布快捷键）。"""
        return tuple(getattr(self, "_inspector_entries", ()) or ())

    def _open_inspector_overlay(self, layer) -> None:
        """非模态属性栏：普通 CTkFrame，**不 grab_set / 不 wait_window**，绑现有共享 var。

        落在画布上的事件照常进 _on_canvas_*；只有点进栏内 Entry 才消费事件（§11）。
        """
        self.document.selected_layer_id = layer.id
        self._inspector_layer_id = layer.id
        self._inspector_suppress_trace = True   # _sync 写 var 不应触发事务/重绘
        self._sync_layer_properties(layer)
        self._inspector_suppress_trace = False

        # 已开则只刷新内容（选别的层时复用同一栏）。
        existing = getattr(self, "_inspector_frame", None)
        if existing is not None:
            try:
                existing.destroy()
            except Exception:
                pass

        parent = self.root
        frame = ctk.CTkFrame(parent, corner_radius=8) if ctk is not None else tk.Frame(parent, bd=1, relief="solid")
        frame.columnconfigure(1, weight=1)
        self._inspector_frame = frame
        self._inspector_entries = []
        self._inspector_traces = []

        rows = [("位置 X", self.layer_x_var), ("位置 Y", self.layer_y_var),
                ("宽", self.layer_w_var), ("高", self.layer_h_var)]
        if isinstance(layer, TextLayer):
            rows.append(("字号", self.layer_font_size_var))

        for i, (lbl, var) in enumerate(rows):
            if ctk is not None:
                ctk.CTkLabel(frame, text=lbl).grid(row=i, column=0, padx=8, pady=4, sticky="w")
                entry = ctk.CTkEntry(frame, textvariable=var, width=110)
            else:
                tk.Label(frame, text=lbl).grid(row=i, column=0, padx=8, pady=4, sticky="w")
                entry = tk.Entry(frame, textvariable=var, width=12)
            entry.grid(row=i, column=1, padx=8, pady=4, sticky="ew")
            entry.bind("<FocusOut>", lambda _e: self._inspector_commit())
            entry.bind("<Return>", lambda _e: self._inspector_commit())
            entry.bind("<Escape>", lambda _e: self._inspector_rollback())
            self._inspector_entries.append(entry)
            trace_id = var.trace_add("write", self._on_inspector_var_write)
            self._inspector_traces.append((var, trace_id))

        if ctk is not None:
            ctk.CTkButton(frame, text="关闭", width=60, command=self._close_inspector_overlay).grid(
                row=len(rows), column=0, columnspan=2, padx=8, pady=(2, 6), sticky="ew"
            )
        else:
            tk.Button(frame, text="关闭", command=self._close_inspector_overlay).grid(
                row=len(rows), column=0, columnspan=2, padx=8, pady=(2, 6), sticky="ew"
            )

        # 夹紧到视口内（栏自身坐标，绝不写进 layer，§11）。
        frame.update_idletasks()
        try:
            bar_w = frame.winfo_reqwidth()
            bar_h = frame.winfo_reqheight()
            win_w = parent.winfo_width() or parent.winfo_reqwidth()
            win_h = parent.winfo_height() or parent.winfo_reqheight()
        except tk.TclError:
            bar_w, bar_h, win_w, win_h = 160, 200, 1000, 700
        px, py = self._clamp_overlay_position(win_w - bar_w - 24, 80, bar_w, bar_h, win_w, win_h)
        frame.place(x=px, y=py)
        frame.lift()

    def _on_inspector_var_write(self, *_args) -> None:
        """var trace：首次改值开事务，之后每次写 layer + 重绘（去抖），不重复压栈（§11/§12）。"""
        if getattr(self, "_inspector_suppress_trace", False):
            return
        layer = self.document.layer_by_id(getattr(self, "_inspector_layer_id", None))
        if layer is None:
            return
        # 首次改值 → 进入编辑事务（压一次快照）。
        self.history_manager.begin_transaction(self.document)
        if not self._write_inspector_vars_to_layer(layer):
            return
        # 实时预览：复用 25ms 去抖全量重绘。
        self._schedule_canvas_render()

    def _write_inspector_vars_to_layer(self, layer) -> bool:
        """把栏内 var 写回 layer 几何；非法值（空/非数字/<=0）静默忽略，返回是否写成功。

        绝不写 preview_pan_x/y 或栏自身坐标到 layer（移动栏不移动图层，§11）。
        """
        try:
            x = float(self.layer_x_var.get())
            y = float(self.layer_y_var.get())
            width = float(self.layer_w_var.get())
            height = float(self.layer_h_var.get())
        except (ValueError, tk.TclError):
            return False
        if width <= 0 or height <= 0:
            return False
        layer.x, layer.y, layer.width, layer.height = x, y, width, height
        font_size: int | None = None
        if isinstance(layer, TextLayer):
            try:
                font_size = max(1, int(float(self.layer_font_size_var.get())))
                layer.font_size = font_size
            except (ValueError, tk.TclError):
                font_size = None
        # 与 _apply_layer_production 一致：记录图层级生产 override（随层走）。
        layer.production = ProductionParams(x=x, y=y, width=width, height=height, font_size=font_size)
        return True

    def _inspector_commit(self) -> None:
        """失焦 / 回车：提交事务（连续编辑合并为一条 undo）。"""
        history = getattr(self, "history_manager", None)
        if history is not None:
            history.commit_transaction()

    def _inspector_rollback(self) -> None:
        """Escape：回滚到进入编辑前快照。"""
        history = getattr(self, "history_manager", None)
        if history is not None:
            history.rollback_transaction(self._restore_document_snapshot)

    def _close_inspector_overlay(self) -> None:
        self._inspector_commit()
        frame = getattr(self, "_inspector_frame", None)
        for var, trace_id in getattr(self, "_inspector_traces", ()) or ():
            try:
                var.trace_remove("write", trace_id)
            except Exception:
                pass
        self._inspector_traces = []
        self._inspector_entries = []
        self._inspector_layer_id = None
        if frame is not None:
            try:
                frame.destroy()
            except Exception:
                pass
        self._inspector_frame = None

    def _open_layer_geometry_dialog(self, layer) -> None:
        """位置/尺寸小对话框：复用 layer_x/y/w/h(+字号) var 与 _apply_layer_production 写回。

        Packet 1：默认走非模态属性栏 overlay（INSPECTOR_OVERLAY=1，不阻塞画布、实时预览）；
        关掉 flag 时退回此对话框，但已去掉 grab_set，故即便走旧路径也不再独占输入。
        """
        if INSPECTOR_OVERLAY:
            self._open_inspector_overlay(layer)
            return
        self.document.selected_layer_id = layer.id
        self._sync_layer_properties(layer)
        win = ctk.CTkToplevel(self.root)
        win.title("位置 / 尺寸")
        win.transient(self.root)
        win.columnconfigure(1, weight=1)
        rows = [("位置 X", self.layer_x_var), ("位置 Y", self.layer_y_var),
                ("宽", self.layer_w_var), ("高", self.layer_h_var)]
        if isinstance(layer, TextLayer):
            rows.append(("字号", self.layer_font_size_var))
        for i, (lbl, var) in enumerate(rows):
            ctk.CTkLabel(win, text=lbl).grid(row=i, column=0, padx=10, pady=6, sticky="w")
            ctk.CTkEntry(win, textvariable=var, width=120).grid(row=i, column=1, padx=10, pady=6, sticky="ew")

        def apply_and_close() -> None:
            self._apply_layer_production()
            win.destroy()

        self._btn(win, "应用", apply_and_close, primary=True).grid(
            row=len(rows), column=0, columnspan=2, padx=10, pady=10, sticky="ew"
        )
        win.update_idletasks()

    def _open_heart_anchor_dialog(self, layer) -> None:
        """末尾爱心 mm 调节框：与文字的间距 / 上下偏移 / 大小（mm）。

        爱心是锚定文字的从属图层，位置每帧由 anchor_resolve 重算，故不调绝对 X/Y，改调相对
        文字的 mm 参数。预填「当前有效 mm」：显式值直接显示，自动(None)时按已 resolve 的实际像素反算。
        """
        if not isinstance(layer, AnchoredHeartLayer):
            return
        self.document.selected_layer_id = layer.id
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            layout = EngravingLayout()
        phys_w = self._template_physical_size_mm(layout)[0] or 80.0
        px_per_mm = (self.document.canvas_width / phys_w) if phys_w else 1.0
        anchor = self.document.layer_by_id(layer.anchor_layer_id)
        if layer.size_mm is not None:
            size_mm = float(layer.size_mm)
        else:
            size_mm = (layer.height / px_per_mm) if px_per_mm else 0.0
        if layer.gap_mm is not None:
            gap_mm = float(layer.gap_mm)
        else:
            try:
                fit = compute_text_fit(anchor) if isinstance(anchor, TextLayer) else None
                gap_px = ENDING_HEART_GAP_RATIO * fit.font_size if fit is not None else 0.0
            except Exception:
                gap_px = 0.0
            gap_mm = (gap_px / px_per_mm) if px_per_mm else 0.0
        offset_mm = float(layer.offset_y_mm or 0.0)

        gap_var = tk.StringVar(value=f"{gap_mm:.2f}")
        offset_var = tk.StringVar(value=f"{offset_mm:.2f}")
        size_var = tk.StringVar(value=f"{size_mm:.2f}")

        win = ctk.CTkToplevel(self.root)
        win.title("末尾爱心")
        win.transient(self.root)
        win.columnconfigure(1, weight=1)
        rows = [("与文字间距 (mm)", gap_var), ("上下偏移 (mm)", offset_var), ("大小 (mm)", size_var)]
        for i, (lbl, var) in enumerate(rows):
            ctk.CTkLabel(win, text=lbl).grid(row=i, column=0, padx=10, pady=6, sticky="w")
            ctk.CTkEntry(win, textvariable=var, width=120).grid(row=i, column=1, padx=10, pady=6, sticky="ew")

        def apply_and_close() -> None:
            try:
                gap = float(gap_var.get())
                off = float(offset_var.get())
                size = float(size_var.get())
            except ValueError:
                messagebox.showerror("末尾爱心", "间距 / 偏移 / 大小必须是数字")
                return
            if size <= 0:
                messagebox.showerror("末尾爱心", "大小必须大于 0")
                return
            layer.gap_mm = gap
            layer.offset_y_mm = off
            layer.size_mm = size
            self.status_var.set("末尾爱心参数已应用")
            self._redraw_preview()
            self._refresh_layers_panel()
            win.destroy()

        self._btn(win, "应用", apply_and_close, primary=True).grid(
            row=len(rows), column=0, columnspan=2, padx=10, pady=10, sticky="ew"
        )
        win.update_idletasks()
        # Packet 1：去掉 grab_set，末尾爱心调节框不再独占输入（画布仍可拖/缩/选）。

    def _refresh_layers_panel(self) -> None:
        """刷新右下角图层面板，显示名称、类型、显隐和锁定状态。"""
        self._schedule_render_layers()  # 真实图层行：延后到 idle 渲染（去重；不在同步流程里现场建控件）

    def _on_layer_list_select(self, _event=None) -> None:
        self._on_layers_tree_select(_event)

    def _sync_layer_properties(self, layer) -> None:
        # Packet 1：layer→var 是程序性写入（选层/画布拖动同步栏），不应触发属性栏事务/重绘。
        prev_suppress = getattr(self, "_inspector_suppress_trace", False)
        self._inspector_suppress_trace = True
        try:
            if isinstance(layer, TextLayer):
                self.layer_text_var.set(layer.original_text)
                self.layer_font_size_var.set(str(layer.font_size))
                self.layer_color_var.set(layer.fill_color or layer.color)
                self.layer_bold_var.set(bool(getattr(layer, "bold", None) or False))
                self.layer_underline_var.set(bool(getattr(layer, "underline", None) or False))
                self.layer_letter_spacing_var.set(f"{float(getattr(layer, 'letter_spacing', 0) or 0):g}")
            else:
                self.layer_text_var.set("")
            # 增量4：几何字段显示该图层当前有效几何（live = 用户在画布上看到的位置/尺寸）。
            self.layer_x_var.set(f"{layer.x:g}")
            self.layer_y_var.set(f"{layer.y:g}")
            self.layer_w_var.set(f"{layer.width:g}")
            self.layer_h_var.set(f"{layer.height:g}")
        finally:
            self._inspector_suppress_trace = prev_suppress

    def _slot_defaults(self, layer) -> ProductionParams:
        """图层「槽位」的产品级生产默认，取自当前布局默认 EngravingLayout（回落链最低层）。"""
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            layout = active_product(self.config).defaults
        if isinstance(layer, TextLayer):
            return ProductionParams(
                x=layout.text_x, y=layout.text_y, width=layout.text_width,
                height=layout.text_height, font_size=layout.text_size,
            )
        return ProductionParams(
            x=layout.flower_x, y=layout.flower_y,
            width=layout.flower_width, height=layout.flower_height,
        )

    def _pin_key(self, layer) -> str | None:
        if isinstance(layer, AnchoredHeartLayer):
            return None
        if isinstance(layer, TextLayer):
            return "text:0"
        material_key = str(getattr(layer, "material_key", "") or "").strip()
        library_id = str(getattr(layer, "library_id", "") or "").strip()
        if library_id and material_key:
            return f"image:{library_id}:{material_key}"
        path = getattr(layer, "path", None)
        if path:
            return f"path:{Path(path).name}"
        return None

    def _pin_for(self, layer) -> ProductionParams | None:
        key = self._pin_key(layer)
        if not key:
            return None
        for pin in active_product(self.config).layer_pins:
            if pin.key == key:
                return pin.production
        return None

    def _layer_pin_state(self, layer) -> tuple[bool, bool]:
        """返回 (可锁定, 已锁定)。AnchoredHeartLayer 的几何派生自文字，不独立 pin。"""
        key = self._pin_key(layer)
        if not key:
            return False, False
        return True, any(pin.key == key for pin in active_product(self.config).layer_pins)

    def _layer_library_entry_defaults(self, layer) -> tuple[ProductionParams | None, ProductionParams | None]:
        """按图层挂的库/素材 key 反查（库默认, 素材默认）生产参数；查不到返回 (None, None)。"""
        if isinstance(layer, TextLayer):
            libraries = self.active_bundle.font_libraries
            library_id, key = layer.font_library_id, layer.font_key
        else:
            libraries = self.active_bundle.image_libraries
            library_id, key = layer.library_id, layer.material_key
        library = next((lib for lib in libraries if lib.id == library_id), None)
        if library is None:
            return None, None
        entry = library.by_key(key) if key else None
        return library.defaults, (entry.defaults if entry is not None else None)

    def _layer_effective_production(self, layer) -> ProductionParams:
        """§5 回落链：产品默认 → 库默认 → 素材默认 → pin → 图层 override（低→高）。"""
        library_defaults, entry_defaults = self._layer_library_entry_defaults(layer)
        return resolve_chain(self._slot_defaults(layer), library_defaults, entry_defaults, self._pin_for(layer), layer.production)

    @staticmethod
    def _valid_pin_snapshot(production: ProductionParams) -> bool:
        values = (production.x, production.y, production.width, production.height, production.rotation)
        return (
            all(value is not None and math.isfinite(float(value)) for value in values)
            and float(production.width or 0) > 0
            and float(production.height or 0) > 0
            and (production.font_size is None or int(production.font_size) > 0)
        )

    def _snapshot_layer_production(self, layer) -> ProductionParams | None:
        font_size = int(layer.font_size) if isinstance(layer, TextLayer) else None
        snapshot = ProductionParams(
            x=float(layer.x),
            y=float(layer.y),
            width=float(layer.width),
            height=float(layer.height),
            rotation=float(getattr(layer, "rotation", 0.0) or 0.0),
            font_size=font_size,
        )
        return snapshot if self._valid_pin_snapshot(snapshot) else None

    def _apply_effective_production_to_layer(self, layer) -> None:
        production = self._layer_effective_production(layer)
        for attr in ("x", "y", "width", "height", "rotation"):
            value = getattr(production, attr)
            if value is not None:
                setattr(layer, attr, float(value))
        if isinstance(layer, TextLayer):
            if production.font_size is not None:
                layer.font_size = int(production.font_size)
            layer.text_box_width = layer.width
            layer.text_box_height = layer.height

    def _toggle_layer_initial_pin(self, layer=None) -> None:
        layer = layer or self.document.selected_layer()
        if layer is None:
            self.status_var.set("未选择有效图层")
            return
        key = self._pin_key(layer)
        if not key:
            self.status_var.set("该图层的位置由其他图层派生，不能独立锁定初始位置")
            return
        product = active_product(self.config)
        existing = {pin.key: pin for pin in product.layer_pins}
        if key in existing:
            pins = tuple(pin for pin in product.layer_pins if pin.key != key)
            self.config = with_product_layer_pins(self.config, pins)
            save_config(self.config)
            self.status_var.set("已取消初始位置锁定")
        else:
            snapshot = self._snapshot_layer_production(layer)
            if snapshot is None:
                self.status_var.set("当前图层几何无效，未写入锁定")
                return
            pins = product.layer_pins + (LayerPin(key, snapshot),)
            self.config = with_product_layer_pins(self.config, pins)
            save_config(self.config)
            self.status_var.set("已锁定该素材的初始位置")
        self._refresh_layers_panel()
        self._redraw_preview()

    def _apply_layer_production(self) -> None:
        layer = self.document.selected_layer()
        if layer is None:
            self.status_var.set("未选择有效图层")
            return
        try:
            x = float(self.layer_x_var.get())
            y = float(self.layer_y_var.get())
            width = float(self.layer_w_var.get())
            height = float(self.layer_h_var.get())
        except ValueError:
            messagebox.showerror("生产参数", "位置/尺寸必须是数字")
            return
        if width <= 0 or height <= 0:
            messagebox.showerror("生产参数", "宽和高必须大于 0")
            return
        # 写回画布几何（与拖拽同一路径，仍经导出 _apply_canvas_fit，不旁路 WYSIWYG）。
        self._push_document_history()
        layer.x, layer.y, layer.width, layer.height = x, y, width, height
        font_size: int | None = None
        if isinstance(layer, TextLayer):
            try:
                font_size = max(1, int(self.layer_font_size_var.get()))
            except ValueError:
                font_size = None
            if font_size is not None:
                layer.font_size = font_size
        # 记录为图层级生产参数 override（随图层走，供再次 seed / 导出元数据；只填用户给的字段）。
        layer.production = ProductionParams(x=x, y=y, width=width, height=height, font_size=font_size)
        self.status_var.set("生产参数已应用")
        self._refresh_layers_panel()
        self._redraw_preview()

    def _toggle_selected_layer_visible(self) -> None:
        layer = self.document.selected_layer()
        if layer is None:
            self.status_var.set("未选择有效图层")
            return
        self._push_document_history()
        layer.visible = not layer.visible
        self._refresh_layers_panel()
        self._redraw_preview()

    def _toggle_selected_layer_locked(self) -> None:
        layer = self.document.selected_layer()
        if layer is None:
            self.status_var.set("未选择有效图层")
            return
        self._push_document_history()
        layer.locked = not layer.locked
        self._refresh_layers_panel()
        self._redraw_preview()

    def _delete_selected_layer(self) -> None:
        if self.inline_text_entry is not None:
            return
        selected = self.document.selected_layer()
        if selected is None:
            self.status_var.set("未选择有效图层，或图层已锁定")
            return
        if selected.locked:
            self.status_var.set("图层已锁定，先在右键菜单解锁")
            return
        if not messagebox.askyesno("删除图层", f"确定删除「{selected.name}」？"):
            return
        self._push_document_history()
        removed = delete_layer(self.document, self.document.selected_layer_id)
        if removed is None:
            self.status_var.set("未选择有效图层，或图层已锁定")
        elif isinstance(removed, TextLayer):
            remove_anchored_heart_for(self.document, removed.id)
            if self.document.selected_layer() is None:
                remaining = list(self.document.iter_all_layers())
                self.document.selected_layer_id = remaining[-1].id if remaining else None
        self.selected_preview_item = self.document.selected_layer_id
        self._refresh_layers_panel()
        self._redraw_preview()

    def _move_selected_layer(self, action: str) -> None:
        self._push_document_history()
        if not move_layer(self.document, self.document.selected_layer_id, action):
            self.history_manager.undo_stack.pop()
            self.status_var.set("图层无法移动")
            return
        self._refresh_layers_panel()
        self._redraw_preview()

    def _apply_text_layer_properties(self) -> None:
        layer = self.document.selected_layer()
        if not isinstance(layer, TextLayer):
            self.status_var.set("当前选中图层不是文本图层")
            return
        old_text = layer.original_text
        new_text = self.layer_text_var.get()
        try:
            font_size = max(1, int(self.layer_font_size_var.get()))
        except ValueError:
            messagebox.showerror("文本属性", "字号必须是整数")
            return
        try:
            spacing = float(self.layer_letter_spacing_var.get())
        except ValueError:
            messagebox.showerror("文本属性", "字间距必须是数字")
            return
        self._push_document_history()
        layer.original_text = new_text
        layer.raw_text = new_text
        layer.text = new_text
        if old_text != new_text and layer.glyph_overrides:
            LOGGER.info("文本内容变化，清空特殊字形绑定：layer_id=%s", layer.id)
            layer.glyph_overrides.clear()
            self.status_var.set("文本内容已变化，特殊字形需要重新应用")
        layer.render_text = new_text
        layer.font_size = font_size
        layer.fill_color = self.layer_color_var.get().strip() or "#111111"
        layer.color = layer.fill_color
        # 字体样式 per-layer override：直接写概数布尔/字间距（覆盖建层时烘的全局默认）。
        layer.bold = bool(self.layer_bold_var.get())
        layer.underline = bool(self.layer_underline_var.get())
        layer.letter_spacing = spacing
        layer.tracking = spacing  # 两字段同步，避免导出端 `letter_spacing or tracking` 读到旧值。
        # 字号=真实大小：图层属性面板改字号即按字号反推文本框（框随字号长大，§58）；超画布安全区则封顶。
        # 菜单栏全局设置不走此路、不覆盖各图层；手动「宽/高」走 _apply_layer_production，互不影响。
        clamped = self._resize_text_box_to_font(layer)
        self._refresh_layers_panel()
        self._redraw_preview()
        if clamped:
            self.status_var.set("字号过大：已按画布安全区可雕刻范围封顶")

    def _resize_text_box_to_font(self, layer: TextLayer, *, clamp_to_safe_area: bool = True) -> bool:
        """按图层当前字号+文字墨迹反推文本框尺寸（字号=真实大小、框随墨迹长大、最多自动断 2 行），
        并以原框中心为锚重定位 → 改字号/改文字时文字中心不跳、框对称地绕中心长大或缩小。

        clamp_to_safe_area=True（默认）：框最大封顶到画布安全区，超出则 text_box_size_for_font 缩字号，
        返回是否被封顶。
        clamp_to_safe_area=False（画布内联编辑文字用）：给极大上限 → 永不封顶、字号守恒，框随墨迹自由
        长大（可越出画布安全区）；返回「框是否已超出安全区」仅作非阻塞提示。"""
        font_path = getattr(layer, "font_path", None)
        text = (getattr(layer, "original_text", "") or getattr(layer, "text", "") or "").strip()
        safe_w = max(1.0, self.document.canvas_width - 2 * SAFE_MARGIN_X)
        safe_h = max(1.0, self.document.canvas_height - 2 * SAFE_MARGIN_Y)
        max_w, max_h = (safe_w, safe_h) if clamp_to_safe_area else (UNBOUNDED_BOX_SIZE, UNBOUNDED_BOX_SIZE)
        adv = ENDING_HEART_ADVANCE_RATIO if getattr(layer, "ending_heart", False) else 0.0
        new_w, new_h, clamped = text_box_size_for_font(
            text, layer.font_size, font_path,
            max_width=max_w, max_height=max_h, ending_advance_ratio=adv,
        )
        # 以原框中心为锚，改字号/改文字时文字中心不动。
        old_cx = layer.x + layer.text_box_width * layer.scale_x / 2
        old_cy = layer.y + layer.text_box_height * layer.scale_y / 2
        layer.text_box_width = new_w
        layer.text_box_height = new_h
        layer.width = new_w  # 文本图层视觉范围=文本框，同步保旋转中心/选择框/导出几何一致
        layer.height = new_h
        layer.x = old_cx - new_w * layer.scale_x / 2
        layer.y = old_cy - new_h * layer.scale_y / 2
        if clamp_to_safe_area:
            return clamped
        return bool(new_w * layer.scale_x > safe_w or new_h * layer.scale_y > safe_h)

    def _nudge_selected_layer(self, dx: int, dy: int) -> None:
        if self.inline_text_entry is not None:
            return
        layer = self.document.selected_layer()
        if layer is None or layer.locked:
            return
        self._push_document_history()
        layer.x += dx
        layer.y += dy
        self._redraw_preview()

    def _scan_assets(self, show_errors: bool) -> None:
        self.flower_assets = scan_flower_assets(Path(self.flower_dir_var.get()))
        self.font_assets = scan_font_assets(Path(self.font_source_var.get()))
        # 增量5：主库目录仍以单目录入口（flower_dir_var/font_source_var）为准——保证单目录选择器
        # 即时生效；产品配置里「首个之外」的目录作为附加库一起进 bundle（多库）。
        product = active_product(self.config)
        image_dirs = [Path(self.flower_dir_var.get()), *product.image_library_dirs[1:]]
        font_dirs = [Path(self.font_source_var.get()), *product.font_library_dirs[1:]]
        self.active_bundle = LibraryBundle.from_dirs(image_dirs, font_dirs)
        # 增量3：把「附加库」（首库之外）的素材/字体并入候选，使素材库选择器能切到它们（单库时空操作）。
        self._merge_additional_library_assets()
        self.preview_cache.clear()
        self._refresh_library_choices()
        self._render_library_rows()
        self._refresh_flower_choices()
        self._refresh_font_choices()

        warnings: list[str] = []
        if not self.flower_assets:
            warnings.append("未找到花朵 SVG；请检查 BirthMonth flowers 目录。")
        if not self.font_assets:
            warnings.append("未找到字体文件；请检查 Birthmonth_font.ttf 或字体目录。")
        if warnings:
            self._set_warnings(warnings)
            if show_errors:
                messagebox.showwarning("素材扫描", "\n".join(warnings))
        else:
            self._set_warnings([])
        self._redraw_preview()

    def _refresh_flower_choices(self) -> None:
        # 刷新素材列表属于程序化 UI 更新，只能同步下拉框与 pending 素材，不能创建新图层。
        # 增量3：候选按当前选中的素材库过滤（单库时即全部）。
        assets = self._assets_for_selected_image_library()
        self.flower_label_map = {self._flower_label(asset): asset for asset in assets}
        values = list(self.flower_label_map) or ["（请扫描素材）"]
        self._with_programmatic_update(lambda: self.flower_combo.configure(values=values))
        last_result = getattr(self, "last_parse_result", None)
        if last_result is not None:
            self._select_flower_by_parse_result(last_result)
        # ponytail: 无解析结果时也给默认选中，否则「+ 图片图层」读空 flower_asset_var 静默失败
        if self.flower_label_map and self.flower_asset_var.get() not in self.flower_label_map:
            self._set_pending_flower_asset(next(iter(self.flower_label_map)))
        self._update_month_chip()
        self._redraw_preview()

    def _refresh_font_choices(self) -> None:
        # 增量3：候选按当前选中的字体库过滤（单库时即全部）。
        assets = self._assets_for_selected_font_library()
        self.font_label_map = {self._font_label(asset): asset for asset in assets}
        self.font_combo.configure(values=list(self.font_label_map) or ["（请扫描字体）"])
        self._select_font_by_current_field()

    def _merge_additional_library_assets(self) -> None:
        """把素材库 entries 里 scan_flower_assets 没覆盖到的素材并入候选。

        - 图像库：遍历**全部**库（含主库）。主库里带月份名的花已由 scan_flower_assets 收录，
          这里把**无月份名**的素材（如 X.svg、png 图层）按 entry 补进来（month/flower 兜底，
          见 _entry_to_flower_asset），使界面素材列表与文件夹实际内容一致——否则主库里
          不带月份名的新素材两条扫描路都收不到（这是「读 25 文件、列表只 24」的根因）。
        - 字体库：scan_font_assets 已覆盖主库全部字体，故只并「首库之外」的附加字体库。
        按 path.name 去重，不会与 scan 结果重复。
        """
        existing = {asset.path.name for asset in self.flower_assets}
        for library in self.active_bundle.image_libraries:
            for entry in library.entries:
                if entry.path.name not in existing:
                    self.flower_assets.append(self._entry_to_flower_asset(entry))
                    existing.add(entry.path.name)
        existing_fonts = {asset.path.name for asset in self.font_assets}
        for library in self.active_bundle.font_libraries[1:]:
            for entry in library.entries:
                if entry.path.name not in existing_fonts:
                    self.font_assets.append(self._entry_to_font_asset(entry))
                    existing_fonts.add(entry.path.name)

    def _entry_to_flower_asset(self, entry) -> FlowerAsset:
        return FlowerAsset(
            name=entry.name,
            path=entry.path,
            asset_key=entry.key,
            display_name=entry.name,
            is_vector_safe=entry.is_vector_safe,
        )

    def _entry_to_font_asset(self, entry) -> FontAsset:
        return FontAsset(
            name=entry.name,
            index=_coerce_int(entry.tags.get("index"), 0),
            path=entry.path,
            font_design=entry.name,
        )

    def _library_label(self, library) -> str:
        return library.name or library.id

    def _refresh_library_choices(self) -> None:
        """增量3：用 active_bundle 刷新素材库/字体库下拉候选（数据驱动）。"""
        self._image_lib_by_label = {self._library_label(lib): lib for lib in self.active_bundle.image_libraries}
        self._font_lib_by_label = {self._library_label(lib): lib for lib in self.active_bundle.font_libraries}
        self._configure_library_combo(self.image_library_combo, self.image_library_var, self._image_lib_by_label, "（无素材库）")
        self._configure_library_combo(self.font_library_combo, self.font_library_var, self._font_lib_by_label, "（无字体库）")

    def _configure_library_combo(self, combo, var: tk.StringVar, label_map: dict, empty_text: str) -> None:
        if combo is None:
            return
        labels = list(label_map) or [empty_text]
        self._with_programmatic_update(lambda: combo.configure(values=labels))
        if var.get() not in label_map:
            self._with_programmatic_update(lambda: var.set(labels[0]))

    def _assets_for_selected_image_library(self) -> list:
        library = self._image_lib_by_label.get(self.image_library_var.get())
        if library is None:
            return self.flower_assets
        names = {entry.path.name for entry in library.entries}
        filtered = [asset for asset in self.flower_assets if asset.path.name in names]
        return filtered or self.flower_assets  # 库无匹配（如导入临时素材）→ 回落全部，避免清空

    def _assets_for_selected_font_library(self) -> list:
        library = self._font_lib_by_label.get(self.font_library_var.get())
        if library is None:
            return self.font_assets
        names = {entry.path.name for entry in library.entries}
        filtered = [asset for asset in self.font_assets if asset.path.name in names]
        return filtered or self.font_assets

    def _update_month_chip(self) -> None:
        """chip 反映当前选中素材（月份/花序号已删，改显示素材名）。"""
        asset = self.flower_label_map.get(self.flower_asset_var.get())
        self.month_chip_var.set((asset.display_name or asset.name) if asset is not None else "—")

    def _on_image_library_selected(self) -> None:
        if self._is_loading or self._is_programmatic_update:
            return
        self._refresh_flower_choices()

    def _on_font_library_selected(self) -> None:
        if self._is_loading or self._is_programmatic_update:
            return
        self._refresh_font_choices()

    def _on_flower_combo_selected(self) -> None:
        self._on_flower_selection_changed(self.flower_asset_var.get())

    def _on_flower_selection_changed(self, material_id: str) -> None:
        """处理素材下拉框变化：无素材图层时只记录待添加素材，选中素材图层时才替换资源。"""
        if self._is_loading or self._is_programmatic_update:
            return
        asset = self.flower_label_map.get(material_id)
        if asset is None:
            self.pending_flower_asset_label = ""
            return
        selected_layer = self.document.selected_layer()
        if isinstance(selected_layer, ImageLayer):
            self._replace_selected_image_layer(asset)
            return
        # 未选中图层或当前选中的是文本图层时，下拉框仅更新 pending 素材，不能影响现有图层。
        self._set_pending_flower_asset(material_id, sync_fields=True)
        self.status_var.set("已选择待添加素材，请点击“添加素材”")

    def _set_pending_flower_asset(self, material_id: str, *, sync_fields: bool = False) -> None:
        """保存待添加素材但不触发新增图层。sync_fields 形参保留作调用兼容（月份/花序号已删，不再同步）。"""
        self.pending_flower_asset_label = material_id
        self._with_programmatic_update(lambda: self.flower_asset_var.set(material_id))
        self._update_month_chip()  # 刷新素材 chip

    def _replace_selected_image_layer(self, asset: FlowerAsset) -> None:
        """替换当前选中素材图层的图片资源；保持图层尺寸和层级不变。"""
        layer = self.document.selected_layer()
        if not isinstance(layer, ImageLayer):
            return
        if not asset.path.is_file():
            messagebox.showerror("素材错误", f"素材文件不存在：{asset.path}")
            return
        self._push_document_history()
        layer.path = asset.path
        layer.name = asset.display_name or asset.name
        material_key = asset.asset_key or asset.path.stem
        found = self.active_bundle.resolve_material(material_key)
        layer.material_id = material_key
        layer.material_key = material_key
        layer.material_name = asset.display_name or asset.name
        if found:
            layer.library_id = found[0]
        layer.production = None
        self._apply_effective_production_to_layer(layer)
        self._set_pending_flower_asset(self._flower_label(asset), sync_fields=True)
        self._refresh_layers_panel()
        self._redraw_preview()

    def _add_selected_flower_to_canvas(self) -> None:
        asset = self.flower_label_map.get(self.flower_asset_var.get())
        if asset is None:
            return
        if not asset.path.is_file():
            messagebox.showerror("素材错误", f"素材文件不存在：{asset.path}")
            return
        self._set_pending_flower_asset(self.flower_asset_var.get(), sync_fields=True)
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            layout = EngravingLayout()
        # 添加素材必须追加 ImageLayer，不能覆盖已存在的素材图层。
        self._push_document_history()
        material_key = asset.asset_key or asset.path.stem
        found = self.active_bundle.resolve_material(material_key)  # 反查该素材属于哪个库
        layer = add_image_layer(
            self.document,
            asset.path,
            name=asset.display_name or asset.name,
            x=layout.flower_x,
            y=layout.flower_y,
            width=layout.flower_width,
            height=layout.flower_height,
            material_id=material_key,
            material_name=asset.display_name or asset.name,
            library_id=found[0] if found else "",
            material_key=material_key,
        )
        self._apply_effective_production_to_layer(layer)
        self.selected_preview_item = layer.id
        self._refresh_layers_panel()
        self._redraw_preview()

    def _apply_auto_glyph_rules_to_layer(self, layer: TextLayer) -> None:
        """按当前字体规则自动应用首尾字形；失败只提示 warning，不阻塞渲染。"""
        try:
            render_text, overrides, warnings, applied, wants_ending_heart = apply_automatic_glyph_rules(
                layer.original_text,
                self._font_design_label(),
                layer.font_path,
                layer.glyph_overrides,
                self.glyph_rules,
            )
        except Exception as exc:
            LOGGER.warning("自动字形规则失败：font_id=%s reason=%s", self._font_design_label(), exc)
            self.warning_var.set(f"自动字形应用失败：{exc}")
            return
        layer.render_text = render_text
        layer.glyph_overrides = overrides
        # Font 4 等字体末尾改用独立实心爱心：显式置位（非该字体则清零，便于切字体时去掉爱心）。
        layer.ending_heart = bool(wants_ending_heart)
        # 末尾爱心改造成独立锚定图层：选 Font 4 自动补建爱心图层（面板可单独选中、调 mm），
        # 切走则移除该文字的爱心图层。几何由 resolve_anchored_hearts 每次重绘/导出前重算。
        if layer.ending_heart:
            ensure_anchored_heart_for(self.document, layer)
        else:
            remove_anchored_heart_for(self.document, layer.id)
        if applied:
            self.current_glyph_overrides = dict(overrides)
            self.status_var.set("已自动应用字形")
        if warnings:
            self.warning_var.set("；".join(warnings))

    def _add_text_layer_from_fields(self) -> None:
        try:
            layout = self._active_layout_defaults()
        except ValueError:
            layout = EngravingLayout()
        text = self._content_text_for_render().strip() or "Name"
        font_asset = self.font_label_map.get(self.font_asset_var.get())
        font_found = (
            self.active_bundle.resolve_font_by_tags(index=font_asset.index) if font_asset is not None else None
        )
        self._push_document_history()
        layer = add_text_layer(
            self.document,
            text,
            font_path=self._selected_font_path(),
            x=layout.text_x,
            y=layout.text_y,
            width=layout.text_width,
            height=layout.text_height,
            font_size=layout.text_size,
            font_library_id=font_found[0] if font_found else "",
            font_key=font_found[1].key if font_found else "",
        )
        # 烘全局字体样式默认进新图层（渲染端只读图层自身样式；用户可在属性/设置里改）。
        layer.bold = layout.bold
        layer.underline = layout.underline
        layer.bold_strength = layout.bold_strength
        layer.letter_spacing = layout.letter_spacing
        self._apply_auto_glyph_rules_to_layer(layer)
        # 新建即按字号定框（字号=真实大小、框随字号长大，§58；ending_heart 已由自动字形规则置位）。
        self._resize_text_box_to_font(layer)
        if self._pin_for(layer) is not None:
            self._apply_effective_production_to_layer(layer)
        self.selected_preview_item = layer.id
        self._sync_layer_properties(layer)
        self._refresh_layers_panel()
        self._redraw_preview()

    def _show_add_layer_menu(self) -> None:
        """Packet 2：单一「+ 添加图层」入口。弹原生 tk.Menu（复用 _layer_menu/资源选择器的
        tk.Menu 惯用法，避开 CustomTkinter 引用泄漏），各项复用现有处理器，不另写逻辑。"""
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="文字图层", command=self._add_text_layer_from_fields)
        menu.add_command(label="图片素材", command=self._add_selected_flower_to_canvas)
        menu.add_command(label="空白内容层", command=self._add_blank_content_layer)
        menu.add_separator()
        # 组合两项复用 codex（Packet 5）的右键处理器，并沿用其「同级 ≥2 才可组合」guard：
        # 不足 2 个有效选层时置灰（点击也会被处理器内同款判断兜底）。
        can_group = len(self._selected_layer_ids_for_group()) >= 2
        menu.add_command(
            label="普通组合（所选）",
            command=lambda: self._group_selected_layers(),
            state="normal" if can_group else "disabled",
        )
        menu.add_command(
            label="自动布局组合（所选）",
            command=lambda: self._auto_layout_selected_layers(),
            state="normal" if can_group else "disabled",
        )
        try:
            x = self.root.winfo_pointerx()
            y = self.root.winfo_pointery()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _add_blank_content_layer(self) -> None:
        """Packet 2：最小空白内容层 = 未绑素材的 ImageLayer（path=None, material_key=''）。

        选 ImageLayer 而非 TextLayer：path 本就默认 None、资源选择器与预览路径已支持图片层，
        命中走 bounds（非零占位框）；改动最小。给非零默认占位框（不堆零尺寸隐形层），
        画布画虚线占位框 + 「空白内容层」标签（见 _draw_image_layer_preview）；选中后可经
        现有资源选择器绑素材/字体。删除/撤销与普通层一致（add 时压一次 history）。"""
        try:
            layout = self._active_layout_defaults()
        except ValueError:
            layout = EngravingLayout()
        # 占位框尺寸复用版式素材默认（与「图片素材」入口落点一致），坏值兜底成 300×200。
        width = float(getattr(layout, "flower_width", 0) or 0) or 300.0
        height = float(getattr(layout, "flower_height", 0) or 0) or 200.0
        x = float(getattr(layout, "flower_x", 0) or 0)
        y = float(getattr(layout, "flower_y", 0) or 0)
        self._push_document_history()
        layer = ImageLayer(
            name="空白内容层",
            path=None,
            x=x,
            y=y,
            width=width,
            height=height,
            z_index=len(self.document.layers),
        )
        self.document.layers.append(layer)
        self.document.selected_layer_id = layer.id
        self.document.normalize_z_indexes()
        self.selected_preview_item = layer.id
        self.status_var.set("已添加空白内容层（可经「资源」绑定素材）")
        self._refresh_layers_panel()
        self._redraw_preview()

    def _add_universal_layer(self) -> None:
        """通用图层：把当前选中的素材 +/或字体合成一个图层（底座=图组，见 models.add_universal_layer）。

        复用「资源库」现有选择：素材取 flower_asset_var、字体取 font_asset_var；任一为空即跳过，
        两者都空只提示。子层几何按产品版式默认（素材 flower_*、文字 text_*），建后各自可拖动。
        """
        asset = self.flower_label_map.get(self.flower_asset_var.get())
        font_asset = self.font_label_map.get(self.font_asset_var.get())
        if asset is None and font_asset is None:
            messagebox.showinfo("通用图层", "请先在「资源库」里选好素材和/或字体。")
            return
        try:
            layout = self._active_layout_defaults()
        except ValueError:
            layout = EngravingLayout()

        material = None
        if asset is not None and asset.path.is_file():
            material_key = asset.asset_key or asset.path.stem
            found = self.active_bundle.resolve_material(material_key)
            material = dict(
                path=asset.path,
                name=asset.display_name or asset.name,
                x=layout.flower_x, y=layout.flower_y,
                width=layout.flower_width, height=layout.flower_height,
                material_id=material_key, material_name=asset.display_name or asset.name,
                library_id=found[0] if found else "", material_key=material_key,
            )

        text_spec = None
        if font_asset is not None:
            font_found = self.active_bundle.resolve_font_by_tags(index=font_asset.index)
            text_spec = dict(
                text=self._content_text_for_render().strip() or "Name",
                font_path=self._selected_font_path(),
                x=layout.text_x, y=layout.text_y,
                width=layout.text_width, height=layout.text_height,
                font_size=layout.text_size,
                font_library_id=font_found[0] if font_found else "",
                font_key=font_found[1].key if font_found else "",
            )

        self._push_document_history()
        created = add_universal_layer(self.document, name="通用图层", material=material, text=text_spec)
        if created is None:
            return
        children = created.children if isinstance(created, GroupLayer) else [created]
        for child in children:
            if isinstance(child, TextLayer):
                child.bold = layout.bold
                child.underline = layout.underline
                child.bold_strength = layout.bold_strength
                child.letter_spacing = layout.letter_spacing
                self._apply_auto_glyph_rules_to_layer(child)
                self._resize_text_box_to_font(child)
            self._apply_effective_production_to_layer(child)
        self.selected_preview_item = created.id
        self._refresh_layers_panel()
        self._redraw_preview()

    def _on_font_combo_selected(self) -> None:
        self._add_selected_font_to_canvas()

    def _add_selected_font_to_canvas(self) -> None:
        asset = self.font_label_map.get(self.font_asset_var.get())
        if asset is None:
            return
        self.current_manual_glyph_override = None
        self.current_glyph_overrides.clear()
        self.selected_glyph_position = None
        self.font_var.set(str(asset.index))
        layer = self.document.selected_layer()
        if isinstance(layer, TextLayer):
            layer.font_path = asset.path
            self._apply_auto_glyph_rules_to_layer(layer)
            self._sync_layer_properties(layer)
        self._redraw_preview()

    def _select_flower_by_parse_result(self, result) -> None:
        """按解析结果的 material_key / 花名（文件名归一后子串匹配）回选素材下拉框。"""
        query = (getattr(result, "material_key", "") or getattr(result, "flower_name", "") or "").strip()
        needle = "".join(ch for ch in query.casefold() if ch.isalnum())
        if not needle:
            return
        for asset in self.flower_assets:
            for hay in (asset.asset_key, asset.name, asset.path.stem):
                norm = "".join(ch for ch in (hay or "").casefold() if ch.isalnum())
                if norm and (needle == norm or needle in norm or norm in needle):
                    label = self._flower_label(asset)
                    if label in self.flower_label_map:
                        self._set_pending_flower_asset(label)
                    return

    def _select_font_by_current_field(self) -> None:
        try:
            font = int(self.font_var.get())
        except ValueError:
            return
        for label, asset in self.font_label_map.items():
            if asset.index == font:
                self.font_asset_var.set(label)
                return

    def _selected_flower_path(self) -> Path | None:
        asset = self.flower_label_map.get(self.flower_asset_var.get())
        return asset.path if asset else None

    def _selected_font_path(self) -> Path | None:
        asset = self.font_label_map.get(self.font_asset_var.get())
        return asset.path if asset else None

    def _selected_font_name(self) -> str:
        asset = self.font_label_map.get(self.font_asset_var.get())
        return asset.name if asset else ""

    def _selected_preview_font_family(self) -> str:
        asset = self.font_label_map.get(self.font_asset_var.get())
        if asset is None:
            return "TkDefaultFont"
        family = self.preview_font_family_cache.get(asset.path)
        if family:
            return family
        self._load_preview_font(asset.path)
        family = _ttf_family_name(asset.path) or asset.name or "TkDefaultFont"
        self.preview_font_family_cache[asset.path] = family
        return family

    def _load_preview_font(self, font_path: Path) -> None:
        if sys.platform != "win32" or font_path in self.preview_loaded_fonts or not font_path.is_file():
            return
        try:
            ctypes.windll.gdi32.AddFontResourceExW(str(font_path), 0x10, 0)
            self.preview_loaded_fonts.add(font_path)
        except OSError:
            return

    def _selected_flower_name(self) -> str:
        asset = self.flower_label_map.get(self.flower_asset_var.get())
        return asset.name if asset else ""

    def _flower_label(self, asset: FlowerAsset) -> str:
        return f"{asset.display_name or asset.name} | {asset.path.name}"

    def _font_label(self, asset: FontAsset) -> str:
        return format_font_asset_label(asset)

    def _save_current_config(self) -> None:
        # 用 replace 而非整体重建 AppConfig，否则会清空 products/active_product_id/收展态
        # （与 _save_settings_window 同一坑：__post_init__ 只在 products 空时才合成产品0）。
        layout_defaults = self._active_layout_defaults()
        self.config = dataclasses.replace(
            self.config,
            flower_dir=Path(self.flower_dir_var.get()),
            font_source=Path(self.font_source_var.get()),
            output_path=Path(self.output_var.get()),
            output_formats=self._selected_output_formats_or_default(),
        )
        self.config = with_product_defaults(self.config, layout_defaults)
        save_config(self.config)

    def _with_programmatic_update(self, callback):
        previous = self._is_programmatic_update
        self._is_programmatic_update = True
        try:
            return callback()
        finally:
            self._is_programmatic_update = previous

    def _bind_preview_updates(self) -> None:
        for var in self.layout_vars.values():
            var.trace_add("write", lambda *_: self._redraw_preview())
        self.name_var.trace_add("write", lambda *_: self._on_personalization_change())
        self.text_case_var.trace_add("write", lambda *_: self._on_personalization_change())
        self.font_var.trace_add("write", lambda *_: self._on_font_field_change())

    def _on_personalization_change(self) -> None:
        self.current_manual_glyph_override = None
        self.current_glyph_overrides.clear()
        self.selected_glyph_position = None
        self._redraw_preview()

    def _on_flower_field_change(self) -> None:
        if self._is_programmatic_update:
            return
        self._refresh_flower_choices()

    def _on_font_field_change(self) -> None:
        self.current_manual_glyph_override = None
        self.current_glyph_overrides.clear()
        self.selected_glyph_position = None
        self._select_font_by_current_field()
        self._redraw_preview()

    def _reset_layout(self) -> None:
        layout = EngravingLayout()
        self.layout_vars["canvas_width"].set(str(layout.canvas_width))
        self.layout_vars["canvas_height"].set(str(layout.canvas_height))
        self.layout_vars["flower_x"].set(str(layout.flower_x))
        self.layout_vars["flower_y"].set(str(layout.flower_y))
        self.layout_vars["flower_width"].set(str(layout.flower_width))
        self.layout_vars["flower_height"].set(str(layout.flower_height))
        self.layout_vars["text_x"].set(str(layout.text_x))
        self.layout_vars["text_y"].set(str(layout.text_y))
        self.layout_vars["text_width"].set(str(layout.text_width))
        self.layout_vars["text_height"].set(str(layout.text_height))
        self.layout_vars["text_size"].set(str(layout.text_size))

    def _redraw_preview(self) -> None:
        canvas = self.preview_canvas
        if canvas is None:
            return
        self._update_preview_zoom_status()
        canvas.delete("all")
        self.preview_text_images.clear()
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            layout = EngravingLayout()
        scale, offset_x, offset_y = self._preview_transform(layout)

        def sx(value: float) -> float:
            return offset_x + value * scale

        def sy(value: float) -> float:
            return offset_y + value * scale

        canvas.create_rectangle(sx(0), sy(0), sx(layout.canvas_width), sy(layout.canvas_height), outline="#cccccc")
        self.document.canvas_width = layout.canvas_width
        self.document.canvas_height = layout.canvas_height
        auto_layout_warnings = resolve_auto_layout(self.document)
        # 渲染前统一解析锚定爱心：按锚定文字墨迹 + mm 偏移重算每个爱心图层几何，并给被接管文字置
        # ending_heart_detached（文字端不再自贴爱心，避免双爱心）。mm↔px 用模板物理宽度。
        resolve_anchored_hearts(self.document, physical_width_mm=self._template_physical_size_mm(layout)[0])
        # 画布刷新只读取 Document：先清空，再按图层顺序逐层渲染可见图层。
        # ctx 携带 App 自身 + 画布坐标变换（scale/offset + 闭包 sx/sy），provider 据此委托
        # App 现有 _draw_*_preview 绑定方法（Packet 3：分发查表，绘制算法不变）。
        ctx = {
            "app": self,
            "canvas": canvas,
            "scale": scale,
            "offset_x": offset_x,
            "offset_y": offset_y,
            "sx": sx,
            "sy": sy,
        }
        for layer in self.document.flat_render_layers():
            if not layer.visible:
                continue
            # AnchoredHeartLayer 是 ImageLayer 子类，保留专用路径（Packet 3：不强行 provider 化），
            # 必须先判，否则会被 ImageProvider 当普通素材走读盘的圆弧版折线分支。
            if isinstance(layer, AnchoredHeartLayer):
                self._draw_anchored_heart_preview(canvas, layer, scale, offset_x, offset_y)
                continue
            # Packet 3：text/image 经 provider 注册表分发（ADR-001）；委托回 _draw_*_preview。
            provider = get_provider(layer)
            if provider is not None:
                provider.render_preview(layer, ctx)
        if DEBUG_VISUAL_BBOX:
            glyph_result = self._resolve_current_glyph()
            name = glyph_result.render_text.strip() or "Name"
            text_layout = layout_personalization_text(name, layout, self.personalization_type_var.get(), self._selected_font_path())
            self._draw_visual_debug(canvas, layout, text_layout, sx, sy)
        self._draw_selection_controls(canvas, layout, sx, sy)
        if self.document.layers:
            self._set_warnings(auto_layout_warnings)
        else:
            glyph_result = self._resolve_current_glyph()
            name = glyph_result.render_text.strip() or "Name"
            text_layout = layout_personalization_text(name, layout, self.personalization_type_var.get(), self._selected_font_path())
            self._set_readiness_display(self._current_readiness_parse_result(), text_layout)
        # 画布重绘会清空 window item；如果正在内联编辑，重建/移动覆盖编辑器以跟随缩放、平移和图层位置。
        if self.inline_text_entry is not None and not self.inline_text_is_closing:
            self.inline_text_window = None
            self._place_inline_text_editor()
        self._redraw_preview_rulers(layout, scale, offset_x, offset_y)

    def _heart_px_per_mm(self, layout: EngravingLayout) -> float:
        """画布像素/mm：与 resolve_anchored_hearts 同一基准（canvas_width / 模板物理宽度 mm）。"""
        phys_w = self._template_physical_size_mm(layout)[0] or 80.0
        return (self.document.canvas_width / phys_w) if phys_w else 1.0

    def _effective_gap_mm(self, heart, px_per_mm: float) -> float:
        """爱心当前“有效水平间距(mm)”：显式 gap_mm 直接用；自动(None)时按旧 ratio*字号反算。

        拖动时先用它把 None 物化成具体 mm，再叠加位移增量——第一帧之后 gap_mm 已是显式值。
        """
        if heart.gap_mm is not None:
            return float(heart.gap_mm)
        anchor = self.document.layer_by_id(heart.anchor_layer_id)
        if not isinstance(anchor, TextLayer):
            return 0.0
        try:
            fit = compute_text_fit(anchor)
            return (ENDING_HEART_GAP_RATIO * fit.font_size) / px_per_mm if px_per_mm else 0.0
        except Exception:
            return 0.0

    def _template_physical_size_mm(self, layout: EngravingLayout) -> tuple[float, float]:
        """返回当前模板的输出物理尺寸(mm)。读取失败时按既有 DXF 默认宽度 80mm 等比派生高度。"""
        fallback_width = 80.0
        fallback_height = (
            fallback_width * (layout.canvas_height / layout.canvas_width)
            if layout.canvas_width
            else fallback_width
        )
        try:
            phys = load_template_physical_size()
            width = float(phys.width_mm)
            height = float(phys.height_mm)
            if width > 0 and height > 0:
                return width, height
        except Exception as exc:
            LOGGER.warning("读取模板物理尺寸失败,刻度尺使用默认尺寸: %s", exc)
        return fallback_width, fallback_height

    def _ruler_interval_mm(self, px_per_mm: float) -> float:
        """根据当前缩放选择易读的 mm 主刻度间隔；单位固定 mm。
        target_px = 主刻度在屏幕上的目标间距：越小 → 选中的 mm 间隔越小 → 刻度越密越详细。
        取 40px（原 72px）让“缩小/看全板”时刻度更密；放大时本就够细，间隔不再变化。"""
        if px_per_mm <= 0:
            return 10.0
        target_px = 40.0
        for interval in (1, 2, 5, 10, 20, 50, 100, 200, 500):
            if interval * px_per_mm >= target_px:
                return float(interval)
        return 1000.0

    def _redraw_preview_rulers(
        self, layout: EngravingLayout, scale: float, offset_x: float, offset_y: float
    ) -> None:
        x_ruler = self.preview_ruler_x
        y_ruler = self.preview_ruler_y
        corner = self.preview_ruler_corner
        canvas = self.preview_canvas
        if x_ruler is None or y_ruler is None or corner is None or canvas is None:
            return
        for ruler in (x_ruler, y_ruler, corner):
            ruler.delete("all")
        x_ruler.create_rectangle(
            0, 0, max(1, x_ruler.winfo_width()), RULER_THICKNESS, fill="#f8fafc", outline=""
        )
        y_ruler.create_rectangle(
            0, 0, RULER_THICKNESS, max(1, y_ruler.winfo_height()), fill="#f8fafc", outline=""
        )
        corner.create_rectangle(0, 0, RULER_THICKNESS, RULER_THICKNESS, fill="#eef2f7", outline="")
        corner.create_text(
            RULER_THICKNESS - 4,
            RULER_THICKNESS - 5,
            text="mm",
            anchor="se",
            fill=RULER_TEXT_COLOR,
            font=("TkDefaultFont", 8),
        )

        phys_w, phys_h = self._template_physical_size_mm(layout)
        doc_per_mm_x = layout.canvas_width / phys_w if phys_w else 1.0
        doc_per_mm_y = layout.canvas_height / phys_h if phys_h else 1.0
        px_per_mm_x = scale * doc_per_mm_x
        px_per_mm_y = scale * doc_per_mm_y
        major_x = self._ruler_interval_mm(px_per_mm_x)
        major_y = self._ruler_interval_mm(px_per_mm_y)
        minor_x = major_x / 5.0
        minor_y = major_y / 5.0
        self._draw_horizontal_ruler_ticks(x_ruler, offset_x, scale, doc_per_mm_x, phys_w, major_x, minor_x)
        self._draw_vertical_ruler_ticks(y_ruler, offset_y, scale, doc_per_mm_y, phys_h, major_y, minor_y)
        self._draw_ruler_guides(layout, scale, offset_x, offset_y)

    def _draw_horizontal_ruler_ticks(
        self, ruler: tk.Canvas, offset_x: float, scale: float, doc_per_mm: float, max_mm: float, major: float, minor: float
    ) -> None:
        width = max(1, ruler.winfo_width())
        left = max(0.0, offset_x)
        right = min(float(width), offset_x + max_mm * doc_per_mm * scale)
        if right > left:
            ruler.create_rectangle(left, 0, right, RULER_THICKNESS, fill="#ffffff", outline="")
        ruler.create_line(left, RULER_THICKNESS - 1, right, RULER_THICKNESS - 1, fill="#cbd5e1")
        tick = 0.0
        while tick <= max_mm + 1e-6:
            x = offset_x + tick * doc_per_mm * scale
            if 0 <= x <= width:
                is_major = abs((tick / major) - round(tick / major)) < 1e-6
                length = 13 if is_major else 7
                color = RULER_TICK_COLOR if is_major else "#d5dae2"
                ruler.create_line(x, RULER_THICKNESS, x, RULER_THICKNESS - length, fill=color)
                if is_major:
                    ruler.create_text(
                        x + 2,
                        4,
                        text=f"{int(round(tick))}",
                        anchor="nw",
                        fill=RULER_TEXT_COLOR,
                        font=("TkDefaultFont", 8),
                    )
            tick += minor

    def _draw_vertical_ruler_ticks(
        self, ruler: tk.Canvas, offset_y: float, scale: float, doc_per_mm: float, max_mm: float, major: float, minor: float
    ) -> None:
        height = max(1, ruler.winfo_height())
        top = max(0.0, offset_y)
        bottom = min(float(height), offset_y + max_mm * doc_per_mm * scale)
        if bottom > top:
            ruler.create_rectangle(0, top, RULER_THICKNESS, bottom, fill="#ffffff", outline="")
        ruler.create_line(RULER_THICKNESS - 1, top, RULER_THICKNESS - 1, bottom, fill="#cbd5e1")
        tick = 0.0
        while tick <= max_mm + 1e-6:
            y = offset_y + tick * doc_per_mm * scale
            if 0 <= y <= height:
                is_major = abs((tick / major) - round(tick / major)) < 1e-6
                length = 13 if is_major else 7
                color = RULER_TICK_COLOR if is_major else "#d5dae2"
                ruler.create_line(RULER_THICKNESS, y, RULER_THICKNESS - length, y, fill=color)
                if is_major:
                    ruler.create_text(
                        4,
                        y + 2,
                        text=f"{int(round(tick))}",
                        anchor="nw",
                        fill=RULER_TEXT_COLOR,
                        font=("TkDefaultFont", 8),
                    )
            tick += minor

    def _draw_ruler_guides(self, layout: EngravingLayout, scale: float, offset_x: float, offset_y: float) -> None:
        if self.preview_pointer is None or self.preview_ruler_x is None or self.preview_ruler_y is None:
            return
        x, y = self.preview_pointer
        in_doc_x = offset_x <= x <= offset_x + layout.canvas_width * scale
        in_doc_y = offset_y <= y <= offset_y + layout.canvas_height * scale
        if in_doc_x:
            self.preview_ruler_x.create_line(
                x, 0, x, RULER_THICKNESS, fill=RULER_GUIDE_COLOR, width=2, tags=("ruler_guide",)
            )
        if in_doc_y:
            self.preview_ruler_y.create_line(
                0, y, RULER_THICKNESS, y, fill=RULER_GUIDE_COLOR, width=2, tags=("ruler_guide",)
            )

    def _draw_image_layer_preview(self, canvas: tk.Canvas, layer: ImageLayer, sx, sy) -> None:
        """预览素材图层；每个 ImageLayer 独立绘制，不再读取单一 current_asset。"""
        if layer.path is None or not layer.path.exists():
            material_key = getattr(layer, "material_key", "") or getattr(layer, "material_id", "")
            if material_key or layer.path is not None:
                # Packet 4（§8）：已绑素材但磁盘缺失/改名/删除 → 画「素材缺失」占位框（区别于空白未绑层）。
                self._draw_missing_material_placeholder(canvas, layer, sx, sy)
            else:
                # Packet 2：从未绑素材的空白内容层 → 画虚线占位框 + 标签（不是真空，给可见包围盒）。
                self._draw_blank_layer_placeholder(canvas, layer, sx, sy)
            return
        if layer.path.suffix.casefold() in IMPORTABLE_BITMAP_SUFFIXES:
            self._draw_bitmap_image_layer_preview(canvas, layer, sx, sy)
            return
        layout = EngravingLayout(
            canvas_width=self.document.canvas_width,
            canvas_height=self.document.canvas_height,
            flower_x=round(layer.x),
            flower_y=round(layer.y),
            flower_width=round(layer.width * layer.scale_x),
            flower_height=round(layer.height * layer.scale_y),
        )
        try:
            polylines = self.preview_cache.polylines(layer.path, layout)
        except (OSError, ValueError):
            return
        for polyline in polylines:
            points: list[float] = []
            for x, y in polyline:
                points.extend((sx(x), sy(y)))
            if len(points) >= 4:
                canvas.create_line(*points, fill="#555555", width=1, smooth=False, tags=("layer_art", f"layer:{layer.id}"))

    def _draw_blank_layer_placeholder(self, canvas: tk.Canvas, layer: ImageLayer, sx, sy) -> None:
        """Packet 2：未绑素材的空白内容层占位 —— 虚线矩形 + 居中「空白内容层」标签。

        走 layer.bounds（非零占位框），保证有可见包围盒、可命中、可经资源选择器绑素材。"""
        left, top, right, bottom = layer.bounds
        canvas.create_rectangle(
            sx(left), sy(top), sx(right), sy(bottom),
            outline="#888888", dash=(4, 3), width=1,
            tags=("layer_art", f"layer:{layer.id}"),
        )
        canvas.create_text(
            sx((left + right) / 2), sy((top + bottom) / 2),
            text="空白内容层", fill="#888888", anchor="center",
            tags=("layer_art", f"layer:{layer.id}"),
        )

    def _draw_missing_material_placeholder(self, canvas: tk.Canvas, layer: ImageLayer, sx, sy) -> None:
        """Packet 4（§8）：已绑素材但文件缺失的占位 —— 虚线红框 + 「素材缺失: {key}」标签。

        与「空白内容层」区分：这层曾绑过素材但文件丢失/改名/删除，需提示用户重新绑定；
        导出端 _image_layer 对同一情况跳过 + warning，文档仍可打开/导出（仅该层缺席）。"""
        left, top, right, bottom = layer.bounds
        key = getattr(layer, "material_key", "") or getattr(layer, "material_id", "") or "?"
        canvas.create_rectangle(
            sx(left), sy(top), sx(right), sy(bottom),
            outline="#c0392b", dash=(4, 3), width=1,
            tags=("layer_art", f"layer:{layer.id}"),
        )
        canvas.create_text(
            sx((left + right) / 2), sy((top + bottom) / 2),
            text=f"素材缺失: {key}", fill="#c0392b", anchor="center",
            tags=("layer_art", f"layer:{layer.id}"),
        )

    def _draw_bitmap_image_layer_preview(self, canvas: tk.Canvas, layer: ImageLayer, sx, sy) -> None:
        try:
            from PIL import Image, ImageTk
        except Exception:
            return
        try:
            image = Image.open(layer.path).convert("RGBA")
        except Exception:
            return
        target_width = max(1, round((layer.width * layer.scale_x) * (sx(1) - sx(0))))
        target_height = max(1, round((layer.height * layer.scale_y) * (sy(1) - sy(0))))
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
        image.thumbnail((target_width, target_height), resampling)
        try:
            photo = ImageTk.PhotoImage(image, master=canvas)
        except Exception:
            return
        self.preview_text_images.append(photo)
        canvas.create_image(sx(layer.x), sy(layer.y), image=photo, anchor="nw", tags=("layer_art", f"layer:{layer.id}"))

    def _draw_anchored_heart_preview(self, canvas: tk.Canvas, layer: AnchoredHeartLayer, scale: float, offset_x: float, offset_y: float) -> None:
        """预览锚定末尾爱心：用归一化 heart_svg_markup 栅格化（与导出 inlineSvg、文字端贴图同一几何），

        贴到 resolve 算好的画布绝对位置/尺寸。避免读磁盘圆弧版导致预览与导出不一致。
        """
        try:
            from PIL import ImageTk
        except Exception:
            return
        from text_renderer import _rasterize_heart

        target_width = max(1, round(layer.width * layer.scale_x * scale))
        target_height = max(1, round(layer.height * layer.scale_y * scale))
        fill = getattr(layer, "fill_color", "") or "#111111"
        image = _rasterize_heart(fill, target_width, target_height)
        if image is None:
            return
        try:
            photo = ImageTk.PhotoImage(image, master=canvas)
        except Exception:
            return
        self.preview_text_images.append(photo)
        canvas.create_image(
            offset_x + layer.x * scale,
            offset_y + layer.y * scale,
            image=photo,
            anchor="nw",
            tags=("layer_art", f"layer:{layer.id}"),
        )

    def _draw_text_layer_preview(self, canvas: tk.Canvas, layer: TextLayer, scale: float, offset_x: float, offset_y: float) -> None:
        """普通状态只显示 TextRenderer 输出的透明文字图；输入控件不进入最终画布。"""
        try:
            from PIL import ImageTk
        except Exception:
            return
        result = CanvasTextItem(layer).render()
        if result.warnings:
            LOGGER.warning("TextLayer 预览降级：layer_id=%s warnings=%s", layer.id, "; ".join(result.warnings))
            self.warning_var.set("；".join(result.warnings))
        image = result.image
        target_width = max(1, round(image.width * layer.scale_x * scale))
        target_height = max(1, round(image.height * layer.scale_y * scale))
        if image.size != (target_width, target_height):
            try:
                from PIL import Image

                resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
                image = image.resize((target_width, target_height), resampling)
            except Exception:
                image = image.resize((target_width, target_height))
        if layer.rotation:
            try:
                from PIL import Image

                resampling = getattr(getattr(Image, "Resampling", Image), "BICUBIC", 3)
                image = image.rotate(-layer.rotation, expand=True, resample=resampling)
            except Exception:
                image = image.rotate(-layer.rotation, expand=True)
        try:
            photo = ImageTk.PhotoImage(image, master=canvas)
        except Exception:
            return
        self.preview_text_images.append(photo)
        canvas.create_image(
            offset_x + layer.x * scale,
            offset_y + layer.y * scale,
            image=photo,
            anchor="nw",
            tags=("text_art", "layer_art", f"layer:{layer.id}"),
        )

    def _draw_ink_aligned_preview_text(
        self,
        canvas: tk.Canvas,
        line: str,
        origin_x: float,
        origin_y: float,
        font_size: int,
        font_path: Path | None,
        scale: float,
        offset_x: float,
        offset_y: float,
        fill_bounds=None,
    ) -> bool:
        """用 Pillow 生成真实墨迹预览图，让黑色字形边界与布局框一致；失败时回退到 Tk 文本。"""
        try:
            from PIL import ImageTk
        except Exception:
            return False
        preview_size = max(8, round(font_size * scale))
        if fill_bounds is not None:
            image = _preview_text_fill_image(
                line,
                preview_size,
                font_path,
                max(1, round(fill_bounds.width * scale)),
                max(1, round(fill_bounds.height * scale)),
            )
            if image is None:
                return False
            x = offset_x + fill_bounds.left * scale
            y = offset_y + fill_bounds.top * scale
        else:
            image_and_offset = _preview_text_ink_image(line, preview_size, font_path)
            if image_and_offset is None:
                return False
            image, offset_left, offset_top = image_and_offset
            x = offset_x + (origin_x * scale) + offset_left
            y = offset_y + (origin_y * scale) + offset_top
        try:
            photo = ImageTk.PhotoImage(image, master=canvas)
        except Exception:
            return False
        self.preview_text_images.append(photo)
        canvas.create_image(x, y, image=photo, anchor="nw", tags=("text_art",))
        return True

    def _draw_flower_preview(self, canvas: tk.Canvas, layout: EngravingLayout, sx, sy) -> None:
        asset_path = self._selected_flower_path()
        if asset_path is None:
            return
        if asset_path.suffix.casefold() in IMPORTABLE_BITMAP_SUFFIXES:
            self._draw_bitmap_flower_preview(canvas, asset_path, layout, sx, sy)
            return
        try:
            polylines = self.preview_cache.polylines(asset_path, layout)
        except (OSError, ValueError):
            return
        for polyline in polylines:
            points: list[float] = []
            for x, y in polyline:
                points.extend((sx(x), sy(y)))
            if len(points) >= 4:
                canvas.create_line(*points, fill="#555555", width=1, smooth=False, tags=("flower_art",))

    def _draw_bitmap_flower_preview(self, canvas: tk.Canvas, asset_path: Path, layout: EngravingLayout, sx, sy) -> None:
        try:
            from PIL import Image, ImageTk
        except Exception:
            return
        try:
            image = Image.open(asset_path).convert("RGBA")
        except Exception:
            return
        target_width = max(1, round(sx(layout.flower_x + layout.flower_width) - sx(layout.flower_x)))
        target_height = max(1, round(sy(layout.flower_y + layout.flower_height) - sy(layout.flower_y)))
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
        image.thumbnail((target_width, target_height), resampling)
        try:
            photo = ImageTk.PhotoImage(image, master=canvas)
        except Exception:
            return
        self.preview_text_images.append(photo)
        x = sx(layout.flower_x) + (target_width - image.width) / 2
        y = sy(layout.flower_y) + (target_height - image.height) / 2
        canvas.create_image(x, y, image=photo, anchor="nw", tags=("flower_art",))

    def _draw_visual_debug(self, canvas: tk.Canvas, layout: EngravingLayout, text_layout, sx, sy) -> None:
        asset_path = self._selected_flower_path()
        if asset_path is not None:
            try:
                boxes = flower_debug_bboxes(asset_path, layout)
            except (OSError, ValueError):
                boxes = {}
            for name, color in (("target", "#00a3ff"), ("layout", "#ff9f1c"), ("visual", "#00a878")):
                rect = boxes.get(name)
                if rect is not None:
                    self._draw_debug_rect(canvas, rect.left, rect.top, rect.right, rect.bottom, color, sx, sy)
        self._draw_debug_rect(
            canvas,
            layout.text_x,
            layout.text_y,
            layout.text_x + layout.text_width,
            layout.text_y + layout.text_height,
            "#00a3ff",
            sx,
            sy,
        )
        self._draw_debug_rect(
            canvas,
            text_layout.text_bounds.left,
            text_layout.text_bounds.top,
            text_layout.text_bounds.right,
            text_layout.text_bounds.bottom,
            "#00a878",
            sx,
            sy,
        )

    def _draw_debug_rect(self, canvas: tk.Canvas, left: float, top: float, right: float, bottom: float, color: str, sx, sy) -> None:
        canvas.create_rectangle(sx(left), sy(top), sx(right), sy(bottom), outline=color, dash=(4, 3), tags=("debug_bbox",))

    def _preview_zoom_percent_text(self) -> str:
        return f"{round(self.preview_zoom * 100)}%"

    def _preview_canvas_size_text(self, layout: EngravingLayout | None = None) -> str:
        try:
            layout = layout or layout_from_values(self.layout_vars)
            width = int(layout.canvas_width)
            height = int(layout.canvas_height)
        except Exception:
            return "画布：— px"
        if width <= 0 or height <= 0:
            return "画布：— px"
        return f"画布：{width} × {height} px"

    def _update_preview_zoom_status(self) -> None:
        var = getattr(self, "preview_zoom_status_var", None)
        if var is not None:
            var.set(self._preview_zoom_percent_text())

    def _update_preview_canvas_size_status(self, layout: EngravingLayout | None = None) -> None:
        var = getattr(self, "preview_canvas_size_var", None)
        if var is not None:
            var.set(self._preview_canvas_size_text(layout))

    def _begin_canvas_size_edit(self) -> None:
        """点击实时画板尺寸 → 原地把这行变成 [宽] × [高] px 两个输入框。
        回车/失焦提交，Esc 取消。提交即写回 layout_vars（trace 自动重绘）并存盘。"""
        if self._size_edit_frame is not None:
            return
        try:
            layout = layout_from_values(self.layout_vars)
            w0, h0 = int(layout.canvas_width), int(layout.canvas_height)
        except Exception:
            w0 = h0 = ""
        self.preview_size_label.grid_remove()
        frame = ctk.CTkFrame(self._size_status_row, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="w")
        self._size_edit_frame = frame
        font = ctk.CTkFont(size=11)
        ctk.CTkLabel(frame, text="画布：", text_color=APP_COLORS["muted"], font=font).pack(side="left")
        self._size_w_entry = ctk.CTkEntry(frame, width=52, height=22, font=font)
        self._size_w_entry.pack(side="left")
        ctk.CTkLabel(frame, text=" × ", text_color=APP_COLORS["muted"], font=font).pack(side="left")
        self._size_h_entry = ctk.CTkEntry(frame, width=52, height=22, font=font)
        self._size_h_entry.pack(side="left")
        ctk.CTkLabel(frame, text=" px", text_color=APP_COLORS["muted"], font=font).pack(side="left")
        for entry, val in ((self._size_w_entry, w0), (self._size_h_entry, h0)):
            entry.insert(0, str(val))
            entry.bind("<Return>", lambda _e: self._commit_canvas_size_edit(strict=True))
            entry.bind("<Escape>", lambda _e: self._end_canvas_size_edit())
            entry.bind("<FocusOut>", self._on_canvas_size_focus_out)
        self._size_w_entry.focus_set()

    def _on_canvas_size_focus_out(self, _event) -> None:
        # 在宽/高两框间切换 Tab/点击不算离开；焦点真正移出编辑区才按非严格提交。
        def check() -> None:
            if self._size_edit_frame is None:
                return
            if self.root.focus_get() not in (self._size_w_entry, self._size_h_entry):
                self._commit_canvas_size_edit(strict=False)
        self.root.after_idle(check)

    def _commit_canvas_size_edit(self, *, strict: bool) -> None:
        if self._size_edit_frame is None:
            return
        try:
            w = int(round(float(self._size_w_entry.get())))
            h = int(round(float(self._size_h_entry.get())))
        except ValueError:
            w = h = 0
        if w <= 0 or h <= 0:
            if strict:  # 回车显式提交才报错并留在编辑态；失焦则静默取消，不打断操作
                messagebox.showerror("画布尺寸", "宽和高必须是大于 0 的数值。")
                self._size_w_entry.focus_set()
                return
            self._end_canvas_size_edit()
            return
        self.layout_vars["canvas_width"].set(str(w))   # 触发 trace → _redraw_preview
        self.layout_vars["canvas_height"].set(str(h))
        self._update_preview_canvas_size_status()
        self._save_current_config()
        self._end_canvas_size_edit()

    def _end_canvas_size_edit(self) -> None:
        frame = self._size_edit_frame
        if frame is not None:
            self._size_edit_frame = None
            frame.destroy()
        self.preview_size_label.grid()

    def _preview_base_transform(self, layout: EngravingLayout) -> tuple[float, float, float]:
        canvas = self.preview_canvas
        if canvas is None:
            return 1.0, 0.0, 0.0
        canvas_width = max(int(canvas["width"]), canvas.winfo_width())
        canvas_height = max(int(canvas["height"]), canvas.winfo_height())
        scale = min(canvas_width / layout.canvas_width, canvas_height / layout.canvas_height)
        offset_x = (canvas_width - layout.canvas_width * scale) / 2
        offset_y = (canvas_height - layout.canvas_height * scale) / 2
        return scale, offset_x, offset_y

    def _preview_transform(self, layout: EngravingLayout) -> tuple[float, float, float]:
        """返回 Document→画板屏幕坐标变换；包含用户滚轮缩放和平移偏移。"""
        base_scale, base_offset_x, base_offset_y = self._preview_base_transform(layout)
        zoom = max(PREVIEW_ZOOM_MIN, min(PREVIEW_ZOOM_MAX, self.preview_zoom))
        return (
            base_scale * zoom,
            base_offset_x + self.preview_pan_x,
            base_offset_y + self.preview_pan_y,
        )

    def _wheel_direction(self, event) -> int:
        """Normalize wheel direction across Windows/macOS (<MouseWheel>) and Linux/X11 (Button-4/5)."""
        delta = getattr(event, "delta", 0)
        if delta:
            return 1 if delta > 0 else -1
        if getattr(event, "num", None) == 4:
            return 1
        if getattr(event, "num", None) == 5:
            return -1
        return 0

    def _on_canvas_motion(self, event) -> None:
        self.preview_pointer = (float(event.x), float(event.y))
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            layout = EngravingLayout()
        scale, offset_x, offset_y = self._preview_transform(layout)
        self._redraw_preview_rulers(layout, scale, offset_x, offset_y)

    def _on_canvas_leave(self, _event) -> None:
        self.preview_pointer = None
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            layout = EngravingLayout()
        scale, offset_x, offset_y = self._preview_transform(layout)
        self._redraw_preview_rulers(layout, scale, offset_x, offset_y)

    def _on_canvas_mousewheel(self, event) -> str:
        """以鼠标所在点为中心缩放画板；Alt/Shift+滚轮都可横向平移，模拟 PS/Figma/CAD 手感。"""
        canvas = self.preview_canvas
        if canvas is None:
            return "break"
        if self.inline_text_entry is not None:
            self._commit_inline_text_edit()
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            layout = EngravingLayout()

        direction = self._wheel_direction(event)
        if direction == 0:
            return "break"

        # 滚轮只负责缩放；平移由鼠标拖动负责，避免修饰键误判把缩放吞掉。
        old_scale, old_offset_x, old_offset_y = self._preview_transform(layout)
        if old_scale <= 0:
            return "break"

        old_zoom = self.preview_zoom
        # 线性步进：上滚 +5%、下滚 -5%，保证 100→105→110→115 这样的整齐刻度。
        new_zoom = old_zoom + direction * PREVIEW_ZOOM_STEP
        new_zoom = max(PREVIEW_ZOOM_MIN, min(PREVIEW_ZOOM_MAX, new_zoom))
        if abs(new_zoom - old_zoom) < 1e-9:
            return "break"

        mouse_x = float(event.x)
        mouse_y = float(event.y)
        doc_x = (mouse_x - old_offset_x) / old_scale
        doc_y = (mouse_y - old_offset_y) / old_scale
        base_scale, base_offset_x, base_offset_y = self._preview_base_transform(layout)
        new_scale = base_scale * new_zoom
        # 关键：让滚轮前鼠标下的 document 点，滚轮后仍在同一个屏幕坐标。
        self.preview_zoom = new_zoom
        self.preview_pan_x = mouse_x - doc_x * new_scale - base_offset_x
        self.preview_pan_y = mouse_y - doc_y * new_scale - base_offset_y
        self._update_preview_zoom_status()
        canvas.focus_set()
        self._redraw_preview()
        return "break"

    def _draw_selection_controls(self, canvas: tk.Canvas, layout: EngravingLayout, sx, sy) -> None:
        if self.inline_text_entry is not None:
            return
        layer = self.document.selected_layer()
        if layer is None:
            return
        left, top, right, bottom = layer.bounds
        self._draw_selection_box(canvas, sx(left), sy(top), sx(right), sy(bottom), layer.id)

    def _draw_selection_box(self, canvas: tk.Canvas, left: float, top: float, right: float, bottom: float, item: str) -> None:
        color = "#0d9488"
        box_tag = "selected_layer_box"
        handle_tag = "selected_layer_handle"
        canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline=color,
            dash=(5, 3),
            width=1,
            tags=("selection_box", box_tag),
        )
        handle_size = 8
        canvas.create_rectangle(
            right - handle_size,
            bottom - handle_size,
            right + handle_size,
            bottom + handle_size,
            fill=color,
            outline=color,
            tags=("selection_handle", handle_tag),
        )

    def _select_preview_item(self, item: str | None) -> None:
        if self.document.layer_by_id(item):
            self.document.selected_layer_id = item
            self.selected_preview_item = item
        else:
            self.document.selected_layer_id = None
            self.selected_preview_item = None
        self._refresh_layers_panel()
        self._redraw_preview()

    def _delete_selected_preview_item(self) -> None:
        self._delete_selected_layer()

    def _on_canvas_double_click(self, event) -> None:
        canvas = self.preview_canvas
        if canvas is None:
            return
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            layout = EngravingLayout()
        scale, offset_x, offset_y = self._preview_transform(layout)
        layer = hit_test(self.document, (event.x - offset_x) / scale, (event.y - offset_y) / scale)
        if isinstance(layer, TextLayer):
            self.document.selected_layer_id = layer.id
            self._sync_layer_properties(layer)
            self._start_inline_text_edit(layer)

    def _start_inline_text_edit(self, layer_or_event=None) -> None:
        """在画布文本框上方创建覆盖式编辑器；仅修改当前 TextLayer，不新增图层。"""
        canvas = self.preview_canvas
        if canvas is None:
            return
        layer = layer_or_event if isinstance(layer_or_event, TextLayer) else self.document.selected_layer()
        if not isinstance(layer, TextLayer):
            return
        self._destroy_inline_text_editor()
        self.document.selected_layer_id = layer.id
        self.inline_text_layer_id = layer.id
        self.inline_text_original_text = layer.text
        self.inline_text_history_pushed = False
        # 快照框几何：编辑中框随墨迹变动，Esc 取消时据此还原。
        self.inline_text_original_box = (
            layer.x, layer.y, layer.width, layer.height,
            layer.text_box_width, layer.text_box_height,
        )
        self.floating_text_editor = FloatingTextEditor(layer.id, layer.text)
        self.inline_text_is_closing = False

        editor = tk.Text(
            canvas,
            wrap="word",
            undo=False,
            bg="white",
            fg=layer.color or APP_COLORS["text"],
            insertbackground=layer.color or APP_COLORS["text"],
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
        )
        # 保留 Unicode / PUA 私用区字符：不做任何输入过滤，直接写回 TextLayer.text。
        editor.insert("1.0", layer.text)
        editor.tag_add("sel", "1.0", "end-1c")
        editor.edit_modified(False)
        editor.bind("<<Modified>>", self._on_inline_text_modified)
        editor.bind("<Return>", lambda _event: self._commit_inline_text_edit())
        editor.bind("<Control-Return>", lambda _event: self._commit_inline_text_edit())
        editor.bind("<Escape>", lambda _event: self._cancel_inline_text_edit())
        editor.bind("<FocusOut>", lambda _event: self._commit_inline_text_edit() if not self.inline_text_is_closing else "break")
        editor.bind("<Button-3>", self._show_inline_text_context_menu)
        editor.bind("<Button-2>", self._show_inline_text_context_menu)
        self.inline_text_entry = editor
        self._place_inline_text_editor()
        editor.focus_set()
        editor.mark_set("insert", "end-1c")
        editor.see("insert")

    def _on_inline_text_modified(self, event) -> str:
        editor = self.inline_text_entry
        if editor is None or self.inline_text_is_closing:
            return "break"
        try:
            if not editor.edit_modified():
                return "break"
            editor.edit_modified(False)
        except tk.TclError:
            return "break"
        layer = self.document.layer_by_id(self.inline_text_layer_id)
        if isinstance(layer, TextLayer):
            # 每次输入立即同步到当前 TextLayer；这里只重绘预览，不触发最终 PNG/SVG/DXF 导出。
            new_text = editor.get("1.0", "end-1c")
            if new_text != layer.original_text and not self.inline_text_history_pushed:
                self._push_document_history()
                self.inline_text_history_pushed = True
            if new_text != layer.original_text and layer.glyph_overrides:
                LOGGER.info("文本内容变化，清空特殊字形绑定：layer_id=%s", layer.id)
                layer.glyph_overrides.clear()
            layer.original_text = new_text
            layer.raw_text = new_text
            layer.text = new_text
            if layer.glyph_overrides:
                self._apply_text_layer_render_text(layer)
            else:
                layer.render_text = new_text
            self.layer_text_var.set(layer.original_text)
            # 固定字号，文本框随墨迹实时长大/缩小且不封顶（可越出画布安全区）；以框中心为锚重定位，
            # 编辑器随之贴合 → 内容从中心展开，大字号不再被窗口裁切。
            exceeds_safe_area = self._resize_text_box_to_font(layer, clamp_to_safe_area=False)
            self._place_inline_text_editor()
            self.status_var.set("文本框已超出画布安全区，雕刻时可能被裁切" if exceeds_safe_area else "")
            self._schedule_canvas_render()
        return "break"

    def _schedule_canvas_render(self, delay_ms: int = 25) -> None:
        """对高频文字输入做 16-33ms 级防抖，避免 Pillow 字体预览频繁渲染导致卡顿。"""
        if self.inline_text_render_after_id is not None:
            try:
                self.root.after_cancel(self.inline_text_render_after_id)
            except tk.TclError:
                pass
        self.inline_text_render_after_id = self.root.after(delay_ms, self._run_scheduled_canvas_render)

    def _run_scheduled_canvas_render(self) -> None:
        self.inline_text_render_after_id = None
        self._redraw_preview()

    def _place_inline_text_editor(self) -> None:
        """把覆盖编辑器**以文本框中心为锚**贴合到（随墨迹实时长大的）文本框上：
        窗口尺寸跟随文本框、文字水平居中 → 内容从中心向四周展开，大字号也不会被窗口裁切。"""
        canvas = self.preview_canvas
        editor = self.inline_text_entry
        layer = self.document.layer_by_id(self.inline_text_layer_id)
        if canvas is None or editor is None or not isinstance(layer, TextLayer):
            return
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            layout = EngravingLayout()
        scale, offset_x, offset_y = self._preview_transform(layout)
        left, top, right, bottom = layer.bounds
        center_x = offset_x + (left + right) / 2 * scale
        center_y = offset_y + (top + bottom) / 2 * scale
        font_px = max(8, round(layer.font_size * scale))
        # 窗口贴合实时文本框；留至少一个字高/字宽，保证空文本/小字号时光标仍可见。
        width = max(int((right - left) * scale), font_px)
        height = max(int((bottom - top) * scale), int(font_px * 1.4))
        try:
            editor.configure(font=(self._selected_preview_font_family(), font_px))
            # 文字水平居中：tk.Text 仅支持按 tag 设 justify，新输入需重新覆盖整段。
            editor.tag_configure("center_layout", justify="center")
            editor.tag_add("center_layout", "1.0", "end")
        except tk.TclError:
            pass
        if self.inline_text_window is None:
            self.inline_text_window = canvas.create_window(
                center_x,
                center_y,
                window=editor,
                anchor="center",
                width=width,
                height=height,
                tags=("inline_text_editor",),
            )
            if self.floating_text_editor is not None:
                self.floating_text_editor.window_id = self.inline_text_window
        else:
            canvas.coords(self.inline_text_window, center_x, center_y)
            canvas.itemconfigure(self.inline_text_window, width=width, height=height)
        canvas.tag_raise(self.inline_text_window)

    def _commit_inline_text_edit(self) -> str:
        editor = self.inline_text_entry
        layer = self.document.layer_by_id(self.inline_text_layer_id)
        if editor is not None and isinstance(layer, TextLayer):
            new_text = editor.get("1.0", "end-1c")
            if new_text != layer.original_text and not self.inline_text_history_pushed:
                self._push_document_history()
                self.inline_text_history_pushed = True
            if new_text != layer.original_text and layer.glyph_overrides:
                LOGGER.info("文本内容变化，清空特殊字形绑定：layer_id=%s", layer.id)
                layer.glyph_overrides.clear()
            layer.original_text = new_text
            layer.raw_text = new_text
            layer.text = new_text
            if layer.glyph_overrides:
                self._apply_text_layer_render_text(layer)
            else:
                layer.render_text = new_text
            self.layer_text_var.set(layer.original_text)
        self._destroy_inline_text_editor()
        self._refresh_layers_panel()
        self._redraw_preview()
        return "break"

    def _cancel_inline_text_edit(self) -> str:
        layer = self.document.layer_by_id(self.inline_text_layer_id)
        if isinstance(layer, TextLayer):
            layer.original_text = self.inline_text_original_text
            layer.raw_text = self.inline_text_original_text
            layer.text = self.inline_text_original_text
            if layer.glyph_overrides:
                self._apply_text_layer_render_text(layer)
            else:
                layer.render_text = self.inline_text_original_text
            self.layer_text_var.set(layer.original_text)
            # 还原编辑前的框几何（编辑中框随墨迹变动过）。
            if self.inline_text_original_box is not None:
                (layer.x, layer.y, layer.width, layer.height,
                 layer.text_box_width, layer.text_box_height) = self.inline_text_original_box
            if self.inline_text_history_pushed:
                self._pop_last_history_snapshot()
                self.inline_text_history_pushed = False
        self._destroy_inline_text_editor()
        self._refresh_layers_panel()
        self._redraw_preview()
        return "break"

    def _destroy_inline_text_editor(self) -> None:
        canvas = self.preview_canvas
        editor = self.inline_text_entry
        self.inline_text_is_closing = True
        if self.inline_text_render_after_id is not None:
            try:
                self.root.after_cancel(self.inline_text_render_after_id)
            except tk.TclError:
                pass
        self.inline_text_render_after_id = None
        self.inline_text_entry = None
        if self.inline_text_window is not None and canvas is not None:
            canvas.delete(self.inline_text_window)
        if canvas is not None:
            canvas.delete("inline_text_editor")
        if editor is not None:
            editor.destroy()
        self.inline_text_window = None
        self.inline_text_layer_id = None
        self.inline_text_original_text = ""
        self.inline_text_history_pushed = False
        self.inline_text_original_box = None
        self.floating_text_editor = None
        self.inline_text_is_closing = False

    def _on_canvas_press(self, event) -> None:
        canvas = self.preview_canvas
        if canvas is None:
            return
        if self.inline_text_entry is not None:
            # 点击画布空白/其他对象时结束内联编辑；Text 控件内部点击不会触发 Canvas 事件。
            self._commit_inline_text_edit()
            return
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            layout = EngravingLayout()
        scale, offset_x, offset_y = self._preview_transform(layout)
        doc_x = (event.x - offset_x) / scale
        doc_y = (event.y - offset_y) / scale
        layer = self.document.selected_layer()
        tags = set(canvas.gettags(canvas.find_closest(event.x, event.y)[0])) if canvas.find_closest(event.x, event.y) else set()
        if layer is not None and "selected_layer_handle" in tags and not layer.locked:
            self._drag_target = layer.id
            self._drag_mode = "resize"
        else:
            layer = hit_test(self.document, doc_x, doc_y)
            if layer is None:
                # 空白处按下：左键拖动平移视图，不选中也不移动任何图层。
                self._drag_target = None
                self._drag_mode = "pan"
                self._set_preview_cursor("fleur")
            else:
                self._drag_target = layer.id if not layer.locked else None
                self._drag_mode = "move"
        self._drag_history_pushed = False
        self.document.selected_layer_id = layer.id if layer else None
        self.selected_preview_item = self.document.selected_layer_id
        self._drag_start = (event.x, event.y)
        canvas.focus_set()
        self._refresh_layers_panel()
        self._redraw_preview()

    def _set_preview_cursor(self, cursor: str) -> None:
        canvas = self.preview_canvas
        if canvas is None:
            return
        try:
            canvas.configure(cursor=cursor)
        except tk.TclError:
            pass

    def _pan_preview_by(self, dx: float, dy: float) -> None:
        """Move only the viewport in screen pixels; document/export coordinates stay unchanged."""
        self.preview_pan_x += dx
        self.preview_pan_y += dy

    def _on_canvas_drag(self, event) -> None:
        if self._drag_start is None:
            return
        screen_dx = event.x - self._drag_start[0]
        screen_dy = event.y - self._drag_start[1]
        self._drag_start = (event.x, event.y)
        if self._drag_mode == "pan":
            self._pan_preview_by(screen_dx, screen_dy)
            self._redraw_preview()
            return
        if self._drag_target is None:
            return
        layer = self.document.layer_by_id(self._drag_target)
        if layer is None or layer.locked:
            return
        if not self._drag_history_pushed:
            self._push_document_history()
            self._drag_history_pushed = True
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            return
        scale, _offset_x, _offset_y = self._preview_transform(layout)
        dx = screen_dx / scale
        dy = screen_dy / scale
        if self._drag_mode == "resize":
            if isinstance(layer, AnchoredHeartLayer):
                # 锚定爱心几何每帧被 resolve 覆盖：把缩放手柄拖动折成 size_mm（大小），才会“记住”。
                px_per_mm = self._heart_px_per_mm(layout)
                if px_per_mm:
                    layer.size_mm = max(0.5, (layer.height + dy) / px_per_mm)
            elif isinstance(layer, TextLayer):
                CanvasTextItem(layer).resize_by(dx, dy)
            else:
                layer.width = max(20, layer.width + dx)
                layer.height = max(20, layer.height + dy)
        else:
            if isinstance(layer, AnchoredHeartLayer):
                # 锚定爱心 x/y 每帧被 resolve 覆盖：把拖动位移折成相对文字的 mm 偏移
                # （gap_mm 左右、offset_y_mm 上下），既能自由拖动、又保持锚定跟随文字。
                px_per_mm = self._heart_px_per_mm(layout)
                anchor = self.document.layer_by_id(layer.anchor_layer_id)
                anchor_sx = float(getattr(anchor, "scale_x", 1.0) or 1.0) if anchor is not None else 1.0
                anchor_sy = float(getattr(anchor, "scale_y", 1.0) or 1.0) if anchor is not None else 1.0
                if px_per_mm:
                    layer.gap_mm = self._effective_gap_mm(layer, px_per_mm) + (dx / anchor_sx) / px_per_mm
                    layer.offset_y_mm = float(layer.offset_y_mm or 0.0) + (dy / anchor_sy) / px_per_mm
            elif isinstance(layer, TextLayer):
                CanvasTextItem(layer).move_by(dx, dy)
            else:
                layer.x = max(0, layer.x + dx)
                layer.y = max(0, layer.y + dy)
        self._redraw_preview()

    def _on_canvas_release(self, _event) -> None:
        self._drag_target = None
        self._drag_start = None
        self._drag_history_pushed = False
        if self._drag_mode == "pan":
            self._set_preview_cursor("")
        self._drag_mode = "move"


def _preview_text_ink_image(text: str, font_size: int, font_path: Path | None):
    """返回裁剪到真实黑色墨迹的 RGBA 图片及其相对文字 origin 的偏移，供 Tk 预览精准贴合方框。"""
    if not text:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    try:
        font = ImageFont.truetype(str(font_path), font_size) if font_path is not None else ImageFont.load_default(size=font_size)
    except Exception:
        try:
            font = ImageFont.load_default(size=font_size)
        except TypeError:
            font = ImageFont.load_default()
    bbox = measure_text_ink_bbox(text, font_size, font_path)
    if bbox.width <= 0 or bbox.height <= 0:
        return None
    width = max(1, int(bbox.width) + 1)
    height = max(1, int(bbox.height) + 1)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.text((-bbox.left, -bbox.top), text, font=font, fill="#111111")
    alpha_bbox = image.getbbox()
    if alpha_bbox is None:
        return None
    cropped = image.crop(alpha_bbox)
    return cropped, bbox.left + alpha_bbox[0], bbox.top + alpha_bbox[1]


def _preview_text_fill_image(text: str, font_size: int, font_path: Path | None, target_width: int, target_height: int):
    """把裁剪后的真实墨迹图非等比拉伸到目标方框尺寸，确保预览墨迹四边贴合方框。"""
    image_and_offset = _preview_text_ink_image(text, font_size, font_path)
    if image_and_offset is None:
        return None
    image, _offset_left, _offset_top = image_and_offset
    target_size = (max(1, int(target_width)), max(1, int(target_height)))
    if image.size == target_size:
        return image
    try:
        from PIL import Image

        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
    except Exception:
        resampling = 1
    return image.resize(target_size, resampling)


def _reexec_with_complete_env() -> None:
    """DXF 导出(ezdxf→numpy)和物理尺寸读取(pydantic)需要完整依赖。若当前解释器装不全
    (常见是缺 numpy/pydantic 的 MSYS .venv),自动用项目内 .venv-win 重新启动应用,
    免得用户每次手动切解释器、也避免 DXF 一直报"需要 ezdxf"。"""
    if os.environ.get("FLOWER_PY_REEXEC") or getattr(sys, "frozen", False):
        return
    try:
        import numpy  # noqa: F401  ezdxf 依赖;缺它代表当前解释器不完整
        import customtkinter  # noqa: F401  UI 必需;引导解释器缺它也要切到 .venv-win
        return
    except ImportError:
        pass
    candidate = Path(__file__).resolve().parent / ".venv-win" / "Scripts" / "python.exe"
    if not candidate.is_file():
        LOGGER.warning("当前 Python 缺 numpy 且未找到 .venv-win;DXF 导出会失败,请用完整环境启动")
        return
    LOGGER.info("当前 Python 依赖不全,改用 %s 重新启动应用", candidate)
    env = dict(os.environ, FLOWER_PY_REEXEC="1")
    result = subprocess.run([str(candidate), *sys.argv], env=env)
    sys.exit(result.returncode)


def main() -> None:
    _reexec_with_complete_env()
    # ctk.CTk = CustomTkinter 托管窗口（深色标题栏，Ezcad 同款）；ctk 缺失时回退 tk.Tk。
    root = ctk.CTk() if ctk is not None else tk.Tk()
    BirthFlowerApp(root)
    root.mainloop()


def _ttf_family_name(font_path: Path) -> str:
    """读取 TTF family 名；失败时返回空字符串并让 Tk 使用回退字体。"""
    try:
        data = font_path.read_bytes()
        table_count = struct.unpack(">H", data[4:6])[0]
    except (OSError, struct.error):
        return ""

    tables: dict[str, tuple[int, int]] = {}
    offset = 12
    for _ in range(table_count):
        try:
            tag, _checksum, table_offset, length = struct.unpack(">4sIII", data[offset : offset + 16])
        except struct.error:
            return ""
        tables[tag.decode("latin1")] = (table_offset, length)
        offset += 16

    name_table = tables.get("name")
    if name_table is None:
        return ""
    table_offset, _length = name_table
    try:
        _format, record_count, string_offset = struct.unpack(">HHH", data[table_offset : table_offset + 6])
    except struct.error:
        return ""

    names_by_priority: dict[int, str] = {}
    for index in range(record_count):
        record_start = table_offset + 6 + index * 12
        try:
            platform_id, _encoding_id, _language_id, name_id, length, name_offset = struct.unpack(
                ">HHHHHH", data[record_start : record_start + 12]
            )
        except struct.error:
            continue
        if name_id not in (16, 1):
            continue
        raw = data[table_offset + string_offset + name_offset : table_offset + string_offset + name_offset + length]
        encoding = "utf-16-be" if platform_id in (0, 3) else "latin1"
        try:
            decoded = raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
        if decoded:
            names_by_priority.setdefault(name_id, decoded)
    return names_by_priority.get(16) or names_by_priority.get(1) or ""
