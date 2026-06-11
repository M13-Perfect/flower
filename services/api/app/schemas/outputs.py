from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.schemas.errors import ApiModel


class SaveOutputsRequest(ApiModel):
    order_name: str = Field(alias="orderName", min_length=1, max_length=200)
    document: dict[str, Any]
    svg: str = Field(min_length=1)
    png_data_url: str = Field(alias="pngDataUrl", min_length=1)
    dxf_content_base64: str | None = Field(default=None, alias="dxfContentBase64")


class SavedOutputFileBody(ApiModel):
    kind: Literal["json", "png", "svg", "dxf"]
    file_name: str = Field(alias="fileName")
    relative_path: str = Field(alias="relativePath")
    bytes_written: int = Field(alias="bytesWritten")


class SaveOutputsResponse(ApiModel):
    output_dir: str = Field(alias="outputDir")
    files: list[SavedOutputFileBody]
