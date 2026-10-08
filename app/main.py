"""VYOM+ local evaluator API. Run with: uv run uvicorn app.main:app."""

import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .extraction import MAX_PAGES, extract_document, ocr_available
from .models import (
    AuditEvent,
    Document,
    ProcessingMetadata,
    QualityAssessment,
    Review,
    ReviewUpdate,
    RoutingMetadata,
    SourceObservation,
)
from .provenance import attach_invoice_provenance, review_audit_entries
from .quality import analyze_and_retain, ocr_enhancement
from .store import Store, csv_export
from .tabular import extract_tabular
from .validation import validate_document
from .vision import vision_model

ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD = 20 * 1024 * 1024
TYPES = {
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".pdf": "pdf",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
}
MEDIA = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "jpeg": "image/jpeg",
    "png": "image/png",
}
_processing_lock = threading.Lock()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def routing_metadata(
    kind: str, pipeline: str, handwriting: bool, quality: QualityAssessment
) -> RoutingMetadata:
    if kind in {"csv", "xlsx"}:
        document_class = "tabular"
        reason = "Structured rows were routed to the bounded CSV/XLSX table extractor."
    elif kind == "pdf" and pipeline == "pdf_text":
        document_class = "digital_pdf"
        reason = "Usable native PDF text was available, so raster OCR was not required."
    elif kind == "pdf":
        document_class = "scanned"
        reason = "The PDF page was routed through rendered-page extraction because native text was unavailable or insufficient."
    else:
        document_class = "printed"
        reason = "The uploaded image was routed through the local image extraction pipeline."
    selected_route = pipeline
    if quality.applicable and quality.score is not None:
        if not (kind == "pdf" and pipeline == "pdf_text"):
            reason += f" Quality assessment: {quality.score}/100."
        if quality.score < 45 and kind not in {"csv", "xlsx"}:
            document_class = "poor_quality"
            selected_route = f"{pipeline}_quality_review"
            reason += " Enhanced representations were retained and source review is required."
    if handwriting:
        selected_route = f"{pipeline}_handwriting_review"
        if document_class != "poor_quality":
            document_class = "handwritten"
        reason += " Handwriting mode was requested; this is a review signal, not handwriting recognition."
    return RoutingMetadata(
        document_class=document_class,
        selected_route=selected_route,
        reason=reason,
        handwriting_requested=handwriting,
    )


def fallback_reason(warnings: list[str]) -> str | None:
    signals = ("fallback", "failed", "unavailable", "could not", "ambiguous")
    reasons = [warning for warning in warnings if any(signal in warning.lower() for signal in signals)]
    return " ".join(dict.fromkeys(reasons))[:2000] or None


def page_count(kind: str, observations: list[SourceObservation], tables: list) -> int | None:
    if kind in {"csv", "xlsx"}:
        return len(tables)
    pages = [observation.page_number for observation in observations if observation.page_number]
    return max(pages, default=1)


def annotate_page_quality(
    page_quality,
    observations: list[SourceObservation],
    pipeline: str,
    ocr_preprocessing: str,
):
    """Join pre-extraction page metrics with the extraction method that ran."""

    for page in page_quality:
        page_observations = [
            observation
            for observation in observations
            if observation.page_number == page.page_number
        ]
        native = any(observation.source == "native_text" for observation in page_observations)
        page.native_text_available = native
        page.extraction_method = "pdf_text" if native else pipeline
        if not native:
            page.ocr_preprocessing = f"grayscale+{ocr_preprocessing}"


