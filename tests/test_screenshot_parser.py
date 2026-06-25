"""订单截图视觉解析单测；离线 fake http_post，不依赖网络/真实模型。"""

from __future__ import annotations

from pathlib import Path

import pytest

from material_library import MaterialLibrary
from order_catalog import LibraryBundle
from screenshot_parser import _image_data_url, parse_order_screenshot_with_gpt

_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0h10v10H0z"/></svg>'


def _bundle(tmp_path: Path) -> LibraryBundle:
    img = tmp_path / "flowers"
    img.mkdir()
    # 零配置命名：key = 文件名 slug（Daffodil → "daffodil"），不再识别月份前缀。
    (img / "Daffodil.svg").write_text(_SVG, encoding="utf-8")
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    (fonts / "MalovelyScript.ttf").write_bytes(b"fake-font")
    return LibraryBundle(
        image_libraries=(MaterialLibrary.from_folder(img, library_id="birth-flowers", kind="image"),),
        font_libraries=(MaterialLibrary.from_folder(fonts, library_id="scripts", kind="font"),),
    )


def _legacy_response(_url, _payload, _headers, _timeout):
    return {
        "output": [
            {
                "content": [
                    {
                        "type": "output_text",
                        "text": '{"text":"Vivian","flower_name":"Daffodil","font":1,"warnings":[],"confidence":0.9}',
                    }
                ]
            }
        ]
    }


def test_image_data_url_from_bytes_and_file(tmp_path: Path):
    assert _image_data_url(b"\x89PNG", None).startswith("data:image/png;base64,")
    jpg = tmp_path / "o.jpg"
    jpg.write_bytes(b"\xff\xd8\xff")
    assert _image_data_url(jpg, None).startswith("data:image/jpeg;base64,")


def test_screenshot_openai_legacy_sends_image_and_parses(tmp_path: Path):
    img = tmp_path / "order.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n-fake")
    calls = []

    def fake(url, payload, headers, timeout):
        calls.append(payload)
        return _legacy_response(url, payload, headers, timeout)

    result = parse_order_screenshot_with_gpt(img, api_key="sk-test", http_post=fake)
    assert result.text == "Vivian"
    assert result.flower_name == "Daffodil" and result.font == 1

    user_content = calls[0]["input"][1]["content"]
    image_parts = [p for p in user_content if p.get("type") == "input_image"]
    assert image_parts and image_parts[0]["image_url"].startswith("data:image/png;base64,")
    # 不传 bundle → 文字/花名/字体 schema（按花名配素材，无 month/flower）
    schema_props = calls[0]["text"]["format"]["schema"]["properties"]
    assert "month" not in schema_props and "flower" not in schema_props
    assert set(schema_props) == {"text", "flower_name", "font", "warnings", "confidence"}


def test_screenshot_openai_catalog_mode(tmp_path: Path):
    bundle = _bundle(tmp_path)
    img = tmp_path / "order.png"
    img.write_bytes(b"\x89PNG-fake")

    def fake(url, payload, headers, timeout):
        return {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"text":"V","material_key":"daffodil","font_key":"malovelyscript","warnings":[],"confidence":0.9}',
                        }
                    ]
                }
            ]
        }

    result = parse_order_screenshot_with_gpt(img, bundle=bundle, api_key="sk-test", http_post=fake)
    assert result.material_key == "daffodil"
    assert result.selected_flower_asset  # 富化到具体素材路径


def test_screenshot_missing_key_raises(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    img = tmp_path / "o.png"
    img.write_bytes(b"x")
    with pytest.raises(RuntimeError):
        parse_order_screenshot_with_gpt(img, provider="openai", http_post=lambda *a: {})


def test_screenshot_unsupported_provider(tmp_path: Path):
    img = tmp_path / "o.png"
    img.write_bytes(b"x")
    with pytest.raises(ValueError):
        parse_order_screenshot_with_gpt(img, api_key="k", provider="claude", http_post=lambda *a: {})
