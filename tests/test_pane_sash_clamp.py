"""_clamp_sashes 自检：还原分隔条位置时，三列都不得低于 minsize，且两条 sash 不交叉。"""
from ui_app import _clamp_sashes, PRODUCT_RAIL_COLLAPSED_WIDTH

MIN_CENTER, MIN_FUNC = 360, 300


def test_extreme_fractions_still_respect_minsizes():
    total = 1120
    x0, x1 = _clamp_sashes((0.001, 0.999), total)  # 越界到几乎贴边
    assert x0 >= PRODUCT_RAIL_COLLAPSED_WIDTH       # 左列 ≥ 产品列收起宽
    assert x1 - x0 >= MIN_CENTER                    # 中列 ≥ minsize
    assert total - x1 >= MIN_FUNC                   # 右列 ≥ minsize
    assert x0 < x1                                  # 顺序正确


def test_reasonable_fractions_preserved():
    total = 1200
    x0, x1 = _clamp_sashes((0.1, 0.7), total)       # 0.1/0.7 三列都够 → 原样保留
    assert (x0, x1) == (int(0.1 * total), int(0.7 * total))


if __name__ == "__main__":  # ponytail: 无框架也能直接 python 这个文件自检
    test_extreme_fractions_still_respect_minsizes()
    test_reasonable_fractions_preserved()
    print("ok")
