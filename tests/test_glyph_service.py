import sys
from pathlib import Path

import pytest

import glyph_service
from glyph_service import GlyphMapConfig, check_runtime_dependencies, scan_font_glyphs, resolve_glyph


def _config(tmp_path: Path, letters: dict[str, str] | None = None, apply_mode: str = "replace_last_letter") -> GlyphMapConfig:
    config = GlyphMapConfig.load(tmp_path / "glyph_maps.json")
    for letter, codepoint in (letters or {}).items():
        config.set_glyph_for_letter("Font 4", letter, codepoint, f"{letter} ending glyph")
    policy = config.get_font_policy("Font 4")
    policy["apply_mode"] = apply_mode
    config.save()
    return GlyphMapConfig.load(tmp_path / "glyph_maps.json")


def test_font4_jazmin_replaces_last_n_when_mapping_exists(tmp_path):
    config = _config(tmp_path, {"n": "U+E014"})

    result = resolve_glyph("Jazmin", "Font 4", config)

    assert result.original_text == "Jazmin"
    assert result.render_text == "Jazmi" + chr(0xE014)
    assert result.source_letter == "n"
    assert result.source_index == 5
    assert result.glyph_codepoint == "U+E014"
    assert result.glyph_source == "auto"
    assert result.needs_review is False


def test_font4_milla_replaces_last_a_when_mapping_exists(tmp_path):
    config = _config(tmp_path, {"a": "U+E001"})

    result = resolve_glyph("Milla", "Font 4", config)

    assert result.render_text == "Mill" + chr(0xE001)
    assert result.source_letter == "a"


def test_font1_keeps_original_text(tmp_path):
    config = _config(tmp_path, {"n": "U+E014"})

    result = resolve_glyph("Jazmin", "Font 1", config)

    assert result.render_text == "Jazmin"
    assert result.glyph_source == "none"
    assert result.needs_review is False


def test_empty_text_needs_review_without_crashing(tmp_path):
    result = resolve_glyph("", "Font 4", _config(tmp_path, {"n": "U+E014"}))

    assert result.render_text == ""
    assert result.needs_review is True
    assert result.reason == "个性化文字为空"


def test_chinese_name_needs_review_without_glyph(tmp_path):
    result = resolve_glyph("小明", "Font 4", _config(tmp_path, {"n": "U+E014"}))

    assert result.render_text == "小明"
    assert result.needs_review is True
    assert "未找到英文字母" in result.reason


def test_missing_letter_mapping_does_not_apply_glyph(tmp_path):
    result = resolve_glyph("Jazmin", "Font 4", _config(tmp_path, {"a": "U+E001"}))

    assert result.render_text == "Jazmin"
    assert result.source_letter == "n"
    assert result.glyph_char is None
    assert result.needs_review is True
    assert "未配置 n 的结尾字形" in result.reason


def test_repeated_resolve_uses_original_text_and_does_not_append_twice(tmp_path):
    config = _config(tmp_path, {"n": "U+E014"}, apply_mode="append_suffix")

    first = resolve_glyph("Jazmin", "Font 4", config)
    second = resolve_glyph("Jazmin", "Font 4", config)

    assert first.render_text == "Jazmin" + chr(0xE014)
    assert second.render_text == first.render_text


def test_manual_override_wins_over_auto_mapping(tmp_path):
    config = _config(tmp_path, {"n": "U+E014"})

    result = resolve_glyph(
        "Jazmin",
        "Font 4",
        config,
        manual_override={"letter": "z", "codepoint": "U+E099", "apply_mode": "replace_last_letter"},
    )

    assert result.render_text == "Jazmi" + chr(0xE099)
    assert result.source_letter == "z"
    assert result.glyph_codepoint == "U+E099"
    assert result.glyph_source == "manual"


