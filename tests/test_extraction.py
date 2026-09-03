from pathlib import Path

from fastapi.testclient import TestClient

from app.backend.main import app
from constructai.extraction.agent import ExtractionAgent
from constructai.extraction.text_providers import SvgTextProvider


SAMPLE_DRAWING = Path("data/sample/sample_drawing.svg")


def test_extraction_agent_returns_structured_elements() -> None:
    result = ExtractionAgent([SvgTextProvider()]).extract(SAMPLE_DRAWING)

    assert result.source_name == "sample_drawing.svg"
    assert len(result.elements) == 1
    assert result.elements[0].element_type == "wall"
    assert result.elements[0].element_id == "W-001"
    assert result.elements[0].quantity == 13.5
    assert result.elements[0].source_page == 1


def test_extraction_endpoint_accepts_drawing_upload() -> None:
    client = TestClient(app)
    with SAMPLE_DRAWING.open("rb") as drawing:
        response = client.post(
            "/extractions",
            files={"file": (SAMPLE_DRAWING.name, drawing, "image/svg+xml")},
        )

    assert response.status_code == 200
    assert response.json()["elements"][0]["specification"] == "200mm concrete block"


def test_extraction_endpoint_rejects_unsupported_files() -> None:
    response = TestClient(app).post(
        "/extractions",
        files={"file": ("notes.txt", b"not a drawing", "text/plain")},
    )

    assert response.status_code == 415