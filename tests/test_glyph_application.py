from __future__ import annotations

import json
from pathlib import Path

from glyph_service import (
    GlyphBindingsConfig,
    GlyphRulesConfig,
    GlyphVariant,
    apply_automatic_glyph_rules,
    apply_glyph_variant_to_text,
    default_glyph_bindings_payload,
    default_glyph_rules_payload,
    rebuild_render_text,
    remove_glyph_override,
)
from models import Document, TextLayer, add_text_layer
from renderer import render_document_svg, render_document_png


def _variant() -> GlyphVariant:
    return GlyphVariant.from_mapping(
        {
            "base_char": "n",
            "replacement_char": "\ue123",
            "codepoint": "E123",
            "glyph_name": "uniE123",
            "font_id": "Font 4",
            "font_path": "",
            "display_name": "n 尾花",
            "usage": "end",
            "source": "manual_binding",
        }
    )


def test_manual_glyph_variant_updates_render_text_without_changing_original():
    original = "Jazmin"
    render_text, overrides, warnings = apply_glyph_variant_to_text(original, {}, 5, _variant())

    assert warnings == []
    assert original == "Jazmin"
    assert render_text == "Jazmi\ue123"
    assert overrides[5]["index"] == 5
    assert overrides[5]["base_char"] == "n"
    assert overrides[5]["replacement_char"] == "\ue123"
    assert overrides[5]["codepoint"] == "E123"
    assert overrides[5]["glyph_name"] == "uniE123"


def test_remove_glyph_override_restores_original_text():
    render_text, overrides, _warnings = apply_glyph_variant_to_text("Jazmin", {}, 5, _variant())
    assert render_text.endswith("\ue123")

    restored, clean, warnings = remove_glyph_override("Jazmin", overrides, 5)

    assert warnings == []
    assert restored == "Jazmin"
    assert clean == {}


def test_rebuild_render_text_ignores_out_of_range_and_base_char_mismatch(caplog):
    render_text, overrides, warnings = rebuild_render_text(
        "Jazmin",
        {
            2: {"index": 2, "base_char": "x", "replacement_char": "\ue111", "codepoint": "E111"},
            99: {"index": 99, "base_char": "n", "replacement_char": "\ue123", "codepoint": "E123"},
        },
    )

    assert render_text == "Jazmin"
    assert overrides == {}
    assert any("原字符已变化" in warning for warning in warnings)
    assert any("超出当前文字长度" in warning for warning in warnings)
    assert "glyph override" in caplog.text or "字形" in caplog.text


def test_text_layer_migrates_text_to_original_and_render_text():
    layer = TextLayer(text="Jazmin")

    assert layer.original_text == "Jazmin"
    assert layer.render_text == "Jazmin"
    assert layer.glyph_overrides == {}


def test_automatic_end_rule_applies_and_can_be_disabled():
    enabled = GlyphRulesConfig(
        data={"enabled": True, "fonts": {"Font 4": {"end_char_rules": {"n": "E123"}, "start_char_rules": {}}}}
    )
    render_text, overrides, warnings, applied = apply_automatic_glyph_rules("Jazmin", "Font 4", None, {}, enabled)

    assert warnings == []
    assert applied is True
    assert render_text == "Jazmi\ue123"
    assert overrides[5]["source"] == "rule"

    disabled = GlyphRulesConfig(data={"enabled": False, "fonts": {"Font 4": {"end_char_rules": {"n": "E123"}}}})
    render_text, overrides, warnings, applied = apply_automatic_glyph_rules("Jazmin", "Font 4", None, {}, disabled)
    assert (render_text, overrides, warnings, applied) == ("Jazmin", {}, [], False)


def test_font2_default_bindings_and_rules_cover_common_ending_glyphs():
    bindings = default_glyph_bindings_payload()["fonts"]["Font 2"]["bindings"]
    rules = default_glyph_rules_payload()["fonts"]["Font 2"]["end_char_rules"]

    assert bindings["E068"]["base_char"] == "a"
    assert bindings["E081"]["base_char"] == "z"
    assert rules["a"] == "E068"
    assert rules["z"] == "E081"

    render_text, overrides, warnings, applied = apply_automatic_glyph_rules(
        "Jazmin",
        "Font 2",
        None,
        {},
        GlyphRulesConfig(data=default_glyph_rules_payload()),
    )

    assert warnings == []
    assert applied is True
    assert render_text == "Jazmi\ue075"
    assert overrides[5]["codepoint"] == "E075"


def test_manual_override_wins_over_automatic_rule():
    manual = {5: {"index": 5, "base_char": "n", "replacement_char": "\ue999", "codepoint": "E999", "source": "manual"}}
    rules = GlyphRulesConfig(data={"enabled": True, "fonts": {"Font 4": {"end_char_rules": {"n": "E123"}}}})

    render_text, overrides, _warnings, applied = apply_automatic_glyph_rules("Jazmin", "Font 4", None, manual, rules)

    assert applied is False
    assert render_text == "Jazmi\ue999"
    assert overrides[5]["codepoint"] == "E999"


def test_corrupt_bindings_and_rules_are_backed_up_and_rebuilt(tmp_path):
    bindings_path = tmp_path / "glyph_bindings.json"
    rules_path = tmp_path / "glyph_rules.json"
    bindings_path.write_text("{broken", encoding="utf-8")
    rules_path.write_text("{broken", encoding="utf-8")

    bindings = GlyphBindingsConfig.load(bindings_path)
    rules = GlyphRulesConfig.load(rules_path)

    assert bindings.data == default_glyph_bindings_payload()
    assert rules.data["enabled"] is True
    assert rules.data["fonts"]["Font 2"]["end_char_rules"]["n"] == "E075"
    assert list(tmp_path.glob("glyph_bindings.broken.*.json"))
    assert list(tmp_path.glob("glyph_rules.broken.*.json"))


def test_document_svg_and_png_use_render_text(tmp_path):
    document = Document(300, 160)
    layer = add_text_layer(document, "Jazmin", x=10, y=10, width=200, height=80, font_size=32)
    layer.glyph_overrides[5] = _variant().to_override(5)
    layer.glyph_overrides[5]["base_char"] = "n"

    svg_path = render_document_svg(document, tmp_path / "out.svg")
    png_path = render_document_png(document, tmp_path / "out.png")

    assert "Jazmi\ue123" in svg_path.read_text(encoding="utf-8")
    assert png_path.exists()
    assert layer.original_text == "Jazmin"
    assert layer.render_text == "Jazmi\ue123"
