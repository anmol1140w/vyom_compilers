You are the lead engineer responsible for transforming the existing VYOM+ repository into a competition-winning, production-quality AI-powered GST invoice intelligence platform.

Repository:
https://github.com/anmol1140w/vyom_compilers

IMPORTANT:
Do NOT blindly rewrite the existing project.
First inspect the complete repository and understand what already works.
Preserve and improve working functionality.
Make architectural decisions based on the current codebase, constraints, available open-source tooling, and the actual problem statement.

==================================================

1. PROBLEM STATEMENT
   ==================================================

VYOM+ must accept:

* XLSX
* CSV
* PDF
* JPEG/JPG
* PNG

and convert real-world invoice/transaction documents into:

* structured machine-readable financial records
* validated GST information
* reliable line-item data
* explainable extraction results
* reviewable records
* accounting-ready outputs

The PRIMARY technical challenge is reliable document intelligence, with SPECIAL EMPHASIS on handwritten GST invoices, while maintaining strong performance on printed and digitally generated invoices.

The final product should feel like an intelligent financial-document platform, not an OCR demo.

==================================================
2. CURRENT REPOSITORY BASELINE
==============================

The current repository already contains substantial functionality.

Current architecture includes:

* FastAPI backend
* HTML/CSS/JavaScript frontend
* CSV/XLSX ingestion
* PDF extraction
* image extraction
* RapidOCR
* optional Ollama vision model integration
* normalized Pydantic invoice schema
* Decimal financial handling
* GSTIN format/state/checksum validation
* arithmetic reconciliation
* CGST/SGST/IGST checks
* line-item validation
* source evidence
* human review
* JSON editor
* persistence using SQLite
* JSON export
* CSV export
* batch file upload
* source document retention
* browser smoke tests
* security/upload boundaries
* synthetic samples

Do not remove these capabilities unless replacing them with demonstrably better equivalents.

The current code has modules such as:

