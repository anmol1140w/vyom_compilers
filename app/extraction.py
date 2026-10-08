"""Local PDF/image extraction: native text, OCR preprocessing, optional VLM."""

import importlib.util
import re
import threading
import warnings as python_warnings
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

from .models import BoundingBox, SourceObservation
from .provenance import attach_invoice_provenance
from .text_extract import parse_text
from .vision import extract_vision, vision_model

MAX_PAGES = 20
MAX_PIXELS = 25_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
_engine = None
_engine_lock = threading.Lock()


def ocr_available():
    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


def read_image(path: Path) -> Image.Image:
    try:
        with python_warnings.catch_warnings():
            python_warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format not in {"PNG", "JPEG"}:
                    raise ValueError("The file content must be a JPEG or PNG image.")
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError("Image exceeds 25 megapixels; resize it before uploading.")
                return ImageOps.exif_transpose(image).convert("RGB")
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("Invalid or oversized image.") from exc


def ocr(
    image: Image.Image,
    include_regions: bool = False,
    preprocessing: str = "autocontrast",
):
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
        image = image.copy()
        image.thumbnail((2400, 2400))
        image = ImageOps.autocontrast(ImageOps.grayscale(image))
        if preprocessing == "sharpened":
            image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
        image = image.convert("RGB")
        image_width, image_height = image.size
        result, _ = _engine(np.asarray(image))
    if not result:
        return ("", None, []) if include_regions else ("", None)
    # Restore rows from bounding boxes instead of flattening multi-column tables.
    boxes = []
    regions = []
    for box, value, score in result:
        y = sum(point[1] for point in box) / 4
        height = max(point[1] for point in box) - min(point[1] for point in box)
        left = min(point[0] for point in box)
        top = min(point[1] for point in box)
        right = max(point[0] for point in box)
        bottom = max(point[1] for point in box)
        score = float(score)
        boxes.append((y, left, max(height, 1), value, score))
        regions.append(
            SourceObservation(
                source="ocr",
                text=str(value),
                bounding_box=BoundingBox(
                    x=max(0, min(1, left / max(image_width, 1))),
                    y=max(0, min(1, top / max(image_height, 1))),
                    width=max(0, min(1, (right - left) / max(image_width, 1))),
                    height=max(0, min(1, (bottom - top) / max(image_height, 1))),
                ),
                recognition_score=score,
                preprocessing=f"grayscale+{preprocessing}",
            )
        )
    rows = []
    for box in sorted(boxes):
        if rows and abs(box[0] - rows[-1][0][0]) < max(box[2], rows[-1][0][2]) * 0.5:
            rows[-1].append(box)
        else:
            rows.append([box])
    contents = "\n".join(
        "  ".join(box[3] for box in sorted(row, key=lambda b: b[1])) for row in rows
    )
    score = sum(len(box[3]) * box[4] for box in boxes) / max(1, sum(len(box[3]) for box in boxes))
    return (contents, round(score, 4), regions) if include_regions else (contents, round(score, 4))


def native_pdf_text(page) -> str:
    text_page = page.get_textpage()
    try:
        return text_page.get_text_bounded()
    finally:
        text_page.close()


