from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import importlib.util
import json
import logging
from datetime import datetime
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)
DEFAULT_GLYPH_MAP_PATH = Path(__file__).resolve().parent / "glyph_maps" / "glyph_maps.json"
DEFAULT_GLYPH_BINDINGS_PATH = Path(__file__).resolve().parent / "glyph_maps" / "glyph_bindings.json"
DEFAULT_GLYPH_RULES_PATH = Path(__file__).resolve().parent / "glyph_maps" / "glyph_rules.json"
VALID_GLYPH_USAGES = {"start", "middle", "end", "any"}
VALID_GLYPH_SOURCES = {"cmap", "gsub", "manual_binding", "rule"}
VALID_APPLY_MODES = {"replace_last_letter", "append_suffix", "manual_per_character"}
PUA_START = 0xE000
PUA_END = 0xF8FF
PUA_RANGES = (
    (0xE000, 0xF8FF),
    (0xF0000, 0xFFFFD),
    (0x100000, 0x10FFFD),
)
INSTALL_COMMAND_PACKAGES = "fonttools pillow freetype-py uharfbuzz svgwrite ezdxf"
RUNTIME_DEPENDENCIES = (
    ("fonttools", "fontTools.ttLib"),
    ("pillow", "PIL"),
    ("freetype-py", "freetype"),
)

# Font 2 常用结尾字形：截图中的 a.005-z.005，按 a-z 顺序连续映射到 PUA E068-E081。
FONT2_DEFAULT_ENDING_GLYPHS = {
    letter: f"U+{0xE068 + index:04X}"
    for index, letter in enumerate("abcdefghijklmnopqrstuvwxyz")
}




@dataclass(frozen=True)
class GlyphVariant:
    base_char: str
    replacement_char: str
    codepoint: str
    glyph_name: str
    font_id: str
    font_path: str
    display_name: str
    usage: str = "any"
    is_pua: bool = False
    source: str = "cmap"
    advance_width: float | None = None
    bbox: tuple[float, float, float, float] | None = None
    preview_path: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, font_id: str = "", font_path: str = "") -> "GlyphVariant":
        """从 JSON/扫描结果安全构建 GlyphVariant，缺字段时降级并写日志。"""
        if not isinstance(value, Mapping):
            LOGGER.warning("GlyphVariant 配置不是对象：%r", value)
            value = {}
        raw_codepoint = str(value.get("codepoint") or value.get("unicode") or "").strip()
        clean_codepoint = _codepoint_hex(raw_codepoint)
        replacement_char = str(value.get("replacement_char") or value.get("char") or "")
        if not replacement_char and clean_codepoint:
            try:
                replacement_char = chr(int(clean_codepoint, 16))
            except (TypeError, ValueError):
                LOGGER.warning("GlyphVariant codepoint 无效：%s", raw_codepoint)
                replacement_char = ""
        usage = str(value.get("usage") or "any").strip().casefold()
        if usage not in VALID_GLYPH_USAGES:
            LOGGER.warning("GlyphVariant usage 无效，已降级为 any：%s", usage)
            usage = "any"
        source = str(value.get("source") or "cmap").strip().casefold()
        if source not in VALID_GLYPH_SOURCES:
            LOGGER.warning("GlyphVariant source 无效，已降级为 cmap：%s", source)
            source = "cmap"
        bbox = value.get("bbox")
        clean_bbox = None
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            try:
                clean_bbox = tuple(float(item) for item in bbox)  # type: ignore[assignment]
            except (TypeError, ValueError):
                LOGGER.warning("GlyphVariant bbox 无效：%r", bbox)
        advance = value.get("advance_width")
        try:
            clean_advance = None if advance is None else float(advance)
        except (TypeError, ValueError):
            LOGGER.warning("GlyphVariant advance_width 无效：%r", advance)
            clean_advance = None
        return cls(
            base_char=str(value.get("base_char") or "")[:1],
            replacement_char=replacement_char,
            codepoint=clean_codepoint,
            glyph_name=str(value.get("glyph_name") or (f"uni{clean_codepoint}" if clean_codepoint else "")),
            font_id=str(value.get("font_id") or font_id),
            font_path=str(value.get("font_path") or font_path),
            display_name=str(value.get("display_name") or value.get("glyph_name") or clean_codepoint or replacement_char),
            usage=usage,
            is_pua=_is_hex_pua(clean_codepoint),
            source=source,
            advance_width=clean_advance,
            bbox=clean_bbox,
            preview_path=str(value.get("preview_path") or "") or None,
        )

    def to_override(self, index: int, *, source: str | None = None) -> dict[str, Any]:
        return {
            "index": int(index),
            "base_char": self.base_char,
            "original_char": self.base_char,
            "replacement_char": self.replacement_char,
            "codepoint": self.codepoint,
            "glyph_name": self.glyph_name,
            "font_id": self.font_id,
            "font_path": self.font_path,
            "usage": self.usage,
            "source": source or self.source,
            "is_pua": self.is_pua,
            "is_mapped": bool(self.codepoint),
        }


@dataclass(frozen=True)
class GlyphCatalog:
    font_id: str
    font_path: str
    modified_time: float
    variants: tuple[GlyphVariant, ...]
    warnings: tuple[str, ...] = ()


_GLYPH_CATALOG_CACHE: dict[tuple[str, str], GlyphCatalog] = {}

@dataclass(frozen=True)
class RuntimeDependencyStatus:
    python_executable: str
    missing_packages: tuple[str, ...]
    install_command: str

    @property
    def ok(self) -> bool:
        return not self.missing_packages

    @property
    def message(self) -> str:
        if self.ok:
            return f"依赖检测通过。\n当前 Python 路径：{self.python_executable}"
        return (
            "字形功能缺少运行依赖。\n"
            f"当前 Python 路径：{self.python_executable}\n"
            f"缺少的包名：{', '.join(self.missing_packages)}\n"
            f"建议安装命令：{self.install_command}"
        )


