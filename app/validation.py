"""Deterministic consistency checks, not tax advice or GST registration verification."""

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .models import Document, Invoice, Issue

TOLERANCE = Decimal("0.05")
ZERO = Decimal("0")
TAX_KEYS = ("cgst_amount", "sgst_amount", "igst_amount", "cess_amount")
STATES = {
    "jammu and kashmir": "01",
    "himachal pradesh": "02",
    "punjab": "03",
    "chandigarh": "04",
    "uttarakhand": "05",
    "haryana": "06",
    "delhi": "07",
    "rajasthan": "08",
    "uttar pradesh": "09",
    "bihar": "10",
    "sikkim": "11",
    "arunachal pradesh": "12",
    "nagaland": "13",
    "manipur": "14",
    "mizoram": "15",
    "tripura": "16",
    "meghalaya": "17",
    "assam": "18",
    "west bengal": "19",
    "jharkhand": "20",
    "odisha": "21",
    "chhattisgarh": "22",
    "madhya pradesh": "23",
    "gujarat": "24",
    "dadra and nagar haveli and daman and diu": "26",
    "maharashtra": "27",
    "andhra pradesh": "37",
    "karnataka": "29",
    "goa": "30",
    "lakshadweep": "31",
    "kerala": "32",
    "tamil nadu": "33",
    "puducherry": "34",
    "andaman and nicobar islands": "35",
    "telangana": "36",
    "ladakh": "38",
}


def gst_check_digit(prefix: str) -> str:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    total = 0
    factor = 2
    for char in reversed(prefix.upper()):
        value = alphabet.index(char) * factor
        total += value // 36 + value % 36
        factor = 1 if factor == 2 else 2
    return alphabet[(36 - total % 36) % 36]


def valid_gstin(value: str) -> bool:
    value = value.upper()
    if not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", value):
        return False
    if value[:2] not in {*STATES.values(), "25", "28", "97", "99"}:
        return False
    return gst_check_digit(value[:14]) == value[-1]


