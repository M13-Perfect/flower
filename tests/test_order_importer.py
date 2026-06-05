from order_importer import load_order_remark_from_file


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
