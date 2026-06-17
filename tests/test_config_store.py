from pathlib import Path

from config_store import (
    DEFAULT_AI_PROFILE_NAME,
    DEFAULT_OUTPUT_PATH,
    AIProfile,
    AppConfig,
    active_ai_profile,
    active_product,
    load_config,
    normalize_output_formats,
    normalize_output_path,
    save_config,
    with_product_prompts,
)


def test_save_and_load_config_round_trip(tmp_path):
    path = tmp_path / "config.json"
    config = AppConfig(
        flower_dir=Path("BirthMonth flowers"),
        font_source=Path("Birthmonth_font.ttf"),
        output_path=tmp_path / "outputs" / "result.svg",
    )

    save_config(config, path)
    loaded = load_config(path)

    assert loaded == config


def test_load_config_returns_defaults_when_file_is_missing(tmp_path):
    config = load_config(tmp_path / "missing.json")

    assert config.flower_dir == Path("BirthMonth flowers")
    assert config.font_source == Path("Birthmonth_font.ttf")
    assert config.output_path == DEFAULT_OUTPUT_PATH
    assert config.output_path.parent.name == "outputs"


def test_normalize_output_path_puts_bare_filename_in_app_outputs():
    assert normalize_output_path("custom.svg") == DEFAULT_OUTPUT_PATH.parent / "custom.svg"


def test_load_config_normalizes_legacy_relative_output_path(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"flower_dir":"BirthMonth flowers","font_source":"Birthmonth_font.ttf","output_path":"custom.svg"}',
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.output_path == DEFAULT_OUTPUT_PATH.parent / "custom.svg"


def test_save_and_load_config_keeps_output_formats_and_ai_profile(tmp_path):
    path = tmp_path / "config.json"
    config = AppConfig(
        flower_dir=Path("assets"),
        font_source=Path("fonts"),
        output_path=tmp_path / "outputs" / "result.svg",
        output_formats=("png", "svg"),
        ai_profiles=(
            AIProfile(
                name="OpenAI shop",
                provider="openai",
                model="gpt-5-nano",
                base_url="https://api.openai.com/v1/responses",
                api_key_env_var="SHOP_OPENAI_KEY",
                project_env_var="SHOP_OPENAI_PROJECT",
                org_env_var="SHOP_OPENAI_ORG",
                enabled=True,
                prefer_ai=True,
            ),
        ),
        active_ai_profile="OpenAI shop",
    )

    save_config(config, path)
    raw = path.read_text(encoding="utf-8")
    loaded = load_config(path)

    assert "sk-" not in raw
    assert loaded.output_formats == ("png", "svg")
    assert loaded.active_ai_profile == "OpenAI shop"
    assert loaded.ai_profiles[0].base_url == "https://api.openai.com/v1/responses"
    assert loaded.ai_profiles[0].api_key_env_var == "SHOP_OPENAI_KEY"
    assert loaded.ai_profiles[0].prefer_ai is True


def test_save_and_load_config_keeps_deepseek_profile_without_secret(tmp_path):
    path = tmp_path / "config.json"
    config = AppConfig(
        ai_profiles=(
            AIProfile(
                name="DeepSeek speed test",
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                api_key_env_var="DEEPSEEK_API_KEY",
                project_env_var="",
                org_env_var="",
                enabled=True,
                prefer_ai=True,
            ),
        ),
        active_ai_profile="DeepSeek speed test",
    )

    save_config(config, path)
    raw = path.read_text(encoding="utf-8")
    loaded = load_config(path)

    assert "ds-" not in raw
    assert loaded.ai_profiles[0].provider == "deepseek"
    assert loaded.ai_profiles[0].model == "deepseek-v4-flash"
    assert loaded.ai_profiles[0].base_url == "https://api.deepseek.com"
    assert loaded.ai_profiles[0].api_key_env_var == "DEEPSEEK_API_KEY"


def test_load_config_supplies_default_ai_profile(tmp_path):
    config = load_config(tmp_path / "missing.json")

    profile = active_ai_profile(config)

    assert profile.name == DEFAULT_AI_PROFILE_NAME
    assert profile.provider == "openai"
    assert profile.model == "gpt-5-nano"
    assert profile.base_url == ""
    assert profile.api_key_env_var == "OPENAI_API_KEY"
    assert profile.prefer_ai is False


def test_normalize_output_formats_rejects_unknown_and_keeps_order():
    assert normalize_output_formats(["svg", "bad", "png", "svg"]) == ("svg", "png")
    assert normalize_output_formats([]) == ("svg", "dxf")


def test_save_and_load_config_keeps_layout_defaults(tmp_path):
    from models import EngravingLayout

    path = tmp_path / "config.json"
    defaults = EngravingLayout(flower_x=111, flower_y=222, flower_width=333, flower_height=444, text_x=555)
    config = AppConfig(layout_defaults=defaults)

    save_config(config, path)
    loaded = load_config(path)

    assert loaded.layout_defaults.flower_x == 111
    assert loaded.layout_defaults.flower_y == 222
    assert loaded.layout_defaults.flower_width == 333
    assert loaded.layout_defaults.flower_height == 444
    assert loaded.layout_defaults.text_x == 555


def test_save_and_load_config_keeps_product_prompts(tmp_path):
    """提取提示词 / 背景提示词随产品配置往返持久化（空值也合法）。"""
    path = tmp_path / "config.json"
    config = with_product_prompts(
        AppConfig(), extraction_prompt="提取顾客名字与花", background_prompt="木盒礼品语境"
    )

    save_config(config, path)
    loaded = load_config(path)

    product = active_product(loaded)
    assert product.extraction_prompt == "提取顾客名字与花"
    assert product.background_prompt == "木盒礼品语境"


def test_with_product_prompts_allows_empty_and_isolates_other_products(tmp_path):
    config = with_product_prompts(AppConfig(), extraction_prompt="x", background_prompt="y")
    cleared = with_product_prompts(config, extraction_prompt="", background_prompt="")

    path = tmp_path / "c.json"
    save_config(cleared, path)
    product = active_product(load_config(path))
    assert product.extraction_prompt == ""
    assert product.background_prompt == ""
