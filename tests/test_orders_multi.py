"""多订单识别（一次粘贴多笔订单）解析层测试。

覆盖：多订单 schema 解析与字段校验、前台提示词接进 API、AI/本地两条路径、订单块切分。
真实订单格式：每块第一行=订单号，其余=出生花/字体/个性化内容（见 test.txt）。
"""

from __future__ import annotations

import json

import pytest

from gpt_parser import (
    ORDERS_SCHEMA,
    build_orders_system_prompt,
    parse_orders_payload,
    parse_orders_with_gpt,
)
from models import AIParseConfig, ParseResult
from parse_pipeline import parse_orders_auto, split_order_blocks


REAL_ORDER = (
    "4090627965\n"
    "Choose Your Birth Flower  ：Dec - Narcissus\n"
    "Font Design  ：Font 4\n"
    "Personalization  ：#1 Mom      Kicking Ass & Taking Names!\n"
    "\n"
    "4093542955\n"
    "Choose Your Birth Flower  ：Jun - Honeysuckle\n"
    "Font Design  ：Font 3\n"
    "Personalization  ：Esther\n"
    "GiftMessage  ：Happy birthday my dearest Esther!\n"
    "\n"
    "4093587551\n"
    "Choose Your Birth Flower  ：Jul - Waterlily\n"
    "Font Design  ：Font 4\n"
    "Personalization  ：Michelle\n"
    "\n"
    "4093626247\n"
    "Choose Your Birth Flower  ：May - Lily of the Valley\n"
    "Font Design  ：Font 3\n"
    "Personalization  ：Celia\n"
)


def test_parse_orders_payload_bounds_and_strips():
    payload = {
        "orders": [
            {
                "order_number": " 4090627965 ",
                "quantity": 2,
                "month": 13,  # 越界 → None
                "flower_name": " Narcissus ",
                "flower": 2,
                "font": 9,  # 越界 → None
                "text": "  Amy  ",
                "gift_message": " hi ",
                "warnings": ["x", ""],
                "confidence": 1.5,  # clamp → 1.0
            }
        ]
    }
    [result] = parse_orders_payload(payload)
    assert result.order_number == "4090627965"
    assert result.quantity == 2
    assert result.month is None
    assert result.flower == 2
    assert result.font is None
    assert result.text == "Amy"
    assert result.flower_name == "Narcissus"
    assert result.gift_message == "hi"
    assert result.warnings == ["x"]
    assert result.confidence == 1.0


def test_parse_orders_payload_collapses_internal_spaces_in_text():
    # 连续无效空格（影响生产）合并成单个，首尾去白。
    [result] = parse_orders_payload(
        {"orders": [{"text": "  #1 Mom      Kicking Ass & Taking Names!  "}]}
    )
    assert result.text == "#1 Mom Kicking Ass & Taking Names!"


def test_parse_orders_payload_handles_single_object_fallback():
    # 模型偶尔不包 orders 直接返回单条，也要容错成 1 元素列表。
    [result] = parse_orders_payload({"text": "Lacey", "month": 9, "font": 3, "flower": 1})
    assert result.text == "Lacey"
    assert result.month == 9


def test_parse_orders_payload_empty_on_garbage():
    assert parse_orders_payload({}) == []
    assert parse_orders_payload({"orders": "nope"}) == []


def test_build_orders_system_prompt_is_frontend_only():
    # 本地脚手架/业务规则已删除：提示词 100% 来自前台。空入参 → 空串（结构由 schema 兜底）。
    assert build_orders_system_prompt(None, None) == ""
    # 传入的规则原样拼接；背景词以【背景】另附；不再有任何本地脚手架/业务规则文案。
    combined = build_orders_system_prompt("自定义提取规则", "木盒礼品语境")
    assert "自定义提取规则" in combined
    assert "【背景】木盒礼品语境" in combined
    assert "【提取规则】" not in combined
    assert "雕刻订单解析器" not in combined


