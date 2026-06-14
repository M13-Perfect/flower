"""回归护栏：文字“算一次、等比、预览==导出”。

等比改造（text_layout.fit_text_box 统一适配 + 各端消费同一结果）后，名字在：
- PNG 预览（TextRenderer 墨迹居中贴框，不再非等比拉伸）
- 矢量 DXF（消费桌面烘进 textLayout 的每行基线锚点）
两条路径的字号与居中必须一致。本测试锁住：不拉伸（四周留白）、预览==导出（几何中心一致）、
lines↔origins 一一对应、长名等比缩字号、字间距下仍居中。
"""
from pathlib import Path

import pytest

FONT = Path("BirthMonth flowers/Malovely Script.ttf")
BOX = dict(x=780, y=830, width=804, height=260)


def _require_assets():
    pytest.importorskip("PIL")
    ezdxf = pytest.importorskip("ezdxf")
    if not FONT.is_file():
        pytest.skip("business font asset not present")
    return ezdxf


def _build_doc(name: str, *, font_size: int = 190, letter_spacing: float = 0.0):
    from models import Document, add_text_layer

    doc = Document(canvas_width=1732, canvas_height=1280)
    layer = add_text_layer(doc, name, font_size=font_size, **BOX)
    layer.font_path = FONT
    layer.align = "center"
    layer.vertical_align = "middle"
    layer.letter_spacing = letter_spacing
    layer.tracking = letter_spacing
    return doc


def _png_ink_center(doc, tmp_path):
    from PIL import Image

    from renderer import render_document_png

    ink = Image.open(render_document_png(doc, tmp_path / "o.png")).convert("RGBA").getbbox()
    return ink, ((ink[0] + ink[2]) / 2, (ink[1] + ink[3]) / 2)


def _dxf_geom_center(ezdxf, doc, tmp_path):
    from desktop_export import render_document_dxf

    dxf_doc = ezdxf.readfile(str(render_document_dxf(doc, tmp_path / "o.dxf")))
    xs: list[float] = []
    ys: list[float] = []
    for entity in dxf_doc.modelspace():
        if entity.dxftype() == "SPLINE":
            for point in entity.control_points:
                xs.append(point[0])
                ys.append(point[1])
    assert xs and ys
    scale = 80.0 / 1732.0  # DEFAULT_PHYSICAL_WIDTH_MM / canvas_width
    return (((min(xs) + max(xs)) / 2) / scale, 1280 - ((min(ys) + max(ys)) / 2) / scale)


@pytest.mark.parametrize("name", ["Harlow", "Mia"])
def test_short_name_preview_equals_vector_and_not_stretched(tmp_path, name):
    ezdxf = _require_assets()
    doc = _build_doc(name)

    from desktop_export import _document_to_layer_document

    text_dict = next(item for item in _document_to_layer_document(doc)["layers"] if item["type"] == "text")
    tl = text_dict["textLayout"]
    assert tl["lines"] == [name]
    assert len(tl["origins"]) == len(tl["lines"])  # lines↔origins 一一对应
    assert 0 < text_dict["style"]["fontSize"] <= 190

    png_ink, (png_cx, png_cy) = _png_ink_center(doc, tmp_path)
    bx0, by0, bx1, by1 = BOX["x"], BOX["y"], BOX["x"] + BOX["width"], BOX["y"] + BOX["height"]
    # 短名不拉伸：四周留白。
    assert png_ink[0] > bx0 + 5 and png_ink[2] < bx1 - 5
    assert png_ink[1] > by0 + 5 and png_ink[3] < by1 - 5
    # 居中（短名中心 == 框中心）。
    assert abs(png_cx - (bx0 + bx1) / 2) < 4
    assert abs(png_cy - (by0 + by1) / 2) < 4

    dxf_cx, dxf_cy = _dxf_geom_center(ezdxf, doc, tmp_path)
    # 预览==导出：跨格式几何中心一致（残差仅来自栅格 vs 轮廓测量）。
    assert abs(dxf_cx - png_cx) < 10
    assert abs(dxf_cy - png_cy) < 10


def test_long_name_shrinks_below_cap_and_stays_consistent(tmp_path):
    ezdxf = _require_assets()
    doc = _build_doc("Alexandria Catherine Montgomery", font_size=190)

    from desktop_export import _document_to_layer_document

    text_dict = next(item for item in _document_to_layer_document(doc)["layers"] if item["type"] == "text")
    # 太长 → 等比缩到框宽，字号低于上限。
    assert text_dict["style"]["fontSize"] < 190

    _, (png_cx, png_cy) = _png_ink_center(doc, tmp_path)
    dxf_cx, dxf_cy = _dxf_geom_center(ezdxf, doc, tmp_path)
    assert abs(dxf_cx - png_cx) < 12
    assert abs(dxf_cy - png_cy) < 12


def test_letter_spacing_name_stays_centered_in_both(tmp_path):
    ezdxf = _require_assets()
    doc = _build_doc("Emma", font_size=160, letter_spacing=20.0)

    _, (png_cx, png_cy) = _png_ink_center(doc, tmp_path)
    bx0, bx1 = BOX["x"], BOX["x"] + BOX["width"]
    assert abs(png_cx - (bx0 + bx1) / 2) < 6  # 预览仍居中
    dxf_cx, dxf_cy = _dxf_geom_center(ezdxf, doc, tmp_path)
    # 字间距补偿后矢量也居中：与预览一致（若不补偿会右偏约 (n-1)*spacing/2 ≈ 30px）。
    assert abs(dxf_cx - png_cx) < 12
