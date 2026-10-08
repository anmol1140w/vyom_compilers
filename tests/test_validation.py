from decimal import Decimal

import pytest

from app.models import Invoice, LineItem, Party, Totals
from app.normalize import iso_date, number
from app.validation import gst_check_digit, valid_gstin, validate_invoice


def invoice():
    return Invoice(
        invoice_number="INV-1",
        invoice_date="2026-01-15",
        supplier=Party(name="Demo Supplier", gstin="27AAPFU0939F1ZV"),
        place_of_supply="Maharashtra",
        line_items=[
            LineItem(
                description="Office chairs",
                hsn_sac="9403",
                quantity="2",
                unit_price="5000",
                taxable_value="10000",
                gst_rate="18",
                cgst_rate="9",
                sgst_rate="9",
                cgst_amount="900",
                sgst_amount="900",
                total="11800",
            )
        ],
        totals=Totals(
            taxable_value="10000", cgst_amount="900", sgst_amount="900", grand_total="11800"
        ),
        extraction_method="tabular",
    )


def codes(record):
    return {issue.code for issue in validate_invoice(record, 0)}


def test_valid_record():
    assert validate_invoice(invoice(), 0) == []


@pytest.mark.parametrize(
    "gstin,valid",
    [
        ("27AAPFU0939F1ZV", True),
        ("27aapfu0939f1zv", True),
        ("27AAPFU0939F1Z0", False),
        ("00AAPFU0939F1ZV", False),
        ("garbage", False),
        ("27AAPFUO939F1ZV", False),
    ],
)
def test_gstin_format_state_and_checksum(gstin, valid):
    assert valid_gstin(gstin) is valid
    assert gst_check_digit("27AAPFU0939F1Z") == "V"


def test_bad_gstin_is_not_autocorrected():
    record = invoice()
    record.supplier.gstin = "27AAPFUO939F1ZV"
    assert "invalid_gstin" in codes(record)
    assert record.supplier.gstin == "27AAPFUO939F1ZV"


def test_decimal_reconciliation_and_tolerance():
    record = invoice()
    record.totals.grand_total = Decimal("11800.05")
    assert "arithmetic_mismatch" not in codes(record)
    record.totals.grand_total = Decimal("11800.06")
    assert "arithmetic_mismatch" in codes(record)
    record.totals.grand_total = Decimal("11801")
    record.totals.round_off = Decimal("1")
    assert "arithmetic_mismatch" not in codes(record)


def test_line_discount_not_double_subtracted_from_taxable_total():
    record = invoice()
    item = record.line_items[0]
    item.discount = Decimal("1000")
    item.taxable_value = Decimal("9000")
    item.cgst_amount = item.sgst_amount = Decimal("810")
    item.total = Decimal("10620")
    record.totals = Totals(
        taxable_value="9000",
        cgst_amount="810",
        sgst_amount="810",
        discount="1000",
        grand_total="10620",
    )
    assert validate_invoice(record, 0) == []


def test_line_tax_rate_and_total_mismatch():
    record = invoice()
    record.line_items[0].cgst_amount = Decimal("500")
    found = codes(record)
    assert {"tax_mismatch", "line_sum_mismatch", "arithmetic_mismatch"} <= found


def test_tax_regime_and_missing_values_are_flagged():
    record = invoice()
    record.place_of_supply = "Karnataka"
    assert "tax_regime_mismatch" in codes(record)
    record.totals.igst_amount = Decimal("1800")
    assert "mixed_tax_regime" in codes(record)
    record.invoice_date = "2026-02-30"
    assert "invalid_date" in codes(record)
    record.totals.grand_total = None
    assert "missing_required" in codes(record)


def test_incomplete_local_tax_split_is_not_assumed_zero():
    record = invoice()
    record.totals.sgst_amount = None
    record.totals.grand_total = Decimal("10900")
    assert "incomplete_tax_split" in codes(record)


def test_no_invented_zero_tax():
    record = invoice()
    record.totals.cgst_amount = record.totals.sgst_amount = None
    assert "missing_tax_breakdown" in codes(record)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("₹ 1,23,456.78", "123456.78"),
        ("Rs. 100.50", "100.50"),
        ("(50.00)", "-50.00"),
        ("18%", "18"),
        ("1O0", None),
        ("NaN", None),
        ("Infinity", None),
        ("-", None),
    ],
)
def test_conservative_numeric_normalization(value, expected):
    assert number(value) == (Decimal(expected) if expected is not None else None)


def test_dates_are_day_first_and_invalid_dates_remain_visible():
    assert iso_date("02/03/2026") == "2026-03-02"
    assert iso_date("31/02/2026") == "31/02/2026"


def test_gst_identifier_formats_are_checked_without_claiming_verification():
    record = invoice()
    record.identifiers.irn = "not-an-irn"
    record.identifiers.eway_bill_number = "123"

    assert "invalid_identifier_format" in codes(record)
