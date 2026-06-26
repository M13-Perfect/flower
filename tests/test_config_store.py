from pathlib import Path

import prompts_db
from config_store import (
    DEFAULT_AI_PROFILE_NAME,
    DEFAULT_OUTPUT_PATH,
    AIProfile,
    AppConfig,
    active_ai_profile,
    active_product,
    has_admin_password,
    hash_password,
    ProductConfig,
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
    # 首次 load 会为产品迁移回填 prompt_set_id（非空），故不再等于内存里 set_id 为空的 config。
    loaded = load_config(path)
    assert active_product(loaded).prompt_set_id
    # 迁移幂等：再次 load 完全相等（已带 prompt_set_id，跳过迁移）。
    assert load_config(path) == loaded


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


def test_product_prompt_set_id_round_trips_and_background_lives_in_db(tmp_path):
    """产品只持有 prompt_set_id（配置往返保持）；背景提示词写进共享库 set 并往返保持。"""
    path = tmp_path / "config.json"
    db_path = path.parent / "prompts.db"
    # 先建配置（load 会为产品迁移出 prompt_set_id），再用 with_product_prompts 改背景提示词写库。
    save_config(AppConfig(), path)
    config = load_config(path)
    set_id = active_product(config).prompt_set_id
    assert set_id  # 迁移已回填

    with_product_prompts(config, background_prompt="木盒礼品语境", db_path=db_path)

    # 配置侧：prompt_set_id 往返不变。
    loaded = load_config(path)
    assert active_product(loaded).prompt_set_id == set_id
    # db 侧：背景提示词写入同一 set 并能往返载出。
    assert prompts_db.load_prompt_set(set_id, db_path).background_prompt == "木盒礼品语境"


def test_all_products_share_one_global_prompt_set(tmp_path):
    """全局共用一套：多个产品 load 后指向同一个 prompt_set_id（改一处=全产品生效）；迁移幂等。"""
    path = tmp_path / "config.json"
    config = AppConfig(
        products=(
            ProductConfig(id="a", name="A"),
            ProductConfig(id="b", name="B"),
            ProductConfig(id="c", name="C"),
        ),
        active_product_id="a",
    )
    save_config(config, path)
    loaded = load_config(path)

    set_ids = {product.prompt_set_id for product in loaded.products}
    assert len(set_ids) == 1  # 三个产品共用同一套
    assert all(product.prompt_set_id for product in loaded.products)  # 都已回填非空
    assert load_config(path) == loaded  # 幂等：再次 load 不变


def test_with_product_prompts_allows_empty_background(tmp_path):
    path = tmp_path / "c.json"
    db_path = path.parent / "prompts.db"
    save_config(AppConfig(), path)
    config = load_config(path)
    set_id = active_product(config).prompt_set_id

    with_product_prompts(config, background_prompt="y", db_path=db_path)
    with_product_prompts(config, background_prompt="", db_path=db_path)

    assert prompts_db.load_prompt_set(set_id, db_path).background_prompt == ""


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
