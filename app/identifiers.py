"""Conservative GST document identifier and optional QR extraction helpers."""

from __future__ import annotations

import importlib.util
import json
import re

from PIL import Image

from .models import (
    DocumentIdentifiers,
    Invoice,
    Party,
    SourceObservation,
    Totals,
)
from .normalize import iso_date, number


def _labeled(raw: str, labels: str, value_pattern: str) -> tuple[str | None, str | None]:
    pattern = re.compile(
        rf"(?im)^\s*(?:{labels})\s*(?:[:#=\-]|\s+)\s*({value_pattern})\s*$"
    )
    match = pattern.search(raw)
    return (match.group(1).strip(), match.group(0).strip()) if match else (None, None)


def extract_identifier_fields(
    raw: str,
) -> tuple[DocumentIdentifiers, dict[str, str], list[str]]:
    """Extract labelled identifiers while preserving unrecognized values for review."""

    identifiers = DocumentIdentifiers()
    evidence: dict[str, str] = {}
    warnings: list[str] = []
    fields = {
        "irn": (
            r"irn|invoice\s+reference(?:\s+number)?",
            r"[A-Za-z0-9]{32,128}",
        ),
        "acknowledgement_number": (
            r"ack(?:nowledg(?:e?ment)?)?(?:\s+number|\s+no\.?)?",
            r"[A-Za-z0-9\-/]{3,100}",
        ),
        "acknowledgement_date": (
            r"ack(?:nowledg(?:e?ment)?)?\s+date|ack\s+dt",
            r"[^\r\n]+",
        ),
        "eway_bill_number": (
            r"e[-\s]?way\s+bill(?:\s+number|\s+no\.?)?|eway(?:\s+number|\s+no\.?)?",
            r"[A-Za-z0-9\-/]{6,100}",
        ),
        "vehicle_number": (
            r"vehicle(?:\s+registration)?(?:\s+number|\s+no\.?)?",
            r"[A-Za-z0-9\- ]{4,50}",
        ),
        "transport_mode": (r"transport\s+mode|mode\s+of\s+transport", r"[^\r\n]+"),
    }
    for field, (labels, value_pattern) in fields.items():
        value, line = _labeled(raw, labels, value_pattern)
        if value is None:
            continue
        if field == "acknowledgement_date":
            value = iso_date(value)
        elif field == "vehicle_number":
            value = " ".join(value.upper().split())
        elif field in {"irn", "eway_bill_number"}:
            value = value.strip()
        setattr(identifiers, field, value)
        evidence[f"identifiers.{field}"] = line or value
    return identifiers, evidence, warnings


def _normalized_qr_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.casefold())


def qr_fields(payload: str) -> dict[str, str]:
    """Read common e-invoice QR key names without treating QR as authoritative."""

    values: dict[str, str] = {}
    try:
        parsed = json.loads(payload)
        pairs = parsed.items() if isinstance(parsed, dict) else []
    except (TypeError, json.JSONDecodeError):
        pairs = []
    if not pairs:
        pairs = re.findall(r"([A-Za-z][A-Za-z _-]{1,40})\s*[:=|]\s*([^|;\n]+)", payload)
    aliases = {
        "irn": "identifiers.irn",
        "invoicereferencenumber": "identifiers.irn",
        "docno": "invoice_number",
        "documentnumber": "invoice_number",
        "invoicenumber": "invoice_number",
        "docdate": "invoice_date",
        "docdt": "invoice_date",
        "invoicedate": "invoice_date",
        "sellergstin": "supplier.gstin",
        "suppliergstin": "supplier.gstin",
        "buyergstin": "buyer.gstin",
        "recipientgstin": "buyer.gstin",
        "totinvval": "totals.grand_total",
        "totalinvoicevalue": "totals.grand_total",
        "grandtotal": "totals.grand_total",
        "ewaybillnumber": "identifiers.eway_bill_number",
        "ewaybillno": "identifiers.eway_bill_number",
    }
    for key, value in pairs:
        target = aliases.get(_normalized_qr_key(str(key)))
        if target and value is not None and str(value).strip():
            values[target] = str(value).strip()
    return values


def qr_candidate(payload: str, fields: dict[str, str]) -> Invoice:
    """Create a source candidate only; callers must compare it before using values."""

    invoice = Invoice(extraction_method="qr")
    for field, value in fields.items():
        invoice.field_evidence[field] = f"QR payload: {value}"
        if field == "invoice_number":
            invoice.invoice_number = value
        elif field == "invoice_date":
            invoice.invoice_date = iso_date(value)
        elif field == "supplier.gstin":
            invoice.supplier = Party(gstin=value.upper())
        elif field == "buyer.gstin":
            invoice.buyer = Party(gstin=value.upper())
        elif field == "totals.grand_total":
            invoice.totals = Totals(grand_total=number(value))
        elif field.startswith("identifiers."):
            setattr(invoice.identifiers, field.split(".", 1)[1], value)
    return invoice


def decode_qr(image: Image.Image, page_number: int) -> tuple[SourceObservation, Invoice] | None:
    """Decode one QR using an optional local OpenCV installation."""

    if importlib.util.find_spec("cv2") is None:
        return None
    try:
        import cv2
        import numpy as np

        working = image.convert("RGB")
        try:
            detector = cv2.QRCodeDetector()
            payload, _, _ = detector.detectAndDecode(np.asarray(working))
        finally:
            working.close()
    except Exception:
        return None
    payload = str(payload or "").strip()
    if not payload:
        return None
    fields = qr_fields(payload)
    observation = SourceObservation(
        source="qr",
        page_number=page_number,
        text=payload[:10000],
        metadata={key: value[:500] for key, value in fields.items()},
    )
    return observation, qr_candidate(payload, fields)
