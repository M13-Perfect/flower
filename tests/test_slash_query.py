"""光标锚定的斜杠词解析：背景提示词区 / 引用弹窗的检测核心。"""

from prompt_references import slash_query_at_cursor


def _no_chip(_col: int) -> bool:
    return False


def _chip_cols(*cols: int):
    s = set(cols)
    return lambda col: col in s


def test_slash_at_word_start():
    assert slash_query_at_cursor("/na", _no_chip) == "na"


def test_slash_after_space():
    assert slash_query_at_cursor("foo /na", _no_chip) == "na"


def test_bare_slash_shows_all():
    assert slash_query_at_cursor("/", _no_chip) == ""


def test_normal_text_with_slash_not_triggered():
    # and/or、2cm/3cm 是正文，不是命令
    assert slash_query_at_cursor("2cm/3cm", _no_chip) is None
    assert slash_query_at_cursor("and/or", _no_chip) is None


def test_no_slash():
    assert slash_query_at_cursor("hello", _no_chip) is None


def test_slash_right_after_chip():
    # chip 文本 "/月份"(列0-2) 后紧跟新 "/"(列3)：应识别新命令、show all，不被 chip 吞掉
    assert slash_query_at_cursor("/月份/", _chip_cols(0, 1, 2)) == ""


def test_query_right_after_chip():
    # "/月份" 后接 "/abc"：取 chip 边界之后的词，不含 chip 文本
    assert slash_query_at_cursor("/月份/abc", _chip_cols(0, 1, 2)) == "abc"


def test_chip_text_alone_not_a_command():
    # 光标停在 chip 文本内部/末尾，不应弹命令窗
    assert slash_query_at_cursor("/月份", _chip_cols(0, 1, 2)) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