@dataclass(frozen=True)
class GlyphApplyResult:
    original_text: str
    render_text: str
    font_design: str
    apply_mode: str
    source_letter: str | None
    source_index: int | None
    glyph_codepoint: str | None
    glyph_char: str | None
    glyph_source: str
    needs_review: bool
    reason: str
    glyph_overrides: dict[int, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class GlyphCandidate:
    glyph_name: str
    glyph_id: int
    unicode: str | None
    char: str | None
    is_pua: bool
    is_mapped: bool
    render_error: str = ""

    @property
    def codepoint(self) -> str:
        return self.unicode or ""

    @property
    def preview_text(self) -> str:
        return self.char or self.glyph_name


def check_runtime_dependencies(import_checker: Callable[[str], bool] | None = None) -> RuntimeDependencyStatus:
    """检测当前应用进程的 Python 依赖，避免误用系统里的其他 Python。"""
    checker = import_checker or _module_available
    missing = tuple(package for package, module in RUNTIME_DEPENDENCIES if not checker(module))
    command = f"{sys.executable} -m pip install {INSTALL_COMMAND_PACKAGES}"
    return RuntimeDependencyStatus(
        python_executable=sys.executable,
        missing_packages=missing,
        install_command=command,
    )


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        return False


@dataclass
class GlyphMapConfig:
    path: Path = DEFAULT_GLYPH_MAP_PATH
    data: dict[str, Any] | None = None
    load_warning: str = ""

    @classmethod
    def load(cls, path: Path | str = DEFAULT_GLYPH_MAP_PATH) -> "GlyphMapConfig":
        config_path = Path(path)
        if not config_path.exists():
            config = cls(path=config_path, data=default_glyph_map_payload())
            config.save()
            return config
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise json.JSONDecodeError("root is not object", "", 0)
        except (OSError, json.JSONDecodeError):
            _backup_corrupt_config(config_path)
            config = cls(
                path=config_path,
                data=default_glyph_map_payload(),
                load_warning="字形配置文件损坏，已备份并重建默认配置。",
            )
            config.save()
            return config
        return cls(path=config_path, data=_merged_default_payload(payload))

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.data if isinstance(self.data, dict) else default_glyph_map_payload()
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)
        return self.path

    def get_font_policy(self, font_design: str) -> dict[str, Any]:
        key = _font_key(font_design)
        payload = self.data if isinstance(self.data, dict) else {}
        policy = payload.get(key)
        if not isinstance(policy, dict):
            return {}
        letters = policy.get("letters")
        if not isinstance(letters, dict):
            policy["letters"] = {}
        return policy

    def get_glyph_for_letter(self, font_design: str, letter: str) -> dict[str, str] | None:
        policy = self.get_font_policy(font_design)
        letters = policy.get("letters", {})
        if not isinstance(letters, dict):
            return None
        entry = letters.get(_letter_key(letter))
        if not isinstance(entry, dict):
            return None
        codepoint = normalize_codepoint(str(entry.get("codepoint", "")))
        return {
            "codepoint": codepoint,
            "char": codepoint_to_char(codepoint),
            "label": str(entry.get("label", "")).strip(),
        }

    def set_glyph_for_letter(self, font_design: str, letter: str, codepoint: str, label: str = "") -> None:
        key = _font_key(font_design)
        payload = self.data if isinstance(self.data, dict) else default_glyph_map_payload()
        self.data = payload
        policy = payload.setdefault(
            key,
            {
                "enabled": key in {"Font 2", "Font 4"},
                "apply_mode": "replace_last_letter",
                "description": f"{key} ending swash glyphs",
                "letters": {},
            },
        )
        if not isinstance(policy, dict):
            raise ValueError("字形配置格式错误：字体策略必须是对象")
        letters = policy.setdefault("letters", {})
        if not isinstance(letters, dict):
            letters = {}
            policy["letters"] = letters
        clean_letter = _letter_key(letter)
        if not clean_letter:
            raise ValueError("字母必须是 a-z")
        clean_codepoint = normalize_codepoint(codepoint)
        letters[clean_letter] = {
            "codepoint": clean_codepoint,
            "label": label.strip() or f"{clean_letter} ending glyph",
        }


def default_glyph_map_payload() -> dict[str, Any]:
    return {
        "Font 4": {
            "enabled": True,
            "apply_mode": "replace_last_letter",
            "description": "Font 4 ending swash glyphs",
            "letters": {},
        },
        "Font 2": {
            "enabled": True,
            "apply_mode": "replace_last_letter",
            "description": "Font 2 ending swash glyphs",
            "letters": {
                letter: {
                    "codepoint": codepoint,
                    "label": f"{letter}.005 ending glyph",
                }
                for letter, codepoint in FONT2_DEFAULT_ENDING_GLYPHS.items()
            },
        },
    }


