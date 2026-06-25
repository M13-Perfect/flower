import threading
import tkinter as tk
from tkinter import ttk
from pathlib import Path

import customtkinter as ctk
from types import SimpleNamespace

import pytest

from config_store import AIProfile, active_product
from generation_readiness import GenerationReadiness
from glyph_service import GlyphApplyResult, GlyphVariant
from models import Document, FlowerAsset, FontAsset, ImageLayer, ParseResult, TextLayer, add_image_layer, add_text_layer
import ui_app as ui_app_module
from ui_app import (
    APP_COLORS,
    BirthFlowerApp,
    ENTRY_ROLE_META,
    IMPORTABLE_ASSET_SUFFIXES,
    IMPORTABLE_FONT_SUFFIXES,
    VIEW_ADMIN,
    VIEW_OPERATOR,
    VIEW_OPERATOR_CONFIG,
    view_cards_for_role,
    order_row_view,
    target_box_piece_count,
    mark_status_style,
    ai_status_style,
    shop_status_style,
    _short_dt,
    _blend_hex,
    _preview_text_ink_image,
    _ttf_family_name,
    build_ai_profile_from_settings,
    build_ai_parse_config,
    build_design_from_values,
    build_readiness_parse_result_from_values,
    collect_importable_files,
    _paths_equal,
    dxf_path_for_svg,
    format_font_asset_label,
    format_glyph_detail,
    format_readiness_summary,
    layout_from_values,
    output_path_for_format,
    run_background,
    sanitize_filename_stem,
    validate_output_formats,
)


class FakeRoot:
    def __init__(self):
        self.callbacks = []

    def after(self, delay, callback):
        self.callbacks.append((delay, callback))


def test_view_cards_for_role_splits_three_ends():
    # 三端↔卡片映射的回归护栏：提示词类卡片(②/字段/背景)只在管理员端；生成/图层只在操作员端；
    # 资源库只在配置端；订单信息/解析结果(①③)在操作员与管理员两端共用。
    # 2026-06-19 改：配置端不编辑、只监控调度+订单，故中心区换成订单表，不再挂「画布/图层」(production)。
    operator = view_cards_for_role(VIEW_OPERATOR)
    admin = view_cards_for_role(VIEW_ADMIN)
    config = view_cards_for_role(VIEW_OPERATOR_CONFIG)

    assert operator == ["order", "result", "production", "output"]
    assert admin == ["order", "result", "production", "fields", "background", "prompt_obs", "output"]
    assert config == ["fetch", "library"]
    # 红线：②提示词全文/字段规则/背景词不进操作员端（IP 归管理员端）。
    for ip_card in ("prompt_obs", "fields", "background"):
        assert ip_card not in operator
    # 「画布/图层」(production) 只对操作员/管理员两端开放；配置端无画板（中心区是订单表）。
    assert "production" in operator and "production" in admin
    assert "production" not in config
    # 输出（输出设置+生成）在操作员、管理员两端都有；配置端不放输出。资源库只在配置端。
    assert "output" in operator and "output" in admin and "output" not in config
    assert "library" not in operator and "library" not in admin
    # 「抓取订单」面板只在操作员配置端。
    assert "fetch" in config and "fetch" not in operator and "fetch" not in admin
    # 未知端回退操作员端，绝不空。
    assert view_cards_for_role("bogus") == operator


def test_short_dt_compacts_iso_and_handles_empty():
    assert _short_dt("2026-06-19T02:25:00+00:00") == "06-19 02:25"
    assert _short_dt("2026-06-19T02:25") == "06-19 02:25"
    assert _short_dt(None) == "—"
    assert _short_dt("") == "—"


def test_shop_status_style_classifies_by_keyword():
    # 状态列=店小秘订单状态原文，按退款拦截口径上色。
    assert shop_status_style("已退款")[0] == "已退款" and shop_status_style("已退款")[1] == "#3d2422"  # 退款=红
    assert shop_status_style("取消不发货")[1] == "#3d2422"  # 取消=红
    assert shop_status_style("风控中")[1] == "#3d3220"  # 风控=黄
    assert shop_status_style("已审核")[1] == "#1f3d2c"  # 正常=绿
    assert shop_status_style("已发货")[1] == "#1f3d2c"
    assert shop_status_style("已忽略")[1] == "#2c3036"  # 忽略=灰
    assert shop_status_style("")[0] == "未抓取" and shop_status_style("")[1] == "#2c3036"  # 未抓到=灰


def test_order_row_view_status_is_shop_status_not_internal():
    # 状态列=店小秘订单状态(refund_status)；内部 status 只进 internal_label，不当主状态。
    order = {
        "order_id": "DX001",
        "status": "CANNOT_AUTOGEN",      # 内部状态
        "refund_status": "已审核",        # 店小秘状态
        "paid_at": "2026-06-19T02:31:00+00:00",
        "received_at": "2026-06-19T02:40:00+00:00",
        "items": [
            {"quantity": 2, "is_target_box": True},
            {"quantity": 1, "is_target_box": True},
            {"quantity": 5, "is_target_box": False},  # 其他商品
        ],
    }
    row = order_row_view(order)
    assert row["order_id"] == "DX001"
    assert row["status_label"] == "已审核"     # 主状态=店小秘状态，不是内部的"人工审核"
    assert row["status_bg"] == "#1f3d2c"       # 已审核=绿
    assert row["shop_status"] == "已审核"
    assert row["internal_label"] == "人工审核"  # 内部 CANNOT_AUTOGEN → 详情用
    assert row["quantity"] == 8  # 2+1+5
    assert row["has_other_products"] is True
    assert row["paid_at"] == "06-19 02:31"  # 用 paid_at 而非 received_at
    assert "refund" not in row  # 不再有独立"退款"字段/列


def test_order_row_view_refunded_shop_status_and_empty_items():
    # items 空（扩展只抓列表页）→ 件数 0（UI 显 —）；店小秘已退款→红；内部未知状态原样进 internal_label。
    order = {
        "order_id": "DX002",
        "status": "WEIRD_STATE",
        "refund_status": "已退款",
        "received_at": "2026-06-19T03:00:00+00:00",
        "items": [],
    }
    row = order_row_view(order)
    assert row["quantity"] == 0
    assert row["has_other_products"] is False
    assert row["status_label"] == "已退款"
    assert row["status_bg"] == "#3d2422"        # 退款=红（生产拦截信号）
    assert row["internal_label"] == "WEIRD_STATE"  # 未知内部状态原样
    assert row["paid_at"] == "06-19 03:00"  # 无 paid_at → 回退 received_at


def test_format_scrape_status_reflects_connection_and_switch():
    # 抓取面板状态文案：服务连接 + 自动抓开关态 + 授权态（任务租约）+ 订单范围 + 当前单。
    base = "http://127.0.0.1:8770"
    on = BirthFlowerApp._format_scrape_status(
        True, base,
        {"enabled": True, "authorized": True, "interval_seconds": 300, "scrape_from": "2026-06-19 02:25"},
        "4090627965",
    )
    assert "已连接" in on and base in on and "自动抓：开" in on and "300s" in on
    assert "授权 是" in on and "2026-06-19 02:25" in on and "4090627965" in on
    # 开关「开」但授权「否」（任务过期/未心跳，如 flower 异常退出残留）→ 文案提示授权 否。
    stale = BirthFlowerApp._format_scrape_status(
        True, base, {"enabled": True, "authorized": False, "interval_seconds": 300, "scrape_from": None}, None
    )
    assert "自动抓：开" in stale and "授权 否" in stale
    off = BirthFlowerApp._format_scrape_status(
        True, base, {"enabled": False, "authorized": False, "interval_seconds": 60, "scrape_from": None}, None
    )
    assert "自动抓：关" in off and "授权 否" in off and "当前单：—" in off
    # 服务未连接：提示未连接 + 地址，不读开关。
    down = BirthFlowerApp._format_scrape_status(False, base, None, None)
    assert "未连接" in down and base in down


def test_scrape_switch_state_maps_connection_to_clickable_and_checked():
    # 自动抓实时开关：未探活/未连接/状态未知 → 不可点且不勾；已知 → 勾选=enabled、可点。
    assert BirthFlowerApp._scrape_switch_state(False, False, None) == (False, False)  # 未探活
    assert BirthFlowerApp._scrape_switch_state(True, False, None) == (False, False)  # 已探活但未连接
    assert BirthFlowerApp._scrape_switch_state(True, True, None) == (False, False)   # 连上但开关态未知
    assert BirthFlowerApp._scrape_switch_state(True, True, {"enabled": True}) == (True, True)
    assert BirthFlowerApp._scrape_switch_state(True, True, {"enabled": False}) == (False, True)


def _make_order(order_id, *, refund="已审核", qty=1):
    return {
        "order_id": order_id, "refund_status": refund, "paid_at": "2026-06-20 01:00",
        "items": [{"quantity": qty, "is_target_box": True}], "mark_jobs": None,
    }


def test_orders_table_renders_incrementally_and_deletes_one_row_locally():
    # 阶段三护栏：Treeview 增量渲染（iid=order_id）——删消失行、建新增行、存活行原位更新值；本地删行只删那一行。
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")
    try:
        app = BirthFlowerApp(root)
        app._render_orders_rows([_make_order("A"), _make_order("B"), _make_order("C")])
        assert set(app.orders_tree.get_children("")) == {"A", "B", "C"}
        assert set(app._orders_data) == {"A", "B", "C"}
        # 再渲染：去掉 B、改 A 的店小秘状态 → A/C 复用(iid 还在)、B 删除、A 状态原位更新。
        app._render_orders_rows([_make_order("A", refund="已退款"), _make_order("C")])
        assert set(app.orders_tree.get_children("")) == {"A", "C"}
        assert not app.orders_tree.exists("B")                      # 消失行已删
        assert shop_status_style("已退款")[0] in app.orders_tree.item("A", "values")  # 值原位更新
        assert app.orders_tree.item("A", "tags") == ("refund",)    # 退款 → 整行红 tag
        # 本地删行：删 A → 只剩 C，不触网/不整表重拉。
        app._remove_order_row_local("A")
        assert set(app.orders_tree.get_children("")) == {"C"}
        assert "A" not in app._orders_data
    finally:
        root.destroy()


def test_format_parse_result_renders_structured_summary():
    result = ParseResult(
        text="Amy", font=4, flower_name="Narcissus",
        order_number="4090627965", quantity=2, confidence=0.97,
    )
    summary = BirthFlowerApp._format_parse_result(result, 0, 3)
    assert "第 1/3 单" in summary          # 多单时带序号
    assert "4090627965" in summary
    assert "Amy" in summary
    assert "0.97" in summary
    # 异常/缺失：警告以 ⚠ 前缀显示；None 结果不炸。
    warned = BirthFlowerApp._format_parse_result(
        ParseResult(text="", warnings=["件数与定制数不一致"]), 0, 1
    )
    assert "⚠" in warned and "件数与定制数不一致" in warned
    assert BirthFlowerApp._format_parse_result(None, 0, 0) == "（未识别到订单）"


def test_parse_result_can_create_layers_uses_live_fields():
    can = BirthFlowerApp._parse_result_can_create_layers
    # 完整单（text+font+flower_name）→ 解析后自动替换图层。
    assert can(None, ParseResult(text="Amy", font=4, flower_name="Narcissus"))
    assert can(None, ParseResult(text="Amy", font=4, material_key="narcissus"))
    # 缺花/缺字/缺文字/有警告 → 不自动建层。
    assert not can(None, ParseResult(text="Amy", font=4))
    assert not can(None, ParseResult(text="Amy", flower_name="Narcissus"))
    assert not can(None, ParseResult(text="", font=4, flower_name="Narcissus"))
    assert not can(None, ParseResult(text="Amy", font=4, flower_name="Narcissus", warnings=["x"]))


def test_build_design_from_manual_values_accepts_user_edits():
    design = build_design_from_values(" Iris ", "4", "3", "2", "flowers/DaisyApril.svg", "font.ttf", "Daisy")

    assert design.text == "Iris"
    assert design.month == 4
    assert design.font == 3
    assert design.flower == 2
    assert design.flower_asset_path == Path("flowers/DaisyApril.svg")
    assert design.font_path == Path("font.ttf")
    assert design.flower_name == "Daisy"


