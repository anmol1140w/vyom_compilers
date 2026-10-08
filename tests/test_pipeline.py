import csv
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from PIL import Image

from app.main import create_app

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.mark.parametrize("filename", ["sample-invoices.csv", "sample-invoices.xlsx"])
def test_clean_tables_group_items_validate_and_preserve_source(upload, filename):
    response = upload(filename)
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["pipeline"] == "tabular"
    assert record["status"] == "validated"
    assert len(record["invoices"]) == 2
    assert len(record["invoices"][0]["line_items"]) == 2
    assert record["invoices"][0]["totals"]["grand_total"] == "14160.00"
    assert record["invoices"][0]["totals"]["taxable_value"] == "12000.00"
    assert len(record["tables"][0]["rows"]) == 3
    assert record["invoices"][0]["confidence"] is None
    assert record["issues"] == []


def test_native_pdf_and_human_review_round_trip(client, upload):
    response = upload("sample-invoice.pdf")
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["pipeline"] == "pdf_text"
    assert record["status"] == "needs_review"
    invoice = record["invoices"][0]
    assert invoice["invoice_number"] == "VYM-2026-001"
    assert len(invoice["line_items"]) == 2
    assert invoice["supplier"]["gstin"] == "27AAPFU0939F1ZV"
    assert "Grand Total" in record["raw_text"]
    response = client.put(
        f"/api/documents/{record['id']}",
        json={"invoices": record["invoices"], "reviewer_confirmed": True},
    )
    assert response.status_code == 200
    saved = response.json()
    assert saved["status"] == "validated"
    assert saved["review"]["confirmed"] is True
    assert saved["review"]["updated_at"] is not None
    assert client.get(f"/api/documents/{record['id']}").json() == saved


def test_processing_metadata_and_structured_native_provenance(upload):
    record = upload("sample-invoice.pdf").json()
    assert record["processing"]["record_count"] == 1
    assert record["processing"]["page_count"] == 1
    assert record["processing"]["extraction_duration_ms"] >= 0
    assert record["processing"]["validation_duration_ms"] >= 0
    assert record["routing"] == {
        "document_class": "digital_pdf",
        "selected_route": "pdf_text",
        "reason": "Usable native PDF text was available, so raster OCR was not required.",
        "handwriting_requested": False,
    }
    invoice = record["invoices"][0]
    evidence = invoice["field_provenance"]["invoice_number"]
    assert evidence["observations"][0]["source"] == "native_text"
    assert evidence["observations"][0]["page_number"] == 1
    assert "extraction_completed" in {event["action"] for event in record["audit_events"]}
    assert record["extraction_snapshot"][0]["invoice_number"] == invoice["invoice_number"]


def test_extraction_snapshot_and_review_corrections_are_separate(client, upload):
    record = upload("sample-invoice.pdf").json()
    original = record["invoices"][0]["totals"]["grand_total"]
    record["invoices"][0]["totals"]["grand_total"] = "11800.01"
    updated = client.put(
        f"/api/documents/{record['id']}",
        json={"invoices": record["invoices"], "reviewer_confirmed": True},
    ).json()
    assert updated["invoices"][0]["totals"]["grand_total"] == "11800.01"
    assert updated["extraction_snapshot"][0]["totals"]["grand_total"] == original
    corrections = updated["human_corrections"]
    assert any(
        correction["field"] == "totals.grand_total"
        and correction["old_value"] == original
        and correction["new_value"] == "11800.01"
        for correction in corrections
    )
    assert {event["action"] for event in updated["audit_events"]} >= {
        "reviewer_correction",
        "reviewer_confirmation",
        "revalidation",
    }