def resolve_glyph(
    original_text: str,
    font_design: str,
    glyph_config: GlyphMapConfig,
    manual_override: dict[str, str] | None = None,
    glyph_overrides: Mapping[int, Mapping[str, Any]] | None = None,
) -> GlyphApplyResult:
    text = original_text or ""
    clean_font = _font_key(font_design)
    if not text.strip():
        return _result(text, text, clean_font, "replace_last_letter", None, None, None, None, "none", True, "个性化文字为空")

    text_review, text_reason = _text_review_reason(text)
    if glyph_overrides:
        render_text, clean_overrides, override_reasons = apply_glyph_overrides(text, glyph_overrides)
        first_index = min(clean_overrides) if clean_overrides else None
        first_override = clean_overrides[first_index] if first_index is not None else {}
        reasons = list(override_reasons)
        if text_reason:
            reasons.append(text_reason)
        return _result(
            text,
            render_text,
            clean_font,
            "manual_per_character",
            str(first_override.get("original_char", "")).casefold() or None,
            first_index,
            first_override.get("codepoint") if isinstance(first_override.get("codepoint"), str) else None,
            first_override.get("char") if isinstance(first_override.get("char"), str) else None,
            "manual" if clean_overrides else "none",
            bool(reasons) or text_review,
            "；".join(reasons),
            clean_overrides,
        )

    policy = glyph_config.get_font_policy(clean_font)
    if not policy or not bool(policy.get("enabled", False)):
        return _result(text, text, clean_font, _clean_apply_mode(policy.get("apply_mode")), None, None, None, None, "none", False, "该字体未启用结尾字形")

    source_letter, source_index, accent_review = _last_latin_letter(text)
    needs_review = accent_review or text_review
    reasons: list[str] = []
    if accent_review:
        reasons.append("包含带重音拉丁字母，已按基础字母识别，建议人工确认")
    if text_reason:
        reasons.append(text_reason)
    if source_letter is None or source_index is None:
        reasons.append("未找到英文字母，未应用结尾字形")
        return _result(text, text, clean_font, _clean_apply_mode(policy.get("apply_mode")), None, None, None, None, "none", True, "；".join(reasons))

    override = manual_override or {}
    glyph_source = "manual" if override else "auto"
    apply_mode = _clean_apply_mode(override.get("apply_mode") or policy.get("apply_mode"))
    selected_letter = _letter_key(override.get("letter", "")) or source_letter
    try:
        if override.get("codepoint"):
            glyph_codepoint = normalize_codepoint(str(override["codepoint"]))
            glyph_char = codepoint_to_char(glyph_codepoint)
        else:
            glyph_entry = glyph_config.get_glyph_for_letter(clean_font, selected_letter)
            if glyph_entry is None:
                reasons.append(f"未配置 {selected_letter} 的结尾字形")
                return _result(text, text, clean_font, apply_mode, source_letter, source_index, None, None, "none", True, "；".join(reasons))
            glyph_codepoint = glyph_entry["codepoint"]
            glyph_char = glyph_entry["char"]
    except ValueError as exc:
        reasons.append(str(exc))
        return _result(text, text, clean_font, apply_mode, selected_letter, source_index, None, None, "none", True, "；".join(reasons))

    render_text = _apply_glyph(text, source_index, glyph_char, apply_mode)
    return _result(
        text,
        render_text,
        clean_font,
        apply_mode,
        selected_letter if glyph_source == "manual" else source_letter,
        source_index,
        glyph_codepoint,
        glyph_char,
        glyph_source,
        needs_review,
        "；".join(reasons),
    )


def scan_font_glyphs(font_path: str | Path, pua_only: bool = False, limit: int | None = None) -> list[GlyphCandidate]:
    path = Path(font_path)
    if not path.is_file():
        raise ValueError(f"字体文件不存在：{path}")
    try:
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        raise RuntimeError(check_runtime_dependencies().message) from exc
    try:
        font = TTFont(str(path))
    except Exception as exc:
        raise RuntimeError(f"字体文件读取失败：{path}") from exc
    try:
        glyph_order = list(font.getGlyphOrder())
        best_cmap = font.getBestCmap() or {}
        glyph_set = font.getGlyphSet()
    except Exception as exc:
        raise RuntimeError("字体 glyph 表读取失败，无法扫描字形。") from exc

    glyph_ids = {name: index for index, name in enumerate(glyph_order)}
    mapped_names: set[str] = set()
    candidates: list[GlyphCandidate] = []
    for code, glyph_name_value in sorted(best_cmap.items()):
        if not 0 <= int(code) <= 0x10FFFF:
            continue
        glyph_name = str(glyph_name_value)
        if glyph_name not in glyph_set:
            continue
        is_pua = is_pua_codepoint(int(code))
        if pua_only and not is_pua:
            continue
        mapped_names.add(glyph_name)
        candidates.append(
            GlyphCandidate(
                glyph_name=glyph_name,
                glyph_id=glyph_ids.get(glyph_name, -1),
                unicode=int_to_codepoint(int(code)),
                char=chr(int(code)),
                is_pua=is_pua,
                is_mapped=True,
            )
        )

    if not pua_only:
        for glyph_name in glyph_order:
            if glyph_name in mapped_names or glyph_name not in glyph_set:
                continue
            candidates.append(
                GlyphCandidate(
                    glyph_name=glyph_name,
                    glyph_id=glyph_ids.get(glyph_name, -1),
                    unicode=None,
                    char=None,
                    is_pua=False,
                    is_mapped=False,
                )
            )
    if limit is not None:
        candidates = candidates[: max(0, limit)]
    if not candidates:
        if pua_only:
            raise ValueError("未发现 PUA 字形，可能该字体使用 OpenType 替代字形或没有私用区字形。")
        raise ValueError("未发现可展示字形。")
    return candidates


def scan_font_pua_glyphs(font_path: str | Path) -> list[GlyphCandidate]:
    return scan_font_glyphs(font_path, pua_only=True)


def filter_glyph_candidates(candidates: list[GlyphCandidate], query: str = "", filter_mode: str = "All glyphs") -> list[GlyphCandidate]:
    """按 UI 搜索条件过滤字形，支持字符、glyph name 和 codepoint。"""
    mode = str(filter_mode or "All glyphs").strip().casefold()
    if mode not in {
        "all glyphs",
        "完整字体",
        "全部字形",
        "unicode mapped",
        "unicode mapped glyphs",
        "unicode 映射",
        "pua only",
        "私用区 pua",
        "pua",
        "unmapped glyphs",
        "未映射 glyph",
        "未映射字形",
    }:
        mode = "all glyphs"
    filtered = [
        glyph
        for glyph in candidates
        if (
            mode in {"all glyphs", "完整字体", "全部字形"}
            or (mode in {"unicode mapped", "unicode mapped glyphs", "unicode 映射"} and glyph.is_mapped)
            or (mode in {"pua only", "私用区 pua", "pua"} and glyph.is_pua)
            or (mode in {"unmapped glyphs", "未映射 glyph", "未映射字形"} and not glyph.is_mapped)
        )
    ]
    clean_query = str(query or "").strip().casefold()
    if not clean_query:
        return filtered
    code_query = clean_query.removeprefix("u+")
    return [glyph for glyph in filtered if _glyph_matches_query(glyph, clean_query, code_query)]


def render_glyph_thumbnail(font_path: str | Path, glyph: GlyphCandidate, image_size: int = 72, font_size: int = 56):
    """生成真实字形缩略图；mapped 用 Pillow 文本，unmapped 用 freetype glyph index。"""
    path = Path(font_path)
    if not path.is_file():
        raise ValueError(f"字体文件不存在：{path}")
    if glyph.char:
        return _render_mapped_thumbnail(path, glyph.char, image_size, font_size)
    return _render_unmapped_thumbnail(path, glyph.glyph_id, image_size, font_size)


