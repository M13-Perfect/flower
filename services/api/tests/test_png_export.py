from __future__ import annotations

import struct
import sys
import types
import zlib

import pytest

from app.domain import DomainError
from app.domain.exports.png import rasterize_svg_to_png, read_png_size


def test_rasterize_svg_to_png_uses_cairosvg_when_available(tmp_path, monkeypatch) -> None:
    fake_cairosvg = types.SimpleNamespace(svg2png=fake_svg2png)
    monkeypatch.setitem(sys.modules, "cairosvg", fake_cairosvg)
    output_path = tmp_path / "preview.png"

    result = rasterize_svg_to_png(
        "<svg/>",
        width=123,
        height=45,
        output_path=output_path,
    )

    assert result.path == output_path
    assert result.width == 123
    assert result.height == 45
    assert result.bytes_written == len(output_path.read_bytes())
    assert read_png_size(output_path.read_bytes()) == (123, 45)


def test_rasterize_svg_to_png_reports_optional_dependency_gap(tmp_path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "cairosvg", None)
    output_path = tmp_path / "preview.png"

    with pytest.raises(DomainError) as exc_info:
        rasterize_svg_to_png("<svg/>", width=20, height=10, output_path=output_path)

    assert exc_info.value.code == "PNG_RASTERIZER_UNAVAILABLE"
    assert not output_path.exists()


def fake_svg2png(
    *,
    bytestring: bytes,
    write_to: str,
    output_width: int,
    output_height: int,
) -> None:
    assert bytestring.startswith(b"<svg")
    with open(write_to, "wb") as handle:
        handle.write(tiny_png(output_width, output_height))


def tiny_png(width: int, height: int) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"\x00" + b"\x00\x00\x00\x00" * width
    idat = zlib.compress(raw * height)
    return signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )
