from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from models import EngravingLayout


APP_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = APP_DIR / "birth_flower_config.json"
DEFAULT_OUTPUT_DIR = APP_DIR / "outputs"
DEFAULT_OUTPUT_PATH = DEFAULT_OUTPUT_DIR / "birth_flower.svg"
DEFAULT_OUTPUT_FORMATS = ("svg", "dxf")
SUPPORTED_OUTPUT_FORMATS = {"png", "svg", "dxf"}
DEFAULT_AI_PROFILE_NAME = "OpenAI default"


@dataclass(frozen=True)
class AIProfile:
    name: str = DEFAULT_AI_PROFILE_NAME
    provider: str = "openai"
    model: str = "gpt-5-nano"
    base_url: str = ""
    api_key_env_var: str = "OPENAI_API_KEY"
    project_env_var: str = "OPENAI_PROJECT"
    org_env_var: str = "OPENAI_ORG_ID"
    enabled: bool = True
    prefer_ai: bool = False


@dataclass(frozen=True)
class AppConfig:
    flower_dir: Path = Path("BirthMonth flowers")
    font_source: Path = Path("Birthmonth_font.ttf")
    output_path: Path = DEFAULT_OUTPUT_PATH
    output_formats: tuple[str, ...] = DEFAULT_OUTPUT_FORMATS
    ai_profiles: tuple[AIProfile, ...] = (AIProfile(),)
    active_ai_profile: str = DEFAULT_AI_PROFILE_NAME
    layout_defaults: EngravingLayout = EngravingLayout()


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> AppConfig:
    """读取本地 UI 配置；文件缺失或损坏时返回默认值，避免启动失败。"""
    config_path = Path(path)
    if not config_path.exists():
        return AppConfig()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppConfig()
    if not isinstance(payload, dict):
        return AppConfig()
    raw_profiles = payload.get("ai_profiles", [])
    profiles = tuple(_ai_profile_from_payload(item) for item in raw_profiles if isinstance(item, dict))
    if not profiles:
        profiles = (AIProfile(),)
    active_profile = _string_value(payload, "active_ai_profile", profiles[0].name)
    return AppConfig(
        flower_dir=Path(_string_value(payload, "flower_dir", str(AppConfig().flower_dir))),
        font_source=Path(_string_value(payload, "font_source", str(AppConfig().font_source))),
        output_path=normalize_output_path(_string_value(payload, "output_path", str(AppConfig().output_path))),
        output_formats=normalize_output_formats(payload.get("output_formats")),
        ai_profiles=profiles,
        active_ai_profile=active_profile,
        layout_defaults=_layout_from_payload(payload.get("layout_defaults")),
    )


def save_config(config: AppConfig, path: Path | str = DEFAULT_CONFIG_PATH) -> Path:
    """保存用户选择的素材目录、字体源和输出路径。"""
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "flower_dir": str(config.flower_dir),
        "font_source": str(config.font_source),
        "output_path": str(config.output_path),
        "output_formats": list(normalize_output_formats(config.output_formats)),
        "ai_profiles": [_ai_profile_to_payload(profile) for profile in config.ai_profiles],
        "active_ai_profile": active_ai_profile(config).name,
        "layout_defaults": _layout_to_payload(config.layout_defaults),
    }
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return config_path



def _layout_from_payload(payload: Any) -> EngravingLayout:
    """从配置文件恢复全局默认布局；字段缺失或非法时使用项目默认值。"""
    default = EngravingLayout()
    if not isinstance(payload, dict):
        return default
    values: dict[str, int] = {}
    for field in (
        "canvas_width",
        "canvas_height",
        "flower_x",
        "flower_y",
        "flower_width",
        "flower_height",
        "text_x",
        "text_y",
        "text_width",
        "text_height",
        "text_size",
    ):
        raw = payload.get(field, getattr(default, field))
        try:
            values[field] = int(raw)
        except (TypeError, ValueError):
            values[field] = getattr(default, field)
    try:
        return EngravingLayout(**values)
    except TypeError:
        return default


def _layout_to_payload(layout: EngravingLayout) -> dict[str, int]:
    """把全局默认布局写入配置；只保存数值，不保存任何图层快照。"""
    return {
        "canvas_width": layout.canvas_width,
        "canvas_height": layout.canvas_height,
        "flower_x": layout.flower_x,
        "flower_y": layout.flower_y,
        "flower_width": layout.flower_width,
        "flower_height": layout.flower_height,
        "text_x": layout.text_x,
        "text_y": layout.text_y,
        "text_width": layout.text_width,
        "text_height": layout.text_height,
        "text_size": layout.text_size,
    }

def normalize_output_formats(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values or DEFAULT_OUTPUT_FORMATS:
        item = str(value).strip().casefold()
        if item in SUPPORTED_OUTPUT_FORMATS and item not in normalized:
            normalized.append(item)
    return tuple(normalized) or DEFAULT_OUTPUT_FORMATS


def active_ai_profile(config: AppConfig) -> AIProfile:
    for profile in config.ai_profiles:
        if profile.name == config.active_ai_profile:
            return profile
    return config.ai_profiles[0] if config.ai_profiles else AIProfile()


def _string_value(payload: dict[str, Any], key: str, default: str) -> str:
    value = payload.get(key, default)
    return value if isinstance(value, str) and value.strip() else default


def _optional_string_value(payload: dict[str, Any], key: str, default: str) -> str:
    if key not in payload:
        return default
    value = payload.get(key)
    return value if isinstance(value, str) else default


def _ai_profile_from_payload(payload: dict[str, Any]) -> AIProfile:
    return AIProfile(
        name=_string_value(payload, "name", DEFAULT_AI_PROFILE_NAME),
        provider=_string_value(payload, "provider", "openai"),
        model=_string_value(payload, "model", "gpt-5-nano"),
        base_url=_optional_string_value(payload, "base_url", ""),
        api_key_env_var=_string_value(payload, "api_key_env_var", "OPENAI_API_KEY"),
        project_env_var=_optional_string_value(payload, "project_env_var", "OPENAI_PROJECT"),
        org_env_var=_optional_string_value(payload, "org_env_var", "OPENAI_ORG_ID"),
        enabled=bool(payload.get("enabled", True)),
        prefer_ai=bool(payload.get("prefer_ai", False)),
    )


def _ai_profile_to_payload(profile: AIProfile) -> dict[str, Any]:
    return {
        "name": profile.name,
        "provider": profile.provider,
        "model": profile.model,
        "base_url": profile.base_url,
        "api_key_env_var": profile.api_key_env_var,
        "project_env_var": profile.project_env_var,
        "org_env_var": profile.org_env_var,
        "enabled": profile.enabled,
        "prefer_ai": profile.prefer_ai,
    }


def normalize_output_path(value: Path | str | None = None) -> Path:
    """把默认或相对输出路径固定到程序同目录的 outputs 文件夹。"""
    if value is None or not str(value).strip():
        return DEFAULT_OUTPUT_PATH
    path = Path(value)
    if path.is_absolute():
        return path
    if path.parent == Path("."):
        return DEFAULT_OUTPUT_DIR / path.name
    return APP_DIR / path
