from __future__ import annotations

from local_order_parser import parse_order_remark_local


def test_local_order_parser_adapts_web_order_parser_to_parse_result():
    result = parse_order_remark_local(
        "Customer Name: Ava Chen\n"
        "Birth Month: June\n"
        "Flower: Rose\n"
        "Font Design: Font 2\n"
        "Special Notes: Please keep the name centered."
    )

    assert result.text == "Ava Chen"
    assert result.month == 6
    assert result.font == 2
    assert result.flower == 1
    assert result.birth_month == "June"
    assert result.flower_name == "Rose"
    assert result.font_design == "Font 2"
    assert result.personalization_raw == "Ava Chen"
    assert result.personalization_type == "name"
    assert result.warnings == []
    assert result.confidence >= 0.9


def test_local_order_parser_falls_back_to_legacy_multilingual_rules():
    result = parse_order_remark_local(
        "t\u00ean: An th\u00e1ng t\u00e1m font 4 flower 1"
    )

    assert result.text == "An"
    assert result.month == 8
    assert result.font == 4
    assert result.flower == 1
    assert result.warnings == []
