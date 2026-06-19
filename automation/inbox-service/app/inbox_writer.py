from __future__ import annotations

import json
import os
import re
from pathlib import Path

ORDER_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


class InboxWriteError(Exception):
    """写收件夹文件失败：非法 order_id / 路径越界 / IO 错误。"""


def write_order_file(inbox_dir: Path, order_id: str, payload: dict) -> Path:
    """把订单原子写成 ``inbox_dir/{order_id}.json``。

    先写 ``.{order_id}.json.tmp`` 再 ``os.replace`` 成最终名：保证 Flower 的 ``*.json`` 轮询
    永远看不到半写文件（临时文件前导点也不会被 glob 命中）。``order_id`` 经正则与父目录双重校验，
    杜绝路径穿越。
    """
    if not ORDER_ID_RE.match(order_id):
        raise InboxWriteError(f"非法 order_id：{order_id!r}")
    inbox_dir = inbox_dir.resolve()
    inbox_dir.mkdir(parents=True, exist_ok=True)
    final_path = (inbox_dir / f"{order_id}.json").resolve()
    if final_path.parent != inbox_dir:
        raise InboxWriteError(f"order_id 越界：{order_id!r}")
    tmp_path = inbox_dir / f".{order_id}.json.tmp"
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, final_path)
    except OSError as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise InboxWriteError(str(exc)) from exc
    return final_path
