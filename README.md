# VYOM+ · GST Invoice Intelligence

A working, local-first invoice ingestion and review application. Upload **XLSX, CSV, PDF, JPEG/JPG or PNG**, inspect extracted records and source text, correct records, revalidate, and export JSON or CSV. Documents and corrections persist in SQLite across restarts.

> **Validation means consistency checks passed—not that a document is authentic, GST-registered, legally compliant, or ready to post without accounting review.** Missing values remain null. OCR recognition scores are not field-accuracy probabilities.

## Run

Requires **Python 3.11–3.13** (tested on Python 3.12) and [uv](https://docs.astral.sh/uv/). No Node build or external API key is needed.

```bash
cd /home/anmol/vyom-plus
uv sync --python python3.12
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. Interactive API documentation is at `/docs` (FastAPI's documentation UI loads CDN assets; the application itself does not). The schema is available offline at `/openapi.json`.

Run commands from the project root. This is a source-run application, not a published Python package; `uv sync` creates an isolated `.venv` and installs the locked dependencies.

RapidOCR and its bundled model weights are installed with the dependencies. The first OCR call initializes the CPU inference engine; no document is sent to an external service by default. If a headless Linux system lacks `libGL`, install the OS library required by OpenCV before running image extraction.

### Try the complete workflow

1. Download a synthetic sample using the sample links in the interface, or use the files in `samples/`.
2. Upload `sample-invoices.csv` or `.xlsx`: two invoices, three item rows, reconciled GST and totals.
3. Upload `sample-invoice.pdf`: native text and two item rows are extracted; the result requires review.
4. Upload `sample-invoice.png`: real CPU OCR extracts the printed invoice, also requiring review.
5. Upload `sample-mismatch.csv`: the incorrect grand total is flagged as an error.
6. Open a record, inspect issues/source, and edit the normalized invoices. For the mismatch sample, change `totals.grand_total` from `"12000.00"` to `"11800.00"` and save.
7. Confirm source review for OCR/PDF/vision results. Confirmation **does not waive missing fields, invalid GSTINs, or reconciliation errors**.
8. Export JSON for nested accounting records or CSV for one row per line item. Invoice totals repeat on each item row: **do not sum the repeated invoice-total columns**. Exports include validation status and issues, including when a record is not yet validated.

The sample GSTIN is syntactically/checksum-valid but **not verified as a real registration**. All sample business data is synthetic. Regenerate samples with `uv run python -m samples.generate`.

## Processing architecture

```text
Upload → size/extension/signature checks → format router
  CSV/XLSX → header/delimiter detection → rows → invoice grouping
  PDF      → native text when usable; otherwise bounded page rendering → OCR
  JPG/PNG  → bounded quality assessment + retained preprocessing → OCR + layout rows
  Optional → local Ollama VLM on page images, including handwriting
                           ↓
  strict Pydantic schema + Decimal financial normalization + source evidence
                           ↓
  deterministic GST, date, tax, line-item and total validation
                           ↓
  SQLite + private source storage → browser review/correction → JSON / CSV
```

### Extraction and normalization

- Supports UTF-8/UTF-16 CSV with comma, semicolon, tab, or pipe separators; header aliases and preamble detection.
- XLSX supports multiple sheets, bounded rows, and empty-cell handling. Formulas are **not executed**: save/export values before uploading formula-driven workbooks. Such cells are retained in original tables and flagged.
- Preserves original spreadsheet columns and rows in `tables`, including unmapped fields. Per-sheet rows group by invoice number and supplier identity. Ambiguous continuation rows and conflicting repeated totals are flagged.
- Generic transaction tables are preserved as separate `transaction` records; missing GST/invoice fields remain review issues rather than being invented.
- Printed PDF/image fallback extraction handles labeled supplier/buyer, GSTINs, invoice number/date, place of supply, amounts, and recognizable item tables. Arbitrary layouts may need a VLM or corrections.
- Visual PDF/image input receives deterministic, bounded quality signals for blur, brightness, contrast, resolution, skew, readability, and ruled-table likelihood. The review response retains private orientation-corrected, grayscale, autocontrast, thresholded, sharpened, denoised, upscaled, and deskewed previews. These signals guide review and preprocessing; they are not field-accuracy probabilities or handwriting recognition.
- Elevated blur selects grayscale plus sharpening for the OCR pass; normal pages use grayscale plus autocontrast. The original source is always retained separately.
- Decimal strings avoid binary floating-point money errors. HSN/SAC and invoice identifiers stay strings. Dates use Indian day-first normalization.
- Only defensible spreadsheet calculations are derived (quantity × price − line discount, sums of complete columns, or sums of explicit item totals). Derivations are recorded in `field_evidence`. Missing tax values are not manufactured.
- `taxable_value` means value **after item discount and before tax**. Invoice-level `discount` is informational; it is not subtracted a second time. `round_off` is included in total reconciliation. An invoice-wide discount must already be reflected in taxable values.
- Repeated invoice identities on separate PDF pages are retained and flagged, not silently merged. Multiple invoice-number labels on one page trigger a warning in fallback extraction; use vision or split/correct those records. Review multipage continuation invoices before export.

### Validation

- GSTIN structure, recognized state code and base-36 check digit; no live GST registration lookup.
- Required invoice/date/supplier/taxable/grand-total fields, valid/future dates, HSN/SAC shape, duplicate identities within one document, and unsupported currencies.
- Quantity × unit price − discount; item tax amounts against explicit rates; item totals; sums of item taxable/tax values; invoice total including round-off. Decimal arithmetic with **₹0.05 tolerance**.
- CGST/SGST split consistency, mixed IGST/local taxes, and supply-state tax-regime warnings. Special tax treatments (SEZ, reverse charge, mixed supplies) remain human-review cases.
- Three statuses: `invalid` (errors), `needs_review` (warnings), `validated` (no unresolved checks). Every PDF/OCR/VLM extraction requires explicit source comparison, regardless of its recognition score.
- Source extraction warnings remain visible after review. Reviewer confirmation acknowledges those warnings but cannot override deterministic validation failures. Provenance is server-controlled.

## Handwritten invoices and optional local vision

**The default OCR engine is optimized for printed text, not handwriting.** Handwriting mode without a configured VLM displays a fallback warning and never auto-validates the result. There is no claim of benchmarked handwritten-GST accuracy.

For stronger handwriting/layout understanding, explicitly install an appropriately licensed, **image-capable Ollama model**. For example, if compatible with your hardware and license requirements:

```bash
# Optional, explicit model download. This can require several GB of disk/RAM/VRAM.
ollama pull qwen2.5vl:7b
# Ensure Ollama is running, then start VYOM+ in this shell:
export VYOM_VISION_MODEL=qwen2.5vl:7b
export VYOM_VISION_URL=http://127.0.0.1:11434
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`.env.example` documents options; `.env` is **not** automatically loaded. Setting `VYOM_VISION_MODEL` enables vision on PDF/image pages, not spreadsheets. Localhost is the default endpoint. **Configuring a remote endpoint sends page images to that endpoint**; do this only with authorization to share those documents.

The adapter uses schema-constrained output, a deterministic temperature, an instruction to treat document contents as untrusted data, explicit unknown/null values, and source-evidence fields. Model-reported confidence is discarded. OCR/text versus vision disagreements on invoice number, supplier GSTIN and total are flagged. Timeout, invalid model output, or unavailable service falls back to OCR/text with a visible warning.

For handwritten evaluations:

- Enable handwriting mode and use a configured vision model; retain the original source for comparison.
- Check GSTIN digits, dates, HSN, decimal placement, tax splits, and each line total; arithmetic can pass despite a misread value.
- Correct uncertain values and explicitly confirm source review; never treat model-produced evidence as independent proof.
- Evaluate on a representative, consented, labeled set (including poor scans, diverse handwriting, scripts and layouts). Measure per-field exact accuracy, line-item recall, arithmetic errors and human correction rate. **No such real-world handwriting benchmark is included or claimed here.**

## API

```bash
curl -F 'file=@samples/sample-invoices.xlsx' http://127.0.0.1:8000/api/documents
curl -F 'file=@samples/sample-invoice.png' -F 'handwriting=true' http://127.0.0.1:8000/api/documents
curl http://127.0.0.1:8000/api/documents
curl http://127.0.0.1:8000/api/documents/DOCUMENT_ID
curl -o records.json 'http://127.0.0.1:8000/api/documents/DOCUMENT_ID/export?format=json'
curl -o records.csv 'http://127.0.0.1:8000/api/documents/DOCUMENT_ID/export?format=csv'
```

| Route | Purpose |
|---|---|
| `GET /api/health` | OCR package availability, configured vision model, limits (not model-readiness certification) |
| `POST /api/documents` | Multipart `file` plus optional `handwriting` boolean |
| `GET /api/documents` | Latest 200 document summaries |
| `GET /api/documents/{id}` | Complete normalized document, tables, evidence, raw text and issues |
| `PUT /api/documents/{id}` | JSON `{ "invoices": [...], "reviewer_confirmed": true }`; strict schema and revalidation |
| `GET /api/documents/{id}/source` | Original document download |
| `GET /api/documents/{id}/preprocessing/{page}/{name}` | Server-controlled retained preprocessing preview |
| `GET /api/documents/{id}/export?format=json\|csv` | Full nested JSON or flattened item CSV |
| `DELETE /api/documents/{id}` | Remove saved record and original source |
| `GET /api/samples` | Synthetic sample download metadata |

Use `/docs` for the complete schema. Invoice records contain supplier/buyer, invoice metadata, place of supply, reverse charge, line items, totals, extraction method, recognition confidence (when available), and field evidence. Money and quantities serialize as decimal strings; unknowns are `null`.

## Storage, safety and operating limits

- Original documents, retained preprocessing previews, and records live in `.data/` by default; set `VYOM_DATA_DIR` to change this. The app creates private directories/files and never uses client filenames as storage paths. Data is not encrypted at rest and is retained until deleted. No external telemetry is added.
- Bind to `127.0.0.1`. This is a **single-user evaluator application**, not a multi-tenant production service. Before remote hosting add authentication, authorization, tenant isolation, TLS, malware scanning, encrypted storage, retention/audit policies, rate limiting and an isolated job queue/worker sandbox.
- Maximum file: **20 MB**. PDF: **20 pages**. Images: **25 megapixels**. Workbook: **20 sheets, 5,000 total rows, 100 columns**, expanded XLSX at most 80 MB. At most **500 records** per document. Uploads are processed one at a time; concurrent requests receive a retryable `429`.
- Content signatures are checked for binary formats, multipart bodies are bounded, XLSX expansion is bounded, cross-origin writes are rejected, and CSV exports neutralize spreadsheet formulas. PDF/image parsing still relies on native libraries; keep dependencies updated and use isolation for untrusted public uploads.
- Source text preview is capped at 300,000 characters; original spreadsheets remain in structured `tables` and source downloads.
- There is no live GST portal integration, e-invoice IRN verification, global cross-document duplicate detection, trained layout-specific model, handwriting fine-tuning, or measured real-world accuracy guarantee.

## Development and checks

```bash
uv sync --python python3.12
uv run pytest -q                    # unit + API integration + REAL printed-image/scanned-PDF OCR
uv run ruff check app tests samples
uv run python -m compileall -q app
node --check app/static/app.js      # browser JavaScript syntax
```

Tests cover each accepted format, grouping, original-table preservation, money/GST validation, correction and persistence, export/delete, malicious/invalid input boundaries, real OCR on synthetic samples, and optional vision routing/failure/schema behavior using a **mocked model boundary**. A live VLM and real handwriting corpus are separate, currently unverified checks. There is no TypeScript typecheck or frontend bundle/build step: the UI is plain HTML/CSS/JavaScript served by FastAPI.

A real Chromium smoke script is also provided. Start a server with a **new disposable data directory**, then run:

```bash
# Terminal 1 (disposable workspace, not your actual stored invoices):
VYOM_DATA_DIR=$(mktemp -d) uv run uvicorn app.main:app --host 127.0.0.1 --port 8931
# Terminal 2, using an installed Chrome/Chromium executable:
uv run python tests/browser_smoke.py http://127.0.0.1:8931 /usr/bin/google-chrome
```

It exercises browser multi-upload, real OCR preview, corrections, revalidation, persistence, both downloads, deletion, and mobile navigation. It expects an empty workspace and writes screenshots to ignored `test-results/`. Stop the test server afterward.

### Verification performed

- `pytest -q`: **65 passed**, including real OCR on synthetic PNG/JPG/JPEG/scanned-PDF invoices. One third-party Starlette/httpx deprecation warning remains; no test failures.
- `ruff check app tests samples`, `python -m compileall -q app`, `node --check app/static/app.js`, and `uv lock --check`: passed.
- `tests/browser_smoke.py` against the real API in Chrome: passed the complete upload/review/export workflow and mobile navigation, with no browser JavaScript/CSP errors. Desktop/mobile screenshots were inspected.
- Live vision-model inference and a real handwritten-invoice accuracy benchmark: **not run**. Optional vision schema/routing/fallback tests use a mocked adapter boundary and do not establish handwriting accuracy.

Dependencies and exact versions are recorded in `pyproject.toml` and `uv.lock`. Review upstream licenses for the OCR/model artifacts you deploy. Core components include FastAPI/Pydantic, OpenPyXL, PDFium via pypdfium2, Pillow, RapidOCR/ONNX Runtime, and optional Ollama-hosted vision models.
