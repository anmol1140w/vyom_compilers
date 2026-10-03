"""VYOM+ local evaluator API. Run with: uv run uvicorn app.main:app."""

import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .extraction import MAX_PAGES, extract_document, ocr_available
from .models import Document, Review, ReviewUpdate
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
            )
            if kind in {"csv", "xlsx"}:
                (
                    document.invoices,
                    document.tables,
                    document.raw_text,
                    document.extraction_warnings,
                ) = extract_tabular(path, kind)
                document.pipeline = "tabular"
            else:
                (
                    document.invoices,
                    document.raw_text,
                    document.pipeline,
                    document.extraction_warnings,
                ) = extract_document(path, kind, handwriting)
            validate_document(document)
            store.save(document)
            return document
        except HTTPException:
            path.unlink(missing_ok=True)
            raise
        except (ValueError, ValidationError) as exc:
            path.unlink(missing_ok=True)
            message = (
                "Extraction returned values outside the supported schema."
                if isinstance(exc, ValidationError)
                else str(exc)
            )
            raise HTTPException(422, message) from None
        except Exception:
            path.unlink(missing_ok=True)
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
        for index, invoice in enumerate(changes.invoices):
            original = document.invoices[index] if index < len(document.invoices) else None
            # Provenance cannot be changed to bypass the review requirement.
            invoice.extraction_method = original.extraction_method if original else "manual"
            invoice.confidence = original.confidence if original else None
            invoice.field_evidence = dict(original.field_evidence) if original else {}
            invoice.field_evidence["review_note"] = (
                "Record edited in review; original extraction evidence retained and may not match corrected values."
            )
        document.invoices = changes.invoices
        document.review = Review(confirmed=changes.reviewer_confirmed, updated_at=utc_now())
        validate_document(document)
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
