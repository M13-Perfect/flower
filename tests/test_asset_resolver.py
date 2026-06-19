from pathlib import Path

from asset_resolver import find_flower_asset, match_asset_by_name, scan_flower_assets, scan_font_assets


def test_scan_flower_assets_assigns_month_and_flower_index_from_names(tmp_path):
    flower_dir = tmp_path / "BirthMonth flowers"
    flower_dir.mkdir()
    (flower_dir / "SnowdropJanuary .svg").write_text("<svg />", encoding="utf-8")
    (flower_dir / "CarnationJanuary .svg").write_text("<svg />", encoding="utf-8")
    (flower_dir / "DaffodilMarch.svg").write_text("<svg />", encoding="utf-8")
    (flower_dir / "CherryMarch.svg").write_text("<svg />", encoding="utf-8")

    assets = scan_flower_assets(flower_dir)

    january = [asset for asset in assets if asset.month == 1]
    march = [asset for asset in assets if asset.month == 3]
    assert [(asset.flower, asset.name) for asset in january] == [(1, "Snowdrop"), (2, "Carnation")]
    assert [(asset.flower, asset.name) for asset in march] == [(1, "Daffodil"), (2, "Cherry Blossom")]


def test_find_flower_asset_returns_requested_month_and_choice(tmp_path):
    flower_dir = tmp_path / "flowers"
    flower_dir.mkdir()
    expected = flower_dir / "LarkspurJuly.svg"
    (flower_dir / "Waterlilyjuly.svg").write_text("<svg />", encoding="utf-8")
    expected.write_text("<svg />", encoding="utf-8")

    asset = find_flower_asset(flower_dir, month=7, flower=2)

    assert asset is not None
    assert asset.path == expected
    assert asset.name == "Larkspur"


def test_scan_font_assets_accepts_single_ttf_file(tmp_path):
    font_path = tmp_path / "Birthmonth_font.ttf"
    font_path.write_bytes(b"font")

    assets = scan_font_assets(font_path)

    assert len(assets) == 1
    assert assets[0].index == 1
    assert assets[0].path == Path(font_path)


def test_scan_font_assets_splits_each_business_font_into_regular_and_ending(tmp_path):
    # 新规则：每个家族只需 1 个字体文件，同一文件同时承载「常规 / 带末尾装饰」两个编号。
    malovely = tmp_path / "Malovely Script.ttf"
    adora = tmp_path / "AdoraBella.ttf"
    malovely.write_bytes(b"m" * 20)
    adora.write_bytes(b"a" * 40)

    assets = scan_font_assets(tmp_path)

    assert [(asset.index, asset.name, asset.path.name) for asset in assets[:4]] == [
        (1, "Malovely Script", "Malovely Script.ttf"),
        (2, "Malovely Script", "Malovely Script.ttf"),
        (3, "AdoraBella", "AdoraBella.ttf"),
        (4, "AdoraBella", "AdoraBella.ttf"),
    ]
    # 1&2 同源、3&4 同源：区别只在末尾装饰，不再靠第二个文件。
    assert assets[0].path == assets[1].path
    assert assets[2].path == assets[3].path
    assert assets[0].has_ending_glyphs is False
    assert assets[1].font_design == "Font 2"
    assert assets[1].has_ending_glyphs is True
    assert assets[2].has_ending_glyphs is False
    assert assets[3].font_design == "Font 4"
    assert assets[3].has_ending_glyphs is True


def test_scan_font_assets_picks_ttf_representative_when_legacy_otf_lingers(tmp_path):
    # 家族内仍残留旧 .otf 时，取 .ttf 为代表文件，.otf 被忽略（不再编号）。
    (tmp_path / "Malovely Script.otf").write_bytes(b"m" * 10)
    (tmp_path / "Malovely Script.ttf").write_bytes(b"m" * 20)

    assets = scan_font_assets(tmp_path)

    assert [(asset.index, asset.path.name) for asset in assets] == [
        (1, "Malovely Script.ttf"),
        (2, "Malovely Script.ttf"),
    ]


def test_scan_font_assets_keeps_other_fonts_after_business_fonts(tmp_path):
    (tmp_path / "Other.otf").write_bytes(b"x" * 5)
    (tmp_path / "Malovely Script.ttf").write_bytes(b"m" * 20)

    assets = scan_font_assets(tmp_path)

    assert [(asset.index, asset.path.name) for asset in assets] == [
        (1, "Malovely Script.ttf"),
        (2, "Malovely Script.ttf"),
        (3, "Other.otf"),
    ]


def test_scan_flower_assets_adds_general_asset_metadata(tmp_path):
    flower_path = tmp_path / "June Rose.svg"
    flower_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L1 1"/></svg>', encoding="utf-8")

    assets = scan_flower_assets(tmp_path)

    assert assets[0].asset_key == "rose"  # key 取纯花名（已去月份）
    assert assets[0].display_name == "Rose"
    assert assets[0].category == "birth_flower"
    assert assets[0].is_vector_safe is True
    assert assets[0].embedded_raster_warnings == ()


def test_scan_flower_assets_detects_embedded_raster(tmp_path):
    flower_path = tmp_path / "June Rose.svg"
    flower_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="rose.png"/></svg>',
        encoding="utf-8",
    )

    assets = scan_flower_assets(tmp_path)

    assert assets[0].is_vector_safe is False
    assert "rose.png" in assets[0].embedded_raster_warnings[0]


def test_match_asset_by_name_prefers_asset_key_then_display_name(tmp_path):
    (tmp_path / "June Rose.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
    (tmp_path / "April Daisy.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
    assets = scan_flower_assets(tmp_path)

    assert match_asset_by_name(assets, "rose").display_name == "Rose"
    assert match_asset_by_name(assets, "daisy").display_name == "Daisy"
    assert match_asset_by_name(assets, "unknown") is None
