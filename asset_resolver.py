from __future__ import annotations

import re
from pathlib import Path
import xml.etree.ElementTree as ET

from models import FlowerAsset, FontAsset


MONTH_NAME_TO_NUMBER = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

PREFERRED_FLOWER_ORDER = {
    1: ("snowdrop", "carnation"),
    2: ("violet", "primrose"),
    3: ("daffodil", "cherry"),
    4: ("daisy", "sweetpea"),
    5: ("lilyofthevalley", "hawthorn"),
    6: ("rose", "honeysuckle"),
    7: ("waterlily", "larkspur"),
    8: ("poppy", "gladiolus"),
    9: ("aster", "morningglory"),
    10: ("marigold", "cosmos"),
    11: ("chrysanthemum", "peony"),
    12: ("holly", "narcissus"),
}

DISPLAY_NAMES = {
    "cherry": "Cherry Blossom",
    "lilyofthevalley": "Lily of the valley",
    "morningglory": "Morning Glory",
    "sweetpea": "Sweetpea",
    "waterlily": "Waterlily",
}

FONT_EXTENSIONS = {".ttf", ".otf"}
BUSINESS_FONT_GROUPS = (
    ("malovelyscript", 1),
    ("adorabella", 3),
)


def scan_flower_assets(directory: Path | str) -> list[FlowerAsset]:
    """扫描花朵 SVG 目录；根据文件名识别月份，并按 All in one 图中的顺序分配 flower 1-2。"""
    root = Path(directory)
    if not root.exists() or not root.is_dir():
        return []

    grouped: dict[int, list[Path]] = {}
    for path in root.glob("*.svg"):
        month = _month_from_name(path.stem)
        if month is None:
            continue
        grouped.setdefault(month, []).append(path)

    assets: list[FlowerAsset] = []
    for month, paths in sorted(grouped.items()):
        ordered = _sort_flower_paths(month, paths)
        for index, path in enumerate(ordered, start=1):
            display_name = _display_name(path.stem)
            raster_warnings = _embedded_raster_warnings(path)
            assets.append(
                FlowerAsset(
                    name=display_name,
                    month=month,
                    flower=index,
                    path=path,
                    asset_key=_asset_key(path.stem),
                    display_name=display_name,
                    category="birth_flower",
                    is_vector_safe=not raster_warnings,
                    embedded_raster_warnings=tuple(raster_warnings),
                )
            )
    return assets


def find_flower_asset(directory: Path | str, month: int, flower: int) -> FlowerAsset | None:
    for asset in scan_flower_assets(directory):
        if asset.month == month and asset.flower == flower:
            return asset
    return None


def match_asset_by_name(assets: list[FlowerAsset], query: str) -> FlowerAsset | None:
    """按通用素材名匹配素材，同时保留旧 month/flower 扫描结果。"""
    needle = _asset_key(query)
    if not needle:
        return None
    for asset in assets:
        if needle == asset.asset_key or needle in asset.asset_key:
            return asset
    for asset in assets:
        if needle == _asset_key(asset.display_name or asset.name):
            return asset
    for asset in assets:
        if needle in _asset_key(asset.display_name or asset.name):
            return asset
    return None


def scan_font_assets(source: Path | str) -> list[FontAsset]:
    """字体源可为单个字体文件，也可为字体目录，方便后期扩展到 3-8 个字体。"""
    path = Path(source)
    if path.is_file() and path.suffix.casefold() in FONT_EXTENSIONS:
        return [_font_asset(path, 1)]
    if not path.exists() or not path.is_dir():
        return []

    fonts = list(
        (item for item in path.iterdir() if item.is_file() and item.suffix.casefold() in FONT_EXTENSIONS),
    )
    return [_font_asset(font, index) for index, font in _ordered_font_paths(fonts)]


def _ordered_font_paths(fonts: list[Path]) -> list[tuple[int, Path]]:
    """按业务字体规则编号；同名字体中大文件是带字形版本。"""
    used: set[Path] = set()
    ordered: list[tuple[int, Path]] = []
    for group_key, start_index in BUSINESS_FONT_GROUPS:
        group = sorted(
            (font for font in fonts if _compact_name(font.stem) == group_key),
            key=lambda font: (_font_size(font), font.suffix.casefold(), font.name.casefold()),
        )
        for offset, font in enumerate(group[:2]):
            ordered.append((start_index + offset, font))
            used.add(font)

    next_index = 1
    used_indexes = {index for index, _font in ordered}
    for font in sorted((font for font in fonts if font not in used), key=lambda item: item.name.casefold()):
        while next_index in used_indexes:
            next_index += 1
        ordered.append((next_index, font))
        used_indexes.add(next_index)
        next_index += 1
    return sorted(ordered, key=lambda item: item[0])


def _font_asset(path: Path, index: int) -> FontAsset:
    file_size = _font_size(path)
    return FontAsset(
        name=_font_display_name(path),
        index=index,
        path=path,
        font_design=f"Font {index}",
        family_name=_font_family_name(path),
        file_size=file_size,
        has_ending_glyphs=index in {2, 4},
    )


def _font_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _font_display_name(path: Path) -> str:
    family = _font_family_name(path)
    return family or path.stem


def _font_family_name(path: Path) -> str:
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return ""
    try:
        font = TTFont(str(path), lazy=True)
        names = font["name"].names
    except Exception:
        return ""
    for name_id in (16, 1):
        for record in names:
            if record.nameID != name_id:
                continue
            try:
                value = record.toUnicode().strip()
            except Exception:
                continue
            if value:
                return value
    return ""


def _month_from_name(name: str) -> int | None:
    normalized = _compact_name(name)
    for month_name, month in MONTH_NAME_TO_NUMBER.items():
        if month_name in normalized:
            return month
    return None


def _sort_flower_paths(month: int, paths: list[Path]) -> list[Path]:
    order = PREFERRED_FLOWER_ORDER.get(month, ())

    def sort_key(path: Path) -> tuple[int, str]:
        normalized = _compact_name(path.stem)
        for index, token in enumerate(order):
            if token in normalized:
                return index, normalized
        return len(order), normalized

    return sorted(paths, key=sort_key)


def _display_name(name: str) -> str:
    compact = _compact_name(name)
    for month_name in MONTH_NAME_TO_NUMBER:
        compact = compact.replace(month_name, "")
    for token, display in DISPLAY_NAMES.items():
        if token in compact:
            return display
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", name.replace("_", " ").replace("-", " "))
    words = [word for word in words if word.casefold() not in MONTH_NAME_TO_NUMBER]
    return " ".join(words).strip() or name.strip()


def _compact_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.casefold())


def _asset_key(name: str) -> str:
    parts = re.findall(r"[a-z0-9]+", name.casefold())
    return "-".join(parts)


def _embedded_raster_warnings(path: Path) -> list[str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return [f"无法读取素材：{path}"]
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    warnings: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].casefold() != "image":
            continue
        href = element.attrib.get("href") or element.attrib.get("{http://www.w3.org/1999/xlink}href") or ""
        if href.casefold().endswith((".png", ".jpg", ".jpeg", ".webp")):
            warnings.append(f"素材嵌入位图文件，不是纯矢量：{href}")
    return warnings
