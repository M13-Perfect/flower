from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
import hashlib
import hmac
import json
import math
import os
import sys
import threading
from pathlib import Path
from typing import Any

from models import EngravingLayout
from prompt_references import (
    ReferenceField,
    create_reference_field,
    default_prompt_template,
    reference_fields_from_legacy,
)
from production import ProductionParams


APP_DIR = Path(__file__).resolve().parent


def _is_writable(directory: Path) -> bool:
    try:
        probe = directory / ".bf_write_test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _data_root() -> Path:
    """配置/输出根。优先级：BIRTHFLOWER_DATA_DIR > 冻结态(exe 同级 data\\ / %APPDATA%) > 源码态(本目录)。

    源码态返回 APP_DIR，与历史行为完全一致（开发/测试不受影响）。冻结态把数据放到 exe 旁的
    data\\，升级换 exe 不丢；exe 目录不可写时回落 %APPDATA%\\BirthFlower。打包后由 packaging/
    launcher.py 通过 BIRTHFLOWER_DATA_DIR 统一注入（两处算法保持一致）。
    """
    env_dir = os.environ.get("BIRTHFLOWER_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        if _is_writable(exe_dir):
            return exe_dir / "data"
        appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        return (Path(appdata) if appdata else exe_dir) / "BirthFlower"
    return APP_DIR


def _default_config_path() -> Path:
    explicit = os.environ.get("BIRTHFLOWER_CONFIG")
    if explicit:
        return Path(explicit)
    return _data_root() / "birth_flower_config.json"


def _default_inbox_folder() -> str:
    """统一包里 flower「收件夹」的兜底值，使打包后无需手动配置即可自动取单。

    serve（inbox-service）把订单 JSON 写到 FLOWER_INBOX_DIR（launcher 注入 = DATA_ROOT/outputs/inbox）；
    flower 需轮询同一目录才能自动载入。故：有 FLOWER_INBOX_DIR 时用它；冻结态回落 DATA_ROOT/outputs/inbox；
    纯源码/开发态返回 ""（保持历史行为：收件夹默认关，需用户在「抓取设置」里手动指定）。
    """
    env_dir = os.environ.get("FLOWER_INBOX_DIR")
    if env_dir:
        return env_dir
    if getattr(sys, "frozen", False):
        return str(_data_root() / "outputs" / "inbox")
    return ""


# 注意：以下常量在**模块 import 时**按当时的环境变量一次性固化。打包后 flower 子进程由 launcher
# 在 subprocess 启动前注入 BIRTHFLOWER_DATA_DIR/FLOWER_INBOX_DIR，故子进程 import 时 env 已就位、取值正确。
# 但任何在 import 之后才设/改这些 env 的代码都不会反映到这里——勿在进程内动态改 DATA_ROOT。
DEFAULT_CONFIG_PATH = _default_config_path()
DEFAULT_OUTPUT_DIR = _data_root() / "outputs"
DEFAULT_OUTPUT_PATH = DEFAULT_OUTPUT_DIR / "birth_flower.svg"
DEFAULT_OUTPUT_FORMATS = ("svg", "dxf")
SUPPORTED_OUTPUT_FORMATS = {"png", "svg", "dxf"}
DEFAULT_AI_PROFILE_NAME = "OpenAI default"
# PNG 底:transparent=镂空(默认,激光雕刻背景不出刀)| white=正常白色实心底(普通查看/打印)。
DEFAULT_PNG_BACKGROUND = "transparent"
_CONFIG_WRITE_LOCK = threading.RLock()
PNG_BACKGROUND_CHOICES = ("transparent", "white")


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
class LayerPin:
    """产品级「锁定初始位置」：按稳定素材身份保存一份生产几何快照。"""

    key: str
    production: ProductionParams


@dataclass(frozen=True)
class ProductConfig:
    """一个产品（每窗口=一个产品）：声明该产品可用的素材库/字体库目录与默认生产参数。

    见 docs/superpowers/plans/2026-06-14-layer-material-library-system.md §3。
    """

    id: str = "birth-flower-card"
    name: str = "生日花卡"
    image_library_dirs: tuple[Path, ...] = ()
    font_library_dirs: tuple[Path, ...] = ()
    defaults: EngravingLayout = EngravingLayout()
    layer_pins: tuple[LayerPin, ...] = ()
    manual_fields: tuple[str, ...] = ()  # 人工确认字段集；空=用产品默认（Phase 2 UI 消费）
    extraction_prompt: str = ""  # 「提取提示词」：发给 API 的提取指令（按产品存）
    background_prompt: str = ""  # 「背景提示词」：附加背景上下文（按产品存）
    # Reference Field System: 新结构与旧 extraction_prompt/background_prompt 并存，便于渐进发布和回滚。
    reference_fields: tuple[ReferenceField, ...] = ()
    field_seq_max: int = 0
    prompt_template: str = ""
    template_version: int = 1


@dataclass(frozen=True)
class AppConfig:
    flower_dir: Path = Path("BirthMonth flowers")
    font_source: Path = Path("Birthmonth_font.ttf")
    output_path: Path = DEFAULT_OUTPUT_PATH
    output_formats: tuple[str, ...] = DEFAULT_OUTPUT_FORMATS
    # PNG 导出底:transparent=镂空(默认)| white=正常白底。只影响 PNG,SVG/DXF 不变。
    png_background: str = DEFAULT_PNG_BACKGROUND
    ai_profiles: tuple[AIProfile, ...] = (AIProfile(),)
    active_ai_profile: str = DEFAULT_AI_PROFILE_NAME
    layout_defaults: EngravingLayout = EngravingLayout()
    # 新产品体系：每个产品引用自己的素材库/字体库目录列表 + 默认生产参数。
    # 旧配置无 products 时由 __post_init__ 迁移合成「产品0」，用户零感知。
    products: tuple[ProductConfig, ...] = ()
    active_product_id: str = ""
    # 左侧产品切换列默认收起（方案2 可收/展），收/展状态随配置持久化。
    products_panel_collapsed: bool = True
    # 自动取单收件夹（automation/ 一期）：扩展→本地服务→写 {order_id}.json 到此目录；
    # Flower 用 Tk .after 轮询，自动载入备注+解析、停在生成前。空=功能关（默认），对现有用户零影响。
    inbox_folder: Path = Path("")
    # 收件夹来单后是否自动解析识别（始终停在生成前，绝不自动生成）。默认关：
    # 「自动识别」必须由用户在 GUI 的「抓取订单」区域显式打开，与「自动抓取」语义/状态完全独立。
    inbox_autoparse: bool = False
    # 「自动识别」是否由用户经新版 GUI 显式设置过。False=旧配置 / 全新 / 默认。
    # 安全优先：load 时只有该标记为 True 才采信存储的 inbox_autoparse，否则一律回落 False，
    # 避免旧配置里遗留的 inbox_autoparse=True 在用户没有明确同意时自动触发解析。
    inbox_autoparse_user_set: bool = False
    # flower→inbox-service 地址（「抓取订单」面板的服务地址）。空=用客户端默认 127.0.0.1:8770。
    # 在「抓取设置」里改后持久化到此，重启不丢。
    inbox_service_url: str = ""
    # 管理员端密码（PBKDF2-SHA256，格式见 hash_password）。空=尚未设密码（首次进管理员端引导设置）。
    # 只存哈希、不存明文；选端页「管理员端」据此决定是否弹密码门。
    admin_password_hash: str = ""
    # 三列布局（产品列|中心|功能区）2 条分隔条的位置，存的是占总宽的比例（0~1），不是绝对像素——
    # 换窗口大小/换屏幕分辨率都不串位（还原时按当前总宽折算，见 ui_app._restore_pane_sashes）。空=用默认列宽。
    pane_sash_fractions: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not self.products:
            object.__setattr__(
                self,
                "products",
                _ensure_products((), self.flower_dir, self.font_source, self.layout_defaults),
            )
        if not self.active_product_id:
            object.__setattr__(self, "active_product_id", self.products[0].id)


def _fractions_value(payload: dict, key: str) -> tuple[float, ...]:
    """读取一串 0~1 的比例值（分隔条位置）；任一项越界/非数则整组作废回落空（用默认列宽）。"""
    raw = payload.get(key)
    if not isinstance(raw, (list, tuple)):
        return ()
    out: list[float] = []
    for value in raw:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return ()
        if not (0.0 < number < 1.0):
            return ()
        out.append(number)
    return tuple(out)


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
    # 「自动识别」安全迁移：仅当用户经新版 GUI 显式设置过（inbox_autoparse_user_set=True）才采信存储值；
    # 否则（旧配置遗留 True / 全新 / 缺字段）一律回落 False，避免未经用户明确同意就自动解析。
    autoparse_user_set = _bool_value(payload, "inbox_autoparse_user_set", False)
    inbox_autoparse = _bool_value(payload, "inbox_autoparse", False) if autoparse_user_set else False
    layout_defaults = _layout_from_payload(payload.get("layout_defaults"))
    return AppConfig(
        flower_dir=Path(_string_value(payload, "flower_dir", str(AppConfig().flower_dir))),
        font_source=Path(_string_value(payload, "font_source", str(AppConfig().font_source))),
        output_path=normalize_output_path(_string_value(payload, "output_path", str(AppConfig().output_path))),
        output_formats=normalize_output_formats(payload.get("output_formats")),
        png_background=normalize_png_background(payload.get("png_background")),
        ai_profiles=profiles,
        active_ai_profile=active_profile,
        layout_defaults=layout_defaults,
        products=_products_from_payload(payload.get("products"), layout_defaults),
        active_product_id=_string_value(payload, "active_product_id", ""),
        products_panel_collapsed=_bool_value(payload, "products_panel_collapsed", True),
        inbox_folder=Path(_optional_string_value(payload, "inbox_folder", "") or _default_inbox_folder()),
        inbox_autoparse=inbox_autoparse,
        inbox_autoparse_user_set=autoparse_user_set,
        inbox_service_url=_optional_string_value(payload, "inbox_service_url", ""),
        admin_password_hash=_optional_string_value(payload, "admin_password_hash", ""),
        pane_sash_fractions=_fractions_value(payload, "pane_sash_fractions"),
    )


def save_config(config: AppConfig, path: Path | str = DEFAULT_CONFIG_PATH) -> Path:
    """保存用户选择的素材目录、字体源和输出路径。"""
    config_path = Path(path)
    with _CONFIG_WRITE_LOCK:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "flower_dir": str(config.flower_dir),
            "font_source": str(config.font_source),
            "output_path": str(config.output_path),
            "output_formats": list(normalize_output_formats(config.output_formats)),
            "png_background": normalize_png_background(config.png_background),
            "ai_profiles": [_ai_profile_to_payload(profile) for profile in config.ai_profiles],
            "active_ai_profile": active_ai_profile(config).name,
            "layout_defaults": _layout_to_payload(config.layout_defaults),
            "products": [_product_to_payload(product) for product in config.products],
            "active_product_id": active_product(config).id,
            "products_panel_collapsed": bool(config.products_panel_collapsed),
            "inbox_folder": str(config.inbox_folder),
            "inbox_autoparse": bool(config.inbox_autoparse),
            "inbox_autoparse_user_set": bool(config.inbox_autoparse_user_set),
            "inbox_service_url": config.inbox_service_url,
            "admin_password_hash": config.admin_password_hash,
            "pane_sash_fractions": list(config.pane_sash_fractions),
        }
        tmp_path = config_path.with_name(config_path.name + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(config_path)
    return config_path



def _layout_from_payload(payload: Any, default: EngravingLayout | None = None) -> EngravingLayout:
    """从配置文件恢复全局默认布局；字段缺失或非法时使用项目默认值。"""
    default = default or EngravingLayout()
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
    # 字体样式（新增）：bool/float 字段，单独解析（不能走上面的 int 转换）。
    style: dict[str, Any] = {}
    for flag in ("bold", "underline", "italic"):
        style[flag] = bool(payload.get(flag, getattr(default, flag)))
    for fkey in ("bold_strength", "letter_spacing"):
        try:
            style[fkey] = float(payload.get(fkey, getattr(default, fkey)))
        except (TypeError, ValueError):
            style[fkey] = getattr(default, fkey)
    try:
        return EngravingLayout(**values, **style)
    except TypeError:
        return default


def _layout_to_payload(layout: EngravingLayout) -> dict[str, Any]:
    """把全局默认布局写入配置；只保存数值与字体样式，不保存任何图层快照。"""
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
        "bold": layout.bold,
        "underline": layout.underline,
        "italic": layout.italic,
        "bold_strength": layout.bold_strength,
        "letter_spacing": layout.letter_spacing,
    }

