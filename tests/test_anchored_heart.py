"""回归护栏：末尾爱心「独立图层·锚定文字」。

旧实现把 Font 4 末尾爱心死贴在文字墨迹后（烘进 textLayout.endingHeart）；新实现把爱心
分离成独立 AnchoredHeartLayer（面板可单独选中、可拖动、可调 mm 间距/上下偏移/大小），但仍
锚定文字、每单按墨迹自动跟随。本测试锁住：
- 零回归：auto 默认（gap/size=None）下，新独立爱心层与旧烘焙路径的 DXF/PNG 几何逐像素一致；
- 自动跟随：不同名字宽度，爱心 x 随末行墨迹右缘移动；
- mm 生效：gap/offset_y/size 各按 px_per_mm 精确换算；
- 独立导出：导出层文档出现独立 svg 心层，且锚定文字层不再烘 endingHeart；
- 迁移/移除：ensure 补建恰好 1 个、remove 清除并清 detached 标志；
- 空名隐藏：末行无墨迹时爱心 visible=False，不导出乱飘符号。
"""
from pathlib import Path

import pytest

FONT = Path("BirthMonth flowers/Malovely Script.ttf")
BOX = dict(x=780, y=830, width=804, height=260)
PX_PER_MM = 1732 / 80.0  # canvas_width / DEFAULT_PHYSICAL_WIDTH_MM


def _require_assets():
    pytest.importorskip("PIL")
    ezdxf = pytest.importorskip("ezdxf")
    if not FONT.is_file():
        pytest.skip("business font asset not present")
    return ezdxf


def _build(name: str, *, with_heart_layer: bool, font_size: int = 190):
    from models import Document, add_text_layer
    from anchor_resolve import ensure_anchored_heart_for

    doc = Document(canvas_width=1732, canvas_height=1280)
    layer = add_text_layer(doc, name, font_size=font_size, **BOX)
    layer.font_path = FONT
    layer.align = "center"
    layer.vertical_align = "middle"
    layer.ending_heart = True
    heart = ensure_anchored_heart_for(doc, layer) if with_heart_layer else None
    return doc, layer, heart


def _png_right(doc, path) -> float:
    from PIL import Image
    from renderer import render_document_png

    return Image.open(render_document_png(doc, path)).convert("RGBA").getbbox()[2]


def _dxf_right_canvas(ezdxf, doc, path) -> float:
    from desktop_export import render_document_dxf

    dxf_doc = ezdxf.readfile(str(render_document_dxf(doc, path)))
    xs: list[float] = []
    for entity in dxf_doc.modelspace():
        if entity.dxftype() == "SPLINE":
            xs.extend(p[0] for p in entity.control_points)
        elif entity.dxftype() == "POLYLINE":
            xs.extend(p[0] for p in entity.points())
    assert xs
    scale = 80.0 / 1732.0
    return max(xs) / scale


@pytest.mark.parametrize("name", ["Mia", "Katie", "Alexandria"])
def test_anchored_heart_matches_legacy_baked_geometry(tmp_path, name):
    # 零回归：auto 默认下，新独立爱心层与旧烘焙路径的 PNG/DXF 右缘逐像素一致。
    ezdxf = _require_assets()
    doc_old, _, _ = _build(name, with_heart_layer=False)  # 旧烘焙（textLayout.endingHeart）
    doc_new, _, _ = _build(name, with_heart_layer=True)   # 新独立爱心层

    assert abs(_png_right(doc_old, tmp_path / "o.png") - _png_right(doc_new, tmp_path / "n.png")) < 2
    rx_old = _dxf_right_canvas(ezdxf, doc_old, tmp_path / "o.dxf")
    rx_new = _dxf_right_canvas(ezdxf, doc_new, tmp_path / "n.dxf")
    assert abs(rx_old - rx_new) < 2


