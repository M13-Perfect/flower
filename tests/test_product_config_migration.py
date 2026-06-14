"""AppConfig 产品体系 + 旧配置零感知迁移单测（见 ExecPlan Task 1 Step 4）。"""

from __future__ import annotations

import json
from pathlib import Path

from config_store import AppConfig, ProductConfig, active_product, load_config, save_config


def test_default_appconfig_synthesizes_product_zero():
    config = AppConfig()
    assert config.products, "products 不应为空（__post_init__ 迁移合成）"
    product = config.products[0]
    assert product.id == "birth-flower-card"
    assert product.image_library_dirs == (config.flower_dir,)
    assert product.font_library_dirs == (config.font_source,)
    assert product.defaults == config.layout_defaults
    assert config.active_product_id == "birth-flower-card"


def test_load_legacy_config_without_products_migrates(tmp_path: Path):
    cfg = tmp_path / "c.json"
    cfg.write_text(
        json.dumps(
            {"flower_dir": "my flowers", "font_source": "my.ttf", "layout_defaults": {"canvas_width": 2000}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = load_config(cfg)
    product = active_product(config)
    assert product.image_library_dirs == (Path("my flowers"),)
    assert product.font_library_dirs == (Path("my.ttf"),)
    assert product.defaults.canvas_width == 2000


def test_round_trip_products(tmp_path: Path):
    cfg = tmp_path / "c.json"
    source = AppConfig(
        products=(ProductConfig(id="zodiac", name="星座", image_library_dirs=(Path("z"),)),),
        active_product_id="zodiac",
    )
    save_config(source, cfg)
    loaded = load_config(cfg)
    assert any(p.id == "zodiac" for p in loaded.products)
    assert active_product(loaded).id == "zodiac"
    assert active_product(loaded).image_library_dirs == (Path("z"),)


def test_explicit_products_not_overwritten_by_migration(tmp_path: Path):
    cfg = tmp_path / "c.json"
    cfg.write_text(
        json.dumps({"products": [{"id": "foo", "name": "Foo"}], "active_product_id": "foo"}, ensure_ascii=False),
        encoding="utf-8",
    )
    config = load_config(cfg)
    assert {p.id for p in config.products} == {"foo"}  # 未被合成的 birth-flower-card 覆盖
    assert active_product(config).id == "foo"
