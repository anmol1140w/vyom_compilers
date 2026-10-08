# VYOM+ Implementation Progress

Checkpoint: 2026-10-08

## Current position

The repository audit, Phase 1 foundation, and the first Phase 2 quality/routing
increment from `PHASED_IMPLEMENTATION_PLAN.md` are complete. The next
implementation session should continue with richer layout/table signals and then
the consensus work described in `ARCHITECTURE_NOTES.md`.

## Completed in this session

### Phase 0

- Audited the FastAPI routes, extraction modules, strict models, validation flow,
  SQLite persistence, browser UI, exports, and current tests.
- Recorded extension points, regression risks, dependency decisions, compatibility
  rules, and the ordered backlog in `ARCHITECTURE_NOTES.md`.
- Confirmed that the existing baseline was clean before changes: 65 tests passed.
- Added no new dependency.

### Phase 1 foundation

- Added additive Pydantic metadata models for:
  - processing timings, source size, page/record counts, and fallback reasons;
  - route selection, document class, route reason, and handwriting intent;
  - source observations from OCR, native PDF text, local vision, and tabular data;
  - normalized source bounding boxes and engine recognition scores;
  - per-field structured provenance beside the existing `field_evidence` strings;
  - reserved risk and verification result structures with honest not-assessed
    defaults.
- Preserved old serialized `Document` records by giving all new fields compatible
  defaults.
- Added OCR region observations without changing the default two-value `ocr()`
  contract or the default four-value `extract_document()` contract. The upload
  route opts into the additional observations.
- Added a server-maintained `extraction_snapshot` so reviewer edits do not replace
  the original AI/tabular extraction.
- Added explicit `human_corrections` and `audit_events` for extraction,
  validation, reviewer edits, confirmation, and revalidation.
- Preserved server control of extraction method, recognition confidence, evidence,
  field confidence, and field provenance during review updates.

### Phase 2 quality and preprocessing increment

- Added bounded Pillow/NumPy quality heuristics for blur, brightness, contrast,
  resolution, skew, readability, ruled-table signal, and explicit unknown
  handwriting likelihood.
- Added per-page quality metadata and retained private preprocessing previews for
  orientation-corrected, grayscale, autocontrast, adaptive-threshold, sharpened,
  denoised, upscaled, and deskewed representations.
- Kept the original upload immutable and bounded generated artifacts to prevent a
  preprocessing step from becoming an unbounded storage multiplier.
- Added a safe preprocessing-image API route and review-panel links so a reviewer
  can inspect the retained representations.
- Connected elevated blur to the existing OCR path: blurry pages use the retained
  sharpened representation, while normal pages continue using autocontrast.
- Added explicit route/classification metadata for tabular, digital PDF, scanned,
  printed, poor-quality, and requested-handwriting review paths. A requested
  handwriting path remains a review signal and is not a recognition claim.
- Kept borderless-table and handwriting classification conservative. No trained
  detector or calibrated confidence is claimed.

## Verification at checkpoint

The following checks pass after the changes:

```text
uv run pytest -q
uv run ruff check app tests samples
uv run python -m compileall -q app
node --check app/static/app.js
```

The suite now includes focused coverage for native-text provenance, OCR source
regions, processing/routing metadata, immutable extraction snapshots, reviewer
correction/audit history, quality scoring, preprocessing artifacts, route signals,
and preprocessing serving. The existing supported-file, validation, boundary,
persistence, export, browser smoke, and optional vision tests remain in place.

Final Phase 2 verification for this checkpoint: `74 passed`, Ruff passed,
compileall passed, JavaScript syntax passed, and the disposable-data browser smoke
workflow passed.

## Important design constraints for the next session

- Do not copy OCR recognition scores into `Invoice.field_confidence`; they are not
  calibrated field-accuracy probabilities.
- Keep `Document.extraction_snapshot` unchanged after human edits.
- Keep existing string `field_evidence` and REST route shapes readable.
- Do not populate `risk` or `verification` with unsupported claims. A format check
  must remain distinct from authoritative registration verification.
- Preserve the original source file and deterministic validation behavior.
- Avoid adding a dependency until its license, Python compatibility, resource cost,
  offline behavior, and concrete feature need are documented.

## Next work item

Improve quality/layout signals with labeled fixtures and page-level table/layout
region extraction. Then implement a reusable OCR/native-text/VLM observation
consensus engine that records critical-field conflicts instead of selecting an
uncertain value silently. Keep the current OCR fallback and review workflow as the
safe baseline while adding those observations.