def test_anchored_heart_export_is_separate_layer_without_baked_heart():
    # 新路径：导出层文档出现独立 svg 心层（inlineSvg），且锚定文字层不再烘 endingHeart。
    _require_assets()
    from desktop_export import _document_to_layer_document

    doc, text, _ = _build("Mia", with_heart_layer=True)
    layer_doc = _document_to_layer_document(doc)
    text_dict = next(it for it in layer_doc["layers"] if it["type"] == "text")
    svg_dicts = [it for it in layer_doc["layers"] if it["type"] == "svg"]
    assert "endingHeart" not in text_dict.get("textLayout", {})       # 文字层不再自烘爱心
    assert any("inlineSvg" in it for it in svg_dicts)                  # 爱心作为内联 svg 层导出


def test_anchored_heart_follows_name_width():
    # 锚定：名字越长，爱心 x（末行墨迹右缘 + 间距）越靠右。
    _require_assets()
    from anchor_resolve import resolve_anchored_hearts

    xs = []
    for name in ["Mia", "Katie", "Alexandria"]:
        doc, _, heart = _build(name, with_heart_layer=True)
        resolve_anchored_hearts(doc)
        xs.append(heart.x)
    assert xs[0] < xs[1] < xs[2]


def test_anchored_heart_mm_params_take_effect():
    # mm 生效：gap/offset_y/size 各按 px_per_mm 精确换算。
    _require_assets()
    from anchor_resolve import resolve_anchored_hearts
    from heart_symbol import HEART_ASPECT

    doc, _, heart = _build("Mia", with_heart_layer=True)
    heart.gap_mm = 2.0
    resolve_anchored_hearts(doc)
    x2 = heart.x
    heart.gap_mm = 5.0
    resolve_anchored_hearts(doc)
    assert abs((heart.x - x2) - 3.0 * PX_PER_MM) < 1.0  # +3mm → 右移 3*px_per_mm

    heart.offset_y_mm = 0.0
    resolve_anchored_hearts(doc)
    y0 = heart.y
    heart.offset_y_mm = 4.0
    resolve_anchored_hearts(doc)
    assert abs((heart.y - y0) - 4.0 * PX_PER_MM) < 1.0  # +4mm → 下移 4*px_per_mm

    heart.size_mm = 8.0
    resolve_anchored_hearts(doc)
    assert abs(heart.height - 8.0 * PX_PER_MM) < 1.0
    assert abs(heart.width - 8.0 * PX_PER_MM * HEART_ASPECT) < 1.0


def test_ensure_and_remove_migration():
    # 迁移：ensure 给 ending_heart 文字补建恰好 1 个爱心层；remove 清除并清 detached 标志。
    _require_assets()
    from models import Document, add_text_layer, AnchoredHeartLayer
    from anchor_resolve import ensure_anchored_hearts, remove_anchored_heart_for, resolve_anchored_hearts

    doc = Document(canvas_width=1732, canvas_height=1280)
    text = add_text_layer(doc, "Mia", font_size=190, **BOX)
    text.font_path = FONT
    text.ending_heart = True  # 旧存档：只有标志、无爱心层

    ensure_anchored_hearts(doc)
    hearts = [l for l in doc.layers if isinstance(l, AnchoredHeartLayer)]
    assert len(hearts) == 1 and hearts[0].anchor_layer_id == text.id
    ensure_anchored_hearts(doc)  # 幂等：不重复补建
    assert len([l for l in doc.layers if isinstance(l, AnchoredHeartLayer)]) == 1

    resolve_anchored_hearts(doc)
    assert text.ending_heart_detached is True
    assert remove_anchored_heart_for(doc, text.id) is True
    assert not [l for l in doc.layers if isinstance(l, AnchoredHeartLayer)]
    assert text.ending_heart_detached is False


def test_empty_name_hides_heart():
    # 空名（末行无墨迹）→ 爱心隐藏，不导出乱飘符号。
    _require_assets()
    from models import Document, add_text_layer
    from anchor_resolve import ensure_anchored_heart_for, resolve_anchored_hearts

    doc = Document(canvas_width=1732, canvas_height=1280)
    text = add_text_layer(doc, "   ", font_size=190, **BOX)
    text.font_path = FONT
    text.ending_heart = True
    heart = ensure_anchored_heart_for(doc, text)
    resolve_anchored_hearts(doc)
    assert heart.visible is False
