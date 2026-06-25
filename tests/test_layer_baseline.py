"""Packet 0 字节稳定门禁（Layer System v2）。

红线：**没有新字段的旧数据，导出字节必须不变**。后续 Packet（provider 化、序列化、
auto-layout 等）只要不动「旧数据」导出路径，本测试就必须保持通过；一旦某次重构让现有
生产形态 Document 的导出 dict 结构或导出字节发生漂移，本门禁立即失败。

构造一份当前生产形态 Document（1 个真实花朵 SVG ImageLayer + 1 个真实字体 TextLayer），
全程内存构造（不读盘文档），并把 Layer.id 固定为确定值（默认是 uuid4，见 models._new_layer_id），
消除唯一的对象级非确定源。在此基础上锁两件事：

1. **导出字节内进程确定性**：同一 fixture 连续导出两次，规整掉「已知且与几何无关」的
   元数据非确定位后，DXF / 矢量 SVG 必须逐字节一致。
2. **导出 dict 结构金标**：`desktop_export._document_to_layer_document` 的输出（把超大
   `inlineSvg` 折成 长度+sha256 哨兵以保持金标小）对照 `tests/fixtures/` 下的金标 JSON；
   缺失时首跑生成→skip，再跑逐字段比对。

已知且**有意**规整掉的非确定位（均为 ezdxf / 导出器元数据，非绘图几何）：
- DXF：`$FINGERPRINTGUID` / `$VERSIONGUID` 的 GUID 值，以及 `CREATED_BY_EZDXF` /
  `WRITTEN_BY_EZDXF` 的 ``<ver> @ <ISO 时间戳>`` 行（ezdxf 每次写盘新生成）。
- SVG：`<metadata>` 内嵌的 ``"exportedAt": "<ISO 时间戳>"``
  （见 services/api 导出器；desktop_export 传入的 metadata 不含它，由导出器注入）。

不依赖 Tk display：纯 model + export，无任何 UI／Tk root。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from app.domain.exports.dxf import _project_root
from desktop_export import (
    _document_to_layer_document,
    render_document_dxf,
    render_document_vector_svg,
)
from models import Document, add_image_layer, add_text_layer

FIX = Path(__file__).parent / "fixtures"
DOC_BASELINE = FIX / "layer_baseline_doc.json"

# 真实素材：必须是真实存在的纯矢量 SVG 花 + 真实字体，否则 desktop_export 会抛 ValueError。
_FLOWER_SVG = _project_root() / "BirthMonth flowers" / "CherryMarch.svg"
_FONT = _project_root() / "Birthmonth_font.ttf"


def _build_document() -> Document:
    """生产形态 Document：1 image + 1 text，全程内存构造，Layer.id 固定为确定值。"""
    document = Document(canvas_width=1732, canvas_height=1280)
    image = add_image_layer(document, _FLOWER_SVG, x=100, y=100, width=600, height=600)
    text = add_text_layer(
        document, "Mia", font_path=_FONT, x=200, y=900, width=600, height=200, font_size=180
    )
    # Layer.id 默认 uuid4（models._new_layer_id），是唯一的对象级非确定源；固定掉它。
    image.id = "baseline-image"
    text.id = "baseline-text"
    return document


# --- DXF 已知非确定元数据规整（GUID + ezdxf 时间戳，非绘图几何） ---
_DXF_GUID = re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}")
_DXF_EZDXF_STAMP = re.compile(r"@ \d{4}-\d{2}-\d{2}T[\d:.+\-]+")
# --- SVG 已知非确定元数据规整（导出器注入的 exportedAt 时间戳） ---
_SVG_EXPORTED_AT = re.compile(r'"exportedAt":\s*"[^"]*"')


def _normalize_dxf(raw: bytes) -> bytes:
    text = raw.decode("utf-8", errors="surrogateescape")
    text = _DXF_GUID.sub("{GUID}", text)
    text = _DXF_EZDXF_STAMP.sub("@ TIMESTAMP", text)
    return text.encode("utf-8", errors="surrogateescape")


def _normalize_svg(text: str) -> str:
    return _SVG_EXPORTED_AT.sub('"exportedAt": "TIMESTAMP"', text)


def test_dxf_export_is_byte_stable_in_process(tmp_path):
    """红线：同一旧数据 Document 连续两次导出 DXF，规整元数据后逐字节一致。"""
    a = render_document_dxf(_build_document(), tmp_path / "a.dxf", physical_width_mm=80)
    b = render_document_dxf(_build_document(), tmp_path / "b.dxf", physical_width_mm=80)
    assert _normalize_dxf(a.read_bytes()) == _normalize_dxf(b.read_bytes())


def test_vector_svg_export_is_byte_stable_in_process(tmp_path):
    """红线：同一旧数据 Document 连续两次导出矢量 SVG，规整 exportedAt 后逐字节一致。"""
    a = render_document_vector_svg(_build_document(), tmp_path / "a.svg").read_text(encoding="utf-8")
    b = render_document_vector_svg(_build_document(), tmp_path / "b.svg").read_text(encoding="utf-8")
    assert _normalize_svg(a) == _normalize_svg(b)


def _structural_layer_document() -> dict:
    """导出 dict，但把超大 inlineSvg 折成 长度+sha 哨兵，金标得以保持小而稳定。"""
    doc = _document_to_layer_document(_build_document())
    for layer in doc["layers"]:
        inline = layer.get("inlineSvg")
        if inline is not None:
            digest = hashlib.sha256(inline.encode("utf-8")).hexdigest()
            layer["inlineSvg"] = f"<sha256:{digest} len:{len(inline)}>"
    return doc


def test_layer_document_structure_golden_lock():
    """导出 dict 结构金标：生产形态 Document → _document_to_layer_document 逐字段锁定。

    缺基线时首跑生成→skip，再跑逐字段比对（与 test_dxf_golden_lock 同一惯例）。
    """
    structural = _structural_layer_document()
    if not DOC_BASELINE.exists():
        FIX.mkdir(parents=True, exist_ok=True)
        DOC_BASELINE.write_text(
            json.dumps(structural, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        pytest.skip(f"baseline generated at {DOC_BASELINE}; re-run to lock")
    baseline = json.loads(DOC_BASELINE.read_text(encoding="utf-8"))
    assert structural == baseline, "导出 dict 结构相对基线漂移（旧数据导出必须不变）"
