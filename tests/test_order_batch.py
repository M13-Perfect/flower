from __future__ import annotations

from pathlib import Path

from order_batch import ParsedOrderResult, run_batch_render, validate_parsed_order


def test_parsed_order_validation_flags_red_and_yellow():
    result = validate_parsed_order(
        ParsedOrderResult(order_id="", raw_note="raw", month=None, flower=None, personalization=None, font_design=None, confidence=0.5)
    )

    assert result.status == "failed"
    assert "order_id 为空" in result.red_flags
    assert "month 缺失" in result.red_flags
    assert "font_design 缺失" in result.yellow_flags
    assert "confidence < 0.8" in result.yellow_flags


def test_batch_render_isolates_single_order_failure(tmp_path):
    orders = [
        ParsedOrderResult(order_id="ok", raw_note="", month="1", flower="1", personalization="A", font_design=1, confidence=1),
        ParsedOrderResult(order_id="bad", raw_note="", month="1", flower="1", personalization="B", font_design=1, confidence=1),
    ]

    def render_one(order: ParsedOrderResult) -> list[Path]:
        if order.order_id == "bad":
            raise RuntimeError("boom")
        path = tmp_path / f"{order.order_id}.png"
        path.write_text("ok", encoding="utf-8")
        return [path]

    report = run_batch_render(orders, render_one)

    assert report.success_count == 1
    assert report.failure_count == 1
    assert report.items[0].status == "exported"
    assert report.items[1].status == "failed"
    assert report.items[1].error == "boom"
