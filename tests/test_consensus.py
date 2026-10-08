from app.consensus import apply_consensus
from app.layout import infer_layout_regions
from app.models import Invoice, SourceObservation


def test_conflicting_critical_readings_are_retained_without_auto_selection():
    baseline = Invoice(
        invoice_number="A-100",
        extraction_method="ocr",
        field_evidence={"invoice_number": "Invoice No: A-100"},
    )
    vision = Invoice(
        invoice_number="A-1OO",
        extraction_method="local_vision",
        field_evidence={"invoice_number": "Invoice No: A-1OO"},
    )
    summary = apply_consensus(
        vision,
        [("ocr", baseline), ("vision", vision)],
        [SourceObservation(source="ocr", text="Invoice No: A-100")],
        page_number=1,
    )

    assert summary.status == "conflict"
    assert summary.conflicts == ["invoice_number"]
    assert vision.invoice_number is None
    provenance = vision.field_provenance["invoice_number"]
    assert provenance.status == "conflict"
    assert provenance.alternatives == ["A-100", "A-1OO"]
    assert {reading.source for reading in provenance.readings} == {"ocr", "vision"}


def test_layout_regions_label_native_text_and_keep_missing_coordinates():
    regions = infer_layout_regions(
        [
            SourceObservation(
                source="native_text",
                page_number=1,
                text=(
                    "TAX INVOICE\n"
                    "Supplier: Example Supplies\n"
                    "Description HSN Qty Unit Price Total\n"
                    "Grand Total: 100.00"
                ),
            )
        ]
    )

    assert {region.kind for region in regions} >= {"header", "supplier", "line_items", "totals"}
    assert all(region.bounding_box is None for region in regions)
    assert all(region.page_number == 1 for region in regions)
