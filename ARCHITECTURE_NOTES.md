# VYOM+ Architecture Notes and Ordered Backlog

This note records the Phase 0 audit and the compatibility decisions used while
starting `PHASED_IMPLEMENTATION_PLAN.md`. It is intentionally grounded in the
current repository rather than proposing a replacement architecture.

## Current architecture

```text
FastAPI upload route
  ├─ bounded request and source-file checks
  ├─ CSV/XLSX -> app.tabular -> normalized invoices + preserved tables
  └─ PDF/image -> app.extraction
       ├─ usable native PDF text -> app.text_extract
       ├─ rendered page -> RapidOCR -> app.text_extract
       └─ optional local Ollama vision -> strict VisionResponse
                                  ↓
                       app.models canonical Pydantic records
                                  ↓
                       app.validation deterministic checks
                                  ↓
                       app.store SQLite JSON record + private source file
                                  ↓
                       plain HTML/CSS/JS review and export UI
```

### Extension points

| Area | Existing boundary | Safe extension point |
|---|---|---|
| Canonical data | `app.models` strict Pydantic models | Add optional metadata with defaults; keep decimal fields as `Decimal` |
| Tabular extraction | `extract_tabular(path, kind)` | Preserve `Table` rows and attach structured provenance after normalization |
| PDF/image extraction | `extract_document(path, kind, handwriting)` | Keep the original four-value return by default; opt into source observations |
| OCR | `app.extraction.ocr` | Retain line reconstruction while preserving region coordinates |
| Validation | `validate_document(document)` mutates issues/status | Add independent validators and risk signals without allowing them to override errors |
| Persistence | One JSON record per row in SQLite | Additive JSON fields require no destructive migration; add tables only when query volume justifies it |
| Review API | `PUT /api/documents/{id}` with `ReviewUpdate` | Keep the route and server-controlled provenance; append correction/audit metadata |
| Frontend | Plain JavaScript consumes the complete document response | Add evidence and routing panels without a build system or framework migration |

## Findings and regression risks

1. SQLite currently stores a complete serialized `Document`, so older records can
   only be kept readable if new fields have defaults and old evidence strings are
   not reinterpreted in place.
2. `validate_document` owns the status transition. Review confirmation must never
   bypass this function or turn an error into a validated record.
3. OCR recognition scores are document/engine signals, not calibrated field
   accuracy. They are retained on source observations and are not copied to field
   confidence.
4. Native PDF extraction currently has text but not PDF glyph coordinates. OCR
   regions can provide bounding boxes now; native-text coordinates and visual
   region detection belong to the layout phase.
5. The upload route serializes processing with a process-local lock. A worker
   system would change failure and persistence behavior and is not justified yet.
6. The UI relies on the existing response shape and expects the JSON export to
   represent the saved record. Export audit events are therefore deferred until a
   separate audit-report path exists.
7. The VLM boundary is already schema-constrained and local by default. Remote
   endpoints remain an explicit operator choice and must not be enabled by a new
   dependency or silent network call.

## Phase 0 dependency and compatibility decisions

- No dependency was added for the first increment. FastAPI/Pydantic, Pillow,
  PDFium, RapidOCR, OpenPyXL, and the optional Ollama adapter already cover the
  current local/offline paths.
- Image preprocessing will initially use Pillow and NumPy. A heavier layout or
  handwriting model will be evaluated only after quality fixtures establish a
  concrete need; its license, Python support, model size, CPU/GPU behavior, and
  offline behavior must be recorded before adoption.
- QR decoding, layout detection, and authoritative GST/e-invoice verification are
  deferred behind adapters. A format check must never be presented as live
  registration verification.
- The canonical response remains backward-compatible. Existing string
  `field_evidence` remains available while `field_provenance`, observations,
  processing metadata, and review history are additive.

## Phase 1 foundation delivered

The schema now supports:

- processing timestamps, durations, page/record counts, source size, and fallback
  reason;
- selected route, document class, route reason, and handwriting-mode intent;
- source observations with OCR/native/VLM/tabular origin, page, normalized bounding
  box, preprocessing, and a separate recognition score;
- per-field structured provenance alongside the legacy evidence text;
- per-line-item source text, page, region, and extraction-method provenance;
- structured IRN, acknowledgement, e-way bill, vehicle, and transport identifiers;
- an immutable server-maintained extraction snapshot;
- explicit human corrections and audit events for extraction, validation, review
  edits, confirmation, and revalidation;
- reserved risk and verification result structures whose default state is
  `not_assessed`/`not_checked`, so the application makes no unsupported claim.

The foundation does not infer field confidence or claim handwriting detection. Those
signals require the quality/routing and consensus work below.

## Phase 2 quality/preprocessing increment delivered

- `app.quality` uses only the existing Pillow, NumPy, and PDFium dependencies to
  compute bounded image/page heuristics. It deliberately abstains from handwriting
  classification unless a future evaluated detector is added.
- Derived previews are stored under a private `preprocessed/<document-id>/` tree;
  the source upload remains separate and unchanged. Each generated artifact has a
  per-file and per-document bound, and failed uploads clean the derived directory.
- The OCR adapter now receives a selected photometric path. Normal pages use
  grayscale plus autocontrast; elevated blur selects grayscale plus sharpening.
  Coordinates remain tied to the OCR image used for the observation.
- Quality is exposed in the `Document.quality` and `Document.page_quality` fields,
  route rationale is in `Document.routing`, and derived images are available only
  through the server-controlled preprocessing route.
- The quality score is a review/routing heuristic. It is not a field accuracy
  probability, handwriting accuracy measure, or legal/compliance conclusion.

## Ordered implementation backlog

1. **Quality and preprocessing:** add bounded image quality metrics and retained
   representations using the original source as the immutable baseline.
2. **Routing:** make quality/classification decisions explicit and record fallback
   reasons for tabular, native PDF, scanned, printed, handwritten, mixed, and poor
   quality inputs.
3. **Layout and tables:** improve region detection, wrapped/multi-line row
   handling, native-PDF coordinate reconstruction, and line-level provenance.
   The first heuristic page-region and source-reading increment is now present;
   it remains deliberately conservative until labeled fixtures are added.
4. **Consensus:** introduce reusable OCR/native/VLM/QR observations and conflict
   states for critical fields; never silently choose a disagreement. OCR/native/VLM
   comparison and conflict clearing are now present, with optional QR candidates
   and identifier comparisons; deterministic arithmetic readings remain future work.
5. **Explainable review UI:** show route, source regions, observations, confidence
   semantics, correction history, and original-versus-current values.
6. **GST document intelligence:** add QR, IRN, acknowledgement, e-way fields and
   deterministic cross-checks, with a clearly labelled verification adapter.
7. **Risk and duplicates:** implement explainable cross-document comparison,
   anomaly factors, blocking reasons, and accounting-readiness signals.
8. **Workspace scale:** add supplier profiles, review queue, practical search,
   batch status, filtering, retry, and decision-oriented analytics.
9. **API/report surface:** expose metadata, evidence, risk, verification, audit,
   review queue, retry, and dedicated validation/risk/audit reports while keeping
   current routes stable.
10. **Evaluation and hardening:** add labeled fixtures and benchmark tooling,
    browser/manual checks, security review, performance checks, and documentation.

Every backlog item should preserve the current accepted formats, source retention,
strict model validation, Decimal arithmetic, deterministic validation, review path,
JSON/CSV exports, and existing boundary tests.
