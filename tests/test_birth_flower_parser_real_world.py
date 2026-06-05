from pathlib import Path

import pytest

from birth_flower_parser import parse_order_remark


REQUIRED_STRUCTURED_FIELDS = (
    "birth_month",
    "flower_name",
    "font_design",
    "personalization_raw",
    "personalization_type",
    "warnings",
    "parse_confidence",
)


REAL_WORLD_ORDER_NOTES = [
    pytest.param(
        "Choose Your Birth Flower  ：Jun - Rose\n"
        "Font Design  ：Font 4\n"
        "Personalization  ：Jazmin",
        {
            "birth_month": "Jun",
            "flower_name": "Rose",
            "font_design": "Font 4",
            "personalization_raw": "Jazmin",
            "personalization_type": "name",
        },
        id="01-jun-rose-font-4-jazmin",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Aug - Poppy\n"
        "Font Design  ：Font 2\n"
        "Personalization  ：I love you like no one else……Loves you!",
        {
            "birth_month": "Aug",
            "flower_name": "Poppy",
            "font_design": "Font 2",
            "personalization_raw": "I love you like no one else……Loves you!",
            "personalization_type": "message",
        },
        id="02-aug-poppy-font-2-message",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Jun - Honeysuckle\n"
        "Font Design  ：Font 4\n"
        "Personalization  ：Sara",
        {
            "birth_month": "Jun",
            "flower_name": "Honeysuckle",
            "font_design": "Font 4",
            "personalization_raw": "Sara",
            "personalization_type": "name",
        },
        id="03-jun-honeysuckle-font-4-sara",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Oct - Marigold\n"
        "Font Design  ：Font 1\n"
        "Personalization  ：Bonnie",
        {
            "birth_month": "Oct",
            "flower_name": "Marigold",
            "font_design": "Font 1",
            "personalization_raw": "Bonnie",
            "personalization_type": "name",
        },
        id="04-oct-marigold-font-1-bonnie",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Jul - Waterlily\n"
        "Font Design  ：Font 3\n"
        "Personalization  ：Cara",
        {
            "birth_month": "Jul",
            "flower_name": "Waterlily",
            "font_design": "Font 3",
            "personalization_raw": "Cara",
            "personalization_type": "name",
        },
        id="05-jul-waterlily-font-3-cara",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Apr - Daisy\n"
        "Font Design  ：Font 3\n"
        "Personalization  ：Lindsay",
        {
            "birth_month": "Apr",
            "flower_name": "Daisy",
            "font_design": "Font 3",
            "personalization_raw": "Lindsay",
            "personalization_type": "name",
        },
        id="06-apr-daisy-font-3-lindsay",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Nov - Peony\n"
        "Font Design  ：Font 3\n"
        "Personalization  ：Maria",
        {
            "birth_month": "Nov",
            "flower_name": "Peony",
            "font_design": "Font 3",
            "personalization_raw": "Maria",
            "personalization_type": "name",
        },
        id="07-nov-peony-font-3-maria",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Jun - Rose\n"
        "Font Design  ：Font 1\n"
        "Personalization  ：Sarah",
        {
            "birth_month": "Jun",
            "flower_name": "Rose",
            "font_design": "Font 1",
            "personalization_raw": "Sarah",
            "personalization_type": "name",
        },
        id="08-jun-rose-font-1-sarah",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Jun - Rose\n"
        "Font Design  ：Font 1\n"
        "Personalization  ：Anna",
        {
            "birth_month": "Jun",
            "flower_name": "Rose",
            "font_design": "Font 1",
            "personalization_raw": "Anna",
            "personalization_type": "name",
        },
        id="09-jun-rose-font-1-anna",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Jun - Rose\n"
        "Font Design  ：Font 3\n"
        "Personalization  ：Debbie",
        {
            "birth_month": "Jun",
            "flower_name": "Rose",
            "font_design": "Font 3",
            "personalization_raw": "Debbie",
            "personalization_type": "name",
        },
        id="10-jun-rose-font-3-debbie",
    ),
    pytest.param(
        "Choose Your Birth Flower  ：Jun - Rose\n"
        "Font Design  ：Font 4\n"
        "Personalization  ：Mom ❤️",
        {
            "birth_month": "Jun",
            "flower_name": "Rose",
            "font_design": "Font 4",
            "personalization_raw": "Mom ❤️",
            "personalization_type": "name",
        },
        id="11-jun-rose-font-4-mom-heart",
    ),
]


