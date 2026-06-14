"""ImageLayer / TextLayer 新增素材库字段 + 迁移单测（见 ExecPlan Task 1 Step 3）。"""

from __future__ import annotations

from pathlib import Path

from models import Document, ImageLayer, TextLayer, add_image_layer, add_text_layer
from production import ProductionParams


def test_image_layer_new_fields_default_empty():
    layer = ImageLayer()
    assert layer.library_id == ""
    assert layer.material_key == ""
    assert layer.production is None


def test_image_layer_migrates_material_key_from_material_id():
    # 旧素材图层只有 material_id → 迁移出 material_key
    layer = ImageLayer(material_id="march-daffodil")
    assert layer.material_key == "march-daffodil"


def test_image_layer_keeps_explicit_material_key():
    layer = ImageLayer(material_id="x", material_key="explicit")
    assert layer.material_key == "explicit"


def test_image_layer_production_dict_coerced():
    layer = ImageLayer(production={"width": 500, "x": 10})
    assert isinstance(layer.production, ProductionParams)
    assert layer.production.width == 500
    assert layer.production.x == 10


def test_text_layer_new_fields_and_font_key_migration():
    layer = TextLayer(font_path=Path("Malovely Script.otf"))
    assert layer.font_key == "Malovely Script"  # best-effort 从文件名迁移
    assert layer.font_library_id == ""
    assert layer.production is None


def test_text_layer_production_dict_coerced():
    layer = TextLayer(production={"font_size": 88})
    assert isinstance(layer.production, ProductionParams)
    assert layer.production.font_size == 88


def test_add_image_layer_sets_library_fields():
    doc = Document()
    layer = add_image_layer(
        doc, "x.svg", library_id="birth-flowers", material_key="march-daffodil", production=ProductionParams(width=900)
    )
    assert layer.library_id == "birth-flowers"
    assert layer.material_key == "march-daffodil"
    assert layer.production is not None and layer.production.width == 900


def test_add_text_layer_sets_font_library_fields():
    doc = Document()
    layer = add_text_layer(doc, "Hi", font_library_id="scripts", font_key="malovelyscript")
    assert layer.font_library_id == "scripts"
    assert layer.font_key == "malovelyscript"
