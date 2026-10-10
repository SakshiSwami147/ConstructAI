from pathlib import Path
from decimal import Decimal

import cv2
import numpy as np

from constructai.extraction.agent import ExtractionAgent
from constructai.extraction.schemas import ElementReviewStatus
from constructai.extraction.vision import DetectionCandidate, OpenCVFloorPlanDetector


def _create_sample_floorplan(path: Path) -> None:
    image = np.full((700, 900, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (60, 60), (420, 90), (0, 0, 0), thickness=10)
    cv2.rectangle(image, (80, 180), (160, 420), (0, 0, 0), thickness=10)
    cv2.rectangle(image, (520, 120), (610, 300), (0, 0, 0), thickness=10)
    cv2.rectangle(image, (650, 200), (790, 260), (0, 0, 0), thickness=10)
    cv2.imwrite(str(path), image)


def test_opencv_detector_finds_floorplan_objects(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample_floorplan.png"
    _create_sample_floorplan(sample_path)

    detections = OpenCVFloorPlanDetector(min_area=150).detect(sample_path)

    assert detections
    assert {item.element_type for item in detections} <= {"wall", "door", "window", "column", "beam"}
    assert all(item.review_status is ElementReviewStatus.PENDING for item in detections)
    assert all("prototype_classification" in item.review_reasons for item in detections)
    assert all(item.unit is None for item in detections)


def test_extraction_agent_supports_image_drawings(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample_floorplan.png"
    _create_sample_floorplan(sample_path)

    result = ExtractionAgent([], vision_detector=OpenCVFloorPlanDetector(min_area=150)).extract(sample_path)

    assert result.source_name == "sample_floorplan.png"
    assert result.elements
    assert all(item.source_page == 1 for item in result.elements)
    assert all(item.confidence >= 0.0 for item in result.elements)


def test_ocr_dimensions_are_provenanced_and_still_pending(tmp_path: Path, monkeypatch) -> None:
    sample_path = tmp_path / "sample_floorplan.png"
    _create_sample_floorplan(sample_path)
    detector = OpenCVFloorPlanDetector(use_ocr=True)
    candidate = DetectionCandidate("wall", 60, 60, 360, 30, 0.98, "wall candidate")
    monkeypatch.setattr(detector, "_detect_contours", lambda image: [candidate])
    monkeypatch.setattr(detector, "_extract_label", lambda image, candidate: "4.5 3.0")

    element = detector.detect(sample_path)[0]

    assert element.dimensions is not None
    assert element.dimensions.length == Decimal("4.5")
    assert element.dimensions.width == Decimal("3.0")
    assert element.dimensions_source == "ocr"
    assert "ocr_dimensions" in element.review_reasons
    assert element.review_status is ElementReviewStatus.PENDING


def test_missing_ocr_keeps_dimensions_none(tmp_path: Path, monkeypatch) -> None:
    sample_path = tmp_path / "sample_floorplan.png"
    _create_sample_floorplan(sample_path)
    detector = OpenCVFloorPlanDetector(use_ocr=False)
    candidate = DetectionCandidate("wall", 60, 60, 360, 30, 0.98, "wall candidate")
    monkeypatch.setattr(detector, "_detect_contours", lambda image: [candidate])

    element = detector.detect(sample_path)[0]

    assert element.dimensions is None
    assert element.dimensions_source is None
