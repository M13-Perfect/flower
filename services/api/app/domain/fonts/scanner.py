from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from pathlib import Path
from typing import Any

from app.domain import DomainError
from app.domain.settings import get_path_settings, has_saved_path_settings


PROJECT_ROOT = Path(__file__).resolve().parents[5]
FONT_DIRECTORIES = ("assets/fonts", "BirthMonth flowers")
FONT_FILES = ("Birthmonth_font.ttf",)
SUPPORTED_FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".otc"}
PUA_RANGES = (
    (0xE000, 0xF8FF),
    (0xF0000, 0xFFFFD),
    (0x100000, 0x10FFFD),
)


@dataclass(frozen=True)
class FontScanIssue:
    code: str
    message: str
    path: str | None = None
    recoverable: bool = True


@dataclass(frozen=True)
class FontMetrics:
    units_per_em: int
    ascender: int
    descender: int
    line_gap: int
    cap_height: int | None = None
    x_height: int | None = None
    bbox: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class FontRecord:
    id: str
    family_name: str
    style_name: str
    full_name: str
    postscript_name: str
    source_path: str
    format: str
    file_size: int
    metrics: FontMetrics
    glyph_count: int
    mapped_glyph_count: int
    pua_glyph_count: int
    fingerprint: str


@dataclass(frozen=True)
class GlyphRecord:
    glyph_id: int
    glyph_name: str
    codepoint: str | None
    char: str | None
    is_mapped: bool
    is_pua: bool
    advance_width: int | None = None
    bbox: dict[str, int] | None = None


@dataclass(frozen=True)
class FontCatalog:
    fonts: tuple[FontRecord, ...]
    issues: tuple[FontScanIssue, ...]


def list_fonts() -> FontCatalog:
    fonts: list[FontRecord] = []
    issues: list[FontScanIssue] = []
    fingerprints: dict[str, FontRecord] = {}
    ids: set[str] = set()

    for path in _discover_font_candidates(issues):
        if path.suffix.casefold() not in SUPPORTED_FONT_EXTENSIONS:
            issues.append(
                FontScanIssue(
                    code="UNSUPPORTED_FONT_FORMAT",
                    message=f"Unsupported font format: {_relative_path(path)}",
                    path=_relative_path(path),
                )
            )
            continue

        try:
            record = _scan_font_summary(path)
        except Exception:
            issues.append(
                FontScanIssue(
                    code="FONT_READ_FAILED",
                    message=f"Font could not be read: {_relative_path(path)}",
                    path=_relative_path(path),
                    recoverable=True,
                )
            )
            continue

        duplicate = fingerprints.get(record.fingerprint)
        if duplicate is not None:
            issues.append(
                FontScanIssue(
                    code="DUPLICATE_FONT",
                    message=f"Duplicate font ignored: {_relative_path(path)}",
                    path=_relative_path(path),
                    recoverable=True,
                )
            )
            continue

        if record.id in ids:
            record = _with_unique_id(record, ids)
            issues.append(
                FontScanIssue(
                    code="DUPLICATE_FONT_ID",
                    message=f"Font id was made unique: {_relative_path(path)}",
                    path=_relative_path(path),
                    recoverable=True,
                )
            )

        fingerprints[record.fingerprint] = record
        ids.add(record.id)
        fonts.append(record)

    return FontCatalog(fonts=tuple(sorted(fonts, key=lambda item: item.id)), issues=tuple(issues))


def list_glyphs(font_id: str) -> tuple[FontRecord, tuple[GlyphRecord, ...], tuple[FontScanIssue, ...]]:
    catalog = list_fonts()
    for font in catalog.fonts:
        if font.id == font_id:
            return font, _scan_font_glyphs(_source_path(font.source_path)), catalog.issues

    raise DomainError(
        code="FONT_NOT_FOUND",
        message="Font was not found.",
        details={"fontId": font_id},
        recoverable=True,
    )


def get_font_file_path(font_id: str) -> Path:
    catalog = list_fonts()
    for font in catalog.fonts:
        if font.id == font_id:
            path = _source_path(font.source_path)
            if not path.is_file():
                break
            return path

    raise DomainError(
        code="FONT_NOT_FOUND",
        message="Font was not found.",
        details={"fontId": font_id},
        recoverable=True,
    )


