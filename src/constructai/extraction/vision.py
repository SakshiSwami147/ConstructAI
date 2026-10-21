from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from numpy.typing import NDArray

try:
    import cv2
    import numpy as np
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    cv2 = None
    np = None
    _CV2_IMPORT_ERROR = exc
else:  # pragma: no cover - imported in supported environments
    _CV2_IMPORT_ERROR = None

from constructai.extraction.schemas import Dimensions, ExtractedElement


SUPPORTED_VISUAL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


@dataclass(slots=True)
class DetectionCandidate:
    """Normalized, geometry-based candidate extracted from a floor plan."""

    element_type: str
    x: int
    y: int
    width: int
    height: int
    confidence: float
    description: str
    label: str | None = None
    dimensions: Dimensions | None = None


class YOLOFloorPlanDetector:
    """Optional YOLO adapter for a trained construction-drawing detector.

    A project-specific YOLO model is required for production-grade recognition.
    This class intentionally raises a clear error when no weights/configuration is
    available instead of pretending a trained detector is shipped with the repo.
    """

    def __init__(
        self,
        weights_path: str | Path | None = None,
        config_path: str | Path | None = None,
        names_path: str | Path | None = None,
        conf_threshold: float = 0.35,
    ) -> None:
        self.weights_path = Path(weights_path) if weights_path else None
        self.config_path = Path(config_path) if config_path else None
        self.names_path = Path(names_path) if names_path else None
        self.conf_threshold = conf_threshold

        if not self.weights_path or not self.config_path:
            raise ValueError(
                "YOLO model configuration is missing. Provide trained weights_path and config_path "
                "for a construction-drawing detector before using this adapter."
            )

    def detect(self, source: str | Path) -> list[ExtractedElement]:
        raise ValueError(
            "No trained YOLO weights were found for this project. Train or fine-tune a model on "
            "construction floor-plan images and provide the weights, config, and class names to use "
            "YOLOFloorPlanDetector."
        )


class OpenCVFloorPlanDetector:
    """Geometry-first detector for line-based floor-plan drawings.

    This is a reusable prototype that does not invent dimensions or quantities. It
    only returns detections supported by contour geometry and optional OCR text when
    the OCR dependency is available. Uncertain objects are returned with lower
    confidence and flagged for human review.
    """

    def __init__(
        self,
        min_area: int = 200,
        conf_threshold: float = 0.45,
        use_ocr: bool = False,
    ) -> None:
        if cv2 is None or np is None:
            raise RuntimeError(
                "OpenCV and NumPy are required for the vision pipeline. Install the project dependencies "
                "or the optional vision extras."
            ) from _CV2_IMPORT_ERROR

        self.min_area = min_area
        self.conf_threshold = conf_threshold
        self.use_ocr = use_ocr

    def detect(self, source: str | Path) -> list[ExtractedElement]:
        image_path = Path(source)
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f"Unable to read floor-plan image '{image_path}'")

        candidates = self._detect_contours(image)
        elements: list[ExtractedElement] = []
        for index, candidate in enumerate(candidates, start=1):
            if candidate.confidence < self.conf_threshold:
                candidate.description = f"{candidate.element_type} candidate requires human review"

            label = self._extract_label(image, candidate)
            dimensions = self._extract_dimensions(candidate, label)
            review_reasons = ["prototype_classification"]
            if candidate.confidence < self.conf_threshold:
                review_reasons.append("low_confidence")
            if dimensions is not None:
                review_reasons.append("ocr_dimensions")

            elements.append(
                ExtractedElement(
                    element_type=candidate.element_type,
                    element_id=f"{candidate.element_type[:1].upper()}{index:03d}",
                    description=candidate.description,
                    location=f"x={candidate.x}, y={candidate.y}, w={candidate.width}, h={candidate.height}",
                    dimensions=dimensions,
                    quantity=None,
                    unit=None,
                    specification="Prototype OpenCV contour classification; verify against the source drawing.",
                    source_page=1,
                    source_reference=f"page-1:{candidate.x},{candidate.y}",
                    confidence=float(round(candidate.confidence, 3)),
                    dimensions_source="ocr" if dimensions is not None else None,
                    review_reasons=review_reasons,
                )
            )
        return elements

    def _detect_contours(self, image: NDArray) -> list[DetectionCandidate]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        _, threshold = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        edges = cv2.Canny(gray, 50, 150)
        combined = cv2.bitwise_or(threshold, edges)

        contours, _ = cv2.findContours(combined, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        candidates: list[DetectionCandidate] = []

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.min_area:
                continue

            x, y, width, height = cv2.boundingRect(contour)
            if width < 8 or height < 8:
                continue

            if width * height <= 0:
                continue

            element_type = self._classify_shape(width, height, area)
            confidence = self._shape_confidence(width, height, area)
            description = self._describe_element(element_type, width, height)
            candidates.append(
                DetectionCandidate(
                    element_type=element_type,
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    confidence=confidence,
                    description=description,
                )
            )

        candidates.sort(key=lambda item: item.width * item.height, reverse=True)
        return candidates

    @staticmethod
    def _classify_shape(width: int, height: int, area: int) -> str:
        aspect_ratio = max(width, height) / max(min(width, height), 1)
        if width > height * 2.5:
            return "wall"
        if height > width * 2.5:
            return "column"
        if aspect_ratio > 2.0 and area < 20000:
            return "beam"
        if width < 200 and height < 200:
            return "window"
        return "door"

    @staticmethod
    def _shape_confidence(width: int, height: int, area: int) -> float:
        metric = max(width, height) / max(min(width, height), 1)
        score = min(0.96, 0.5 + (min(area, 35000) / 35000) * 0.25 + (min(metric, 8.0) / 8.0) * 0.2)
        return round(score, 3)

    @staticmethod
    def _describe_element(element_type: str, width: int, height: int) -> str:
        return f"{element_type} candidate with bounding box {width}x{height}"

    def _extract_label(self, image: NDArray, candidate: DetectionCandidate) -> str | None:
        if not self.use_ocr:
            return None

        try:
            import pytesseract  # type: ignore
        except ImportError:
            return None

        x0 = max(0, candidate.x - 10)
        y0 = max(0, candidate.y - 10)
        x1 = min(image.shape[1], candidate.x + candidate.width + 10)
        y1 = min(image.shape[0], candidate.y + candidate.height + 10)
        crop = image[y0:y1, x0:x1]
        if crop.size == 0:
            return None

        text = pytesseract.image_to_string(crop, config="--psm 6")
        cleaned = re.sub(r"\s+", " ", text).strip()
        return cleaned or None

    @staticmethod
    def _extract_dimensions(candidate: DetectionCandidate, label: str | None) -> Dimensions | None:
        if not label:
            return None

        values = re.findall(r"\d+(?:\.\d+)?", label)
        if not values:
            return None

        if len(values) >= 2:
            length, width = map(float, values[:2])
            return Dimensions(length=Decimal(str(length)), width=Decimal(str(width)), height=None)
        if len(values) == 1:
            return Dimensions(length=Decimal(str(values[0])), width=None, height=None)
        return None


__all__ = [
    "DetectionCandidate",
    "OpenCVFloorPlanDetector",
    "YOLOFloorPlanDetector",
    "SUPPORTED_VISUAL_EXTENSIONS",
]