def test_sanitize_filename_stem_strips_illegal_and_trailing():
    assert sanitize_filename_stem("a/b:c*?.svg") == "abc.svg"
    assert sanitize_filename_stem("  order  ") == "order"
    assert sanitize_filename_stem("name. ") == "name"
    assert sanitize_filename_stem("") == ""
    assert sanitize_filename_stem(None) == ""
    # 保留设备名前缀下划线避让（大小写不敏感）。
    assert sanitize_filename_stem("CON") == "_CON"
    assert sanitize_filename_stem("nul") == "_nul"


def _bind_piece_methods(fake):
    """给 SimpleNamespace 桩绑定一单多件后缀相关的真方法，并补它们读取的默认属性（默认=单件，零后缀）。"""
    for name in ("_with_piece_suffix", "_piece_index_total", "_update_piece_filename"):
        setattr(fake, name, getattr(BirthFlowerApp, name).__get__(fake))
    for name, default in (("parsed_orders", []), ("_parsed_order_index", 0), ("_db_order_piece_count", 0)):
        if not hasattr(fake, name):
            setattr(fake, name, default)
    return fake


def _fake_filename_app(typed="", order_no="", db_order=None, inbox=None):
    """只喂 _resolve_output_basename 用到的属性，免去构建整套 UI（headless 易碎）。"""
    return _bind_piece_methods(SimpleNamespace(
        filename_template_var=SimpleNamespace(get=lambda: typed),
        current_order_number=order_no,
        _db_order_active_id=db_order,
        _inbox_active=inbox,
    ))


def test_resolve_output_basename_priority():
    resolve = BirthFlowerApp._resolve_output_basename
    base = Path("C:/out/原始名.svg")
    # 1) 「文件名」框非空 → 纯文本所见即所得（清洗后）。
    assert resolve(_fake_filename_app(typed="贺卡A"), base) == "贺卡A"
    assert resolve(_fake_filename_app(typed="a/b:c"), base) == "abc"
    # 2) 框留空 → 解析到的订单号优先。
    assert resolve(_fake_filename_app(order_no="29972194015"), base) == "29972194015"
    # 3) 框空且无解析订单号 → 回退库驱动载单的订单号。
    assert resolve(_fake_filename_app(db_order="4091090394"), base) == "4091090394"
    # 4) 再回退 inbox 收件夹 JSON 文件名 stem。
    assert resolve(_fake_filename_app(inbox=Path("inbox/2997.json")), base) == "2997"
    # 5) 全空 → 回退「输出目录」原文件名（旧行为），名字永不为空。
    assert resolve(_fake_filename_app(), base) == "原始名"


def _fake_db_load_app(*, autoparse: bool):
    """喂 _load_db_order 用到的最小桩：捕获 remark/文件名/状态/订单号 + 记录是否触发解析。"""
    captured: dict = {"parse_called": False, "warnings_cleared": False}
    box = _FakeVar("")
    box.set = lambda v, _box=box: (_FakeVar.set(_box, v), captured.update(filename=v))[0]  # 既写值又记录
    fake = SimpleNamespace(
        current_order_number="",
        _db_order_active_id=None,
        filename_template_var=box,
        status_var=SimpleNamespace(set=lambda v: captured.update(status=v)),
        config=SimpleNamespace(inbox_autoparse=autoparse),
        _set_remark_text=lambda v: captured.update(remark=v),
        _set_warnings=lambda v: captured.update(warnings_cleared=(v == [])),
        _refresh_fetch_status=lambda: captured.update(fetch_refreshed=True),
        parse_remark=lambda: captured.update(parse_called=True),
    )
    return _bind_piece_methods(fake), captured


def test_load_db_order_populates_box_filename_and_active_id():
    # 库订单 dict → 订单信息框首行=订单号、其后接备注；文件名框=订单号；记当前订单号 + 队首守卫 id。
    fake, captured = _fake_db_load_app(autoparse=False)
    order = {"order_id": "4091090394", "remark": "Jun - Rose / Patty", "items": []}
    BirthFlowerApp._load_db_order(fake, order)
    assert captured["remark"] == "4091090394\nJun - Rose / Patty"
    assert captured["filename"] == "4091090394"
    assert fake.current_order_number == "4091090394"
    assert fake._db_order_active_id == "4091090394"
    assert captured["warnings_cleared"] is True
    assert captured["parse_called"] is False  # 自动识别关 → 只载入不解析


def test_load_db_order_autoparses_when_enabled():
    fake, captured = _fake_db_load_app(autoparse=True)
    BirthFlowerApp._load_db_order(fake, {"order_id": "X1", "remark": "", "items": [{"personalization_raw": "Amy"}]})
    assert captured["remark"] == "X1\nAmy"  # 空 remark 回退 items[].personalization_raw
    assert captured["parse_called"] is True  # 自动识别开 → 载入即解析（绝不自动生成）


def test_build_design_from_manual_values_accepts_extended_asset_and_font_indexes_when_paths_exist():
    design = build_design_from_values(
        " Iris ",
        "4",
        "8",
        "12",
        "flowers/CustomAsset.svg",
        "fonts/CustomFont.ttf",
        "Custom Asset",
    )

    assert design.font == 8
    assert design.flower == 12
    assert design.flower_asset_path == Path("flowers/CustomAsset.svg")
    assert design.font_path == Path("fonts/CustomFont.ttf")


def test_build_design_from_manual_values_rejects_invalid_manual_edits():
    with pytest.raises(ValueError):
        build_design_from_values("Iris", "13", "1", "1")


def test_build_readiness_parse_result_from_manual_values_lowers_asset_confidence_for_missing_assets():
    result = build_readiness_parse_result_from_values("Iris", "2", None, None, "unknown", "name")

    assert result.parse_confidence == 1.0
    assert result.asset_confidence < 1.0
    assert "Missing flower asset" in result.warnings
    assert "Missing font asset" in result.warnings


def test_dxf_path_for_svg_reuses_output_stem():
    assert dxf_path_for_svg(Path("outputs/result.svg")) == Path("outputs/result.dxf")


def test_layout_from_values_parses_numeric_layout_fields():
    layout = layout_from_values(
        {
            "canvas_width": "1372",
            "canvas_height": "1280",
            "flower_x": "310",
            "flower_y": "40",
            "flower_width": "1060",
            "flower_height": "1060",
            "text_x": "1210",
            "text_y": "1090",
            "text_width": "804",
            "text_height": "260",
            "text_size": "190",
        }
    )

    assert layout.canvas_width == 1372
    assert layout.canvas_height == 1280
    assert layout.flower_width == 1060
    assert layout.text_width == 804
    assert layout.text_height == 260
    assert layout.text_size == 190


def test_preview_text_ink_image_is_cropped_to_visible_black_pixels():
    result = _preview_text_ink_image("gyjpq", 64, None)

    assert result is not None
    image, offset_left, offset_top = result
    assert image.width > 0
    assert image.height > 0
    assert image.getbbox() == (0, 0, image.width, image.height)
    assert isinstance(offset_left, float)
    assert isinstance(offset_top, float)


def test_preview_text_fill_image_resizes_black_ink_to_target_box():
    result = ui_app_module._preview_text_fill_image("Hi", 64, None, 240, 80)

    assert result is not None
    image = result
    assert image.size == (240, 80)
    assert image.getbbox() == (0, 0, 240, 80)


def test_ttf_family_name_reads_birthmonth_font_family():
    font_path = Path("Birthmonth_font.ttf")
    if not font_path.is_file():
        pytest.skip("Optional business font asset is not present")

    assert _ttf_family_name(font_path) == "birthmonth by hannah"


def test_output_path_for_format_reuses_output_stem():
    assert output_path_for_format(Path("outputs/result.svg"), "svg") == Path("outputs/result.svg")
    assert output_path_for_format(Path("outputs/result.svg"), "dxf") == Path("outputs/result.dxf")
    assert output_path_for_format(Path("outputs/result.svg"), "png") == Path("outputs/result.png")


def test_validate_output_formats_requires_at_least_one_format():
    with pytest.raises(ValueError):
        validate_output_formats([])

    assert validate_output_formats(["svg", "bad", "png", "svg"]) == ("svg", "png")


def test_birth_flower_app_initializes_desktop_ui_state():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        assert root.title() == "Birth Flower MVP"
        assert len(app._menus) == 4  # 顶栏 CTk 菜单（已弃用原生菜单栏白条）
        assert set(APP_COLORS) >= {"background", "panel", "border", "text", "muted", "warning"}
        assert app.remark_text is None or isinstance(app.remark_text, (tk.Text, ctk.CTkTextbox))
        assert app.remark_text is not None
        assert int(app.remark_text.cget("height")) > 0
        assert app.confirm_button is None or hasattr(app.confirm_button, "invoke")
        assert isinstance(app.section_frames, dict)
        assert set(app.section_frames) >= {
            "preview_panel",
            "function_panel",
            "order_panel",
            "production_panel",
        }
        assert hasattr(app, "current_glyph_result")
        assert root.minsize() == (760, 560)
        assert app.preview_canvas is not None
        assert app.preview_canvas.bind("<Button-1>")
        assert app.preview_canvas.bind("<B1-Motion>")
        assert app.preview_canvas.bind("<B2-Motion>")
        assert app.preview_canvas.bind("<ButtonRelease-1>")
        assert app.preview_canvas.bind("<ButtonRelease-2>")
        assert app.preview_canvas.bind("<Double-Button-1>")
        assert app.preview_canvas.bind("<MouseWheel>")
        assert app.preview_canvas.bind("<Button-4>")
        assert app.preview_canvas.bind("<Button-5>")
        assert app.preview_canvas.bind("<Delete>")
        assert app.preview_canvas.bind("<BackSpace>")
        assert app.preview_canvas.bind("<Motion>")
        assert app.preview_canvas.bind("<Leave>")
        assert app.preview_ruler_x is not None
        assert app.preview_ruler_y is not None
        assert app.preview_ruler_corner is not None
        # 菜单数据驱动（弹窗用原生 tk.Menu）；直接校验 app._menus 的数据结构。
        menus = dict(app._menus)
        assert list(menus) == ["文件", "编辑", "查看", "帮助"]
        file_labels = [it["label"] for it in menus["文件"] if it.get("type") != "separator"]
        assert "导入备注..." in file_labels
        edit_labels = [it["label"] for it in menus["编辑"] if it.get("type") != "separator"]
        assert edit_labels == ["布局设置...", "字形..."]
        assert app.preview_canvas.bind("<Button-3>")
        assert app.preview_canvas.bind("<Button-2>")
        visible_texts = _widget_texts(root)
        # Packet 7 更新陈旧期望：迁移期重排面板时，旧「内容/大小写」编辑卡与底部「生产输出」
        # 栏已删除（见 ui_app._build_output_settings_panel 注释「原底部『生产输出』栏已删」），
        # 其唯一保留的两项（状态 + 主操作「生成」）并入「输出设置」卡。故这三处可见文本现已
        # 不在界面上；按当前事实改为「不在 visible_texts」。可见的主操作仍是「生成」「100%」。
        assert "内容" not in visible_texts
        assert "大小写" not in visible_texts
        assert "添加" not in visible_texts
        assert "画布宽" not in visible_texts
        assert "画布高" not in visible_texts
        assert "生产输出" not in visible_texts
        assert "生成" in visible_texts
        assert "姓名/文字" not in visible_texts
        assert "重新扫描" not in visible_texts
        assert "显示辅助框" not in visible_texts
        assert "适配窗口" not in visible_texts
        assert "100%" in visible_texts
        assert "重置布局" not in visible_texts
        assert "字形详情" not in visible_texts
    finally:
        root.destroy()


def test_preview_mousewheel_zoom_keeps_mouse_anchor():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        assert app.preview_canvas is not None
        app.preview_canvas.update_idletasks()
        layout = layout_from_values(app.layout_vars)
        mouse_x = 360
        mouse_y = 260
        old_scale, old_offset_x, old_offset_y = app._preview_transform(layout)
        anchored_doc_x = (mouse_x - old_offset_x) / old_scale
        anchored_doc_y = (mouse_y - old_offset_y) / old_scale

        result = app._on_canvas_mousewheel(SimpleNamespace(x=mouse_x, y=mouse_y, delta=120))

        new_scale, new_offset_x, new_offset_y = app._preview_transform(layout)
        assert result == "break"
        assert app.preview_zoom > 1.0
        assert new_scale > old_scale
        assert new_offset_x + anchored_doc_x * new_scale == pytest.approx(mouse_x)
        assert new_offset_y + anchored_doc_y * new_scale == pytest.approx(mouse_y)
    finally:
        root.destroy()