def _discover_font_candidates(issues: list[FontScanIssue]) -> list[Path]:
    candidates: list[Path] = []
    for directory in _font_directories():
        display_path = _relative_path(directory)
        if not directory.exists():
            issues.append(
                FontScanIssue(
                    code="FONT_DIRECTORY_MISSING",
                    message=f"Font directory not found: {display_path}",
                    path=display_path,
                )
            )
            continue
        if not directory.is_dir():
            issues.append(
                FontScanIssue(
                    code="FONT_SOURCE_NOT_DIRECTORY",
                    message=f"Font source is not a directory: {display_path}",
                    path=display_path,
                )
            )
            continue
        candidates.extend(path for path in directory.iterdir() if path.is_file())

    for relative_file in FONT_FILES:
        path = PROJECT_ROOT / relative_file
        if path.exists() and path.is_file():
            candidates.append(path)

    return sorted(candidates, key=lambda item: _relative_path(item).casefold())


def _scan_font_summary(path: Path) -> FontRecord:
    from fontTools.ttLib import TTFont

    font = TTFont(str(path), lazy=True)
    glyph_order = list(font.getGlyphOrder())
    cmap = _best_unicode_cmap(font)
    family = _name(font, 16) or _name(font, 1) or path.stem
    style = _name(font, 17) or _name(font, 2) or "Regular"
    full_name = _name(font, 4) or f"{family} {style}".strip()
    postscript_name = _name(font, 6) or _slug(full_name)
    pua_count = sum(1 for codepoint in cmap if is_pua_codepoint(codepoint))

    return FontRecord(
        id=_slug(family if style.casefold() == "regular" else f"{family}-{style}"),
        family_name=family,
        style_name=style,
        full_name=full_name,
        postscript_name=postscript_name,
        source_path=_relative_path(path),
        format=path.suffix.casefold().lstrip("."),
        file_size=path.stat().st_size,
        metrics=_font_metrics(font),
        glyph_count=len(glyph_order),
        mapped_glyph_count=len(cmap),
        pua_glyph_count=pua_count,
        fingerprint=_fingerprint(path),
    )


def _scan_font_glyphs(path: Path) -> tuple[GlyphRecord, ...]:
    from fontTools.ttLib import TTFont

    font = TTFont(str(path), lazy=True)
    glyph_order = list(font.getGlyphOrder())
    glyph_ids = {name: index for index, name in enumerate(glyph_order)}
    glyph_set = font.getGlyphSet()
    cmap = _best_unicode_cmap(font)
    hmtx = font["hmtx"].metrics if "hmtx" in font else {}
    mapped_names: set[str] = set()
    glyphs: list[GlyphRecord] = []

    for codepoint, glyph_name in sorted(cmap.items()):
        if glyph_name not in glyph_set:
            continue
        if _is_control_codepoint(codepoint):
            continue
        mapped_names.add(glyph_name)
        glyphs.append(
            GlyphRecord(
                glyph_id=glyph_ids.get(glyph_name, -1),
                glyph_name=str(glyph_name),
                codepoint=f"U+{codepoint:04X}",
                char=chr(codepoint),
                is_mapped=True,
                is_pua=is_pua_codepoint(codepoint),
                advance_width=_advance_width(hmtx, glyph_name),
                bbox=_glyph_bbox(glyph_set[glyph_name]),
            )
        )

    for glyph_name in glyph_order:
        if glyph_name in mapped_names or glyph_name not in glyph_set:
            continue
        glyphs.append(
            GlyphRecord(
                glyph_id=glyph_ids.get(glyph_name, -1),
                glyph_name=str(glyph_name),
                codepoint=None,
                char=None,
                is_mapped=False,
                is_pua=False,
                advance_width=_advance_width(hmtx, glyph_name),
                bbox=_glyph_bbox(glyph_set[glyph_name]),
            )
        )

    return tuple(glyphs)


def _is_control_codepoint(codepoint: int) -> bool:
    return 0x0000 <= codepoint <= 0x001F or 0x007F <= codepoint <= 0x009F


def _best_unicode_cmap(font: Any) -> dict[int, str]:
    cmap = font.getBestCmap() or {}
    result: dict[int, str] = {}
    for raw_codepoint, raw_glyph_name in cmap.items():
        codepoint = int(raw_codepoint)
        if 0 <= codepoint <= 0x10FFFF:
            result[codepoint] = str(raw_glyph_name)
    return result


