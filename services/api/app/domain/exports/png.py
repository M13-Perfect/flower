from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from pathlib import Path

from app.domain import DomainError


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# cairocffi 在 Windows 上通过 PATH 查找 cairo 原生 DLL;pip 不会提供它。
# 默认候选是 msys2 的 ucrt64 运行时,可用 FLOWER_CAIRO_DIR 覆盖。
_DEFAULT_CAIRO_DIR = r"C:\msys64\ucrt64\bin"


@dataclass(frozen=True)
class PngRasterizeResult:
    path: Path
    width: int
    height: int
    bytes_written: int


def rasterize_svg_to_png(
    svg: str,
    *,
    width: int,
    height: int,
    output_path: Path | str,
) -> PngRasterizeResult:
    if width <= 0 or height <= 0:
        raise DomainError(
            code="VALIDATION_ERROR",
            message="PNG width and height must be positive.",
            details={"width": width, "height": height},
            recoverable=True,
        )

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if _try_cairosvg(svg, width, height, path):
        data = path.read_bytes()
        actual_width, actual_height = read_png_size(data)
        return PngRasterizeResult(
            path=path,
            width=actual_width,
            height=actual_height,
            bytes_written=len(data),
        )
    raise DomainError(
        code="PNG_RASTERIZER_UNAVAILABLE",
        message="PNG output requires cairosvg.",
        details={"install": "Install cairosvg, or omit --png."},
        recoverable=True,
    )


def read_png_size(data: bytes) -> tuple[int, int]:
    if not data.startswith(PNG_SIGNATURE) or len(data) < 24:
        raise DomainError(
            code="PNG_INVALID",
            message="PNG output is invalid.",
            details={},
            recoverable=True,
        )
    if data[12:16] != b"IHDR":
        raise DomainError(
            code="PNG_INVALID",
            message="PNG output is missing IHDR.",
            details={},
            recoverable=True,
        )
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


def png_rasterizer_available() -> bool:
    """探测栅格化能力;批量流程据此自动决定是否生成 PNG,而不是硬失败。"""
    return _import_cairosvg() is not None


def _import_cairosvg():
    candidate_dirs = [None]
    env_dir = os.environ.get("FLOWER_CAIRO_DIR")
    if env_dir:
        candidate_dirs.append(env_dir)
    candidate_dirs.append(_DEFAULT_CAIRO_DIR)
    for directory in candidate_dirs:
        if directory:
            if not Path(directory).is_dir():
                continue
            current_path = os.environ.get("PATH", "")
            if directory not in current_path.split(os.pathsep):
                os.environ["PATH"] = directory + os.pathsep + current_path
        try:
            return importlib.import_module("cairosvg")
        except ImportError:
            return None  # 包未安装,换目录也无济于事
        except OSError:
            continue  # cairo DLL 未找到,注入下一个候选目录重试
    return None


def _try_cairosvg(svg: str, width: int, height: int, output_path: Path) -> bool:
    cairosvg = _import_cairosvg()
    if cairosvg is None:
        return False
    try:
        cairosvg.svg2png(
            bytestring=svg.encode("utf-8"),
            write_to=str(output_path),
            output_width=width,
            output_height=height,
        )
    except Exception as exc:
        raise DomainError(
            code="PNG_EXPORT_FAILED",
            message="cairosvg could not rasterize SVG.",
            details={"errorType": exc.__class__.__name__},
            recoverable=True,
        ) from exc
    return True