class RequestLimits:
    """Bound even chunked multipart bodies, before the multipart parser allocates files."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        # No public hosting/authentication is implied by this local evaluator app.
        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            origin = headers.get(b"origin", b"").decode("latin1")
            host = headers.get(b"host", b"").decode("latin1")
            if origin and origin not in {f"http://{host}", f"https://{host}"}:
                return await JSONResponse(
                    {"detail": "Cross-origin writes are not allowed."}, status_code=403
                )(scope, receive, send)
        limit = MAX_UPLOAD + 1024 * 1024
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = limit + 1
        if length > limit:
            return await JSONResponse(
                {"detail": "Request too large. Maximum upload is 20 MB."}, status_code=413
            )(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > limit:
                return await JSONResponse(
                    {"detail": "Request too large. Maximum upload is 20 MB."}, status_code=413
                )(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body"):
                break
        body = b"".join(chunks)
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        async def secure_send(message):
            if message["type"] == "http.response.start":
                policy = b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
                if scope["path"] in {"/docs", "/redoc"}:
                    policy = b"default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store"),
                    (b"content-security-policy", policy),
                ]
            await send(message)

        return await self.app(scope, bounded_receive, secure_send)


def create_app(data_dir: Path | None = None):
    api = FastAPI(
        title="VYOM+ Invoice Intelligence",
        version="0.1.0",
        description="Local-first invoice extraction. Validation checks consistency, not legal GST compliance.",
    )
    store = Store(data_dir or Path(os.getenv("VYOM_DATA_DIR", ROOT / ".data")))
    api.state.store = store
    api.add_middleware(RequestLimits)

    def get_document(document_id: str):
        try:
            UUID(document_id)
        except ValueError:
            raise HTTPException(404, "Document not found.") from None
        document = store.get(document_id)
        if document is None:
            raise HTTPException(404, "Document not found.")
        return document

    @api.get("/api/health")
    def health():
        return {
            "status": "ok",
            "ocr_available": ocr_available(),
            "vision_configured": bool(vision_model()),
            "vision_model": vision_model(),
            "limits": {"max_upload_mb": 20, "max_pages": MAX_PAGES},
        }

    @api.get("/api/documents")
    def list_documents():
        return {"documents": store.list()}

    @api.post("/api/documents", response_model=Document, status_code=201)
    def upload(file: UploadFile = File(...), handwriting: bool = Form(False)):
        filename = re.sub(
            r"[\x00-\x1f\x7f]", "", (file.filename or "document").replace("\\", "/").split("/")[-1]
        )[:180]
        suffix = Path(filename).suffix.lower()
        if suffix not in TYPES:
            raise HTTPException(415, "Supported formats: .xlsx, .csv, .pdf, .jpg, .jpeg, .png")
        if not _processing_lock.acquire(blocking=False):
            raise HTTPException(
                429, "Another document is processing. Please retry when it finishes."
            )
        document_id = str(uuid4())
        path = store.uploads / document_id
        started_at = utc_now()
        started_clock = time.perf_counter()
        try:
            size = 0
            with path.open("wb") as output:
                path.chmod(0o600)
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, "Maximum upload size is 20 MB.")
                    output.write(chunk)
            if not size:
                raise HTTPException(400, "The uploaded file is empty.")
            with path.open("rb") as source:
                signature = source.read(16)
            kind = TYPES[suffix]
            signatures = {
                "pdf": b"%PDF-",
                "xlsx": b"PK\x03\x04",
                "png": b"\x89PNG\r\n\x1a\n",
                "jpeg": b"\xff\xd8\xff",
            }
            if kind in signatures and not signature.startswith(signatures[kind]):
                raise HTTPException(400, "File contents do not match the selected file extension.")
            document = Document(
                id=document_id,
                filename=filename,
                source_type=kind,
                pipeline="",
                created_at=utc_now(),
                processing=ProcessingMetadata(started_at=started_at, source_size_bytes=size),
            )
            quality_started = time.perf_counter()
            quality_warnings = []
            ocr_preprocessing = "autocontrast"
            if kind in {"png", "jpeg", "pdf"}:
                (
                    document.quality,
                    document.page_quality,
                    document.preprocessing,
                    quality_warnings,
                ) = analyze_and_retain(
                    path,
                    kind,
                    store.preprocessing / document_id,
                    f"preprocessed/{document_id}",
                )
            else:
                document.quality = QualityAssessment(
                    applicable=False,
                    score=None,
                    notes=["Visual quality metrics do not apply to structured tabular input."],
                )
            document.processing.quality_duration_ms = round(
                (time.perf_counter() - quality_started) * 1000
            )
            if document.quality.applicable:
                ocr_preprocessing = ocr_enhancement(document.quality)
            extraction_started = time.perf_counter()
            if kind in {"csv", "xlsx"}:
                (
                    document.invoices,
                    document.tables,
                    document.raw_text,
                    document.extraction_warnings,
                ) = extract_tabular(path, kind)
                document.pipeline = "tabular"
                document.observations = [
                    SourceObservation(
                        source="tabular",
                        text=document.raw_text[:10000],
                        metadata={"sheet_count": str(len(document.tables))},
                    )
                ]
                for invoice in document.invoices:
                    attach_invoice_provenance(invoice, observations=document.observations)
            else:
                (
                    document.invoices,
                    document.raw_text,
                    document.pipeline,
                    document.extraction_warnings,
                    document.observations,
                ) = extract_document(
                    path,
                    kind,
                    handwriting,
                    include_observations=True,
                    preprocessing=ocr_preprocessing,
                )
            document.extraction_warnings = quality_warnings + document.extraction_warnings
            annotate_page_quality(
                document.page_quality,
                document.observations,
                document.pipeline,
                ocr_preprocessing,
            )
            extraction_duration = round((time.perf_counter() - extraction_started) * 1000)
            document.routing = routing_metadata(
                kind, document.pipeline, handwriting, document.quality
            )
            document.processing.extraction_duration_ms = extraction_duration
            document.processing.page_count = page_count(
                kind, document.observations, document.tables
            )
            document.processing.record_count = len(document.invoices)
            document.processing.fallback_reason = fallback_reason(document.extraction_warnings)
            document.extraction_snapshot = [invoice.model_copy(deep=True) for invoice in document.invoices]
            validation_started = time.perf_counter()
            validate_document(document)
            document.processing.validation_duration_ms = round(
                (time.perf_counter() - validation_started) * 1000
            )
            completed_at = utc_now()
            document.processing.completed_at = completed_at
            document.processing.duration_ms = round((time.perf_counter() - started_clock) * 1000)
            document.audit_events.extend(
                [
                    AuditEvent(
                        timestamp=completed_at,
                        action="extraction_completed",
                        reason=(
                            f"Route {document.pipeline} selected; {len(document.invoices)} "
                            "record(s) returned."
                        ),
                    ),
                    AuditEvent(
                        timestamp=completed_at,
                        action="validation_executed",
                        reason=f"Deterministic validation completed with status {document.status}.",
                    ),
                ]
            )
            store.save(document)
            return document
        except HTTPException:
            path.unlink(missing_ok=True)
            store.cleanup_preprocessing(document_id)
            raise
        except (ValueError, ValidationError) as exc:
            path.unlink(missing_ok=True)
            store.cleanup_preprocessing(document_id)
            message = (
                "Extraction returned values outside the supported schema."
                if isinstance(exc, ValidationError)
                else str(exc)
            )
            raise HTTPException(422, message) from None
        except Exception:
            path.unlink(missing_ok=True)
            store.cleanup_preprocessing(document_id)
            raise HTTPException(
                422,
                "Document could not be processed. Check for corruption, unsupported layout, or unavailable OCR dependencies.",
            ) from None
        finally:
            file.file.close()
            _processing_lock.release()

    @api.get("/api/documents/{document_id}", response_model=Document)
    def detail(document_id: str):
        return get_document(document_id)

    @api.put("/api/documents/{document_id}", response_model=Document)
    def update(document_id: str, changes: ReviewUpdate):
        document = get_document(document_id)
        before = [invoice.model_copy(deep=True) for invoice in document.invoices]
        submitted = [invoice.model_copy(deep=True) for invoice in changes.invoices]
        if not document.extraction_snapshot:
            # Legacy records predate the snapshot field. Preserve their current
            # values as the best available extraction baseline on first review.
            document.extraction_snapshot = [invoice.model_copy(deep=True) for invoice in before]
        for index, invoice in enumerate(changes.invoices):
            original = document.invoices[index] if index < len(document.invoices) else None
            # Provenance cannot be changed to bypass the review requirement.
            invoice.extraction_method = original.extraction_method if original else "manual"
            invoice.confidence = original.confidence if original else None
            invoice.field_evidence = dict(original.field_evidence) if original else {}
            invoice.field_confidence = dict(original.field_confidence) if original else {}
            invoice.field_provenance = (
                {
                    key: value.model_copy(deep=True)
                    for key, value in original.field_provenance.items()
                }
                if original
                else {}
            )
            invoice.field_evidence["review_note"] = (
                "Record edited in review; original extraction evidence retained and may not match corrected values."
            )
        timestamp = utc_now()
        corrections, audit_events = review_audit_entries(before, submitted, timestamp)
        document.invoices = changes.invoices
        document.review = Review(confirmed=changes.reviewer_confirmed, updated_at=utc_now())
        document.human_corrections.extend(corrections)
        document.audit_events.extend(audit_events)
        if changes.reviewer_confirmed:
            document.audit_events.append(
                AuditEvent(
                    timestamp=timestamp,
                    action="reviewer_confirmation",
                    reason="Reviewer explicitly confirmed source comparison.",
                )
            )
        validation_started = time.perf_counter()
        validate_document(document)
        document.processing.validation_duration_ms = round(
            (time.perf_counter() - validation_started) * 1000
        )
        document.audit_events.append(
            AuditEvent(
                timestamp=utc_now(),
                action="revalidation",
                reason=f"Deterministic validation re-run with status {document.status}.",
            )
        )
        store.save(document)
        return document

    @api.delete("/api/documents/{document_id}", status_code=204)
    def delete(document_id: str):
        get_document(document_id)
        store.delete(document_id)
        return Response(status_code=204)

    @api.get("/api/documents/{document_id}/export")
    def export(document_id: str, format: str = "json"):
        document = get_document(document_id)
        if format == "json":
            return Response(
                document.model_dump_json(indent=2),
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="vyom-{document.id}.json"'},
            )
        if format == "csv":
            return Response(
                csv_export(document),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="vyom-{document.id}.csv"'},
            )
        raise HTTPException(400, "Export format must be json or csv.")

    @api.get("/api/documents/{document_id}/source")
    def source(document_id: str):
        document = get_document(document_id)
        path = store.uploads / document.id
        if not path.is_file():
            raise HTTPException(404, "Original source file is unavailable.")
        return FileResponse(
            path, filename=document.filename, media_type=MEDIA[document.source_type]
        )

    @api.get("/api/documents/{document_id}/preprocessing/{page_number}/{name}")
    def preprocessing(document_id: str, page_number: int, name: str):
        document = get_document(document_id)
        representation = next(
            (
                item
                for item in document.preprocessing
                if item.page_number == page_number and item.name == name
            ),
            None,
        )
        if not representation or not representation.artifact_path:
            raise HTTPException(404, "Preprocessing representation is unavailable.")
        path = (store.root / representation.artifact_path).resolve()
        preprocessing_root = store.preprocessing.resolve()
        if not path.is_relative_to(preprocessing_root) or not path.is_file():
            raise HTTPException(404, "Preprocessing representation is unavailable.")
        return FileResponse(path, filename=path.name, media_type="image/png")

    @api.get("/api/samples")
    def samples():
        descriptions = {
            "sample-invoices.csv": "Two invoices with explicit GST and item totals.",
            "sample-invoices.xlsx": "Excel version of the clean item table.",
            "sample-invoice.pdf": "Digitally generated, labeled GST invoice.",
            "sample-invoice.png": "Printed invoice image for local OCR.",
            "sample-mismatch.csv": "Deliberately inconsistent grand total to exercise validation.",
        }
        return {
            "samples": [
                {
                    "name": name.removeprefix("sample-")
                    .rsplit(".", 1)[0]
                    .replace("-", " ")
                    .title(),
                    "filename": name,
                    "url": f"/samples/{name}",
                    "description": description,
                }
                for name, description in descriptions.items()
                if (ROOT / "samples" / name).is_file()
            ]
        }

    api.mount("/samples", StaticFiles(directory=ROOT / "samples"), name="samples")
    api.mount("/", StaticFiles(directory=ROOT / "app" / "static", html=True), name="frontend")
    return api


app = create_app()