def state_code(value: str | None) -> str | None:
    if not value:
        return None
    match = re.match(r"^(\d{2})(?:\D|$)", value.strip())
    if match:
        return match[1] if match[1] in {*STATES.values(), "25", "28", "97", "99"} else None
    return STATES.get(value.strip().lower())


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validate_invoice(invoice: Invoice, index: int) -> list[Issue]:
    issues = []

    def add(code, field, message, severity="warning"):
        issues.append(
            Issue(code=code, field=field, message=message, severity=severity, invoice_index=index)
        )

    def compare(actual, expected, field, code="arithmetic_mismatch"):
        if actual is not None and abs(actual - expected) > TOLERANCE:
            add(
                code,
                field,
                f"Recorded {actual}; expected {money(expected)} (tolerance ₹0.05).",
                "error",
            )

    for key in ("invoice_number", "invoice_date"):
        if not getattr(invoice, key):
            add("missing_required", key, f"Missing {key.replace('_', ' ')}; verify the source.")
    if invoice.invoice_date:
        try:
            parsed = date.fromisoformat(invoice.invoice_date)
            if parsed > date.today():
                add("future_date", "invoice_date", "Invoice date is in the future.")
        except ValueError:
            add(
                "invalid_date",
                "invoice_date",
                "Date must be a real ISO date (YYYY-MM-DD).",
                "error",
            )
    if not invoice.supplier.name:
        add("missing_required", "supplier.name", "Supplier name is missing.")
    if invoice.identifiers.irn and not re.fullmatch(r"[0-9A-Fa-f]{64}", invoice.identifiers.irn):
        add(
            "invalid_identifier_format",
            "identifiers.irn",
            "IRN is not a 64-character hexadecimal value; compare it with the source.",
        )
    if invoice.identifiers.eway_bill_number and not re.fullmatch(
        r"\d{12}", invoice.identifiers.eway_bill_number
    ):
        add(
            "invalid_identifier_format",
            "identifiers.eway_bill_number",
            "E-way bill number is not a 12-digit value; compare it with the source.",
        )
    for name in ("supplier", "buyer"):
        party = getattr(invoice, name)
        if party.gstin and not valid_gstin(party.gstin):
            add(
                "invalid_gstin",
                f"{name}.gstin",
                "GSTIN format, state code, or checksum is invalid.",
                "error",
            )
        elif name == "supplier" and not party.gstin:
            add(
                "missing_gstin",
                "supplier.gstin",
                "Supplier GSTIN is missing; check registration/tax applicability.",
            )
    if invoice.currency != "INR":
        add(
            "unsupported_currency",
            "currency",
            "GST checks assume INR; foreign currency needs manual review.",
        )
    if not invoice.line_items:
        add("missing_line_items", "line_items", "No item rows were reliably extracted.")
    totals = invoice.totals
    if (
        invoice.document_type == "invoice"
        and totals.grand_total is not None
        and totals.grand_total < ZERO
    ):
        add(
            "negative_invoice_total",
            "totals.grand_total",
            "Negative invoice total; check whether this is a credit note or reversal.",
        )
    if totals.grand_total is None:
        add("missing_required", "totals.grand_total", "Grand total is missing.")
    if totals.taxable_value is None:
        add("missing_required", "totals.taxable_value", "Taxable value is missing.")
    if totals.taxable_value is not None and totals.grand_total is not None:
        if any(getattr(totals, k) is not None for k in TAX_KEYS):
            expected = totals.taxable_value + sum(
                (getattr(totals, k) or ZERO for k in TAX_KEYS), ZERO
            )
            compare(totals.grand_total, expected + (totals.round_off or ZERO), "totals.grand_total")
        else:
            add(
                "missing_tax_breakdown",
                "totals",
                "No explicit tax breakdown; zero tax was not assumed.",
            )
    for key in TAX_KEYS:
        values = [getattr(item, key) for item in invoice.line_items]
        if values and all(v is not None for v in values):
            compare(getattr(totals, key), sum(values, ZERO), f"totals.{key}", "line_sum_mismatch")
        elif values and any(v is not None for v in values):
            add(
                "incomplete_line_tax",
                f"line_items.{key}",
                "Some item tax amounts are missing; tax sum cannot be reconciled.",
            )
    values = [item.taxable_value for item in invoice.line_items]
    if values and all(v is not None for v in values):
        compare(
            totals.taxable_value, sum(values, ZERO), "totals.taxable_value", "line_sum_mismatch"
        )
    for n, item in enumerate(invoice.line_items):
        field = f"line_items.{n}"
        if not item.description:
            add("missing_description", field + ".description", "Item description is missing.")
        if item.hsn_sac and not re.fullmatch(r"\d{4}|\d{6}|\d{8}", item.hsn_sac):
            add(
                "invalid_hsn",
                field + ".hsn_sac",
                "HSN/SAC should contain 4, 6, or 8 digits; check source.",
            )
        if item.quantity is not None and item.quantity <= ZERO:
            add(
                "nonpositive_quantity", field + ".quantity", "Nonpositive quantity requires review."
            )
        if item.taxable_value is None:
            add("missing_taxable_value", field + ".taxable_value", "Item taxable value is missing.")
        if item.quantity is not None and item.unit_price is not None:
            compare(
                item.taxable_value,
                item.quantity * item.unit_price - (item.discount or ZERO),
                field + ".taxable_value",
            )
        if item.taxable_value is not None:
            for tax in ("cgst", "sgst", "igst"):
                rate, amount = getattr(item, f"{tax}_rate"), getattr(item, f"{tax}_amount")
                if rate is not None:
                    if rate < ZERO or rate > 100:
                        add(
                            "invalid_tax_rate",
                            field + f".{tax}_rate",
                            "Tax rate must be between 0 and 100.",
                            "error",
                        )
                    compare(
                        amount,
                        money(item.taxable_value * rate / 100),
                        field + f".{tax}_amount",
                        "tax_mismatch",
                    )
            if item.gst_rate is not None:
                if not ZERO <= item.gst_rate <= 100:
                    add(
                        "invalid_tax_rate",
                        field + ".gst_rate",
                        "GST rate must be between 0 and 100.",
                        "error",
                    )
                tax_amounts = [item.cgst_amount, item.sgst_amount, item.igst_amount]
                if any(v is not None for v in tax_amounts):
                    compare(
                        sum((v or ZERO for v in tax_amounts), ZERO),
                        money(item.taxable_value * item.gst_rate / 100),
                        field + ".gst_rate",
                        "tax_mismatch",
                    )
            if item.total is not None and any(getattr(item, key) is not None for key in TAX_KEYS):
                compare(
                    item.total,
                    item.taxable_value
                    + sum((getattr(item, key) or ZERO for key in TAX_KEYS), ZERO),
                    field + ".total",
                )
        if item.igst_amount and (item.cgst_amount or item.sgst_amount):
            add("mixed_tax_regime", field, "A line has both IGST and CGST/SGST.", "error")
    if totals.igst_amount and (totals.cgst_amount or totals.sgst_amount):
        add(
            "mixed_tax_regime",
            "totals",
            "Invoice has both IGST and CGST/SGST; verify mixed supplies.",
        )
    if (totals.cgst_amount and totals.sgst_amount is None) or (
        totals.sgst_amount and totals.cgst_amount is None
    ):
        add(
            "incomplete_tax_split",
            "totals",
            "Only one of CGST and SGST/UTGST was provided; the other was not assumed to be zero.",
        )
    if totals.cgst_amount is not None and totals.sgst_amount is not None:
        compare(totals.cgst_amount, totals.sgst_amount, "totals.cgst_amount", "split_tax_mismatch")
    source_state = invoice.supplier.gstin[:2] if invoice.supplier.gstin else None
    supply_state = state_code(invoice.place_of_supply)
    if not supply_state:
        add(
            "unknown_place_of_supply",
            "place_of_supply",
            "Cannot determine place of supply; tax regime not verified.",
        )
    elif source_state:
        if source_state == supply_state and totals.igst_amount:
            add(
                "tax_regime_mismatch",
                "totals.igst_amount",
                "IGST on same-state supply needs review (e.g. SEZ exceptions).",
            )
        if source_state != supply_state and (totals.cgst_amount or totals.sgst_amount):
            add("tax_regime_mismatch", "totals", "CGST/SGST on interstate supply needs review.")
    if invoice.reverse_charge:
        add(
            "reverse_charge", "reverse_charge", "Reverse-charge invoice requires accounting review."
        )
    return issues


