"""Bounded, dependency-light document quality and preprocessing helpers.

The measurements here are routing signals, not trained document classifiers. They
are intentionally conservative and remain useful when no VLM or GPU is available.
The original uploaded file is never replaced; derived previews are written under a
private per-document directory for source comparison and later UI use.
"""

from __future__ import annotations

import io
import warnings as python_warnings
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

from .models import PageQuality, PreprocessingRepresentation, QualityAssessment

MAX_ANALYSIS_SIDE = 1600
MAX_ARTIFACT_BYTES = 6 * 1024 * 1024
MAX_ARTIFACT_TOTAL = 40 * 1024 * 1024
PDF_MAX_PAGES = 20
REPRESENTATION_NAMES = (
    "original",
    "orientation_corrected",
    "grayscale",
    "autocontrast",
    "adaptive_threshold",
    "sharpened",
    "denoised",
    "upscaled",
    "deskewed",
)


def _bounded_image(path: Path) -> Image.Image:
    """Load a user image with the same format and pixel boundaries as extraction."""

    try:
        with Image.open(path) as image:
            with python_warnings.catch_warnings():
                python_warnings.simplefilter("error", Image.DecompressionBombWarning)
                if image.format not in {"PNG", "JPEG"}:
                    raise ValueError("The file content must be a JPEG or PNG image.")
                if image.width * image.height > 25_000_000:
                    raise ValueError("Image exceeds 25 megapixels; resize it before uploading.")
                return ImageOps.exif_transpose(image).convert("RGB")
    except (
        UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning
    ) as exc:
        raise ValueError("Invalid or oversized image.") from exc


def _analysis_image(image: Image.Image) -> Image.Image:
    working = image.copy().convert("RGB")
    working.thumbnail((MAX_ANALYSIS_SIDE, MAX_ANALYSIS_SIDE), Image.Resampling.LANCZOS)
    return working


def _clip(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 4)


def _estimate_skew(gray: Image.Image) -> float | None:
    """Estimate signed page skew; its negative is the Pillow correction angle.

    Abstain when a +/-5 degree search has no distinct peak. This only measures
    small skew; upside-down/quarter-turn orientation requires a separate detector.
    """

    array = np.asarray(gray, dtype=np.uint8)
    if array.size == 0:
        return None
    threshold = min(210, max(120, int(np.percentile(array, 55))))
    ink = array < threshold
    if ink.mean() < 0.002 or ink.mean() > 0.7:
        return None
    sample = gray.copy()
    if max(sample.size) > 900:
        sample.thumbnail((900, 900), Image.Resampling.BILINEAR)
    candidates = np.arange(-5.0, 5.01, 0.5)
    scores = []
    for angle in candidates:
        with sample.rotate(float(angle), resample=Image.Resampling.BILINEAR, fillcolor=255) as rotated:
            rotated_ink = np.asarray(rotated, dtype=np.uint8) < threshold
            rows = rotated_ink.sum(axis=1).astype(np.float32)
            scores.append(float(rows.var()))
    sample.close()
    best = int(np.argmax(scores))
    if best in {0, len(scores) - 1} or max(scores) < np.median(scores) * 1.15:
        return None
    return round(-float(candidates[best]), 2)


def _table_likelihood(array: np.ndarray) -> float:
    """A ruled-grid signal, not a detector for borderless tables."""
    threshold = min(210, max(120, int(np.percentile(array, 65))))
    ink = array < threshold
    row_strength = ink.mean(axis=1)
    column_strength = ink.mean(axis=0)
    def bands(strength):
        active = strength > 0.45
        return int(np.count_nonzero(active & ~np.r_[False, active[:-1]]))

    horizontal, vertical = bands(row_strength), bands(column_strength)
    if horizontal < 2 or vertical < 2:
        return 0.0
    return _clip(min(horizontal, vertical) / 4)


