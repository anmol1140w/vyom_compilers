# VYOM+ Phased Implementation Plan

This document breaks `next_plan.md` into incremental phases. The existing
working functionality must be preserved throughout the implementation.

## Current baseline

VYOM+ already provides:

- FastAPI backend and HTML/CSS/JavaScript frontend
- CSV, XLSX, PDF, PNG, and JPEG/JPG ingestion
- Tabular extraction, PDF extraction, RapidOCR, and optional Ollama vision
- Normalized Pydantic invoice records
- Decimal financial calculations
- GSTIN, tax, line-item, and arithmetic validation
- Source evidence, human review, JSON editing, and SQLite persistence
- JSON/CSV export, batch upload, source retention, security boundaries, and tests

Do not remove these capabilities unless a replacement is demonstrably better.

## Phase 0 — Audit and architecture decisions

**Goal:** Understand the current application before making structural changes.

Tasks:

- Inspect all extraction, normalization, validation, storage, API, and UI code.
- Identify extension points and regression risks.
- Research OCR, handwriting, VLM, layout, table, QR, and PDF options.
- Check licenses, Python compatibility, CPU/GPU requirements, and offline behavior.
- Decide which dependencies are justified.
- Create a feature backlog and compatibility strategy.

**Deliverable:** Architecture notes and an ordered implementation backlog.

## Phase 1 — Data model, provenance, and observability foundation

**Goal:** Prepare the schema and database for explainable document intelligence.

Add backward-compatible support for:

- Document quality and routing metadata
- Processing durations and page/record counts
- Field-level confidence and evidence
- Page numbers and source bounding boxes
- OCR, VLM, native-text, and QR observations
- Risk and verification results
- Human corrections and audit events

Keep AI extraction separate from reviewer changes. Existing records must remain
readable, and the current REST API should remain stable where practical.

## Phase 2 — Quality assessment, preprocessing, and routing

**Goal:** Select an appropriate pipeline for every document.

Implement quality indicators for:

- Blur
- Brightness and contrast
- Resolution
- Skew and rotation
- Readability
- Handwriting likelihood
- Table likelihood

Generate and retain preprocessing representations:

- Original
- Orientation-corrected
- Grayscale
- Autocontrast
- Adaptive threshold
- Sharpened
- Denoised
- Upscaled
- Deskewed
- Perspective-corrected

Add explicit classification and routing for tabular, digital PDF, scanned,
printed, handwritten, mixed, and poor-quality documents. Record the selected
route and the reason for it, then expose that information in the UI.

## Phase 3 — Layout understanding and table extraction

**Goal:** Make extraction template-independent and improve line-item quality.

Detect regions such as supplier, buyer, addresses, invoice metadata, GSTINs,
line-item tables, totals, tax summaries, payment/bank details, QR codes, and
signatures/stamps.

Improve support for:

- Wrapped descriptions
- Multi-line items
- Missing columns
- Merged cells
- Variable spacing
- Collapsed native-PDF tables
- OCR coordinate reconstruction
- Handwritten rows where practical

Every extracted row should include confidence, evidence, source region, and
extraction method.

## Phase 4 — Handwriting pipeline and OCR/VLM consensus

**Goal:** Make handwritten invoice processing the primary differentiator.

Implement:

- Handwriting detection
- Region-specific extraction
- OCR and optional local VLM observations
- Native PDF text as an additional observation where available
- A reusable consensus engine
- Critical-field conflict detection
- Possible alternatives and unreadable-field states

When sources disagree, show the conflict and require human review. Never
silently repair uncertain characters or choose an uncertain GSTIN.

The system must degrade gracefully:

```text
No VLM:        OCR + deterministic validation + manual review
VLM available: OCR + VLM + consensus + deterministic validation
```

## Phase 5 — Explainable review interface

**Goal:** Let a reviewer understand where every important value came from.

Improve the review screen with:

- Original document and source-region highlighting
- Structured extracted fields
- Field confidence and evidence
- OCR, VLM, native-text, and QR readings
- Validation results and conflicts
- Preprocessing path
- Human correction history

Support accept, edit, reject, mark-unreadable, revalidate, and original-versus-
corrected comparison actions. Keep human corrections explicitly distinct from
AI extraction.

## Phase 6 — GST, QR, IRN, and e-way bill intelligence

**Goal:** Add GST-specific cross-checking without making unsupported claims.

Improve checks for GSTINs, state codes, supplier/buyer consistency, place of
supply, CGST/SGST/IGST, rates, cess, round-off, reverse charge, credit notes,
debit notes, and special cases.

Add detection and comparison for:

- QR contents
- Supplier GSTIN
- Invoice number and date
- Total amount
- IRN
- Acknowledgement number/date
- E-way bill number
- Vehicle and transport details

