"""Flower 单单收件夹监听（automation 一期）单元测试。

不构造完整 Tk 窗口：用 ``BirthFlowerApp.__new__`` 取裸实例，挂上轮询方法需要的属性 +
记录式 FakeRoot（after 只记录不执行），测试手动驱动 after(0) 派发。
覆盖：载入最新送达一单 + 新文件覆盖当前单(旧单丢弃) + 载入不移动文件 + 生成后放行下一单 +
自动解析开关 + 坏文件不堵队列 + 未配置则关。
"""

import os
from pathlib import Path

from config_store import AppConfig
from ui_app import BirthFlowerApp


class _FakeRoot:
    """记录 after 调度但不自动执行；测试手动驱动 after(0,...) 回调。"""

    def __init__(self) -> None:
        self.scheduled: list[tuple[int, object, tuple]] = []

    def after(self, delay, callback=None, *args):
        self.scheduled.append((delay, callback, args))
        return f"after#{len(self.scheduled)}"

    def after_cancel(self, _ident) -> None:
        pass


class _FakeVar:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def set(self, value) -> None:
        self._value = value

    def get(self) -> str:
        return self._value


def _make_inbox_app(inbox_folder, *, autoparse: bool = False) -> BirthFlowerApp:
    app = BirthFlowerApp.__new__(BirthFlowerApp)  # 跳过重量级 __init__
    app.root = _FakeRoot()
    app.config = AppConfig(inbox_folder=Path(inbox_folder), inbox_autoparse=autoparse)
    app._inbox_active = None
    app._inbox_after_id = None
    app._inbox_dir = None
    app._inbox_processed_dir = None
    app.remark_var = _FakeVar()
    app.warning_var = _FakeVar()
    app.status_var = _FakeVar()
    app.filename_template_var = _FakeVar()
    app.remark_text = None
    app.parse_calls = []
    app.parse_remark = lambda: app.parse_calls.append(True)  # type: ignore[method-assign]
    return app


def _run_after0(app: BirthFlowerApp) -> None:
    """执行并清掉 FakeRoot 上所有 after(0,...) 派发（模拟回到主线程载入订单）。"""
    pending = [s for s in app.root.scheduled if s[0] == 0]  # type: ignore[attr-defined]
    app.root.scheduled = [s for s in app.root.scheduled if s[0] != 0]  # type: ignore[attr-defined]
    for _delay, callback, args in pending:
        if callback is not None:
            callback(*args)


def _write_order(folder: Path, order_id: str, remark: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{order_id}.json"
    payload = '{"schema_version":"1.0","order_id":"%s","remark":"%s"}' % (order_id, remark)
    path.write_text(payload, encoding="utf-8")
    return path


def test_loads_remark_without_moving_on_load(tmp_path):
    inbox = tmp_path / "inbox"
    _write_order(inbox, "ORD-1", "name Amy May font 1 flower 2")
    app = _make_inbox_app(inbox, autoparse=False)

    app._start_inbox_poller()
    _run_after0(app)

    # 订单号置顶为第 1 行，其后接产品规格备注；订单号同时写进「文件名」框。
    assert app.remark_var.get() == "ORD-1\nname Amy May font 1 flower 2"
    assert app.filename_template_var.get() == "ORD-1"
    assert app._inbox_active is not None and app._inbox_active.name == "ORD-1.json"
    # 载入阶段不移动文件（等生成后才移走）。
    assert (inbox / "ORD-1.json").exists()
    # 单单路径默认不自动解析，更绝不自动生成。
    assert app.parse_calls == []


def test_autoparse_triggers_parse(tmp_path):
    inbox = tmp_path / "inbox"
    _write_order(inbox, "ORD-2", "name Bob June font 3 flower 1")
    app = _make_inbox_app(inbox, autoparse=True)

    app._start_inbox_poller()
    _run_after0(app)

    assert app.parse_calls == [True]  # 自动解析触发；仍停在生成前


def test_loads_newest_then_holds_until_generate_then_advances(tmp_path):
    inbox = tmp_path / "inbox"
    f1 = _write_order(inbox, "ORD-1", "first")
    f2 = _write_order(inbox, "ORD-2", "second")
    os.utime(f1, (1000, 1000))
    os.utime(f2, (2000, 2000))  # ORD-2 更新 → 最新送达，先载入
    app = _make_inbox_app(inbox, autoparse=False)

    app._start_inbox_poller()
    _run_after0(app)
    assert app.remark_var.get() == "ORD-2\nsecond"  # 最新送达的 ORD-2 先载入（订单号置顶）
    assert app.filename_template_var.get() == "ORD-2"
    assert (inbox / "ORD-1.json").exists() and (inbox / "ORD-2.json").exists()

    # 没有新文件到达 → 再轮询不变（仍是当前单）。
    app._poll_inbox_once()
    _run_after0(app)
    assert app.remark_var.get() == "ORD-2\nsecond"

    # 模拟「生成」成功 → 放行：ORD-2 移入 processed，当前单清空。
    app._advance_inbox_after_generate()
    assert app._inbox_active is None
    assert not (inbox / "ORD-2.json").exists()
    assert (inbox / "processed" / "ORD-2.json").exists()

    # 下一轮载入剩下的 ORD-1。
    app._poll_inbox_once()
    _run_after0(app)
    assert app.remark_var.get() == "ORD-1\nfirst"
    assert app.filename_template_var.get() == "ORD-1"
    assert app._inbox_active is not None and app._inbox_active.name == "ORD-1.json"


def test_newer_file_overwrites_current_and_discards_old(tmp_path):
    # 浏览器又发来一单：新文件覆盖当前订单信息+文件名，被覆盖的旧单（未生成）移入 processed 丢弃。
    inbox = tmp_path / "inbox"
    old = _write_order(inbox, "ORD-1", "first")
    os.utime(old, (1000, 1000))
    app = _make_inbox_app(inbox, autoparse=False)

    app._start_inbox_poller()
    _run_after0(app)
    assert app.remark_var.get() == "ORD-1\nfirst"
    assert app._inbox_active is not None and app._inbox_active.name == "ORD-1.json"

    new = _write_order(inbox, "ORD-2", "second")
    os.utime(new, (2000, 2000))  # 更新 → 抢占当前单
    app._poll_inbox_once()
    _run_after0(app)

    assert app.remark_var.get() == "ORD-2\nsecond"      # 覆盖订单信息
    assert app.filename_template_var.get() == "ORD-2"   # 覆盖文件名
    assert app._inbox_active is not None and app._inbox_active.name == "ORD-2.json"
    assert not (inbox / "ORD-1.json").exists()              # 旧单被丢弃
    assert (inbox / "processed" / "ORD-1.json").exists()


def test_bad_file_is_moved_and_does_not_block(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "BAD.json").write_text("{ not valid json", encoding="utf-8")
    app = _make_inbox_app(inbox, autoparse=False)

    app._start_inbox_poller()
    _run_after0(app)

    assert app._inbox_active is None  # 坏文件清掉，不挂起队列
    assert (inbox / "processed" / "BAD.json").exists()


def test_disabled_when_folder_unset(tmp_path):
    app = _make_inbox_app("", autoparse=False)  # Path("") → "."，视为功能关

    app._start_inbox_poller()

    assert app._inbox_dir is None
    assert app.root.scheduled == []