def assess_image(image: Image.Image) -> QualityAssessment:
    """Return deterministic quality heuristics for one image/page."""

    working = _analysis_image(image)
    gray = ImageOps.grayscale(working)
    array = np.asarray(gray, dtype=np.float32)
    mean = float(array.mean()) if array.size else 0.0
    standard_deviation = float(array.std()) if array.size else 0.0
    laplacian = (
        array[:-2, 1:-1] + array[2:, 1:-1] + array[1:-1, :-2] + array[1:-1, 2:]
        - 4 * array[1:-1, 1:-1]
    )
    sharpness = _clip(float(laplacian.var()) / 350.0) if laplacian.size else 0.0
    blur = _clip(1.0 - sharpness)
    brightness = _clip(mean / 255.0)
    exposure_quality = _clip(brightness / 0.65)
    contrast = _clip(standard_deviation / 64.0)
    resolution = _clip(min(image.size) / 900.0)
    skew = _estimate_skew(gray)
    skew_quality = 1.0 if skew is None else _clip(1.0 - abs(skew) / 8.0)
    readability = _clip(
        (1.0 - blur) * 0.35
        + exposure_quality * 0.2
        + contrast * 0.25
        + resolution * 0.1
        + skew_quality * 0.1
    )
    table_likelihood = _table_likelihood(array)
    # Edge density does not distinguish print from handwriting. Leave unknown
    # until a handwriting detector has been evaluated on labelled examples.
    handwriting_likelihood = None
    if standard_deviation < 1:
        readability = 0.0
    score = round(
        max(
            0,
            min(
                100,
                100
                * (
                    (1.0 - blur) * 0.25
                    + exposure_quality * 0.15
                    + contrast * 0.2
                    + resolution * 0.15
                    + readability * 0.25
                ),
            ),
        )
    )
    notes = [
        "Quality values are deterministic routing heuristics, not field-accuracy probabilities.",
        "Handwriting likelihood is unknown; these image metrics are not handwriting recognition.",
        "Table signal measures ruled grids only; borderless tables may score zero.",
        "Brightness is mean luminance; blur and contrast are measured at a bounded analysis scale.",
    ]
    if blur > 0.45:
        notes.append("Blur signal is elevated; compare OCR values with the original source.")
    if contrast < 0.35:
        notes.append("Contrast is low; contrast enhancement may help source review.")
    if resolution < 0.45:
        notes.append("Resolution is limited for small text and line-item details.")
    gray.close()
    working.close()
    return QualityAssessment(
        applicable=True,
        score=score,
        width=image.width,
        height=image.height,
        blur=blur,
        brightness=brightness,
        contrast=contrast,
        resolution=resolution,
        skew_degrees=skew,
        readability=readability,
        handwriting_likelihood=handwriting_likelihood,
        table_likelihood=table_likelihood,
        notes=notes,
    )


def _adaptive_threshold(gray: Image.Image) -> Image.Image:
    array = np.asarray(gray, dtype=np.uint8)
    local = np.asarray(gray.filter(ImageFilter.BoxBlur(7)), dtype=np.int16)
    thresholded = np.where(array < local - 8, 0, 255).astype(np.uint8)
    return Image.fromarray(thresholded)


def _representations(image: Image.Image, skew: float | None) -> dict[str, Image.Image]:
    working = _analysis_image(image)
    gray = ImageOps.grayscale(working)
    autocontrast = ImageOps.autocontrast(gray)
    sharpened = autocontrast.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
    denoised = autocontrast.filter(ImageFilter.MedianFilter(size=3))
    upscaled = autocontrast.copy()
    if max(autocontrast.size) < 2400:
        scale = min(1.5, 2400 / max(autocontrast.size))
        upscaled = autocontrast.resize(
          tuple(max(1, round(value * scale)) for value in autocontrast.size),
            Image.Resampling.LANCZOS,
        )
    deskewed = autocontrast.copy()
    if skew is not None and abs(skew) >= 0.25:
        deskewed = autocontrast.rotate(
            -skew, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255
        )
        deskewed.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
    return {
        "orientation_corrected": working,
        "grayscale": gray,
        "autocontrast": autocontrast,
        "adaptive_threshold": _adaptive_threshold(gray),
        "sharpened": sharpened,
        "denoised": denoised,
        "upscaled": upscaled,
        "deskewed": deskewed,
    }


def _write_representation(
    image: Image.Image,
    target: Path,
    written_bytes: int,
) -> int | None:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=3)
    payload = buffer.getvalue()
    if len(payload) > MAX_ARTIFACT_BYTES or written_bytes + len(payload) > MAX_ARTIFACT_TOTAL:
        return None
    target.write_bytes(payload)
    target.chmod(0o600)
    return written_bytes + len(payload)


def _retain_page(
    image: Image.Image,
    page_number: int,
    artifact_dir: Path,
    artifact_prefix: str,
    written_bytes: int,
) -> tuple[QualityAssessment, list[PreprocessingRepresentation], int, list[str]]:
    quality = assess_image(image)
    artifacts = [
        PreprocessingRepresentation(
            name="original",
            page_number=page_number,
            artifact_path=None,
            width=image.width,
            height=image.height,
            format="source",
        )
    ]
    warnings = []
    transformed = _representations(image, quality.skew_degrees)
    page_dir = artifact_dir
    page_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, transformed_image in transformed.items():
        target = page_dir / f"page-{page_number}-{name}.png"
        updated_bytes = _write_representation(transformed_image, target, written_bytes)
        if updated_bytes is None:
            warnings.append(f"Preprocessing representation skipped due to the bounded artifact limit: {name}.")
            transformed_image.close()
            continue
        written_bytes = updated_bytes
        artifacts.append(
            PreprocessingRepresentation(
                name=name,
                page_number=page_number,
                artifact_path=f"{artifact_prefix}/page-{page_number}-{name}.png",
                width=transformed_image.width,
                height=transformed_image.height,
                applied=(skew_applied(quality) if name == "deskewed" else True),
                reason=(
                    "Small-skew estimate unavailable or negligible; preview is unchanged."
                    if name == "deskewed" and not skew_applied(quality) else None
                ),
            )
        )
        transformed_image.close()
    return quality, artifacts, written_bytes, warnings


