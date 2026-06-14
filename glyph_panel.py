from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk

from glyph_service import (
    GlyphCandidate,
    GlyphVariant,
    build_glyph_catalog,
    candidate_to_variant,
    filter_glyph_candidates,
    font_contains_codepoint,
    recommended_glyph_variants,
    int_to_codepoint,
    normalize_codepoint,
    codepoint_to_char,
    render_glyph_thumbnail,
    scan_font_glyphs,
)


LETTERS = "abcdefghijklmnopqrstuvwxyz"
PAGE_SIZE = 64
THUMB_SIZE = 72
LOGGER = logging.getLogger(__name__)


def _current_text(app) -> str:
    layer = app.document.selected_layer()
    if getattr(layer, "type", "") == "text" and hasattr(layer, "original_text"):
        return layer.original_text
    return app.name_var.get()


def _current_selected_char(app) -> str:
    text = _current_text(app)
    index = app.selected_glyph_position
    if index is None or index < 0 or index >= len(text):
        return ""
    return text[index]


def open_glyph_panel(app, mapping_only: bool = False) -> tk.Toplevel:
    window = tk.Toplevel(app.root)
    window.title("字形")
    window.transient(app.root)
    window.geometry("920x760")

    selected_letter = tk.StringVar(value=(app.current_glyph_result.source_letter if app.current_glyph_result else "a") or "a")
    selected_codepoint = tk.StringVar(value=(app.current_glyph_result.glyph_codepoint if app.current_glyph_result else "") or "")
    apply_mode = tk.StringVar(value="manual_per_character" if not mapping_only else "replace_last_letter")
    manual_codepoint = tk.StringVar(value=selected_codepoint.get())
    batch_glyphs = tk.StringVar()
    glyph_filter = tk.StringVar(value="推荐字形" if not mapping_only else "All glyphs")
    glyph_search = tk.StringVar()
    page_index = tk.IntVar(value=0)
    state: dict[str, object] = {"images": [], "scan_warning": ""}

    shell = ttk.Frame(window, padding=12)
    shell.pack(fill="both", expand=True)
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(5, weight=1)

    position_host = ttk.Frame(shell)
    position_host.grid(row=3, column=0, sticky="ew", pady=(0, 8))
    grid_host = ttk.Frame(shell)
    grid_host.grid(row=5, column=0, sticky="nsew")
    grid_host.columnconfigure(0, weight=1)
    grid_host.rowconfigure(0, weight=1)

    def refresh_positions() -> None:
        for child in position_host.winfo_children():
            child.destroy()
        if not mapping_only:
            _build_position_picker(app, position_host, refresh_positions)

    def refresh_grid(reset_page: bool = False) -> None:
        if reset_page:
            page_index.set(0)
        for child in grid_host.winfo_children():
            child.destroy()
        _build_glyph_grid(
            app,
            grid_host,
            selected_letter,
            selected_codepoint,
            apply_mode,
            glyph_filter,
            glyph_search,
            page_index,
            state,
            refresh_positions,
            lambda: refresh_grid(),
            mapping_only,
        )

    def change_font_and_refresh() -> None:
        app._on_font_combo_selected()
        refresh_positions()
        refresh_grid(reset_page=True)

    _build_dependency_banner(app, shell)
    _build_header(app, shell, glyph_filter, glyph_search, change_font_and_refresh, lambda: refresh_grid(reset_page=True))
    _build_current_info(app, shell)
    refresh_positions()
    _build_controls(app, shell, selected_letter, selected_codepoint, apply_mode, manual_codepoint, batch_glyphs, mapping_only, refresh_positions)
    refresh_grid()
    trace_id = app.name_var.trace_add("write", lambda *_: (refresh_positions(), refresh_grid(reset_page=True)))
    window.protocol("WM_DELETE_WINDOW", lambda: _close_panel(app, window, trace_id))
    return window


def _close_panel(app, window: tk.Toplevel, trace_id: str) -> None:
    try:
        app.name_var.trace_remove("write", trace_id)
    except tk.TclError:
        pass
    window.destroy()


def _build_dependency_banner(app, parent: ttk.Frame) -> None:
    status = app.runtime_dependency_status
    if status.ok:
        return
    banner = ttk.LabelFrame(parent, text="依赖提示", padding=8)
    banner.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    ttk.Label(banner, text=status.message, wraplength=850, foreground="#9a5b00").pack(anchor="w")