def normalize_output_formats(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values or DEFAULT_OUTPUT_FORMATS:
        item = str(value).strip().casefold()
        if item in SUPPORTED_OUTPUT_FORMATS and item not in normalized:
            normalized.append(item)
    return tuple(normalized) or DEFAULT_OUTPUT_FORMATS


def normalize_png_background(value: Any) -> str:
    """PNG 底归一化:仅接受 transparent/white,其它(含 None/旧配置)回落 transparent。"""
    item = str(value).strip().casefold() if value is not None else ""
    return item if item in PNG_BACKGROUND_CHOICES else DEFAULT_PNG_BACKGROUND


def active_ai_profile(config: AppConfig) -> AIProfile:
    for profile in config.ai_profiles:
        if profile.name == config.active_ai_profile:
            return profile
    return config.ai_profiles[0] if config.ai_profiles else AIProfile()


def active_product(config: AppConfig) -> ProductConfig:
    """返回当前激活产品；找不到时回退到第一个（products 恒非空，见 AppConfig.__post_init__）。"""
    for product in config.products:
        if product.id == config.active_product_id:
            return product
    return config.products[0] if config.products else ProductConfig()


def _slugify(value: str) -> str:
    """把产品名转成 ASCII slug；非 ASCII（如中文）字符忽略，便于生成稳定 id。"""
    chars: list[str] = []
    for ch in value.strip().lower():
        if ch.isascii() and ch.isalnum():
            chars.append(ch)
        elif ch in " -_":
            chars.append("-")
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def unique_product_id(name: str, existing_ids: Iterable[str]) -> str:
    """从产品名生成唯一稳定 id：slug 化（中文/空名回退 product），冲突按 -2/-3 递增。"""
    existing = set(existing_ids)
    base = _slugify(name) or "product"
    if base not in existing:
        return base
    index = 2
    while f"{base}-{index}" in existing:
        index += 1
    return f"{base}-{index}"


def with_added_product(
    config: AppConfig, product: ProductConfig, *, activate: bool = True
) -> AppConfig:
    """返回追加了新产品的配置（不可变）；activate=True 时同时切为激活产品。"""
    products = config.products + (product,)
    active = product.id if activate else config.active_product_id
    return replace(config, products=products, active_product_id=active)


def with_product_library_dirs(
    config: AppConfig,
    image_dirs: Iterable[Path | str],
    font_dirs: Iterable[Path | str],
    *,
    product_id: str | None = None,
) -> AppConfig:
    """更新指定产品（默认当前激活产品）的素材库/字体库目录列表，返回新配置（不可变）。

    同时把首个库目录回写顶层 ``flower_dir``/``font_source``，作为旧单目录链路的迁移兼容入口；
    目录列表为空时保留原顶层值。其余产品原样保留。
    """
    target_id = product_id or config.active_product_id
    image_tuple = tuple(Path(path) for path in image_dirs)
    font_tuple = tuple(Path(path) for path in font_dirs)
    products = tuple(
        replace(product, image_library_dirs=image_tuple, font_library_dirs=font_tuple)
        if product.id == target_id
        else product
        for product in config.products
    )
    flower_dir = image_tuple[0] if image_tuple else config.flower_dir
    font_source = font_tuple[0] if font_tuple else config.font_source
    return replace(config, products=products, flower_dir=flower_dir, font_source=font_source)


def with_product_defaults(
    config: AppConfig,
    defaults: EngravingLayout,
    *,
    product_id: str | None = None,
) -> AppConfig:
    """更新指定产品的默认几何；产品0 同步顶层 layout_defaults，旧链路零回归。"""
    target_id = product_id or config.active_product_id
    products = tuple(
        replace(product, defaults=defaults) if product.id == target_id else product
        for product in config.products
    )
    layout_defaults = defaults if products and products[0].id == target_id else config.layout_defaults
    return replace(config, products=products, layout_defaults=layout_defaults)


def with_product_layer_pins(
    config: AppConfig,
    layer_pins: Iterable[LayerPin],
    *,
    product_id: str | None = None,
) -> AppConfig:
    """替换指定产品的 layer_pins；按 key 去重，后出现的 pin 覆盖旧值。"""
    target_id = product_id or config.active_product_id
    by_key: dict[str, LayerPin] = {}
    for pin in layer_pins:
        cleaned = _coerce_layer_pin(pin)
        if cleaned is not None:
            by_key[cleaned.key] = cleaned
    pins = tuple(by_key[key] for key in sorted(by_key))
    products = tuple(
        replace(product, layer_pins=pins) if product.id == target_id else product
        for product in config.products
    )
    return replace(config, products=products)


def with_product_prompts(
    config: AppConfig,
    *,
    extraction_prompt: str,
    background_prompt: str,
    product_id: str | None = None,
) -> AppConfig:
    """更新指定产品（默认当前激活产品）的「提取提示词」「背景提示词」，返回新配置（不可变）。

    其余产品原样保留。空字符串是合法值（表示未填）。
    """
    target_id = product_id or config.active_product_id
    products = tuple(
        replace(product, extraction_prompt=extraction_prompt, background_prompt=background_prompt)
        if product.id == target_id
        else product
        for product in config.products
    )
    return replace(config, products=products)


def with_product_reference_fields(
    config: AppConfig,
    *,
    reference_fields: tuple[ReferenceField, ...],
    field_seq_max: int,
    prompt_template: str | None = None,
    template_version: int | None = None,
    extraction_prompt: str | None = None,
    background_prompt: str | None = None,
    product_id: str | None = None,
) -> AppConfig:
    """更新当前产品的可引用字段配置；旧字段同步保留，供兼容期回滚。"""
    target_id = product_id or config.active_product_id

    def patch(product: ProductConfig) -> ProductConfig:
        if product.id != target_id:
            return product
        return replace(
            product,
            reference_fields=reference_fields,
            field_seq_max=max(field_seq_max, *(field.sequence_number for field in reference_fields), 0),
            prompt_template=product.prompt_template if prompt_template is None else prompt_template,
            template_version=product.template_version if template_version is None else template_version,
            extraction_prompt=product.extraction_prompt if extraction_prompt is None else extraction_prompt,
            background_prompt=product.background_prompt if background_prompt is None else background_prompt,
        )

    return replace(config, products=tuple(patch(product) for product in config.products))


def create_product_reference_field_in_file(
    path: Path | str,
    product_id: str,
    *,
    reference_name: str,
    prompt: str,
    field_type: str = "文本",
) -> tuple[AppConfig, ReferenceField]:
    """在锁内读取最新配置、分配序号并原子写回，避免并发创建拿到重复序号。"""
    with _CONFIG_WRITE_LOCK:
        config = load_config(path)
        target_id = product_id or active_product(config).id
        target = next((product for product in config.products if product.id == target_id), active_product(config))
        fields, seq_max, created = create_reference_field(
            target.reference_fields,
            field_seq_max=target.field_seq_max,
            scope_id=target.id,
            reference_name=reference_name,
            prompt=prompt,
            field_type=field_type,
        )
        template = target.prompt_template or default_prompt_template(fields, target.background_prompt)
        updated = with_product_reference_fields(
            config,
            product_id=target.id,
            reference_fields=fields,
            field_seq_max=seq_max,
            prompt_template=template,
        )
        save_config(updated, path)
        return updated, created


# ===== 管理员密码（PBKDF2-SHA256，纯标准库，无新依赖）=====
# 存储格式：``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``。只存哈希、不存明文。
_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str, *, salt: bytes | None = None, iterations: int = _PBKDF2_ITERATIONS) -> str:
    """把明文密码哈希成可持久化字符串（带随机盐 + 迭代）。salt 仅供测试注入固定值。"""
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(stored: str, password: str) -> bool:
    """常量时间校验明文是否匹配已存哈希；格式非法/空哈希一律返回 False。"""
    if not stored:
        return False
    try:
        algo, iter_s, salt_hex, hash_hex = stored.split("$")
        iterations = int(iter_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


def has_admin_password(config: AppConfig) -> bool:
    """是否已设管理员密码（空哈希=未设，首次进管理员端引导设置）。"""
    return bool(config.admin_password_hash)


def verify_admin_password(config: AppConfig, password: str) -> bool:
    return verify_password(config.admin_password_hash, password)


def with_admin_password(config: AppConfig, password: str) -> AppConfig:
    """返回设好管理员密码的新配置（不可变）。空密码=清除（回到未设态）。"""
    return replace(config, admin_password_hash=hash_password(password) if password else "")


def _bool_value(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    return value if isinstance(value, bool) else default


def _int_value(payload: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(payload.get(key, default))
    except (TypeError, ValueError):
        return default


def _ensure_products(
    products: tuple[ProductConfig, ...],
    flower_dir: Path,
    font_source: Path,
    layout_defaults: EngravingLayout,
) -> tuple[ProductConfig, ...]:
    """已有 products 原样返回；否则把旧全局 flower_dir/font_source/layout_defaults 合成「产品0=生日花卡」。"""
    if products:
        return products
    return (
        ProductConfig(
            id="birth-flower-card",
            name="生日花卡",
            image_library_dirs=(flower_dir,),
            font_library_dirs=(font_source,),
            defaults=layout_defaults,
        ),
    )


def _products_from_payload(value: Any, defaults: EngravingLayout | None = None) -> tuple[ProductConfig, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(_product_from_payload(item, defaults) for item in value if isinstance(item, dict))


def _product_from_payload(payload: dict[str, Any], defaults: EngravingLayout | None = None) -> ProductConfig:
    product_id = _string_value(payload, "id", "product")
    extraction_prompt = _optional_string_value(payload, "extraction_prompt", "")
    background_prompt = _optional_string_value(payload, "background_prompt", "")
    reference_fields = _reference_fields_from_payload(payload.get("reference_fields"), product_id)
    if not reference_fields:
        reference_fields = reference_fields_from_legacy(extraction_prompt, scope_id=product_id)
    field_seq_max = _int_value(
        payload,
        "field_seq_max",
        max((field.sequence_number for field in reference_fields), default=0),
    )
    prompt_template = _optional_string_value(payload, "prompt_template", "")
    if not prompt_template and reference_fields:
        prompt_template = default_prompt_template(reference_fields, background_prompt)
    return ProductConfig(
        id=product_id,
        name=_string_value(payload, "name", product_id),
        image_library_dirs=_path_tuple(payload.get("image_library_dirs")),
        font_library_dirs=_path_tuple(payload.get("font_library_dirs")),
        defaults=_layout_from_payload(payload.get("defaults"), defaults),
        layer_pins=_layer_pins_from_payload(payload.get("layer_pins")),
        manual_fields=_str_tuple(payload.get("manual_fields")),
        extraction_prompt=extraction_prompt,
        background_prompt=background_prompt,
        reference_fields=reference_fields,
        field_seq_max=max(field_seq_max, *(field.sequence_number for field in reference_fields), 0),
        prompt_template=prompt_template,
        template_version=_int_value(payload, "template_version", 1),
    )


def _product_to_payload(product: ProductConfig) -> dict[str, Any]:
    return {
        "id": product.id,
        "name": product.name,
        "image_library_dirs": [str(path) for path in product.image_library_dirs],
        "font_library_dirs": [str(path) for path in product.font_library_dirs],
        "defaults": _layout_to_payload(product.defaults),
        "layer_pins": [_layer_pin_to_payload(pin) for pin in product.layer_pins],
        "manual_fields": list(product.manual_fields),
        "extraction_prompt": product.extraction_prompt,
        "background_prompt": product.background_prompt,
        "reference_fields": [_reference_field_to_payload(field) for field in product.reference_fields],
        "field_seq_max": product.field_seq_max,
        "prompt_template": product.prompt_template,
        "template_version": product.template_version,
    }


def _finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _valid_pin_production(production: ProductionParams) -> bool:
    for field_name in ("x", "y", "width", "height"):
        if not _finite_number(getattr(production, field_name)):
            return False
    if float(production.width or 0) <= 0 or float(production.height or 0) <= 0:
        return False
    if production.rotation is not None and not _finite_number(production.rotation):
        return False
    if production.font_size is not None:
        try:
            if int(production.font_size) <= 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _coerce_layer_pin(value: Any) -> LayerPin | None:
    if isinstance(value, LayerPin):
        key = value.key.strip()
        production = value.production
    elif isinstance(value, dict):
        key = _optional_string_value(value, "key", "").strip()
        production = ProductionParams.from_mapping(value.get("production"))
    else:
        return None
    if not key or not _valid_pin_production(production):
        return None
    return LayerPin(key=key, production=production)


def _layer_pins_from_payload(value: Any) -> tuple[LayerPin, ...]:
    if not isinstance(value, list):
        return ()
    pins: list[LayerPin] = []
    seen: set[str] = set()
    for item in value:
        pin = _coerce_layer_pin(item)
        if pin is None or pin.key in seen:
            continue
        seen.add(pin.key)
        pins.append(pin)
    return tuple(pins)


def _layer_pin_to_payload(pin: LayerPin) -> dict[str, Any]:
    return {"key": pin.key, "production": pin.production.to_dict()}


def _reference_fields_from_payload(value: Any, product_id: str) -> tuple[ReferenceField, ...]:
    if not isinstance(value, list):
        return ()
    fields: list[ReferenceField] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        field_id = _optional_string_value(item, "id", "")
        if not field_id:
            continue
        sequence = _int_value(item, "sequence_number", 0)
        if sequence <= 0:
            continue
        fields.append(
            ReferenceField(
                id=field_id,
                scope_id=_optional_string_value(item, "scope_id", product_id) or product_id,
                sequence_number=sequence,
                reference_name=_optional_string_value(item, "reference_name", "") or f"字段{sequence}",
                prompt=_optional_string_value(item, "prompt", ""),
                sort_order=_int_value(item, "sort_order", sequence),
                enabled=_bool_value(item, "enabled", True),
                created_at=_optional_string_value(item, "created_at", ""),
                updated_at=_optional_string_value(item, "updated_at", ""),
                deleted_at=_optional_string_value(item, "deleted_at", ""),
                field_type=_optional_string_value(item, "field_type", "文本") or "文本",
                legacy_key=_optional_string_value(item, "legacy_key", ""),
            )
        )
    return tuple(sorted(fields, key=lambda field: (field.sort_order, field.sequence_number)))


def _reference_field_to_payload(field: ReferenceField) -> dict[str, Any]:
    return {
        "id": field.id,
        "scope_id": field.scope_id,
        "sequence_number": field.sequence_number,
        "reference_name": field.reference_name,
        "prompt": field.prompt,
        "sort_order": field.sort_order,
        "enabled": field.enabled,
        "created_at": field.created_at,
        "updated_at": field.updated_at,
        "deleted_at": field.deleted_at,
        "field_type": field.field_type,
        "legacy_key": field.legacy_key,
    }


def _path_tuple(value: Any) -> tuple[Path, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(Path(str(item)) for item in value if str(item).strip())


def _str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


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
