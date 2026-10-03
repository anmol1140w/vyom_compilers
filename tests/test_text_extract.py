from app.text_extract import parse_text


def test_supplier_gstin_is_not_misclassified_as_supplier_name():
    record, _ = parse_text(
        "Supplier GSTIN: 27AAPFU0939F1ZV\nInvoice No: A1\nGrand Total: 118", "pdf_text"
    )
    assert record.supplier.name is None
    assert record.supplier.gstin == "27AAPFU0939F1ZV"


def test_addresses_and_currency_remain_explicit_source_values():
    record, _ = parse_text(
        "Supplier: Example Company\nSupplier Address: Pune, Maharashtra\nBuyer: Demo Customer\nBuyer Address: Bengaluru\nCurrency: USD\nInvoice No: A1",
        "pdf_text",
    )
    assert record.supplier.name == "Example Company"
    assert record.supplier.address == "Pune, Maharashtra"
    assert record.buyer.address == "Bengaluru"
    assert record.currency == "USD"


def test_ambiguous_table_cells_are_not_numeric_guesses():
    source = (
        "Description  Qty  Unit Price  Taxable Value\nOffice chair  2  50O  1000\nGrand Total: 1180"
    )
    record, warnings = parse_text(source, "ocr", 0.91)
    assert record.line_items == []
    assert any("Ambiguous item row" in warning for warning in warnings)
    assert record.totals.taxable_value is None


def test_multiple_invoice_sections_are_not_silently_presented_as_complete():
    source = "Invoice No: A1\nGrand Total: 100\nInvoice No: A2\nGrand Total: 200"
    _, warnings = parse_text(source, "pdf_text")
    assert any("Multiple invoice numbers" in warning for warning in warnings)


def test_native_pdf_collapsed_table_spacing():
    source = "Description HSN Qty Unit Price Taxable Value CGST SGST Total\nOffice chairs 9403 2 5000.00 10000.00 900.00 900.00 11800.00\nGrand Total: 11800.00"
    record, _ = parse_text(source, "pdf_text")
    assert len(record.line_items) == 1
    assert record.line_items[0].description == "Office chairs"
    assert str(record.line_items[0].taxable_value) == "10000.00"
