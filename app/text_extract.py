"""Evidence-first fallback parser for labeled invoices and common item tables.

It deliberately leaves ambiguous/unrecognized fields null. Vision extraction can
handle more layouts; this parser never equates OCR text with a verified record.
"""

import re

from .models import Invoice, LineItem
from .normalize import ALIASES, HEADER_MAP, header, iso_date, number

GST_PATTERN = r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b"
MONEY_PATTERN = r"[-(]?(?:₹\s*|INR\s*|Rs\.?\s*)?[\d,]+(?:\.\d+)?\)?"


def _labeled(lines, labels):
    pattern = re.compile(
        r"^\s*(?:" + "|".join(labels) + r")\s*(?:[:#=]|\s+-\s+)?\s+(.+?)\s*$", re.I
    )
    compact = re.compile(r"^\s*(?:" + "|".join(labels) + r")\s*[:#=]\s*(.+?)\s*$", re.I)
    for line in lines:
        match = compact.match(line) or pattern.match(line)
        if match:
            return match.group(1).strip(), line
    return None, None


def table_header(line):
    cells = [cell.strip() for cell in re.split(r"\s*\|\s*|\t|\s{2,}", line.strip()) if cell.strip()]
    keys = [HEADER_MAP.get(header(cell)) for cell in cells]
    if "description" in keys and sum(k is not None for k in keys) >= 3 and all(keys):
        return keys
    # Native PDFs often collapse horizontal gaps. Recognize longest header phrases.
    possible = {}
    for key in LineItem.model_fields:
        for alias in ALIASES.get(key, [key]):
            possible[alias.lower()] = key
    pattern = (
        r"(?<!\w)("
        + "|".join(re.escape(s) for s in sorted(possible, key=len, reverse=True))
        + r")(?!\w)"
    )
    matches = list(re.finditer(pattern, line, re.I))
    if re.sub(pattern, "", line, flags=re.I).strip(" |\t"):
        return None
    keys = [possible[m.group(1).lower()] for m in matches]
    return (
        keys if len(keys) >= 3 and "description" in keys and len(keys) == len(set(keys)) else None
    )