Create adapters for external GST/e-invoice verification. If an authoritative
integration is unavailable, use a clearly labelled demo/mock adapter and keep
these states separate:

```text
Format valid
Registration verified
```

## Phase 7 — Duplicate detection, anomaly detection, and risk scoring

**Goal:** Identify repeated and suspicious records with explainable results.

Add duplicate comparison using supplier identity, invoice number, date, total,
line items, and document similarity. Add interpretable anomaly rules for high
amounts, unusual tax rates, supplier identity changes, invoice-number gaps,
repeated values, unexpected tax regimes, and unusual invoice frequency.

Provide:

- Duplicate risk and explanation
- Risk score and level
- Contributing factors
- Accounting-readiness score
- Blocking reasons

Do not create a score that cannot explain its contributing signals.

## Phase 8 — Supplier intelligence, batch workspace, search, and analytics

**Goal:** Support real accounting workflows across many documents.

Add supplier profiles with invoice counts, totals, averages, GST rates, common
HSN/SAC, places of supply, anomaly counts, and duplicate counts.

Improve batch processing with progress, counts by status/risk, filtering,
sorting, safe bulk actions, export, deletion, and retry/reprocessing.

Support search and filters for invoice number, GSTIN, supplier, buyer, date,
HSN/SAC, amount, IRN, EWB, filename, status, risk, document type, extraction
method, handwriting, review state, and duplicate candidates.

Add decision-oriented analytics for invoice volume/value over time, tax
breakdown, supplier distribution, status, risk, and anomalies.

## Phase 9 — APIs, exports, and audit trail

Keep existing REST routes stable where practical. Add strict APIs for quality,
processing metadata, evidence, risk, duplicates, analytics, the review queue,
audit history, verification, QR/IRN results, and retry/reprocessing.

Retain JSON and CSV exports and add useful validation, risk, audit, and batch
reports.

Record events for extraction, validation, field changes, reviewer corrections,
reviewer confirmation, revalidation, export, and deletion. Store timestamps,
actions, fields, old/new values, and reasons where available.

## Phase 10 — Benchmarks, tests, security, and final polish

**Goal:** Demonstrate reliability and prepare the project for competition use.

Create benchmark categories for printed, scanned, handwritten, poor-quality,
mixed, and multi-layout documents. Measure field accuracy, tax accuracy,
line-item precision/recall where practical, correction rate, OCR/VLM conflict
rate, and validation error rate. Never invent benchmark numbers.

Add fixtures and tests for rotated, blurry, low-contrast, mixed-content,
handwritten, QR, duplicate, anomaly, GST-error, tax-conflict, risk, audit,
batch, search, and analytics scenarios.

Preserve existing security protections and review path traversal, decompression
bombs, malicious PDFs, oversized inputs, formula injection, unsafe HTML,
prompt injection, model output validation, uploaded-document isolation, SSRF,
QR contents, and remote model endpoints.

Run the complete checks:

```bash
uv run pytest -q
uv run ruff check app tests samples
uv run python -m compileall -q app
node --check app/static/app.js
```

Also run browser smoke tests, manual UI review, supported-file tests, failure
paths, export tests, persistence tests, and performance checks.

## Recommended execution order

1. Audit current architecture
2. Add provenance and observability foundations
3. Implement quality scoring and preprocessing
4. Add intelligent routing
5. Improve layout and source coordinates
6. Build the handwriting pipeline
7. Add OCR/VLM consensus
8. Build the explainable review UI
9. Add GST, QR, IRN, and e-way intelligence
10. Add duplicate and risk analysis
11. Add supplier intelligence, batch workflows, and analytics
12. Add benchmark fixtures and demo data
13. Complete security review, testing, and documentation

## Non-negotiable rules

1. Never silently invent invoice values.
2. Never silently repair uncertain GSTINs or other critical fields.
3. Never claim live GST verification without an authoritative integration.
4. Never treat OCR confidence as field-accuracy probability.
5. Never allow an AI model to bypass deterministic validation.
6. Never hide extraction conflicts.
7. Preserve original source documents and provenance.
8. Keep human corrections distinguishable from AI extraction.
9. Use exact decimal arithmetic for financial calculations.
10. Keep current working functionality and avoid unnecessary rewrites.
11. Test every feature before calling it complete.
12. Never fabricate benchmark results.

## Competition success criteria

The final product should visibly answer:

- Why is this better than ordinary OCR?
- What did the system find, and what is uncertain?
- Where did each important value come from?
- Do OCR, VLM, QR, and arithmetic agree?
- How is GST consistency checked?
- Which documents are duplicates or suspicious?
- What exactly needs human attention?
- What did the reviewer change?
- Can the final records be exported for downstream accounting?

The strongest differentiator is an explainable workflow that combines
handwriting-aware extraction, source evidence, consensus, deterministic GST
checks, transparent risk signals, and human review.
