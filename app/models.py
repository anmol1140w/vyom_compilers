"""Shared, strict record schema. Decimal values serialize as strings, never floats.

The metadata models in this module are deliberately additive. Documents written by
older versions contain none of these fields and remain readable because every new
collection has a default and every new scalar is optional.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, str_max_length=10000, validate_assignment=True
    )


class BoundingBox(Model):
    """A normalized source rectangle (all coordinates are relative to the page)."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(ge=0, le=1)
    height: float = Field(ge=0, le=1)


ObservationSource = Literal[
    "ocr", "vision", "native_text", "qr", "tabular", "derived", "human"
]


class SourceObservation(Model):
    """One source reading or OCR region retained for later comparison."""

    source: ObservationSource
    page_number: int | None = Field(default=None, ge=1)
    text: str | None = Field(default=None, max_length=10000)
    bounding_box: BoundingBox | None = None
    # This is an engine recognition score, never a field-accuracy probability.
    recognition_score: float | None = Field(default=None, ge=0, le=1)
    preprocessing: str | None = Field(default=None, max_length=200)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=100)


class FieldReading(Model):
    """A normalized reading from one independent extraction source."""

    source: ObservationSource
    value: str | None = Field(default=None, max_length=10000)
    evidence: str | None = Field(default=None, max_length=10000)
    page_number: int | None = Field(default=None, ge=1)
    bounding_box: BoundingBox | None = None
    recognition_score: float | None = Field(default=None, ge=0, le=1)
    preprocessing: str | None = Field(default=None, max_length=200)


class FieldProvenance(Model):
    """Evidence attached to one normalized field, separate from its value."""

    observations: list[SourceObservation] = Field(default_factory=list, max_length=20)
    readings: list[FieldReading] = Field(default_factory=list, max_length=20)
    status: Literal["observed", "derived", "conflict", "unreadable", "corrected"] = "observed"
    confidence: float | None = Field(default=None, ge=0, le=1)
    alternatives: list[str] = Field(default_factory=list, max_length=20)


class ConsensusSummary(Model):
    """Explainable comparison status; no score is implied by agreement."""

    status: Literal["not_run", "single_source", "agree", "conflict"] = "not_run"
    sources: list[ObservationSource] = Field(default_factory=list, max_length=20)
    fields_compared: int = Field(default=0, ge=0)
    fields_with_readings: int = Field(default=0, ge=0)
    conflicts: list[str] = Field(default_factory=list, max_length=100)
    notes: list[str] = Field(default_factory=list, max_length=20)


LayoutRegionKind = Literal[
    "header",
    "supplier",
    "buyer",
    "invoice_metadata",
    "line_items",
    "tax_summary",
    "totals",
    "payment",
    "qr",
    "signature",
    "unknown",
]


class LayoutRegion(Model):
    """A conservative page region inferred from source observations."""

    page_number: int = Field(ge=1)
    kind: LayoutRegionKind = "unknown"
    text: str = Field(default="", max_length=10000)
    bounding_box: BoundingBox | None = None
    observation_indexes: list[int] = Field(default_factory=list, max_length=500)
    source: ObservationSource = "ocr"
    method: str = "heuristic_text_geometry"


class ProcessingMetadata(Model):
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    extraction_duration_ms: int | None = Field(default=None, ge=0)
    quality_duration_ms: int | None = Field(default=None, ge=0)
    validation_duration_ms: int | None = Field(default=None, ge=0)
    page_count: int | None = Field(default=None, ge=0)
    record_count: int | None = Field(default=None, ge=0)
    source_size_bytes: int | None = Field(default=None, ge=0)
    fallback_reason: str | None = Field(default=None, max_length=2000)


class QualityAssessment(Model):
    """Bounded, heuristic quality signals; these are routing aids, not accuracy claims."""

    applicable: bool = False
    score: int | None = Field(default=None, ge=0, le=100)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    blur: float | None = Field(default=None, ge=0, le=1)
    brightness: float | None = Field(default=None, ge=0, le=1)
    contrast: float | None = Field(default=None, ge=0, le=1)
    resolution: float | None = Field(default=None, ge=0, le=1)
    skew_degrees: float | None = Field(default=None, ge=-45, le=45)
    readability: float | None = Field(default=None, ge=0, le=1)
    handwriting_likelihood: float | None = Field(default=None, ge=0, le=1)
    table_likelihood: float | None = Field(default=None, ge=0, le=1)
    method: str = "deterministic_pillow_numpy_heuristics"
    notes: list[str] = Field(default_factory=list, max_length=50)


