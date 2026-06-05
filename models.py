from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParseResult:
    text: str = ""
    month: int | None = None
    font: int | None = None
    flower: int | None = None
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0
    birth_month: str | None = None
    flower_name: str | None = None
    font_design: str | None = None
    personalization_raw: str | None = None
    personalization_type: str = "unknown"
    selected_flower_asset: str | None = None
    selected_font_asset: str | None = None
    parse_confidence: float = 0.0
    asset_confidence: float = 0.0


@dataclass(frozen=True)
class AIParseConfig:
    enabled: bool = True
    prefer_ai: bool = False
    api_key: str | None = None
    model: str | None = None
    project: str | None = None
    organization: str | None = None
    provider: str = "openai"
    base_url: str | None = None
    timeout: float = 20.0


@dataclass(frozen=True)
class EngravingLayout:
    canvas_width: int = 1732
    canvas_height: int = 1280
    flower_x: int = 310
    flower_y: int = 40
    flower_width: int = 1060
    flower_height: int = 1060
    text_x: int = 808
    text_y: int = 830
    text_width: int = 804
    text_height: int = 260
    text_size: int = 190


@dataclass(frozen=True)
class BirthFlowerDesign:
    text: str
    month: int
    font: int
    flower: int
    flower_asset_path: Path | None = None
    font_path: Path | None = None
    flower_name: str = ""
    layout: EngravingLayout = field(default_factory=EngravingLayout)
    personalization_type: str = "unknown"
    glyph_overrides: dict[int, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class FlowerAsset:
    name: str
    month: int
    flower: int
    path: Path
    asset_key: str = ""
    display_name: str = ""
    category: str = "birth_flower"
    is_vector_safe: bool = True
    embedded_raster_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class FontAsset:
    name: str
    index: int
    path: Path
    font_design: str = ""
    family_name: str = ""
    file_size: int = 0
    has_ending_glyphs: bool = False