def test_append_suffix_mode_appends_glyph(tmp_path):
    config = _config(tmp_path, {"n": "U+E014"}, apply_mode="append_suffix")

    result = resolve_glyph("Jazmin", "Font 4", config)

    assert result.render_text == "Jazmin" + chr(0xE014)
    assert result.apply_mode == "append_suffix"


def test_corrupt_json_is_backed_up_and_default_config_is_rebuilt(tmp_path):
    path = tmp_path / "glyph_maps.json"
    path.write_text("{broken", encoding="utf-8")

    config = GlyphMapConfig.load(path)

    assert path.with_suffix(".json.bak").exists()
    assert config.get_font_policy("Font 2")["enabled"] is True
    assert config.get_font_policy("Font 4")["enabled"] is True
    assert config.load_warning == "字形配置文件损坏，已备份并重建默认配置。"


def test_scan_font_glyphs_reads_full_font_cmap_and_pua_subset():
    font_path = Path("BirthMonth flowers") / "Malovely Script.ttf"
    if not font_path.is_file():
        pytest.skip("Optional business font asset is not present")

    all_glyphs = scan_font_glyphs(font_path, pua_only=False)
    pua_glyphs = scan_font_glyphs(font_path, pua_only=True)

    assert len(all_glyphs) > len(pua_glyphs) > 0
    assert all(glyph.codepoint.startswith("U+") for glyph in pua_glyphs)
    assert all(ord(glyph.char) >= 0xE000 for glyph in pua_glyphs)


def test_dependency_status_uses_current_python_and_actionable_install_command():
    status = check_runtime_dependencies(import_checker=lambda module: module != "PIL")

    assert status.python_executable == sys.executable
    assert status.missing_packages == ("pillow",)
    assert status.install_command == (
        f"{sys.executable} -m pip install fonttools pillow freetype-py uharfbuzz svgwrite ezdxf"
    )
    assert "当前 Python 路径" in status.message
    assert sys.executable in status.message


def test_dependency_status_handles_missing_parent_package_without_crashing(monkeypatch):
    def missing_parent(_module_name: str):
        raise ModuleNotFoundError("No module named 'fontTools'")

    monkeypatch.setattr(glyph_service.importlib.util, "find_spec", missing_parent)

    status = check_runtime_dependencies()

    assert status.missing_packages == tuple(package for package, _module in glyph_service.RUNTIME_DEPENDENCIES)


def test_scan_font_glyphs_returns_mapped_pua_and_unmapped_records():
    font_path = Path("BirthMonth flowers") / "Malovely Script.ttf"
    if not font_path.is_file():
        pytest.skip("Optional business font asset is not present")

    glyphs = scan_font_glyphs(font_path, pua_only=False)

    assert any(glyph.is_mapped and glyph.unicode and glyph.char for glyph in glyphs)
    assert any(glyph.is_pua and glyph.unicode for glyph in glyphs)
    assert any(not glyph.is_mapped and glyph.unicode is None for glyph in glyphs)
    assert all(isinstance(glyph.glyph_id, int) for glyph in glyphs)


def test_manual_per_character_overrides_replace_exact_text_positions(tmp_path):
    config = _config(tmp_path, {"n": "U+E014"})

    result = resolve_glyph(
        "Jazmin",
        "Font 4",
        config,
        glyph_overrides={
            2: {
                "original_char": "z",
                "glyph_name": "z.swash",
                "glyph_id": 184,
                "codepoint": None,
            },
            5: {
                "original_char": "n",
                "glyph_name": "n.alt",
                "glyph_id": 203,
                "codepoint": "U+E04A",
            },
        },
    )

    assert result.apply_mode == "manual_per_character"
    assert result.render_text == "Jazmi" + chr(0xE04A)
    assert result.glyph_source == "manual"
    assert result.glyph_overrides[2]["glyph_name"] == "z.swash"
    assert result.glyph_overrides[5]["codepoint"] == "U+E04A"
    assert result.needs_review is True
    assert "可预览但暂不支持导出" in result.reason
