from __future__ import annotations

import json

from glyph_service import (
    GlyphBindingsConfig,
    GlyphRulesConfig,
    GlyphVariant,
    apply_automatic_glyph_rules,
    apply_glyph_to_text_layer,
    apply_glyph_variant_to_text,
    default_glyph_bindings_payload,
    default_glyph_rules_payload,
    get_safe_glyph_unicode,
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


def test_get_safe_glyph_unicode_never_falls_back_to_glyph_id():
    assert get_safe_glyph_unicode({"glyph_id": 10, "glyph_name": "linefeed.alt"}) is None


def test_get_safe_glyph_unicode_rejects_control_codepoint_and_allows_pua():
    assert get_safe_glyph_unicode({"unicode": "U+E001"}) == "\ue001"

    try:
        get_safe_glyph_unicode({"unicode": "U+000A"})
    except ValueError as exc:
        assert "control" in str(exc).casefold() or "控制" in str(exc)
    else:
        raise AssertionError("control codepoint must be rejected")


def test_apply_glyph_to_text_layer_preserves_raw_text_and_stores_override():
    layer = TextLayer(text="name")

    render_text, overrides, warnings = apply_glyph_to_text_layer(
        layer,
        1,
        {
            "unicode": "U+E001",
            "glyph_name": "a.swash",
            "glyph_id": 10,
            "font_path": "font.ttf",
        },
    )

    assert warnings == []
    assert layer.raw_text == "name"
    assert layer.original_text == "name"
    assert render_text == "n\ue001me"
    assert "\n" not in render_text
    assert overrides[1]["base_char"] == "a"
    assert overrides[1]["glyph_name"] == "a.swash"
    assert overrides[1]["glyph_id"] == 10
    assert overrides[1]["unicode_char"] == "\ue001"
    assert overrides[1]["font_path"] == "font.ttf"


def test_apply_glyph_to_text_layer_rejects_unmapped_glyph_id_without_newline():
    layer = TextLayer(text="name")

    try:
        apply_glyph_to_text_layer(layer, 1, {"glyph_id": 10, "glyph_name": "a.alt"})
    except ValueError as exc:
        assert "Unicode" in str(exc)
    else:
        raise AssertionError("unmapped glyph must not be applied as text")

    assert layer.raw_text == "name"
    assert layer.original_text == "name"
    assert layer.render_text == "name"
    assert layer.glyph_overrides == {}


def test_legacy_control_character_override_is_ignored():
    render_text, overrides, warnings = rebuild_render_text(
        "name",
        {
            1: {
                "index": 1,
                "base_char": "a",
                "replacement_char": "\n",
                "glyph_id": 10,
                "glyph_name": "a.bad",
            }
        },
    )

    assert render_text == "name"
    assert overrides == {}
    assert "\n" not in render_text
    assert any("control" in warning.casefold() or "控制" in warning for warning in warnings)


def test_preset_and_existing_text_glyph_paths_are_consistent():
    variant = GlyphVariant.from_mapping(
        {
            "base_char": "a",
            "replacement_char": "\ue001",
            "codepoint": "U+E001",
            "glyph_name": "a.swash",
            "glyph_id": 10,
            "font_path": "font.ttf",
        }
    )
    pre_render, pre_overrides, pre_warnings = apply_glyph_variant_to_text("name", {}, 1, variant)

    layer = TextLayer(text="name")
    post_render, post_overrides, post_warnings = apply_glyph_to_text_layer(
        layer,
        1,
        {
            "unicode": "U+E001",
            "glyph_name": "a.swash",
            "glyph_id": 10,
            "font_path": "font.ttf",
        },
    )

    assert pre_warnings == post_warnings == []
    assert pre_render == post_render == "n\ue001me"
    assert pre_overrides[1]["base_char"] == post_overrides[1]["base_char"] == "a"
    assert pre_overrides[1]["replacement_char"] == post_overrides[1]["replacement_char"] == "\ue001"


def test_text_layer_json_round_trip_preserves_raw_text_and_glyph_overrides():
    from dataclasses import asdict

    layer = TextLayer(text="name")
    apply_glyph_to_text_layer(layer, 1, {"unicode": "U+E001", "glyph_name": "a.swash", "glyph_id": 10})

    payload = json.loads(json.dumps(asdict(layer), ensure_ascii=False, default=str))
    loaded = TextLayer(**payload)

    assert loaded.raw_text == "name"
    assert loaded.original_text == "name"
    assert 1 in loaded.glyph_overrides
    assert loaded.glyph_overrides[1]["base_char"] == "a"


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
    # \u7528\u975e\u201c\u72ec\u7acb\u7231\u5fc3\u201d\u5b57\u4f53\uff08Font 9\uff09\u9a8c\u8bc1\u901a\u7528\u672b\u5b57\u89c4\u5219\u4ecd\u751f\u6548\uff08Font 4 \u5df2\u6539\u8d70\u72ec\u7acb\u7231\u5fc3\uff0c\u89c1\u4e13\u6d4b\uff09\u3002
    enabled = GlyphRulesConfig(
        data={"enabled": True, "fonts": {"Font 9": {"end_char_rules": {"n": "E123"}, "start_char_rules": {}}}}
    )
    render_text, overrides, warnings, applied, wants_heart = apply_automatic_glyph_rules("Jazmin", "Font 9", None, {}, enabled)

    assert warnings == []
    assert applied is True
    assert wants_heart is False
    assert render_text == "Jazmi\ue123"
    assert overrides[5]["source"] == "rule"

    disabled = GlyphRulesConfig(data={"enabled": False, "fonts": {"Font 9": {"end_char_rules": {"n": "E123"}}}})
    render_text, overrides, warnings, applied, wants_heart = apply_automatic_glyph_rules("Jazmin", "Font 9", None, {}, disabled)
    assert (render_text, overrides, warnings, applied, wants_heart) == ("Jazmin", {}, [], False, False)


def test_font2_default_bindings_and_rules_cover_common_ending_glyphs():
    bindings = default_glyph_bindings_payload()["fonts"]["Font 2"]["bindings"]
    rules = default_glyph_rules_payload()["fonts"]["Font 2"]["end_char_rules"]

    assert bindings["E034"]["base_char"] == "a"
    assert bindings["E04D"]["base_char"] == "z"
    assert rules["a"] == "E034"
    assert rules["z"] == "E04D"

    render_text, overrides, warnings, applied, wants_heart = apply_automatic_glyph_rules(
        "Jazmin",
        "Font 2",
        None,
        {},
        GlyphRulesConfig(data=default_glyph_rules_payload()),
    )

    assert warnings == []
    assert applied is True
    assert wants_heart is False
    assert render_text == "Jazmi\ue041"
    assert overrides[5]["codepoint"] == "E041"


def test_font4_default_bindings_and_rules_cover_heart_ending_glyphs():
    bindings = default_glyph_bindings_payload()["fonts"]["Font 4"]["bindings"]
    rules = default_glyph_rules_payload()["fonts"]["Font 4"]["end_char_rules"]

    assert len(bindings) == 26
    assert bindings["E034"]["base_char"] == "a"
    assert bindings["E041"]["base_char"] == "n"
    assert bindings["E04D"]["base_char"] == "z"
    assert rules["a"] == "E034"
    assert rules["n"] == "E041"
    assert rules["z"] == "E04D"

    # Font 4 \u672b\u5c3e\u6539\u7528\u72ec\u7acb\u5b9e\u5fc3\u7231\u5fc3\uff1a\u4e0d\u518d\u628a\u672b\u5b57\u66ff\u6362\u6210 PUA \u5408\u4f53\u5b57\u5f62\uff0c\u6539\u4e3a wants_ending_heart=True\uff0c
    # \u672b\u5b57\u4fdd\u6301\u539f\u6837\uff08render_text \u4e0d\u542b PUA\u3001\u4e0d\u5199 override\uff09\uff0c\u7231\u5fc3\u7531\u6e32\u67d3/\u5bfc\u51fa\u7aef\u8ffd\u52a0\u3002
    render_text, overrides, warnings, applied, wants_heart = apply_automatic_glyph_rules(
        "Jazmin",
        "Font 4",
        None,
        {},
        GlyphRulesConfig(data=default_glyph_rules_payload()),
    )

    assert warnings == []
    assert wants_heart is True
    assert applied is False
    assert render_text == "Jazmin"
    assert overrides == {}


def test_manual_override_wins_over_automatic_rule():
    # \u7528\u975e\u201c\u72ec\u7acb\u7231\u5fc3\u201d\u5b57\u4f53\uff08Font 9\uff09\uff1a\u81ea\u52a8\u672b\u5b57\u89c4\u5219\u4f1a\u547d\u4e2d\uff0c\u4f46\u624b\u52a8\u8986\u76d6\u5e94\u80dc\u51fa\uff08Font 4 \u672b\u5b57\u5df2\u4e0d\u8d70\u89c4\u5219\uff09\u3002
    manual = {5: {"index": 5, "base_char": "n", "replacement_char": "\ue999", "codepoint": "E999", "source": "manual"}}
    rules = GlyphRulesConfig(data={"enabled": True, "fonts": {"Font 9": {"end_char_rules": {"n": "E123"}}}})

    render_text, overrides, _warnings, applied, wants_heart = apply_automatic_glyph_rules("Jazmin", "Font 9", None, manual, rules)

    assert applied is False
    assert wants_heart is False
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
    assert rules.data["fonts"]["Font 2"]["end_char_rules"]["n"] == "E041"
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
