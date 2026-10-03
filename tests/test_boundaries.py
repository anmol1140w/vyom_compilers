import io

import pytest
from PIL import Image

from app import extraction, main, vision
from app.models import Invoice


@pytest.mark.parametrize(
    "name,data,status",
    [
        ("invoice.exe", b"invalid", 415),
        ("invoice.pdf", b"not a pdf", 400),
        ("invoice.png", b"%PDF-1.4", 400),
        ("invoice.csv", b"", 400),
        ("invoice.xlsx", b"PK\x03\x04bad", 422),
        ("invoice.csv", b"a,b\none,two", 422),
        ("invoice.pdf", b"%PDF-1.4 broken", 422),
    ],
)
def test_rejects_bad_uploads_without_orphan_files(client, upload, name, data, status):
    response = upload(name, data)
    assert response.status_code == status, response.text
    assert not list(client.app.state.store.uploads.iterdir())
    assert client.get("/api/documents").json()["documents"] == []


def test_limits_headers_rows_and_pages(client, upload, monkeypatch):
    response = client.post(
        "/api/documents", content=b"x", headers={"content-length": str(22 * 1024 * 1024)}
    )
    assert response.status_code == 413
    contents = b"Invoice No,Description,Amount\n" + b"A1,Item,1\n" * 5000
    response = upload("large.csv", contents)
    assert response.status_code == 422
    assert "5,000" in response.json()["detail"]
    monkeypatch.setattr(extraction, "MAX_PAGES", 0)
    assert upload("sample-invoice.pdf").status_code == 422


def test_cross_origin_writes_blocked_and_missing_ids_are_404(client):
    response = client.post("/api/documents", headers={"origin": "https://untrusted.example"})
    assert response.status_code == 403
    assert client.get("/api/documents/not-a-uuid").status_code == 404
    assert client.get("/api/documents/00000000-0000-0000-0000-000000000000").status_code == 404


def test_concurrent_processing_gets_retryable_error(upload):
    main._processing_lock.acquire()
    try:
        response = upload()
        assert response.status_code == 429
    finally:
        main._processing_lock.release()


def test_invalid_numeric_source_is_null_not_fabricated(upload):
    record = upload(
        "bad-numbers.csv", b"Invoice No,Description,Taxable Value,Grand Total\nA1,Item,1O0,118\n"
    ).json()
    assert record["invoices"][0]["totals"]["taxable_value"] is None
    assert any("could not parse taxable_value" in w for w in record["extraction_warnings"])
    assert record["status"] != "validated"


def test_vision_failure_falls_back_and_stays_reviewable(upload, monkeypatch):
    monkeypatch.setenv("VYOM_VISION_MODEL", "test-model-no-network")

    def fail(image):
        raise TimeoutError("Simulated adapter timeout")

    monkeypatch.setattr(extraction, "extract_vision", fail)
    record = upload("sample-invoice.png", handwriting="true").json()
    assert record["pipeline"] == "ocr"
    assert record["status"] == "needs_review"
    assert any(
        "Vision extraction failed (TimeoutError)" in w for w in record["extraction_warnings"]
    )


def test_vision_route_preserves_uncertainty_and_provenance(upload, monkeypatch):
    monkeypatch.setenv("VYOM_VISION_MODEL", "mock-boundary-only")
    monkeypatch.setattr(
        extraction,
        "extract_vision",
        lambda image: [Invoice(invoice_number="UNKNOWN", extraction_method="local_vision")],
    )
    record = upload("sample-invoice.png", handwriting="true").json()
    assert record["pipeline"] == "local_vision"
    assert record["status"] == "needs_review"
    assert record["invoices"][0]["totals"]["grand_total"] is None
    assert "Office chairs" in record["raw_text"]
    assert any("model-produced" in w for w in record["extraction_warnings"])


def test_vision_adapter_schema_request_and_untrusted_confidence(monkeypatch):
    monkeypatch.setenv("VYOM_VISION_MODEL", "mock-boundary-only")
    calls = []

    class Reply:
        content = b"synthetic reply"

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "message": {
                    "content": '{"invoices": [{"invoice_number":"A1", "confidence":1, "extraction_method":"tabular"}]}'
                }
            }

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, json):
            calls.append((url, json))
            return Reply()

    monkeypatch.setattr(vision.httpx, "Client", Client)
    records = vision.extract_vision(Image.new("RGB", (32, 32), "white"))
    assert calls[0][0] == "http://127.0.0.1:11434/api/chat"
    assert calls[0][1]["messages"][0]["images"]
    assert calls[0][1]["format"]["properties"]["invoices"]
    assert records[0].confidence is None
    assert records[0].extraction_method == "local_vision"


def test_image_decompression_limit(upload, monkeypatch):
    monkeypatch.setattr(extraction, "MAX_PIXELS", 100)
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buffer, format="PNG")
    response = upload("too-big.png", buffer.getvalue())
    assert response.status_code == 422


def test_original_filename_cannot_escape_upload_directory(client, upload):
    response = upload("../../outside.csv", b"Invoice No,Description,Amount\nA1,Test,1\n")
    assert response.status_code == 201
    record = response.json()
    assert record["filename"] == "outside.csv"
    assert (client.app.state.store.uploads / record["id"]).is_file()
    assert len(list(client.app.state.store.uploads.iterdir())) == 1


def test_unsupported_export_format(client, upload):
    record = upload().json()
    assert client.get(f"/api/documents/{record['id']}/export?format=xml").status_code == 400


def test_health_and_sample_downloads(client):
    response = client.get("/api/health")
    assert response.json()["ocr_available"] is True
    assert response.json()["vision_configured"] is False
    samples = client.get("/api/samples").json()["samples"]
    assert len(samples) == 5
    for sample in samples:
        assert client.get(sample["url"]).status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