def _page_records(image, native, handwriting, page_number, preprocessing):
    warnings = []
    method = "pdf_text" if native else "ocr"
    confidence = None
    raw = native
    observations = []
    if native:
        observations.append(
            SourceObservation(source="native_text", page_number=page_number, text=native[:10000])
        )
    if not native:
        try:
            raw, confidence, regions = ocr(
                image, include_regions=True, preprocessing=preprocessing
            )
            observations.extend(
                observation.model_copy(update={"page_number": page_number})
                for observation in regions
            )
            if raw:
                observations.insert(
                    0,
                    SourceObservation(
                        source="ocr",
                        page_number=page_number,
                        text=raw[:10000],
                        recognition_score=confidence,
                        preprocessing=f"grayscale+{preprocessing}",
                    ),
                )
        except Exception as exc:
            warnings.append(f"Local OCR unavailable/failed ({type(exc).__name__}).")
            raw = ""
        if confidence is not None and confidence < 0.85:
            warnings.append(
                f"Low OCR recognition score ({confidence:.0%}); this is not field-level accuracy."
            )
    if image is not None and vision_model():
        try:
            records = extract_vision(image)
            observations.append(
                SourceObservation(
                    source="vision",
                    page_number=page_number,
                    metadata={"evidence": "model-produced"},
                )
            )
            if raw and len(records) == 1:
                baseline, _ = parse_text(raw, method, confidence)
                comparisons = {
                    "invoice_number": (baseline.invoice_number, records[0].invoice_number),
                    "supplier.gstin": (baseline.supplier.gstin, records[0].supplier.gstin),
                    "totals.grand_total": (
                        baseline.totals.grand_total,
                        records[0].totals.grand_total,
                    ),
                }
                for field, (observed, predicted) in comparisons.items():
                    if observed is not None and predicted is not None and observed != predicted:
                        warnings.append(
                            f"OCR/text and vision disagree on {field}; compare both readings with the source."
                        )
            return (
                records,
                raw,
                "local_vision",
                warnings
                + [
                    "Vision output requires source comparison; evidence text is model-produced, not independently verified."
                ],
                observations,
            )
        except Exception as exc:
            warnings.append(
                f"Vision extraction failed ({type(exc).__name__}); used conservative OCR/text fallback."
            )
    if handwriting and not vision_model():
        warnings.append(
            "Handwriting mode requested but no local vision model configured. Printed-text OCR is a fallback, not reliable handwriting recognition."
        )
    invoice, parse_warnings = parse_text(raw, method, confidence)
    return [invoice], raw, method, warnings + parse_warnings, observations


def extract_document(
    path: Path,
    kind: str,
    handwriting: bool = False,
    include_observations: bool = False,
    preprocessing: str = "autocontrast",
):
    records, chunks, methods, warnings, observations = [], [], [], [], []

    def consume(image, native, page_number):
        extracted, raw, method, notes, page_observations = _page_records(
            image, native, handwriting, page_number, preprocessing
        )
        for invoice in extracted:
            invoice.field_evidence["page"] = str(page_number)
            attach_invoice_provenance(
                invoice, page_number=page_number, observations=page_observations
            )
            existing = next(
                (
                    record
                    for record in records
                    if invoice.invoice_number
                    and record.invoice_number == invoice.invoice_number
                    and record.supplier.gstin == invoice.supplier.gstin
                ),
                None,
            )
            if existing:
                # Never silently collapse ambiguous repeated invoices or multipage records.
                warnings.append(
                    f"Page {page_number}: repeated invoice identity retained separately; review continuation/duplicate handling."
                )
            records.append(invoice)
        chunks.append(f"--- Page {page_number} ---\n{raw}")
        methods.append(method)
        warnings.extend(f"Page {page_number}: {note}" for note in notes)
        observations.extend(page_observations)

    if kind in {"png", "jpeg"}:
        consume(read_image(path), "", 1)
    else:
        try:
            pdf = pdfium.PdfDocument(path)
        except Exception as exc:
            raise ValueError("Cannot open PDF. It may be corrupted or password protected.") from exc
        try:
            if not 1 <= len(pdf) <= MAX_PAGES:
                raise ValueError(f"PDF must contain 1–{MAX_PAGES} pages; split larger files.")
            for index in range(len(pdf)):
                page = pdf[index]
                bitmap = None
                image = None
                try:
                    native = native_pdf_text(page)
                    if len(native) > 100000:
                        raise ValueError("PDF page contains too much text for safe processing.")
                    usable = len(native.strip()) >= 80 and re.search(
                        r"(?:invoice|GSTIN|taxable)", native, re.I
                    )
                    if not usable or handwriting or vision_model():
                        width, height = page.get_size()
                        if min(width, height) <= 0:
                            raise ValueError("Invalid PDF page dimensions.")
                        bitmap = page.render(scale=min(2.5, 2400 / max(width, height)))
                        image = bitmap.to_pil().convert("RGB")
                    consume(image, native if usable else "", index + 1)
                finally:
                    if image is not None:
                        image.close()
                    if bitmap is not None:
                        bitmap.close()
                    page.close()
        finally:
            pdf.close()
    raw_text = "\n\n".join(chunks)
    if len(raw_text) > 300000:
        warnings.append("Extracted text preview truncated at 300,000 characters.")
    if handwriting:
        warnings.append(
            "Handwritten fields require human verification, even if arithmetic and GST checks pass."
        )
    result = (
        records,
        raw_text[:300000],
        " + ".join(dict.fromkeys(methods)),
        list(dict.fromkeys(warnings)),
    )
    return (*result, observations) if include_observations else result
