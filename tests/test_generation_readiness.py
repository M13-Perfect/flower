from generation_readiness import build_generation_readiness
from models import ParseResult
from text_layout import Bounds, TextLayoutResult


def _layout(confidence=1.0, did_fit=True, warnings=None):
    return TextLayoutResult(
        did_fit=did_fit,
        final_font_size=96,
        line_count=2,
        text_bounds=Bounds(200, 900, 1200, 1040),
        safe_area_bounds=Bounds(120, 70, 1612, 1210),
        layout_confidence=confidence,
        warnings=list(warnings or []),
        lines=("I love you like", "no one else……Loves you!"),
        personalization_type="message",
    )


def test_readiness_uses_conservative_overall_score():
    readiness = build_generation_readiness(
        ParseResult(parse_confidence=0.95, asset_confidence=0.82, warnings=[]),
        _layout(confidence=0.73),
    )

    assert readiness.parse_confidence == 0.95
    assert readiness.asset_confidence == 0.82
    assert readiness.layout_confidence == 0.73
    assert readiness.overall_confidence == 0.73
    assert readiness.status == "Needs review"


def test_overflowing_layout_cannot_show_perfect_confidence():
    readiness = build_generation_readiness(
        ParseResult(parse_confidence=1.0, asset_confidence=1.0, warnings=[]),
        _layout(confidence=0.45, did_fit=False, warnings=["Text exceeds safe area"]),
    )

    assert readiness.layout_confidence == 0.45
    assert readiness.overall_confidence == 0.45
    assert readiness.status == "Needs review"
    assert "Text exceeds safe area" in readiness.warnings


def test_warnings_cap_overall_confidence_below_one():
    readiness = build_generation_readiness(
        ParseResult(parse_confidence=1.0, asset_confidence=1.0, warnings=["Missing font asset"]),
        _layout(confidence=1.0),
    )

    assert readiness.overall_confidence == 0.99
    assert readiness.status == "Needs review"
    assert "Missing font asset" in readiness.warnings


def test_missing_required_fields_are_not_ready_to_generate():
    readiness = build_generation_readiness(
        ParseResult(parse_confidence=0.2, asset_confidence=0.8, warnings=["Missing personalization"]),
        _layout(confidence=1.0),
    )

    assert readiness.status == "Cannot generate"
    assert readiness.overall_confidence == 0.2
