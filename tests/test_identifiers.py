from app.identifiers import qr_candidate, qr_fields
from app.text_extract import parse_text


def test_labeled_gst_and_transport_identifiers_are_structured_and_evidenced():
    raw = (
        "IRN: "
        + "a" * 64
        + "\nAcknowledgement Number: ACK123\n"
        "Acknowledgement Date: 15/01/2026\n"
        "E-Way Bill Number: 123456789012\n"
        "Vehicle Number: MH12AB1234\n"
        "Transport Mode: Road"
    )

    invoice, warnings = parse_text(raw, "pdf_text")

    assert invoice.identifiers.model_dump() == {
        "irn": "a" * 64,
        "acknowledgement_number": "ACK123",
        "acknowledgement_date": "2026-01-15",
        "eway_bill_number": "123456789012",
        "vehicle_number": "MH12AB1234",
        "transport_mode": "Road",
    }
    assert invoice.field_evidence["identifiers.irn"].startswith("IRN:")
    assert not any("identifier" in warning.lower() for warning in warnings)


def test_identifier_aliases_and_line_item_provenance_survive_tabular_upload(upload):
    response = upload(
        "identifiers.csv",
        (
            b"Invoice No,Invoice Date,Description,Qty,Unit Price,Grand Total,IRN,E-Way Bill Number\n"
            b"A1,15/01/2026,Widgets,2,10,20," + b"a" * 64 + b",123456789012\n"
        ),
    )
    assert response.status_code == 201, response.text
    invoice = response.json()["invoices"][0]
    assert invoice["identifiers"]["irn"] == "a" * 64
    assert invoice["identifiers"]["eway_bill_number"] == "123456789012"
    assert invoice["line_items"][0]["provenance"]["extraction_method"] == "tabular"
    assert invoice["line_items"][0]["provenance"]["source_text"] == "CSV row 2"


def test_common_einvoice_qr_keys_become_a_reviewable_source_candidate():
    payload = (
        '{"SellerGstin":"27AAPFU0939F1ZV","DocNo":"A-1",'
        '"DocDt":"15/01/2026","TotInvVal":"118.00",'
        '"Irn":"' + "b" * 64 + '"}'
    )

    fields = qr_fields(payload)
    candidate = qr_candidate(payload, fields)

    assert fields == {
        "supplier.gstin": "27AAPFU0939F1ZV",
        "invoice_number": "A-1",
        "invoice_date": "15/01/2026",
        "totals.grand_total": "118.00",
        "identifiers.irn": "b" * 64,
    }
    assert candidate.supplier.gstin == "27AAPFU0939F1ZV"
    assert candidate.invoice_date == "2026-01-15"
    assert str(candidate.totals.grand_total) == "118.00"
    assert candidate.extraction_method == "qr"
