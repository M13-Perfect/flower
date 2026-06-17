from __future__ import annotations
import ctypes
import dataclasses
import logging
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import customtkinter as ctk
except ImportError:  # 引导解释器（如 MSYS .venv）可能没装 ctk；容忍导入，交给 _reexec 切到 .venv-win
    ctk = None  # type: ignore[assignment]
from typing import TypeVar

from asset_resolver import find_flower_asset, scan_flower_assets, scan_font_assets
from canvas_text_item import CanvasTextItem, FloatingTextEditor
from config_store import (
    AIProfile,
    AppConfig,
    ProductConfig,
    active_ai_profile,
    active_product,
    load_config,
    normalize_output_path,
    save_config,
    unique_product_id,
    with_added_product,
    with_product_library_dirs,
    with_product_prompts,
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
    normalize_codepoint,
    rebuild_render_text,
    recommended_glyph_variants,
    remove_glyph_override,
    resolve_glyph,
)
from models import AIParseConfig, BirthFlowerDesign, Document, EngravingLayout, FlowerAsset, FontAsset, ImageLayer, TextLayer, ParseResult, add_image_layer, add_text_layer, delete_layer, hit_test, move_layer
from order_importer import load_order_remark_from_file
from parse_pipeline import parse_order_remark_auto
from order_catalog import LibraryBundle
from production import ProductionParams, resolve_chain
from gpt_parser import DEFAULT_DEEPSEEK_BASE_URL, DEFAULT_DEEPSEEK_MODEL, DEFAULT_MODEL, parse_order_remark_with_gpt
from renderer import DEBUG_VISUAL_BBOX, PreviewCache, flower_debug_bboxes, render_document_png, render_dxf, render_png, render_svg
from desktop_export import render_document_dxf, render_document_vector_svg
from text_layout import measure_text_ink_bbox, layout_personalization_text


DEFAULT_FLOWER_DIR = Path("BirthMonth flowers")
DEFAULT_FONT_SOURCE = Path("Birthmonth_font.ttf")
IMPORTABLE_FONT_SUFFIXES = {".ttf", ".otf"}
IMPORTABLE_VECTOR_SUFFIXES = {".svg"}
IMPORTABLE_BITMAP_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
IMPORTABLE_ASSET_SUFFIXES = IMPORTABLE_VECTOR_SUFFIXES | IMPORTABLE_BITMAP_SUFFIXES
SINGLE_REMARK_SUFFIXES = {".txt", ".json", ".csv"}
PREVIEW_ZOOM_MIN = 0.2
PREVIEW_ZOOM_MAX = 8.0
PREVIEW_ZOOM_STEP = 1.25
PREVIEW_WHEEL_PAN_STEP = 60
# 三态大小写切换:点击循环 默认→大写→小写;影响"识别内容"的输出大小写。
TEXT_CASE_ORDER = ("default", "upper", "lower")
TEXT_CASE_LABELS = {"default": "默认", "upper": "大写", "lower": "小写"}
SERVICES_API_DIR = Path(__file__).resolve().parent / "services" / "api"
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
# 引导解释器没装 ctk（ctk=None）时跳过；_reexec 会切到装了 ctk 的 .venv-win 再真正建 UI。
if ctk is not None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

# 产品切换列（方案2）收起/展开两种宽度（像素）。
PRODUCT_RAIL_COLLAPSED_WIDTH = 48
PRODUCT_RAIL_EXPANDED_WIDTH = 168
# 主窗口最小尺寸；产品列外推时用常量而非 root.minsize() 读回（ctk.CTk 的无参 minsize 会抛 TypeError）。
MIN_WINDOW_WIDTH = 760
MIN_WINDOW_HEIGHT = 560

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


class CtkMenu:
    """自绘深色下拉菜单：overrideredirect Toplevel + CTk 行，替代原生 tk.Menu 的系统白边弹窗。

    items：list[dict]，每项 {"label","command","enabled"=True} 或 {"type":"separator"}。
    关闭时机：选中一项 / 失焦(FocusOut) / Esc。
    """

    def __init__(self, master: tk.Misc):
        self._master = master
        self._win: tk.Toplevel | None = None

    def popup(self, x: int, y: int, items: list[dict]) -> None:
        win = tk.Toplevel(self._master)
        win.overrideredirect(True)  # 去系统边框 → 没有白边
        win.attributes("-topmost", True)
        # 圆角 CTkFrame 的四角缺口会露出 Toplevel 默认浅底（白角）→ 把底色也设成深色面板。
        win.configure(bg=APP_COLORS["panel"])
        outer = ctk.CTkFrame(
            win,
            corner_radius=8,
            fg_color=APP_COLORS["panel"],
            border_width=1,
            border_color=APP_COLORS["border"],
        )
        outer.pack(fill="both", expand=True)
        for item in items:
            if item.get("type") == "separator":
                ctk.CTkFrame(outer, height=1, fg_color=APP_COLORS["border"]).pack(fill="x", padx=10, pady=4)
                continue
            enabled = item.get("enabled", True)
            ctk.CTkButton(
                outer,
                text=item["label"],
                anchor="w",
                height=30,
                corner_radius=6,
                fg_color="transparent",
                hover_color=APP_COLORS["accent_soft"],
                text_color=APP_COLORS["text"] if enabled else APP_COLORS["muted"],
                state="normal" if enabled else "disabled",
                command=(lambda c=item.get("command"): self._run(c)),
            ).pack(fill="x", padx=4, pady=1)
        win.update_idletasks()
        win.geometry(f"+{int(x)}+{int(y)}")
        win.bind("<Escape>", lambda _e: self.close())

        def arm() -> None:
            # 先抢焦点再绑 FocusOut，避免开窗瞬间的假失焦把自己关掉。
            if self._win is None:
                return
            self._win.focus_force()
            self._win.bind("<FocusOut>", lambda _e: self.close())

        win.after(10, arm)
        self._win = win

    def _run(self, command) -> None:
        self.close()
        if command is not None:
            command()

    def close(self) -> None:
        if self._win is not None:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
            self._win = None


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
    month: str,
    font: str,
    flower: str,
    flower_asset_path: str | Path | None = None,
    font_path: str | Path | None = None,
    personalization_type: str = "unknown",
) -> ParseResult:
    clean_text = text.strip()
    parse_warnings: list[str] = []
    asset_warnings: list[str] = []

    month_number = _readiness_int(month)
    font_number = _readiness_int(font)
    flower_number = _readiness_int(flower)
    if not clean_text:
        parse_warnings.append("Missing personalization")
    if month_number is None or not 1 <= month_number <= 12:
        parse_warnings.append("Invalid birth month")
        month_number = None
    if font_number is None or font_number < 1:
        parse_warnings.append("Invalid font design")
        font_number = None
    if flower_number is None or flower_number < 1:
        parse_warnings.append("Invalid flower choice")
        flower_number = None

    selected_flower_asset = _existing_asset_path(flower_asset_path)
    selected_font_asset = _existing_asset_path(font_path)
    if month_number is not None and flower_number is not None and selected_flower_asset is None:
        asset_warnings.append("Missing flower asset")
    if font_number is not None and selected_font_asset is None:
        asset_warnings.append("Missing font asset")

    parse_confidence = _manual_parse_confidence(clean_text, month_number, font_number, flower_number, parse_warnings)
    asset_confidence = _manual_asset_confidence(selected_flower_asset, selected_font_asset, asset_warnings)
    return ParseResult(
        text=clean_text,
        month=month_number,
        font=font_number,
        flower=flower_number,
        warnings=[*parse_warnings, *asset_warnings],
        confidence=parse_confidence,
        birth_month=str(month_number) if month_number is not None else None,
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
    month: int | None,
    font: int | None,
    flower: int | None,
    warnings: list[str],
) -> float:
    score = 1.0
    if month is None or flower is None:
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
    suffix = "含字形" if asset.has_ending_glyphs else "普通"
    return f"{design} - {asset.name} - {asset.path.name} - {size_text} - {suffix}"