def test_preview_ruler_interval_uses_readable_mm_steps_without_display():
    # Packet 7 更新陈旧期望：迁移后 _ruler_interval_mm 的目标屏幕间距改为 target_px=40
    # （原 72），让“看全板/缩小”时刻度更密。选取「使 interval*px_per_mm >= 40 的最小档」，
    # 档位序列 (1,2,5,10,20,50,...)。故 100px/mm→1mm、10px/mm→5mm、1px/mm→50mm。
    # 旧断言（1/10/100）来自迁移前的 target_px，与当前实现不符，按现行为更新。
    app = BirthFlowerApp.__new__(BirthFlowerApp)

    assert app._ruler_interval_mm(100) == pytest.approx(1)
    assert app._ruler_interval_mm(10) == pytest.approx(5)
    assert app._ruler_interval_mm(1) == pytest.approx(50)


def test_preview_physical_size_mm_falls_back_to_scaled_80mm_without_display(monkeypatch):
    app = BirthFlowerApp.__new__(BirthFlowerApp)
    layout = ui_app_module.EngravingLayout(canvas_width=1600, canvas_height=800)
    monkeypatch.setattr(
        ui_app_module, "load_template_physical_size", lambda: (_ for _ in ()).throw(RuntimeError("missing"))
    )

    assert app._template_physical_size_mm(layout) == pytest.approx((80.0, 40.0))

def test_preview_zoom_status_text_updates_without_display():
    class FakeVar:
        def __init__(self):
            self.value = ""

        def set(self, value):
            self.value = value

    app = BirthFlowerApp.__new__(BirthFlowerApp)
    app.preview_zoom = 2.5
    app.preview_zoom_status_var = FakeVar()

    assert app._preview_zoom_percent_text() == "250%"

    app._update_preview_zoom_status()

    assert app.preview_zoom_status_var.value == "250%"


def test_preview_mousewheel_zoom_status_reaches_125_percent_without_display(monkeypatch):
    class FakeCanvas:
        def __getitem__(self, key):
            return "720" if key == "width" else "532"

        def winfo_width(self):
            return 720

        def winfo_height(self):
            return 532

        def focus_set(self):
            pass

    class FakeVar:
        def __init__(self):
            self.value = "100%"

        def set(self, value):
            self.value = value

    app = BirthFlowerApp.__new__(BirthFlowerApp)
    app.preview_canvas = FakeCanvas()
    app.inline_text_entry = None
    app.preview_zoom = 1.0
    app.preview_pan_x = 0.0
    app.preview_pan_y = 0.0
    app.preview_zoom_status_var = FakeVar()
    app.layout_vars = {}
    app._redraw_preview = lambda: None
    layout = ui_app_module.EngravingLayout(canvas_width=1000, canvas_height=500)
    monkeypatch.setattr(ui_app_module, "layout_from_values", lambda _vars: layout)

    # Packet 7 更新陈旧期望：当前 PREVIEW_ZOOM_STEP=0.05（线性 5%/tick，迁移前是 0.25），
    # 故一次上滚 1.00→1.05、状态显示 105%。旧断言 1.25/125% 来自已被改掉的步长，按现行为更新。
    assert app._on_canvas_mousewheel(SimpleNamespace(x=320, y=180, delta=120, state=0)) == "break"

    assert app.preview_zoom == pytest.approx(1.05)
    assert app.preview_zoom_status_var.value == "105%"


def test_preview_mousewheel_zoom_logic_without_display(monkeypatch):
    class FakeCanvas:
        def __init__(self):
            self.focused = False

        def __getitem__(self, key):
            if key == "width":
                return "720"
            if key == "height":
                return "532"
            raise KeyError(key)

        def winfo_width(self):
            return 720

        def winfo_height(self):
            return 532

        def focus_set(self):
            self.focused = True

    app = BirthFlowerApp.__new__(BirthFlowerApp)
    app.preview_canvas = FakeCanvas()
    app.inline_text_entry = None
    app.preview_zoom = 1.0
    app.preview_pan_x = 0.0
    app.preview_pan_y = 0.0
    redraw_calls = []
    app._redraw_preview = lambda: redraw_calls.append("redraw")
    layout = ui_app_module.EngravingLayout(canvas_width=1000, canvas_height=500)
    monkeypatch.setattr(ui_app_module, "layout_from_values", lambda _vars: layout)
    app.layout_vars = {}

    mouse_x = 300
    mouse_y = 220
    old_scale, old_offset_x, old_offset_y = app._preview_transform(layout)
    anchored_doc_x = (mouse_x - old_offset_x) / old_scale
    anchored_doc_y = (mouse_y - old_offset_y) / old_scale

    assert app._on_canvas_mousewheel(SimpleNamespace(x=mouse_x, y=mouse_y, delta=120)) == "break"

    new_scale, new_offset_x, new_offset_y = app._preview_transform(layout)
    assert app.preview_zoom > 1.0
    assert new_scale > old_scale
    assert new_offset_x + anchored_doc_x * new_scale == pytest.approx(mouse_x)
    assert new_offset_y + anchored_doc_y * new_scale == pytest.approx(mouse_y)
    assert app.preview_canvas.focused is True
    assert redraw_calls == ["redraw"]


def test_preview_mousewheel_zoom_out_logic_without_display(monkeypatch):
    class FakeCanvas:
        def __getitem__(self, key):
            return "720" if key == "width" else "532"

        def winfo_width(self):
            return 720

        def winfo_height(self):
            return 532

        def focus_set(self):
            pass

    app = BirthFlowerApp.__new__(BirthFlowerApp)
    app.preview_canvas = FakeCanvas()
    app.inline_text_entry = None
    app.preview_zoom = 2.0
    app.preview_pan_x = -120.0
    app.preview_pan_y = -60.0
    app._redraw_preview = lambda: None
    layout = ui_app_module.EngravingLayout(canvas_width=1000, canvas_height=500)
    monkeypatch.setattr(ui_app_module, "layout_from_values", lambda _vars: layout)
    app.layout_vars = {}

    old_scale, _old_offset_x, _old_offset_y = app._preview_transform(layout)

    assert app._on_canvas_mousewheel(SimpleNamespace(x=320, y=180, delta=-120)) == "break"

    new_scale, _new_offset_x, _new_offset_y = app._preview_transform(layout)
    assert app.preview_zoom < 2.0
    assert new_scale < old_scale

    # Linux/X11 Button-5 is also zoom-out and should keep moving toward the lower bound.
    previous_zoom = app.preview_zoom
    assert app._on_canvas_mousewheel(SimpleNamespace(x=320, y=180, delta=0, num=5)) == "break"
    assert app.preview_zoom < previous_zoom


def test_preview_modifier_mousewheel_still_zooms_without_display(monkeypatch):
    # Packet 7 重写陈旧期望：迁移后滚轮**只负责缩放**（平移交给鼠标拖动 / 中键 pan），
    # Shift/Alt+滚轮不再做横向平移，PREVIEW_WHEEL_PAN_STEP 常量也已删除。这里把原
    # 「修饰键滚轮横向平移」用例改为断言现行为：带修饰键的滚轮仍以鼠标为锚点缩放。
    class FakeCanvas:
        def __getitem__(self, key):
            return "720" if key == "width" else "532"

        def winfo_width(self):
            return 720

        def winfo_height(self):
            return 532

        def focus_set(self):
            pass

    app = BirthFlowerApp.__new__(BirthFlowerApp)
    app.preview_canvas = FakeCanvas()
    app.inline_text_entry = None
    app.preview_zoom = 1.5
    app.preview_pan_x = 10.0
    app.preview_pan_y = 20.0
    app.preview_zoom_status_var = None
    redraw_calls = []
    app._redraw_preview = lambda: redraw_calls.append("redraw")
    layout = ui_app_module.EngravingLayout(canvas_width=1000, canvas_height=500)
    monkeypatch.setattr(ui_app_module, "layout_from_values", lambda _vars: layout)
    app.layout_vars = {}

    # Shift+上滚：仍缩放（线性 +5%），不是平移。
    assert app._on_canvas_mousewheel(SimpleNamespace(x=320, y=180, delta=120, state=0x0001)) == "break"
    assert app.preview_zoom == pytest.approx(1.55)

    # Alt+下滚：继续缩放（-5%），回到 1.5。
    assert app._on_canvas_mousewheel(SimpleNamespace(x=320, y=180, delta=-120, state=0x0008)) == "break"
    assert app.preview_zoom == pytest.approx(1.5)
    assert redraw_calls == ["redraw", "redraw"]
    assert not hasattr(ui_app_module, "PREVIEW_WHEEL_PAN_STEP")


def test_preview_middle_press_starts_pan_mode_without_display():
    class FakeCanvas:
        def __init__(self):
            self.cursor = ""
            self.focused = False

        def focus_set(self):
            self.focused = True

        def configure(self, **kwargs):
            if "cursor" in kwargs:
                self.cursor = kwargs["cursor"]

    app = BirthFlowerApp.__new__(BirthFlowerApp)
    app.preview_canvas = FakeCanvas()
    app.inline_text_entry = None
    app.document = SimpleNamespace(selected_layer_id="old")
    app.selected_preview_item = "old"
    app._drag_target = "old-layer"
    app._drag_mode = "move"
    app._drag_start = None

    assert app._on_canvas_pan_press(SimpleNamespace(x=200, y=160)) == "break"

    assert app._drag_mode == "pan"
    assert app._drag_target is None
    assert app._drag_start == (200, 160)
    assert app.document.selected_layer_id == "old"
    assert app.selected_preview_item == "old"
    assert app.preview_canvas.cursor == "fleur"
    assert app.preview_canvas.focused is True


def test_preview_middle_drag_pan_moves_viewport_without_display():
    class FakeCanvas:
        def __init__(self):
            self.cursor = "fleur"

        def configure(self, **kwargs):
            if "cursor" in kwargs:
                self.cursor = kwargs["cursor"]

    app = BirthFlowerApp.__new__(BirthFlowerApp)
    app.preview_canvas = FakeCanvas()
    app.preview_pan_x = 15.0
    app.preview_pan_y = -5.0
    app._drag_mode = "pan"
    app._drag_target = None
    app._drag_start = (100, 80)
    redraw_calls = []
    app._redraw_preview = lambda: redraw_calls.append("redraw")

    app._on_canvas_drag(SimpleNamespace(x=145, y=110))

    assert app.preview_pan_x == pytest.approx(60.0)
    assert app.preview_pan_y == pytest.approx(25.0)
    assert app._drag_start == (145, 110)
    assert redraw_calls == ["redraw"]

    app._on_canvas_release(SimpleNamespace())

    assert app._drag_mode == "move"
    assert app._drag_target is None
    assert app._drag_start is None
    assert app.preview_canvas.cursor == ""


def test_preview_zoom_and_pan_do_not_mutate_document_or_layer_geometry(monkeypatch):
    class FakeCanvas:
        def __init__(self):
            self.cursor = ""

        def __getitem__(self, key):
            return "720" if key == "width" else "532"

        def winfo_width(self):
            return 720

        def winfo_height(self):
            return 532

        def focus_set(self):
            pass

        def configure(self, **kwargs):
            if "cursor" in kwargs:
                self.cursor = kwargs["cursor"]

    app = BirthFlowerApp.__new__(BirthFlowerApp)
    app.preview_canvas = FakeCanvas()
    app.inline_text_entry = None
    app.preview_zoom = 1.0
    app.preview_pan_x = 0.0
    app.preview_pan_y = 0.0
    app.preview_zoom_status_var = None
    app.layout_vars = {}
    app.document = Document(1000, 500)
    layer = add_text_layer(app.document, "Export Safe", x=123, y=45, width=300, height=80, font_size=42)
    app._redraw_preview = lambda: None
    layout = ui_app_module.EngravingLayout(canvas_width=1000, canvas_height=500)
    monkeypatch.setattr(ui_app_module, "layout_from_values", lambda _vars: layout)
    before_document = (app.document.canvas_width, app.document.canvas_height, app.document.selected_layer_id)
    before_layer = (layer.x, layer.y, layer.width, layer.height, layer.scale_x, layer.scale_y, layer.font_size, layer.text)

    app._on_canvas_mousewheel(SimpleNamespace(x=320, y=180, delta=120, state=0))
    app._on_canvas_pan_press(SimpleNamespace(x=320, y=180))
    app._on_canvas_drag(SimpleNamespace(x=370, y=210))
    app._on_canvas_release(SimpleNamespace())

    after_document = (app.document.canvas_width, app.document.canvas_height, app.document.selected_layer_id)
    after_layer = (layer.x, layer.y, layer.width, layer.height, layer.scale_x, layer.scale_y, layer.font_size, layer.text)
    assert app.preview_zoom != 1.0
    assert (app.preview_pan_x, app.preview_pan_y) != (0.0, 0.0)
    assert after_document == before_document
    assert after_layer == before_layer

