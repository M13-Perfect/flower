import pytest

from birth_flower_parser import parse_order_remark


@pytest.mark.parametrize(
    ("remark", "expected"),
    [
        (
            "Name: Lily, March, font 2, flower 1",
            {"text": "Lily", "month": 3, "font": 2, "flower": 1},
        ),
        (
            "姓名：小雅 五月 font ３ flower ２",
            {"text": "小雅", "month": 5, "font": 3, "flower": 2},
        ),
        (
            "ชื่อ: Mali เดือนมกราคม font ๑ flower ๒",
            {"text": "Mali", "month": 1, "font": 1, "flower": 2},
        ),
        (
            "tên: An tháng tám font 4 flower 1",
            {"text": "An", "month": 8, "font": 4, "flower": 1},
        ),
        (
            "nama: Sari bulan Oktober font ٢ flower ١",
            {"text": "Sari", "month": 10, "font": 2, "flower": 1},
        ),
        (
            "Text=Noel December font ４ flower ２",
            {"text": "Noel", "month": 12, "font": 4, "flower": 2},
        ),
        (
            "Name: Aiko ７月 font 2 flower 1",
            {"text": "Aiko", "month": 7, "font": 2, "flower": 1},
        ),
        (
            "ชื่อ: Dao เดือนกุมภาพันธ์ font 3 flower 1",
            {"text": "Dao", "month": 2, "font": 3, "flower": 1},
        ),
    ],
)
def test_parse_multilingual_order_remark(remark, expected):
    result = parse_order_remark(remark)

    assert result.text == expected["text"]
    assert result.month == expected["month"]
    assert result.font == expected["font"]
    assert result.flower == expected["flower"]
    assert result.warnings == []
    assert result.confidence >= 0.9


def test_parse_normalizes_unicode_digits_and_warns_about_missing_parts():
    result = parse_order_remark("Name: Hana month １２ font ９")

    assert result.text == "Hana"
    assert result.month == 12
    assert result.font is None
    assert result.flower is None
    assert "font 只能是 1-4" in result.warnings
    assert "未识别 flower 1-2" in result.warnings
    assert result.confidence < 0.8


@pytest.mark.parametrize(
    ("remark", "expected"),
    [
        (
            "Name: Ava March font 2 flower Cherry Blossom",
            {"text": "Ava", "month": 3, "font": 2, "flower": 2},
        ),
        (
            "Name: Mei font 1 Daisy",
            {"text": "Mei", "month": 4, "font": 1, "flower": 1},
        ),
        (
            "Name: Lily May font 1 flower Lily of the valley",
            {"text": "Lily", "month": 5, "font": 1, "flower": 1},
        ),
    ],
)
def test_parse_flower_name_selects_matching_month_flower(remark, expected):
    result = parse_order_remark(remark)

    assert result.text == expected["text"]
    assert result.month == expected["month"]
    assert result.font == expected["font"]
    assert result.flower == expected["flower"]
    assert result.warnings == []


def test_parse_does_not_treat_customer_name_as_flower_name():
    result = parse_order_remark("Name: Rose June font 1")

    assert result.text == "Rose"
    assert result.month == 6
    assert result.font == 1
    assert result.flower is None
    assert "未识别 flower 1-2" in result.warnings


def test_parse_shopify_personalization_field_from_current_order_format():
    result = parse_order_remark(
        "Choose Your Birth Flower : Jun - RoseFont Design : Font 1Personalization : Pam"
    )

    assert result.text == "Pam"
    assert result.month == 6
    assert result.font == 1
    assert result.flower == 1
    assert result.warnings == []
