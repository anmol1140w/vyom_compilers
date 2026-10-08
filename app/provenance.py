"""Helpers for additive provenance and reviewer-change tracking.

The legacy ``field_evidence`` mapping remains intact for API compatibility. These
helpers populate the structured metadata beside it and keep reviewer edits separate
from the server-owned extraction snapshot.
"""

import json
from collections.abc import Iterator

from .models import (
    AuditEvent,
    FieldProvenance,
    HumanCorrection,
    Invoice,
    SourceObservation,
)

METHOD_SOURCES = {
    "ocr": "ocr",
    "pdf_text": "native_text",
    "local_vision": "vision",
    "tabular": "tabular",
}
_SERVER_CONTROLLED_FIELDS = {
    "confidence",
    "extraction_method",
    "field_evidence",
    "field_confidence",
    "field_provenance",
}


def source_for_method(method: str) -> str:
    return METHOD_SOURCES.get(method, "native_text" if method == "pdf" else "tabular")


def _matching_observation(evidence: str, observations: list[SourceObservation]):
    normalized = " ".join(evidence.split()).casefold()
    for observation in observations:
        if observation.text is None or observation.bounding_box is None:
            continue
        candidate = " ".join(observation.text.split()).casefold()
        if normalized == candidate or normalized in candidate or candidate in normalized:
            return observation
    return None


def attach_invoice_provenance(
    invoice: Invoice,
    *,
    page_number: int | None = None,
    observations: list[SourceObservation] | None = None,
) -> None:
    """Convert existing evidence strings into structured source observations.

    No confidence is inferred here. In particular, an OCR recognition score is
    stored only on the source observation and is never copied to a field confidence.
    """

    observations = observations or []
    for field, evidence in invoice.field_evidence.items():
        if field == "page" or not evidence:
            continue
        evidence_text = str(evidence)
        source = "derived" if evidence_text.lower().startswith("derived:") else source_for_method(
            invoice.extraction_method
        )
        matched = _matching_observation(evidence_text, observations)
        field_observation = SourceObservation(
            source=source,
            page_number=page_number,
            text=evidence_text,
            bounding_box=matched.bounding_box if matched else None,
            recognition_score=matched.recognition_score if matched else None,
            preprocessing=matched.preprocessing if matched else None,
            metadata={"evidence": "model-produced"} if source == "vision" else {},
        )
        existing = invoice.field_provenance.get(field)
        invoice.field_provenance[field] = FieldProvenance(
            observations=[field_observation],
            readings=existing.readings if existing else [],
            status=(
                existing.status
                if existing and existing.status in {"conflict", "corrected", "unreadable"}
                else "derived" if source == "derived" else "observed"
            ),
            confidence=existing.confidence if existing else None,
            alternatives=existing.alternatives if existing else [],
        )
    for index, item in enumerate(invoice.line_items):
        row_evidence = invoice.field_evidence.get(f"line_items.{index}")
        matched = _matching_observation(row_evidence or item.provenance.source_text, observations)
        existing = item.provenance
        item.provenance = existing.model_copy(
            update={
                "page_number": page_number or existing.page_number or (matched.page_number if matched else None),
                "source_region": matched.bounding_box if matched else existing.source_region,
                "source_text": existing.source_text or row_evidence,
                "extraction_method": (
                    existing.extraction_method
                    if existing.extraction_method != "unknown"
                    else invoice.extraction_method
                ),
                "field_evidence": {
                    **existing.field_evidence,
                    **({"row": row_evidence} if row_evidence else {}),
                },
            }
        )


def json_value(value) -> str | None:
    """Serialize an audit value without losing nested structure or decimal strings."""

    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _flatten(value, prefix: str) -> Iterator[tuple[str, object]]:
    if isinstance(value, dict):
        if not value:
            yield prefix, value
            return
        for key in sorted(value):
            yield from _flatten(value[key], f"{prefix}.{key}" if prefix else key)
        return
    if isinstance(value, list):
        if not value:
            yield prefix, value
            return
        for index, item in enumerate(value):
            yield from _flatten(item, f"{prefix}[{index}]")
        return
    yield prefix, value


def changed_fields(before: Invoice | None, after: Invoice | None) -> list[tuple[str, object, object]]:
    """Return reviewer-editable leaf changes while ignoring server-owned metadata."""

    before_data = before.model_dump(mode="json") if before else {}
    after_data = after.model_dump(mode="json") if after else {}
    old_values = dict(_flatten(before_data, ""))
    new_values = dict(_flatten(after_data, ""))
    changes = []
    for field in sorted(set(old_values) | set(new_values)):
        root = field.split(".", 1)[0].split("[", 1)[0]
        if root in _SERVER_CONTROLLED_FIELDS or ".provenance" in field:
            continue
        old_value, new_value = old_values.get(field), new_values.get(field)
        if old_value != new_value:
            changes.append((field, old_value, new_value))
    return changes


def review_audit_entries(
    before: list[Invoice], after: list[Invoice], timestamp: str
) -> tuple[list[HumanCorrection], list[AuditEvent]]:
    corrections: list[HumanCorrection] = []
    events: list[AuditEvent] = []
    for index in range(max(len(before), len(after))):
        changes = changed_fields(
            before[index] if index < len(before) else None,
            after[index] if index < len(after) else None,
        )
        for field, old_value, new_value in changes:
            old_serialized, new_serialized = json_value(old_value), json_value(new_value)
            corrections.append(
                HumanCorrection(
                    timestamp=timestamp,
                    invoice_index=index,
                    field=field,
                    old_value=old_serialized,
                    new_value=new_serialized,
                    reason="Reviewer changed the normalized record; original extraction retained.",
                )
            )
            events.append(
                AuditEvent(
                    timestamp=timestamp,
                    action="reviewer_correction",
                    invoice_index=index,
                    field=field,
                    old_value=old_serialized,
                    new_value=new_serialized,
                    reason="Human review edit",
                )
            )
    return corrections, events