@pytest.mark.parametrize(("remark", "expected"), REAL_WORLD_ORDER_NOTES)
def test_parse_real_world_birth_flower_notes_into_structured_fields(remark, expected):
    result = parse_order_remark(remark)

    _assert_structured_fields_exist(result)
    assert result.birth_month == expected["birth_month"]
    assert result.flower_name == expected["flower_name"]
    assert result.font_design == expected["font_design"]
    assert result.personalization_raw == expected["personalization_raw"]
    assert result.personalization_type == expected["personalization_type"]
    assert result.warnings == []
    assert 0.9 <= result.parse_confidence <= 1.0


def test_parse_supports_half_width_colons_and_irregular_label_spacing():
    result = parse_order_remark(
        "  Choose Your Birth Flower:   Jun - Honeysuckle\n"
        "Font Design:Font 4\n"
        " Personalization   :   Sara  "
    )

    _assert_structured_fields_exist(result)
    assert result.birth_month == "Jun"
    assert result.flower_name == "Honeysuckle"
    assert result.font_design == "Font 4"
    assert result.personalization_raw == "Sara"
    assert result.personalization_type == "name"
    assert result.warnings == []


def test_parse_preserves_emoji_and_unicode_ellipsis_in_personalization_raw():
    message_result = parse_order_remark(
        "Choose Your Birth Flower  ：Aug - Poppy\n"
        "Font Design  ：Font 2\n"
        "Personalization  ：I love you like no one else……Loves you!"
    )
    emoji_result = parse_order_remark(
        "Choose Your Birth Flower  ：Jun - Rose\n"
        "Font Design  ：Font 4\n"
        "Personalization  ：Mom ❤️"
    )

    _assert_structured_fields_exist(message_result)
    _assert_structured_fields_exist(emoji_result)
    assert message_result.personalization_raw == "I love you like no one else……Loves you!"
    assert "..." not in message_result.personalization_raw
    assert emoji_result.personalization_raw == "Mom ❤️"
    assert emoji_result.personalization_type == "name"


def test_parse_uses_flower_name_from_choice_instead_of_inferring_from_month_only():
    rose_result = parse_order_remark(
        "Choose Your Birth Flower  ：Jun - Rose\n"
        "Font Design  ：Font 4\n"
        "Personalization  ：Jazmin"
    )
    honeysuckle_result = parse_order_remark(
        "Choose Your Birth Flower  ：Jun - Honeysuckle\n"
        "Font Design  ：Font 4\n"
        "Personalization  ：Sara"
    )

    _assert_structured_fields_exist(rose_result)
    _assert_structured_fields_exist(honeysuckle_result)
    assert rose_result.birth_month == "Jun"
    assert honeysuckle_result.birth_month == "Jun"
    assert rose_result.flower_name == "Rose"
    assert honeysuckle_result.flower_name == "Honeysuckle"


def test_parse_result_records_existing_asset_paths_for_known_flower_and_font():
    if not Path("BirthMonth flowers").is_dir() or not Path("Birthmonth_font.ttf").is_file():
        pytest.skip("Optional business assets are not present")

    result = parse_order_remark(
        "Choose Your Birth Flower : Jun - Rose"
        "Font Design : Font 4"
        "Personalization : Jazmin"
    )

    assert result.selected_flower_asset is not None
    assert Path(result.selected_flower_asset).exists()
    assert result.selected_font_asset is not None
    assert Path(result.selected_font_asset).exists()
    assert result.asset_confidence == 1.0


def _assert_structured_fields_exist(result):
    missing = [field for field in REQUIRED_STRUCTURED_FIELDS if not hasattr(result, field)]
    assert missing == [], f"Parser result missing structured fields: {missing}"