def glyph_candidate_to_override(glyph: GlyphCandidate, original_char: str) -> dict[str, Any]:
    """把面板选中的字形转换为按位置覆盖结构。"""
    return {
        "original_char": original_char,
        "glyph_name": glyph.glyph_name,
        "glyph_id": glyph.glyph_id,
        "codepoint": glyph.unicode,
        "char": glyph.char,
        "is_pua": glyph.is_pua,
        "is_mapped": glyph.is_mapped,
    }


def apply_glyph_overrides(
    text: str,
    glyph_overrides: Mapping[int, Mapping[str, Any]],
) -> tuple[str, dict[int, dict[str, Any]], list[str]]:
    """按文字位置应用字形覆盖；无 Unicode 的 glyph 保留原字，交给 PNG 预览按 glyph_id 绘制。"""
    chars = list(text)
    clean_overrides: dict[int, dict[str, Any]] = {}
    reasons: list[str] = []
    for raw_index, raw_override in sorted(glyph_overrides.items(), key=lambda item: _safe_int(item[0], 10**9)):
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            reasons.append(f"字形覆盖索引无效：{raw_index}")
            continue
        if index < 0 or index >= len(chars):
            reasons.append(f"字形覆盖位置 {index} 已超出当前文字长度，已跳过。")
            continue
        original_char = str(raw_override.get("original_char", ""))
        if original_char and chars[index] != original_char:
            reasons.append(f"位置 {index} 原字符已从 {original_char} 变为 {chars[index]}，已跳过该字形绑定。")
            continue
        codepoint = raw_override.get("codepoint") or raw_override.get("unicode")
        clean_codepoint: str | None = None
        glyph_char: str | None = None
        if codepoint:
            try:
                clean_codepoint = normalize_codepoint(str(codepoint))
                glyph_char = codepoint_to_char(clean_codepoint)
                chars[index] = glyph_char
            except ValueError as exc:
                reasons.append(str(exc))
                continue
        glyph_name = str(raw_override.get("glyph_name") or f"glyph-{raw_override.get('glyph_id', index)}")
        glyph_id = _safe_int(raw_override.get("glyph_id"), -1)
        is_pua = is_pua_codepoint(int(clean_codepoint[2:], 16)) if clean_codepoint else False
        clean_overrides[index] = {
            "original_char": original_char or text[index],
            "glyph_name": glyph_name,
            "glyph_id": glyph_id,
            "codepoint": clean_codepoint,
            "char": glyph_char,
            "is_pua": is_pua,
            "is_mapped": clean_codepoint is not None,
        }
        if clean_codepoint is None:
            reasons.append(f"{glyph_name} 可预览但暂不支持导出；后续需要通过 glyph outline 转路径。")
    return "".join(chars), clean_overrides, reasons


def font_contains_codepoint(font_path: str | Path, codepoint: str) -> bool:
    path = Path(font_path)
    if not path.is_file():
        raise ValueError(f"字体文件不存在：{path}")
    try:
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        raise RuntimeError("当前环境未安装 fontTools，无法校验字体码位。") from exc

    code = int(normalize_codepoint(codepoint)[2:], 16)
    try:
        font = TTFont(str(path))
        for table in font["cmap"].tables:
            if code in table.cmap:
                return True
    except Exception as exc:
        raise RuntimeError(f"字体文件读取失败：{path}") from exc
    return False


def normalize_codepoint(value: str) -> str:
    clean = str(value or "").strip().upper()
    match = re.fullmatch(r"(?:U\+)?([0-9A-F]{4,6})", clean)
    if not match:
        raise ValueError(f"codepoint 格式错误：{value}")
    code = int(match.group(1), 16)
    if code > 0x10FFFF:
        raise ValueError(f"codepoint 超出 Unicode 范围：{value}")
    return int_to_codepoint(code)


def codepoint_to_char(codepoint: str) -> str:
    return chr(int(normalize_codepoint(codepoint)[2:], 16))


def int_to_codepoint(value: int) -> str:
    return f"U+{value:04X}"


def is_pua_codepoint(value: int) -> bool:
    return any(start <= value <= end for start, end in PUA_RANGES)


def _glyph_matches_query(glyph: GlyphCandidate, clean_query: str, code_query: str) -> bool:
    if glyph.char and clean_query in glyph.char.casefold():
        return True
    if clean_query in glyph.glyph_name.casefold():
        return True
    if glyph.unicode:
        compact_codepoint = glyph.unicode.casefold().replace("u+", "")
        return code_query in compact_codepoint or clean_query in glyph.unicode.casefold()
    return False


