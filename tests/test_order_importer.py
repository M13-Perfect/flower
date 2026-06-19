import pytest

from order_importer import load_order_from_file, load_order_remark_from_file


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