def output_path_for_format(base_path: Path | str, output_format: str) -> Path:
    clean_format = output_format.strip().casefold()
    if clean_format not in {"png", "svg", "dxf"}:
        raise ValueError(f"不支持的输出格式：{output_format}")
    return Path(base_path).with_suffix(f".{clean_format}")


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
        self.field_results: dict[str, str] = {"field1": "Ammy", "field2": "1月", "field3": "Font5"}
        self.field_defs: list[dict] = [
            {"key": "field1", "name": "Info1", "type": "文本",
             "instruction": "顾客需要定制的文本内容，不超过20个字符，如果超过20个字符，输出error"},
            {"key": "field2", "name": "Info2", "type": "素材",
             "instruction": "顾客生日的月份，只可以是1~12月中的某一个，请严格按照1月，2月，3月这样的表达方式给我"},
            {"key": "field3", "name": "Info3", "type": "字体",
             "instruction": "顾客想要的字体编号，请严格按照 font1；font2，font3这样的格式给我"},
        ]
        for _f in self.field_defs:
            self._ensure_field_vars(_f)
        self.field_seq = len(self.field_defs)  # 下一个字段编号自增基准
        self.fields_body = None  # 合并后的「字段」卡 body（一字段一卡）
        self.filename_template_var = tk.StringVar(value="")
        self.background_prompt_text = None
        self.generated_prompt_text = None
        self.config_locked_var = tk.BooleanVar(value=False)
        self.lock_button = None
        # 配置锁：受锁控件登记表（订单备注框/导入解析清空/锁按钮本身不入列表）。
        self._locked_widgets: list = []
        # 图层卡：真实动态行容器（单行紧凑：拖柄 + 状态 + 库/素材或字体下拉）。
        self.layers_rows_box = None
        self._layer_rows: dict[str, dict] = {}        # layer_id → 该行控件引用（增量复用，避免反复销毁 CTkOptionMenu）
        self._layers_empty_hint = None                # 无图层时的占位提示
        self._layer_row_widgets: list = []            # (row_card, layer_id)，拖动落点命中用
        self._drag_layer_id: str | None = None        # 当前拖动中的图层 id
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
        default_layout = self.config.layout_defaults
        # 多图层文档是画布的真实数据源；旧版字段继续保留，保证订单解析和月份/字体选择兼容。
        self.document = Document(default_layout.canvas_width, default_layout.canvas_height)
        self.history_manager = None  # 预留 Ctrl+Z/Ctrl+Y 历史管理入口。
        self.layers_listbox: tk.Listbox | None = None
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
        self.remark_text: tk.Text | None = None
        self.confirm_button: ttk.Button | None = None
        self.inline_text_entry: tk.Text | None = None
        self.inline_text_window: int | None = None
        self.inline_text_layer_id: str | None = None
        self.inline_text_original_text: str = ""
        self.inline_text_render_after_id: str | None = None
        self.inline_text_is_closing = False
        self.floating_text_editor: FloatingTextEditor | None = None
        self.section_frames: dict[str, tk.Widget] = {}
        self._drag_target: str | None = None
        self._drag_start: tuple[int, int] | None = None
        self._drag_mode: str = "move"
        self.selected_preview_item: str | None = None
        # 画板视图状态：默认等比适配；滚轮缩放时只改变视图，不改 Document/export 坐标。
        self.preview_zoom = 1.0
        self.preview_pan_x = 0.0
        self.preview_pan_y = 0.0
        self.preview_zoom_status_var = tk.StringVar(value=self._preview_zoom_percent_text())
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

    def _build_menu(self) -> None:
        # 菜单数据驱动，弹窗用自绘 CtkMenu（深色圆角、无系统白边）；不再用原生 tk.Menu / 菜单栏。
        # 原「导入」子菜单拍平为顶层两项（CtkMenu 不做嵌套子菜单），用分隔线保留分组。
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
        self.root.bind("<Control-z>", lambda _event: self.status_var.set("撤销历史已预留，后续版本启用"))
        self.root.bind("<Control-y>", lambda _event: self.status_var.set("重做历史已预留，后续版本启用"))

    def _build_menubar(self, parent) -> ctk.CTkFrame:
        """顶部深色菜单条：每个按钮弹出自绘 CtkMenu（深色圆角，无系统白边）。"""
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
        return bar

    def _open_dropdown(self, button: tk.Widget, items: list[dict]) -> None:
        x = button.winfo_rootx()
        y = button.winfo_rooty() + button.winfo_height() + 2
        CtkMenu(self.root).popup(x, y, items)

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
        style.configure("TNotebook", background=panel, bordercolor=border)
        style.configure("TNotebook.Tab", background=field, foreground=text, padding=(10, 4))
        style.map("TNotebook.Tab", background=[("selected", panel)], foreground=[("selected", text)])

        # ttk Combobox 下拉列表用经典 Listbox，需经 option database 刷深色。
        self.root.option_add("*TCombobox*Listbox.background", field)
        self.root.option_add("*TCombobox*Listbox.foreground", text)
        self.root.option_add("*TCombobox*Listbox.selectBackground", accent)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    def _ctk_card(self, parent, title: str, *, locked: bool = False) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
        """深色圆角卡片 + 顶部标题；返回 (card, body)，内容 grid 进 body（替代 ttk.LabelFrame）。

        locked=True 时标题前加 🔒 标，表示该卡属配置锁定区（控件随锁开合 disable）。
        """
        card = ctk.CTkFrame(
            parent,
            corner_radius=10,
            fg_color=APP_COLORS["panel"],
            border_width=1,
            border_color=APP_COLORS["border"],
        )
        ctk.CTkLabel(
            card, text=(f"🔒 {title}" if locked else title), anchor="w",
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

    # ===== 配置锁：登记/清理受锁控件 =====
    def _register_lock(self, widget):
        """登记一个受配置锁控制的控件，按当前锁态应用一次 state；返回 widget 便于链式 .grid()。"""
        self._locked_widgets.append(widget)
        if self.config_locked_var.get():
            try:
                widget.configure(state="disabled")
            except Exception:
                pass
        return widget

    def _prune_locked(self) -> None:
        """剔除已销毁的受锁控件引用（字段/图层卡重渲染时旧控件会被 destroy）。"""
        alive = []
        for widget in self._locked_widgets:
            try:
                if int(widget.winfo_exists()):
                    alive.append(widget)
            except Exception:
                pass
        self._locked_widgets = alive

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

        # 产品切换列：作为最左新增一列，原 body（预览 + 功能区）两栏布局保持不变。
        self.product_rail = ctk.CTkFrame(
            frame, width=PRODUCT_RAIL_COLLAPSED_WIDTH, corner_radius=0, fg_color=APP_COLORS["panel"]
        )
        self.product_rail.pack(side="left", fill="y", padx=(0, 8))
        self.product_rail.pack_propagate(False)
        self._render_product_rail()

        body = ttk.Frame(frame, style="App.TFrame")
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1, minsize=360)
        body.columnconfigure(1, weight=0, minsize=300)
        body.rowconfigure(0, weight=1)

        preview_panel = self._build_preview_panel(body)
        function_panel, order_panel, production_panel = self._build_function_panel(body)

        preview_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        function_panel.grid(row=0, column=1, sticky="nsew")

        self.section_frames = {
            "order_panel": order_panel,
            "preview_panel": preview_panel,
            "function_panel": function_panel,
            "production_panel": production_panel,
            "product_rail": self.product_rail,
        }
        self._set_warnings(["等待解析；识别结果不会自动生成最终文件。"])
        # ctk.CTk 根窗自带深色标题栏；仅当回退到 tk.Tk（测试/缺 ctk）时用 DWM 兜底。
        if ctk is None or not isinstance(self.root, ctk.CTk):
            _enable_dark_titlebar(self.root)

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
        if collapsed:
            # 收起时只显示首字，用悬浮提示补全产品名。
            _attach_tooltip(button, str(item["name"]))

    def _toggle_product_rail(self) -> None:
        """收/展产品列；窗口宽度同步增减，让列「往外推出」而非「往内挤占画板」。"""
        delta = PRODUCT_RAIL_EXPANDED_WIDTH - PRODUCT_RAIL_COLLAPSED_WIDTH
        expanding = self.products_collapsed  # 当前收起 → 即将展开
        self.products_collapsed = not self.products_collapsed
        self.config = dataclasses.replace(
            self.config, products_panel_collapsed=self.products_collapsed
        )
        save_config(self.config)
        self._render_product_rail()
        # 窗口整体加宽/收窄 delta，使画板与功能区宽度保持不变（产品列向外扩，不吃画板）。
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        new_width = width + delta if expanding else max(MIN_WINDOW_WIDTH, width - delta)
        self.root.geometry(f"{new_width}x{height}")

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
        self._load_prompts_into_widgets()  # 载入新产品的提示词
        self._render_product_rail()
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
        button_row.grid(row=4, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self._btn(button_row, "取消", window.destroy).grid(row=0, column=0, padx=(0, 8))
        self._btn(
            button_row,
            "创建",
            lambda: self._create_product_from_dialog(
                window, name_var, id_var, image_dir_var, font_dir_var
            ),
            primary=True,
        ).grid(row=0, column=1)

    def _choose_dir_into(self, var: tk.StringVar) -> None:
        path = filedialog.askdirectory()
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
            defaults=self.config.layout_defaults,
        )
        # 先追加（不激活）再走切换逻辑，复用切换里的重扫/重绘/持久化。
        self.config = with_added_product(self.config, product, activate=False)
        save_config(self.config)
        window.destroy()
        self._switch_product(product_id)

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

        # 最终布局：订单信息 → 背景提示词 → 字段 → 图层 → 库 → 生成提示词 → 输出设置(含「生成」)。
        # 「输出设置」置于功能区最底部：底栏已删，主操作「生成」落在此卡。
        # 旧的「图层」listbox 面板(_build_layers_panel)暂不装配；其刷新方法已自带 None 守卫退化为 no-op。
        order_panel = self._build_order_panel(panel)
        production_panel = self._build_production_panel(panel)  # 「图层」卡，真实动态行 + 保留隐藏全局选择器联动
        cards = [
            order_panel,
            self._build_background_prompt_panel(panel),
            self._build_fields_panel(panel),
            production_panel,
            self._build_library_panel(panel),
            self._build_generate_prompt_panel(panel),
            self._build_output_settings_panel(panel),
        ]
        for row, card in enumerate(cards):
            card.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        return panel, order_panel, production_panel


    def _build_layers_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        """右下角图层面板：负责选择、显隐、锁定、删除和调整层级。"""
        panel, body = self._ctk_card(parent, "图层")
        self.layers_listbox = tk.Listbox(
            body,
            height=7,
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
        self.layers_listbox.grid(row=0, column=0, columnspan=5, sticky="ew")
        self.layers_listbox.bind("<<ListboxSelect>>", self._on_layer_list_select)
        self.layers_listbox.bind("<Double-Button-1>", self._on_layer_list_double_click)
        self.layers_listbox.bind("<Button-3>", self._show_layer_context_menu)
        self.layers_listbox.bind("<Button-2>", self._show_layer_context_menu)
        self._btn(body, "显/隐", self._toggle_selected_layer_visible).grid(row=1, column=0, sticky="ew", pady=3, padx=2)
        self._btn(body, "锁/解", self._toggle_selected_layer_locked).grid(row=1, column=1, sticky="ew", pady=3, padx=2)
        self._btn(body, "删除", self._delete_selected_layer).grid(row=1, column=2, sticky="ew", pady=3, padx=2)
        self._btn(body, "上移", lambda: self._move_selected_layer("up")).grid(row=2, column=0, sticky="ew", pady=3, padx=2)
        self._btn(body, "下移", lambda: self._move_selected_layer("down")).grid(row=2, column=1, sticky="ew", pady=3, padx=2)
        self._btn(body, "置顶", lambda: self._move_selected_layer("top")).grid(row=2, column=2, sticky="ew", pady=3, padx=2)
        self._btn(body, "置底", lambda: self._move_selected_layer("bottom")).grid(row=2, column=3, sticky="ew", pady=3, padx=2)
        ctk.CTkLabel(
            body, textvariable=self.layer_detail_var, text_color=APP_COLORS["muted"],
            wraplength=240, anchor="w", justify="left",
        ).grid(row=3, column=0, columnspan=5, sticky="ew", pady=(4, 0))
        ctk.CTkLabel(body, text="文本", anchor="w").grid(row=4, column=0, sticky="w", pady=(6, 2))
        ctk.CTkEntry(body, textvariable=self.layer_text_var).grid(row=4, column=1, columnspan=4, sticky="ew", pady=(6, 2))
        ctk.CTkLabel(body, text="字号", anchor="w").grid(row=5, column=0, sticky="w", pady=2)
        ctk.CTkEntry(body, textvariable=self.layer_font_size_var, width=70).grid(row=5, column=1, sticky="ew", pady=2)
        ctk.CTkLabel(body, text="颜色", anchor="w").grid(row=5, column=2, sticky="w", pady=2)
        ctk.CTkEntry(body, textvariable=self.layer_color_var, width=90).grid(row=5, column=3, sticky="ew", pady=2)
        self._btn(body, "应用文本属性", self._apply_text_layer_properties).grid(row=5, column=4, sticky="ew", pady=2, padx=2)
        # 增量4：图层级生产参数（几何）——任意图层可编辑位置/尺寸，应用写回 layer.production 并落到画布几何。
        ctk.CTkLabel(body, text="位置X", anchor="w").grid(row=6, column=0, sticky="w", pady=2)
        ctk.CTkEntry(body, textvariable=self.layer_x_var, width=70).grid(row=6, column=1, sticky="ew", pady=2)
        ctk.CTkLabel(body, text="Y", anchor="w").grid(row=6, column=2, sticky="w", pady=2)
        ctk.CTkEntry(body, textvariable=self.layer_y_var, width=70).grid(row=6, column=3, sticky="ew", pady=2)
        ctk.CTkLabel(body, text="宽", anchor="w").grid(row=7, column=0, sticky="w", pady=2)
        ctk.CTkEntry(body, textvariable=self.layer_w_var, width=70).grid(row=7, column=1, sticky="ew", pady=2)
        ctk.CTkLabel(body, text="高", anchor="w").grid(row=7, column=2, sticky="w", pady=2)
        ctk.CTkEntry(body, textvariable=self.layer_h_var, width=70).grid(row=7, column=3, sticky="ew", pady=2)
        self._btn(body, "应用生产参数", self._apply_layer_production).grid(row=7, column=4, sticky="ew", pady=2, padx=2)
        # 字体样式（per-layer override，文本图层有效）：由上方「应用文本属性」一并写回选中图层。
        ctk.CTkCheckBox(body, text="加粗", variable=self.layer_bold_var, width=60).grid(
            row=8, column=0, sticky="w", pady=2
        )
        ctk.CTkCheckBox(body, text="下划线", variable=self.layer_underline_var, width=72).grid(
            row=8, column=1, sticky="w", pady=2
        )
        ctk.CTkLabel(body, text="字间距", anchor="w").grid(row=8, column=2, sticky="w", pady=2)
        ctk.CTkEntry(body, textvariable=self.layer_letter_spacing_var, width=70).grid(
            row=8, column=3, sticky="ew", pady=2
        )
        return panel

    def _build_order_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        panel, body = self._ctk_card(parent, "订单信息")
        body.columnconfigure(0, weight=1)

        header = ctk.CTkFrame(body, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="订单信息", anchor="w").grid(row=0, column=0, sticky="w")
        # 锁按钮：只用一把锁图标，无文字、不占长度。P1 仅视觉开合，密码校验/控件禁用在 P4。
        self.lock_button = self._btn(header, "🔓", self._toggle_config_lock, width=30)
        self.lock_button.grid(row=0, column=1, sticky="e")

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
        ctk.CTkLabel(
            body, text="下方配置可加密码锁：管理员配置 / 操作员只填订单文本", anchor="w",
            text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11),
            wraplength=270, justify="left",
        ).grid(row=3, column=0, sticky="w", pady=(8, 0))
        return panel

    def _build_preview_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        panel, body = self._ctk_card(parent, "实时画板")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        status_row = ctk.CTkFrame(body, fg_color="transparent")
        status_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        status_row.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            status_row,
            textvariable=self.preview_zoom_status_var,
            anchor="e",
            text_color=APP_COLORS["muted"],
            font=ctk.CTkFont(size=11),
        ).grid(row=0, column=0, sticky="e")

        # 画板保持白底：代表浅色木料，雕刻预览是深灰折线 + 黑墨字，翻黑会看不见。
        self.preview_canvas = tk.Canvas(
            body,
            width=720,
            height=532,
            bg="white",
            highlightthickness=1,
            highlightbackground=APP_COLORS["border"],
        )
        self.preview_canvas.grid(row=1, column=0, sticky="nsew")
        self.preview_canvas.bind("<Button-1>", self._on_canvas_press)
        self.preview_canvas.bind("<Double-Button-1>", self._on_canvas_double_click)
        self.preview_canvas.bind("<Button-3>", self._show_canvas_context_menu)
        self.preview_canvas.bind("<Button-2>", self._on_canvas_pan_press)
        self.preview_canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.preview_canvas.bind("<B2-Motion>", self._on_canvas_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.preview_canvas.bind("<ButtonRelease-2>", self._on_canvas_release)
        self.preview_canvas.bind("<Configure>", lambda _event: self._redraw_preview())
        self.preview_canvas.bind("<MouseWheel>", self._on_canvas_mousewheel)
        self.preview_canvas.bind("<Button-4>", self._on_canvas_mousewheel)
        self.preview_canvas.bind("<Button-5>", self._on_canvas_mousewheel)
        self.preview_canvas.bind("<Delete>", lambda _event: self._delete_selected_layer())
        self.preview_canvas.bind("<BackSpace>", lambda _event: self._delete_selected_layer())
        return panel

    def _build_production_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        panel, body = self._ctk_card(parent, "图层", locked=True)
        body.columnconfigure(0, weight=1)

        header = ctk.CTkFrame(body, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text=f"画布尺寸 {self.layout_vars['canvas_width'].get()} × {self.layout_vars['canvas_height'].get()}",
            anchor="w", text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header, text="拖柄调序 · 右键/⋮ 设属性", anchor="e",
            text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=10),
        ).grid(row=0, column=1, sticky="e")

        # 每个图层一行：内容字段 + 来源库 + 具体素材/字体（文字另含字号）聚合在行内；
        # 位置/尺寸/对齐/显隐/删除走右键。真实动态行由 _render_layers() 按 document.layers 渲染。
        self.layers_rows_box = ctk.CTkFrame(body, fg_color="transparent")
        self.layers_rows_box.grid(row=1, column=0, sticky="ew")
        self.layers_rows_box.columnconfigure(0, weight=1)
        self._render_layers()

        action_row = ctk.CTkFrame(body, fg_color="transparent")
        action_row.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        action_row.columnconfigure(0, weight=1)
        self._register_lock(
            self._btn(action_row, "+ 文字图层", self._add_text_layer_from_fields, primary=True)
        ).grid(row=0, column=1, padx=(0, 6))
        self._register_lock(
            self._btn(action_row, "+ 图片图层", self._add_selected_flower_to_canvas)
        ).grid(row=0, column=2)

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
        return ctk.CTkLabel(
            parent, text=text, fg_color=APP_COLORS["accent_soft"], text_color="#7fa8ff",
            corner_radius=6, width=52, font=ctk.CTkFont(size=11),
        )

    def _build_fields_panel(self, parent) -> ctk.CTkFrame:
        """合并后的「字段」卡：一字段一张子卡（结果 + 类型 + 提取规则）。属配置锁定区。"""
        panel, body = self._ctk_card(parent, "字段", locked=True)
        self.fields_body = body
        self._render_fields()
        return panel

    def _render_fields(self) -> None:
        body = self.fields_body
        if body is None:
            return
        for child in body.winfo_children():
            child.destroy()
        self._prune_locked()
        body.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            body, text="每个字段 = 一条提取规则 + 一个结果（结果为占位，P3 接 GPT 真填）", anchor="w",
            text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11), wraplength=270, justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
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
            top.columnconfigure(2, weight=1)
            self._field_chip(top, field["name_var"].get()).grid(row=0, column=0, padx=(0, 6))
            self._register_lock(ctk.CTkOptionMenu(
                top, variable=field["type_var"], values=["文本", "素材", "字体"], width=72,
                command=lambda _c: self._on_field_changed(),
                fg_color=APP_COLORS["background"], button_color=APP_COLORS["accent"],
                button_hover_color=APP_COLORS["accent_soft"], text_color=APP_COLORS["text"],
            )).grid(row=0, column=1, padx=(0, 6))
            result = self._register_lock(ctk.CTkEntry(
                top, textvariable=field["result_var"], fg_color=APP_COLORS["background"],
                border_color=APP_COLORS["border"], text_color=APP_COLORS["text"],
            ))
            # error 哨兵：结果为 error（不区分大小写）→ 标红（禁用「生成」的联动在 P3 接真值时做）。
            if field["result_var"].get().strip().lower() == "error":
                result.configure(border_color=APP_COLORS["warning"], text_color=APP_COLORS["warning"])
            result.grid(row=0, column=2, sticky="ew")
            self._register_lock(
                self._btn(top, "✕", lambda key=field["key"]: self._delete_field(key), width=30)
            ).grid(row=0, column=3, padx=(6, 0))
            self._register_lock(ctk.CTkEntry(
                card, textvariable=field["inst_var"], fg_color=APP_COLORS["background"],
                border_color=APP_COLORS["border"], text_color=APP_COLORS["text"],
                placeholder_text="提取规则：告诉 AI 提取什么、约束是什么",
            )).grid(row=1, column=0, sticky="ew", padx=7, pady=(0, 7))
        self._register_lock(
            self._btn(body, "添加字段 +", self._add_field)
        ).grid(row=len(self.field_defs) + 1, column=0, sticky="w", pady=(8, 0))

    def _add_field(self) -> None:
        self.field_seq += 1
        key = f"field{self.field_seq}"
        field = {"key": key, "name": f"字段{self.field_seq}", "type": "文本", "instruction": ""}
        self._ensure_field_vars(field)
        self.field_defs.append(field)
        self._on_field_changed()

    def _delete_field(self, key: str) -> None:
        self.field_defs = [f for f in self.field_defs if f["key"] != key]
        self._on_field_changed()

    def _on_field_changed(self) -> None:
        # 字段增删/类型变 → 重渲染字段卡。（图层行已改为独立单行设计，不再随字段联动。）
        self._render_fields()

    def _build_library_panel(self, parent) -> ctk.CTkFrame:
        panel, body = self._ctk_card(parent, "字体库 / 素材库", locked=True)
        body.columnconfigure(0, weight=1)
        font_names = [getattr(lib, "name", "") or "字体库" for lib in self.active_bundle.font_libraries] or ["字体库1"]
        image_names = [getattr(lib, "name", "") or "素材库" for lib in self.active_bundle.image_libraries] or ["素材库1"]
        row = 0
        for prefix, names in (("字体库", font_names), ("素材库", image_names)):
            for name in names:
                line = ctk.CTkFrame(body, fg_color="transparent")
                line.grid(row=row, column=0, sticky="ew", pady=2)
                line.columnconfigure(0, weight=1)
                ctk.CTkLabel(line, text=f"{prefix} · {name}", anchor="w").grid(row=0, column=0, sticky="w")
                self._register_lock(
                    self._btn(line, "点击上传", self.open_settings, width=80)
                ).grid(row=0, column=1, padx=(6, 0))
                row += 1
        ctk.CTkLabel(
            body, text="库目录当前在菜单栏「设置」中管理", anchor="w",
            text_color=APP_COLORS["muted"], font=ctk.CTkFont(size=11),
        ).grid(row=row, column=0, sticky="w", pady=(6, 0))
        return panel

    def _build_output_settings_panel(self, parent) -> ctk.CTkFrame:
        panel, body = self._ctk_card(parent, "输出设置", locked=True)
        body.columnconfigure(1, weight=1)
        ctk.CTkLabel(body, text="输出目录", anchor="w").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 8))
        dir_row = ctk.CTkFrame(body, fg_color="transparent")
        dir_row.grid(row=0, column=1, sticky="ew", pady=4)
        dir_row.columnconfigure(0, weight=1)
        self._register_lock(ctk.CTkEntry(dir_row, textvariable=self.output_var)).grid(row=0, column=0, sticky="ew")
        self._register_lock(self._btn(dir_row, "选择", self.choose_output)).grid(row=0, column=1, padx=(8, 0))
        ctk.CTkLabel(body, text="输出格式", anchor="w").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 8))
        fmt_row = ctk.CTkFrame(body, fg_color="transparent")
        fmt_row.grid(row=1, column=1, sticky="w", pady=4)
        for output_format, label in (("png", "PNG"), ("svg", "SVG"), ("dxf", "DXF")):
            self._register_lock(ctk.CTkCheckBox(
                fmt_row, text=label, variable=self.output_format_vars[output_format],
                onvalue=True, offvalue=False, checkbox_width=18, checkbox_height=18,
                fg_color=APP_COLORS["accent"], hover_color=APP_COLORS["accent_soft"],
            )).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(body, text="文件命名", anchor="w").grid(row=2, column=0, sticky="w", pady=4, padx=(0, 8))
        self._register_lock(ctk.CTkEntry(
            body, textvariable=self.filename_template_var, placeholder_text="可填 GPT 识别的订单号字段",
        )).grid(row=2, column=1, sticky="ew", pady=4)
        # 状态 + 主操作「生成」：原底部「生产输出」栏已删，这里承接其唯一不重复的两项。
        action_row = ctk.CTkFrame(body, fg_color="transparent")
        action_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        action_row.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            action_row, textvariable=self.status_var, text_color=APP_COLORS["muted"], anchor="w",
            font=ctk.CTkFont(size=11), wraplength=200, justify="left",
        ).grid(row=0, column=0, sticky="ew")
        # 「生成」是操作动作（非配置）：**不入锁**，配置锁定时操作员仍可生成。
        self.confirm_button = self._btn(action_row, "生成", self.confirm_and_generate, primary=True, width=90)
        self.confirm_button.grid(row=0, column=1, sticky="e", padx=(8, 0))
        return panel

    def _build_background_prompt_panel(self, parent) -> ctk.CTkFrame:
        panel, body = self._ctk_card(parent, "背景提示词", locked=True)
        body.columnconfigure(0, weight=1)
        self.background_prompt_text = self._register_lock(ctk.CTkTextbox(
            body, height=54, fg_color=APP_COLORS["input"], text_color=APP_COLORS["text"],
            border_width=1, border_color=APP_COLORS["border"],
        ))
        self.background_prompt_text.grid(row=0, column=0, sticky="ew")
        saved = active_product(self.config).background_prompt
        if saved:
            self.background_prompt_text.insert("1.0", saved)
        self.background_prompt_text.bind("<FocusOut>", lambda _e: self._persist_prompts())
        return panel

    def _build_generate_prompt_panel(self, parent) -> ctk.CTkFrame:
        panel, body = self._ctk_card(parent, "生成的提示词（开发期）", locked=True)
        body.columnconfigure(0, weight=1)
        self._register_lock(
            self._btn(body, "生成提示词", self._show_generated_prompt, primary=True)
        ).grid(row=0, column=0, sticky="w")
        self.generated_prompt_text = ctk.CTkTextbox(
            body, height=110, fg_color="#161616", text_color=APP_COLORS["muted"],
            border_width=1, border_color=APP_COLORS["border"],
        )
        self.generated_prompt_text.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.generated_prompt_text.configure(state="disabled")
        return panel

    def _toggle_config_lock(self) -> None:
        """锁定区（背景词/字段/图层/库/输出/生成）控件随锁开合 disable；订单备注框不受锁。

        P4 再接密码校验；本轮先做真正的控件只读切换。
        """
        locked = not self.config_locked_var.get()
        self.config_locked_var.set(locked)
        if self.lock_button is not None:
            self.lock_button.configure(text="🔒" if locked else "🔓")
        state = "disabled" if locked else "normal"
        self._prune_locked()  # 先剔除已销毁引用，避免对死控件 configure
        for widget in self._locked_widgets:
            try:
                widget.configure(state=state)
            except Exception:
                pass
        self.status_var.set("配置已锁定（密码校验 P4 接入）" if locked else "配置已解锁")

    def _persist_prompts(self) -> None:
        """把「背景提示词」存回当前产品配置并落盘（失焦/切产品时触发）。
        提取已回档为多字段「字段」卡（UI 态 mock，P3 接真），不走提示词持久化；
        product.extraction_prompt 原样保留不动。"""
        background = ""
        if self.background_prompt_text is not None:
            background = self.background_prompt_text.get("1.0", "end-1c").strip()
        product = active_product(self.config)
        if background == product.background_prompt:
            return  # 无变化不写盘
        self.config = with_product_prompts(
            self.config, extraction_prompt=product.extraction_prompt, background_prompt=background
        )
        save_config(self.config)

    def _load_prompts_into_widgets(self) -> None:
        """把当前产品的背景提示词载入文本框（切产品后调用）。"""
        product = active_product(self.config)
        box = self.background_prompt_text
        if box is None:
            return
        box.delete("1.0", "end")
        if product.background_prompt:
            box.insert("1.0", product.background_prompt)

    def _show_generated_prompt(self) -> None:
        """本地拼装预览：字段提取规则 + 背景词 + 订单信息。P3 再接库目录与真实发送格式。"""
        lines = ["[字段提取规则]"]
        for field in self.field_defs:
            lines.append(
                f"- {field['name_var'].get()}（{field['type_var'].get()}）：{field['inst_var'].get()}"
            )
        background = ""
        if self.background_prompt_text is not None:
            background = self.background_prompt_text.get("1.0", "end-1c").strip()
        if background:
            lines += ["", f"[背景提示词] {background}"]
        remark = self._current_remark_text().strip()
        lines += ["", f"[订单信息] {remark or '（未填写）'}"]
        text = "\n".join(lines)
        box = self.generated_prompt_text
        if box is not None:
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("1.0", text)
            box.configure(state="disabled")
        self.status_var.set("已生成提示词预览（本地拼装；P3 接库目录与真实发送格式）")

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
        self.ai_prefer_var = tk.BooleanVar(value=profile.prefer_ai)
        self.ai_provider_var = tk.StringVar(value=profile.provider)
        self.ai_model_var = tk.StringVar(value=profile.model)
        self.ai_base_url_var = tk.StringVar(value=profile.base_url)
        self.ai_api_key_env_var = tk.StringVar(value=profile.api_key_env_var)
        self.ai_project_env_var = tk.StringVar(value=profile.project_env_var)
        self.ai_org_env_var = tk.StringVar(value=profile.org_env_var)
        ttk.Checkbutton(frame, text="优先使用 AI 解析", variable=self.ai_prefer_var).grid(row=0, column=0, columnspan=2, sticky="w", pady=4)
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
            layout_defaults=self._active_layout_defaults(),
        )
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

    def _current_ai_config(self) -> AIParseConfig:
        return build_ai_parse_config(active_ai_profile(self.config), self.session_api_key_var.get())

    def _settings_ai_profile(self) -> AIProfile:
        return build_ai_profile_from_settings(
            active_ai_profile(self.config),
            provider=self.ai_provider_var.get(),
            model=self.ai_model_var.get(),
            base_url=self.ai_base_url_var.get(),
            api_key_env_var=self.ai_api_key_env_var.get(),
            project_env_var=self.ai_project_env_var.get(),
            org_env_var=self.ai_org_env_var.get(),
            prefer_ai=bool(self.ai_prefer_var.get()),
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
        try:
            month = int(self.month_var.get())
        except ValueError:
            month = 1
        month = min(12, max(1, month))
        try:
            flower = int(self.flower_var.get())
        except ValueError:
            flower = 1
        flower = max(1, flower)
        is_bitmap = path.suffix.casefold() in IMPORTABLE_BITMAP_SUFFIXES
        return FlowerAsset(
            name=path.stem,
            month=month,
            flower=flower,
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
        ai_config = self._current_ai_config()
        self.status_var.set("解析中...")

        def on_error(exc: Exception) -> None:
            self.status_var.set("解析失败")
            messagebox.showerror("解析失败", str(exc))

        run_background(
            self.root,
            lambda: parse_order_remark_auto(remark, ai_config=ai_config, bundle=self.active_bundle),
            self._apply_parse_result,
            on_error,
        )

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
        if result.text:
            self.name_var.set(result.text)
        if result.month is not None:
            self.month_var.set(str(result.month))
        if result.font is not None:
            self.font_var.set(str(result.font))
        if result.flower is not None:
            self.flower_var.set(str(result.flower))
        self.personalization_type_var.set(getattr(result, "personalization_type", "unknown") or "unknown")
        self._refresh_flower_choices()
        self._select_flower_by_current_fields()
        self._select_font_by_current_field()
        self._replace_layers_from_parse_result(result)
        if result.warnings:
            self._show_parse_warning_dialog(result)
        self._redraw_preview()

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

    def _parse_result_can_create_layers(self, result) -> bool:
        warnings = getattr(result, "warnings", []) or []
        return (
            not warnings
            and bool((getattr(result, "text", "") or "").strip())
            and getattr(result, "month", None) is not None
            and getattr(result, "font", None) is not None
            and getattr(result, "flower", None) is not None
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
        path = filedialog.askopenfilename(
            title="选择字体",
            filetypes=[("Font", "*.ttf *.otf")],
        )
        if not path:
            path = filedialog.askdirectory(title="选择字体目录")
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
            for output_format in selected_formats:
                target_path = output_path_for_format(base_output_path, output_format)
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

    def _current_readiness_parse_result(self) -> ParseResult:
        result = build_readiness_parse_result_from_values(
            self._content_text_for_render(),
            self.month_var.get(),
            self.font_var.get(),
            self.flower_var.get(),
            self._selected_flower_path(),
            self._selected_font_path(),
            self.personalization_type_var.get(),
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



    def _layer_from_listbox_event(self, event) -> object | None:
        listbox = self.layers_listbox
        if listbox is None:
            return None
        index = listbox.nearest(event.y)
        if index < 0:
            return None
        layer_index = len(self.document.layers) - 1 - index
        if not 0 <= layer_index < len(self.document.layers):
            return None
        layer = self.document.layers[layer_index]
        self.document.selected_layer_id = layer.id
        self.selected_preview_item = layer.id
        listbox.selection_clear(0, "end")
        listbox.selection_set(index)
        self._sync_layer_properties(layer)
        return layer

    def _show_layer_context_menu(self, event) -> None:
        """图层列表右键菜单；文本图层暂不进入素材编辑，后续单独做文字属性编辑。"""
        layer = self._layer_from_listbox_event(event)
        if layer is None:
            return
        menu = tk.Menu(self.root, tearoff=False)
        edit_state = "normal" if isinstance(layer, ImageLayer) else "disabled"
        menu.add_command(label="编辑素材...", state=edit_state, command=self.open_selected_material_editor)
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
        layer = self._layer_from_listbox_event(event)
        if isinstance(layer, ImageLayer):
            self.open_selected_material_editor()
        elif layer is not None:
            self.status_var.set("文本图层暂不使用素材编辑；请使用文本属性区域。")

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
        """类型小图标：文本=蓝底 T，素材/图片=绿底 ▣。"""
        if isinstance(layer, TextLayer):
            return ("T", APP_COLORS["accent"])
        return ("▣", "#3fb27f")

    def _layer_main_text(self, layer) -> str:
        """行内主内容：文本层=识别到的文字内容，素材层=文件名（空则返回 ''，调用方显示占位）。"""
        if isinstance(layer, TextLayer):
            for attr in ("original_text", "text", "render_text"):
                value = str(getattr(layer, attr, "") or "").strip()
                if value:
                    return value
            return ""
        name = str(getattr(layer, "name", "") or "").strip()
        if name:
            return name
        path = getattr(layer, "path", None)
        return path.stem if path is not None else ""

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
        widget.bind("<Button-3>", lambda e, l=layer: self._layer_menu(l, e))
        widget.bind("<Button-2>", lambda e, l=layer: self._layer_menu(l, e))
        for child in widget.winfo_children():
            self._bind_layer_menu(child, layer)

    def _lib_label_for_id(self, libraries, library_id: str) -> str:
        if not library_id:
            return ""
        lib = next((l for l in libraries if l.id == library_id), None)
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
        box = self.layers_rows_box
        if box is None:
            return
        order = [layer.id for layer in reversed(self.document.layers)]  # z 大在上，与画布一致
        layer_by_id = {layer.id: layer for layer in self.document.layers}
        # 1) 删除已不存在图层的行（仅此时才销毁控件——频率低）
        for lid in list(self._layer_rows):
            if lid not in layer_by_id:
                self._layer_rows.pop(lid)["card"].destroy()
        self._prune_locked()
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
        handle.bind("<ButtonPress-1>", lambda e, l=layer: self._layer_drag_start(l, e))
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
            area.bind("<Button-1>", lambda _e, l=layer: self._select_layer_row(l))
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
                material_key = asset.asset_key or asset.path.stem
                found = self.active_bundle.resolve_material(material_key)
                layer.path = asset.path
                layer.name = asset.display_name or asset.name
                layer.material_id = material_key
                layer.material_key = material_key
                layer.material_name = asset.display_name or asset.name
                if found:
                    layer.library_id = found[0]
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
            layer.font_path = asset.path
            font_found = self.active_bundle.resolve_font_by_tags(index=asset.index)
            if font_found:
                layer.font_library_id = font_found[0]
                layer.font_key = font_found[1].key
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
        order_ids.pop(old_pos)
        order_ids.insert(insert_idx, drag_id)
        layer_by_id = {l.id: l for l in self.document.layers}
        self.document.layers[:] = [layer_by_id[lid] for lid in reversed(order_ids)]  # 列表是 下→上
        self.document.normalize_z_indexes()
        self.status_var.set("图层顺序已更新")
        self._render_layers()
        self._redraw_preview()

    # ---- B5 右键/⋮ 菜单（接真实操作，复用既有逻辑）----
    def _layer_menu(self, layer, event=None) -> None:
        self._select_layer_row(layer)
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="位置 / 尺寸…", command=lambda l=layer: self._open_layer_geometry_dialog(l))
        # 改库 / 改素材或字体：行内不放下拉，统一收进右键菜单（候选来自 active_bundle）。
        if isinstance(layer, ImageLayer):
            lib_labels = list(self._image_lib_by_label)
            if lib_labels:
                lib_menu = tk.Menu(menu, tearoff=False)
                for lbl in lib_labels:
                    lib_menu.add_command(label=self._abbrev(lbl, 24),
                                         command=lambda l=layer, x=lbl: self._on_layer_image_lib_changed(l, x))
                menu.add_cascade(label="素材库", menu=lib_menu)
            item_labels = list(self.flower_label_map)
            if item_labels:
                item_menu = tk.Menu(menu, tearoff=False)
                for lbl in item_labels:
                    item_menu.add_command(label=self._abbrev(lbl, 28),
                                          command=lambda l=layer, x=lbl: self._on_layer_material_changed(l, x))
                menu.add_cascade(label="素材", menu=item_menu)
        if isinstance(layer, TextLayer):
            lib_labels = list(self._font_lib_by_label)
            if lib_labels:
                lib_menu = tk.Menu(menu, tearoff=False)
                for lbl in lib_labels:
                    lib_menu.add_command(label=self._abbrev(lbl, 24),
                                         command=lambda l=layer, x=lbl: self._on_layer_font_lib_changed(l, x))
                menu.add_cascade(label="字体库", menu=lib_menu)
            font_labels = list(self.font_label_map)
            if font_labels:
                font_menu = tk.Menu(menu, tearoff=False)
                for lbl in font_labels:
                    font_menu.add_command(label=self._abbrev(lbl, 28),
                                          command=lambda l=layer, x=lbl: self._on_layer_font_changed(l, x))
                menu.add_cascade(label="字体", menu=font_menu)
            align_menu = tk.Menu(menu, tearoff=False)
            for key, lbl in (("left", "左对齐"), ("center", "居中"), ("right", "右对齐")):
                align_menu.add_command(label=lbl, command=lambda l=layer, k=key: self._set_layer_align(l, k))
            menu.add_cascade(label="对齐", menu=align_menu)
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

    def _set_layer_align(self, layer, key: str) -> None:
        if isinstance(layer, TextLayer):
            layer.align = key
            self.status_var.set(f"对齐 → {key}")
            self._redraw_preview()

    def _open_layer_geometry_dialog(self, layer) -> None:
        """位置/尺寸小对话框：复用 layer_x/y/w/h(+字号) var 与 _apply_layer_production 写回。"""
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
        win.grab_set()

    def _refresh_layers_panel(self) -> None:
        """刷新右下角图层面板，显示名称、类型、显隐和锁定状态。"""
        self._schedule_render_layers()  # 真实图层行：延后到 idle 渲染（去重；不在同步流程里现场建控件）
        listbox = self.layers_listbox
        if listbox is None:
            return
        listbox.delete(0, "end")
        for layer in reversed(self.document.layers):
            visible = "👁" if layer.visible else "🚫"
            locked = "🔒" if layer.locked else "🔓"
            listbox.insert("end", f"{visible} {locked} {layer.name} [{layer.type}]")
        selected = self.document.selected_layer()
        if selected is not None:
            panel_index = len(self.document.layers) - 1 - self.document.layers.index(selected)
            listbox.selection_set(panel_index)
            self.layer_detail_var.set(f"已选：{selected.name} ({selected.type})")
            self._sync_layer_properties(selected)
        else:
            self.layer_detail_var.set("未选择图层")

    def _on_layer_list_select(self, _event=None) -> None:
        listbox = self.layers_listbox
        if listbox is None:
            return
        selection = listbox.curselection()
        if not selection:
            return
        layer_index = len(self.document.layers) - 1 - selection[0]
        if 0 <= layer_index < len(self.document.layers):
            layer = self.document.layers[layer_index]
            self.document.selected_layer_id = layer.id
            self.selected_preview_item = layer.id
            self._sync_layer_properties(layer)
            self._redraw_preview()

    def _sync_layer_properties(self, layer) -> None:
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

    def _slot_defaults(self, layer) -> ProductionParams:
        """图层「槽位」的产品级生产默认，取自当前布局默认 EngravingLayout（回落链最低层）。"""
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            layout = self.config.layout_defaults
        if isinstance(layer, TextLayer):
            return ProductionParams(
                x=layout.text_x, y=layout.text_y, width=layout.text_width,
                height=layout.text_height, font_size=layout.text_size,
            )
        return ProductionParams(
            x=layout.flower_x, y=layout.flower_y,
            width=layout.flower_width, height=layout.flower_height,
        )

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
        """§5 回落链：产品默认 → 库默认 → 素材默认 → 图层 override（低→高优先级）。"""
        library_defaults, entry_defaults = self._layer_library_entry_defaults(layer)
        return resolve_chain(self._slot_defaults(layer), library_defaults, entry_defaults, layer.production)

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
        layer.visible = not layer.visible
        self._refresh_layers_panel()
        self._redraw_preview()

    def _toggle_selected_layer_locked(self) -> None:
        layer = self.document.selected_layer()
        if layer is None:
            self.status_var.set("未选择有效图层")
            return
        layer.locked = not layer.locked
        self._refresh_layers_panel()
        self._redraw_preview()

    def _delete_selected_layer(self) -> None:
        if self.inline_text_entry is not None:
            return
        removed = delete_layer(self.document, self.document.selected_layer_id)
        if removed is None:
            self.status_var.set("未选择有效图层，或图层已锁定")
        self.selected_preview_item = self.document.selected_layer_id
        self._refresh_layers_panel()
        self._redraw_preview()

    def _move_selected_layer(self, action: str) -> None:
        if not move_layer(self.document, self.document.selected_layer_id, action):
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
        layer.original_text = new_text
        layer.raw_text = new_text
        layer.text = new_text
        if old_text != new_text and layer.glyph_overrides:
            LOGGER.info("文本内容变化，清空特殊字形绑定：layer_id=%s", layer.id)
            layer.glyph_overrides.clear()
            self.status_var.set("文本内容已变化，特殊字形需要重新应用")
        layer.render_text = new_text
        try:
            layer.font_size = max(1, int(self.layer_font_size_var.get()))
        except ValueError:
            messagebox.showerror("文本属性", "字号必须是整数")
            return
        layer.fill_color = self.layer_color_var.get().strip() or "#111111"
        layer.color = layer.fill_color
        # 字体样式 per-layer override：直接写概数布尔/字间距（覆盖建层时烘的全局默认）。
        layer.bold = bool(self.layer_bold_var.get())
        layer.underline = bool(self.layer_underline_var.get())
        try:
            spacing = float(self.layer_letter_spacing_var.get())
        except ValueError:
            messagebox.showerror("文本属性", "字间距必须是数字")
            return
        layer.letter_spacing = spacing
        layer.tracking = spacing  # 两字段同步，避免导出端 `letter_spacing or tracking` 读到旧值。
        # 文本修改后只更新 TextLayer，自身仍可继续编辑并重新渲染。
        self._refresh_layers_panel()
        self._redraw_preview()

    def _nudge_selected_layer(self, dx: int, dy: int) -> None:
        if self.inline_text_entry is not None:
            return
        layer = self.document.selected_layer()
        if layer is None or layer.locked:
            return
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
        self._select_flower_by_current_fields()
        self._update_month_chip()
        self._redraw_preview()

    def _refresh_font_choices(self) -> None:
        # 增量3：候选按当前选中的字体库过滤（单库时即全部）。
        assets = self._assets_for_selected_font_library()
        self.font_label_map = {self._font_label(asset): asset for asset in assets}
        self.font_combo.configure(values=list(self.font_label_map) or ["（请扫描字体）"])
        self._select_font_by_current_field()

    def _merge_additional_library_assets(self) -> None:
        """单库时空操作；多库时把「首库之外」的 image/font 库 entries 转成资产并入候选。"""
        existing = {asset.path.name for asset in self.flower_assets}
        for library in self.active_bundle.image_libraries[1:]:
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
            month=_coerce_int(entry.tags.get("month"), 1),
            flower=_coerce_int(entry.tags.get("flower"), 1),
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
        """月份 chip 反映当前选中素材的月份/花朵（取代手填月份字段）。"""
        asset = self.flower_label_map.get(self.flower_asset_var.get())
        self.month_chip_var.set(f"{asset.month} 月 · 花 {asset.flower}" if asset is not None else "—")

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
        """保存待添加素材；可选同步旧版月份/flower 字段但不触发新增图层。"""
        self.pending_flower_asset_label = material_id
        asset = self.flower_label_map.get(material_id)

        def update_fields() -> None:
            self.flower_asset_var.set(material_id)
            if sync_fields and asset is not None:
                self.month_var.set(str(asset.month))
                self.flower_var.set(str(asset.flower))

        self._with_programmatic_update(update_fields)
        self._update_month_chip()  # 增量3：选中素材后刷新只读月份 chip

    def _replace_selected_image_layer(self, asset: FlowerAsset) -> None:
        """替换当前选中素材图层的图片资源；保持图层尺寸和层级不变。"""
        layer = self.document.selected_layer()
        if not isinstance(layer, ImageLayer):
            return
        if not asset.path.is_file():
            messagebox.showerror("素材错误", f"素材文件不存在：{asset.path}")
            return
        layer.path = asset.path
        layer.name = asset.display_name or asset.name
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
        self.selected_preview_item = layer.id
        self._refresh_layers_panel()
        self._redraw_preview()

    def _apply_auto_glyph_rules_to_layer(self, layer: TextLayer) -> None:
        """按当前字体规则自动应用首尾字形；失败只提示 warning，不阻塞渲染。"""
        try:
            render_text, overrides, warnings, applied = apply_automatic_glyph_rules(
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
        self.selected_preview_item = layer.id
        self._sync_layer_properties(layer)
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

    def _select_flower_by_current_fields(self) -> None:
        try:
            month = int(self.month_var.get())
            flower = int(self.flower_var.get())
        except ValueError:
            return
        selected = find_flower_asset(Path(self.flower_dir_var.get()), month=month, flower=flower)
        if selected is None:
            return
        label = self._flower_label(selected)
        if label in self.flower_label_map:
            self._set_pending_flower_asset(label)

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
        return f"{asset.flower} - {asset.name} | {asset.path.name}"

    def _font_label(self, asset: FontAsset) -> str:
        return format_font_asset_label(asset)

    def _save_current_config(self) -> None:
        # 用 replace 而非整体重建 AppConfig，否则会清空 products/active_product_id/收展态
        # （与 _save_settings_window 同一坑：__post_init__ 只在 products 空时才合成产品0）。
        self.config = dataclasses.replace(
            self.config,
            flower_dir=Path(self.flower_dir_var.get()),
            font_source=Path(self.font_source_var.get()),
            output_path=Path(self.output_var.get()),
            output_formats=self._selected_output_formats_or_default(),
            layout_defaults=self._active_layout_defaults(),
        )
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
        self.month_var.trace_add("write", lambda *_: self._on_flower_field_change())
        self.flower_var.trace_add("write", lambda *_: self._on_flower_field_change())
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
        # 画布刷新只读取 Document：先清空，再按图层顺序逐层渲染可见图层。
        for layer in self.document.sorted_layers():
            if not layer.visible:
                continue
            if isinstance(layer, ImageLayer):
                self._draw_image_layer_preview(canvas, layer, sx, sy)
            elif isinstance(layer, TextLayer):
                self._draw_text_layer_preview(canvas, layer, scale, offset_x, offset_y)
        if DEBUG_VISUAL_BBOX:
            glyph_result = self._resolve_current_glyph()
            name = glyph_result.render_text.strip() or "Name"
            text_layout = layout_personalization_text(name, layout, self.personalization_type_var.get(), self._selected_font_path())
            self._draw_visual_debug(canvas, layout, text_layout, sx, sy)
        self._draw_selection_controls(canvas, layout, sx, sy)
        if self.document.layers:
            self._set_warnings([])
        else:
            glyph_result = self._resolve_current_glyph()
            name = glyph_result.render_text.strip() or "Name"
            text_layout = layout_personalization_text(name, layout, self.personalization_type_var.get(), self._selected_font_path())
            self._set_readiness_display(self._current_readiness_parse_result(), text_layout)
        # 画布重绘会清空 window item；如果正在内联编辑，重建/移动覆盖编辑器以跟随缩放、平移和图层位置。
        if self.inline_text_entry is not None and not self.inline_text_is_closing:
            self.inline_text_window = None
            self._place_inline_text_editor()

    def _draw_image_layer_preview(self, canvas: tk.Canvas, layer: ImageLayer, sx, sy) -> None:
        """预览素材图层；每个 ImageLayer 独立绘制，不再读取单一 current_asset。"""
        if layer.path is None or not layer.path.exists():
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

    def _update_preview_zoom_status(self) -> None:
        var = getattr(self, "preview_zoom_status_var", None)
        if var is not None:
            var.set(self._preview_zoom_percent_text())

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

    def _wheel_horizontal_pan_requested(self, event) -> bool:
        """Alt/Shift + wheel: horizontal pan, matching common editor/CAD shortcuts."""
        state = int(getattr(event, "state", 0) or 0)
        shift_pressed = bool(state & 0x0001)
        # Alt is usually Mod1 (0x0008) on Tk/X11; Windows Tk may report extended high bits.
        alt_pressed = bool(state & 0x0008 or state & 0x20000)
        return shift_pressed or alt_pressed

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

        if self._wheel_horizontal_pan_requested(event):
            # Shift/Alt + 滚轮只移动视口，不改变缩放；方向保持“滚轮向上→内容向右”。
            self.preview_pan_x += direction * PREVIEW_WHEEL_PAN_STEP
            canvas.focus_set()
            self._redraw_preview()
            return "break"

        old_scale, old_offset_x, old_offset_y = self._preview_transform(layout)
        if old_scale <= 0:
            return "break"

        old_zoom = self.preview_zoom
        factor = PREVIEW_ZOOM_STEP if direction > 0 else 1 / PREVIEW_ZOOM_STEP
        new_zoom = max(PREVIEW_ZOOM_MIN, min(PREVIEW_ZOOM_MAX, old_zoom * factor))
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
        """按当前缩放/平移把覆盖编辑器放到文本图层 bounding box 附近。"""
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
        x = offset_x + left * scale
        y = offset_y + top * scale
        width = max(160, int((right - left) * scale))
        height = max(44, int((bottom - top) * scale))
        try:
            editor.configure(font=(self._selected_preview_font_family(), max(8, round(layer.font_size * scale))))
        except tk.TclError:
            pass
        if self.inline_text_window is None:
            self.inline_text_window = canvas.create_window(
                x,
                y,
                window=editor,
                anchor="nw",
                width=width,
                height=height,
                tags=("inline_text_editor",),
            )
            if self.floating_text_editor is not None:
                self.floating_text_editor.window_id = self.inline_text_window
        else:
            canvas.coords(self.inline_text_window, x, y)
            canvas.itemconfigure(self.inline_text_window, width=width, height=height)
        canvas.tag_raise(self.inline_text_window)

    def _commit_inline_text_edit(self) -> str:
        editor = self.inline_text_entry
        layer = self.document.layer_by_id(self.inline_text_layer_id)
        if editor is not None and isinstance(layer, TextLayer):
            new_text = editor.get("1.0", "end-1c")
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
            self._drag_target = layer.id if layer and not layer.locked else None
            self._drag_mode = "move"
        self.document.selected_layer_id = layer.id if layer else None
        self.selected_preview_item = self.document.selected_layer_id
        self._drag_start = (event.x, event.y)
        canvas.focus_set()
        self._refresh_layers_panel()
        self._redraw_preview()

    def _on_canvas_pan_press(self, event) -> str:
        """鼠标中键按住后拖动平移画板；不改变图层选择和导出坐标。"""
        canvas = self.preview_canvas
        if canvas is None:
            return "break"
        if self.inline_text_entry is not None:
            self._commit_inline_text_edit()
        self._drag_target = None
        self._drag_mode = "pan"
        self._drag_start = (event.x, event.y)
        self._set_preview_cursor("fleur")
        canvas.focus_set()
        return "break"

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
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            return
        scale, _offset_x, _offset_y = self._preview_transform(layout)
        dx = screen_dx / scale
        dy = screen_dy / scale
        if self._drag_mode == "resize":
            if isinstance(layer, TextLayer):
                CanvasTextItem(layer).resize_by(dx, dy)
            else:
                layer.width = max(20, layer.width + dx)
                layer.height = max(20, layer.height + dy)
        else:
            if isinstance(layer, TextLayer):
                CanvasTextItem(layer).move_by(dx, dy)
            else:
                layer.x = max(0, layer.x + dx)
                layer.y = max(0, layer.y + dy)
        self._redraw_preview()

    def _on_canvas_release(self, _event) -> None:
        self._drag_target = None
        self._drag_start = None
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
