from __future__ import annotations

import json

import pytest

from app.domain import DomainError
from app.domain.fonts import options
from app.domain.fonts.options import resolve_font_option


def test_resolve_font_option_uses_listing_mapping_not_filename_order(tmp_path, monkeypatch) -> None:
    font_dir = tmp_path / "assets" / "fonts"
    mapping_dir = tmp_path / "templates" / "font-options"
    font_dir.mkdir(parents=True)
    mapping_dir.mkdir(parents=True)
    font_path = font_dir / "z-last-file-name.ttf"
    font_path.write_bytes(b"fake font bytes")
    (mapping_dir / "birth-flower-card.json").write_text(
        json.dumps(
            {
                "listingId": "birth-flower-card",
                "listingVersion": "2026-06",
                "fontOptions": [
                    {
                        "optionNo": 5,
                        "label": "Font 5",
                        "fontId": "lovely-script",
                        "sourcePath": "assets/fonts/z-last-file-name.ttf",
                        "fingerprint": "",
                        "status": "active",
                        "previewImage": "assets/font-previews/birth-flower-card/font-5.png",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(options, "PROJECT_ROOT", tmp_path)

    resolution = resolve_font_option("birth-flower-card", "2026-06", 5)

    assert resolution.font_id == "lovely-script"
    assert resolution.label == "Font 5"
    assert resolution.issues == []


def test_resolve_font_option_reports_unmapped_option(tmp_path, monkeypatch) -> None:
    mapping_dir = tmp_path / "templates" / "font-options"
    mapping_dir.mkdir(parents=True)
    (mapping_dir / "birth-flower-card.json").write_text(
        json.dumps({"listingId": "birth-flower-card", "listingVersion": "2026-06", "fontOptions": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(options, "PROJECT_ROOT", tmp_path)

    resolution = resolve_font_option("birth-flower-card", "2026-06", 5)

    assert resolution.font_id is None
    assert [issue.code for issue in resolution.issues] == ["FONT_OPTION_UNMAPPED"]


def test_resolve_font_option_reports_missing_mapped_font_file(tmp_path, monkeypatch) -> None:
    mapping_dir = tmp_path / "templates" / "font-options"
    mapping_dir.mkdir(parents=True)
    (mapping_dir / "birth-flower-card.json").write_text(
        json.dumps(
            {
                "listingId": "birth-flower-card",
                "listingVersion": "2026-06",
                "fontOptions": [
                    {
                        "optionNo": 5,
                        "label": "Font 5",
                        "fontId": "lovely-script",
                        "sourcePath": "assets/fonts/missing.ttf",
                        "fingerprint": "",
                        "status": "active",
                        "previewImage": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(options, "PROJECT_ROOT", tmp_path)

    resolution = resolve_font_option("birth-flower-card", "2026-06", 5)

    assert resolution.font_id is None
    assert [issue.code for issue in resolution.issues] == ["FONT_ASSET_MISSING"]


@pytest.mark.parametrize("listing_id", ["../other", "bad/name", r"bad\name", "C:/bad"])
def test_resolve_font_option_rejects_invalid_listing_ids(tmp_path, monkeypatch, listing_id) -> None:
    monkeypatch.setattr(options, "PROJECT_ROOT", tmp_path)

    with pytest.raises(DomainError) as exc_info:
        resolve_font_option(listing_id, "2026-06", 5)

    assert exc_info.value.code == "FONT_OPTION_LISTING_INVALID"


def test_resolve_font_option_rejects_font_options_that_are_not_a_list(
    tmp_path, monkeypatch
) -> None:
    mapping_dir = tmp_path / "templates" / "font-options"
    mapping_dir.mkdir(parents=True)
    (mapping_dir / "birth-flower-card.json").write_text(
        json.dumps(
            {
                "listingId": "birth-flower-card",
                "listingVersion": "2026-06",
                "fontOptions": {"optionNo": 5},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(options, "PROJECT_ROOT", tmp_path)

    with pytest.raises(DomainError) as exc_info:
        resolve_font_option("birth-flower-card", "2026-06", 5)

    assert exc_info.value.code == "FONT_OPTION_MAPPING_INVALID"


@pytest.mark.parametrize("font_option", [None, {"optionNo": "abc"}, {"optionNo": 5.9}, {"optionNo": True}])
def test_resolve_font_option_rejects_malformed_font_option_entries(
    tmp_path, monkeypatch, font_option
) -> None:
    mapping_dir = tmp_path / "templates" / "font-options"
    mapping_dir.mkdir(parents=True)
    (mapping_dir / "birth-flower-card.json").write_text(
        json.dumps(
            {
                "listingId": "birth-flower-card",
                "listingVersion": "2026-06",
                "fontOptions": [font_option],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(options, "PROJECT_ROOT", tmp_path)

    with pytest.raises(DomainError) as exc_info:
        resolve_font_option("birth-flower-card", "2026-06", 5)

    assert exc_info.value.code == "FONT_OPTION_MAPPING_INVALID"


def test_resolve_font_option_reports_blank_font_id_for_existing_file(tmp_path, monkeypatch) -> None:
    font_dir = tmp_path / "assets" / "fonts"
    mapping_dir = tmp_path / "templates" / "font-options"
    font_dir.mkdir(parents=True)
    mapping_dir.mkdir(parents=True)
    (font_dir / "lovely.ttf").write_bytes(b"fake font bytes")
    (mapping_dir / "birth-flower-card.json").write_text(
        json.dumps(
            {
                "listingId": "birth-flower-card",
                "listingVersion": "2026-06",
                "fontOptions": [
                    {
                        "optionNo": 5,
                        "label": "Font 5",
                        "fontId": "",
                        "sourcePath": "assets/fonts/lovely.ttf",
                        "fingerprint": "",
                        "status": "active",
                        "previewImage": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(options, "PROJECT_ROOT", tmp_path)

    resolution = resolve_font_option("birth-flower-card", "2026-06", 5)

    assert resolution.font_id is None
    assert [issue.code for issue in resolution.issues] == ["FONT_OPTION_UNMAPPED"]
    assert "mapped font id is missing" in resolution.issues[0].message


def test_resolve_font_option_rejects_listing_version_mismatch(tmp_path, monkeypatch) -> None:
    mapping_dir = tmp_path / "templates" / "font-options"
    mapping_dir.mkdir(parents=True)
    (mapping_dir / "birth-flower-card.json").write_text(
        json.dumps(
            {
                "listingId": "birth-flower-card",
                "listingVersion": "2026-06",
                "fontOptions": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(options, "PROJECT_ROOT", tmp_path)

    with pytest.raises(DomainError) as exc_info:
        resolve_font_option("birth-flower-card", "2026-07", 5)

    assert exc_info.value.code == "FONT_OPTION_VERSION_MISMATCH"
    assert exc_info.value.details == {
        "listingId": "birth-flower-card",
        "requestedVersion": "2026-07",
        "mappingVersion": "2026-06",
    }
