"""Reusable source-reading comparison for critical invoice fields.

Consensus here means transparent comparison, not an automatic truth decision. When
independent sources disagree, the target value is cleared and the alternatives are
retained in provenance so a reviewer must resolve the conflict against the source.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from .models import (
    ConsensusSummary,
    FieldProvenance,
    FieldReading,
    Invoice,
    ObservationSource,
    SourceObservation,
)

CRITICAL_FIELDS = (
    "invoice_number",
    "invoice_date",
    "supplier.name",
    "supplier.gstin",
    "buyer.name",
    "buyer.gstin",
    "place_of_supply",
    "totals.taxable_value",
    "totals.cgst_amount",
    "totals.sgst_amount",
    "totals.igst_amount",
    "totals.cess_amount",
    "totals.grand_total",
    "identifiers.irn",
    "identifiers.acknowledgement_number",
    "identifiers.eway_bill_number",
)

METHOD_SOURCES: dict[str, ObservationSource] = {
    "ocr": "ocr",
    "pdf_text": "native_text",
    "local_vision": "vision",
    "tabular": "tabular",
}


def source_for_method(method: str) -> ObservationSource:
    return METHOD_SOURCES.get(method, "derived")


def _get_field(invoice: Invoice, path: str):
    value = invoice
    for part in path.split("."):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def _set_field(invoice: Invoice, path: str, value) -> None:
    parts = path.split(".")
    target = invoice
    for part in parts[:-1]:
        target = getattr(target, part)
    setattr(target, parts[-1], value)


def _value_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _comparison_key(value: str) -> str:
    compact = " ".join(value.split()).casefold()
    try:
        return str(Decimal(compact))
    except Exception:
        return compact


def _matching_observation(
    evidence: str | None, observations: list[SourceObservation]
) -> SourceObservation | None:
    if not evidence:
        return None
    normalized = " ".join(evidence.split()).casefold()
    for observation in observations:
        if observation.text is None or observation.bounding_box is None:
            continue
        candidate = " ".join(observation.text.split()).casefold()
        if normalized == candidate or normalized in candidate or candidate in normalized:
            return observation
    return None


def _reading(
    source: ObservationSource,
    invoice: Invoice,
    field: str,
    observations: list[SourceObservation],
    page_number: int | None,
) -> FieldReading | None:
    value = _value_text(_get_field(invoice, field))
    evidence = invoice.field_evidence.get(field)
    if value is None and not evidence:
        return None
    matched = _matching_observation(evidence, observations)
    return FieldReading(
        source=source,
        value=value,
        evidence=evidence,
        page_number=page_number or (matched.page_number if matched else None),
        bounding_box=matched.bounding_box if matched else None,
        recognition_score=matched.recognition_score if matched else None,
        preprocessing=matched.preprocessing if matched else None,
    )


def apply_consensus(
    target: Invoice,
    candidates: Iterable[tuple[ObservationSource, Invoice]],
    observations: list[SourceObservation],
    page_number: int | None = None,
) -> ConsensusSummary:
    """Attach readings and mark disagreements without selecting a winner."""

    candidate_list = list(candidates)
    sources = list(dict.fromkeys(source for source, _ in candidate_list))
    conflicts = []
    compared = 0
    with_readings = 0
    for field in CRITICAL_FIELDS:
        readings = [
            reading
            for source, invoice in candidate_list
            if (reading := _reading(source, invoice, field, observations, page_number)) is not None
        ]
        existing = target.field_provenance.get(field)
        if not readings and existing is None:
            continue
        with_readings += 1 if readings else 0
        values = [reading.value for reading in readings if reading.value is not None]
        unique_values: dict[str, str] = {}
        for value in values:
            unique_values.setdefault(_comparison_key(value), value)
        is_conflict = len(unique_values) > 1
        if len(values) >= 2:
            compared += 1
        alternatives = list(unique_values.values()) if is_conflict else []
        if is_conflict:
            conflicts.append(field)
            _set_field(target, field, None)
        target.field_provenance[field] = FieldProvenance(
            observations=existing.observations if existing else [],
            readings=readings,
            status="conflict" if is_conflict else existing.status if existing else "observed",
            confidence=existing.confidence if existing else None,
            alternatives=alternatives,
        )

    if conflicts:
        status = "conflict"
    elif compared:
        status = "agree"
    elif len(sources) <= 1:
        status = "single_source"
    else:
        status = "single_source"
    notes = [
        (
            "Agreement records comparable readings; it is not a calibrated accuracy score."
            if compared
            else "Only one source supplied comparable readings; source review remains required."
        )
    ]
    if conflicts:
        notes.append("Conflicting critical fields were cleared until a reviewer resolves them against the source.")
    return ConsensusSummary(
        status=status,
        sources=sources,
        fields_compared=compared,
        fields_with_readings=with_readings,
        conflicts=conflicts,
        notes=notes,
    )


def consensus_warnings(summary: ConsensusSummary) -> list[str]:
    if not summary.conflicts:
        return []
    return [
        "Source consensus conflict for "
        + ", ".join(summary.conflicts)
        + "; values were not selected automatically and require human review."
    ]


def merge_summaries(summaries: Iterable[ConsensusSummary]) -> ConsensusSummary:
    items = list(summaries)
    if not items:
        return ConsensusSummary()
    conflicts = list(dict.fromkeys(field for item in items for field in item.conflicts))
    sources = list(dict.fromkeys(source for item in items for source in item.sources))
    compared = sum(item.fields_compared for item in items)
    with_readings = sum(item.fields_with_readings for item in items)
    status = "conflict" if conflicts else "agree" if compared else "single_source"
    notes = list(dict.fromkeys(note for item in items for note in item.notes))
    return ConsensusSummary(
        status=status,
        sources=sources,
        fields_compared=compared,
        fields_with_readings=with_readings,
        conflicts=conflicts,
        notes=notes,
    )
