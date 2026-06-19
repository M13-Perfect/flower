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


def test_long_name_auto_wraps_and_is_bigger_than_single_line():
    # 图1 升级：长名自动断成 2 行，字号比强制单行更大，仍装得下框。
    _require_assets()
    from text_layout import fit_text_box, _fit_name_font_size

    name = "Melanie Helen Margaret"
    w, h = 520, 420  # 偏窄偏高：单行明显受宽度压制，断行收益大
    fit = fit_text_box(name, w, h, FONT, personalization_type="name")
    single_size = _fit_name_font_size(name, w, h, FONT)
    assert len(fit.lines) == 2
    assert fit.font_size > single_size
    assert fit.did_fit


def test_short_single_name_stays_one_line():
    # 短名/单词不无谓换行。
    _require_assets()
    from text_layout import fit_text_box

    fit = fit_text_box("Emma", 520, 420, FONT, personalization_type="name")
    assert len(fit.lines) == 1


def _text_layer(doc):
    from models import TextLayer

    return next(layer for layer in doc.layers if isinstance(layer, TextLayer))


def _png_ink_bbox(doc, path):
    from PIL import Image

    from renderer import render_document_png

    return Image.open(render_document_png(doc, path)).convert("RGBA").getbbox()


def _dxf_right_x_canvas(ezdxf, doc, path):
    from desktop_export import render_document_dxf

    dxf_doc = ezdxf.readfile(str(render_document_dxf(doc, path)))
    xs: list[float] = []
    for entity in dxf_doc.modelspace():
        if entity.dxftype() == "SPLINE":
            xs.extend(p[0] for p in entity.control_points)
        elif entity.dxftype() == "POLYLINE":
            xs.extend(p[0] for p in entity.points())
    assert xs
    scale = 80.0 / 1732.0  # DEFAULT_PHYSICAL_WIDTH_MM / canvas_width
    return max(xs) / scale  # 最右 x，换回 canvas 像素


def test_ending_heart_right_edge_matches_preview_and_vector(tmp_path):
    # 末尾爱心：预览(PNG)与导出(DXF)都比无爱心向右扩，且“最右缘”跨端一致（爱心落点同一）。
    ezdxf = _require_assets()
    doc_no = _build_doc("Mia", font_size=190)
    doc_yes = _build_doc("Mia", font_size=190)
    _text_layer(doc_yes).ending_heart = True

    png_no = _png_ink_bbox(doc_no, tmp_path / "no.png")
    png_yes = _png_ink_bbox(doc_yes, tmp_path / "yes.png")
    assert png_yes[2] > png_no[2] + 10  # 预览右扩（出现爱心）

    rx_no = _dxf_right_x_canvas(ezdxf, doc_no, tmp_path / "no.dxf")
    rx_yes = _dxf_right_x_canvas(ezdxf, doc_yes, tmp_path / "yes.dxf")
    assert rx_yes > rx_no + 10  # 矢量右扩（出现爱心）

    # 预览爱心右缘 ≈ 矢量爱心右缘（残差仅来自栅格 vs 轮廓测量）。
    assert abs(png_yes[2] - rx_yes) < 16