def _build_header(app, parent: ttk.Frame, glyph_filter: tk.StringVar, glyph_search: tk.StringVar, on_font_change, on_refresh) -> None:
    header = ttk.LabelFrame(parent, text="字形", padding=8)
    header.grid(row=1, column=0, sticky="ew", pady=(0, 8))
    header.columnconfigure(1, weight=1)
    header.columnconfigure(3, weight=1)
    font_values = [app._font_label(asset) for asset in app.font_assets] or [app._font_design_label()]
    ttk.Label(header, text="字体").grid(row=0, column=0, sticky="w", pady=3)
    font_combo = ttk.Combobox(header, textvariable=app.font_asset_var, values=font_values, state="readonly")
    font_combo.grid(row=0, column=1, sticky="ew", pady=3)
    font_combo.bind("<<ComboboxSelected>>", lambda _event: on_font_change())
    ttk.Label(header, text="搜索").grid(row=0, column=2, sticky="w", padx=(8, 4), pady=3)
    search_entry = ttk.Entry(header, textvariable=glyph_search)
    search_entry.grid(row=0, column=3, sticky="ew", pady=3)
    search_entry.bind("<KeyRelease>", lambda _event: on_refresh())

    ttk.Label(header, text="筛选").grid(row=1, column=0, sticky="w", pady=3)
    filter_combo = ttk.Combobox(
        header,
        textvariable=glyph_filter,
        values=("All glyphs", "Unicode mapped", "PUA only", "Unmapped glyphs"),
        state="readonly",
    )
    filter_combo.grid(row=1, column=1, sticky="ew", pady=3)
    filter_combo.bind("<<ComboboxSelected>>", lambda _event: on_refresh())
    ttk.Button(header, text="刷新", command=on_refresh).grid(row=1, column=3, sticky="e", pady=3)
    ttk.Label(header, text="样式").grid(row=2, column=0, sticky="w", pady=3)
    style_combo = ttk.Combobox(header, values=("Regular",), state="readonly")
    style_combo.set("Regular")
    style_combo.grid(row=2, column=1, sticky="w", pady=3)


