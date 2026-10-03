"""Shared, strict record schema. Decimal values serialize as strings, never floats."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, str_max_length=10000, validate_assignment=True
    )


class Party(Model):
    name: str | None = None
    gstin: str | None = None
    address: str | None = None


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
    line_items: list[LineItem] = Field(default_factory=list, max_length=5000)
    totals: Totals = Field(default_factory=Totals)
    confidence: float | None = Field(default=None, ge=0, le=1)
    extraction_method: str = "unknown"
    field_evidence: dict[str, str] = Field(default_factory=dict, max_length=10000)


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


class ReviewUpdate(Model):
    invoices: list[Invoice] = Field(min_length=1, max_length=500)
    reviewer_confirmed: bool = False
