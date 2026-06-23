"""MaterialLibrary 构造 / 查找 / catalog 单测（见 ExecPlan §3）。

用临时目录造小素材，不依赖私有 BirthMonth flowers 资产，可在任意环境跑。
"""

from __future__ import annotations

import json
from pathlib import Path

from material_library import Catalog, MaterialLibrary

_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0h10v10H0z"/></svg>'


def _write(path: Path, text: str = _SVG) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------- 零配置：birth-flower
def test_zero_config_birth_flower_keeps_month_tags(tmp_path: Path):
    _write(tmp_path / "March_Daffodil.svg")
    _write(tmp_path / "March_CherryBlossom.svg")

    library = MaterialLibrary.from_folder(tmp_path, library_id="birth-flowers", kind="image")

    assert library.id == "birth-flowers"
    assert library.kind == "image"
    keys = {entry.key for entry in library.entries}
    assert "daffodil" in keys  # key 取纯花名（已去月份）

    daffodil = library.by_key("daffodil")
    assert daffodil is not None
    assert daffodil.tags.get("month") == 3  # month/flower 仅作上下文标签保留
    assert daffodil.tags.get("flower") == 1  # daffodil 在三月排第一


def test_zero_config_birth_flower_catalog(tmp_path: Path):
    _write(tmp_path / "January_Snowdrop.svg")
    library = MaterialLibrary.from_folder(tmp_path, kind="image")
    catalog = library.catalog()
    assert isinstance(catalog, Catalog)
    assert "snowdrop" in catalog.keys()  # key 取纯花名（已去月份）
    item = next(iter(catalog.items))
    assert item["tags"].get("month") == 1


# ---------------------------------------------------------------- 零配置：通用图像
def test_zero_config_generic_images(tmp_path: Path):
    _write(tmp_path / "border-floral.svg")
    (tmp_path / "star-badge.png").write_bytes(b"\x89PNG\r\n")

    library = MaterialLibrary.from_folder(tmp_path, kind="image")
    keys = {entry.key for entry in library.entries}
    assert keys == {"border-floral", "star-badge"}
    border = library.by_key("border-floral")
    assert border is not None
    assert "month" not in border.tags  # 非花朵素材无月份标签


def test_zero_config_mixes_birth_flower_and_generic(tmp_path: Path):
    """并集扫描：带月份的花与不带月份的新素材在同一文件夹里共存，都要进库。"""
    _write(tmp_path / "March_Daffodil.svg")  # 带月份名 → 保留 month/flower 标签
    _write(tmp_path / "X.svg")  # 不带月份名 → 旧逻辑会被丢弃，现按文件名收
    (tmp_path / "lens-clear.png").write_bytes(b"\x89PNG\r\n")

    library = MaterialLibrary.from_folder(tmp_path, kind="image")
    keys = {entry.key for entry in library.entries}
    assert keys == {"daffodil", "x", "lens-clear"}  # 三个都进库，无重复

    daffodil = library.by_key("daffodil")
    assert daffodil is not None and daffodil.tags.get("month") == 3  # 花仍带月份标签
    x = library.by_key("x")
    assert x is not None and "month" not in x.tags  # 非花素材无月份标签


# ---------------------------------------------------------------- 清单驱动
def test_manifest_drives_keys_aliases_and_defaults(tmp_path: Path):
    _write(tmp_path / "leo.svg")
    manifest = {
        "id": "zodiac",
        "name": "星座",
        "kind": "image",
        "defaults": {"width": 900, "height": 900},
        "materials": [
            {
                "key": "leo",
                "name": "Leo 狮子座",
                "file": "leo.svg",
                "aliases": ["狮子", "lion"],
                "tags": {"element": "fire"},
                "defaults": {"width": 1000},
            },
            {"key": "virgo", "name": "Virgo", "file": "missing.svg"},
        ],
    }
    (tmp_path / "library.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    library = MaterialLibrary.from_folder(tmp_path)
    assert library.id == "zodiac"
    assert library.name == "星座"
    assert library.defaults is not None and library.defaults.width == 900

    leo = library.by_key("leo")
    assert leo is not None
    assert leo.defaults is not None and leo.defaults.width == 1000  # per-素材覆盖库默认
    assert "狮子" in leo.aliases
    assert leo.tags.get("element") == "fire"

    virgo = library.by_key("virgo")
    assert virgo is not None
    assert virgo.warnings  # 文件缺失被记录
    assert virgo.is_vector_safe is False


def test_manifest_match_by_alias_and_case(tmp_path: Path):
    _write(tmp_path / "leo.svg")
    manifest = {
        "id": "zodiac",
        "kind": "image",
        "materials": [{"key": "leo", "name": "Leo", "file": "leo.svg", "aliases": ["狮子", "lion"]}],
    }
    (tmp_path / "library.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    library = MaterialLibrary.from_folder(tmp_path)

    assert library.match("狮子") is library.by_key("leo")
    assert library.match("lion") is library.by_key("leo")
    assert library.match("LEO").key == "leo"  # key 大小写不敏感
    assert library.match("不存在的素材") is None


# ---------------------------------------------------------------- 边界
def test_missing_folder_returns_empty_library(tmp_path: Path):
    library = MaterialLibrary.from_folder(tmp_path / "nope", library_id="ghost", kind="image")
    assert library.id == "ghost"
    assert library.entries == ()
    assert library.catalog().keys() == set()


def test_font_source_can_be_single_file(tmp_path: Path):
    # 兼容旧 font_source = 单个 .ttf 文件（非目录）
    font = tmp_path / "MalovelyScript.ttf"
    font.write_bytes(b"fake-font")
    library = MaterialLibrary.from_folder(font, kind="font")
    assert library.kind == "font"
    assert library.entries  # 单文件也成库
    assert library.entries[0].tags.get("index") == 1