def _build_current_info(app, parent: ttk.Frame) -> None:
    info = ttk.Frame(parent)
    info.grid(row=2, column=0, sticky="ew", pady=(0, 8))
    info.columnconfigure(1, weight=1)
    result = app.current_glyph_result
    values = (
        ("当前", f"{app._font_design_label()} | {_current_text(app) or '-'}"),
        ("状态", _source_label(result.glyph_source if result else "")),
        ("识别字母", result.source_letter if result and result.source_letter else "-"),
        ("字形码位", result.glyph_codepoint if result and result.glyph_codepoint else "-"),
        ("应用方式", _mode_label(result.apply_mode if result else "")),
        ("提醒", result.reason if result and result.reason else "-"),
    )
    for row, (label, value) in enumerate(values):
        ttk.Label(info, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Label(info, text=value, wraplength=760).grid(row=row, column=1, sticky="w", pady=2)


def _build_position_picker(app, parent: ttk.Frame, on_change) -> None:
    group = ttk.LabelFrame(parent, text="按文字位置替换", padding=8)
    group.pack(fill="x")
    text = _current_text(app)
    if not text:
        ttk.Label(group, text="请先输入 personalization 文字。").pack(anchor="w")
        return
    for index, char in enumerate(text):
        bound = index in app.current_glyph_overrides
        selected = app.selected_glyph_position == index
        label = f"{'>' if selected else ''}[{index}:{char}]{'*' if bound else ''}"
        ttk.Button(group, text=label, width=max(6, len(label)), command=lambda i=index: _select_position(app, i, on_change)).pack(
            side="left",
            padx=2,
            pady=2,
        )


def _select_position(app, index: int, on_change) -> None:
    app.select_glyph_position(index)
    on_change()


def _build_controls(
    app,
    parent: ttk.Frame,
    selected_letter: tk.StringVar,
    selected_codepoint: tk.StringVar,
    apply_mode: tk.StringVar,
    manual_codepoint: tk.StringVar,
    batch_glyphs: tk.StringVar,
    mapping_only: bool,
    refresh_positions,
) -> None:
    controls = ttk.LabelFrame(parent, text="绑定与覆盖", padding=8)
    controls.grid(row=4, column=0, sticky="ew", pady=(0, 8))
    controls.columnconfigure(1, weight=1)

    ttk.Label(controls, text="应用方式").grid(row=0, column=0, sticky="w", pady=3)
    ttk.Combobox(
        controls,
        textvariable=apply_mode,
        values=("manual_per_character", "replace_last_letter", "append_suffix"),
        state="readonly",
        width=24,
    ).grid(row=0, column=1, sticky="w", pady=3)
    ttk.Label(controls, text="映射字母").grid(row=0, column=2, sticky="w", padx=(8, 4), pady=3)
    ttk.Combobox(controls, textvariable=selected_letter, values=tuple(LETTERS), state="readonly", width=5).grid(
        row=0,
        column=3,
        sticky="w",
        pady=3,
    )
    ttk.Label(controls, text="手动 codepoint").grid(row=1, column=0, sticky="w", pady=3)
    ttk.Entry(controls, textvariable=manual_codepoint).grid(row=1, column=1, columnspan=2, sticky="ew", pady=3)
    ttk.Button(
        controls,
        text="使用输入码位",
        command=lambda: _use_manual_codepoint(app, manual_codepoint, selected_codepoint),
    ).grid(row=1, column=3, padx=(8, 0), pady=3)

    ttk.Label(controls, text="批量 26 字形").grid(row=2, column=0, sticky="w", pady=3)
    ttk.Entry(controls, textvariable=batch_glyphs).grid(row=2, column=1, columnspan=2, sticky="ew", pady=3)
    ttk.Button(controls, text="按 a-z 绑定", command=lambda: _bind_batch(app, batch_glyphs)).grid(row=2, column=3, padx=(8, 0), pady=3)

    ttk.Button(controls, text="绑定到映射字母", command=lambda: _bind_selected(app, selected_letter.get(), selected_codepoint.get())).grid(
        row=3,
        column=0,
        pady=(6, 0),
        sticky="w",
    )
    if not mapping_only:
        ttk.Button(
            controls,
            text="清除当前字符绑定",
            command=lambda: (app.clear_current_position_glyph_override(), refresh_positions()),
        ).grid(row=3, column=1, pady=(6, 0), sticky="w")
        ttk.Button(
            controls,
            text="清除全部绑定",
            command=lambda: (app.clear_all_position_glyph_overrides(), refresh_positions()),
        ).grid(row=3, column=2, pady=(6, 0), sticky="w")
        ttk.Button(controls, text="清除人工选择", command=lambda: (app.clear_manual_glyph_selection(), refresh_positions())).grid(
            row=3,
            column=3,
            pady=(6, 0),
            sticky="e",
        )


def _build_glyph_grid(
    app,
    parent: ttk.Frame,
    selected_letter: tk.StringVar,
    selected_codepoint: tk.StringVar,
    apply_mode: tk.StringVar,
    glyph_filter: tk.StringVar,
    glyph_search: tk.StringVar,
    page_index: tk.IntVar,
    state: dict[str, object],
    refresh_positions,
    on_page_change,
    mapping_only: bool,
) -> None:
    group = ttk.LabelFrame(parent, text="字形网格", padding=8)
    group.grid(row=0, column=0, sticky="nsew")
    group.columnconfigure(0, weight=1)
    group.rowconfigure(1, weight=1)
    pager = ttk.Frame(group)
    pager.grid(row=0, column=0, sticky="ew", pady=(0, 6))

    canvas = tk.Canvas(group, height=330, highlightthickness=0)
    scrollbar = ttk.Scrollbar(group, orient="vertical", command=canvas.yview)
    grid = ttk.Frame(canvas)
    grid.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=grid, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.grid(row=1, column=0, sticky="nsew")
    scrollbar.grid(row=1, column=1, sticky="ns")

    font_path = app._selected_font_path()
    if font_path is None:
        ttk.Label(grid, text="未选择字体文件。").grid(row=0, column=0, sticky="w")
        return
    try:
        all_candidates = scan_font_glyphs(font_path, pua_only=False)
    except (RuntimeError, ValueError) as exc:
        ttk.Label(grid, text=f"字体加载失败：{font_path}\n{exc}", wraplength=850).grid(row=0, column=0, sticky="w")
        LOGGER.exception("字体扫描失败：font_path=%s", font_path)
        if state.get("scan_warning") != str(exc):
            state["scan_warning"] = str(exc)
            messagebox.showerror("字体扫描失败", str(exc))
        return

    if glyph_filter.get() == "推荐字形":
        current_char = _current_selected_char(app)
        try:
            catalog = build_glyph_catalog(font_path, app._font_design_label(), app.glyph_bindings)
            variants = recommended_glyph_variants(catalog, current_char)
            variant_codes = {variant.codepoint for variant in variants if variant.codepoint}
            candidates = [candidate for candidate in all_candidates if (candidate.unicode or "").replace("U+", "").upper() in variant_codes]
        except Exception as exc:
            LOGGER.exception("推荐字形构建失败：font_path=%s char=%s", font_path, current_char)
            ttk.Label(grid, text=f"推荐字形加载失败：{exc}", wraplength=850).grid(row=0, column=0, sticky="w")
            return
        if not current_char or not candidates:
            ttk.Label(grid, text="当前字符暂无已识别的替代字形，可切换到全部字形或手动绑定。", wraplength=850).grid(row=0, column=0, sticky="w")
            return
    else:
        candidates = filter_glyph_candidates(all_candidates, glyph_search.get(), glyph_filter.get())
    page_count = max(1, (len(candidates) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page_index.get(), page_count - 1))
    page_index.set(page)
    ttk.Button(pager, text="上一页", command=lambda: _page_to(page_index, page - 1, on_page_change)).pack(side="left")
    ttk.Label(pager, text=f"{page + 1}/{page_count} | {len(candidates)} glyphs").pack(side="left", padx=8)
    ttk.Button(pager, text="下一页", command=lambda: _page_to(page_index, page + 1, on_page_change)).pack(side="left")

    state["images"] = []
    start = page * PAGE_SIZE
    for index, candidate in enumerate(candidates[start : start + PAGE_SIZE]):
        cell = ttk.Frame(grid, padding=3)
        cell.grid(row=index // 8, column=index % 8, padx=3, pady=4, sticky="n")
        photo = _photo_image(font_path, candidate)
        if photo is not None:
            state["images"].append(photo)
            button = ttk.Button(
                cell,
                image=photo,
                command=lambda glyph=candidate: _select_grid_glyph(
                    app,
                    selected_letter,
                    selected_codepoint,
                    apply_mode,
                    glyph,
                    refresh_positions,
                    mapping_only,
                ),
            )
        else:
            button = ttk.Button(
                cell,
                text=candidate.char or "□",
                width=8,
                command=lambda glyph=candidate: _select_grid_glyph(
                    app,
                    selected_letter,
                    selected_codepoint,
                    apply_mode,
                    glyph,
                    refresh_positions,
                    mapping_only,
                ),
            )
        button.pack()
        codepoint = candidate.unicode or "unmapped"
        if not candidate.is_mapped:
            codepoint += "\n可预览/不导出"
        ttk.Label(cell, text=f"{candidate.glyph_name}\n{codepoint}", wraplength=92, justify="center").pack()


def _page_to(page_index: tk.IntVar, value: int, on_page_change) -> None:
    page_index.set(max(0, value))
    on_page_change()


def _photo_image(font_path, candidate: GlyphCandidate):
    try:
        from PIL import ImageTk
    except ImportError:
        return None

    try:
        image = render_glyph_thumbnail(font_path, candidate, image_size=THUMB_SIZE, font_size=56)
        return ImageTk.PhotoImage(image)
    except Exception as exc:
        if "字形功能缺少运行依赖" in str(exc):
            return None
        LOGGER.warning("glyph thumbnail failed: %s %s", candidate.glyph_name, exc)
        return None


def _select_grid_glyph(
    app,
    selected_letter: tk.StringVar,
    selected_codepoint: tk.StringVar,
    apply_mode: tk.StringVar,
    glyph: GlyphCandidate,
    refresh_positions,
    mapping_only: bool,
) -> None:
    if glyph.unicode:
        selected_codepoint.set(glyph.unicode)
    if not mapping_only and apply_mode.get() == "manual_per_character":
        if app.selected_glyph_position is None:
            messagebox.showwarning("字形绑定", "请先点击 personalization 中的字符位置。")
            return
        text = _current_text(app)
        index = app.selected_glyph_position
        if index < 0 or index >= len(text):
            messagebox.showerror("字形绑定失败", "当前字符位置已失效，请重新选择。")
            return
        variant = candidate_to_variant(glyph, font_id=app._font_design_label(), font_path=app._selected_font_path(), base_char=text[index])
        app.apply_glyph_variant_to_current_text(variant)
        refresh_positions()
        return
    if not glyph.unicode:
        messagebox.showwarning("字形绑定", "该 glyph 没有 Unicode codepoint，只能用于按位置 PNG 预览，暂不支持映射导出。")
        return
    app.set_manual_glyph_override(selected_letter.get() or "a", glyph.unicode, apply_mode.get())


def _use_manual_codepoint(app, manual_codepoint: tk.StringVar, selected_codepoint: tk.StringVar) -> None:
    try:
        codepoint = normalize_codepoint(manual_codepoint.get())
        codepoint_to_char(codepoint)
        _warn_if_codepoint_unverified(app, codepoint)
    except (RuntimeError, ValueError) as exc:
        messagebox.showerror("字形码位", str(exc))
        return
    selected_codepoint.set(codepoint)
    app.status_var.set(f"已选择字形码位：{codepoint}")


def _bind_selected(app, letter: str, codepoint: str) -> None:
    try:
        clean_codepoint = normalize_codepoint(codepoint)
        codepoint_to_char(clean_codepoint)
        _warn_if_codepoint_unverified(app, clean_codepoint)
        app.glyph_config.set_glyph_for_letter(app._font_design_label(), letter, clean_codepoint, f"{letter} ending glyph")
        app.glyph_config.save()
        font_path = app._selected_font_path()
        if font_path is not None:
            variant = GlyphVariant.from_mapping(
                {
                    "base_char": letter,
                    "codepoint": clean_codepoint,
                    "glyph_name": f"uni{clean_codepoint.replace('U+', '')}",
                    "font_id": app._font_design_label(),
                    "font_path": str(font_path),
                    "display_name": f"{letter} ending glyph",
                    "usage": "end",
                    "source": "manual_binding",
                }
            )
            app.glyph_bindings.set_binding(app._font_design_label(), font_path, variant, letter, "end", f"{letter} ending glyph")
            app.glyph_bindings.save()
    except (RuntimeError, ValueError) as exc:
        messagebox.showerror("字形绑定失败", str(exc))
        return
    app.status_var.set(f"已绑定 {letter} -> {clean_codepoint}")
    app.reidentify_glyph()


def _bind_batch(app, batch_glyphs: tk.StringVar) -> None:
    glyphs = list(batch_glyphs.get())
    if len(glyphs) != 26:
        messagebox.showerror("批量绑定失败", "请按 a-z 顺序粘贴 26 个字形字符。")
        return
    try:
        for letter, glyph in zip(LETTERS, glyphs, strict=True):
            codepoint = int_to_codepoint(ord(glyph))
            codepoint_to_char(codepoint)
            app.glyph_config.set_glyph_for_letter(app._font_design_label(), letter, codepoint, f"{letter} ending glyph")
        app.glyph_config.save()
    except ValueError as exc:
        messagebox.showerror("批量绑定失败", str(exc))
        return
    app.status_var.set("已按 a-z 绑定 26 个字形。")
    app.reidentify_glyph()


def _warn_if_codepoint_unverified(app, codepoint: str) -> None:
    font_path = app._selected_font_path()
    if font_path is None:
        return
    try:
        if not font_contains_codepoint(font_path, codepoint):
            raise ValueError(f"{codepoint} 不在当前字体 cmap 中。")
    except RuntimeError as exc:
        messagebox.showwarning("字形码位未校验", str(exc))


def _mode_label(value: str) -> str:
    return {
        "replace_last_letter": "替换最后字母",
        "append_suffix": "追加后缀",
        "manual_per_character": "按位置手动替换",
    }.get(value, value or "-")


def _source_label(value: str) -> str:
    return {"auto": "自动", "manual": "人工", "none": "未应用"}.get(value, value or "未启用")
