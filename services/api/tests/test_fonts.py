from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from app.domain.fonts import scanner
from app.main import app


def test_list_fonts_reports_scanned_fonts_and_scan_issues(tmp_path, monkeypatch) -> None:
    font_root = tmp_path / "assets" / "fonts"
    font_root.mkdir(parents=True)
    font_path = font_root / "Specimen.ttf"
    duplicate_path = font_root / "Specimen Copy.ttf"
    broken_path = font_root / "Broken.ttf"
    unsupported_path = font_root / "readme.txt"
    build_test_font(font_path, family_name="Specimen", pua_codepoint=0xE123)
    shutil.copyfile(font_path, duplicate_path)
    broken_path.write_bytes(b"not a real font")
    unsupported_path.write_text("not a font", encoding="utf-8")
    monkeypatch.setattr(scanner, "PROJECT_ROOT", tmp_path)

    response = TestClient(app).get("/fonts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["fontCount"] == 1
    assert payload["fonts"][0]["id"] == "specimen"
    assert payload["fonts"][0]["familyName"] == "Specimen"
    assert payload["fonts"][0]["metrics"]["unitsPerEm"] == 1000
    assert payload["fonts"][0]["glyphCount"] >= 3
    assert payload["fonts"][0]["mappedGlyphCount"] == 2
    assert payload["fonts"][0]["puaGlyphCount"] == 1
    assert {issue["code"] for issue in payload["issues"]} >= {
        "DUPLICATE_FONT",
        "FONT_READ_FAILED",
        "UNSUPPORTED_FONT_FORMAT",
    }
    assert all(str(tmp_path) not in issue["message"] for issue in payload["issues"])


def test_get_font_glyphs_reads_unicode_cmap_glyph_names_pua_and_metrics(
    tmp_path, monkeypatch
) -> None:
    font_root = tmp_path / "assets" / "fonts"
    font_root.mkdir(parents=True)
    build_test_font(font_root / "Specimen.ttf", family_name="Specimen", pua_codepoint=0xE123)
    monkeypatch.setattr(scanner, "PROJECT_ROOT", tmp_path)

    response = TestClient(app).get("/fonts/specimen/glyphs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["font"]["id"] == "specimen"
    glyphs_by_codepoint = {glyph["codepoint"]: glyph for glyph in payload["glyphs"]}
    assert glyphs_by_codepoint["U+0041"] == {
        "glyphId": 1,
        "glyphName": "A",
        "codepoint": "U+0041",
        "char": "A",
        "isMapped": True,
        "isPua": False,
        "advanceWidth": 620,
        "bbox": {"xMin": 0, "yMin": 0, "xMax": 500, "yMax": 700},
    }
    assert glyphs_by_codepoint["U+E123"]["glyphName"] == "uniE123.swash"
    assert glyphs_by_codepoint["U+E123"]["char"] == "\ue123"
    assert glyphs_by_codepoint["U+E123"]["isPua"] is True
    assert any(glyph["glyphName"] == "unmapped.alt" and glyph["isMapped"] is False for glyph in payload["glyphs"])


def test_get_font_glyphs_returns_structured_error_for_missing_font(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(scanner, "PROJECT_ROOT", tmp_path)

    response = TestClient(app).get("/fonts/missing/glyphs")

    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "FONT_NOT_FOUND"
    assert payload["error"]["details"] == {"fontId": "missing"}


def test_selected_font_directory_is_scanned_and_font_file_is_served(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLOWER_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(scanner, "PROJECT_ROOT", tmp_path)
    font_root = tmp_path / "external-fonts"
    font_root.mkdir()
    font_path = font_root / "Specimen.ttf"
    build_test_font(font_path, family_name="Specimen", pua_codepoint=0xE123)
    client = TestClient(app)

    settings_response = client.put(
        "/settings/paths",
        json={
            "assetDirectories": [],
            "fontDirectories": [str(font_root)],
            "outputDirectory": None,
        },
    )
    assert settings_response.status_code == 200

    fonts_response = client.get("/fonts")
    assert fonts_response.status_code == 200
    fonts_payload = fonts_response.json()
    assert fonts_payload["fontCount"] == 1
    assert fonts_payload["fonts"][0]["id"] == "specimen"

    file_response = client.get("/fonts/specimen/file")
    assert file_response.status_code == 200
    assert file_response.content == font_path.read_bytes()


def build_test_font(path: Path, *, family_name: str, pua_codepoint: int) -> None:
    glyph_order = [".notdef", "A", "uniE123.swash", "unmapped.alt"]
    glyphs = {name: draw_box_glyph() for name in glyph_order}
    advance_widths = {
        ".notdef": (500, 0),
        "A": (620, 0),
        "uniE123.swash": (700, 0),
        "unmapped.alt": (450, 0),
    }

    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap({0x0041: "A", pua_codepoint: "uniE123.swash"})
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(advance_widths)
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupOS2(
        sTypoAscender=780,
        sTypoDescender=-220,
        usWinAscent=820,
        usWinDescent=220,
    )
    builder.setupNameTable(
        {
            "familyName": family_name,
            "styleName": "Regular",
            "uniqueFontIdentifier": f"{family_name} Regular",
            "fullName": f"{family_name} Regular",
            "psName": f"{family_name}-Regular",
        }
    )
    builder.setupPost()
    builder.save(path)


def draw_box_glyph() -> Any:
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((500, 0))
    pen.lineTo((500, 700))
    pen.lineTo((0, 700))
    pen.closePath()
    return pen.glyph()