def validate_document(document: Document) -> Document:
    issues = []
    records_to_check = [*document.invoices, *document.extraction_snapshot]
    if not records_to_check or (
        not any(
            invoice.invoice_number
            or invoice.supplier.name
            or invoice.line_items
            or invoice.totals.grand_total is not None
            for invoice in records_to_check
        )
        and not document.raw_text.strip()
    ):
        issues.append(
            Issue(
                severity="error",
                code="no_records",
                field="invoices",
                message="No usable records extracted.",
            )
        )
    seen = set()
    for index, invoice in enumerate(document.invoices):
        issues.extend(validate_invoice(invoice, index))
        identity = (invoice.supplier.gstin, invoice.invoice_number, invoice.invoice_date)
        if invoice.invoice_number and identity in seen:
            issues.append(
                Issue(
                    severity="warning",
                    code="duplicate_invoice",
                    field="invoice_number",
                    message="Duplicate invoice identity within this document.",
                    invoice_index=index,
                )
            )
        seen.add(identity)
        if not document.review.confirmed and (invoice.extraction_method not in {"tabular"}):
            issues.append(
                Issue(
                    severity="warning",
                    code="extraction_review",
                    field="invoices",
                    message="Document extraction must be compared with the source by a reviewer.",
                    invoice_index=index,
                )
            )
    if document.extraction_warnings and not document.review.confirmed:
        issues.append(
            Issue(
                severity="warning",
                code="source_review",
                field="extraction_warnings",
                message="Review the extraction warnings and confirm against the source.",
            )
        )
    document.issues = issues
    document.status = (
        "invalid"
        if any(i.severity == "error" for i in issues)
        else ("needs_review" if any(i.severity == "warning" for i in issues) else "validated")
    )
    return document
