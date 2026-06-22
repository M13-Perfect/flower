import pytest

from order_importer import load_order_from_file, load_order_remark_from_file, order_from_payload


def test_load_order_from_json_returns_order_id_and_remark(tmp_path):
    # 收件夹自动化的 {order_id}.json：同时取订单号与产品规格备注。
    path = tmp_path / "4091090394.json"
    path.write_text(
        '{"schema_version":"1.0","order_id":"4091090394",'
        '"remark":"Choose Your Birth Flower: Jun - Rose / Font Design: Font 3 / Personalization: Patty",'
        '"spec":"21842163346"}',
        encoding="utf-8",
    )
    order = load_order_from_file(path)
    assert order.order_id == "4091090394"  # 取 order_id 而非 spec
    assert order.remark == "Choose Your Birth Flower: Jun - Rose / Font Design: Font 3 / Personalization: Patty"


def test_load_order_from_text_file_has_empty_order_id(tmp_path):
    # 纯文本无订单号字段 → order_id 为空串，remark 为全文。
    path = tmp_path / "remark.txt"
    path.write_text("Name: Vivian June font 1 flower 1", encoding="utf-8")
    order = load_order_from_file(path)
    assert order.order_id == ""
    assert order.remark == "Name: Vivian June font 1 flower 1"


def test_load_order_remark_from_text_file(tmp_path):
    path = tmp_path / "remark.txt"
    path.write_text("Name: Vivian June font 1 flower 1", encoding="utf-8")

    assert load_order_remark_from_file(path) == "Name: Vivian June font 1 flower 1"


def test_load_order_remark_from_json_remark_field(tmp_path):
    path = tmp_path / "order.json"
    path.write_text('{"remark": "姓名：小雅 五月 font 1 flower 2"}', encoding="utf-8")

    assert load_order_remark_from_file(path) == "姓名：小雅 五月 font 1 flower 2"


def test_load_order_remark_from_csv_prefers_remark_column(tmp_path):
    path = tmp_path / "orders.csv"
    path.write_text("order_id,remark\n1,\"ชื่อ: Dao เดือนกุมภาพันธ์ font 3 flower 1\"\n", encoding="utf-8")

    assert load_order_remark_from_file(path) == "ชื่อ: Dao เดือนกุมภาพันธ์ font 3 flower 1"


def test_load_order_remark_from_binary_file_raises_friendly_error(tmp_path):
    path = tmp_path / "orders.xlsx"
    path.write_bytes(b"\xff\xfe\x00\x00binary")

    with pytest.raises(ValueError, match="该文件是二进制格式,请确认文件类型"):
        load_order_remark_from_file(path)


# ── 2026-06-19 契约放宽：remark 可空，空时回退 items[].personalization_raw（automation 自动取单链路）──


def test_load_order_json_empty_remark_falls_back_to_items(tmp_path):
    # 空 remark + items 带 personalization_raw（混单）→ 回退拼出备注，按行用 " / " 连接。
    path = tmp_path / "4092270213.json"
    path.write_text(
        '{"schema_version":"1.0","order_id":"4092270213","remark":"",'
        '"items":[{"line_index":0,"personalization_raw":"Jun - Rose / Patty"},'
        '{"line_index":1,"personalization_raw":"May - Lily / Amy"}]}',
        encoding="utf-8",
    )
    order = load_order_from_file(path)
    assert order.order_id == "4092270213"
    assert order.remark == "Jun - Rose / Patty / May - Lily / Amy"


def test_load_order_json_standard_product_loads_with_empty_remark(tmp_path):
    # 标品/无定制单：空 remark + items 无 personalization_raw → 照常载入，remark 为空（不再抛错丢单）。
    path = tmp_path / "4002659188.json"
    path.write_text(
        '{"schema_version":"1.0","order_id":"4002659188","remark":"",'
        '"items":[{"line_index":0,"product_sku":"SKU-STD","quantity":1}]}',
        encoding="utf-8",
    )
    order = load_order_from_file(path)
    assert order.order_id == "4002659188"
    assert order.remark == ""


def test_load_order_json_remark_takes_precedence_over_items(tmp_path):
    # 顶层 remark 有值时优先用它，不走 items 回退（向后兼容）。
    path = tmp_path / "ord.json"
    path.write_text(
        '{"order_id":"X","remark":"顶层备注","items":[{"line_index":0,"personalization_raw":"行内备注"}]}',
        encoding="utf-8",
    )
    assert load_order_from_file(path).remark == "顶层备注"


def test_load_order_json_no_remark_no_items_still_raises(tmp_path):
    # 既无备注又无行项目 = 真空文件，沿用老约定报错（坏文件挪走、不堵队列）。
    path = tmp_path / "empty.json"
    path.write_text('{"schema_version":"1.0","order_id":"Z"}', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON 中未找到备注字段"):
        load_order_from_file(path)


# ── order_from_payload：库订单 dict（inbox-service /inbox/orders 一条）→ 订单号 + 备注（库驱动载单复用）──


def test_order_from_payload_takes_top_level_remark():
    order = {"order_id": "DX001", "remark": "Jun - Rose / Patty", "items": [{"personalization_raw": "行内备注"}]}
    out = order_from_payload(order)
    assert out.order_id == "DX001"
    assert out.remark == "Jun - Rose / Patty"  # 顶层 remark 优先，不走 items 回退


def test_order_from_payload_falls_back_to_items_when_remark_empty():
    order = {
        "order_id": "DX002",
        "remark": "",
        "items": [
            {"line_index": 0, "personalization_raw": "Jun - Rose / Patty"},
            {"line_index": 1, "personalization_raw": "May - Lily / Amy"},
        ],
    }
    out = order_from_payload(order)
    assert out.order_id == "DX002"
    assert out.remark == "Jun - Rose / Patty / May - Lily / Amy"


def test_order_from_payload_standard_product_empty_remark():
    # 标品单：remark 空 + items 无 personalization_raw → order_id 在、remark 空（照常载入）。
    order = {"order_id": "DX003", "remark": "", "items": [{"line_index": 0, "product_sku": "SKU", "quantity": 1}]}
    out = order_from_payload(order)
    assert out.order_id == "DX003" and out.remark == ""


def test_order_from_payload_non_dict_is_empty():
    assert order_from_payload(None) == ("", "")
    assert order_from_payload([{"order_id": "X"}]) == ("", "")
