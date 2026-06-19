from __future__ import annotations

import json

import pytest

from app.inbox_writer import InboxWriteError, write_order_file


def test_atomic_write_creates_file_without_tmp_leftover(tmp_path):
    inbox = tmp_path / "inbox"
    path = write_order_file(inbox, "ORD-1", {"order_id": "ORD-1", "remark": "hi"})
    assert path.is_file()
    assert path.name == "ORD-1.json"
    assert json.loads(path.read_text(encoding="utf-8"))["remark"] == "hi"
    assert not list(inbox.glob(".*"))  # 无残留 .tmp


@pytest.mark.parametrize("bad", ["../evil", "a/b", "a b", "", "a\\b", "a*b"])
def test_rejects_illegal_order_id(tmp_path, bad):
    with pytest.raises(InboxWriteError):
        write_order_file(tmp_path / "inbox", bad, {"x": 1})


def test_overwrites_same_id_atomically(tmp_path):
    inbox = tmp_path / "inbox"
    write_order_file(inbox, "ORD-1", {"remark": "v1"})
    write_order_file(inbox, "ORD-1", {"remark": "v2"})
    assert json.loads((inbox / "ORD-1.json").read_text(encoding="utf-8"))["remark"] == "v2"
    assert len(list(inbox.glob("*.json"))) == 1
