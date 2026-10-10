from pathlib import Path

import cv2
import numpy as np
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


def test_extraction_endpoint_accepts_floorplan_images() -> None:
    client = TestClient(app)
    image = np.full((700, 900, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (60, 60), (420, 90), (0, 0, 0), thickness=10)
    cv2.rectangle(image, (80, 180), (160, 420), (0, 0, 0), thickness=10)
    cv2.rectangle(image, (520, 120), (610, 300), (0, 0, 0), thickness=10)
    cv2.rectangle(image, (650, 200), (790, 260), (0, 0, 0), thickness=10)
    _, encoded = cv2.imencode(".png", image)

    response = client.post(
        "/extractions",
        files={"file": ("sample_floorplan.png", encoded.tobytes(), "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["elements"]


def test_extraction_endpoint_rejects_unsupported_files() -> None:
    response = TestClient(app).post(
        "/extractions",
        files={"file": ("notes.txt", b"not a drawing", "text/plain")},
    )

    assert response.status_code == 415