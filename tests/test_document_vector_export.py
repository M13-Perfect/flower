"""按钮路径回归:桌面 Document 经 desktop_export 走真实 export_dxf/export_svg,
产物必须是 CAD 可编辑的纯矢量(R2018+SPLINE / 文字转路径)。"""
from __future__ import annotations

import ezdxf
import pytest

from app.domain.exports.dxf import _project_root
from desktop_export import render_document_dxf, render_document_vector_svg
from models import Document, add_image_layer, add_text_layer


FLOWER_SVG = (
    '<svg viewBox="0 0 100 100"><path d="M10 10 C30 0 70 0 90 10 '
    'C100 30 100 70 90 90 C70 100 30 100 10 90 C0 70 0 30 10 10 Z"/></svg>'
)


def _build_document(tmp_path) -> Document:
    svg_file = tmp_path / "flower.svg"
    svg_file.write_text(FLOWER_SVG, encoding="utf-8")
    document = Document(canvas_width=1000, canvas_height=1000)
    add_image_layer(document, svg_file, x=100, y=100, width=600, height=600)
    font_path = _project_root() / "Birthmonth_font.ttf"
    add_text_layer(
        document,
        "Mia",
        font_path=font_path,
        x=200,
        y=760,
        width=600,
        height=200,
        font_size=180,
    )
    return document


def test_render_document_dxf_is_editable_r2018_spline(tmp_path) -> None:
    output = render_document_dxf(_build_document(tmp_path), tmp_path / "out.dxf")

    drawing = ezdxf.readfile(str(output))
    assert drawing.dxfversion == "AC1032"  # R2018
    assert drawing.header["$INSUNITS"] == 4  # mm
    types = {entity.dxftype() for entity in drawing.modelspace()}
    assert "SPLINE" in types  # 花朵/字形曲线 → 可编辑 SPLINE
    assert "LWPOLYLINE" not in types  # 不再产出 EzCad 改不动的 LWPOLYLINE
    assert "TEXT" not in types  # 文字已转路径
    layers = {entity.dxf.layer for entity in drawing.modelspace()}
    assert len(layers) == 1  # 花与字同在一个内容层
    assert drawing.layers.get(next(iter(layers))).dxf.color == 7


def test_render_document_dxf_scales_to_physical_width_mm(tmp_path) -> None:
    output = render_document_dxf(
        _build_document(tmp_path), tmp_path / "out.dxf", physical_width_mm=80
    )
    drawing = ezdxf.readfile(str(output))
    from ezdxf import bbox as ezbbox

    extents = ezbbox.extents(drawing.modelspace())
    # 1000px 画布映射 80mm,墨迹必须落在画布内(留白正常)。
    assert -1 <= extents.extmin.x and extents.extmax.x <= 81
    assert extents.size.x <= 80.5


def test_physical_width_controls_dxf_scale(tmp_path) -> None:
    """布局设置里的输出宽度(mm)必须真正控制 DXF 尺寸,而非写死 80mm。"""
    from ezdxf import bbox as ezbbox

    out80 = render_document_dxf(_build_document(tmp_path), tmp_path / "a.dxf", physical_width_mm=80)
    out120 = render_document_dxf(_build_document(tmp_path), tmp_path / "b.dxf", physical_width_mm=120)
    width80 = ezbbox.extents(ezdxf.readfile(str(out80)).modelspace()).size.x
    width120 = ezbbox.extents(ezdxf.readfile(str(out120)).modelspace()).size.x
    assert width120 == pytest.approx(width80 * 120 / 80, rel=0.02)


def test_physical_width_none_falls_back_to_default(tmp_path) -> None:
    out = render_document_dxf(_build_document(tmp_path), tmp_path / "c.dxf", physical_width_mm=None)
    from ezdxf import bbox as ezbbox

    extents = ezbbox.extents(ezdxf.readfile(str(out)).modelspace())
    assert extents.extmax.x <= 81  # 默认 80mm 画布内


def test_render_document_vector_svg_is_pure_vector(tmp_path) -> None:
    output = render_document_vector_svg(_build_document(tmp_path), tmp_path / "out.svg")

    text = output.read_text(encoding="utf-8")
    assert "<text" not in text  # 文字转路径,无 <text>
    assert "<image" not in text  # 素材内联矢量,无位图 <image>
    assert "<path" in text


def test_render_document_dxf_rejects_empty_document(tmp_path) -> None:
    import pytest

    with pytest.raises(ValueError):
        render_document_dxf(Document(canvas_width=800, canvas_height=600), tmp_path / "out.dxf")


def test_export_layer_errors_surface_as_value_error(tmp_path) -> None:
    """导出层抛 DomainError(如无几何)时,桥接需转成 ValueError,UI 才能友好提示。"""
    import pytest

    document = Document(canvas_width=800, canvas_height=600)
    # 只有一个空文本图层 → 无任何几何 → export_dxf 抛 DXF_NO_GEOMETRY(DomainError)。
    add_text_layer(document, "", x=10, y=10, width=200, height=80, font_size=40)
    with pytest.raises(ValueError):
        render_document_dxf(document, tmp_path / "out.dxf")