def test_import_asset_dispatches_font_and_flower_paths(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        font_path = tmp_path / "Custom.ttf"
        flower_path = tmp_path / "Custom.svg"
        font_path.write_bytes(b"font")
        flower_path.write_text("<svg/>", encoding="utf-8")
        calls = []

        def fake_import(path):
            calls.append(Path(path))

        monkeypatch.setattr(app, "_import_font_file", fake_import)
        monkeypatch.setattr(app, "_import_flower_file", fake_import)

        app._import_asset_path(font_path)
        app._import_asset_path(flower_path)

        assert calls == [font_path, flower_path]
        assert ".ttf" in IMPORTABLE_FONT_SUFFIXES
        assert ".svg" in IMPORTABLE_ASSET_SUFFIXES
    finally:
        root.destroy()


def test_import_font_file_selects_font_and_text(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        font_path = tmp_path / "Script.ttf"
        font_path.write_bytes(b"font")
        font_asset = FontAsset(name="Script", index=5, path=font_path)
        monkeypatch.setattr(ui_app_module, "scan_font_assets", lambda _path: [font_asset])
        monkeypatch.setattr(app, "_save_current_config", lambda: None)

        app._import_font_file(font_path)

        assert app.font_source_var.get() == str(font_path)
        assert app.font_assets == [font_asset]
        assert app.font_var.get() == "5"
        layer = app.document.selected_layer()
        assert isinstance(layer, TextLayer)
        assert app.selected_preview_item == layer.id
    finally:
        root.destroy()


def test_import_flower_file_selects_asset_and_flower(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        flower_path = tmp_path / "Custom.svg"
        flower_path.write_text("<svg/>", encoding="utf-8")
        flower_asset = FlowerAsset(name="Custom", path=flower_path, display_name="Custom")
        monkeypatch.setattr(ui_app_module, "scan_flower_assets", lambda _path: [flower_asset])
        monkeypatch.setattr(app, "_save_current_config", lambda: None)

        app._import_flower_file(flower_path)

        assert app.flower_dir_var.get() == str(tmp_path)
        assert app.flower_assets == [flower_asset]
        assert app.pending_flower_asset_label == app._flower_label(flower_asset)
        assert len(app.document.layers) == 1
        assert isinstance(app.document.selected_layer(), ImageLayer)
        assert app.document.selected_layer().path == flower_path
    finally:
        root.destroy()


def test_collect_importable_files_single_file_by_suffix(tmp_path):
    good = tmp_path / "rose.svg"
    bad = tmp_path / "notes.txt"
    good.write_text("<svg/>", encoding="utf-8")
    bad.write_text("x", encoding="utf-8")
    assert collect_importable_files(good, IMPORTABLE_ASSET_SUFFIXES) == ([good], [])
    assert collect_importable_files(bad, IMPORTABLE_ASSET_SUFFIXES) == ([], [bad])


def test_collect_importable_files_folder_splits_and_is_case_insensitive(tmp_path):
    svg = tmp_path / "rose.svg"
    png = tmp_path / "tulip.PNG"  # 大写后缀也应识别
    txt = tmp_path / "notes.txt"  # 不支持 → 跳过
    for path in (svg, png, txt):
        path.write_text("x", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    deep = sub / "deep.svg"
    deep.write_text("<svg/>", encoding="utf-8")

    valid, skipped = collect_importable_files(tmp_path, IMPORTABLE_ASSET_SUFFIXES)
    assert valid == [svg, png]  # 排序稳定、非递归忽略子目录
    assert skipped == [txt]

    valid_recursive, _ = collect_importable_files(tmp_path, IMPORTABLE_ASSET_SUFFIXES, recursive=True)
    assert deep in valid_recursive


def test_collect_importable_files_missing_path_is_empty(tmp_path):
    assert collect_importable_files(tmp_path / "nope", IMPORTABLE_ASSET_SUFFIXES) == ([], [])


def test_add_library_folder_imports_image_folder_and_accumulates(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        monkeypatch.setattr(ui_app_module, "save_config", lambda *_a, **_k: None)
        folder = tmp_path / "lib_a"
        folder.mkdir()
        (folder / "rose.svg").write_text("<svg/>", encoding="utf-8")
        (folder / "tulip.png").write_bytes(b"\x89PNG\r\n")
        (folder / "notes.txt").write_text("skip me", encoding="utf-8")  # 不支持 → 不中断

        summary = app._add_library_folder("image", folder)

        assert summary["imported"] >= 1  # 文件夹内支持的素材批量并入
        assert summary["skipped"] == 1  # 不支持文件被跳过、流程未中断
        assert summary["already"] is False
        assert any(_paths_equal(folder, d) for d in active_product(app.config).image_library_dirs)

        # 再次导入同一文件夹 = 按路径去重，不重复添加，也不报错
        dirs_before = list(active_product(app.config).image_library_dirs)
        summary_again = app._add_library_folder("image", folder)
        assert summary_again["already"] is True
        assert list(active_product(app.config).image_library_dirs) == dirs_before
    finally:
        root.destroy()


def test_add_library_folder_imports_font_folder_and_skips_unsupported(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        monkeypatch.setattr(ui_app_module, "save_config", lambda *_a, **_k: None)
        folder = tmp_path / "fonts"
        folder.mkdir()
        (folder / "Custom.ttf").write_bytes(b"\x00\x01\x00\x00fake-font")
        (folder / "readme.txt").write_text("skip", encoding="utf-8")

        summary = app._add_library_folder("font", folder)

        assert summary["imported"] >= 1
        assert summary["skipped"] == 1
        assert any(_paths_equal(folder, d) for d in active_product(app.config).font_library_dirs)
        assert any(asset.path.name == "Custom.ttf" for asset in app.font_assets)
    finally:
        root.destroy()


def test_add_library_folder_warns_and_keeps_config_when_no_supported_files(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        monkeypatch.setattr(ui_app_module, "save_config", lambda *_a, **_k: None)
        warnings: list = []
        monkeypatch.setattr(ui_app_module.messagebox, "showwarning", lambda *a, **k: warnings.append(a))
        folder = tmp_path / "empty_lib"
        folder.mkdir()
        (folder / "readme.txt").write_text("no assets here", encoding="utf-8")
        dirs_before = list(active_product(app.config).image_library_dirs)

        summary = app._add_library_folder("image", folder)

        assert summary["imported"] == 0
        assert warnings  # 给了提示
        assert list(active_product(app.config).image_library_dirs) == dirs_before  # 配置未被改动
    finally:
        root.destroy()


def test_confirm_rejects_bitmap_flower_when_dxf_is_selected(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        flower_path = tmp_path / "Imported.png"
        flower_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        asset = FlowerAsset(name="Imported", path=flower_path, display_name="Imported", is_vector_safe=False)
        app.name_var.set("Iris")
        app.month_var.set("4")
        app.flower_var.set("9")
        app.font_var.set("1")
        app.flower_assets = [asset]
        app._refresh_flower_choices()
        label = app._flower_label(asset)
        app.flower_asset_var.set(label)
        app.output_format_vars["png"].set(False)
        app.output_format_vars["svg"].set(False)
        app.output_format_vars["dxf"].set(True)
        errors = []
        asked = []

        monkeypatch.setattr(ui_app_module.messagebox, "showerror", lambda title, message: errors.append((title, message)))
        monkeypatch.setattr(ui_app_module.messagebox, "askyesno", lambda *_args, **_kwargs: asked.append(True))

        app.confirm_and_generate()

        assert errors
        assert "位图素材无法导出 DXF" in errors[0][1]
        assert asked == []
    finally:
        root.destroy()


def test_double_click_text_opens_inline_editor_and_commits_content():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        layer = add_text_layer(app.document, "Rose", x=100, y=80, width=240, height=90, font_size=72)
        app.document.selected_layer_id = layer.id
        app._start_inline_text_edit(layer)

        assert app.inline_text_entry is not None
        app.inline_text_entry.delete("1.0", "end")
        app.inline_text_entry.insert("1.0", "Lily")
        app._commit_inline_text_edit()

        assert layer.text == "Lily"
        assert app.inline_text_entry is None
        assert len([item for item in app.document.layers if isinstance(item, TextLayer)]) == 1
    finally:
        root.destroy()


def test_inline_text_editor_has_no_visual_frame_and_hides_selection_box():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        layer = add_text_layer(app.document, "Rose", x=100, y=80, width=240, height=90, font_size=72)
        app.document.selected_layer_id = layer.id
        app._redraw_preview()
        assert app.preview_canvas is not None
        assert app.preview_canvas.find_withtag("selection_box")

        app._start_inline_text_edit(layer)
        app._redraw_preview()

        assert app.inline_text_entry is not None
        assert app.inline_text_entry.cget("relief") == "flat"
        assert int(app.inline_text_entry.cget("borderwidth")) == 0
        assert int(app.inline_text_entry.cget("highlightthickness")) == 0
        assert not app.preview_canvas.find_withtag("selection_box")
        assert not app.preview_canvas.find_withtag("selection_handle")
    finally:
        root.destroy()


def test_inline_text_editor_updates_layer_live_and_preserves_pua(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        layer = add_text_layer(app.document, "old", x=100, y=80, width=240, height=90, font_size=72)
        app.document.selected_layer_id = layer.id
        app._start_inline_text_edit(layer)

        redraws = []
        monkeypatch.setattr(app, "_schedule_canvas_render", lambda delay_ms=25: redraws.append(delay_ms))
        assert app.inline_text_entry is not None
        app.inline_text_entry.delete("1.0", "end")
        app.inline_text_entry.insert("1.0", "h\ue014v")
        app.inline_text_entry.edit_modified(True)
        app._on_inline_text_modified(SimpleNamespace())

        assert layer.text == "h\ue014v"
        assert app.layer_text_var.get() == "h\ue014v"
        assert redraws == [25]
        assert len(app.document.layers) == 1
    finally:
        root.destroy()


def test_restore_glyph_uses_inline_text_selection(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    warnings = []
    monkeypatch.setattr(ui_app_module.messagebox, "showwarning", lambda title, message: warnings.append((title, message)))

    try:
        app = BirthFlowerApp(root)
        layer = add_text_layer(app.document, "Jazmin", x=100, y=80, width=240, height=90, font_size=72)
        layer.glyph_overrides[5] = {
            "index": 5,
            "base_char": "n",
            "original_char": "n",
            "replacement_char": "\ue123",
            "char": "\ue123",
            "codepoint": "E123",
            "glyph_name": "uniE123",
            "source": "manual",
        }
        app.document.selected_layer_id = layer.id
        app._apply_text_layer_render_text(layer)
        assert layer.render_text == "Jazmi\ue123"

        app._start_inline_text_edit(layer)
        assert app.inline_text_entry is not None
        app.inline_text_entry.tag_remove("sel", "1.0", "end")
        app.inline_text_entry.tag_add("sel", "1.5", "1.6")
        app.selected_glyph_position = None

        app.restore_selected_glyph_override()

        assert warnings == []
        assert app.selected_glyph_position == 5
        assert layer.glyph_overrides == {}
        assert layer.render_text == "Jazmin"
    finally:
        root.destroy()


def test_apply_recommended_glyph_uses_inline_text_selection(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    font_path = tmp_path / "Font2.ttf"
    font_path.write_bytes(b"fake font")
    variant = GlyphVariant.from_mapping(
        {
            "base_char": "n",
            "replacement_char": "\ue123",
            "codepoint": "E123",
            "glyph_name": "uniE123",
            "font_id": "Font 2",
            "font_path": str(font_path),
            "display_name": "n ending glyph",
            "usage": "end",
            "source": "manual_binding",
        }
    )

    monkeypatch.setattr(ui_app_module, "build_glyph_catalog", lambda *_args, **_kwargs: object(), raising=False)
    monkeypatch.setattr(ui_app_module, "recommended_glyph_variants", lambda _catalog, char: [variant] if char == "n" else [], raising=False)

    opened = []

    try:
        app = BirthFlowerApp(root)
        monkeypatch.setattr(app, "_selected_font_path", lambda: font_path)
        monkeypatch.setattr(app, "open_glyph_panel", lambda: opened.append(True))
        layer = add_text_layer(app.document, "Jazmin", x=100, y=80, width=240, height=90, font_size=72)
        app.document.selected_layer_id = layer.id
        app._start_inline_text_edit(layer)
        assert app.inline_text_entry is not None
        app.inline_text_entry.tag_remove("sel", "1.0", "end")
        app.inline_text_entry.tag_add("sel", "1.5", "1.6")

        app.apply_recommended_glyph_to_selection()

        assert opened == []
        assert app.selected_glyph_position == 5
        assert layer.glyph_overrides[5]["glyph_name"] == "uniE123"
        assert layer.render_text == "Jazmi\ue123"
    finally:
        root.destroy()


def test_inline_text_editor_escape_restores_original_text():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        layer = add_text_layer(app.document, "Rose", x=100, y=80, width=240, height=90, font_size=72)
        app.document.selected_layer_id = layer.id
        app._start_inline_text_edit(layer)

        assert app.inline_text_entry is not None
        app.inline_text_entry.delete("1.0", "end")
        app.inline_text_entry.insert("1.0", "Lily")
        app.inline_text_entry.edit_modified(True)
        app._on_inline_text_modified(SimpleNamespace())
        assert layer.text == "Lily"

        app._cancel_inline_text_edit()

        assert layer.text == "Rose"
        assert app.inline_text_entry is None
        assert len(app.document.layers) == 1
    finally:
        root.destroy()


def test_inline_text_editor_exit_removes_canvas_window_and_border():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        layer = add_text_layer(app.document, "Rose", x=100, y=80, width=240, height=90, font_size=72)
        app.document.selected_layer_id = layer.id
        app._start_inline_text_edit(layer)

        assert app.inline_text_entry is not None
        assert app.preview_canvas is not None
        assert any(app.preview_canvas.type(item) == "window" for item in app.preview_canvas.find_all())

        app._commit_inline_text_edit()
        app._redraw_preview()

        assert app.inline_text_entry is None
        assert app.inline_text_window is None
        assert not any(app.preview_canvas.type(item) == "window" for item in app.preview_canvas.find_all())
        assert not app.preview_canvas.find_withtag("inline_text_editor")
    finally:
        root.destroy()


def test_text_case_toggle_controls_render_content_case():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        app.name_var.set("AbCd")

        app.text_case_var.set("default")
        assert app._content_text_for_render() == "AbCd"  # 默认不改大小写

        app.text_case_var.set("upper")
        assert app._content_text_for_render() == "ABCD"  # 大写

        app.text_case_var.set("lower")
        assert app._content_text_for_render() == "abcd"  # 小写

        # Packet 7：大小写转换逻辑（_content_text_for_render）是活的，但迁移后已无承载
        # `case_button` 的「内容」编辑卡，该控件成了孤儿。_cycle_text_case 仍正确驱动
        # text_case_var → trace → 重绘（这才是用户可见行为）；故只断言模式循环，不再断言
        # 已不存在的 case_button 控件。若未来重建内容卡再把按钮接回并补该断言。
        app.text_case_var.set("default")
        app._cycle_text_case()
        assert app.text_case_var.get() == "upper"
        assert not hasattr(app, "case_button")
    finally:
        root.destroy()


def test_preview_selection_draws_box_and_can_delete_selected_flower(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        assert app.preview_canvas is not None
        flower_path = tmp_path / "RoseJune.svg"
        flower_path.write_text(
            '<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L10 10"/></svg>',
            encoding="utf-8",
        )
        label = "Rose | RoseJune.svg"
        app.flower_label_map = {
            label: FlowerAsset(name="Rose", path=flower_path, display_name="Rose")
        }
        app.flower_asset_var.set(label)

        app._add_selected_flower_to_canvas()
        layer = app.document.selected_layer()
        assert isinstance(layer, ImageLayer)
        root.update_idletasks()

        assert app.preview_canvas.find_withtag("selection_box")
        assert app.preview_canvas.find_withtag("selection_handle")

        app._delete_selected_preview_item()

        assert app.document.layers == []
        assert app.selected_preview_item is None
    finally:
        root.destroy()


def test_canvas_context_menu_selects_layer_and_exposes_canvas_and_glyph_actions(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    menus = []

    class FakeMenu:
        def __init__(self, *_args, **_kwargs):
            self.labels = []
            menus.append(self)

        def add_command(self, **kwargs):
            self.labels.append(kwargs.get("label"))

        def add_separator(self):
            self.labels.append("---")

        def tk_popup(self, *_args):
            self.popup_called = True

        def grab_release(self):
            self.released = True

    try:
        app = BirthFlowerApp(root)
        monkeypatch.setattr(ui_app_module.tk, "Menu", FakeMenu)
        layer = add_text_layer(app.document, "Rose", x=100, y=80, width=240, height=90, font_size=72)
        assert app.preview_canvas is not None
        app._redraw_preview()
        layout = layout_from_values(app.layout_vars)
        scale, offset_x, offset_y = app._preview_transform(layout)
        event = SimpleNamespace(
            x=int(offset_x + (layer.x + 10) * scale),
            y=int(offset_y + (layer.y + 10) * scale),
            x_root=300,
            y_root=240,
        )

        app._show_canvas_context_menu(event)

        assert app.document.selected_layer_id == layer.id
        assert menus
        labels = menus[-1].labels
        assert "编辑文本" in labels
        assert "删除" in labels
        assert "锁定" in labels
        assert "上移" in labels
        assert "下移" in labels
        assert "置顶" in labels
        assert "置底" in labels
        assert "字形..." in labels
        assert "应用推荐字形" in labels
        assert "恢复普通字符" in labels
    finally:
        # 先撤销对 tkinter.Menu 的全局替身，否则 root.destroy() 时 CTkOptionMenu 的
        # DropdownMenu.destroy() 会调用 tkinter.Menu.destroy() 而触到 FakeMenu。
        monkeypatch.undo()
        root.destroy()



def test_flower_combo_change_without_selected_layer_only_updates_pending_material(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        flower_path = tmp_path / "Rose.svg"
        flower_path.write_text("<svg/>", encoding="utf-8")
        asset = FlowerAsset(name="Rose", path=flower_path, display_name="Rose")
        app.flower_assets = [asset]
        app._refresh_flower_choices()
        label = app._flower_label(asset)

        app._select_preview_item(None)
        app.flower_asset_var.set(label)
        app._on_flower_combo_selected()

        assert app.document.layers == []
        assert app.pending_flower_asset_label == label
    finally:
        root.destroy()


def test_flower_combo_change_while_text_layer_selected_does_not_create_or_modify_text(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        flower_path = tmp_path / "Daisy.svg"
        flower_path.write_text("<svg/>", encoding="utf-8")
        asset = FlowerAsset(name="Daisy", path=flower_path, display_name="Daisy")
        app.flower_assets = [asset]
        app._refresh_flower_choices()
        label = app._flower_label(asset)
        app.name_var.set("Original")
        app._add_text_layer_from_fields()
        layer = app.document.selected_layer()
        assert isinstance(layer, TextLayer)

        app.flower_asset_var.set(label)
        app._on_flower_combo_selected()

        assert len(app.document.layers) == 1
        assert app.document.selected_layer() is layer
        assert layer.text == "Original"
        assert app.pending_flower_asset_label == label
    finally:
        root.destroy()


def test_flower_combo_change_while_image_layer_selected_replaces_only_current_image(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        first_path = tmp_path / "Rose.svg"
        second_path = tmp_path / "Lily.svg"
        first_path.write_text("<svg/>", encoding="utf-8")
        second_path.write_text("<svg/>", encoding="utf-8")
        first = FlowerAsset(name="Rose", path=first_path, display_name="Rose")
        second = FlowerAsset(name="Lily", path=second_path, display_name="Lily")
        app.flower_assets = [first, second]
        app._refresh_flower_choices()
        first_label = app._flower_label(first)
        second_label = app._flower_label(second)
        app.flower_asset_var.set(first_label)
        app._add_selected_flower_to_canvas()
        layer = app.document.selected_layer()
        assert isinstance(layer, ImageLayer)

        app.flower_asset_var.set(second_label)
        app._on_flower_combo_selected()

        assert len(app.document.layers) == 1
        assert app.document.selected_layer() is layer
        assert layer.path == second_path
        assert layer.name == "Lily"
        assert app.pending_flower_asset_label == second_label
    finally:
        root.destroy()


def test_parse_result_replaces_existing_material_and_text_layers(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        old_flower_path = tmp_path / "Old.svg"
        flower_path = tmp_path / "IrisMay.svg"
        font_path = tmp_path / "Font2.ttf"
        old_flower_path.write_text("<svg/>", encoding="utf-8")
        flower_path.write_text("<svg/>", encoding="utf-8")
        font_path.write_bytes(b"font")
        add_image_layer(app.document, old_flower_path, name="Old flower")
        add_text_layer(app.document, "Old name", font_path=font_path)
        asset = FlowerAsset(name="Iris", path=flower_path, display_name="Iris")
        font = FontAsset(name="Font 2", index=2, path=font_path, font_design="Font 2")
        app.flower_dir_var.set(str(tmp_path))
        app.flower_assets = [asset]
        app.font_assets = [font]
        warnings = []
        monkeypatch.setattr(ui_app_module.messagebox, "showwarning", lambda title, message: warnings.append((title, message)))

        app._refresh_flower_choices()
        app._refresh_font_choices()
        app._apply_parse_result(
            SimpleNamespace(text="Ivy", month=5, font=2, flower=1, flower_name="Iris", material_key="", warnings=[])
        )

        assert len(app.document.layers) == 2
        image_layer, text_layer = app.document.layers
        assert isinstance(image_layer, ImageLayer)
        assert isinstance(text_layer, TextLayer)
        assert image_layer.path == flower_path
        assert image_layer.name == "Iris"
        assert text_layer.text == "Ivy"
        assert text_layer.original_text == "Ivy"
        assert text_layer.font_path == font_path
        assert app.pending_flower_asset_label == app._flower_label(asset)
        assert warnings == []
    finally:
        root.destroy()


def test_parse_remark_reads_current_text_widget_content(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        assert app.remark_text is not None
        note = (
            "Choose Your Birth Flower  : Sep - Aster\n"
            "Font Design  : Font 3\n"
            "Personalization  : Lacey"
        )
        app.remark_var.set("")
        app.remark_text.delete("1.0", "end")
        app.remark_text.insert("1.0", note)
        calls = []
        received_bundle = []

        def fake_parser(remark, ai_config=None, bundle=None, trace=None):
            calls.append(remark)
            received_bundle.append(bundle)
            # 多订单接口返回列表；单笔时 _apply_parsed_orders 载入第一笔。
            # trace=空壳 ParsePromptTrace（解析可观测②）：真实解析路径会填它，fake 无需填。
            return [SimpleNamespace(text="Lacey", month=9, font=3, flower=1, warnings=[])]

        def run_immediately(_root, work, on_success, on_error):
            try:
                result = work()
            except Exception as exc:
                on_error(exc)
            else:
                on_success(result)
            return SimpleNamespace()

        monkeypatch.setattr(ui_app_module, "parse_orders_auto", fake_parser)
        monkeypatch.setattr(ui_app_module, "run_background", run_immediately)
        monkeypatch.setattr(ui_app_module.messagebox, "showwarning", lambda *_args, **_kwargs: None)

        app.parse_remark()

        assert calls == [note]
        assert received_bundle == [app.active_bundle]  # 增量：解析时把当前产品库 bundle 传给后端
        assert app.remark_var.get() == note
        assert app.name_var.get() == "Lacey"
        assert app.font_var.get() == "3"
    finally:
        root.destroy()


def test_field_instructions_drive_ai_system_prompt(monkeypatch):
    # 提示词规则来自前台「字段」区，不来自写死常量。
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")
    try:
        app = BirthFlowerApp(root)
        rules = app._assemble_field_rules()
        assert "花朵名" in rules  # 默认花朵字段规则进了提示词（月→花对照表已删，零配置按文件名）
        cfg = app._current_ai_config("ORDER TEXT")
        assert "花朵名" in cfg.system_prompt
        assert "ORDER TEXT" in cfg.system_prompt  # 订单文本原样插入，无 <order_data> 包裹
        assert cfg.user_content == ""
        # 编辑某字段 instruction → 立即反映进发给 API 的提示词
        app.field_defs[0]["inst_var"].set("只提取顾客名字 XYZ")
        app._persist_prompts()
        assert "只提取顾客名字 XYZ" in app._current_ai_config().system_prompt
    finally:
        root.destroy()


def test_field_defs_persist_and_reload(monkeypatch):
    # 字段（=提示词规则）编辑后按产品落盘，重载恢复。
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")
    try:
        monkeypatch.setattr(ui_app_module, "save_config", lambda _cfg: None)
        app = BirthFlowerApp(root)
        app.field_defs[1]["inst_var"].set("自定义出生花规则")
        app._persist_prompts()
        assert active_product(app.config).extraction_prompt  # 序列化进 extraction_prompt
        app._load_field_defs_into_self()
        assert any(f["instruction"] == "自定义出生花规则" for f in app.field_defs)
    finally:
        root.destroy()


def test_add_field_sequence_stays_unique_after_delete(monkeypatch):
    # 加字段编号基于现有字段、key 取最大序号+1：删中间字段后再加不撞已有 key。
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")
    try:
        monkeypatch.setattr(ui_app_module, "save_config", lambda _cfg: None)
        app = BirthFlowerApp(root)
        start_seq = active_product(app.config).field_seq_max
        app._add_field()
        created = max(active_product(app.config).reference_fields, key=lambda field: field.sequence_number)
        assert created.sequence_number == start_seq + 1
        app._delete_field(created.id)
        app._add_field()
        sequences = [field.sequence_number for field in active_product(app.config).reference_fields]
        assert len(sequences) == len(set(sequences)), f"sequence 出现重复: {sequences}"
        assert max(sequences) == start_seq + 2
    finally:
        root.destroy()


def test_add_flower_writes_layer_library_and_material_key(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")
    try:
        from asset_resolver import scan_flower_assets
        from models import ImageLayer
        from order_catalog import LibraryBundle

        app = BirthFlowerApp(root)
        flowers = tmp_path / "flowers"
        flowers.mkdir()
        (flowers / "March_Daffodil.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0h10v10H0z"/></svg>',
            encoding="utf-8",
        )
        assets = scan_flower_assets(flowers)
        assert assets
        asset = assets[0]
        label = app._flower_label(asset)
        app.flower_label_map = {label: asset}
        app.flower_asset_var.set(label)
        app.active_bundle = LibraryBundle.from_dirs([flowers], [])

        app._add_selected_flower_to_canvas()

        images = [layer for layer in app.document.layers if isinstance(layer, ImageLayer)]
        assert images
        new_layer = images[-1]
        assert new_layer.material_key == asset.asset_key  # 图层记录引用的素材 key
        assert new_layer.library_id == app.active_bundle.image_libraries[0].id  # 以及所属库
    finally:
        root.destroy()


def test_import_remark_file_updates_visible_text_widget(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        assert app.remark_text is not None
        note = (
            "Choose Your Birth Flower  : Sep - Aster\n"
            "Font Design  : Font 3\n"
            "Personalization  : Lacey"
        )
        expected = " ".join(note.split())
        monkeypatch.setattr(ui_app_module.filedialog, "askopenfilename", lambda **_kwargs: "order.txt")
        monkeypatch.setattr(ui_app_module, "load_order_remark_from_file", lambda _path: note)

        app.import_remark_file()

        assert app.remark_var.get() == expected
        assert app.remark_text.get("1.0", "end-1c") == expected
    finally:
        root.destroy()


def test_import_remark_file_xlsx_runs_batch_flow(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        source = tmp_path / "orders.xlsx"
        source.write_bytes(b"xlsx")
        report_path = tmp_path / "batch-report.xlsx"
        result = SimpleNamespace(
            items=[
                SimpleNamespace(status="EXPORTED", needs_manual_review=False),
                SimpleNamespace(status="BLOCKED", needs_manual_review=True),
            ],
            report_path=report_path,
        )
        captured_dialog: list[object] = []
        captured_dialog_kwargs: dict[str, object] = {}
        imported_paths: list[Path] = []

        def fake_askopenfilename(**kwargs):
            captured_dialog_kwargs.update(kwargs)
            return str(source)

        def run_immediately(_root, work, on_success, on_error):
            try:
                value = work()
            except Exception as exc:
                on_error(exc)
            else:
                on_success(value)
            return SimpleNamespace()

        monkeypatch.setattr(ui_app_module.filedialog, "askopenfilename", fake_askopenfilename)
        monkeypatch.setattr(ui_app_module, "load_order_remark_from_file", lambda _path: (_ for _ in ()).throw(AssertionError("legacy importer called")))
        monkeypatch.setattr(ui_app_module, "run_background", run_immediately)
        monkeypatch.setattr(ui_app_module, "import_dianxiaomi_xlsx_batch", lambda path, layout=None: imported_paths.append(Path(path)) or result)
        monkeypatch.setattr(ui_app_module, "show_xlsx_batch_import_summary", lambda _root, value: captured_dialog.append(value))

        app.import_remark_file()

        assert "*.xlsx" in captured_dialog_kwargs["filetypes"][0][1]
        assert imported_paths == [source]
        assert captured_dialog == [result]
        assert ui_app_module.summarize_xlsx_batch_result(result) == (2, 1, 1, report_path)
    finally:
        root.destroy()


def test_font_settings_uses_one_choose_font_button():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        app.open_settings()
        root.update_idletasks()
        texts = _widget_texts(root)

        assert "选择字体" in texts
        assert "选择字体文件" not in texts
        assert "选择字体目录" not in texts
    finally:
        root.destroy()


def test_output_settings_exposes_format_path_and_resolution():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        app.open_settings()
        root.update_idletasks()
        settings_window = [child for child in root.winfo_children() if isinstance(child, tk.Toplevel)][-1]
        notebook = next(child for child in settings_window.winfo_children() if isinstance(child, ttk.Notebook))
        tab_texts = [notebook.tab(index, "text") for index in range(len(notebook.tabs()))]
        texts = _widget_texts(root)

        assert "输出设置" in tab_texts
        assert "输出格式" in texts
        assert "输出路径" in texts
        assert "输出分辨率" in texts
        assert "画布宽" in texts
        assert "画布高" in texts
    finally:
        root.destroy()


def test_glyph_menu_opens_ps_like_glyph_window():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        app.open_glyph_panel()
        root.update()

        panels = [child for child in root.winfo_children() if isinstance(child, tk.Toplevel)]
        assert panels
        panel = panels[-1]
        assert panel.title() == "字形"
        texts = _widget_texts(panel)
        assert "字形" in texts
        assert "字体" in texts
        assert "样式" in texts
        assert "筛选" in texts
        assert "状态" in texts
        assert "识别字母" in texts
        assert "字形码位" in texts
        assert "提醒" in texts
        assert "字形网格" in texts
        assert "字母 a-z" not in texts
        assert "当前字体 PUA glyph" not in texts
    finally:
        root.destroy()


def test_glyph_help_explains_font2_default_binding(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        app.show_glyph_help()  # 现在弹深色 CTk 窗口而非 messagebox；验证不报错 + 文本内容

        message = ui_app_module.GLYPH_HELP_TEXT
        assert "Font 2 已内置 a-z 26 个结尾字形" in message
        assert "a=U+E068" in message
        assert "z=U+E081" in message
        assert "编辑 -> 管理字形绑定" in message
        assert "按 a-z 绑定" in message
    finally:
        root.destroy()


def _widget_texts(widget):
    texts = []
    for child in widget.winfo_children():
        if hasattr(child, "cget"):
            try:
                text = child.cget("text")
            except (tk.TclError, ValueError):
                # CTk 容器（如 CTkFrame）对不支持的 "text" 选项抛 ValueError，而非 TclError。
                text = ""
            if text:
                texts.append(text)
        texts.extend(_widget_texts(child))
    return texts


def test_build_ai_parse_config_prefers_session_key_then_profile_environment():
    profile = AIProfile(
        provider="deepseek",
        model="gpt-5-nano",
        base_url="https://api.deepseek.com",
        api_key_env_var="SHOP_OPENAI_KEY",
        project_env_var="SHOP_PROJECT",
        org_env_var="SHOP_ORG",
        enabled=True,
        prefer_ai=True,
    )

    from_session = build_ai_parse_config(
        profile,
        session_api_key="sk-session",
        environ={"SHOP_OPENAI_KEY": "sk-env", "SHOP_PROJECT": "proj_1", "SHOP_ORG": "org_1"},
    )
    from_env = build_ai_parse_config(
        profile,
        session_api_key="",
        environ={"SHOP_OPENAI_KEY": "sk-env", "SHOP_PROJECT": "proj_1", "SHOP_ORG": "org_1"},
    )

    assert from_session.api_key == "sk-session"
    assert from_env.api_key == "sk-env"
    assert from_env.project == "proj_1"
    assert from_env.organization == "org_1"
    assert from_env.model == "gpt-5-nano"
    assert from_env.provider == "deepseek"
    assert from_env.base_url == "https://api.deepseek.com"
    assert from_env.prefer_ai is True


def test_build_ai_profile_from_settings_defaults_deepseek_fields_without_secret():
    profile = build_ai_profile_from_settings(
        AIProfile(name="OpenAI default"),
        provider="deepseek",
        model="",
        base_url="",
        api_key_env_var="",
        project_env_var="",
        org_env_var="",
        prefer_ai=True,
    )

    assert profile.provider == "deepseek"
    assert profile.model == "deepseek-v4-flash"
    assert profile.base_url == "https://api.deepseek.com"
    assert profile.api_key_env_var == "DEEPSEEK_API_KEY"
    assert profile.project_env_var == ""
    assert profile.org_env_var == ""
    assert profile.prefer_ai is True


def test_format_readiness_summary_shows_all_confidence_parts():
    summary = format_readiness_summary(
        GenerationReadiness(
            parse_confidence=0.97,
            asset_confidence=0.82,
            layout_confidence=0.45,
            overall_confidence=0.45,
            status="Needs review",
            warnings=["Text exceeds safe area"],
        )
    )

    assert "Needs review" in summary
    assert "parse 0.97" in summary
    assert "asset 0.82" in summary
    assert "layout 0.45" in summary
    assert "overall 0.45" in summary


def test_format_glyph_detail_shows_chinese_status_and_review_reason():
    detail = format_glyph_detail(
        GlyphApplyResult(
            original_text="Jazmin",
            render_text="Jazmi" + chr(0xE014),
            font_design="Font 4",
            apply_mode="replace_last_letter",
            source_letter="n",
            source_index=5,
            glyph_codepoint="U+E014",
            glyph_char=chr(0xE014),
            glyph_source="auto",
            needs_review=True,
            reason="长文本，建议人工确认",
        )
    )

    assert detail["status"] == "自动"
    assert detail["letter"] == "n"
    assert detail["codepoint"] == "U+E014"
    assert detail["apply_mode"] == "替换最后字母"
    assert detail["reason"] == "长文本，建议人工确认"


def test_format_font_asset_label_distinguishes_ending_decoration(tmp_path):
    path = tmp_path / "Malovely Script.ttf"
    path.write_bytes(b"font")

    def label(index: int, design: str, ending: bool) -> str:
        return format_font_asset_label(
            FontAsset(
                name="Malovely Script",
                index=index,
                path=path,
                font_design=design,
                file_size=105944,
                has_ending_glyphs=ending,
            )
        )

    # Font 2：字体内末尾字形（PUA 合体字形）。
    assert label(2, "Font 2", True) == "Font 2 - Malovely Script - Malovely Script.ttf - 103.5 KB - 末尾字形"
    # Font 4：独立爱心 SVG（无字形映射），文案须区别于「字形」。
    assert label(4, "Font 4", True) == "Font 4 - Malovely Script - Malovely Script.ttf - 103.5 KB - 末尾爱心"
    # 常规字体无末尾装饰。
    assert label(1, "Font 1", False) == "Font 1 - Malovely Script - Malovely Script.ttf - 103.5 KB - 常规"


def test_run_background_returns_before_slow_work_finishes():
    root = FakeRoot()
    release = threading.Event()
    started = threading.Event()
    results = []
    errors = []

    def work():
        started.set()
        release.wait(timeout=2)
        return "ok"

    thread = run_background(root, work, results.append, errors.append)

    assert started.wait(timeout=1)
    assert thread.is_alive()
    assert root.callbacks == []

    release.set()
    thread.join(timeout=1)

    assert len(root.callbacks) == 1
    delay, callback = root.callbacks[0]
    assert delay == 0
    callback()
    assert results == ["ok"]
    assert errors == []


def test_global_layout_defaults_only_initialize_new_layers(monkeypatch, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")

    try:
        app = BirthFlowerApp(root)
        monkeypatch.setattr(app, "_save_current_config", lambda: None)
        first_path = tmp_path / "First.svg"
        second_path = tmp_path / "Second.svg"
        first_path.write_text('<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        second_path.write_text('<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        first = FlowerAsset(name="First", path=first_path, display_name="First")
        second = FlowerAsset(name="Second", path=second_path, display_name="Second")
        app.flower_label_map = {"first": first, "second": second}

        app.layout_vars["flower_x"].set("10")
        app.layout_vars["flower_y"].set("20")
        app.layout_vars["flower_width"].set("300")
        app.layout_vars["flower_height"].set("400")
        app.flower_asset_var.set("first")
        app._add_selected_flower_to_canvas()
        first_layer = app.document.selected_layer()

        app.layout_vars["flower_x"].set("700")
        app.layout_vars["flower_y"].set("800")
        app.layout_vars["flower_width"].set("90")
        app.layout_vars["flower_height"].set("100")
        app.flower_asset_var.set("second")
        app._add_selected_flower_to_canvas()
        second_layer = app.document.selected_layer()

        assert first_layer.x == 10
        assert first_layer.y == 20
        assert first_layer.width == 300
        assert first_layer.height == 400
        assert second_layer.x == 700
        assert second_layer.y == 800
        assert second_layer.width == 90
        assert second_layer.height == 100
    finally:
        root.destroy()


def test_apply_layer_production_writes_geometry_and_override(tmp_path):
    # 增量4：属性面板编辑几何 → 写回画布几何 + 记录 layer.production override。
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")
    try:
        from production import ProductionParams

        app = BirthFlowerApp(root)
        layer = add_image_layer(app.document, tmp_path / "x.svg", name="x", x=10, y=10, width=50, height=50)
        app.document.selected_layer_id = layer.id
        app.layer_x_var.set("120")
        app.layer_y_var.set("140")
        app.layer_w_var.set("260")
        app.layer_h_var.set("180")

        app._apply_layer_production()

        assert (layer.x, layer.y, layer.width, layer.height) == (120, 140, 260, 180)
        assert isinstance(layer.production, ProductionParams)
        assert layer.production.x == 120 and layer.production.width == 260
    finally:
        root.destroy()


def test_apply_layer_production_rejects_nonpositive_size(tmp_path, monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")
    try:
        app = BirthFlowerApp(root)
        layer = add_image_layer(app.document, tmp_path / "x.svg", name="x", x=10, y=10, width=50, height=50)
        app.document.selected_layer_id = layer.id
        app.layer_x_var.set("0")
        app.layer_y_var.set("0")
        app.layer_w_var.set("0")  # 非法宽
        app.layer_h_var.set("100")
        errors = []
        monkeypatch.setattr(ui_app_module.messagebox, "showerror", lambda *a, **k: errors.append(a))

        app._apply_layer_production()

        assert errors  # 弹了错误
        assert layer.production is None  # 未写入 override
        assert (layer.x, layer.y, layer.width, layer.height) == (10, 10, 50, 50)  # 几何不变
    finally:
        root.destroy()


def test_parse_missing_field_hints_flags_only_none_fields():
    # 图2 弹窗：只把 None/空 的字段列为「需人工确认」。
    from ui_app import parse_missing_field_hints

    result = SimpleNamespace(text="", month=None, font=2, flower=None)
    fields = [field for field, _hint in parse_missing_field_hints(result)]
    assert fields == ["内容", "月份", "花材"]  # font 有值 → 不列入


def test_parse_missing_field_hints_empty_when_all_present():
    from ui_app import parse_missing_field_hints

    result = SimpleNamespace(text="Lacey", month=9, font=3, flower=1)
    assert parse_missing_field_hints(result) == []


def test_show_parse_warning_dialog_builds_without_error():
    # 图2 弹窗：主题化弹窗能构造（取代原生 messagebox），不抛异常。
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")
    try:
        app = BirthFlowerApp(root)
        before = len(root.winfo_children())
        result = SimpleNamespace(text="", month=None, font=None, flower=None, warnings=["GPT: x", "本地: y"])
        app._show_parse_warning_dialog(result)
        assert len(root.winfo_children()) > before  # 作为 Toplevel 子窗创建成功
    finally:
        root.destroy()


def test_month_chip_reflects_selected_flower_asset(tmp_path):
    # 月份/花序号映射已删；chip 改显选中素材的名称（display_name 优先）。
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")
    try:
        app = BirthFlowerApp(root)
        path = tmp_path / "March_Daffodil.svg"
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>', encoding="utf-8")
        asset = FlowerAsset(name="Daffodil", path=path, asset_key="march-daffodil", display_name="Daffodil")
        label = app._flower_label(asset)
        app.flower_label_map = {label: asset}
        app._set_pending_flower_asset(label, sync_fields=True)
        assert app.month_chip_var.get() == "Daffodil"
    finally:
        root.destroy()


def test_refresh_library_choices_lists_image_libraries(tmp_path):
    # 增量3：素材库下拉数据驱动自 active_bundle。
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")
    try:
        from config_store import with_product_library_dirs

        app = BirthFlowerApp(root)
        lib_a = tmp_path / "liba"
        lib_b = tmp_path / "libb"
        lib_a.mkdir()
        lib_b.mkdir()
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0h10v10H0z"/></svg>'
        (lib_a / "March_Daffodil.svg").write_text(svg, encoding="utf-8")
        (lib_b / "April_Daisy.svg").write_text(svg, encoding="utf-8")
        app.config = with_product_library_dirs(app.config, [lib_a, lib_b], [])
        app.flower_dir_var.set(str(lib_a))
        app._scan_assets(show_errors=False)
        assert len(app._image_lib_by_label) == 2


    finally:
        root.destroy()


def test_image_library_filter_narrows_flower_candidates(tmp_path):
    # 增量3：选中某素材库 → 素材候选只剩该库的素材。
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")
    try:
        from config_store import with_product_library_dirs

        app = BirthFlowerApp(root)
        lib_a = tmp_path / "liba"
        lib_b = tmp_path / "libb"
        lib_a.mkdir()
        lib_b.mkdir()
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0h10v10H0z"/></svg>'
        (lib_a / "March_Daffodil.svg").write_text(svg, encoding="utf-8")
        (lib_b / "April_Daisy.svg").write_text(svg, encoding="utf-8")
        app.config = with_product_library_dirs(app.config, [lib_a, lib_b], [])
        app.flower_dir_var.set(str(lib_a))
        app._scan_assets(show_errors=False)

        # 选第二个库（libb）→ 候选只含 daisy
        label_b = next(lbl for lbl, lib in app._image_lib_by_label.items() if lib.root.name == "libb")
        app.image_library_var.set(label_b)
        names = {asset.path.name for asset in app._assets_for_selected_image_library()}
        assert names == {"April_Daisy.svg"}
    finally:
        root.destroy()


def test_scan_assets_builds_multi_library_bundle(tmp_path):
    # 增量5：产品配了第二个素材库目录后，active_bundle 应含 2 个 image 库。
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")
    try:
        from config_store import with_product_library_dirs

        app = BirthFlowerApp(root)
        lib_a = tmp_path / "liba"
        lib_b = tmp_path / "libb"
        lib_a.mkdir()
        lib_b.mkdir()
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0h10v10H0z"/></svg>'
        (lib_a / "March_Daffodil.svg").write_text(svg, encoding="utf-8")
        (lib_b / "April_Daisy.svg").write_text(svg, encoding="utf-8")
        app.config = with_product_library_dirs(app.config, [lib_a, lib_b], [])
        app.flower_dir_var.set(str(lib_a))  # 主库目录入口与首库一致

        app._scan_assets(show_errors=False)

        assert len(app.active_bundle.image_libraries) == 2
        total_entries = sum(len(lib.entries) for lib in app.active_bundle.image_libraries)
        assert total_entries >= 2
    finally:
        root.destroy()


def test_layer_effective_production_resolves_override_over_slot(tmp_path):
    # 增量4：resolve_chain 回落——override 字段生效，未覆盖字段回落槽位默认。
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is not available")
    try:
        from production import ProductionParams

        app = BirthFlowerApp(root)
        layer = add_image_layer(app.document, tmp_path / "x.svg", name="x")
        layer.production = ProductionParams(x=333, width=99)  # 仅覆盖 x/width
        effective = app._layer_effective_production(layer)
        slot = app._slot_defaults(layer)
        assert effective.x == 333
        assert effective.width == 99
        assert effective.y == slot.y  # 未 override → 回落槽位默认
    finally:
        root.destroy()


# ---- 内联编辑：固定字号、文本框随墨迹实时变动、以框中心为锚 ----
# _resize_text_box_to_font 只依赖 self.document.canvas_width/height，故用「假 self + 解绑方法」
# 直接测，免建整套 Tk UI（headless 易碎）。

def _resize_fake_app(canvas_width=1492, canvas_height=1140):
    return SimpleNamespace(document=SimpleNamespace(canvas_width=canvas_width, canvas_height=canvas_height))


def test_resize_text_box_to_font_widens_with_ink_and_keeps_center():
    # 固定字号下，更长文字 → 框更宽（框随墨迹）；且以原框中心为锚（文字中心不跳）。
    pytest.importorskip("PIL")
    app = _resize_fake_app()
    layer = TextLayer(
        original_text="Al", font_size=120, x=500, y=400,
        width=200, height=120, text_box_width=200, text_box_height=120,
    )
    cx0 = layer.x + layer.text_box_width / 2
    cy0 = layer.y + layer.text_box_height / 2
    BirthFlowerApp._resize_text_box_to_font(app, layer, clamp_to_safe_area=False)
    short_w = layer.text_box_width
    assert abs((layer.x + layer.text_box_width / 2) - cx0) < 1
    assert abs((layer.y + layer.text_box_height / 2) - cy0) < 1

    layer.original_text = "Alexandria"
    BirthFlowerApp._resize_text_box_to_font(app, layer, clamp_to_safe_area=False)
    assert layer.text_box_width > short_w


def test_resize_text_box_to_font_unbounded_overflows_safe_area_while_clamped_caps():
    # clamp=False（内联编辑）：大字号下框越过画布安全区、返回 True、不缩框到安全区；
    # clamp=True（默认/新建/属性面板）：封顶到安全区、返回 True。
    pytest.importorskip("PIL")
    from text_layout import SAFE_MARGIN_X

    app = _resize_fake_app(canvas_width=600, canvas_height=400)
    safe_w = 600 - 2 * SAFE_MARGIN_X

    free = TextLayer(original_text="Patty", font_size=2000, x=0, y=0,
                     width=10, height=10, text_box_width=10, text_box_height=10)
    exceeds = BirthFlowerApp._resize_text_box_to_font(app, free, clamp_to_safe_area=False)
    assert exceeds is True
    assert free.text_box_width > safe_w  # 不封顶：框自由越界，字号守恒

    capped = TextLayer(original_text="Patty", font_size=2000, x=0, y=0,
                       width=10, height=10, text_box_width=10, text_box_height=10)
    clamped = BirthFlowerApp._resize_text_box_to_font(app, capped, clamp_to_safe_area=True)
    assert clamped is True
    assert capped.text_box_width <= safe_w + 1  # 封顶到安全区


# ── 生成成功后入队「AI已处理」标记回写（_enqueue_mark_done_after_generate）──


def _mark_world(monkeypatch):
    """patch run_background 同步执行 + 捕获 inbox_client.request_mark 调用。返回捕获 dict。"""
    captured: dict = {}
    monkeypatch.setattr(ui_app_module, "run_background", lambda root, work, done, err: done(work()))

    def fake_request_mark(url, *, order_id, action):
        captured.update(url=url, order_id=order_id, action=action)
        return {"order_id": order_id, "action": action, "status": "pending"}

    monkeypatch.setattr(ui_app_module.inbox_client, "request_mark", fake_request_mark)
    return captured


def test_enqueue_mark_done_uses_current_order_number(monkeypatch):
    captured = _mark_world(monkeypatch)
    fake = SimpleNamespace(
        current_order_number="4090000003",
        _inbox_active=None,
        _inbox_service_url="http://h:8770",
        root=None,
        warning_var=SimpleNamespace(set=lambda *_: None),
    )
    BirthFlowerApp._enqueue_mark_done_after_generate(fake)
    assert captured == {"url": "http://h:8770", "order_id": "4090000003", "action": "mark_done"}


def test_enqueue_mark_done_falls_back_to_inbox_filename(monkeypatch):
    captured = _mark_world(monkeypatch)
    fake = SimpleNamespace(
        current_order_number="",
        _db_order_active_id=None,
        _inbox_active=Path(r"C:\x\outputs\inbox\4090000099.json"),
        _inbox_service_url="http://h:8770",
        root=None,
        warning_var=SimpleNamespace(set=lambda *_: None),
    )
    BirthFlowerApp._enqueue_mark_done_after_generate(fake)
    assert captured["order_id"] == "4090000099"
    assert captured["action"] == "mark_done"


def test_enqueue_mark_done_skips_when_no_order_id(monkeypatch):
    captured = _mark_world(monkeypatch)
    fake = SimpleNamespace(
        current_order_number="",
        _db_order_active_id=None,
        _inbox_active=None,
        _inbox_service_url="http://h:8770",
        root=None,
        warning_var=SimpleNamespace(set=lambda *_: None),
    )
    BirthFlowerApp._enqueue_mark_done_after_generate(fake)
    assert captured == {}  # 没有订单号 → 不入队


# ── 配置端「标签」列：mark_status_style + order_row_view 标记派生 ──


def test_mark_status_style_prefers_done():
    assert mark_status_style([{"action": "mark_done", "status": "done"}])[0] == "AI已处理 ✓"
    # done 优先于 unrecognized：生成后 mark_done 待写 + 未识别已写 → 显已处理·待写
    assert mark_status_style(
        [{"action": "mark_done", "status": "pending"}, {"action": "mark_unrecognized", "status": "done"}]
    )[0] == "AI已处理·待写"
    assert mark_status_style([{"action": "mark_done", "status": "failed"}])[0] == "AI已处理·失败"


def test_mark_status_style_unrecognized_and_empty():
    assert mark_status_style([{"action": "mark_unrecognized", "status": "done"}])[0] == "AI未识别"
    assert mark_status_style([{"action": "mark_unrecognized", "status": "pending"}])[0] == "AI未识别·待写"
    assert mark_status_style([])[0] == "—"
    assert mark_status_style(None)[0] == "—"


def test_order_row_view_includes_mark_label():
    view = order_row_view(
        {"order_id": "4090000001", "mark_jobs": [{"action": "mark_unrecognized", "status": "pending"}]}
    )
    assert view["mark_label"] == "AI未识别·待写"
    # 无 mark_jobs + 默认 pending → 用 AI 权威态兜底显示「待识别」（不再退化成「—」）
    assert order_row_view({"order_id": "X"})["mark_label"] == "待识别"


def test_order_row_view_recognized_without_mark_jobs_shows_done():
    """recognized 且无打标历史（mark_jobs 空）→ 用权威态兜底显示「AI已处理」，不退化成「—」。"""
    assert order_row_view({"order_id": "X", "ai_status": "recognized"})["mark_label"] == "AI已处理"
    # recognized 有 mark_done 历史 → 保留写状态细节
    view = order_row_view(
        {"order_id": "Y", "ai_status": "recognized", "mark_jobs": [{"action": "mark_done", "status": "done"}]}
    )
    assert view["mark_label"] == "AI已处理 ✓"


# ── AI 识别状态对账：ai_status_style + order_row_view 消费 ai_status / 复核筛选标记 ──


def test_ai_status_style_conflict_and_locked():
    assert ai_status_style("conflict")[0] == "复核"
    assert ai_status_style("locked")[0] == "人工锁定"
    # pending/recognized/None → 不醒目，回退 mark_status_style（返回 None）
    assert ai_status_style("pending") is None
    assert ai_status_style("recognized") is None
    assert ai_status_style(None) is None


def test_order_row_view_conflict_overrides_mark_label_and_flags_review():
    """复核态：标签列显示「复核」并覆盖 mark 写状态；needs_review=True 驱动筛选/着色。"""
    view = order_row_view(
        {
            "order_id": "4100000002",
            "ai_status": "conflict",
            "mark_jobs": [{"action": "mark_unrecognized", "status": "pending"}],
        }
    )
    assert view["mark_label"] == "复核"
    assert view["needs_review"] is True
    assert view["ai_status"] == "conflict"


def test_order_row_view_non_conflict_keeps_mark_writeback_label():
    """recognized/pending：仍显示 mark 写状态细节，needs_review=False（不进复核筛选）。"""
    view = order_row_view(
        {
            "order_id": "4100000003",
            "ai_status": "recognized",
            "mark_jobs": [{"action": "mark_done", "status": "done"}],
        }
    )
    assert view["mark_label"] == "AI已处理 ✓"
    assert view["needs_review"] is False
    # 缺省 ai_status（旧订单 dict）→ pending，不进复核
    assert order_row_view({"order_id": "X"})["needs_review"] is False
    assert order_row_view({"order_id": "X"})["ai_status"] == "pending"


# ── 选端页（门厅）：预混配色 / 角色元数据 / 管理员密码门 gating ──


def test_blend_hex_flattens_over_opaque_bg():
    assert _blend_hex("#ffffff", "#000000", 0.5) == "#808080"
    assert _blend_hex("#2fd4a8", "#101218", 0.0) == "#101218"  # alpha 0 = 纯底色
    assert _blend_hex("#2fd4a8", "#101218", 1.0) == "#2fd4a8"  # alpha 1 = 纯前景


def test_entry_role_meta_covers_three_ends():
    assert set(ENTRY_ROLE_META) == {VIEW_OPERATOR, VIEW_OPERATOR_CONFIG, VIEW_ADMIN}
    for icon, accent, title, desc in ENTRY_ROLE_META.values():
        assert icon and accent.startswith("#") and title and desc


def test_admin_gate_success_from_switch_uses_apply_view():
    calls = []
    fake = SimpleNamespace(
        _admin_authed=False,
        _view_overlay=None,  # 无遮罩（从顶部切端触发）
        _apply_view=lambda role: calls.append(("apply", role)),
        _enter_view=lambda role: calls.append(("enter", role)),
    )
    BirthFlowerApp._admin_gate_success(fake)
    assert fake._admin_authed is True
    assert calls == [("apply", VIEW_ADMIN)]


def test_admin_gate_success_from_overlay_uses_enter_view():
    calls = []
    fake = SimpleNamespace(
        _admin_authed=False,
        _view_overlay=object(),  # 有遮罩（从门厅触发）→ 连遮罩一起关
        _apply_view=lambda role: calls.append(("apply", role)),
        _enter_view=lambda role: calls.append(("enter", role)),
    )
    BirthFlowerApp._admin_gate_success(fake)
    assert calls == [("enter", VIEW_ADMIN)]


def _switch_view_fake(authed: bool):
    calls = []
    fake = SimpleNamespace(
        _admin_authed=authed,
        active_view=VIEW_OPERATOR,
        active_view_var=SimpleNamespace(set=lambda v: calls.append(("set", v))),
        _enter_admin_view=lambda: calls.append(("gate",)),
        _apply_view=lambda role: calls.append(("apply", role)),
    )
    return fake, calls


def test_switch_to_admin_unauthed_always_gates_even_without_password():
    # 回归护栏：未鉴权切管理员端必须过门（_enter_admin_view），即使尚未设密码也不得直进——堵下拉鉴权绕过。
    fake, calls = _switch_view_fake(authed=False)
    BirthFlowerApp._on_switch_view(fake, ui_app_module.VIEW_LABELS[VIEW_ADMIN])
    assert ("gate",) in calls
    assert all(c[0] != "apply" for c in calls)  # 绝不直接 _apply_view 进管理员端


def test_switch_to_admin_after_authed_applies_directly():
    fake, calls = _switch_view_fake(authed=True)
    BirthFlowerApp._on_switch_view(fake, ui_app_module.VIEW_LABELS[VIEW_ADMIN])
    assert calls == [("apply", VIEW_ADMIN)]  # 本次已鉴权 → 自由切，不再问


# ===== 一单多件：文件名「-k」后缀防覆盖（target_box_piece_count + piece-suffix helpers） =====

class _FakeVar:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


def _piece_app(*, parsed, index, db_id, db_count, current_no, filename):
    """造一个只带文件名/件数相关字段的 App 桩，绕开 __init__（headless 无 Tk）。"""
    app = BirthFlowerApp.__new__(BirthFlowerApp)
    app.parsed_orders = parsed
    app._parsed_order_index = index
    app._db_order_active_id = db_id
    app._db_order_piece_count = db_count
    app.current_order_number = current_no
    app.filename_template_var = _FakeVar(filename)
    return app


def test_target_box_piece_count_sums_only_target_boxes():
    order = {"items": [
        {"quantity": 2, "is_target_box": True},
        {"quantity": 1, "is_target_box": True},
        {"quantity": 5, "is_target_box": False},  # 其他商品不雕刻不计
    ]}
    assert target_box_piece_count(order) == 3  # 2 + 1
    assert target_box_piece_count({"items": []}) == 0
    assert target_box_piece_count({}) == 0
    # quantity 缺失/0 的目标盒子行仍按 1 件算
    assert target_box_piece_count({"items": [{"is_target_box": True}, {"quantity": 0, "is_target_box": True}]}) == 2


def test_with_piece_suffix_only_when_multi_piece():
    # 库件数 4 → 当前第 2 笔 → 订单号-2
    app = _piece_app(parsed=[1, 2, 3, 4], index=1, db_id="A1", db_count=4, current_no="A1", filename="A1")
    assert app._with_piece_suffix("A1") == "A1-2"
    assert app._piece_index_total() == (2, 4)
    # 单件（库件数 1、队列 1）→ 不加后缀
    single = _piece_app(parsed=[1], index=0, db_id="A1", db_count=1, current_no="A1", filename="A1")
    assert single._with_piece_suffix("A1") == "A1"


def test_piece_total_falls_back_to_queue_length_without_db_count():
    # 手填粘贴单：无可信库件数 → 用解析队列长度
    app = _piece_app(parsed=[1, 2, 3], index=2, db_id=None, db_count=0, current_no="B9", filename="B9")
    assert app._piece_index_total() == (3, 3)
    assert app._with_piece_suffix("B9") == "B9-3"


def test_piece_total_trusts_db_count_when_order_number_blanked():
    # 逐件解析把 order_number 留空 → 仍按库订单号兜底信库件数
    app = _piece_app(parsed=[1, 2], index=1, db_id="C3", db_count=4, current_no="", filename="C3-1")
    assert app._piece_index_total() == (2, 4)


def test_update_piece_filename_overwrites_auto_value_only():
    # 文件名框是自动值（订单号 / 订单号-数字）→ 覆盖成新后缀
    app = _piece_app(parsed=[1, 2, 3, 4], index=2, db_id="A1", db_count=4, current_no="A1", filename="A1-1")
    app._update_piece_filename()
    assert app.filename_template_var.get() == "A1-3"
    # 操作员手改成别的名字 → 保留不动
    custom = _piece_app(parsed=[1, 2, 3, 4], index=2, db_id="A1", db_count=4, current_no="A1", filename="给客户的礼物")
    custom._update_piece_filename()
    assert custom.filename_template_var.get() == "给客户的礼物"
