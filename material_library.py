"""素材库 / 字体库抽象（见 docs/superpowers/plans/2026-06-14-layer-material-library-system.md §3）。

一个 **素材库** = 一个文件夹，可选放一份 ``library.json`` 清单：

- 有清单：按清单声明 key/显示名/别名/标签/每素材默认生产参数（最灵活，支持非花朵素材）。
- 无清单（零配置）：扫文件夹自动成库。图像库取「并集」——带月份名的文件复用
  ``asset_resolver`` 的 birth-flower 月份/花朵识别（保留旧链路标签
  ``tags={"month","flower"}``），其余 png/svg 一律按文件名取 key 收录；月份识别只决定
  带不带标签，不再当过滤闸门，故文件夹下任意图片都会进库。

库对外暴露两类视图：
- ``by_key`` / ``match``：UI / 解析器据 key 或别名定位具体素材 → 文件路径。
- ``catalog``：把库摊平成「key + 显示名 + 别名 + 标签」列表，供后续注入 GPT 做识别
  （动态枚举校验 material_key，本地不写死月份表）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asset_resolver import (
    _asset_key,
    scan_flower_assets,
    scan_font_assets,
)
from production import ProductionParams

logger = logging.getLogger(__name__)

MANIFEST_NAME = "library.json"
# 与 ui_app.IMPORTABLE_ASSET_SUFFIXES 对齐：位图素材（含 .bmp）也算素材，文件夹零配置扫描时一并收。
IMAGE_EXTENSIONS = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}


@dataclass(frozen=True)
class MaterialEntry:
    """库内一个素材；``key`` 是库内稳定唯一 slug，是解析/引用的主键。"""

    key: str
    name: str
    path: Path
    aliases: tuple[str, ...] = ()
    tags: Mapping[str, Any] = field(default_factory=dict)  # 如 birth-flower 的 {"month":3,"flower":1}
    defaults: ProductionParams | None = None  # per-素材默认生产参数（覆盖库默认）
    kind: str = "image"  # image | font
    is_vector_safe: bool = True
    warnings: tuple[str, ...] = ()

    def matches(self, query: str) -> bool:
        """key / 显示名 / 别名 任一命中即算匹配；用于人工搜索与解析器兜底。

        采用「归一化后相等或子串包含」，对大小写、空格、连字符不敏感，
        且 **保留中日韩等非 ASCII 字符**（用于中文别名匹配，如「狮子」）。
        """
        needle = _norm(query)
        if not needle:
            return False
        haystacks = [_norm(self.key), _norm(self.name)]
        haystacks.extend(_norm(alias) for alias in self.aliases)
        return any(needle == hay or needle in hay or hay in needle for hay in haystacks if hay)


@dataclass(frozen=True)
class Catalog:
    """解析器 / GPT 面向的库目录视图：仅暴露识别所需的最小字段。"""

    library_id: str
    items: tuple[dict[str, Any], ...]

    def keys(self) -> set[str]:
        return {item["key"] for item in self.items}


@dataclass(frozen=True)
class MaterialLibrary:
    """一个素材库或字体库。"""

    id: str
    name: str
    kind: str  # image | font
    root: Path
    defaults: ProductionParams | None = None  # 库级默认生产参数
    entries: tuple[MaterialEntry, ...] = ()

    def by_key(self, key: str) -> MaterialEntry | None:
        """按 key 精确定位（slug 化后比较，容忍大小写/连字符差异）。"""
        if not key:
            return None
        needle = _slug(key)
        return next((entry for entry in self.entries if _slug(entry.key) == needle), None)

    def match(self, query: str) -> MaterialEntry | None:
        """先按 key 精确命中，再按显示名/别名模糊命中；都不中返回 None。"""
        exact = self.by_key(query)
        if exact is not None:
            return exact
        return next((entry for entry in self.entries if entry.matches(query)), None)

    def catalog(self) -> Catalog:
        """摊平成解析器视图；标签里携带 month/flower 等便于 GPT 利用上下文。"""
        items = tuple(
            {
                "key": entry.key,
                "name": entry.name,
                "aliases": list(entry.aliases),
                "tags": dict(entry.tags),
            }
            for entry in self.entries
        )
        return Catalog(library_id=self.id, items=items)

    # ------------------------------------------------------------------ #
    # 构造
    # ------------------------------------------------------------------ #
    @classmethod
    def from_folder(
        cls,
        root: Path | str,
        *,
        library_id: str | None = None,
        name: str | None = None,
        kind: str = "image",
    ) -> "MaterialLibrary":
        """从文件夹构造库：有 library.json 用清单，否则零配置扫描。"""
        root_path = Path(root)
        fallback_id = library_id or _slug(root_path.name) or "library"
        fallback_name = name or root_path.name or fallback_id

        if not root_path.exists():
            return cls(id=fallback_id, name=fallback_name, kind=kind, root=root_path, entries=())
        # 字体源兼容「单个字体文件」（旧 font_source = Birthmonth_font.ttf）：直接扫该文件成库。
        if root_path.is_file():
            if kind == "font":
                return cls(
                    id=fallback_id,
                    name=fallback_name,
                    kind="font",
                    root=root_path.parent,
                    entries=_scan_font_entries(root_path),
                )
            return cls(id=fallback_id, name=fallback_name, kind=kind, root=root_path, entries=())

        manifest_path = root_path / MANIFEST_NAME
        if manifest_path.is_file():
            built = _from_manifest(root_path, manifest_path, fallback_id, fallback_name, kind)
            if built is not None:
                return built
            logger.warning("library.json 解析失败，退回零配置扫描：%s", manifest_path)

        if kind == "font":
            entries = _scan_font_entries(root_path)
        else:
            entries = _scan_image_entries(root_path)
        return cls(id=fallback_id, name=fallback_name, kind=kind, root=root_path, entries=entries)


# ---------------------------------------------------------------------- #
# 清单驱动
# ---------------------------------------------------------------------- #
def _from_manifest(
    root: Path,
    manifest_path: Path,
    fallback_id: str,
    fallback_name: str,
    fallback_kind: str,
) -> MaterialLibrary | None:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    kind = _str(payload.get("kind"), fallback_kind)
    library_defaults = ProductionParams.from_mapping(payload.get("defaults"))
    if library_defaults.is_empty():
        library_defaults = None

    entries: list[MaterialEntry] = []
    for raw in payload.get("materials", []) or []:
        if not isinstance(raw, dict):
            continue
        file_name = _str(raw.get("file"), "")
        if not file_name:
            continue
        path = root / file_name
        key = _str(raw.get("key"), _asset_key(Path(file_name).stem)) or _asset_key(Path(file_name).stem)
        defaults = ProductionParams.from_mapping(raw.get("defaults"))
        warnings: list[str] = []
        if not path.exists():
            warnings.append(f"素材文件缺失：{file_name}")
        entries.append(
            MaterialEntry(
                key=key,
                name=_str(raw.get("name"), Path(file_name).stem),
                path=path,
                aliases=_str_tuple(raw.get("aliases")),
                tags=raw.get("tags") if isinstance(raw.get("tags"), dict) else {},
                defaults=None if defaults.is_empty() else defaults,
                kind=kind,
                is_vector_safe=not warnings,
                warnings=tuple(warnings),
            )
        )

    return MaterialLibrary(
        id=_str(payload.get("id"), fallback_id),
        name=_str(payload.get("name"), fallback_name),
        kind=kind,
        root=root,
        defaults=library_defaults,
        entries=tuple(entries),
    )


# ---------------------------------------------------------------------- #
# 零配置扫描
# ---------------------------------------------------------------------- #
def _scan_image_entries(root: Path) -> tuple[MaterialEntry, ...]:
    """零配置扫描：文件夹下每个图片按文件名收成一个素材（key=文件名 slug），不再识别月份/花序号。

    .svg 走 scan_flower_assets 拿矢量安全检查，其余图片类型直接按文件名补进来。素材只按
    key / 花名定位（见 order_catalog.enrich_parse_result），月份不再参与选素材。
    """
    flower_assets = scan_flower_assets(root)
    entries: list[MaterialEntry] = [
        MaterialEntry(
            key=asset.asset_key or _asset_key(asset.path.stem),
            name=asset.display_name or asset.name,
            path=asset.path,
            aliases=_dedupe((asset.display_name, asset.name)),
            kind="image",
            is_vector_safe=asset.is_vector_safe,
            warnings=asset.embedded_raster_warnings,
        )
        for asset in flower_assets
    ]

    # .svg 已收录；其余图片类型按文件名补进来。
    seen = {asset.path for asset in flower_assets}
    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if path in seen or not path.is_file() or path.suffix.casefold() not in IMAGE_EXTENSIONS:
            continue
        entries.append(
            MaterialEntry(
                key=_asset_key(path.stem) or path.stem,
                name=path.stem,
                path=path,
                kind="image",
            )
        )
    return tuple(entries)


def _scan_font_entries(root: Path) -> tuple[MaterialEntry, ...]:
    """字体库零配置：复用 asset_resolver 的业务编号，标签里保留旧 font index。"""
    entries: list[MaterialEntry] = []
    for asset in scan_font_assets(root):
        key = _asset_key(asset.family_name or asset.name or asset.path.stem) or asset.path.stem
        aliases = _dedupe((asset.family_name, asset.name, asset.font_design))
        entries.append(
            MaterialEntry(
                key=key,
                name=asset.name or asset.family_name or asset.path.stem,
                path=asset.path,
                aliases=aliases,
                tags={"index": asset.index, "font_design": asset.font_design},
                kind="font",
            )
        )
    return tuple(entries)


# ---------------------------------------------------------------------- #
# 小工具
# ---------------------------------------------------------------------- #
def _slug(value: str) -> str:
    return _asset_key(value)


def _norm(value: str) -> str:
    """归一化用于模糊匹配：小写、仅保留字母数字（含 CJK），丢弃空格/标点/连字符。"""
    return "".join(ch for ch in (value or "").casefold() if ch.isalnum())


def _str(value: Any, default: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default


def _str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _dedupe(values: tuple[str | None, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        text = (value or "").strip()
        if text and text not in seen:
            seen.append(text)
    return tuple(seen)
