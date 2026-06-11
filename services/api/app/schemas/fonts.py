from __future__ import annotations

from pydantic import Field

from app.domain.fonts.scanner import FontMetrics, FontRecord, FontScanIssue, GlyphRecord
from app.schemas.errors import ApiModel


class FontIssueBody(ApiModel):
    code: str
    message: str
    path: str | None = None
    recoverable: bool = True

    @classmethod
    def from_domain(cls, issue: FontScanIssue) -> "FontIssueBody":
        return cls(
            code=issue.code,
            message=issue.message,
            path=issue.path,
            recoverable=issue.recoverable,
        )


class FontBoundsBody(ApiModel):
    x_min: int = Field(alias="xMin")
    y_min: int = Field(alias="yMin")
    x_max: int = Field(alias="xMax")
    y_max: int = Field(alias="yMax")

    @classmethod
    def from_dict(cls, value: dict[str, int]) -> "FontBoundsBody":
        return cls(
            xMin=value.get("xMin", 0),
            yMin=value.get("yMin", 0),
            xMax=value.get("xMax", 0),
            yMax=value.get("yMax", 0),
        )


class FontMetricsBody(ApiModel):
    units_per_em: int = Field(alias="unitsPerEm")
    ascender: int
    descender: int
    line_gap: int = Field(alias="lineGap")
    cap_height: int | None = Field(default=None, alias="capHeight")
    x_height: int | None = Field(default=None, alias="xHeight")
    bbox: FontBoundsBody

    @classmethod
    def from_domain(cls, metrics: FontMetrics) -> "FontMetricsBody":
        return cls(
            unitsPerEm=metrics.units_per_em,
            ascender=metrics.ascender,
            descender=metrics.descender,
            lineGap=metrics.line_gap,
            capHeight=metrics.cap_height,
            xHeight=metrics.x_height,
            bbox=FontBoundsBody.from_dict(metrics.bbox),
        )


class FontSummaryBody(ApiModel):
    id: str
    family_name: str = Field(alias="familyName")
    style_name: str = Field(alias="styleName")
    full_name: str = Field(alias="fullName")
    postscript_name: str = Field(alias="postscriptName")
    source_path: str = Field(alias="sourcePath")
    format: str
    file_size: int = Field(alias="fileSize")
    metrics: FontMetricsBody
    glyph_count: int = Field(alias="glyphCount")
    mapped_glyph_count: int = Field(alias="mappedGlyphCount")
    pua_glyph_count: int = Field(alias="puaGlyphCount")

    @classmethod
    def from_domain(cls, font: FontRecord) -> "FontSummaryBody":
        return cls(
            id=font.id,
            familyName=font.family_name,
            styleName=font.style_name,
            fullName=font.full_name,
            postscriptName=font.postscript_name,
            sourcePath=font.source_path,
            format=font.format,
            fileSize=font.file_size,
            metrics=FontMetricsBody.from_domain(font.metrics),
            glyphCount=font.glyph_count,
            mappedGlyphCount=font.mapped_glyph_count,
            puaGlyphCount=font.pua_glyph_count,
        )


class GlyphBody(ApiModel):
    glyph_id: int = Field(alias="glyphId")
    glyph_name: str = Field(alias="glyphName")
    codepoint: str | None = None
    char: str | None = None
    is_mapped: bool = Field(alias="isMapped")
    is_pua: bool = Field(alias="isPua")
    advance_width: int | None = Field(default=None, alias="advanceWidth")
    bbox: FontBoundsBody | None = None

    @classmethod
    def from_domain(cls, glyph: GlyphRecord) -> "GlyphBody":
        return cls(
            glyphId=glyph.glyph_id,
            glyphName=glyph.glyph_name,
            codepoint=glyph.codepoint,
            char=glyph.char,
            isMapped=glyph.is_mapped,
            isPua=glyph.is_pua,
            advanceWidth=glyph.advance_width,
            bbox=FontBoundsBody.from_dict(glyph.bbox) if glyph.bbox else None,
        )


class ListFontsResponse(ApiModel):
    fonts: list[FontSummaryBody]
    issues: list[FontIssueBody] = Field(default_factory=list)
    font_count: int = Field(alias="fontCount")


class FontGlyphsResponse(ApiModel):
    font: FontSummaryBody
    glyphs: list[GlyphBody]
    issues: list[FontIssueBody] = Field(default_factory=list)
    glyph_count: int = Field(alias="glyphCount")
