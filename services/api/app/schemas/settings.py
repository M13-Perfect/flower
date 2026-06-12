from __future__ import annotations

from pydantic import Field

from app.domain.settings import PathSettings
from app.schemas.errors import ApiModel


class PathSettingsBody(ApiModel):
    asset_directories: list[str] = Field(default_factory=list, alias="assetDirectories")
    font_directories: list[str] = Field(default_factory=list, alias="fontDirectories")
    output_directory: str | None = Field(default=None, alias="outputDirectory")

    @classmethod
    def from_domain(cls, settings: PathSettings) -> "PathSettingsBody":
        return cls(
            assetDirectories=list(settings.asset_directories),
            fontDirectories=list(settings.font_directories),
            outputDirectory=settings.output_directory,
        )
