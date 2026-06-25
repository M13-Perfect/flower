"""时间选择器纯函数测试（不依赖 Tk/GUI）：解析、格式化、月历分组。

控件本体（CTkDateTimePicker）属 Tk 交互，沿项目惯例真机手测；这里只锁可单测的纯逻辑。
"""

from __future__ import annotations

from datetime import datetime

import datetime_picker as dp


def test_parse_dt_accepts_minute_second_and_date_only():
    assert dp.parse_dt("2026-06-19 02:25") == datetime(2026, 6, 19, 2, 25)
    assert dp.parse_dt("2026-06-19 02:25:30") == datetime(2026, 6, 19, 2, 25, 30)
    assert dp.parse_dt("2026-06-19") == datetime(2026, 6, 19, 0, 0)


def test_parse_dt_rejects_garbage_and_empty():
    assert dp.parse_dt("garbage") is None
    assert dp.parse_dt("") is None
    assert dp.parse_dt(None) is None


def test_format_dt_is_minute_precision():
    assert dp.format_dt(datetime(2026, 6, 19, 2, 5)) == "2026-06-19 02:05"


def test_month_weeks_sunday_first_and_blanks_are_zero():
    weeks = dp.month_weeks(2026, 6)  # 2026-06-01 是周一
    assert weeks[0] == [0, 1, 2, 3, 4, 5, 6]  # 周日空格=0，周一=1
    # 每周 7 列，非本月补 0，本月日子无遗漏。
    assert all(len(w) == 7 for w in weeks)
    flat = [d for w in weeks for d in w if d]
    assert flat == list(range(1, 31))  # 6 月 30 天
