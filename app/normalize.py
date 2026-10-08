"""Conservative normalization shared by tabular and OCR extraction."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    value = str(value).strip()
    return value if value and value.lower() not in {"null", "none", "nan", "n/a", "-"} else None


def number(value) -> Decimal | None:
    value = text(value)
    if value is None:
        return None
    value = re.sub(r"(?i)\b(?:INR|RS)\.?\s*|[₹%,\s]", "", value)
    if value.startswith("(") and value.endswith(")"):
        value = "-" + value[1:-1]
    try:
        result = Decimal(value)
        if (
            not result.is_finite()
            or abs(result) > Decimal("1e14")
            or result.as_tuple().exponent < -8
        ):
            return None
        return result
    except InvalidOperation:
        return None


def iso_date(value) -> str | None:
    value = text(value)
    if value is None:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d/%m/%y",
        "%d-%m-%y",
        "%d %b %Y",
        "%d-%b-%Y",
        "%d %B %Y",
    ):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return value  # Retain unrecognized values; validation reports them.


def header(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


ALIASES = {
    "invoice_number": [
        "invoice number",
        "invoice no",
        "invoice #",
        "inv no",
        "bill no",
        "voucher no",
        "invoice id",
    ],
    "invoice_date": ["invoice date", "bill date", "date", "transaction date"],
    "supplier_name": ["supplier name", "vendor name", "seller name", "supplier", "vendor"],
    "supplier_gstin": [
        "supplier gstin",
        "vendor gstin",
        "seller gstin",
        "gstin",
        "gst no",
        "supplier gst",
    ],
    "supplier_address": ["supplier address", "vendor address"],
    "buyer_name": ["buyer name", "customer name", "billed to", "buyer", "customer"],
    "buyer_gstin": ["buyer gstin", "customer gstin", "recipient gstin", "buyer gst"],
    "buyer_address": ["buyer address", "customer address"],
    "place_of_supply": ["place of supply", "supply state", "pos"],
    "description": [
        "description",
        "item",
        "item description",
        "item name",
        "product",
        "particulars",
        "product name",
        "service",
    ],
    "hsn_sac": ["hsn", "sac", "hsn/sac", "hsn code", "hsn sac code"],
    "quantity": ["quantity", "qty"],
    "unit": ["unit", "uom"],
    "unit_price": ["unit price", "price", "rate", "unit rate"],
    "discount": ["discount", "discount amount"],
    "taxable_value": ["taxable value", "taxable amount", "net amount", "base amount"],
    "gst_rate": ["gst rate", "gst %", "tax rate", "tax %"],
    "cgst_rate": ["cgst rate", "cgst %"],
    "sgst_rate": ["sgst rate", "sgst %"],
    "igst_rate": ["igst rate", "igst %"],
    "cgst_amount": ["cgst", "cgst amount"],
    "sgst_amount": ["sgst", "sgst amount", "utgst", "utgst amount"],
    "igst_amount": ["igst", "igst amount"],
    "cess_amount": ["cess", "cess amount"],
    "total": ["line total", "item total", "amount", "total"],
    "grand_total": [
        "grand total",
        "invoice total",
        "invoice amount",
        "bill amount",
        "total amount",
    ],
    "round_off": ["round off", "rounding"],
    "currency": ["currency"],
    "document_type": ["document type", "voucher type"],
    "reverse_charge": ["reverse charge", "rcm"],
    "irn": ["irn", "invoice reference number", "invoice reference"],
    "acknowledgement_number": [
        "acknowledgement number",
        "acknowledgment number",
        "ack no",
        "acknowledgement no",
        "acknowledgment no",
    ],
    "acknowledgement_date": [
        "acknowledgement date",
        "acknowledgment date",
        "ack date",
    ],
    "eway_bill_number": [
        "eway bill number",
        "e-way bill number",
        "eway bill no",
        "e-way bill no",
        "eway no",
    ],
    "vehicle_number": ["vehicle number", "vehicle no", "vehicle registration"],
    "transport_mode": ["transport mode", "mode of transport"],
}
HEADER_MAP = {header(alias): key for key, aliases in ALIASES.items() for alias in [key, *aliases]}
