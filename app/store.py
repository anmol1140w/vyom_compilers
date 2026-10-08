"""SQLite document persistence and portable, spreadsheet-safe exports."""

import csv
import io
import json
import shutil
import sqlite3
from pathlib import Path

from .models import Document, Invoice


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.uploads = root / "uploads"
        self.uploads.mkdir(mode=0o700, exist_ok=True)
        self.preprocessing = root / "preprocessed"
        self.preprocessing.mkdir(mode=0o700, exist_ok=True)
        self.db = root / "records.sqlite3"
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, record TEXT NOT NULL)"
            )
        self.db.chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.db, timeout=10)

    def save(self, document: Document):
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET record=excluded.record",
                (document.id, document.created_at, document.model_dump_json()),
            )

    def get(self, document_id: str) -> Document | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT record FROM documents WHERE id=?", (document_id,)
            ).fetchone()
        return Document.model_validate_json(row[0]) if row else None

    def list(self):
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT record FROM documents ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
        summaries = []
        for row in rows:
            document = Document.model_validate_json(row[0])
            summaries.append(
                {
                    **{
                        key: getattr(document, key)
                        for key in (
                            "id",
                            "filename",
                            "source_type",
                            "pipeline",
                            "status",
                            "created_at",
                        )
                    },
                    "invoice_count": len(document.invoices),
                    "issue_count": len(document.issues),
                }
            )
        return summaries

    def delete(self, document_id: str):
        with self.connect() as connection:
            connection.execute("DELETE FROM documents WHERE id=?", (document_id,))
        (self.uploads / document_id).unlink(missing_ok=True)
        shutil.rmtree(self.preprocessing / document_id, ignore_errors=True)

    def cleanup_preprocessing(self, document_id: str):
        """Remove derived artifacts when an upload fails before persistence."""

        shutil.rmtree(self.preprocessing / document_id, ignore_errors=True)


def spreadsheet_safe(value):
    # Decimal strings are deliberately exported as text; JSON retains exact numeric meaning.
    if value is None:
        return ""
    value = str(value)
    if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def csv_export(document: Document) -> str:
    stream = io.StringIO(newline="")
    base_keys = [
        "document_id",
        "validation_status",
        "reviewer_confirmed",
        "invoice_number",
        "invoice_date",
        "currency",
        "document_type",
        "supplier_name",
        "supplier_gstin",
        "buyer_name",
        "buyer_gstin",
        "place_of_supply",
    ]
    item_keys = list(Invoice.model_fields["line_items"].annotation.__args__[0].model_fields)
    total_keys = list(Invoice.model_fields["totals"].annotation.model_fields)
    columns = (
        base_keys
        + [f"item_{key}" for key in item_keys]
        + [f"invoice_{key}" for key in total_keys]
        + ["issues"]
    )
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for index, invoice in enumerate(document.invoices):
        base = {
            "document_id": document.id,
            "validation_status": document.status,
            "reviewer_confirmed": str(document.review.confirmed).lower(),
            **{
                key: getattr(invoice, key)
                for key in [
                    "invoice_number",
                    "invoice_date",
                    "currency",
                    "document_type",
                    "place_of_supply",
                ]
            },
            **{
                f"{role}_{key}": getattr(getattr(invoice, role), key)
                for role in ("supplier", "buyer")
                for key in ("name", "gstin")
            },
            **{f"invoice_{key}": getattr(invoice.totals, key) for key in total_keys},
            "issues": json.dumps(
                [
                    issue.model_dump()
                    for issue in document.issues
                    if issue.invoice_index in {None, index}
                ],
                ensure_ascii=False,
            ),
        }
        for item in invoice.line_items or [None]:
            row = {
                **base,
                **{f"item_{key}": getattr(item, key) if item else None for key in item_keys},
            }
            writer.writerow({key: spreadsheet_safe(value) for key, value in row.items()})
    return "\ufeff" + stream.getvalue()
