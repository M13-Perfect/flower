"""线性图标加载与栅格化（Tabler Icons，MIT 协议）。

设计同 `heart_symbol.py` + `text_renderer._rasterize_heart`：图标源是
`assets/icons/<name>.svg`（Tabler outline，`stroke="currentColor"` / `fill="none"`），
按目标颜色注入 stroke 后用**已装的 cairosvg** 栅格化成 PIL 图，再包成 `CTkImage`
供 `CTkLabel/CTkButton` 用。**不新增任何 pip 依赖**（cairosvg/Pillow/customtkinter 现成）。

依赖缺失（如无头测试环境没装 cairosvg）时全部优雅返回 None，调用方退化为「只显示文字、不显示图标」，绝不抛错崩 UI。
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

try:  # 渲染管线（与 text_renderer 同款，正常环境必有）
    import cairosvg
except Exception:  # pragma: no cover - 仅在缺依赖的环境
    cairosvg = None

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

try:
    import customtkinter as ctk
except Exception:  # pragma: no cover
    ctk = None

ICONS_DIR = Path(__file__).resolve().parent / "assets" / "icons"

# 本次选端页 + 产品栏用到的 14 个 Tabler 图标（与 mockup 一一对应）。
KNOWN_ICONS = (
    "flower", "wand", "gauge", "adjustments", "lock", "inbox", "broadcast",
    "plug-connected", "arrow-right", "history", "plus", "eyeglass",
    "guitar-pick", "text-resize",
)


def icon_exists(name: str) -> bool:
    """图标源文件是否存在（不读盘内容，仅探在）。"""
    return (ICONS_DIR / f"{name}.svg").is_file()


@lru_cache(maxsize=64)
def _svg_template(name: str) -> str | None:
    path = ICONS_DIR / f"{name}.svg"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=256)
def rasterize_icon(name: str, color: str, px: int):
    """把 <name> 图标按 color 染色、栅格化成 px×px 的 RGBA PIL 图；失败返回 None。

    px 是**真实像素**（调用方按需给 2× 以适配 HiDPI）。结果带 lru_cache，重复取零成本。
    """
    if cairosvg is None or Image is None:
        return None
    template = _svg_template(name)
    if template is None:
        return None
    # Tabler outline 全用 stroke="currentColor"，直接整体替换成目标颜色即染色。
    svg = template.replace("currentColor", color)
    try:
        png = cairosvg.svg2png(
            bytestring=svg.encode("utf-8"), output_width=px, output_height=px
        )
    except Exception:  # pragma: no cover - 个别异形 SVG 兜底
        return None
    return Image.open(io.BytesIO(png)).convert("RGBA")


def icon_ctk(name: str, color: str = "#e9e9e9", size: int = 20):
    """返回 `CTkImage`（深浅同图，本 App 纯深色），供 CTkLabel/CTkButton 的 image= 用；失败返回 None。

    内部按 2× 渲染再交给 CTkImage 以 size 逻辑像素显示，HiDPI 下保持锐利。
    调用方需把 CTkImage 作为 image= 传给 widget（CTk 会持引用，免 GC）。
    """
    if ctk is None:
        return None
    image = rasterize_icon(name, color, max(size * 2, 32))
    if image is None:
        return None
    return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))