def skew_applied(quality: QualityAssessment) -> bool:
    return quality.skew_degrees is not None and abs(quality.skew_degrees) >= 0.25


def _aggregate(qualities: list[QualityAssessment]) -> QualityAssessment:
    if not qualities:
        return QualityAssessment(applicable=False, score=None, notes=["No visual page was available for quality assessment."])
    metric_names = (
        "blur",
        "brightness",
        "contrast",
        "resolution",
        "readability",
        "handwriting_likelihood",
        "table_likelihood",
    )
    values = {}
    for name in metric_names:
        available = [getattr(item, name) for item in qualities if getattr(item, name) is not None]
        values[name] = round(sum(available) / len(available), 4) if available else None
    skewed = max(
        (item for item in qualities if item.skew_degrees is not None),
        key=lambda item: abs(item.skew_degrees or 0),
        default=None,
    )
    notes = list(dict.fromkeys(note for item in qualities for note in item.notes))
    if len(qualities) > 1:
        notes.insert(0, f"Aggregated across {len(qualities)} visual page(s); the lowest page score drives review routing.")
    return QualityAssessment(
        applicable=True,
        score=min(item.score for item in qualities if item.score is not None),
        width=max(item.width or 1 for item in qualities),
        height=max(item.height or 1 for item in qualities),
        skew_degrees=skewed.skew_degrees if skewed else None,
        notes=notes,
        **values,
    )


def ocr_enhancement(quality: QualityAssessment) -> str:
    """Select a photometric enhancement without moving evidence coordinates."""

    if quality.blur is not None and quality.blur > 0.45 and (quality.contrast or 0) > 0.01:
        return "sharpened"
    return "autocontrast"


def analyze_and_retain(
    path: Path,
    kind: str,
    artifact_dir: Path,
    artifact_prefix: str,
) -> tuple[
    QualityAssessment,
    list[PageQuality],
    list[PreprocessingRepresentation],
    list[str],
]:
    """Assess visual input and retain bounded derived page representations."""

    qualities = []
    page_quality = []
    artifacts = []
    warnings = []
    written_bytes = 0
    if kind in {"png", "jpeg"}:
        image = _bounded_image(path)
        try:
            quality, page_artifacts, written_bytes, page_warnings = _retain_page(
                image, 1, artifact_dir, artifact_prefix, written_bytes
            )
            qualities.append(quality)
            page_quality.append(PageQuality(page_number=1, assessment=quality))
            artifacts.extend(page_artifacts)
            warnings.extend(page_warnings)
        finally:
            image.close()
    elif kind == "pdf":
        try:
            pdf = pdfium.PdfDocument(path)
        except Exception as exc:
            raise ValueError("Cannot open PDF. It may be corrupted or password protected.") from exc
        try:
            if not 1 <= len(pdf) <= PDF_MAX_PAGES:
                raise ValueError(f"PDF must contain 1–{PDF_MAX_PAGES} pages; split larger files.")
            for index in range(len(pdf)):
                page = pdf[index]
                bitmap = None
                image = None
                try:
                    width, height = page.get_size()
                    if min(width, height) <= 0:
                        raise ValueError("Invalid PDF page dimensions.")
                    bitmap = page.render(scale=min(1.8, 1600 / max(width, height)))
                    image = bitmap.to_pil().convert("RGB")
                    quality, page_artifacts, written_bytes, page_warnings = _retain_page(
                        image, index + 1, artifact_dir, artifact_prefix, written_bytes
                    )
                    qualities.append(quality)
                    page_quality.append(PageQuality(page_number=index + 1, assessment=quality))
                    artifacts.extend(page_artifacts)
                    warnings.extend(page_warnings)
                finally:
                    if image is not None:
                        image.close()
                    if bitmap is not None:
                        bitmap.close()
                    page.close()
        finally:
            pdf.close()
    else:
        return QualityAssessment(
            applicable=False,
            score=None,
            notes=["Visual quality metrics do not apply to structured tabular input."],
        ), [], [], []
    return _aggregate(qualities), page_quality, artifacts, list(dict.fromkeys(warnings))
