"""Conservative page-layout regions derived from OCR/native-text observations.

This module intentionally avoids a trained detector. It groups nearby OCR boxes into
reading rows and labels those rows using transparent text and geometry rules. Regions
are evidence for review and routing; they do not alter normalized invoice values.
"""

from __future__ import annotations

from collections import defaultdict

from .models import BoundingBox, LayoutRegion, SourceObservation


def _classify(text: str, bounding_box: BoundingBox | None) -> str:
    value = " ".join(text.casefold().split())
    if any(token in value for token in ("qr code", "upi", "irn", "ack no")):
        return "qr"
    if any(token in value for token in ("signature", "authorised signatory", "authorized signatory")):
        return "signature"
    if any(token in value for token in ("bank", "account no", "ifsc", "payment", "upi id")):
        return "payment"
    if any(
        token in value
        for token in (
            "grand total",
            "invoice total",
            "amount payable",
            "net payable",
            "round off",
        )
    ):
        return "totals"
    if any(token in value for token in ("description", "particulars", "hsn", "qty", "quantity", "unit price")):
        return "line_items"
    if any(token in value for token in ("cgst", "sgst", "igst", "utgst", "cess", "tax summary")):
        return "tax_summary"
    if any(token in value for token in ("supplier", "seller", "vendor", "from:")):
        return "supplier"
    if any(token in value for token in ("buyer", "customer", "bill to", "billed to", "recipient")):
        return "buyer"
    if any(token in value for token in ("invoice no", "invoice number", "invoice date", "place of supply")):
        return "invoice_metadata"
    if bounding_box is not None and bounding_box.y < 0.18:
        return "header"
    if bounding_box is None and (value.startswith("tax invoice") or value == "invoice"):
        return "header"
    return "unknown"


def _union(boxes: list[BoundingBox]) -> BoundingBox:
    left = min(box.x for box in boxes)
    top = min(box.y for box in boxes)
    right = max(box.x + box.width for box in boxes)
    bottom = max(box.y + box.height for box in boxes)
    return BoundingBox(
        x=max(0, min(1, left)),
        y=max(0, min(1, top)),
        width=max(0, min(1, right - left)),
        height=max(0, min(1, bottom - top)),
    )


def _ocr_regions(page_observations: list[tuple[int, SourceObservation]]) -> list[LayoutRegion]:
    rows: list[list[tuple[int, SourceObservation]]] = []
    for index, observation in sorted(
        page_observations,
        key=lambda item: (
            item[1].bounding_box.y if item[1].bounding_box else 0,
            item[1].bounding_box.x if item[1].bounding_box else 0,
        ),
    ):
        box = observation.bounding_box
        if box is None:
            continue
        center = box.y + box.height / 2
        matching = None
        for row in rows:
            row_boxes = [item.bounding_box for _, item in row if item.bounding_box]
            row_center = sum(item.y + item.height / 2 for item in row_boxes) / len(row_boxes)
            tolerance = max(0.012, max(item.height for item in row_boxes) * 0.8)
            if abs(center - row_center) <= tolerance:
                matching = row
                break
        if matching is None:
            rows.append([(index, observation)])
        else:
            matching.append((index, observation))

    regions = []
    for row in rows:
        ordered = sorted(row, key=lambda item: item[1].bounding_box.x if item[1].bounding_box else 0)
        boxes = [item.bounding_box for _, item in ordered if item.bounding_box]
        text = "  ".join(item.text or "" for _, item in ordered).strip()
        if not text:
            continue
        regions.append(
            LayoutRegion(
                page_number=ordered[0][1].page_number or 1,
                kind=_classify(text, _union(boxes)),
                text=text,
                bounding_box=_union(boxes),
                observation_indexes=[index for index, _ in ordered],
                source=ordered[0][1].source,
            )
        )
    return regions


def _text_regions(page_observations: list[tuple[int, SourceObservation]]) -> list[LayoutRegion]:
    regions = []
    for index, observation in page_observations:
        text = observation.text or ""
        for line in (line.strip() for line in text.splitlines()):
            if not line:
                continue
            regions.append(
                LayoutRegion(
                    page_number=observation.page_number or 1,
                    kind=_classify(line, None),
                    text=line,
                    bounding_box=None,
                    observation_indexes=[index],
                    source=observation.source,
                    method="heuristic_text_labels",
                )
            )
            if len(regions) >= 500:
                return regions
    return regions


def infer_layout_regions(observations: list[SourceObservation]) -> list[LayoutRegion]:
    """Infer bounded, explainable regions without claiming template detection."""

    by_page: dict[int, list[tuple[int, SourceObservation]]] = defaultdict(list)
    for index, observation in enumerate(observations):
        by_page[observation.page_number or 1].append((index, observation))
    regions = []
    for page_number in sorted(by_page):
        page_observations = by_page[page_number]
        regions.extend(_ocr_regions(page_observations))
        regions.extend(
            _text_regions(
                [item for item in page_observations if item[1].bounding_box is None]
            )
        )
    return regions[:2000]
