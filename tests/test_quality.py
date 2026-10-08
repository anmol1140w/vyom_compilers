from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from app.main import routing_metadata
from app.models import QualityAssessment
from app.quality import analyze_and_retain, assess_image, ocr_enhancement


def quality_fixture():
    image = Image.new("RGB", (1200, 800), "white")
    draw = ImageDraw.Draw(image)
    for y in range(80, 720, 80):
        draw.line((60, y, 1140, y), fill="black", width=3)
    for x in range(60, 1200, 270):
        draw.line((x, 80, x, 720), fill="black", width=3)
    draw.text((90, 25), "Invoice number: VYM-1", fill="black")
    return image


def test_quality_heuristics_distinguish_blur_without_claiming_accuracy():
    sharp = assess_image(quality_fixture())
    blurred = assess_image(quality_fixture().filter(ImageFilter.GaussianBlur(8)))

    assert sharp.score > blurred.score
    assert sharp.blur < blurred.blur
    assert 0 <= sharp.readability <= 1
    assert 0 <= sharp.table_likelihood <= 1
    assert any("not field-accuracy" in note for note in sharp.notes)
    assert any("not handwriting recognition" in note for note in sharp.notes)


def test_preprocessing_representations_are_bounded_and_private(tmp_path):
    source = tmp_path / "source.png"
    quality_fixture().save(source)
    artifact_dir = tmp_path / "preprocessed" / "document-id"
    quality, page_quality, representations, warnings = analyze_and_retain(
        source,
        "png",
        artifact_dir,
        "preprocessed/document-id",
    )

    names = {representation.name for representation in representations}
    assert quality.applicable is True
    assert page_quality[0].page_number == 1
    assert page_quality[0].native_text_available is False
    assert {"original", "grayscale", "autocontrast", "adaptive_threshold", "deskewed"} <= names
    assert not warnings
    for representation in representations:
        if representation.artifact_path:
            path = tmp_path / representation.artifact_path
            assert path.is_file()
            assert path.stat().st_mode & 0o777 == 0o600


def test_tabular_quality_is_not_presented_as_visual_quality(upload):
    record = upload().json()

    assert record["quality"]["applicable"] is False
    assert record["quality"]["score"] is None
    assert record["preprocessing"] == []
    assert record["routing"]["document_class"] == "tabular"


def test_visual_quality_and_preprocessing_endpoint_are_persisted(client, upload):
    source = Path(__file__).resolve().parent.parent / "samples" / "sample-invoice.png"
    record = upload("sample-invoice.png", source.read_bytes()).json()

    assert record["quality"]["applicable"] is True
    assert record["quality"]["score"] is not None
    assert record["processing"]["quality_duration_ms"] >= 0
    grayscale = next(item for item in record["preprocessing"] if item["name"] == "grayscale")
    response = client.get(
        f"/api/documents/{record['id']}/preprocessing/{grayscale['page_number']}/{grayscale['name']}"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")
    assert client.get(f"/api/documents/{record['id']}/preprocessing/1/../source").status_code in {
        404,
        422,
    }


def test_quality_route_is_explicit_about_review_signals():
    poor = QualityAssessment(applicable=True, score=30)
    route = routing_metadata("png", "ocr", False, poor)
    assert route.document_class == "poor_quality"
    assert route.selected_route == "ocr_quality_review"
    assert "source review is required" in route.reason

    handwriting = routing_metadata("png", "ocr", True, QualityAssessment(applicable=True, score=80))
    assert handwriting.document_class == "handwritten"
    assert handwriting.selected_route == "ocr_handwriting_review"
    assert "not handwriting recognition" in handwriting.reason


def test_quality_selects_sharpening_only_for_elevated_blur():
    assert ocr_enhancement(QualityAssessment(applicable=True, blur=0.7, contrast=0.8)) == "sharpened"
    assert ocr_enhancement(QualityAssessment(applicable=True, blur=0.1, contrast=0.8)) == "autocontrast"
    assert ocr_enhancement(QualityAssessment(applicable=False)) == "autocontrast"