def _font_metrics(font: Any) -> FontMetrics:
    head = font["head"] if "head" in font else None
    hhea = font["hhea"] if "hhea" in font else None
    os2 = font["OS/2"] if "OS/2" in font else None

    return FontMetrics(
        units_per_em=int(getattr(head, "unitsPerEm", 1000) or 1000),
        ascender=int(getattr(hhea, "ascent", 0) or 0),
        descender=int(getattr(hhea, "descent", 0) or 0),
        line_gap=int(getattr(hhea, "lineGap", 0) or 0),
        cap_height=_optional_int(getattr(os2, "sCapHeight", None)),
        x_height=_optional_int(getattr(os2, "sxHeight", None)),
        bbox={
            "xMin": int(getattr(head, "xMin", 0) or 0),
            "yMin": int(getattr(head, "yMin", 0) or 0),
            "xMax": int(getattr(head, "xMax", 0) or 0),
            "yMax": int(getattr(head, "yMax", 0) or 0),
        },
    )


def _glyph_bbox(glyph: Any) -> dict[str, int] | None:
    try:
        return {
            "xMin": int(glyph.xMin),
            "yMin": int(glyph.yMin),
            "xMax": int(glyph.xMax),
            "yMax": int(glyph.yMax),
        }
    except Exception:
        pass

    try:
        from fontTools.pens.boundsPen import BoundsPen

        # 不同 fontTools 版本的 glyphSet 包装对象不一定暴露 xMin/yMin，绘制一次取边界更稳。
        pen = BoundsPen(None)
        glyph.draw(pen)
        if pen.bounds is None:
            return None
        x_min, y_min, x_max, y_max = pen.bounds
        return {
            "xMin": int(x_min),
            "yMin": int(y_min),
            "xMax": int(x_max),
            "yMax": int(y_max),
        }
    except Exception:
        return None


def _advance_width(hmtx: Any, glyph_name: str) -> int | None:
    if not isinstance(hmtx, dict):
        return None
    value = hmtx.get(glyph_name)
    if not value:
        return None
    try:
        return int(value[0])
    except (TypeError, ValueError):
        return None


def _name(font: Any, name_id: int) -> str:
    if "name" not in font:
        return ""
    for record in font["name"].names:
        if record.nameID != name_id:
            continue
        try:
            value = record.toUnicode().strip()
        except Exception:
            continue
        if value:
            return value
    return ""


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _with_unique_id(record: FontRecord, used_ids: set[str]) -> FontRecord:
    index = 2
    while f"{record.id}-{index}" in used_ids:
        index += 1
    return FontRecord(
        id=f"{record.id}-{index}",
        family_name=record.family_name,
        style_name=record.style_name,
        full_name=record.full_name,
        postscript_name=record.postscript_name,
        source_path=record.source_path,
        format=record.format,
        file_size=record.file_size,
        metrics=record.metrics,
        glyph_count=record.glyph_count,
        mapped_glyph_count=record.mapped_glyph_count,
        pua_glyph_count=record.pua_glyph_count,
        fingerprint=record.fingerprint,
    )


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _font_directories() -> list[Path]:
    if has_saved_path_settings(PROJECT_ROOT):
        return [Path(path).resolve() for path in get_path_settings(PROJECT_ROOT).font_directories]
    return [(PROJECT_ROOT / relative_dir).resolve() for relative_dir in FONT_DIRECTORIES]


def _source_path(source_path: str) -> Path:
    raw_path = Path(source_path)
    path = raw_path.resolve() if raw_path.is_absolute() else (PROJECT_ROOT / source_path).resolve()
    if raw_path.is_absolute():
        return path
    if PROJECT_ROOT.resolve() not in path.parents and path != PROJECT_ROOT.resolve():
        raise DomainError(
            code="PATH_TRAVERSAL_BLOCKED",
            message="Font path is outside the project root.",
            details={"path": source_path},
            recoverable=True,
        )
    return path


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "font"


def _optional_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def is_pua_codepoint(value: int) -> bool:
    return any(start <= value <= end for start, end in PUA_RANGES)