class PageQuality(Model):
    page_number: int = Field(ge=1)
    assessment: QualityAssessment
    native_text_available: bool = False
    extraction_method: str = "unknown"
    ocr_preprocessing: str | None = None


PreprocessingName = Literal[
    "original",
    "orientation_corrected",
    "grayscale",
    "autocontrast",
    "adaptive_threshold",
    "sharpened",
    "denoised",
    "upscaled",
    "deskewed",
]


class PreprocessingRepresentation(Model):
    name: PreprocessingName
    page_number: int = Field(ge=1)
    artifact_path: str | None = Field(default=None, max_length=500)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    format: Literal["source", "png"] = "png"
    applied: bool = True
    reason: str | None = None


class RoutingMetadata(Model):
    document_class: Literal[
        "tabular",
        "digital_pdf",
        "scanned",
        "printed",
        "handwritten",
        "mixed",
        "poor_quality",
        "image",
        "unknown",
    ] = "unknown"
    selected_route: str = ""
    reason: str = ""
    handwriting_requested: bool = False


class RiskFactor(Model):
    code: str = Field(max_length=100)
    message: str = Field(max_length=2000)
    severity: Literal["info", "warning", "error"] = "warning"
    field: str | None = Field(default=None, max_length=200)


class RiskAssessment(Model):
    status: Literal["not_assessed", "clear", "review", "blocked"] = "not_assessed"
    score: int | None = Field(default=None, ge=0, le=100)
    level: Literal["unknown", "low", "medium", "high"] = "unknown"
    factors: list[RiskFactor] = Field(default_factory=list, max_length=500)
    blocking_reasons: list[str] = Field(default_factory=list, max_length=100)


class VerificationSummary(Model):
    # Format validity and registration verification are intentionally distinct.
    status: Literal[
        "not_checked", "format_valid", "registration_verified", "mismatch", "unavailable"
    ] = "not_checked"
    provider: str = "none"
    message: str | None = Field(default=None, max_length=2000)
    checks: dict[str, str] = Field(default_factory=dict, max_length=100)


class HumanCorrection(Model):
    timestamp: str
    invoice_index: int = Field(ge=0)
    field: str = Field(max_length=300)
    old_value: str | None = Field(default=None, max_length=10000)
    new_value: str | None = Field(default=None, max_length=10000)
    action: Literal["corrected", "marked_unreadable", "accepted", "rejected"] = "corrected"
    reason: str | None = Field(default=None, max_length=2000)


class AuditEvent(Model):
    timestamp: str
    action: str = Field(max_length=100)
    invoice_index: int | None = Field(default=None, ge=0)
    field: str | None = Field(default=None, max_length=300)
    old_value: str | None = Field(default=None, max_length=10000)
    new_value: str | None = Field(default=None, max_length=10000)
    reason: str | None = Field(default=None, max_length=2000)


class Party(Model):
    name: str | None = None
    gstin: str | None = None
    address: str | None = None


class LineItemProvenance(Model):
    """Source context for one normalized line item row."""

    page_number: int | None = Field(default=None, ge=1)
    source_region: BoundingBox | None = None
    source_text: str | None = Field(default=None, max_length=10000)
    extraction_method: str = "unknown"
    field_evidence: dict[str, str] = Field(default_factory=dict, max_length=100)


class DocumentIdentifiers(Model):
    """Identifiers commonly present on GST/e-invoice and transport documents."""

    irn: str | None = Field(default=None, max_length=100)
    acknowledgement_number: str | None = Field(default=None, max_length=100)
    acknowledgement_date: str | None = None
    eway_bill_number: str | None = Field(default=None, max_length=100)
    vehicle_number: str | None = Field(default=None, max_length=50)
    transport_mode: str | None = Field(default=None, max_length=100)