@pytest.mark.parametrize("kind", ["png", "jpg", "jpeg", "pdf"])
def test_real_ocr_for_images_and_scanned_pdf(upload, kind):
    image = Image.open(SAMPLES / "sample-invoice.png").convert("RGB")
    contents = io.BytesIO()
    image.save(contents, format={"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "pdf": "PDF"}[kind])
    response = upload(f"scanned.{kind}", contents.getvalue())
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["pipeline"] == "ocr"
    assert record["status"] == "needs_review"
    assert record["invoices"][0]["invoice_number"] == "VYM-2026-001"
    assert record["invoices"][0]["totals"]["grand_total"] == "14160.00"
    assert len(record["invoices"][0]["line_items"]) == 2
    assert record["invoices"][0]["confidence"] > 0.8


def test_ocr_regions_are_retained_as_source_observations(upload):
    record = upload("sample-invoice.png").json()
    regions = [
        observation
        for observation in record["observations"]
        if observation["source"] == "ocr" and observation["bounding_box"]
    ]
    assert regions
    assert all(region["page_number"] == 1 for region in regions)
    assert all(
        0 <= region["bounding_box"][key] <= 1
        for region in regions
        for key in ("x", "y", "width", "height")
    )
    # Recognition scores stay on source observations and are not field accuracy claims.
    assert record["invoices"][0]["field_confidence"] == {}


def test_handwriting_without_model_does_not_claim_reliability(upload):
    response = upload("sample-invoice.png", handwriting="true")
    record = response.json()
    assert record["status"] == "needs_review"
    assert record["pipeline"] == "ocr"
    assert any(
        "no local vision model configured" in warning for warning in record["extraction_warnings"]
    )
    assert any(issue["code"] == "extraction_review" for issue in record["issues"])


def test_review_does_not_waive_errors_and_correction_revalidates(client, upload):
    record = upload("sample-mismatch.csv").json()
    assert record["status"] == "invalid"
    url = f"/api/documents/{record['id']}"
    response = client.put(url, json={"invoices": record["invoices"], "reviewer_confirmed": True})
    assert response.json()["status"] == "invalid"
    record["invoices"][0]["totals"]["grand_total"] = "11800.00"
    fixed = client.put(
        url, json={"invoices": record["invoices"], "reviewer_confirmed": True}
    ).json()
    assert fixed["status"] == "validated"
    assert client.get(url).json()["invoices"][0]["totals"]["grand_total"] == "11800.00"


def test_export_download_readback_and_delete(client, upload):
    record = upload().json()
    url = f"/api/documents/{record['id']}"
    listing = client.get("/api/documents").json()["documents"]
    assert listing[0]["invoice_count"] == 2
    assert listing[0]["issue_count"] == 0
    exported = client.get(url + "/export?format=json")
    assert exported.json() == record
    assert "attachment" in exported.headers["content-disposition"]
    csv_response = client.get(url + "/export?format=csv")
    rows = list(csv.DictReader(io.StringIO(csv_response.text.lstrip("\ufeff"))))
    assert len(rows) == 3
    assert rows[0]["validation_status"] == "validated"
    assert rows[0]["invoice_grand_total"] == "14160.00"
    assert rows[0]["item_hsn_sac"] == "9403"
    source = client.get(url + "/source")
    assert source.content == (SAMPLES / "sample-invoices.csv").read_bytes()
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    assert client.get(url + "/source").status_code == 404
    assert client.get("/api/documents").json() == {"documents": []}
    assert not (client.app.state.store.uploads / record["id"]).exists()
    assert not (client.app.state.store.preprocessing / record["id"]).exists()


def test_persists_across_application_restart(tmp_path):
    path = tmp_path / "persistent"
    first = TestClient(create_app(path))
    response = first.post(
        "/api/documents",
        files={"file": ("sample.csv", (SAMPLES / "sample-invoices.csv").read_bytes())},
    )
    record = response.json()
    second = TestClient(create_app(path))
    assert second.get(f"/api/documents/{record['id']}").json() == record


def test_semicolon_csv_preamble_and_unknown_columns(upload):
    contents = b"Synthetic export\nInvoice No;Description;Qty;Unit Price;HSN;Comment\nA1;Widgets;2;12.50;001234;retain me\n"
    response = upload("messy.csv", contents)
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["invoices"][0]["line_items"][0]["hsn_sac"] == "001234"
    assert record["invoices"][0]["totals"]["taxable_value"] == "25.00"
    assert record["tables"][0]["rows"][0]["Comment"] == "retain me"
    assert record["status"] == "needs_review"


def test_large_group_within_row_limit_remains_readable_after_storage(client, upload):
    contents = b"Invoice No,Description,Amount\n" + b"A1,Item,1\n" * 2000
    response = upload("large-group.csv", contents)
    assert response.status_code == 201, response.text
    record = response.json()
    assert len(record["invoices"][0]["line_items"]) == 2000
    assert client.get(f"/api/documents/{record['id']}").status_code == 200


def test_transaction_rows_are_not_silently_merged(upload):
    response = upload(
        "transactions.csv",
        b"Date,Description,Amount\n15/01/2026,Rent,10000\n16/01/2026,Deposit,5000\n",
    )
    assert response.status_code == 201, response.text
    records = response.json()["invoices"]
    assert len(records) == 2
    assert [record["document_type"] for record in records] == ["transaction", "transaction"]
    assert [record["totals"]["grand_total"] for record in records] == ["10000", "5000"]
    assert records[0]["invoice_number"] is None


def test_blank_invoice_number_continuation_and_conflicting_totals_flagged(upload):
    response = upload(
        "continuation.csv",
        b"Invoice No,Description,Taxable Value,Grand Total\nA1,Widgets,100,118\n,More widgets,200,236\n",
    )
    record = response.json()
    assert len(record["invoices"]) == 1
    assert len(record["invoices"][0]["line_items"]) == 2
    warnings = record["extraction_warnings"]
    assert any("continuation" in w for w in warnings)
    assert any("conflicting repeated" in w for w in warnings)
    assert record["status"] != "validated"


def test_excel_formulas_are_not_executed_or_silently_lost(upload):
    workbook = Workbook()
    workbook.active.append(["Invoice No", "Description", "Taxable Value", "Grand Total"])
    workbook.active.append(["A1", "Widgets", "=SUM(1,2)", "3"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    record = upload("formulas.xlsx", buffer.getvalue()).json()
    assert any("formula not evaluated" in w for w in record["extraction_warnings"])
    assert record["tables"][0]["rows"][0]["Taxable Value"] == "=SUM(1,2)"
    assert record["invoices"][0]["totals"]["taxable_value"] is None


def test_csv_export_neutralizes_formula_injection(client, upload):
    record = upload("injection.csv", b"Invoice No,Description,Amount\n=1+1,@SUM(A1),5\n").json()
    exported = client.get(f"/api/documents/{record['id']}/export?format=csv")
    rows = list(csv.DictReader(io.StringIO(exported.text.lstrip("\ufeff"))))
    # Formula-looking source cells are excluded from field mapping; source tables retain them.
    assert rows[0]["item_description"] == "'@SUM(A1)"
    assert record["tables"][0]["rows"][0]["Invoice No"] == "=1+1"


def test_schema_rejects_invalid_review_payload_and_keeps_saved_record(client, upload):
    record = upload().json()
    url = f"/api/documents/{record['id']}"
    bad = json.loads(json.dumps(record["invoices"]))
    bad[0]["totals"]["grand_total"] = "NaN"
    assert client.put(url, json={"invoices": bad}).status_code == 422
    assert client.get(url).json() == record
    assert client.put(url, json={"invoices": []}).status_code == 422


def test_review_cannot_forge_extraction_provenance(client, upload):
    record = upload("sample-invoice.pdf").json()
    record["invoices"][0]["extraction_method"] = "tabular"
    record["invoices"][0]["confidence"] = 1
    updated = client.put(
        f"/api/documents/{record['id']}",
        json={"invoices": record["invoices"], "reviewer_confirmed": False},
    ).json()
    assert updated["status"] == "needs_review"
    assert updated["invoices"][0]["extraction_method"] == "pdf_text"
    assert updated["invoices"][0]["confidence"] is None
