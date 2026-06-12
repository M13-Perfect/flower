from __future__ import annotations

from pathlib import Path

from app.domain.orders.batch_import import import_orders


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "orders"


def test_dianxiaomi_xlsx_adapter_maps_a_b_columns_to_order_fields() -> None:
    batch = import_orders(
        FIXTURE_DIR / "test.xlsx",
        adapter_name="dianxiaomi-xlsx",
        batch_id="batch_real_fixture",
    )

    assert batch.batch_id == "batch_real_fixture"
    assert batch.source_adapter == "dianxiaomi-xlsx"
    assert [item.order_id for item in batch.items] == ["4087956129", "4087958577", "4087970477"]
    assert {item.listing_id for item in batch.items} == {"birth-flower-card"}
    assert all("Choose Your Birth Flower" in item.order_note for item in batch.items)
    assert all(item.personalization == "" for item in batch.items)
    assert all(item.variation == "" for item in batch.items)


def test_generic_csv_adapter_requires_only_order_id_and_order_note(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "orderId,orderNote\n"
        '1001,"Choose Your Birth Flower: Sep - Aster\nFont Design: Font 3\nPersonalization: Lacey"\n',
        encoding="utf-8-sig",
    )

    batch = import_orders(csv_path, adapter_name="generic-csv", batch_id="batch_csv")

    assert batch.source_adapter == "generic-csv"
    assert batch.items[0].order_id == "1001"
    assert batch.items[0].listing_id == "birth-flower-card"
    assert batch.items[0].status == "IMPORTED"
    assert batch.items[0].issues == []


def test_import_orders_auto_selects_adapter_by_extension(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("orderId,orderNote\n1001,note\n", encoding="utf-8")

    csv_batch = import_orders(csv_path, batch_id="batch_auto_csv")
    xlsx_batch = import_orders(FIXTURE_DIR / "test.xlsx", batch_id="batch_auto_xlsx")

    assert csv_batch.source_adapter == "generic-csv"
    assert xlsx_batch.source_adapter == "dianxiaomi-xlsx"