class LineItem(Model):
    description: str | None = None
    hsn_sac: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    discount: Decimal | None = None
    taxable_value: Decimal | None = None
    gst_rate: Decimal | None = None
    cgst_rate: Decimal | None = None
    sgst_rate: Decimal | None = None
    igst_rate: Decimal | None = None
    cgst_amount: Decimal | None = None
    sgst_amount: Decimal | None = None
    igst_amount: Decimal | None = None
    cess_amount: Decimal | None = None
    total: Decimal | None = None
    provenance: LineItemProvenance = Field(default_factory=LineItemProvenance)

    @field_validator(
        "quantity",
        "unit_price",
        "discount",
        "taxable_value",
        "gst_rate",
        "cgst_rate",
        "sgst_rate",
        "igst_rate",
        "cgst_amount",
        "sgst_amount",
        "igst_amount",
        "cess_amount",
        "total",
    )
    @classmethod
    def bounded_number(cls, value):
        if value is not None and (abs(value) > Decimal("1e14") or value.as_tuple().exponent < -8):
            raise ValueError("Number is outside supported financial precision/range")
        return value


class Totals(Model):
    taxable_value: Decimal | None = None
    cgst_amount: Decimal | None = None
    sgst_amount: Decimal | None = None
    igst_amount: Decimal | None = None
    cess_amount: Decimal | None = None
    discount: Decimal | None = None
    round_off: Decimal | None = None
    grand_total: Decimal | None = None

    @field_validator("*")
    @classmethod
    def bounded_number(cls, value):
        return LineItem.bounded_number(value)


class Invoice(Model):
    invoice_number: str | None = None
    invoice_date: str | None = None
    currency: str = "INR"
    document_type: Literal["invoice", "credit_note", "debit_note", "transaction"] = "invoice"
    supplier: Party = Field(default_factory=Party)
    buyer: Party = Field(default_factory=Party)
    place_of_supply: str | None = None
    reverse_charge: bool | None = None
    identifiers: DocumentIdentifiers = Field(default_factory=DocumentIdentifiers)
    line_items: list[LineItem] = Field(default_factory=list, max_length=5000)
    totals: Totals = Field(default_factory=Totals)
    confidence: float | None = Field(default=None, ge=0, le=1)
    extraction_method: str = "unknown"
    field_evidence: dict[str, str] = Field(default_factory=dict, max_length=10000)
    field_confidence: dict[str, float] = Field(default_factory=dict, max_length=10000)
    field_provenance: dict[str, FieldProvenance] = Field(default_factory=dict, max_length=10000)


class Issue(Model):
    severity: Literal["error", "warning", "info"]
    code: str
    field: str
    message: str
    invoice_index: int | None = None


class Review(Model):
    confirmed: bool = False
    updated_at: str | None = None


class Table(Model):
    sheet: str
    columns: list[str]
    rows: list[dict[str, str | None]]


class Document(Model):
    id: str
    filename: str
    source_type: str
    pipeline: str
    status: Literal["validated", "needs_review", "invalid"] = "needs_review"
    created_at: str
    raw_text: str = Field(default="", max_length=300000)
    extraction_warnings: list[str] = Field(default_factory=list)
    invoices: list[Invoice] = Field(default_factory=list, max_length=500)
    issues: list[Issue] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    review: Review = Field(default_factory=Review)
    processing: ProcessingMetadata = Field(default_factory=ProcessingMetadata)
    quality: QualityAssessment = Field(default_factory=QualityAssessment)
    page_quality: list[PageQuality] = Field(default_factory=list, max_length=20)
    preprocessing: list[PreprocessingRepresentation] = Field(default_factory=list, max_length=200)
    layout_regions: list[LayoutRegion] = Field(default_factory=list, max_length=2000)
    routing: RoutingMetadata = Field(default_factory=RoutingMetadata)
    observations: list[SourceObservation] = Field(default_factory=list, max_length=20000)
    consensus: ConsensusSummary = Field(default_factory=ConsensusSummary)
    risk: RiskAssessment = Field(default_factory=RiskAssessment)
    verification: VerificationSummary = Field(default_factory=VerificationSummary)
    # This is server-maintained and never accepted from ReviewUpdate.
    extraction_snapshot: list[Invoice] = Field(default_factory=list, max_length=500)
    human_corrections: list[HumanCorrection] = Field(default_factory=list, max_length=10000)
    audit_events: list[AuditEvent] = Field(default_factory=list, max_length=10000)


class ReviewUpdate(Model):
    invoices: list[Invoice] = Field(min_length=1, max_length=500)
    reviewer_confirmed: bool = False
