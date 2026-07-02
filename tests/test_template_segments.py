from __future__ import annotations

from prompt_references import (
    ReferenceField,
    SYSTEM_SOURCE_LABELS,
    field_token,
    iter_template_segments,
    render_template_view,
    system_token,
)


def _field(
    *,
    field_id: str = "11111111-1111-4111-8111-111111111111",
    scope_id: str = "product",
    sequence_number: int = 3,
    name: str = "Birthday Month",
) -> ReferenceField:
    return ReferenceField(
        id=field_id,
        scope_id=scope_id,
        sequence_number=sequence_number,
        reference_name=name,
        prompt="Extract month",
        sort_order=sequence_number,
        enabled=True,
        created_at="2026-06-23T00:00:00+00:00",
        updated_at="2026-06-23T00:00:00+00:00",
    )


def test_iter_template_segments_maps_tokens_to_visible_names_in_order():
    field = _field()
    template = f"A {field_token(field.id)} B {system_token('order_information')} C {field_token(field.id)}"

    assert list(iter_template_segments(template, fields=(field,), scope_id="product")) == [
        ("text", "A "),
        ("field", field.id, "/Birthday Month"),
        ("text", " B "),
        ("source", "order_information", "/" + SYSTEM_SOURCE_LABELS["order_information"]),
        ("text", " C "),
        ("field", field.id, "/Birthday Month"),
    ]


def test_iter_template_segments_keeps_plain_slash_text_plain():
    assert list(iter_template_segments("plain /Birthday Month", fields=(), scope_id="product")) == [
        ("text", "plain /Birthday Month"),
    ]


def test_iter_template_segments_marks_unknown_field_without_losing_id():
    missing_id = "99999999-9999-4999-8999-999999999999"

    assert list(iter_template_segments(field_token(missing_id), fields=(), scope_id="product")) == [
        ("field", missing_id, "/无效字段"),
    ]


def test_render_template_view_reuses_segment_mapping():
    field = _field()
    template = f"{field_token(field.id)} {system_token('order_information')}"

    assert render_template_view(template, fields=(field,), scope_id="product") == (
        "/Birthday Month /" + SYSTEM_SOURCE_LABELS["order_information"]
    )
