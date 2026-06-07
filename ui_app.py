from __future__ import annotations

import ctypes
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from types import SimpleNamespace
from typing import TypeVar

from asset_resolver import find_flower_asset, scan_flower_assets, scan_font_assets
from config_store import AIProfile, AppConfig, active_ai_profile, load_config, normalize_output_path, save_config
from generation_readiness import GenerationReadiness, build_generation_readiness
from glyph_service import GlyphApplyResult, GlyphMapConfig, check_runtime_dependencies, codepoint_to_char, normalize_codepoint, resolve_glyph
from models import AIParseConfig, BirthFlowerDesign, Document, EngravingLayout, FlowerAsset, FontAsset, ImageLayer, TextLayer, ParseResult, add_image_layer, add_text_layer, delete_layer, hit_test, move_layer
from order_importer import load_order_remark_from_file
from parse_pipeline import parse_order_remark_auto
from gpt_parser import DEFAULT_DEEPSEEK_BASE_URL, DEFAULT_DEEPSEEK_MODEL, DEFAULT_MODEL, parse_order_remark_with_gpt
from renderer import DEBUG_VISUAL_BBOX, PreviewCache, flower_debug_bboxes, render_document_png, render_document_svg, render_dxf, render_png, render_svg
from text_layout import LINE_HEIGHT_RATIO, measure_text_ink_bbox, layout_personalization_text