app/main.py
app/extraction.py
app/text_extract.py
app/vision.py
app/normalize.py
app/validation.py
app/tabular.py
app/models.py
app/store.py
app/static/*

The current system is already a strong ingestion/review baseline.

The job now is to evolve it substantially.

==================================================
3. YOUR OPERATING MODE
======================

Act as:

* senior backend engineer
* senior frontend engineer
* AI/document intelligence engineer
* OCR/VLM engineer
* GST-domain systems engineer
* security engineer
* product designer
* QA engineer
* hackathon strategist

Do your own technical research before selecting major libraries or models.

Use current documentation and current open-source ecosystem knowledge when evaluating:

* OCR engines
* document AI models
* vision-language models
* table extraction
* layout detection
* QR extraction
* PDF parsing
* GST/e-invoice verification possibilities
* anomaly detection
* confidence estimation
* image preprocessing
* handwriting recognition
* benchmark methodology

Do not add technology simply because it is popular.
Every dependency should have a concrete reason.

Prefer:

* open-source
* locally executable
* appropriately licensed
* offline-friendly
* deterministic where possible
* easy to demonstrate
* CPU/GPU practical
* robust over flashy

Do not fabricate accuracy claims.
Do not claim GST/legal verification unless an actual verification mechanism exists.
Do not claim model training unless a model has actually been trained.

==================================================
4. PRODUCT VISION
=================

Transform VYOM+ from:

"invoice extraction + validation"

into:

"AI-powered GST document intelligence, verification and risk-analysis platform."

Target workflow:

UPLOAD
↓
DOCUMENT CLASSIFICATION
↓
QUALITY ASSESSMENT
↓
INTELLIGENT PIPELINE ROUTING
↓
LAYOUT UNDERSTANDING
↓
OCR / VLM / TABLE EXTRACTION
↓
MULTI-MODEL CONSENSUS
↓
CANONICAL FINANCIAL SCHEMA
↓
GST + ACCOUNTING VALIDATION
↓
EXTERNAL VERIFICATION WHERE AVAILABLE
↓
ANOMALY / DUPLICATE / RISK ANALYSIS
↓
FIELD-LEVEL EVIDENCE + CONFIDENCE
↓
HUMAN REVIEW
↓
AUDIT TRAIL
↓
ACCOUNTING-READY EXPORT

==================================================
5. PRIORITY 0: HANDWRITTEN INVOICE INTELLIGENCE
===============================================

This is the most important feature.

Build a dedicated handwritten-document processing pipeline.

The system must distinguish among:

* printed invoice
* digitally generated invoice
* scanned printed invoice
* handwritten invoice
* mixed printed + handwritten invoice
* poor-quality scan

Do not depend only on generic OCR.

Investigate and implement the strongest practical combination available for the environment, potentially involving:

* RapidOCR or another local OCR engine
* OCR preprocessing variants
* image-capable local VLM
* document layout models
* handwriting-capable vision models
* region-based extraction

Pipeline should conceptually become:

INPUT IMAGE
↓
IMAGE QUALITY ANALYSIS
↓
ORIENTATION / DESKEW
↓
PERSPECTIVE CORRECTION
↓
DENOISE / CONTRAST / SHARPEN
↓
TEXT REGION / LAYOUT DETECTION
↓
HANDWRITING DETECTION
↓
REGION-SPECIFIC EXTRACTION
↓
OCR + VLM
↓
CONSENSUS / CONFLICT ENGINE
↓
NORMALIZED RECORD
↓
VALIDATION

Important:
Do not automatically "repair" uncertain characters.

For example:

OCR:
27AAPFUO939F1ZV

VLM:
27AAPFU0939F1ZV

The system must mark the field as uncertain/conflicting rather than silently deciding.

==================================================
6. IMAGE PREPROCESSING ENGINE
=============================

Implement a preprocessing pipeline capable of creating multiple representations of a page:

* original
* orientation corrected
* grayscale
* autocontrast
* adaptive threshold
* sharpened
* denoised
* upscaled
* deskewed
* perspective corrected

Allow the extraction engine to choose the strongest representation per region.

Record preprocessing decisions as metadata.

Do not destroy the original source.

==================================================
7. DOCUMENT QUALITY SCORING
===========================

Before extraction, calculate document quality indicators such as:

* blur
* brightness
* contrast
* skew
* resolution
* estimated readability
* handwriting likelihood
* table likelihood

Produce a quality summary such as:

Document Quality: 67/100
Blur: Medium
Contrast: Poor
Rotation: 3.2°
Handwriting: Detected
Table: Detected

This must influence routing.

==================================================
8. INTELLIGENT PIPELINE ROUTER
==============================

Create an explicit routing layer.

Example:

CSV/XLSX
-> tabular pipeline

native PDF with usable text
-> native PDF parser

scanned PDF
-> page rendering + OCR

printed image
-> OCR + layout extraction

handwritten image
-> handwriting/VLM pipeline

mixed-content document
-> region-aware hybrid pipeline

very low quality document
-> enhanced preprocessing + VLM + review

Record why a route was selected.

Expose this in the UI.

Example:

Pipeline:
Handwriting Vision + OCR Consensus

Reason:
Handwritten content detected with low OCR confidence.

==================================================
9. LAYOUT UNDERSTANDING
=======================

Implement document layout understanding.

Detect important regions such as:

* invoice header
* supplier block
* buyer block
* billing address
* shipping address
* invoice number
* invoice date
* GSTIN
* place of supply
* line-item table
* subtotal
* discount
* GST summary
* grand total
* payment details
* bank details
* QR code
* signature/stamp

Do not assume all invoices have the same visual layout.

The system should be template-independent.

==================================================
10. TABLE / LINE-ITEM EXTRACTION
================================

Improve the current table extraction substantially.

Support common variations of headers such as:

Description
Item
Particulars
Product
HSN
HSN/SAC
Qty
Quantity
UOM
Rate
Unit Price
Discount
Taxable Value
GST
CGST
SGST
IGST
CESS
Amount
Total

Handle:

* wrapped item descriptions
* missing columns
* merged cells
* multi-line items
* variable spacing
* native PDF table collapse
* OCR coordinate reconstruction
* handwritten rows where practical

Line-item extraction should provide:

* row confidence
* field evidence
* source region
* extraction method

==================================================
11. FIELD-LEVEL CONFIDENCE
==========================

Move beyond document-level confidence.

Every important field should support a confidence/evidence representation.

At minimum:

* invoice number
* date
* supplier name
* supplier GSTIN
* buyer name
* buyer GSTIN
* place of supply
* HSN/SAC
* quantity
* unit price
* taxable value
* tax rate
* CGST
* SGST
* IGST
* grand total

Example:

Supplier GSTIN
27AAPFU0939F1ZV

Confidence:
92%

Evidence:
OCR + VLM agree

Validation:
Checksum valid
State code valid

==================================================
12. OCR + VLM CONSENSUS ENGINE
==============================

Create a reusable consensus engine.

Potential inputs:

* OCR
* VLM
* native PDF text
* QR contents
* deterministic arithmetic
* cross-document knowledge

For critical fields compare all observations.

Example:

Grand Total
OCR: ₹11,800
VLM: ₹11,800
Arithmetic: ₹11,800

=> HIGH CONFIDENCE

Another example:

OCR: ₹11,800
VLM: ₹11,600
Arithmetic: ₹11,800

=> CONFLICT
=> HUMAN REVIEW

The final engine should never hide conflicts.

==================================================
13. VISUAL EVIDENCE
===================

This is a major UX feature.

Allow users to click an extracted field and visually inspect where it came from in the original document.

Example:

GSTIN
27AAPFU0939F1ZV

When clicked:

* highlight source region
* show original visual crop if useful
* show OCR reading
* show VLM reading
* show confidence
* show validation
* show conflicts

This should make the system highly explainable.

==================================================
14. SOURCE PROVENANCE
=====================

For every field where practical, preserve:

* extraction source
* page number
* source region/bounding box
* OCR/VLM/native text origin
* original evidence text
* preprocessing path

Never allow the review editor to fake AI provenance.

Human corrections must be explicitly represented as corrections.

==================================================
15. HANDWRITING REVIEW WORKFLOW
===============================

Build a dedicated human review UX for uncertain handwriting.

For example:

FIELD:
Supplier GSTIN

AI:
27AAPFU0?39F1ZV

Status:
UNCERTAIN

Possible alternatives:
27AAPFU0939F1ZV

Source:
[highlighted region]

User can:

* accept
* edit
* reject
* mark unreadable

After correction:

* rerun deterministic validation
* show what changed
* keep original extraction
* store reviewer correction

==================================================
16. GST INTELLIGENCE ENGINE
===========================

Expand validation beyond basic syntax.

Current GST validation must be retained and improved.

Add logic around:

* GSTIN structure
* state code
* checksum
* supplier/buyer GSTIN consistency
* place of supply
* interstate vs intrastate
* CGST/SGST vs IGST
* tax rates
* taxable value
* round-off
* cess
* reverse charge
* credit notes
* debit notes
* special tax cases as review flags

Be careful with exceptions such as SEZ and reverse-charge scenarios.

Never overstate deterministic assumptions as legal conclusions.

==================================================
17. GSTIN EXTERNAL VERIFICATION
===============================

Investigate current official/legitimate mechanisms for GSTIN verification.

Where an authorized and technically available integration can be safely implemented:

* retrieve registration information
* status
* legal name
* trade name
* state
* registration metadata where permitted

Compare extracted supplier information against verified information.

Example:

Extracted supplier:
ABC TRADERS

Verified GST legal name:
ABC Traders Private Limited

Status:
ACTIVE

Match:
Likely

Important:
If no legitimate API/integration is available in the hackathon environment, implement a clean adapter interface and mock/demo mode rather than fabricating live verification.

Clearly distinguish:

FORMAT VALID
from
REGISTRATION VERIFIED

==================================================
18. QR CODE INTELLIGENCE
========================

Implement QR detection and decoding.

Extract relevant data from GST/e-invoice QR codes where present.

Compare QR data with invoice extraction.

Example:

Supplier GSTIN
Invoice number
Invoice date
Total amount
IRN

Then compare:

OCR
VLM
QR

Display:

✓ All sources agree

or:

⚠ QR and visible invoice disagree

==================================================
19. IRN / E-INVOICE INTELLIGENCE
================================

Detect and extract:

* IRN
* acknowledgement number
* acknowledgement date
* e-invoice identifiers

Create an abstraction for e-invoice verification.

Where real verification is unavailable, support:

* extraction
* format validation
* QR cross-validation
* consistency checking

Do not claim actual verification unless performed against a real authoritative source.

==================================================
20. E-WAY BILL SUPPORT
======================

Detect e-way bill numbers when present.

Extract where applicable:

* EWB number
* transport information
* vehicle number
* document linkage

At minimum support detection and consistency checks.

==================================================
21. DUPLICATE INVOICE DETECTION
===============================

Create cross-document duplicate detection.

Compare:

* supplier GSTIN
* supplier name
* invoice number
* invoice date
* grand total
* line items
* document similarity

Generate:

Duplicate risk:
High / Medium / Low

Explain why.

Example:

Possible duplicate invoice

Same supplier GSTIN
Same invoice number
Same date
Same total

Similarity:
96%

==================================================
22. CROSS-DOCUMENT ANOMALY DETECTION
====================================

Introduce historical/contextual intelligence.

Examples:

* unusually high invoice amount
* unusual GST rate for supplier
* sudden supplier identity change
* duplicate invoice
* unusual invoice frequency
* broken invoice number sequence
* repeated same-value invoices
* unexpected tax regime
* invoice much larger than supplier baseline

Use interpretable anomaly rules first.

Machine-learning anomaly detection may be added only if it genuinely helps.

==================================================
23. SUPPLIER INTELLIGENCE
=========================

Create a supplier profile from uploaded documents.

Show:

* invoice count
* total value
* average invoice
* GST rates
* common HSN/SAC
* common place of supply
* anomaly count
* duplicate count

Do not require a complicated database.

SQLite or another existing persistence layer can be extended.

==================================================
24. INVOICE SEQUENCE CHECKING
=============================

For suppliers with recognizable invoice-number sequences:

Detect suspicious gaps.

Example:

INV-1001
INV-1002
INV-1004

Possible gap:
INV-1003

This should be a REVIEW SIGNAL, never an accusation.

==================================================
25. RISK SCORING
================

Create a transparent invoice risk score.

Example factors:

* invalid GSTIN
* missing mandatory fields
* arithmetic mismatch
* OCR/VLM conflict
* QR mismatch
* duplicate similarity
* suspicious tax regime
* unusual amount
* supplier anomaly
* poor document quality

Show:

Risk Score: 72/100
Risk Level: REVIEW

And clearly explain contributing factors.

Do NOT create a black-box score with no explanation.

==================================================
26. ACCOUNTING READINESS SCORE
==============================

Provide another useful concept:

"Accounting Readiness"

Example:

Accounting Readiness:
89%

Blocked by:

* supplier GSTIN needs confirmation
* buyer GSTIN missing

This is more useful than pretending every extraction is fully correct.

==================================================
27. BATCH PROCESSING
====================

Improve existing multi-upload into a batch workspace.

Show:

Files:
47

Processed:
47/47

Validated:
31

Needs Review:
11

Invalid:
5

High Risk:
3

Average extraction quality:
91%

Allow filtering and sorting.

==================================================
28. SEARCH
==========

Implement full-text-like search over stored records.

Search by:

* invoice number
* GSTIN
* supplier
* buyer
* date
* HSN/SAC
* amount
* IRN
* EWB
* filename

Keep the implementation practical for the current storage layer.

==================================================
29. FILTERS
===========

Support filters for:

* status
* risk
* date
* supplier
* GSTIN
* document type
* extraction method
* handwriting
* needs review
* duplicate candidates

==================================================
30. ANALYTICS DASHBOARD
=======================

Create a meaningful dashboard.

Metrics:

* total documents
* total invoices
* total taxable value
* total tax
* grand total
* CGST
* SGST
* IGST
* CESS
* validated
* needs review
* invalid
* duplicate candidates
* high-risk records

Charts can include:

* invoice volume over time
* total invoice value over time
* tax breakdown
* supplier distribution
* status distribution
* anomaly distribution

Do not make the dashboard decorative.
Every chart should serve a decision.

==================================================
31. AUDIT TRAIL
===============

Track:

* extraction completed
* validation executed
* field changed
* reviewer correction
* reviewer confirmation
* revalidation
* export
* deletion

Store:

* timestamp
* action
* field
* old value
* new value
* reason where available

This is particularly important for financial data.

==================================================
32. REVIEW QUEUE
================

Create a proper review queue.

Sort unresolved records by:

* risk
* confidence
* number of errors
* number of conflicts
* document quality

A reviewer should immediately see:

1. what requires attention
2. why
3. where it came from
4. what action is needed

==================================================
33. BULK ACTIONS
================

Implement safe bulk actions where appropriate:

* mark reviewed
* export selected
* retry extraction
* filter unresolved
* delete selected

Never allow bulk operations to bypass critical validation.

==================================================
34. BETTER JSON SCHEMA
======================

Extend the canonical model only when justified.

Potential fields:

* IRN
* acknowledgement number/date
* EWB number
* PO number
* due date
* billing address
* shipping address
* payment terms
* vehicle number
* transport mode
* bank details
* TDS/TCS
* additional charges
* freight
* packing
* other charges

Maintain backwards compatibility where practical.

==================================================
35. BETTER EXPORTS
==================

Retain:

* JSON
* CSV

Add where useful:

* validation report
* audit report
* batch summary
* risk report

Exports must contain enough context to be useful downstream.

==================================================
36. API DESIGN
==============

Keep the existing REST API stable where practical.

Add clean APIs for:

* quality assessment
* extraction metadata
* field evidence
* risk
* duplicate search
* analytics
* review queue
* audit history
* verification
* QR/IRN
* retry/reprocess

Use strict schemas.

Return useful error messages.

==================================================
37. FRONTEND
============

Do NOT replace the current UI merely for technology preference.

Improve the current interface.

The UI should communicate:

* what the AI found
* what is trustworthy
* what is uncertain
* what is wrong
* what the user needs to fix

Recommended review screen:

LEFT:
Original document

RIGHT:
Structured extraction

Click field:

* highlight source
* show confidence
* show evidence
* show validation

Top:
Overall status
Risk
Accounting readiness

Tabs/sections:

Overview
Fields
Line Items
Issues
Evidence
Risk
Audit Trail
Raw Text
JSON

==================================================
38. DEMO-FIRST UX
=================

The product must be exceptionally easy to demonstrate to judges.

A judge should be able to:

1. upload handwritten invoice
2. watch intelligent processing
3. see handwriting detection
4. see extracted invoice fields
5. see highlighted evidence
6. see confidence
7. see OCR/VLM agreement or conflict
8. see GST validation
9. see QR verification if present
10. see risk analysis
11. correct one field
12. revalidate
13. export final structured record

Do not make the judge explore six menus to understand the point.

==================================================
39. BENCHMARK / EVALUATION SYSTEM
=================================

This is mandatory.

Create a benchmark harness.

Dataset structure should support categories:

* printed
* scanned
* handwritten
* poor-quality
* multi-layout
* mixed documents

Calculate:

* invoice number exact accuracy
* date exact accuracy
* GSTIN exact accuracy
* supplier exact accuracy
* buyer exact accuracy
* taxable amount accuracy
* tax amount accuracy
* grand total accuracy
* line-item recall
* line-item precision where practical
* field-level correction rate
* OCR/VLM disagreement rate
* validation error rate

Produce machine-readable benchmark results.

Do not invent benchmark numbers.

==================================================
40. TESTING
===========

Expand current tests substantially.

Add:

* handwritten fixtures
* multiple layouts
* badly rotated images
* blurry images
* low contrast
* mixed handwriting/print
* QR codes
* duplicate invoices
* anomaly scenarios
* conflicting OCR/VLM
* missing GSTIN
* incorrect GSTIN
* tax regime conflicts
* source evidence
* risk scoring
* audit trail
* batch processing
* search
* analytics APIs

Retain all existing tests.

Run:

pytest
ruff
compile checks
frontend syntax checks

Add integration tests for any new services.

==================================================
41. SECURITY
============

Preserve existing security protections.

Review for:

* path traversal
* decompression bombs
* malicious PDFs
* oversized images
* oversized spreadsheets
* formula injection
* unsafe HTML
* prompt injection from invoice contents
* model output validation
* uploaded document isolation
* SSRF
* untrusted external URLs
* QR contents
* remote model endpoints

Treat invoice contents as untrusted input.

Never let a document tell the AI what system instructions to follow.

Never allow model-generated values to bypass deterministic validation.

==================================================
42. LOCAL-FIRST / MODEL STRATEGY
================================

Prefer a local-first architecture.

Model configuration should be flexible.

Support configurable:

* OCR engine
* VLM model
* VLM endpoint
* extraction mode

The system should gracefully degrade if a VLM is unavailable.

Example:

No VLM:
OCR + parser + review

VLM available:
OCR + VLM + consensus

Higher-end model available:
improved handwriting/layout extraction

==================================================
43. OBSERVABILITY
=================

Add useful processing metadata:

* processing time
* pipeline selected
* OCR time
* VLM time
* validation time
* number of pages
* number of records
* warnings
* fallback reason

Expose enough to debug the system.

==================================================
44. PERFORMANCE
===============

Do not make extraction unnecessarily slow.

Consider:

* page parallelism where safe
* cached preprocessing
* model reuse
* bounded concurrency
* batch operations
* asynchronous jobs if truly necessary

Do not introduce a complicated worker architecture unless the current architecture genuinely requires it.

==================================================
45. DEPENDENCY DISCIPLINE
=========================

Before adding dependencies:

* investigate alternatives
* verify license
* verify Python compatibility
* verify Windows/Linux support where practical
* verify local/offline behavior
* verify GPU requirements
* document setup

Do not add ten frameworks to solve one problem.

==================================================
46. DATABASE
============

The current SQLite design is sufficient for hackathon scale.

Extend it cleanly for:

* documents
* invoice records
* suppliers
* verification results
* audit events
* anomaly results
* review state

Only migrate away from SQLite if technically necessary.

==================================================
47. DOCUMENTATION
=================

Update README with:

* architecture
* setup
* model configuration
* handwritten workflow
* benchmark methodology
* API documentation
* security assumptions
* verification limitations
* deployment
* demo walkthrough

Clearly distinguish:

* extraction
* validation
* verification
* risk signal
* legal/compliance certification

==================================================
48. DEMO DATA
=============

Create high-quality synthetic demo documents covering:

1. clean printed invoice
2. scanned invoice
3. handwritten invoice
4. handwritten + printed invoice
5. invalid GSTIN
6. arithmetic mismatch
7. tax regime mismatch
8. duplicate invoice
9. QR mismatch
10. suspicious/high-risk invoice

The demo data must exercise the new features.

==================================================
49. DEVELOPMENT STRATEGY
========================

Do not try to implement everything as one giant fragile patch.

Work incrementally.

Recommended execution order:

PHASE A

* inspect current code
* identify extension points
* create architecture plan
* implement tests for new behavior

PHASE B

* quality assessment
* preprocessing
* intelligent router
* improved OCR/VLM pipeline

PHASE C

* layout extraction
* table extraction
* field-level confidence
* source bounding boxes

PHASE D

* consensus engine
* handwriting workflow
* human correction

PHASE E

* QR
* IRN
* EWB
* GST verification adapters

PHASE F

* duplicate detection
* anomaly detection
* risk scoring

PHASE G

* supplier intelligence
* analytics
* review queue
* audit trail

PHASE H

* benchmark harness
* demo fixtures
* UX polish
* documentation

==================================================
50. NON-NEGOTIABLE DESIGN RULES
===============================

1. Never silently invent invoice values.
2. Never silently repair uncertain GSTINs.
3. Never claim live GST verification without a real authoritative integration.
4. Never call OCR confidence field accuracy.
5. Never allow the LLM/VLM to bypass deterministic validation.
6. Never hide extraction conflicts.
7. Preserve original source documents.
8. Preserve provenance.
9. Human correction must remain distinguishable from AI extraction.
10. All financial calculations should use exact decimal arithmetic.
11. Keep current working functionality.
12. Avoid unnecessary rewrites.
13. Avoid unnecessary infrastructure.
14. Test before declaring a feature complete.
15. Do not fabricate benchmark results.

==================================================
51. "THINK LIKE A JUDGE"
========================

At every major implementation decision ask:

Why would a judge care?

The final system should visibly answer:

* Why is this better than ordinary OCR?
* Why is handwriting handling special?
* Why can I trust the extracted value?
* What happens when AI is uncertain?
* How is GST validated?
* How can I detect duplicates?
* How can I detect suspicious invoices?
* Where did this value come from?
* What did the human reviewer change?
* Can the final record be consumed downstream?

==================================================
52. "THINK LIKE A REAL ACCOUNTING USER"
=======================================

The user does NOT want:

"AI extracted some text."

They want:

"I uploaded 100 invoices and now I know:

* which records are valid
* which need review
* which are suspicious
* which are duplicates
* which GST details are inconsistent
* exactly where uncertain data came from
* what needs human attention
* and I can export the clean records."

Optimize for this outcome.

==================================================
53. FINAL QUALITY BAR
=====================

Do not stop when the feature technically works.

After implementation:

* run the complete test suite
* run linting
* run browser smoke/integration checks
* test every supported file type
* test handwritten workflow
* test failure paths
* inspect UI manually
* inspect source evidence
* test exports
* test persistence
* verify no regressions

Fix issues you discover.

The final project should feel cohesive.

Do not leave half-integrated features hidden in backend code.

==================================================
54. FINAL DELIVERABLE
=====================

The repository should end with:

* working full-stack application
* robust AI/document-intelligence pipeline
* handwriting-focused extraction
* explainable field-level confidence
* visual source evidence
* OCR/VLM consensus
* GST intelligence
* QR/IRN support
* verification adapters where legitimately possible
* duplicate detection
* anomaly detection
* risk scoring
* accounting-readiness scoring
* review workflow
* audit trail
* batch analytics
* strong UI
* benchmark harness
* comprehensive tests
* updated documentation

The goal is not to make the largest codebase.

The goal is to make VYOM+ the most convincing end-to-end GST invoice intelligence system possible within the available hackathon constraints.

Start by auditing the existing repository in detail, identifying all extension points and regressions risks, then implement the highest-value features in a coherent order.

Do not ask for permission for obvious engineering decisions.
Make reasonable decisions, document them, test them, and proceed.