def _render_mapped_thumbnail(path: Path, char: str, image_size: int, font_size: int):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError(check_runtime_dependencies().message) from exc
    image = Image.new("RGBA", (image_size, image_size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype(str(path), font_size)
    except Exception as exc:
        raise RuntimeError(f"字体缩略图加载失败：{path}") from exc
    bbox = draw.textbbox((0, 0), char, font=font)
    width = max(1, bbox[2] - bbox[0])
    height = max(1, bbox[3] - bbox[1])
    x = (image_size - width) / 2 - bbox[0]
    y = (image_size - height) / 2 - bbox[1]
    draw.text((x, y), char, fill="#111111", font=font)
    return image


def _render_unmapped_thumbnail(path: Path, glyph_id: int, image_size: int, font_size: int):
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(check_runtime_dependencies().message) from exc
    try:
        import freetype
    except ImportError as exc:
        raise RuntimeError(check_runtime_dependencies().message) from exc
    image = Image.new("RGBA", (image_size, image_size), (255, 255, 255, 0))
    try:
        face = freetype.Face(str(path))
        face.set_pixel_sizes(0, font_size)
        face.load_glyph(glyph_id, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_NORMAL)
    except Exception as exc:
        raise RuntimeError(f"glyph index 渲染失败：{glyph_id}") from exc
    bitmap = face.glyph.bitmap
    width = int(bitmap.width)
    rows = int(bitmap.rows)
    if width <= 0 or rows <= 0:
        return image
    pitch = abs(int(bitmap.pitch))
    raw = bytes(bitmap.buffer)
    alpha = b"".join(raw[row * pitch : row * pitch + width] for row in range(rows))
    glyph_mask = Image.frombytes("L", (width, rows), alpha)
    glyph_image = Image.new("RGBA", (width, rows), (17, 17, 17, 255))
    x = max(0, (image_size - width) // 2)
    y = max(0, (image_size - rows) // 2)
    image.paste(glyph_image, (x, y), glyph_mask)
    return image


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _backup_corrupt_config(config_path: Path) -> None:
    if not config_path.exists():
        return
    backup_path = config_path.with_suffix(f"{config_path.suffix}.bak")
    try:
        backup_path.write_bytes(config_path.read_bytes())
    except OSError:
        return


def _merged_default_payload(payload: dict[str, Any]) -> dict[str, Any]:
    merged = default_glyph_map_payload()
    for font_key, policy in payload.items():
        if not isinstance(policy, dict):
            continue
        clean_key = _font_key(str(font_key))
        target = merged.setdefault(
            clean_key,
            {
                "enabled": False,
                "apply_mode": "replace_last_letter",
                "description": f"{clean_key} ending swash glyphs",
                "letters": {},
            },
        )
        target["enabled"] = bool(policy.get("enabled", target.get("enabled", False)))
        target["apply_mode"] = _clean_apply_mode(policy.get("apply_mode", target.get("apply_mode")))
        target["description"] = str(policy.get("description", target.get("description", "")))
        letters = policy.get("letters", {})
        if isinstance(letters, dict):
            target_letters: dict[str, dict[str, str]] = {}
            for letter, entry in letters.items():
                if not isinstance(entry, dict):
                    continue
                try:
                    clean_letter = _letter_key(str(letter))
                    if clean_letter:
                        target_letters[clean_letter] = {
                            "codepoint": normalize_codepoint(str(entry.get("codepoint", ""))),
                            "label": str(entry.get("label", "")).strip(),
                        }
                except ValueError:
                    continue
            target["letters"] = target_letters
    return merged


def _font_key(font_design: str) -> str:
    text = str(font_design or "").strip()
    match = re.search(r"font\s*([0-9]+)", text, flags=re.IGNORECASE)
    if match:
        return f"Font {int(match.group(1))}"
    return text or "Unknown"


def _letter_key(letter: str) -> str:
    clean = str(letter or "").strip().casefold()
    return clean if re.fullmatch(r"[a-z]", clean) else ""


def _clean_apply_mode(value: object) -> str:
    clean = str(value or "replace_last_letter").strip()
    return clean if clean in VALID_APPLY_MODES else "replace_last_letter"


def _last_latin_letter(text: str) -> tuple[str | None, int | None, bool]:
    for index in range(len(text) - 1, -1, -1):
        char = text[index]
        if "a" <= char <= "z" or "A" <= char <= "Z":
            return char.casefold(), index, False
        normalized = unicodedata.normalize("NFKD", char)
        base = "".join(part for part in normalized if not unicodedata.combining(part))
        if len(base) == 1 and ("a" <= base <= "z" or "A" <= base <= "Z") and base != char:
            return base.casefold(), index, True
    return None, None, False


def _text_review_reason(text: str) -> tuple[bool, str]:
    if len(text) > 32 or "\n" in text or re.search(r"[.!?;\u3002\uff01\uff1f\u2026]", text):
        return True, "文本较长或包含句子标点，建议人工确认结尾字形"
    return False, ""


def _apply_glyph(text: str, source_index: int, glyph_char: str, apply_mode: str) -> str:
    if apply_mode == "append_suffix":
        return text + glyph_char
    return text[:source_index] + glyph_char + text[source_index + 1 :]


def _is_displayable_glyph_code(code: int) -> bool:
    if code in {0, 9, 10, 13, 32, 160}:
        return False
    category = unicodedata.category(chr(code))
    return not category.startswith("C") or is_pua_codepoint(code)


def _result(
    original_text: str,
    render_text: str,
    font_design: str,
    apply_mode: str,
    source_letter: str | None,
    source_index: int | None,
    glyph_codepoint: str | None,
    glyph_char: str | None,
    glyph_source: str,
    needs_review: bool,
    reason: str,
    glyph_overrides: dict[int, dict[str, Any]] | None = None,
) -> GlyphApplyResult:
    return GlyphApplyResult(
        original_text=original_text,
        render_text=render_text,
        font_design=font_design,
        apply_mode=apply_mode,
        source_letter=source_letter,
        source_index=source_index,
        glyph_codepoint=glyph_codepoint,
        glyph_char=glyph_char,
        glyph_source=glyph_source,
        needs_review=needs_review,
        reason=reason,
        glyph_overrides=glyph_overrides or {},
    )


@dataclass
class GlyphBindingsConfig:
    path: Path = DEFAULT_GLYPH_BINDINGS_PATH
    data: dict[str, Any] | None = None
    load_warning: str = ""

    @classmethod
    def load(cls, path: Path | str = DEFAULT_GLYPH_BINDINGS_PATH) -> "GlyphBindingsConfig":
        return _load_json_config(cls, Path(path), default_glyph_bindings_payload(), "字形绑定配置文件损坏，已备份并重建空配置。")

    def save(self) -> Path:
        payload = self.data if isinstance(self.data, dict) else default_glyph_bindings_payload()
        return _atomic_write_json(self.path, payload)

    def binding_for_codepoint(self, font_id: str, codepoint: str) -> dict[str, Any] | None:
        font_payload = _font_payload(self.data, font_id)
        bindings = font_payload.get("bindings") if isinstance(font_payload, dict) else None
        if not isinstance(bindings, dict):
            return None
        entry = bindings.get(_codepoint_hex(codepoint))
        return entry if isinstance(entry, dict) else None

    def set_binding(self, font_id: str, font_path: str | Path, variant: GlyphVariant, base_char: str, usage: str = "any", display_name: str = "") -> None:
        clean_base = str(base_char or "")[:1]
        if not clean_base:
            raise ValueError("base_char 不能为空")
        clean_usage = str(usage or "any").casefold()
        if clean_usage not in VALID_GLYPH_USAGES:
            raise ValueError("usage 只允许 start / middle / end / any")
        clean_codepoint = _codepoint_hex(variant.codepoint)
        if not clean_codepoint:
            raise ValueError("codepoint 格式无效")
        payload = self.data if isinstance(self.data, dict) else default_glyph_bindings_payload()
        self.data = payload
        fonts = payload.setdefault("fonts", {})
        font_payload = fonts.setdefault(_font_key(font_id), {"font_path": str(font_path), "bindings": {}})
        font_payload["font_path"] = str(font_path)
        bindings = font_payload.setdefault("bindings", {})
        bindings[clean_codepoint] = {
            "base_char": clean_base,
            "usage": clean_usage,
            "display_name": display_name.strip() or variant.display_name or f"{clean_base} {clean_usage}",
            "glyph_name": variant.glyph_name,
        }


def default_glyph_bindings_payload() -> dict[str, Any]:
    return {
        "fonts": {
            "Font 2": {
                "font_path": "",
                "bindings": {
                    codepoint.removeprefix("U+"): {
                        "base_char": letter,
                        "usage": "end",
                        "display_name": f"{letter}.005 ending glyph",
                        "glyph_name": f"{letter}.005",
                    }
                    for letter, codepoint in FONT2_DEFAULT_ENDING_GLYPHS.items()
                },
            }
        }
    }


@dataclass
class GlyphRulesConfig:
    path: Path = DEFAULT_GLYPH_RULES_PATH
    data: dict[str, Any] | None = None
    load_warning: str = ""

    @classmethod
    def load(cls, path: Path | str = DEFAULT_GLYPH_RULES_PATH) -> "GlyphRulesConfig":
        return _load_json_config(cls, Path(path), default_glyph_rules_payload(), "自动字形规则文件损坏，已备份并重建默认配置。")

    def save(self) -> Path:
        payload = self.data if isinstance(self.data, dict) else default_glyph_rules_payload()
        return _atomic_write_json(self.path, payload)

    @property
    def enabled(self) -> bool:
        return bool((self.data or {}).get("enabled", True))

    def font_rules(self, font_id: str) -> dict[str, Any]:
        payload = self.data if isinstance(self.data, dict) else {}
        fonts = payload.get("fonts")
        if not isinstance(fonts, dict):
            return {}
        rules = fonts.get(_font_key(font_id)) or fonts.get(str(font_id).casefold())
        return rules if isinstance(rules, dict) else {}


def default_glyph_rules_payload() -> dict[str, Any]:
    return {
        "enabled": True,
        "fonts": {
            "Font 4": {"end_char_rules": {}, "start_char_rules": {}},
            "Font 2": {
                "end_char_rules": {
                    letter: codepoint.removeprefix("U+")
                    for letter, codepoint in FONT2_DEFAULT_ENDING_GLYPHS.items()
                },
                "start_char_rules": {},
            },
        },
    }


def build_glyph_catalog(font_path: str | Path, font_id: str = "", bindings: GlyphBindingsConfig | None = None) -> GlyphCatalog:
    """扫描单个字体的 glyph catalog；单字体失败只影响本次调用并写日志。"""
    path = Path(font_path)
    clean_font_id = _font_key(font_id or path.stem)
    try:
        modified = path.stat().st_mtime
    except OSError as exc:
        LOGGER.exception("字体加载失败：font_path=%s error=%s", path, exc)
        raise ValueError(f"字体文件不存在：{path}") from exc
    key = (str(path.resolve()), clean_font_id)
    cached = _GLYPH_CATALOG_CACHE.get(key)
    if cached and cached.modified_time == modified:
        return cached
    warnings: list[str] = []
    try:
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        LOGGER.exception("字体扫描依赖缺失：font_path=%s", path)
        raise RuntimeError(check_runtime_dependencies().message) from exc
    try:
        font = TTFont(str(path))
    except Exception as exc:
        LOGGER.exception("字体加载失败：font_path=%s error=%s", path, exc)
        raise RuntimeError(f"字体文件读取失败：{path}") from exc
    variants: list[GlyphVariant] = []
    try:
        cmap = font.getBestCmap() or {}
    except Exception as exc:
        LOGGER.warning("字体 cmap 表读取失败：font_path=%s error=%s", path, exc)
        warnings.append("字体 cmap 表读取失败。")
        cmap = {}
    try:
        glyph_set = font.getGlyphSet()
    except Exception as exc:
        LOGGER.warning("字体 glyph set 读取失败：font_path=%s error=%s", path, exc)
        warnings.append("字体 glyph set 读取失败。")
        glyph_set = {}
    hmtx = font["hmtx"].metrics if "hmtx" in font else {}
    binding_config = bindings or GlyphBindingsConfig.load()
    for code, glyph_name in sorted(cmap.items()):
        code_hex = f"{int(code):04X}"
        char = chr(int(code))
        glyph = glyph_set.get(glyph_name) if hasattr(glyph_set, "get") else None
        bbox = _glyph_bbox(glyph)
        advance = hmtx.get(glyph_name, (None, None))[0] if isinstance(hmtx, dict) else None
        binding = binding_config.binding_for_codepoint(clean_font_id, code_hex) or {}
        source = "manual_binding" if binding else "cmap"
        variants.append(GlyphVariant.from_mapping({
            "base_char": binding.get("base_char", ""),
            "replacement_char": char,
            "codepoint": code_hex,
            "glyph_name": binding.get("glyph_name") or glyph_name,
            "font_id": clean_font_id,
            "font_path": str(path),
            "display_name": binding.get("display_name") or glyph_name,
            "usage": binding.get("usage", "any"),
            "source": source,
            "advance_width": advance,
            "bbox": bbox,
        }))
    catalog = GlyphCatalog(clean_font_id, str(path), modified, tuple(variants), tuple(warnings))
    _GLYPH_CATALOG_CACHE[key] = catalog
    return catalog


def recommended_glyph_variants(catalog: GlyphCatalog, base_char: str) -> list[GlyphVariant]:
    ch = str(base_char or "")[:1]
    if not ch:
        return []
    lower = ch.casefold()
    patterns = (lower, f"{lower}.", f".{lower}", f"{lower}_", f"_{lower}", f"{lower}.alt", f"{lower}.swash", f"{lower}.end", f"{lower}.start")
    result: list[GlyphVariant] = []
    for variant in catalog.variants:
        name = variant.glyph_name.casefold()
        if variant.base_char.casefold() == lower:
            result.append(variant)
        elif any(pattern in name for pattern in patterns) and not (variant.is_pua and not variant.base_char):
            result.append(variant)
        elif variant.source == "gsub" and variant.base_char.casefold() == lower:
            result.append(variant)
    seen: set[tuple[str, str]] = set()
    unique: list[GlyphVariant] = []
    for variant in result:
        item_key = (variant.codepoint, variant.glyph_name)
        if item_key not in seen:
            seen.add(item_key)
            unique.append(variant)
    return unique


def rebuild_render_text(original_text: str, glyph_overrides: Mapping[int, Mapping[str, Any]] | None, *, font_path: str | Path | None = None, text_layer_id: str = "") -> tuple[str, dict[int, dict[str, Any]], list[str]]:
    """由 original_text + glyph_overrides 重建 render_text；任何无效覆盖都降级并记录 warning。"""
    text = original_text or ""
    chars = list(text)
    clean: dict[int, dict[str, Any]] = {}
    warnings: list[str] = []
    for raw_index, raw in sorted((glyph_overrides or {}).items(), key=lambda item: _safe_int(item[0], 10**9)):
        try:
            index = int(raw.get("index", raw_index) if isinstance(raw, Mapping) else raw_index)
        except (TypeError, ValueError):
            warnings.append(f"字形覆盖索引无效：{raw_index}")
            LOGGER.warning("字形替换失败：text_layer_id=%s original_text=%r index=%r reason=invalid-index", text_layer_id, text, raw_index)
            continue
        if index < 0 or index >= len(chars):
            warnings.append(f"字形覆盖位置 {index} 已超出当前文字长度，已忽略。")
            LOGGER.warning("glyph override index 越界：text_layer_id=%s original_text=%r index=%s", text_layer_id, text, index)
            continue
        if not isinstance(raw, Mapping):
            warnings.append(f"字形覆盖位置 {index} 配置无效，已忽略。")
            continue
        base_char = str(raw.get("base_char") or raw.get("original_char") or chars[index])[:1]
        if chars[index] != base_char:
            warnings.append(f"位置 {index} 原字符已变化，特殊字形已忽略。")
            LOGGER.warning("glyph override base_char 不匹配：text_layer_id=%s original_text=%r index=%s base_char=%r actual=%r", text_layer_id, text, index, base_char, chars[index])
            continue
        replacement = str(raw.get("replacement_char") or raw.get("char") or "")
        codepoint = _codepoint_hex(str(raw.get("codepoint") or raw.get("unicode") or ""))
        if not replacement and codepoint:
            try:
                replacement = chr(int(codepoint, 16))
            except (TypeError, ValueError):
                replacement = ""
        if not replacement:
            warnings.append(f"位置 {index} replacement_char 无效，已使用原字符。")
            LOGGER.warning("字形替换失败：text_layer_id=%s original_text=%r index=%s base_char=%r replacement_char=%r", text_layer_id, text, index, base_char, raw.get("replacement_char"))
            continue
        if font_path and codepoint:
            try:
                if not font_contains_codepoint(font_path, codepoint):
                    warnings.append(f"字形 {codepoint} 当前字体不可用，已使用原字符。")
                    LOGGER.warning("字形不存在：font_path=%s codepoint=%s glyph_name=%s index=%s", font_path, codepoint, raw.get("glyph_name"), index)
                    continue
            except Exception as exc:
                warnings.append(f"字形 {codepoint} 校验失败，已使用原字符。")
                LOGGER.warning("字形校验失败：font_path=%s codepoint=%s error=%s", font_path, codepoint, exc)
                continue
        chars[index] = replacement
        clean[index] = {
            "index": index,
            "base_char": base_char,
            "original_char": base_char,
            "replacement_char": replacement,
            "char": replacement,
            "codepoint": codepoint,
            "glyph_name": str(raw.get("glyph_name") or (f"uni{codepoint}" if codepoint else "glyph")),
            "font_id": str(raw.get("font_id") or ""),
            "font_path": str(raw.get("font_path") or font_path or ""),
            "usage": str(raw.get("usage") or "any") if str(raw.get("usage") or "any") in VALID_GLYPH_USAGES else "any",
            "source": str(raw.get("source") or "manual"),
            "is_pua": _is_hex_pua(codepoint),
            "is_mapped": bool(codepoint),
        }
    return "".join(chars), clean, warnings


def apply_glyph_variant_to_text(original_text: str, glyph_overrides: Mapping[int, Mapping[str, Any]] | None, index: int, variant: GlyphVariant, *, font_path: str | Path | None = None, text_layer_id: str = "") -> tuple[str, dict[int, dict[str, Any]], list[str]]:
    if index < 0 or index >= len(original_text or ""):
        LOGGER.warning("字形替换失败：text_layer_id=%s original_text=%r index=%s glyph_name=%s", text_layer_id, original_text, index, variant.glyph_name)
        raise ValueError("请选择当前文字中的有效字符。")
    overrides = {int(k): dict(v) for k, v in (glyph_overrides or {}).items()}
    base_char = original_text[index]
    override = variant.to_override(index, source=variant.source if variant.source != "cmap" else "manual")
    override["base_char"] = base_char
    override["original_char"] = base_char
    overrides[index] = override
    return rebuild_render_text(original_text, overrides, font_path=font_path, text_layer_id=text_layer_id)


def remove_glyph_override(original_text: str, glyph_overrides: Mapping[int, Mapping[str, Any]] | None, index: int, *, font_path: str | Path | None = None, text_layer_id: str = "") -> tuple[str, dict[int, dict[str, Any]], list[str]]:
    overrides = {int(k): dict(v) for k, v in (glyph_overrides or {}).items() if int(k) != int(index)}
    LOGGER.info("恢复普通字符：text_layer_id=%s index=%s", text_layer_id, index)
    return rebuild_render_text(original_text, overrides, font_path=font_path, text_layer_id=text_layer_id)


def apply_automatic_glyph_rules(original_text: str, font_id: str, font_path: str | Path | None, glyph_overrides: Mapping[int, Mapping[str, Any]] | None = None, rules: GlyphRulesConfig | None = None, *, order_id: str = "") -> tuple[str, dict[int, dict[str, Any]], list[str], bool]:
    rules_config = rules or GlyphRulesConfig.load()
    overrides = {int(k): dict(v) for k, v in (glyph_overrides or {}).items()}
    warnings: list[str] = []
    if not rules_config.enabled:
        render_text, clean, rebuild_warnings = rebuild_render_text(original_text, overrides, font_path=font_path)
        return render_text, clean, rebuild_warnings, False
    font_rules = rules_config.font_rules(font_id)
    if not font_rules or not (original_text or "").strip():
        render_text, clean, rebuild_warnings = rebuild_render_text(original_text, overrides, font_path=font_path)
        return render_text, clean, rebuild_warnings, False
    applied = False

    def add_rule(index: int, codepoint: str, usage: str, rule_name: str) -> None:
        nonlocal applied
        if index in overrides and overrides[index].get("source") == "manual":
            return
        clean_code = _codepoint_hex(codepoint)
        if not clean_code:
            msg = f"自动字形规则 {rule_name} codepoint 无效"
            warnings.append(msg)
            LOGGER.warning("自动字形规则失败：order_id=%s font_id=%s rule=%s reason=bad-codepoint", order_id, font_id, rule_name)
            return
        if font_path:
            try:
                if not font_contains_codepoint(font_path, clean_code):
                    msg = f"自动字形 {clean_code} 当前字体不可用"
                    warnings.append(msg)
                    LOGGER.warning("自动字形规则失败：order_id=%s font_id=%s rule=%s reason=missing-codepoint codepoint=%s", order_id, font_id, rule_name, clean_code)
                    return
            except Exception as exc:
                warnings.append(f"自动字形 {clean_code} 校验失败")
                LOGGER.warning("自动字形规则失败：order_id=%s font_id=%s rule=%s reason=%s", order_id, font_id, rule_name, exc)
                return
        base_char = original_text[index]
        overrides[index] = {
            "index": index,
            "base_char": base_char,
            "original_char": base_char,
            "replacement_char": chr(int(clean_code, 16)),
            "char": chr(int(clean_code, 16)),
            "codepoint": clean_code,
            "glyph_name": f"uni{clean_code}",
            "font_id": _font_key(font_id),
            "font_path": str(font_path or ""),
            "usage": usage,
            "source": "rule",
        }
        applied = True

    stripped = original_text.rstrip()
    if stripped:
        start_rules = font_rules.get("start_char_rules") if isinstance(font_rules.get("start_char_rules"), dict) else {}
        end_rules = font_rules.get("end_char_rules") if isinstance(font_rules.get("end_char_rules"), dict) else {}
        first_index = next((i for i, ch in enumerate(original_text) if not ch.isspace()), None)
        if first_index is not None:
            cp = start_rules.get(original_text[first_index]) or start_rules.get(original_text[first_index].casefold())
            if cp:
                add_rule(first_index, str(cp), "start", "start_char_rules")
        end_index = len(stripped) - 1
        while end_index >= 0 and not stripped[end_index].isalnum():
            end_index -= 1
        if end_index >= 0:
            ch = stripped[end_index]
            cp = end_rules.get(ch) or end_rules.get(ch.casefold())
            if cp:
                add_rule(end_index, str(cp), "end", "end_char_rules")
    render_text, clean, rebuild_warnings = rebuild_render_text(original_text, overrides, font_path=font_path)
    return render_text, clean, [*warnings, *rebuild_warnings], applied


def candidate_to_variant(glyph: GlyphCandidate, *, font_id: str, font_path: str | Path, base_char: str = "", usage: str = "any") -> GlyphVariant:
    return GlyphVariant.from_mapping({
        "base_char": base_char,
        "replacement_char": glyph.char or (codepoint_to_char(glyph.unicode) if glyph.unicode else ""),
        "codepoint": glyph.unicode or "",
        "glyph_name": glyph.glyph_name,
        "font_id": font_id,
        "font_path": str(font_path),
        "display_name": glyph.glyph_name,
        "usage": usage,
        "source": "cmap",
    })


def _glyph_bbox(glyph) -> tuple[float, float, float, float] | None:
    if glyph is None:
        return None
    try:
        return (float(glyph.xMin), float(glyph.yMin), float(glyph.xMax), float(glyph.yMax))
    except Exception:
        return None


def _load_json_config(cls, path: Path, default_payload: dict[str, Any], warning: str):
    if not path.exists():
        config = cls(path=path, data=default_payload)
        config.save()
        return config
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise json.JSONDecodeError("root is not object", "", 0)
    except (OSError, json.JSONDecodeError) as exc:
        backup = _backup_broken_json(path)
        LOGGER.warning("配置文件损坏：file_path=%s backup_path=%s error=%s", path, backup, exc)
        config = cls(path=path, data=default_payload, load_warning=warning)
        config.save()
        return config
    return cls(path=path, data=_merge_config(default_payload, payload))


def _merge_config(default_payload: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(default_payload))
    for key, value in payload.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return path


def _backup_broken_json(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.stem}.broken.{stamp}{path.suffix}")
    try:
        backup.write_bytes(path.read_bytes())
    except OSError as exc:
        LOGGER.warning("配置文件备份失败：file_path=%s backup_path=%s error=%s", path, backup, exc)
    return backup


def _font_payload(data: dict[str, Any] | None, font_id: str) -> dict[str, Any]:
    fonts = (data or {}).get("fonts")
    if not isinstance(fonts, dict):
        return {}
    payload = fonts.get(_font_key(font_id)) or fonts.get(str(font_id)) or fonts.get(str(font_id).casefold())
    return payload if isinstance(payload, dict) else {}


def _codepoint_hex(value: str | None) -> str:
    raw = str(value or "").strip().upper().removeprefix("U+").removeprefix("0X")
    if not raw:
        return ""
    try:
        code = int(raw, 16)
    except ValueError:
        LOGGER.warning("codepoint 格式无效：%s", value)
        return ""
    if not 0 <= code <= 0x10FFFF:
        LOGGER.warning("codepoint 超出 Unicode 范围：%s", value)
        return ""
    return f"{code:04X}"


def _is_hex_pua(value: str) -> bool:
    if not value:
        return False
    try:
        return is_pua_codepoint(int(value, 16))
    except ValueError:
        return False