DEFAULT_FLOWER_DIR = Path("BirthMonth flowers")
DEFAULT_FONT_SOURCE = Path("Birthmonth_font.ttf")
IMPORTABLE_FONT_SUFFIXES = {".ttf", ".otf"}
IMPORTABLE_VECTOR_SUFFIXES = {".svg"}
IMPORTABLE_BITMAP_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
IMPORTABLE_ASSET_SUFFIXES = IMPORTABLE_VECTOR_SUFFIXES | IMPORTABLE_BITMAP_SUFFIXES
APP_COLORS = {
    "background": "#f6f7f8",
    "panel": "#ffffff",
    "border": "#d6d9de",
    "text": "#20242a",
    "muted": "#667085",
    "warning": "#9a5b00",
}
T = TypeVar("T")


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

        self.remark_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.month_var = tk.StringVar(value="1")
        self.font_var = tk.StringVar(value="1")
        self.flower_var = tk.StringVar(value="1")
        self.confidence_var = tk.StringVar(value="Readiness: -")
        self.case_sensitive_var = tk.BooleanVar(value=True)
        self.personalization_type_var = tk.StringVar(value="unknown")
        self.output_var = tk.StringVar(value=str(normalize_output_path(self.config.output_path)))
        self.flower_dir_var = tk.StringVar(value=str(self.config.flower_dir or DEFAULT_FLOWER_DIR))
        self.font_source_var = tk.StringVar(value=str(self.config.font_source or DEFAULT_FONT_SOURCE))
        self.flower_asset_var = tk.StringVar()
        self.font_asset_var = tk.StringVar()
        self.warning_var = tk.StringVar(value="等待解析")
        self.status_var = tk.StringVar(value="等待解析")
        self.output_format_vars = {
            "png": tk.BooleanVar(value="png" in self.config.output_formats),
            "svg": tk.BooleanVar(value="svg" in self.config.output_formats),
            "dxf": tk.BooleanVar(value="dxf" in self.config.output_formats),
        }
        self.session_api_key_var = tk.StringVar()
        self.flower_assets: list[FlowerAsset] = []
        self.font_assets: list[FontAsset] = []
        self.flower_label_map: dict[str, FlowerAsset] = {}
        self.font_label_map: dict[str, FontAsset] = {}
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
        self.layer_detail_var = tk.StringVar(value="未选择图层")
        self.layer_text_var = tk.StringVar()
        self.layer_font_size_var = tk.StringVar(value=str(default_layout.text_size))
        self.layer_color_var = tk.StringVar(value="#111111")
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
        self.preview_canvas: tk.Canvas | None = None
        self.remark_text: tk.Text | None = None
        self.confirm_button: ttk.Button | None = None
        self.inline_text_entry: ttk.Entry | None = None
        self.inline_text_window: int | None = None
        self.section_frames: dict[str, tk.Widget] = {}
        self._drag_target: str | None = None
        self._drag_start: tuple[int, int] | None = None
        self._drag_mode: str = "move"
        self.selected_preview_item: str | None = None
        self.last_parse_result: ParseResult | None = None
        self.glyph_config = GlyphMapConfig.load()
        self.current_glyph_result: GlyphApplyResult | None = None
        self.current_manual_glyph_override: dict[str, str] | None = None
        self.current_glyph_overrides: dict[int, dict[str, object]] = {}
        self.selected_glyph_position: int | None = None
        self.runtime_dependency_status = check_runtime_dependencies()

        self._build_menu()
        self._build_layout()
        self._scan_assets(show_errors=False)
        self._bind_preview_updates()
        self._redraw_preview()
        if not self.runtime_dependency_status.ok:
            self.warning_var.set(self.runtime_dependency_status.message)
        if self.glyph_config.load_warning:
            self.root.after(0, lambda: messagebox.showwarning("字形配置", self.glyph_config.load_warning))

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self.root)
        file_menu = tk.Menu(menu_bar, tearoff=False)
        import_menu = tk.Menu(file_menu, tearoff=False)
        import_menu.add_command(label="导入备注...", command=self.import_remark_file)
        import_menu.add_command(label="导入素材...", command=self.import_asset_file)
        file_menu.add_cascade(label="导入", menu=import_menu)
        file_menu.add_command(label="打开输出目录", command=self.open_output_dir)
        file_menu.add_separator()
        file_menu.add_command(label="设置...", accelerator="Ctrl+,", command=self.open_settings)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.destroy)
        menu_bar.add_cascade(label="文件", menu=file_menu)
        edit_menu = tk.Menu(menu_bar, tearoff=False)
        edit_menu.add_command(label="布局设置...", command=self.open_layout_settings)
        edit_menu.add_command(label="字形...", command=self.open_glyph_panel)
        menu_bar.add_cascade(label="编辑", menu=edit_menu)
        view_menu = tk.Menu(menu_bar, tearoff=False)
        view_menu.add_command(label="刷新预览", command=self._redraw_preview)
        menu_bar.add_cascade(label="查看", menu=view_menu)
        help_menu = tk.Menu(menu_bar, tearoff=False)
        help_menu.add_command(label="字形使用说明", command=self.show_glyph_help)
        menu_bar.add_cascade(label="帮助", menu=help_menu)
        self.root.config(menu=menu_bar)
        self.root.bind("<Control-comma>", lambda _event: self.open_settings())
        self.root.bind("<Delete>", lambda _event: self._delete_selected_layer())
        self.root.bind("<BackSpace>", lambda _event: self._delete_selected_layer())
        self.root.bind("<Left>", lambda _event: self._nudge_selected_layer(-1, 0))
        self.root.bind("<Right>", lambda _event: self._nudge_selected_layer(1, 0))
        self.root.bind("<Up>", lambda _event: self._nudge_selected_layer(0, -1))
        self.root.bind("<Down>", lambda _event: self._nudge_selected_layer(0, 1))
        self.root.bind("<Control-z>", lambda _event: self.status_var.set("撤销历史已预留，后续版本启用"))
        self.root.bind("<Control-y>", lambda _event: self.status_var.set("重做历史已预留，后续版本启用"))

    def _add_row(self, parent: ttk.LabelFrame, row: int, label: str, widget: ttk.Widget) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        widget.grid(row=row, column=1, sticky="ew", pady=4)
        parent.columnconfigure(1, weight=1)

    def _add_path_row(self, parent: ttk.LabelFrame, row: int, label: str, var: tk.StringVar, command) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        row_frame = ttk.Frame(parent)
        row_frame.grid(row=row, column=1, sticky="ew", pady=4)
        row_frame.columnconfigure(0, weight=1)
        ttk.Entry(row_frame, textvariable=var).grid(row=0, column=0, sticky="ew")
        ttk.Button(row_frame, text="选择", command=command).grid(row=0, column=1, padx=(8, 0))
        parent.columnconfigure(1, weight=1)

    def _configure_styles(self) -> None:
        """设置桌面生产工作台的基础 ttk 风格，不引入额外 UI 框架。"""
        self.root.configure(bg=APP_COLORS["background"])
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("App.TFrame", background=APP_COLORS["background"])
        style.configure("Panel.TFrame", background=APP_COLORS["panel"])
        style.configure("Panel.TLabelframe", background=APP_COLORS["panel"], bordercolor=APP_COLORS["border"])
        style.configure("Panel.TLabelframe.Label", foreground=APP_COLORS["text"], background=APP_COLORS["background"])
        style.configure("Status.TLabel", foreground=APP_COLORS["muted"], background=APP_COLORS["panel"])
        style.configure("Warning.TLabel", foreground=APP_COLORS["warning"], background=APP_COLORS["panel"])
        style.configure("Primary.TButton", foreground=APP_COLORS["text"])

    def _build_layout(self) -> None:
        self.root.geometry("1120x760")
        self.root.minsize(760, 560)
        self._configure_styles()

        frame = ttk.Frame(self.root, padding=8, style="App.TFrame")
        frame.pack(fill="both", expand=True)

        production_bar = self._build_production_bar(frame)
        production_bar.pack(side="bottom", fill="x", pady=(8, 0))

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
            "production_bar": production_bar,
        }
        self._set_warnings(["等待解析；识别结果不会自动生成最终文件。"])

    def _build_function_panel(self, parent: ttk.Frame) -> tuple[ttk.LabelFrame, ttk.LabelFrame, ttk.LabelFrame]:
        panel = ttk.LabelFrame(parent, text="功能区", padding=6, style="Panel.TLabelframe")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(0, weight=1)

        scroll_canvas = tk.Canvas(
            panel,
            width=320,
            highlightthickness=0,
            bg=APP_COLORS["panel"],
        )
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=scroll_canvas.yview)
        content = ttk.Frame(scroll_canvas, style="Panel.TFrame")
        window_id = scroll_canvas.create_window((0, 0), window=content, anchor="nw")
        scroll_canvas.configure(yscrollcommand=scrollbar.set)
        scroll_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        def sync_scroll_region(_event=None) -> None:
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))

        def sync_content_width(event) -> None:
            scroll_canvas.itemconfigure(window_id, width=event.width)

        content.bind("<Configure>", sync_scroll_region)
        scroll_canvas.bind("<Configure>", sync_content_width)

        order_panel = self._build_order_panel(content)
        production_panel = self._build_production_panel(content)
        order_panel.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        production_panel.grid(row=1, column=0, sticky="ew")
        layers_panel = self._build_layers_panel(content)
        layers_panel.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        content.columnconfigure(0, weight=1)
        return panel, order_panel, production_panel


    def _build_layers_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        """右下角图层面板：负责选择、显隐、锁定、删除和调整层级。"""
        panel = ttk.LabelFrame(parent, text="图层", padding=10, style="Panel.TLabelframe")
        panel.columnconfigure(0, weight=1)
        self.layers_listbox = tk.Listbox(panel, height=7, exportselection=False)
        self.layers_listbox.grid(row=0, column=0, columnspan=5, sticky="ew")
        self.layers_listbox.bind("<<ListboxSelect>>", self._on_layer_list_select)
        self.layers_listbox.bind("<Double-Button-1>", self._on_layer_list_double_click)
        self.layers_listbox.bind("<Button-3>", self._show_layer_context_menu)
        self.layers_listbox.bind("<Button-2>", self._show_layer_context_menu)
        ttk.Button(panel, text="显/隐", command=self._toggle_selected_layer_visible).grid(row=1, column=0, sticky="ew", pady=3)
        ttk.Button(panel, text="锁/解", command=self._toggle_selected_layer_locked).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Button(panel, text="删除", command=self._delete_selected_layer).grid(row=1, column=2, sticky="ew", pady=3)
        ttk.Button(panel, text="上移", command=lambda: self._move_selected_layer("up")).grid(row=2, column=0, sticky="ew", pady=3)
        ttk.Button(panel, text="下移", command=lambda: self._move_selected_layer("down")).grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Button(panel, text="置顶", command=lambda: self._move_selected_layer("top")).grid(row=2, column=2, sticky="ew", pady=3)
        ttk.Button(panel, text="置底", command=lambda: self._move_selected_layer("bottom")).grid(row=2, column=3, sticky="ew", pady=3)
        ttk.Label(panel, textvariable=self.layer_detail_var, style="Status.TLabel", wraplength=240).grid(row=3, column=0, columnspan=5, sticky="ew")
        ttk.Label(panel, text="文本").grid(row=4, column=0, sticky="w", pady=(6, 2))
        ttk.Entry(panel, textvariable=self.layer_text_var).grid(row=4, column=1, columnspan=4, sticky="ew", pady=(6, 2))
        ttk.Label(panel, text="字号").grid(row=5, column=0, sticky="w", pady=2)
        ttk.Entry(panel, textvariable=self.layer_font_size_var, width=8).grid(row=5, column=1, sticky="ew", pady=2)
        ttk.Label(panel, text="颜色").grid(row=5, column=2, sticky="w", pady=2)
        ttk.Entry(panel, textvariable=self.layer_color_var, width=10).grid(row=5, column=3, sticky="ew", pady=2)
        ttk.Button(panel, text="应用文本属性", command=self._apply_text_layer_properties).grid(row=5, column=4, sticky="ew", pady=2)
        return panel

    def _build_order_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        panel = ttk.LabelFrame(parent, text="订单与解析", padding=12, style="Panel.TLabelframe")
        panel.columnconfigure(0, weight=1)

        ttk.Label(panel, text="订单备注").grid(row=0, column=0, sticky="w")
        self.remark_text = tk.Text(
            panel,
            height=4,
            wrap="word",
            bg=APP_COLORS["panel"],
            fg=APP_COLORS["text"],
            insertbackground=APP_COLORS["text"],
            relief="solid",
            borderwidth=1,
        )
        self.remark_text.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        if self.remark_var.get():
            self.remark_text.insert("1.0", self.remark_var.get())

        action_row = ttk.Frame(panel)
        action_row.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        action_row.columnconfigure(0, weight=1)
        ttk.Button(action_row, text="导入", command=self.import_remark_file).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(action_row, text="解析", command=self.parse_remark).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(action_row, text="清空", command=self.clear_remark).grid(row=0, column=3)

        fields = ttk.LabelFrame(panel, text="人工确认字段", padding=10, style="Panel.TLabelframe")
        fields.grid(row=3, column=0, sticky="ew")
        self._add_row(fields, 0, "内容", ttk.Entry(fields, textvariable=self.name_var))
        self._add_row(fields, 1, "月份", ttk.Spinbox(fields, from_=1, to=12, textvariable=self.month_var, width=8))
        ttk.Checkbutton(fields, text="区分大小写", variable=self.case_sensitive_var).grid(
            row=2, column=1, sticky="w", pady=(6, 2)
        )
        ttk.Label(fields, textvariable=self.warning_var, style="Warning.TLabel", wraplength=240).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )
        return panel

    def _build_preview_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        panel = ttk.LabelFrame(parent, text="实时画板", padding=6, style="Panel.TLabelframe")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(
            panel,
            width=720,
            height=532,
            bg="white",
            highlightthickness=1,
            highlightbackground=APP_COLORS["border"],
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Button-1>", self._on_canvas_press)
        self.preview_canvas.bind("<Double-Button-1>", self._on_canvas_double_click)
        self.preview_canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.preview_canvas.bind("<Configure>", lambda _event: self._redraw_preview())
        self.preview_canvas.bind("<Delete>", lambda _event: self._delete_selected_layer())
        self.preview_canvas.bind("<BackSpace>", lambda _event: self._delete_selected_layer())
        return panel

    def _build_production_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        panel = ttk.LabelFrame(parent, text="生产参数", padding=12, style="Panel.TLabelframe")
        panel.columnconfigure(0, weight=1)

        asset_group = ttk.LabelFrame(panel, text="素材与字体", padding=10, style="Panel.TLabelframe")
        asset_group.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        asset_group.columnconfigure(1, weight=1)
        self.flower_combo = ttk.Combobox(asset_group, textvariable=self.flower_asset_var, state="readonly")
        self.flower_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_flower_combo_selected())
        ttk.Label(asset_group, text="素材名").grid(row=0, column=0, sticky="w", pady=4)
        self.flower_combo.grid(row=0, column=1, sticky="ew", pady=4)
        self.font_combo = ttk.Combobox(asset_group, textvariable=self.font_asset_var, state="readonly")
        self.font_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_font_combo_selected())
        ttk.Label(asset_group, text="字体类型").grid(row=1, column=0, sticky="w", pady=4)
        self.font_combo.grid(row=1, column=1, sticky="ew", pady=4)
        action_row = ttk.Frame(asset_group)
        action_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(action_row, text="添加素材为新图层", command=self._add_selected_flower_to_canvas).pack(side="left")
        ttk.Button(action_row, text="添加文本", command=self._add_text_layer_from_fields).pack(side="left", padx=(8, 0))

        ttk.Label(
            panel,
            text="全局布局默认值已移至：编辑 -> 布局设置...；新建图层会读取该默认值。",
            style="Status.TLabel",
            wraplength=260,
        ).grid(row=1, column=0, sticky="ew")
        return panel

    def _build_production_bar(self, parent: ttk.Frame) -> ttk.LabelFrame:
        bar = ttk.LabelFrame(parent, text="生产输出", padding=10, style="Panel.TLabelframe")
        bar.columnconfigure(2, weight=1)
        ttk.Label(bar, text="格式").grid(row=0, column=0, sticky="w")
        format_row = ttk.Frame(bar, style="Panel.TFrame")
        format_row.grid(row=0, column=1, sticky="w", padx=(8, 12))
        for output_format, label in (("png", "PNG"), ("svg", "SVG"), ("dxf", "DXF")):
            ttk.Checkbutton(format_row, text=label, variable=self.output_format_vars[output_format]).pack(
                side="left", padx=(0, 6)
            )
        ttk.Entry(bar, textvariable=self.output_var, width=28).grid(row=0, column=2, sticky="ew")
        ttk.Button(bar, text="选择", command=self.choose_output).grid(row=0, column=3, sticky="e", padx=(8, 0))
        ttk.Label(bar, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=4, sticky="w", padx=(10, 0))
        self.confirm_button = ttk.Button(
            bar,
            text="人工确认并生成",
            command=self.confirm_and_generate,
            style="Primary.TButton",
        )
        self.confirm_button.grid(row=0, column=5, sticky="e", padx=(10, 0))
        return bar

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
        window = tk.Toplevel(self.root)
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
        self._add_path_row(frame, 0, "素材目录", self.flower_dir_var, self.choose_flower_dir)
        ttk.Button(frame, text="重新扫描", command=lambda: self._scan_assets(show_errors=True)).grid(row=1, column=1, sticky="e", pady=8)

    def _build_font_settings_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=12)
        notebook.add(frame, text="字体库")
        ttk.Label(frame, text="字体文件/目录").grid(row=0, column=0, sticky="w", pady=4)
        row_frame = ttk.Frame(frame)
        row_frame.grid(row=0, column=1, sticky="ew", pady=4)
        row_frame.columnconfigure(0, weight=1)
        ttk.Entry(row_frame, textvariable=self.font_source_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(row_frame, text="选择字体", command=self.choose_font_source).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(frame, text="重新扫描", command=lambda: self._scan_assets(show_errors=True)).grid(row=1, column=1, sticky="e", pady=8)
        frame.columnconfigure(1, weight=1)

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
        ttk.Label(frame, text="最终文件仍必须通过主界面的人工确认按钮生成。").grid(
            row=3, column=1, sticky="w", pady=(4, 0)
        )
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
        self.config = AppConfig(
            flower_dir=Path(self.flower_dir_var.get()),
            font_source=Path(self.font_source_var.get()),
            output_path=Path(self.output_var.get()),
            output_formats=self._selected_output_formats_or_default(),
            ai_profiles=(profile,),
            active_ai_profile=profile.name,
            layout_defaults=layout_from_values(self.layout_vars),
        )
        save_config(self.config)
        self._scan_assets(show_errors=True)
        self.status_var.set("设置已保存")
        window.destroy()


    def open_layout_settings(self) -> None:
        """打开全局默认布局设置；这些值只用于之后新建图层，不回写已有图层。"""
        window = tk.Toplevel(self.root)
        window.title("布局设置")
        window.transient(self.root)
        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)
        fields = (
            ("画布宽", "canvas_width"),
            ("画布高", "canvas_height"),
            ("flower_x", "flower_x"),
            ("flower_y", "flower_y"),
            ("flower_width", "flower_width"),
            ("flower_height", "flower_height"),
            ("text_x", "text_x"),
            ("text_y", "text_y"),
            ("text_width", "text_width"),
            ("text_height", "text_height"),
            ("text_size", "text_size"),
        )
        dialog_vars = {key: tk.StringVar(value=self.layout_vars[key].get()) for _label, key in fields}
        for row, (label, key) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(frame, textvariable=dialog_vars[key], width=14).grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Label(
            frame,
            text="保存后的全局默认值只会初始化新建图层，不会覆盖已有图层的位置和大小。",
            style="Status.TLabel",
            wraplength=360,
        ).grid(row=len(fields), column=0, columnspan=2, sticky="ew", pady=(8, 4))
        frame.columnconfigure(1, weight=1)

        def apply_values(close: bool = False) -> None:
            try:
                layout = layout_from_values(dialog_vars)
            except ValueError as exc:
                messagebox.showerror("布局设置", str(exc))
                return
            self._set_layout_vars(layout)
            self._save_current_config()
            self.status_var.set("全局布局默认值已保存；已有图层未被修改")
            if close:
                window.destroy()

        def reset_defaults() -> None:
            default = EngravingLayout()
            for key in dialog_vars:
                dialog_vars[key].set(str(getattr(default, key)))

        buttons = ttk.Frame(frame)
        buttons.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="恢复默认值", command=reset_defaults).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="应用", command=lambda: apply_values(False)).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="保存", command=lambda: apply_values(True)).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="取消", command=window.destroy).pack(side="left")

    def _set_layout_vars(self, layout: EngravingLayout) -> None:
        """同步全局布局变量；注意不遍历 Document.layers，避免覆盖图层独立几何。"""
        for key in self.layout_vars:
            self.layout_vars[key].set(str(getattr(layout, key)))

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
            filetypes=[("Order Remark", "*.txt *.json *.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            remark = load_order_remark_from_file(Path(path))
        except (OSError, ValueError) as exc:
            messagebox.showerror("导入失败", str(exc))
            return
        self.remark_var.set(" ".join(remark.split()))
        self._set_warnings([])

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
        self.flower_asset_var.set(label)
        self.month_var.set(str(asset.month))
        self.flower_var.set(str(asset.flower))
        if asset.embedded_raster_warnings:
            self._set_warnings(list(asset.embedded_raster_warnings))
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
        remark = self.remark_var.get()
        ai_config = self._current_ai_config()
        self.status_var.set("解析中...")

        def on_error(exc: Exception) -> None:
            self.status_var.set("解析失败")
            messagebox.showerror("解析失败", str(exc))

        run_background(
            self.root,
            lambda: parse_order_remark_auto(remark, ai_config=ai_config),
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
        if result.warnings:
            messagebox.showwarning("无法解析", "\n".join(result.warnings))
        self._redraw_preview()

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
        text = self.name_var.get()
        if index < 0 or index >= len(text):
            messagebox.showerror("字符位置", "请选择当前文字中的有效字符。")
            return
        self.selected_glyph_position = index
        self.status_var.set(f"已选择字符位置：{index}:{text[index]}")
        self._redraw_preview()

    def set_position_glyph_override(self, index: int, override: dict[str, object]) -> None:
        text = self.name_var.get()
        if index < 0 or index >= len(text):
            messagebox.showerror("字形绑定失败", "请选择当前文字中的有效字符。")
            return
        self.current_manual_glyph_override = None
        self.selected_glyph_position = index
        clean_override = dict(override)
        clean_override["original_char"] = text[index]
        self.current_glyph_overrides[index] = clean_override
        codepoint = clean_override.get("codepoint") or "无 Unicode"
        self.status_var.set(f"已绑定位置 {index}:{text[index]} -> {clean_override.get('glyph_name')} ({codepoint})")
        self._redraw_preview()

    def clear_current_position_glyph_override(self) -> None:
        if self.selected_glyph_position is None:
            self.status_var.set("未选择字符位置")
            return
        self.current_glyph_overrides.pop(self.selected_glyph_position, None)
        self.status_var.set(f"已清除位置 {self.selected_glyph_position} 的字形绑定")
        self._redraw_preview()

    def clear_all_position_glyph_overrides(self) -> None:
        self.current_glyph_overrides.clear()
        self.status_var.set("已清除全部按位置字形绑定")
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

    def show_glyph_help(self) -> None:
        messagebox.showinfo(
            "字形使用说明",
            "Font 2 和 Font 4 可启用结尾字形。\n"
            "默认模式会用配置的 PUA 字形替换最后一个英文字母。\n"
            "人工覆盖只影响当前订单；映射绑定会保存到 glyph_maps/glyph_maps.json。\n"
            "SVG 和 DXF 当前仍依赖字体文件显示 PUA 字符，换环境可能显示异常。",
        )

    def _font_design_label(self) -> str:
        try:
            return f"Font {int(self.font_var.get())}"
        except ValueError:
            return self.font_var.get().strip() or "Unknown"

    def _content_text_for_render(self) -> str:
        text = self.name_var.get()
        return text if self.case_sensitive_var.get() else text.lower()

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

        generated_paths: list[Path] = []
        try:
            base_output_path = normalize_output_path(self.output_var.get())
            for output_format in selected_formats:
                target_path = output_path_for_format(base_output_path, output_format)
                if self.document.layers and output_format == "svg":
                    generated_paths.append(render_document_svg(self.document, target_path))
                elif self.document.layers and output_format == "png":
                    generated_paths.append(render_document_png(self.document, target_path))
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
            "locked": layer.locked,
        }
        ratio = (layer.width / layer.height) if layer.height else 1.0
        window = tk.Toplevel(self.root)
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
            "locked": tk.BooleanVar(value=layer.locked),
        }
        geometry_entries: list[ttk.Entry] = []
        fields = (("图层名称", "name"), ("material_id", "material_id"), ("material_name", "material_name"), ("x", "x"), ("y", "y"), ("width", "width"), ("height", "height"))
        for row, (label, key) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
            entry = ttk.Entry(frame, textvariable=vars_map[key], width=24)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            if key in {"x", "y", "width", "height"}:
                geometry_entries.append(entry)
        ttk.Checkbutton(frame, text="锁定宽高比", variable=vars_map["lock_aspect_ratio"]).grid(row=len(fields), column=1, sticky="w", pady=3)
        ttk.Checkbutton(frame, text="是否锁定", variable=vars_map["locked"], command=lambda: sync_entry_state()).grid(row=len(fields) + 1, column=1, sticky="w", pady=3)
        frame.columnconfigure(1, weight=1)
        applying = {"busy": False}

        def sync_entry_state() -> None:
            state = "disabled" if vars_map["locked"].get() else "normal"
            for entry in geometry_entries:
                entry.configure(state=state)

        def apply_live(_name=None, _index=None, _mode=None) -> None:
            if applying["busy"]:
                return
            applying["busy"] = True
            try:
                layer.name = vars_map["name"].get().strip() or snapshot["name"]
                layer.material_id = vars_map["material_id"].get().strip()
                layer.material_name = vars_map["material_name"].get().strip()
                layer.lock_aspect_ratio = bool(vars_map["lock_aspect_ratio"].get())
                layer.locked = bool(vars_map["locked"].get())
                if not layer.locked:
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
                sync_entry_state()
                self._refresh_layers_panel()
                self._redraw_preview()
            except ValueError:
                sync_entry_state()
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
        buttons.grid(row=len(fields) + 2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="确定", command=window.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="取消", command=restore_snapshot).pack(side="left")
        window.protocol("WM_DELETE_WINDOW", restore_snapshot)
        sync_entry_state()

    def _refresh_layers_panel(self) -> None:
        """刷新右下角图层面板，显示名称、类型、显隐和锁定状态。"""
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
            self.layer_text_var.set(layer.text)
            self.layer_font_size_var.set(str(layer.font_size))
            self.layer_color_var.set(layer.color)
        else:
            self.layer_text_var.set("")

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
        layer.text = self.layer_text_var.get()
        try:
            layer.font_size = max(1, int(self.layer_font_size_var.get()))
        except ValueError:
            messagebox.showerror("文本属性", "字号必须是整数")
            return
        layer.color = self.layer_color_var.get().strip() or "#111111"
        # 文本修改后只更新 TextLayer，自身仍可继续编辑并重新渲染。
        self._refresh_layers_panel()
        self._redraw_preview()

    def _nudge_selected_layer(self, dx: int, dy: int) -> None:
        layer = self.document.selected_layer()
        if layer is None or layer.locked:
            return
        layer.x += dx
        layer.y += dy
        self._redraw_preview()

    def _scan_assets(self, show_errors: bool) -> None:
        self.flower_assets = scan_flower_assets(Path(self.flower_dir_var.get()))
        self.font_assets = scan_font_assets(Path(self.font_source_var.get()))
        self.preview_cache.clear()
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
        self.flower_label_map = {self._flower_label(asset): asset for asset in self.flower_assets}
        self.flower_combo.configure(values=list(self.flower_label_map))
        self._select_flower_by_current_fields()
        self._redraw_preview()

    def _refresh_font_choices(self) -> None:
        self.font_label_map = {self._font_label(asset): asset for asset in self.font_assets}
        self.font_combo.configure(values=list(self.font_label_map))
        self._select_font_by_current_field()

    def _on_flower_combo_selected(self) -> None:
        self._add_selected_flower_to_canvas()

    def _add_selected_flower_to_canvas(self) -> None:
        asset = self.flower_label_map.get(self.flower_asset_var.get())
        if asset is None:
            return
        if not asset.path.is_file():
            messagebox.showerror("素材错误", f"素材文件不存在：{asset.path}")
            return
        self.month_var.set(str(asset.month))
        self.flower_var.set(str(asset.flower))
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            layout = EngravingLayout()
        # 添加素材必须追加 ImageLayer，不能覆盖已存在的素材图层。
        layer = add_image_layer(
            self.document,
            asset.path,
            name=asset.display_name or asset.name,
            x=layout.flower_x,
            y=layout.flower_y,
            width=layout.flower_width,
            height=layout.flower_height,
            material_id=asset.asset_key or asset.path.stem,
            material_name=asset.display_name or asset.name,
        )
        self.selected_preview_item = layer.id
        self._refresh_layers_panel()
        self._redraw_preview()

    def _add_text_layer_from_fields(self) -> None:
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            layout = EngravingLayout()
        text = self._content_text_for_render().strip() or "Name"
        layer = add_text_layer(
            self.document,
            text,
            font_path=self._selected_font_path(),
            x=layout.text_x,
            y=layout.text_y,
            width=layout.text_width,
            height=layout.text_height,
            font_size=layout.text_size,
        )
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
            self.flower_asset_var.set(label)

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
        self.config = AppConfig(
            flower_dir=Path(self.flower_dir_var.get()),
            font_source=Path(self.font_source_var.get()),
            output_path=Path(self.output_var.get()),
            output_formats=self._selected_output_formats_or_default(),
            ai_profiles=self.config.ai_profiles,
            active_ai_profile=self.config.active_ai_profile,
            layout_defaults=layout_from_values(self.layout_vars),
        )
        save_config(self.config)

    def _bind_preview_updates(self) -> None:
        for var in self.layout_vars.values():
            var.trace_add("write", lambda *_: self._redraw_preview())
        self.name_var.trace_add("write", lambda *_: self._on_personalization_change())
        self.case_sensitive_var.trace_add("write", lambda *_: self._on_personalization_change())
        self.month_var.trace_add("write", lambda *_: self._on_flower_field_change())
        self.flower_var.trace_add("write", lambda *_: self._on_flower_field_change())
        self.font_var.trace_add("write", lambda *_: self._on_font_field_change())

    def _on_personalization_change(self) -> None:
        self.current_manual_glyph_override = None
        self.current_glyph_overrides.clear()
        self.selected_glyph_position = None
        self._redraw_preview()

    def _on_flower_field_change(self) -> None:
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
            photo = ImageTk.PhotoImage(image)
        except Exception:
            return
        self.preview_text_images.append(photo)
        canvas.create_image(sx(layer.x), sy(layer.y), image=photo, anchor="nw", tags=("layer_art", f"layer:{layer.id}"))

    def _draw_text_layer_preview(self, canvas: tk.Canvas, layer: TextLayer, scale: float, offset_x: float, offset_y: float) -> None:
        """预览文本图层；使用 Pillow 墨迹边界实现真实视觉居中。"""
        if self._draw_ink_aligned_preview_text(
            canvas,
            layer.text,
            layer.x,
            layer.y,
            layer.font_size,
            layer.font_path,
            scale,
            offset_x,
            offset_y,
            SimpleNamespace(left=layer.x, top=layer.y, width=layer.text_box_width, height=layer.text_box_height),
        ):
            return
        canvas.create_text(
            offset_x + layer.x * scale,
            offset_y + layer.y * scale,
            text=layer.text,
            fill=layer.color,
            anchor="nw",
            font=(self._selected_preview_font_family(), max(8, round(layer.font_size * scale))),
            tags=("layer_art", f"layer:{layer.id}"),
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
            photo = ImageTk.PhotoImage(image)
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
            photo = ImageTk.PhotoImage(image)
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

    def _preview_transform(self, layout: EngravingLayout) -> tuple[float, float, float]:
        canvas = self.preview_canvas
        if canvas is None:
            return 1.0, 0.0, 0.0
        canvas_width = max(int(canvas["width"]), canvas.winfo_width())
        canvas_height = max(int(canvas["height"]), canvas.winfo_height())
        scale = min(canvas_width / layout.canvas_width, canvas_height / layout.canvas_height)
        offset_x = (canvas_width - layout.canvas_width * scale) / 2
        offset_y = (canvas_height - layout.canvas_height * scale) / 2
        return scale, offset_x, offset_y

    def _draw_selection_controls(self, canvas: tk.Canvas, layout: EngravingLayout, sx, sy) -> None:
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
            self._start_inline_text_edit(event)

    def _start_inline_text_edit(self, event) -> None:
        canvas = self.preview_canvas
        if canvas is None:
            return
        self._cancel_inline_text_edit()
        entry = ttk.Entry(canvas, textvariable=self.layer_text_var)
        entry.select_range(0, "end")
        entry.bind("<Return>", lambda _event: self._commit_inline_text_edit())
        entry.bind("<FocusOut>", lambda _event: self._commit_inline_text_edit())
        entry.bind("<Escape>", lambda _event: self._cancel_inline_text_edit())
        self.inline_text_entry = entry
        self.inline_text_window = canvas.create_window(event.x, event.y, window=entry, anchor="center", width=220)
        entry.focus_set()

    def _commit_inline_text_edit(self) -> None:
        entry = self.inline_text_entry
        if entry is None:
            return
        layer = self.document.selected_layer()
        if isinstance(layer, TextLayer):
            layer.text = entry.get()
        self._cancel_inline_text_edit()
        self._refresh_layers_panel()
        self._redraw_preview()

    def _cancel_inline_text_edit(self) -> None:
        canvas = self.preview_canvas
        entry = self.inline_text_entry
        self.inline_text_entry = None
        if self.inline_text_window is not None and canvas is not None:
            canvas.delete(self.inline_text_window)
        if entry is not None:
            entry.destroy()
        self.inline_text_window = None

    def _on_canvas_press(self, event) -> None:
        canvas = self.preview_canvas
        if canvas is None:
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

    def _on_canvas_drag(self, event) -> None:
        if self._drag_target is None or self._drag_start is None:
            return
        layer = self.document.layer_by_id(self._drag_target)
        if layer is None or layer.locked:
            return
        try:
            layout = layout_from_values(self.layout_vars)
        except ValueError:
            return
        scale, _offset_x, _offset_y = self._preview_transform(layout)
        dx = (event.x - self._drag_start[0]) / scale
        dy = (event.y - self._drag_start[1]) / scale
        self._drag_start = (event.x, event.y)
        if self._drag_mode == "resize":
            layer.width = max(20, layer.width + dx)
            layer.height = max(20, layer.height + dy)
            if isinstance(layer, TextLayer):
                layer.text_box_width = layer.width
                layer.text_box_height = layer.height
        else:
            layer.x = max(0, layer.x + dx)
            layer.y = max(0, layer.y + dy)
        self._redraw_preview()

    def _on_canvas_release(self, _event) -> None:
        self._drag_target = None
        self._drag_start = None


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


def main() -> None:
    root = tk.Tk()
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
