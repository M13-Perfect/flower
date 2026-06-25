from pathlib import Path

from asset_resolver import scan_flower_assets, scan_font_assets


def test_scan_flower_assets_collects_each_svg_by_filename(tmp_path):
    flower_dir = tmp_path / "BirthMonth flowers"
    flower_dir.mkdir()
    (flower_dir / "SnowdropJanuary .svg").write_text("<svg />", encoding="utf-8")
    (flower_dir / "CarnationJanuary .svg").write_text("<svg />", encoding="utf-8")
    (flower_dir / "DaffodilMarch.svg").write_text("<svg />", encoding="utf-8")
    (flower_dir / "CherryMarch.svg").write_text("<svg />", encoding="utf-8")

    assets = scan_flower_assets(flower_dir)

    # 零配置：name 就是原始 stem（去首尾空白），不识别月份/花序号，顺序按文件名 casefold。
    assert [asset.name for asset in assets] == [
        "CarnationJanuary",
        "CherryMarch",
        "DaffodilMarch",
        "SnowdropJanuary",
    ]


def test_scan_flower_assets_only_picks_svg(tmp_path):
    (tmp_path / "Rose.svg").write_text("<svg />", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    (tmp_path / "Tulip.png").write_bytes(b"png")

    assets = scan_flower_assets(tmp_path)

    assert [asset.name for asset in assets] == ["Rose"]
    assert assets[0].path == tmp_path / "Rose.svg"


def test_scan_flower_assets_missing_directory_returns_empty(tmp_path):
    assert scan_flower_assets(tmp_path / "does-not-exist") == []


def test_scan_font_assets_accepts_single_ttf_file(tmp_path):
    font_path = tmp_path / "Birthmonth_font.ttf"
    font_path.write_bytes(b"font")

    assets = scan_font_assets(font_path)

    assert len(assets) == 1
    assert assets[0].index == 1
    assert assets[0].path == Path(font_path)


def test_scan_font_assets_indexes_from_filename_number(tmp_path):
    (tmp_path / "Front1.ttf").write_bytes(b"1" * 10)
    (tmp_path / "Front2.ttf").write_bytes(b"2" * 20)
    (tmp_path / "Front4.otf").write_bytes(b"4" * 40)

    assets = scan_font_assets(tmp_path)

    # 一个字体文件 = 一个 asset；index 取自文件名第一段数字，不再按业务家族拆成两编号。
    assert [(asset.index, asset.path.name) for asset in assets] == [
        (1, "Front1.ttf"),
        (2, "Front2.ttf"),
        (4, "Front4.otf"),
    ]
    by_index = {asset.index: asset for asset in assets}
    assert by_index[1].font_design == "Font 1"
    assert by_index[2].font_design == "Font 2"
    assert by_index[4].font_design == "Font 4"
    # has_ending_glyphs 仅 index ∈ {2, 4}。
    assert by_index[1].has_ending_glyphs is False
    assert by_index[2].has_ending_glyphs is True
    assert by_index[4].has_ending_glyphs is True


def test_scan_font_assets_fills_unnumbered_files_into_free_indexes(tmp_path):
    (tmp_path / "Front2.ttf").write_bytes(b"2" * 20)
    (tmp_path / "Other.otf").write_bytes(b"o" * 5)

    assets = scan_font_assets(tmp_path)

    # 有数字的占住其号；无数字文件按字母序补到剩余空号（这里空号是 1）。
    assert [(asset.index, asset.path.name) for asset in assets] == [
        (1, "Other.otf"),
        (2, "Front2.ttf"),
    ]


def test_scan_flower_assets_adds_general_asset_metadata(tmp_path):
    flower_path = tmp_path / "June Rose.svg"
    flower_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L1 1"/></svg>', encoding="utf-8")

    assets = scan_flower_assets(tmp_path)

    # key/display_name 直接来自原始文件名（不剥离月份词）。
    assert assets[0].name == "June Rose"
    assert assets[0].asset_key == "june-rose"
    assert assets[0].display_name == "June Rose"
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
