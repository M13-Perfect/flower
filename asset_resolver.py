from __future__ import annotations

import re
from pathlib import Path
import xml.etree.ElementTree as ET

from models import FlowerAsset, FontAsset


FONT_EXTENSIONS = {".ttf", ".otf"}

# 字体编号直接取自文件名里的数字（Front1.ttf→1、Front2.ttf→2…），不再用业务字体家族硬编码表。
# index 是字体身份主键：→ font_design "Font N" → glyph_service 的末尾字形/爱心规则（Font 2 花体、
# Font 4 独立爱心），故文件名数字必须与目标编号一致。
_FONT_INDEX_RE = re.compile(r"(\d+)")

# 目录扫描缓存：切产品/重扫频繁，磁盘扫描+SVG 解析+字体名读取最贵。按「目录下相关文件的
# (名字, mtime_ns, 大小) 签名」缓存——任意增/删/改文件签名即变，缓存自动失效；导入新库目录
# （新增文件）天然会因签名变化重扫，故对「导入新库」正确失效。每入口最多保留近用的若干目录。
_SCAN_CACHE_LIMIT = 16
_FLOWER_CACHE: dict[str, tuple[tuple, list[FlowerAsset]]] = {}
_FONT_CACHE: dict[str, tuple[tuple, list[FontAsset]]] = {}


def _dir_signature(root: Path, suffixes: set[str]) -> tuple:
    """目录下匹配后缀的文件签名：每个文件取 (名字, mtime_ns, 大小)，对增/删/改敏感。"""
    items: list[tuple[str, int, int]] = []
    try:
        for entry in root.iterdir():
            if not entry.is_file() or entry.suffix.casefold() not in suffixes:
                continue
            try:
                st = entry.stat()
            except OSError:
                continue
            items.append((entry.name.casefold(), st.st_mtime_ns, st.st_size))
    except OSError:
        return ()
    items.sort()
    return tuple(items)


def _file_signature(path: Path) -> tuple:
    try:
        st = path.stat()
    except OSError:
        return ()
    return (path.name.casefold(), st.st_mtime_ns, st.st_size)


def _cache_get(cache: dict, key: str, signature: tuple):
    cached = cache.get(key)
    if cached is not None and cached[0] == signature:
        # 返回副本，防止调用方就地修改污染缓存。
        return list(cached[1])
    return None


def _cache_put(cache: dict, key: str, signature: tuple, value: list) -> None:
    if len(cache) >= _SCAN_CACHE_LIMIT and key not in cache:
        # 朴素淘汰：删最早插入的一个，避免无界增长（目录数本就很少）。
        cache.pop(next(iter(cache)))
    cache[key] = (signature, list(value))


def scan_flower_assets(directory: Path | str) -> list[FlowerAsset]:
    """扫描花朵 SVG 目录：每个 .svg 一个素材，key=文件名 slug，不再识别月份/花序号。"""
    root = Path(directory)
    if not root.exists() or not root.is_dir():
        return []

    cache_key = str(root)
    signature = _dir_signature(root, {".svg"})
    cached = _cache_get(_FLOWER_CACHE, cache_key, signature)
    if cached is not None:
        return cached

    assets: list[FlowerAsset] = []
    for path in sorted(root.glob("*.svg"), key=lambda item: item.name.casefold()):
        name = path.stem.strip()
        raster_warnings = _embedded_raster_warnings(path)
        assets.append(
            FlowerAsset(
                name=name,
                path=path,
                asset_key=_asset_key(name),
                display_name=name,
                category="birth_flower",
                is_vector_safe=not raster_warnings,
                embedded_raster_warnings=tuple(raster_warnings),
            )
        )
    _cache_put(_FLOWER_CACHE, cache_key, signature, assets)
    return assets


def scan_font_assets(source: Path | str) -> list[FontAsset]:
    """字体源可为单个字体文件，也可为字体目录；每个字体文件一个 FontAsset。

    编号 index 取自文件名数字（Front1→1…）。无数字的文件按字母序补到剩余空号上，
    保证 index 稳定且不撞号。
    """
    path = Path(source)
    if path.is_file() and path.suffix.casefold() in FONT_EXTENSIONS:
        cache_key = f"file:{path}"
        signature = _file_signature(path)
        cached = _cache_get(_FONT_CACHE, cache_key, signature)
        if cached is not None:
            return cached
        result = _index_fonts([path])
        _cache_put(_FONT_CACHE, cache_key, signature, result)
        return result
    if not path.exists() or not path.is_dir():
        return []

    cache_key = f"dir:{path}"
    signature = _dir_signature(path, FONT_EXTENSIONS)
    cached = _cache_get(_FONT_CACHE, cache_key, signature)
    if cached is not None:
        return cached
    fonts = [
        item for item in path.iterdir() if item.is_file() and item.suffix.casefold() in FONT_EXTENSIONS
    ]
    result = _index_fonts(fonts)
    _cache_put(_FONT_CACHE, cache_key, signature, result)
    return result


def _index_fonts(fonts: list[Path]) -> list[FontAsset]:
    numbered: list[tuple[int, Path]] = []
    unnumbered: list[Path] = []
    for font in fonts:
        match = _FONT_INDEX_RE.search(font.stem)
        if match:
            numbered.append((int(match.group(1)), font))
        else:
            unnumbered.append(font)

    # ponytail: 文件名数字相同会撞号（两个都拿同一 index），现实里 Front1-4 唯一，故不额外去重；
    # 真出现重名再加去重。无数字文件补到剩余空号。
    used = {index for index, _font in numbered}
    next_index = 1
    for font in sorted(unnumbered, key=lambda item: item.name.casefold()):
        while next_index in used:
            next_index += 1
        numbered.append((next_index, font))
        used.add(next_index)
        next_index += 1

    return [_font_asset(font, index) for index, font in sorted(numbered, key=lambda item: item[0])]


def _font_asset(path: Path, index: int) -> FontAsset:
    return FontAsset(
        name=_font_display_name(path),
        index=index,
        path=path,
        font_design=f"Font {index}",
        family_name=_font_family_name(path),
        file_size=_font_size(path),
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
