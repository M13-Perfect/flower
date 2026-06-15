"""Phase 4 产品切换器（方案2）的纯逻辑单测：配置往返 + id 去重 + 展示数据。

不实例化 Tkinter App（沿用 test_ui_app 的「测模块级纯函数」约定）。
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

from config_store import (
    AppConfig,
    ProductConfig,
    active_product,
    load_config,
    save_config,
    unique_product_id,
    with_added_product,
    with_product_library_dirs,
)
from ui_app import product_initial, product_rail_items


def _two_product_config() -> AppConfig:
    return AppConfig(
        products=(
            ProductConfig(id="birth-flower-card", name="生日花卡"),
            ProductConfig(id="wood-sign", name="Wood Sign"),
        ),
        active_product_id="wood-sign",
    )


def test_products_panel_collapsed_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    save_config(AppConfig(products_panel_collapsed=False), path)
    assert load_config(path).products_panel_collapsed is False


def test_products_panel_collapsed_defaults_true_when_missing(tmp_path: Path) -> None:
    # 旧配置没有该字段 → 默认收起。
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    assert load_config(path).products_panel_collapsed is True


def test_unique_product_id_dedupes() -> None:
    assert unique_product_id("Wood Sign", []) == "wood-sign"
    assert unique_product_id("Wood Sign", ["wood-sign"]) == "wood-sign-2"
    assert unique_product_id("Wood Sign", ["wood-sign", "wood-sign-2"]) == "wood-sign-3"


def test_unique_product_id_falls_back_for_non_ascii() -> None:
    assert unique_product_id("木牌", []) == "product"
    assert unique_product_id("木牌", ["product"]) == "product-2"


def test_with_added_product_appends_and_activates() -> None:
    base = AppConfig()  # __post_init__ 迁移出「产品0」
    before = len(base.products)
    config = with_added_product(base, ProductConfig(id="wood-sign", name="Wood Sign"), activate=True)
    assert len(config.products) == before + 1
    assert config.active_product_id == "wood-sign"
    assert active_product(config).id == "wood-sign"


def test_with_added_product_keeps_active_when_not_activating() -> None:
    base = AppConfig()
    keep = base.active_product_id
    config = with_added_product(base, ProductConfig(id="x", name="X"), activate=False)
    assert config.active_product_id == keep
    assert any(product.id == "x" for product in config.products)


def test_settings_replace_preserves_products_and_collapse() -> None:
    # 守护 _save_settings_window 改用 replace 后的行为：换 flower_dir 不丢产品/激活/收展。
    config = dataclasses.replace(_two_product_config(), products_panel_collapsed=False)
    rebuilt = dataclasses.replace(config, flower_dir=Path("other"))
    assert [p.id for p in rebuilt.products] == ["birth-flower-card", "wood-sign"]
    assert rebuilt.active_product_id == "wood-sign"
    assert rebuilt.products_panel_collapsed is False


def test_product_rail_items_marks_active_and_initial() -> None:
    items = product_rail_items(_two_product_config())
    assert [i["id"] for i in items] == ["birth-flower-card", "wood-sign"]
    active = [i for i in items if i["active"]]
    assert len(active) == 1 and active[0]["id"] == "wood-sign"
    assert items[0]["initial"] == "生"
    assert items[1]["initial"] == "W"


def test_product_initial_handles_blank() -> None:
    assert product_initial("") == "?"
    assert product_initial("  ") == "?"
    assert product_initial("apple") == "A"


def test_with_product_library_dirs_updates_active_product_only() -> None:
    # 增量5：只改激活产品的库目录列表，其余产品原样保留；首目录回写顶层迁移入口。
    config = with_product_library_dirs(
        _two_product_config(),
        [Path("libs/a"), Path("libs/b")],
        [Path("fonts/x")],
    )
    active = active_product(config)
    assert active.id == "wood-sign"
    assert active.image_library_dirs == (Path("libs/a"), Path("libs/b"))
    assert active.font_library_dirs == (Path("fonts/x"),)
    # 另一个产品没被动
    other = next(p for p in config.products if p.id == "birth-flower-card")
    assert other.image_library_dirs == ()
    # 首目录回写顶层 flower_dir/font_source（迁移兼容入口）
    assert config.flower_dir == Path("libs/a")
    assert config.font_source == Path("fonts/x")


def test_with_product_library_dirs_empty_keeps_top_level() -> None:
    # 空列表不覆盖顶层 flower_dir/font_source
    base = dataclasses.replace(_two_product_config(), flower_dir=Path("keep"), font_source=Path("keep.ttf"))
    config = with_product_library_dirs(base, [], [])
    assert config.flower_dir == Path("keep")
    assert config.font_source == Path("keep.ttf")
    assert active_product(config).image_library_dirs == ()


def test_with_product_library_dirs_round_trips_through_save(tmp_path: Path) -> None:
    cfg = tmp_path / "c.json"
    config = with_product_library_dirs(
        _two_product_config(), [Path("libs/a"), Path("libs/b")], [Path("fonts/x")]
    )
    save_config(config, cfg)
    reloaded = load_config(cfg)
    active = active_product(reloaded)
    assert active.image_library_dirs == (Path("libs/a"), Path("libs/b"))
    assert active.font_library_dirs == (Path("fonts/x"),)
