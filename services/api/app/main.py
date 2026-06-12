from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.domain import DomainError
from app.domain.exports import export_dxf
from app.domain.fonts import get_font_file_path, list_fonts, list_glyphs
from app.domain.orders import parse_order_note
from app.domain.output_store import save_outputs
from app.domain.settings import get_path_settings, update_path_settings
from app.domain.templates import apply_template
from app.schemas.errors import ErrorBody, ErrorEnvelope
from app.schemas.exports import DxfExportRequest, DxfExportResponse, ExportWarningBody
from app.schemas.fonts import (
    FontGlyphsResponse,
    FontIssueBody,
    FontSummaryBody,
    GlyphBody,
    ListFontsResponse,
)
from app.schemas.health import HealthResponse
from app.schemas.orders import ParseOrderRequest, ParseOrderResponse
from app.schemas.outputs import SaveOutputsRequest, SaveOutputsResponse, SavedOutputFileBody
from app.schemas.settings import PathSettingsBody
from app.schemas.templates import ApplyTemplateRequest, ApplyTemplateResponse

app = FastAPI(title="Flower Local API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="flower-api", version="0.1.0")


@app.get("/fonts", response_model=None)
def get_fonts() -> Any:
    catalog = list_fonts()
    response = ListFontsResponse(
        fonts=[FontSummaryBody.from_domain(font) for font in catalog.fonts],
        issues=[FontIssueBody.from_domain(issue) for issue in catalog.issues],
        fontCount=len(catalog.fonts),
    )
    return response.model_dump(by_alias=True)


@app.get("/fonts/{font_id}/glyphs", response_model=None)
def get_font_glyphs(font_id: str) -> Any:
    try:
        font, glyphs, issues = list_glyphs(font_id)
    except DomainError as exc:
        return _domain_error_response(exc, status_code=404 if exc.code == "FONT_NOT_FOUND" else 422)

    response = FontGlyphsResponse(
        font=FontSummaryBody.from_domain(font),
        glyphs=[GlyphBody.from_domain(glyph) for glyph in glyphs],
        issues=[FontIssueBody.from_domain(issue) for issue in issues],
        glyphCount=len(glyphs),
    )
    return response.model_dump(by_alias=True)


@app.get("/fonts/{font_id}/file", response_model=None)
def get_font_file(font_id: str) -> Any:
    try:
        path = get_font_file_path(font_id)
    except DomainError as exc:
        return _domain_error_response(exc, status_code=404 if exc.code == "FONT_NOT_FOUND" else 422)

    return FileResponse(path, media_type=_font_media_type(path.suffix), filename=path.name)


@app.get("/settings/paths", response_model=None)
def read_path_settings() -> Any:
    try:
        settings = get_path_settings()
    except DomainError as exc:
        return _domain_error_response(exc, status_code=422)
    return PathSettingsBody.from_domain(settings).model_dump(by_alias=True)


@app.put("/settings/paths", response_model=None)
def write_path_settings(request: PathSettingsBody) -> Any:
    try:
        settings = update_path_settings(
            asset_directories=request.asset_directories,
            font_directories=request.font_directories,
            output_directory=request.output_directory,
        )
    except DomainError as exc:
        return _domain_error_response(exc, status_code=422)
    return PathSettingsBody.from_domain(settings).model_dump(by_alias=True)


@app.post("/orders/parse", response_model=None)
def parse_order(request: ParseOrderRequest) -> Any:
    try:
        parsed_order = parse_order_note(request.order_note, request.order_id)
    except DomainError as exc:
        return _domain_error_response(exc, status_code=422)
    response = ParseOrderResponse(parsedOrder=parsed_order)
    return response.model_dump(by_alias=True)


@app.post("/templates/apply", response_model=None)
def apply_template_to_order(request: ApplyTemplateRequest) -> Any:
    try:
        document = apply_template(
            request.template_id,
            request.parsed_order,
            project_id=request.project_id,
            job_id=request.job_id,
        )
    except DomainError as exc:
        return _domain_error_response(exc, status_code=422)
    response = ApplyTemplateResponse(document=document)
    return response.model_dump(by_alias=True)


@app.post("/exports/dxf", response_model=None)
def export_document_dxf(request: DxfExportRequest) -> Any:
    try:
        exported = export_dxf(
            request.document,
            units=request.units,
            exported_at=request.exported_at,
        )
    except DomainError as exc:
        return _domain_error_response(exc, status_code=422)

    response = DxfExportResponse(
        fileName=exported.file_name,
        mimeType=exported.mime_type,
        contentBase64=exported.content_base64,
        metadata=exported.metadata,
        warnings=[ExportWarningBody(**warning.to_dict()) for warning in exported.warnings],
    )
    return response.model_dump(by_alias=True)


@app.post("/outputs/save", response_model=None)
def save_order_outputs(request: SaveOutputsRequest) -> Any:
    try:
        saved = save_outputs(
            order_name=request.order_name,
            document=request.document,
            svg=request.svg,
            png_data_url=request.png_data_url,
            dxf_content_base64=request.dxf_content_base64,
            output_directory=request.output_directory,
        )
    except DomainError as exc:
        return _domain_error_response(exc, status_code=422)

    response = SaveOutputsResponse(
        outputDir=saved.output_dir,
        files=[
            SavedOutputFileBody(
                kind=file.kind,
                fileName=file.file_name,
                relativePath=file.relative_path,
                bytesWritten=file.bytes_written,
            )
            for file in saved.files
        ],
    )
    return response.model_dump(by_alias=True)


def _domain_error_response(exc: DomainError, status_code: int) -> JSONResponse:
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            recoverable=exc.recoverable,
        )
    )
    return JSONResponse(status_code=status_code, content=envelope.model_dump(by_alias=True))


def _font_media_type(suffix: str) -> str:
    suffix = suffix.casefold()
    if suffix in {".ttf", ".ttc"}:
        return "font/ttf"
    if suffix in {".otf", ".otc"}:
        return "font/otf"
    return "application/octet-stream"
