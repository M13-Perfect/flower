from pathlib import Path

from config_store import (
    DEFAULT_AI_PROFILE_NAME,
    DEFAULT_OUTPUT_PATH,
    AIProfile,
    AppConfig,
    active_ai_profile,
    active_product,
    has_admin_password,
    hash_password,
    load_config,
    normalize_output_formats,
    normalize_output_path,
    save_config,
    verify_admin_password,
    verify_password,
    with_admin_password,
    with_product_prompts,
)


def test_hash_and_verify_password_round_trip():
    stored = hash_password("s3cret", salt=b"0123456789abcdef")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password(stored, "s3cret") is True
    assert verify_password(stored, "wrong") is False
    # 同密码不同盐 → 不同哈希串，但都能各自校验通过（盐随机）。
    assert hash_password("s3cret") != hash_password("s3cret")


def test_verify_password_rejects_empty_and_malformed():
    assert verify_password("", "anything") is False
    assert verify_password("not-a-valid-format", "x") is False
    assert verify_password("pbkdf2_sha256$abc$zz$zz", "x") is False


def test_with_admin_password_sets_verifies_and_clears():
    cfg = AppConfig()
    assert has_admin_password(cfg) is False
    cfg2 = with_admin_password(cfg, "1234")
    assert has_admin_password(cfg2) is True
    assert verify_admin_password(cfg2, "1234") is True
    assert verify_admin_password(cfg2, "0000") is False
    # 空密码 = 清除，回到未设态。
    assert has_admin_password(with_admin_password(cfg2, "")) is False


def test_admin_password_hash_persists_round_trip(tmp_path):
    path = tmp_path / "config.json"
    cfg = with_admin_password(AppConfig(), "pw12")
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.admin_password_hash == cfg.admin_password_hash
    assert verify_admin_password(loaded, "pw12") is True


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


def test_save_and_load_config_keeps_inbox_settings(tmp_path):
    """收件夹路径随配置往返持久化（automation 一期）。"""
    path = tmp_path / "config.json"
    config = AppConfig(inbox_folder=tmp_path / "inbox", inbox_autoparse=False)

    save_config(config, path)
    loaded = load_config(path)

    assert loaded.inbox_folder == tmp_path / "inbox"
    assert loaded.inbox_autoparse is False


def test_load_config_defaults_inbox_off(tmp_path):
    """旧配置无 inbox 键：收件夹为空（功能关），自动识别默认【关】（安全优先，须用户在 GUI 显式开）。"""
    config = load_config(tmp_path / "missing.json")

    assert str(config.inbox_folder) in ("", ".")
    assert config.inbox_autoparse is False
    assert config.inbox_autoparse_user_set is False


def test_load_config_legacy_autoparse_true_without_user_flag_falls_back_off(tmp_path):
    """安全迁移：旧配置遗留 inbox_autoparse=True 但无 user_set 标记 → 强制回落 False（未经用户明确同意不自动解析）。"""
    path = tmp_path / "config.json"
    path.write_text('{"inbox_autoparse": true}', encoding="utf-8")

    config = load_config(path)

    assert config.inbox_autoparse is False
    assert config.inbox_autoparse_user_set is False


def test_load_config_honors_explicit_user_autoparse_on(tmp_path):
    """用户经新版 GUI 显式开启（user_set=True + autoparse=True）→ 采信存储值，往返保持 True。"""
    path = tmp_path / "config.json"
    config = AppConfig(inbox_autoparse=True, inbox_autoparse_user_set=True)

    save_config(config, path)
    loaded = load_config(path)

    assert loaded.inbox_autoparse is True
    assert loaded.inbox_autoparse_user_set is True


def test_load_config_honors_explicit_user_autoparse_off(tmp_path):
    """用户显式关闭（user_set=True + autoparse=False）→ 采信存储 False，往返保持关。"""
    path = tmp_path / "config.json"
    config = AppConfig(inbox_autoparse=False, inbox_autoparse_user_set=True)

    save_config(config, path)
    loaded = load_config(path)

    assert loaded.inbox_autoparse is False
    assert loaded.inbox_autoparse_user_set is True


def test_save_and_load_config_keeps_inbox_service_url(tmp_path):
    """抓取面板「服务地址」随配置往返持久化（2026-06-19 缺口修复，重启不丢）。"""
    path = tmp_path / "config.json"
    config = AppConfig(inbox_service_url="http://127.0.0.1:8888")

    save_config(config, path)
    loaded = load_config(path)

    assert loaded.inbox_service_url == "http://127.0.0.1:8888"


def test_load_config_defaults_inbox_service_url_empty(tmp_path):
    """旧配置无该键：服务地址为空串（由客户端回落默认 127.0.0.1:8770）。"""
    config = load_config(tmp_path / "missing.json")

    assert config.inbox_service_url == ""