def test_parse_orders_with_gpt_openai_wires_schema_and_prompt():
    captured: dict = {}

    def fake_post(url, payload, headers, timeout):
        captured["payload"] = payload
        return {
            "output_text": json.dumps(
                {
                    "orders": [
                        {
                            "order_number": "4090627965",
                            "quantity": 1,
                            "month": 12,
                            "flower_name": "Narcissus",
                            "flower": 2,
                            "font": 4,
                            "text": "#1 Mom Kicking Ass & Taking Names!",
                            "gift_message": "",
                            "warnings": [],
                            "confidence": 0.97,
                        },
                        {
                            "order_number": "4093542955",
                            "quantity": 1,
                            "month": 6,
                            "flower_name": "Honeysuckle",
                            "flower": 2,
                            "font": 3,
                            "text": "Esther",
                            "gift_message": "Happy birthday my dearest Esther!",
                            "warnings": [],
                            "confidence": 0.95,
                        },
                    ]
                }
            )
        }

    results = parse_orders_with_gpt(REAL_ORDER, api_key="k", provider="openai", http_post=fake_post)

    assert [r.order_number for r in results] == ["4090627965", "4093542955"]
    assert results[0].month == 12 and results[0].flower == 2 and results[0].font == 4
    assert results[1].gift_message == "Happy birthday my dearest Esther!"
    # 发出去的是多订单 schema；系统提示词只含前台内容（此处未传规则 → 空串，无本地脚手架）。
    assert captured["payload"]["text"]["format"]["schema"] is ORDERS_SCHEMA
    content = captured["payload"]["input"][0]["content"]
    assert "【提取规则】" not in content
    assert content == ""


def test_parse_orders_with_gpt_uses_custom_prompt():
    captured: dict = {}

    def fake_post(url, payload, headers, timeout):
        captured["payload"] = payload
        return {"output_text": json.dumps({"orders": []})}

    parse_orders_with_gpt(
        "x", api_key="k", provider="openai",
        system_prompt="只提取名字", background_prompt="礼品语境",
        http_post=fake_post,
    )
    content = captured["payload"]["input"][0]["content"]
    assert "只提取名字" in content
    assert "【背景】礼品语境" in content


def test_split_order_blocks_extracts_each_order_number():
    blocks = split_order_blocks(REAL_ORDER)
    assert [number for number, _qty, _text in blocks] == [
        "4090627965", "4093542955", "4093587551", "4093626247",
    ]


def test_split_order_blocks_reads_quantity_suffix():
    [(number, quantity, _text)] = split_order_blocks("29972194015x3\nName: A")
    assert number == "29972194015"
    assert quantity == 3


def test_parse_orders_auto_uses_orders_gpt_and_threads_prompt():
    config = AIParseConfig(
        enabled=True, prefer_ai=True, system_prompt="SP", background_prompt="BG"
    )
    captured: dict = {}

    def fake_orders(remark, **kwargs):
        captured.update(kwargs)
        return [ParseResult(text="A", month=1, font=1, flower=1, order_number="111")]

    results = parse_orders_auto("note", ai_config=config, gpt_orders_parser=fake_orders)

    assert [r.text for r in results] == ["A"]
    assert captured["system_prompt"] == "SP"
    assert captured["background_prompt"] == "BG"


def test_parse_orders_auto_raises_when_ai_fails():
    # 全局 AI：本地兜底已停用，AI 失败直接抛错（由 UI 提示），不再静默回退。
    config = AIParseConfig(enabled=True, prefer_ai=True)

    def boom(*_args, **_kwargs):
        raise RuntimeError("no api key")

    with pytest.raises(RuntimeError):
        parse_orders_auto("111111\nName: A", ai_config=config, gpt_orders_parser=boom)


def test_parse_orders_auto_uses_ai_even_when_ai_not_preferred():
    # 全局 AI：不再受「AI 优先」开关影响，始终调用 GPT。
    config = AIParseConfig(enabled=False, prefer_ai=False)
    called: list[str] = []

    def fake_orders(remark, **_kwargs):
        called.append(remark)
        return [ParseResult(text="AI")]

    results = parse_orders_auto("single block", ai_config=config, gpt_orders_parser=fake_orders)
    assert called == ["single block"]
    assert len(results) == 1
    assert results[0].text == "AI"
