"""ProductConfig 注册中心字段：迁移 + 状态 + 序列化往返。"""
from __future__ import annotations

from config_store import (
    AppConfig,
    ProductConfig,
    _product_from_payload,
    _product_to_payload,
    with_product_status,
)


def test_legacy_product_payload_migrates_defaults():
    # 旧配置（无 status，或含已废弃的 gimp_template_id 键）→ 迁移为 active 且忽略未知键，不报错。
    p = _product_from_payload({"id": "birth-flower-card", "name": "生日花卡", "gimp_template_id": "x"})
    assert p.status == "active"


def test_payload_roundtrip_preserves_status():
    p = ProductConfig(id="glasses", name="眼镜", status="disabled")
    back = _product_from_payload(_product_to_payload(p))
    assert back.status == "disabled"


def test_with_product_status():
    cfg = AppConfig(products=(ProductConfig(id="p1", name="P1"),), active_product_id="p1")
    cfg = with_product_status(cfg, "disabled", product_id="p1")
    assert cfg.products[0].status == "disabled"


def test_with_product_status_rejects_bad_value():
    cfg = AppConfig(products=(ProductConfig(id="p1", name="P1"),), active_product_id="p1")
    try:
        with_product_status(cfg, "deleted", product_id="p1")
        assert False, "应拒绝非法状态"
    except ValueError:
        pass


def test_default_config_products_unaffected():
    # 全新默认配置（__post_init__ 合成产品0）仍可用且 status=active。
    cfg = AppConfig()
    assert cfg.products and cfg.products[0].status == "active"