def parse_text(raw: str, method: str, confidence: float | None = None):
    invoice = Invoice(extraction_method=method, confidence=confidence)
    warnings = []
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    metadata_lines = [line.replace(" | ", "  ") for line in lines]
    for field, labels in {
        "invoice_number": [r"invoice\s*(?:no\.?|number|#)", r"inv\.?\s*no\.?", r"bill\s*no\.?"],
        "invoice_date": [r"invoice\s*date", r"date", r"bill\s*date"],
        "place_of_supply": [r"place\s*of\s*supply", r"supply\s*state"],
    }.items():
        value, evidence = _labeled(metadata_lines, labels)
        if value:
            # A second field on the same line must not become part of a field value.
            value = re.split(
                r"\s{2,}|\s+(?=(?:Invoice Date|Date|GSTIN)\s*[:#])", value, maxsplit=1, flags=re.I
            )[0]
            setattr(invoice, field, iso_date(value) if field == "invoice_date" else value)
            invoice.field_evidence[field] = evidence
    if re.search(r"\bcredit\s+note\b", raw, re.I):
        invoice.document_type = "credit_note"
    elif re.search(r"\bdebit\s+note\b", raw, re.I):
        invoice.document_type = "debit_note"
    for party_name, labels in {
        "supplier": ["supplier", "seller", "vendor", "from"],
        "buyer": ["buyer", "customer", "bill to", "billed to", "recipient"],
    }.items():
        party = getattr(invoice, party_name)
        value, evidence = _labeled(
            metadata_lines,
            [rf"{label}(?:\s*name)?(?!\s*(?:GSTIN|GST|address)\b)" for label in labels],
        )
        if value:
            party.name = re.split(r"\s{2,}|\s+GSTIN", value, flags=re.I)[0]
            invoice.field_evidence[f"{party_name}.name"] = evidence
        value, evidence = _labeled(
            metadata_lines, [rf"{label}\s*(?:GSTIN|GST\s*(?:no\.?)?)" for label in labels]
        )
        if value:
            match = re.search(r"\b[A-Z0-9]{15}\b", value.upper())
            party.gstin = match.group() if match else value.strip().upper()
            invoice.field_evidence[f"{party_name}.gstin"] = evidence
        value, evidence = _labeled(metadata_lines, [rf"{label}\s*address" for label in labels])
        if value:
            party.address = value
            invoice.field_evidence[f"{party_name}.address"] = evidence
    value, evidence = _labeled(metadata_lines, ["currency"])
    if value:
        invoice.currency = value.upper()
        invoice.field_evidence["currency"] = evidence
    # Generic GSTIN labels are assigned only when their surrounding party block is explicit.
    role = None
    for line in metadata_lines:
        if re.match(r"^(supplier|seller|vendor|from)\s*[:|]", line, re.I):
            role = "supplier"
        elif re.match(r"^(buyer|customer|bill\s*to|recipient)\s*[:|]", line, re.I):
            role = "buyer"
        match = re.search(GST_PATTERN, line.upper())
        if role and match and not getattr(invoice, role).gstin:
            getattr(invoice, role).gstin = match.group()
            invoice.field_evidence[f"{role}.gstin"] = line
    for field, labels in {
        "taxable_value": [
            "total taxable value",
            "total taxable amount",
            "taxable value",
            "taxable amount",
            "subtotal",
            "sub total",
        ],
        "cgst_amount": ["total cgst", "cgst(?: amount)?(?:\\s*@?\\s*[\\d.]+\\s*%)?"],
        "sgst_amount": ["total sgst", "(?:sgst|utgst)(?: amount)?(?:\\s*@?\\s*[\\d.]+\\s*%)?"],
        "igst_amount": ["total igst", "igst(?: amount)?(?:\\s*@?\\s*[\\d.]+\\s*%)?"],
        "cess_amount": ["cess(?: amount)?"],
        "discount": ["total discount", "discount"],
        "round_off": ["round off", "rounding"],
        "grand_total": [
            "grand total",
            "invoice total",
            "invoice amount",
            "net payable",
            "amount payable",
            "total amount",
            "total",
        ],
    }.items():
        value, evidence = _labeled(metadata_lines, labels)
        if value:
            parsed = number(value)
            if parsed is None:
                warnings.append(f"Could not unambiguously read {field}: {value}")
            setattr(invoice.totals, field, parsed)
            invoice.field_evidence[f"totals.{field}"] = evidence
    value, evidence = _labeled(metadata_lines, ["reverse charge", "rcm"])
    if value:
        invoice.reverse_charge = {"yes": True, "no": False, "true": True, "false": False}.get(
            value.lower()
        )
    columns = None
    for line in lines:
        candidate = table_header(line)
        if candidate:
            columns = candidate
            continue
        if not columns:
            continue
        if re.match(
            r"^(?:grand total|subtotal|sub total|taxable (?:value|amount)|total|cgst|sgst|igst|cess|round off|bank|terms|amount in words)\b",
            line,
            re.I,
        ):
            columns = None
            continue
        cells = [cell.strip() for cell in re.split(r"\s*\|\s*|\t|\s{2,}", line) if cell.strip()]
        if len(cells) != len(columns) and columns[0] == "description":
            cells = line.rsplit(None, len(columns) - 1)
        if len(cells) != len(columns):
            warnings.append(f"Unparsed possible item row: {line[:180]}")
            continue
        mapped = {}
        failed = False
        for key, value in zip(columns, cells):
            mapped[key] = value if key in {"description", "hsn_sac", "unit"} else number(value)
            if mapped[key] is None:
                failed = True
        if failed:
            warnings.append(f"Ambiguous item row left for review: {line[:180]}")
            continue
        invoice.field_evidence[f"line_items.{len(invoice.line_items)}"] = line
        invoice.line_items.append(LineItem(**mapped))
    invoice_labels = [r"invoice\s*(?:no\.?|number|#)", r"inv\.?\s*no\.?", r"bill\s*no\.?"]
    identities = {_labeled([line], invoice_labels)[0] for line in metadata_lines} - {None}
    if len(identities) > 1:
        warnings.append(
            "Multiple invoice numbers on one page: fallback extraction may combine sections. Use vision or split/correct the records before export."
        )
    if not invoice.line_items:
        warnings.append(
            "No recognizable item table. Use the JSON review editor or enable local vision for this layout."
        )
    if not invoice.supplier.gstin and re.search(GST_PATTERN, raw.upper()):
        warnings.append("GSTIN present but supplier/buyer role could not be safely determined.")
    return invoice, warnings
