"""Font 4 末尾独立实心爱心——几何唯一真源。

源文件 assets/symbols/heart.svg（用户手绘实心爱心）。其原始 path 全是 SVG 圆弧命令
（`a`），而本项目矢量端只认 M/L/H/V/Q/C/Z（见 services/api/app/domain/exports/dxf.py
的 _parse_path_objects），故由 tmp_out/gen_heart.py 用 fontTools 一次性把圆弧归一化成
全贝塞尔（仅 M/C/Q/Z）、零基定位后固化成下方常量。预览(text_renderer)与导出
(desktop_export→svg/dxf)都从这里取同一份几何，保证“算一次/预览==导出”。
"""
from __future__ import annotations

import re

# 归一化后的爱心轮廓：绝对坐标、仅 M/C/Q/Z、左上角对齐到 (0,0)。
# 占据约 [0, HEART_VIEW_W] x [0, HEART_VIEW_H] 的盒子。改图请重跑 tmp_out/gen_heart.py。
HEART_PATH_D = (
    "M18.874,13.402C19.397,12.486 19.978,11.604 20.614,10.762C22.047,8.96 23.601,7.256 "
    "25.264,5.662C27.01,4.211 29.262,3.513 31.524,3.722C35.524,3.932 38.894,7.462 "
    "39.314,11.792C39.592,13.952 39.168,16.143 38.104,18.042C36.981,20.066 35.639,21.961 "
    "34.104,23.692C28.186,29.911 20.929,34.699 12.884,37.692C12.524,37.832 12.134,37.912 "
    "11.694,38.042C11.444,37.723 11.214,37.389 11.004,37.042Q6.884,28.532 2.764,20.042"
    "C1.301,17.016 0.397,13.75 0.094,10.402C-0.031,9.296 -0.031,8.179 0.094,7.072"
    "C0.834,1.402 4.924,-1.168 10.424,0.502C12.78,1.119 14.745,2.744 15.794,4.942"
    "C16.404,6.242 17.004,7.552 17.494,8.892C17.984,10.232 18.394,11.582 18.874,13.402Z"
)

HEART_VIEW_W = 39.397
HEART_VIEW_H = 38.042
HEART_ASPECT = HEART_VIEW_W / HEART_VIEW_H  # 宽/高 ≈ 1.036

# 命令 -> 坐标对数量（本爱心只用到这几个；H/V/Z 不含坐标对，故安全）
_CMD_PAIRS = {"M": 1, "L": 1, "Q": 2, "C": 3, "Z": 0, "H": 0, "V": 0}
_TOKEN_RE = re.compile(r"[MLQCZHVmlqczhv]|-?\d*\.?\d+(?:[eE]-?\d+)?")


def _fmt(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def heart_path_d_transformed(x: float, y: float, scale: float) -> str:
    """把 HEART_PATH_D 先等比缩放再平移，返回新的绝对坐标 d。

    坐标全是绝对命令，故对每个 (px, py) 统一施加 (px*scale + x, py*scale + y)。
    用于 SVG 的 <path d>（box 本地坐标）和烘进 schema 的 pathData。
    """
    tokens = _TOKEN_RE.findall(HEART_PATH_D)
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        # 正则只会吐出“命令字母”或“数字”；数字绝不以字母开头，故首字符即可区分。
        if not tok[0].isalpha():
            i += 1
            continue
        cmd = tok.upper()
        out.append(cmd)
        i += 1
        coords: list[str] = []
        for _ in range(_CMD_PAIRS.get(cmd, 0)):
            px = float(tokens[i])
            py = float(tokens[i + 1])
            coords.append(f"{_fmt(px * scale + x)},{_fmt(py * scale + y)}")
            i += 2
        if coords:
            out.append(" ".join(coords))
    return "".join(out)


def heart_svg_markup(fill: str = "#111111") -> str:
    """独立 SVG 文本，供 cairosvg 在预览端栅格化（box 自身 = 爱心紧致盒）。"""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {_fmt(HEART_VIEW_W)} {_fmt(HEART_VIEW_H)}">'
        f'<path d="{HEART_PATH_D}" fill="{fill}"/></svg>'
    )
