"""订单解析素材库对接单测（见 ExecPlan Task 3）。用临时库，不依赖真实资产/网络。"""

from __future__ import annotations

from pathlib import Path

import pytest

from material_library import MaterialLibrary
from models import AIParseConfig, ParseResult
from order_catalog import (
    LibraryBundle,
    build_order_remark_schema,
    build_prompt_catalog,
    enrich_parse_result,
    parse_catalog_payload,
    parse_order_remark_with_gpt_catalog,
)
from parse_pipeline import parse_order_remark_auto

_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0h10v10H0z"/></svg>'


@pytest.fixture
def bundle(tmp_path: Path) -> LibraryBundle:
    img = tmp_path / "flowers"
    img.mkdir()
    (img / "March_Daffodil.svg").write_text(_SVG, encoding="utf-8")
    (img / "March_CherryBlossom.svg").write_text(_SVG, encoding="utf-8")
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    (fonts / "MalovelyScript.ttf").write_bytes(b"fake-font")
    (fonts / "AdoraBella.ttf").write_bytes(b"fake-font")
    image_lib = MaterialLibrary.from_folder(img, library_id="birth-flowers", kind="image")
    font_lib = MaterialLibrary.from_folder(fonts, library_id="scripts", kind="font")
    return LibraryBundle(image_libraries=(image_lib,), font_libraries=(font_lib,))


def test_bundle_keys(bundle: LibraryBundle):
    assert "daffodil" in bundle.image_keys()  # key 取纯花名（已去月份）
    assert bundle.font_keys()


def test_resolve_material_by_key_and_tags(bundle: LibraryBundle):
    lib_id, entry = bundle.resolve_material("daffodil")
    assert lib_id == "birth-flowers"
    assert entry.tags.get("month") == 3  # month/flower 仅作上下文标签保留
    found = bundle.resolve_material_by_tags(month=3, flower=2)
    assert found is not None and "cherry" in found[1].key


def test_resolve_font_by_tags(bundle: LibraryBundle):
    found = bundle.resolve_font_by_tags(index=1)
    assert found is not None
    assert found[1].tags.get("index") == 1


def test_schema_dynamic_enum(bundle: LibraryBundle):
    schema = build_order_remark_schema(bundle.image_keys(), bundle.font_keys())
    enum = schema["properties"]["material_key"]["enum"]
    assert "daffodil" in enum
    assert None in enum
    assert schema["required"] == ["text", "material_key", "font_key", "warnings", "confidence"]


def test_prompt_catalog_includes_items(bundle: LibraryBundle):
    catalog = build_prompt_catalog(bundle)
    keys = [item["key"] for lib in catalog["image_libraries"] for item in lib["items"]]
    assert "daffodil" in keys


def test_parse_catalog_payload_valid_key_enriches(bundle: LibraryBundle):
    result = parse_catalog_payload(
        {
            "text": "Vivian",
            "material_key": "daffodil",
            "font_key": "malovelyscript",
            "warnings": [],
            "confidence": 0.95,
        },
        bundle,
    )
    assert result.text == "Vivian"
    assert result.material_key == "daffodil"
    assert result.material_library_id == "birth-flowers"
    assert result.selected_flower_asset and result.selected_flower_asset.endswith("March_Daffodil.svg")
    assert result.month == 3 and result.flower == 1  # 命中 key 后从标签回填 month/flower
    assert result.font_key == "malovelyscript"
    assert result.selected_font_asset


def test_parse_catalog_payload_rejects_hallucinated_key(bundle: LibraryBundle):
    result = parse_catalog_payload(
        {"text": "Vivian", "material_key": "zzz-nonexistent", "font_key": None, "warnings": [], "confidence": 0.5},
        bundle,
    )
    assert result.material_key == ""
    assert any("不在素材库目录" in w for w in result.warnings)


def test_enrich_matches_by_flower_name_not_month(bundle: LibraryBundle):
    # 月份+序号不再选素材：只有 month/flower 时不落素材（字体仍按 index 命中）。
    month_only = enrich_parse_result(ParseResult(text="Mona", month=3, flower=1, font=1), bundle)
    assert month_only.material_key == ""
    assert month_only.selected_flower_asset is None
    assert month_only.font_key  # font=1 → 字体标签 index 1 命中

    # 按花名匹配：flower_name 命中具体素材。
    by_name = enrich_parse_result(ParseResult(text="Mona", flower_name="Daffodil", font=1), bundle)
    assert by_name.material_key == "daffodil"
    assert by_name.selected_flower_asset


def test_enrich_is_idempotent(bundle: LibraryBundle):
    once = enrich_parse_result(ParseResult(text="Mona", flower_name="Daffodil", font=1), bundle)
    twice = enrich_parse_result(once, bundle)
    assert once.material_key == twice.material_key
    assert once.warnings == twice.warnings
    assert once.selected_flower_asset == twice.selected_flower_asset


def test_gpt_catalog_call_injects_catalog_and_enriches(bundle: LibraryBundle):
    calls = []

    def fake_http_post(url, payload, headers, timeout):
        calls.append((url, payload))
        return {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"text":"Vivian","material_key":"daffodil","font_key":"malovelyscript","warnings":[],"confidence":0.94}',
                        }
                    ]
                }
            ]
        }

    result = parse_order_remark_with_gpt_catalog(
        "for Vivian, March daffodil", bundle, api_key="sk-test", http_post=fake_http_post
    )
    assert result.material_key == "daffodil"
    assert result.selected_flower_asset
    system_content = calls[0][1]["input"][0]["content"]
    assert "daffodil" in system_content  # 目录注入了 prompt
    enum = calls[0][1]["text"]["format"]["schema"]["properties"]["material_key"]["enum"]
    assert "daffodil" in enum  # 动态枚举进了 schema


def test_pipeline_enriches_when_bundle_passed(bundle: LibraryBundle):
    def local(_remark):
        return ParseResult(text="Mona", month=3, flower=1, flower_name="Daffodil", font=1, confidence=1.0)

    result = parse_order_remark_auto(
        "note", gpt_parser=local, bundle=bundle
    )
    assert result.material_key == "daffodil"
    assert result.selected_flower_asset


def test_pipeline_without_bundle_is_unchanged():
    def local(_remark):
        return ParseResult(text="Mona", month=3, flower=1, font=1, confidence=1.0)

    result = parse_order_remark_auto(
        "note", gpt_parser=local
    )
    assert result.material_key == ""  # 未传 bundle → 不富化，行为不变


def test_library_bundle_from_dirs(tmp_path: Path):
    img = tmp_path / "flowers"
    img.mkdir()
    (img / "March_Daffodil.svg").write_text(_SVG, encoding="utf-8")
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    (fonts / "MalovelyScript.ttf").write_bytes(b"fake-font")
    bundle = LibraryBundle.from_dirs([img], [fonts])
    assert "daffodil" in bundle.image_keys()
    assert bundle.font_keys()
