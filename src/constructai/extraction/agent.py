import re
from decimal import Decimal
from pathlib import Path

from constructai.extraction.providers import DocumentTextProvider
from constructai.extraction.schemas import Dimensions, ExtractedElement, ExtractionResult
from constructai.extraction.vision import OpenCVFloorPlanDetector, SUPPORTED_VISUAL_EXTENSIONS


class ExtractionAgent:
    """Coordinate document text extraction and structured element parsing."""

    _element_pattern = re.compile(r"ELEMENT\|(?P<fields>[^\n<]+)")

    def __init__(
        self,
        providers: list[DocumentTextProvider] | None = None,
        *,
        vision_detector: OpenCVFloorPlanDetector | None = None,
    ) -> None:
        self._providers = {
            extension: provider
            for provider in (providers or [])
            for extension in provider.supported_extensions
        }
        self._vision_detector = vision_detector

    def extract(self, source: Path) -> ExtractionResult:
        suffix = source.suffix.lower()

        if suffix in SUPPORTED_VISUAL_EXTENSIONS:
            if self._vision_detector is None:
                self._vision_detector = OpenCVFloorPlanDetector()
            elements = self._vision_detector.detect(source)
            return ExtractionResult(source_name=source.name, elements=elements)

        provider = self._providers.get(suffix)
        if provider is None:
            supported = ", ".join(sorted(self._providers))
            raise ValueError(
                f"Unsupported drawing format '{source.suffix}'. Supported formats: {supported}"
            )

        pages = provider.extract_pages(source)
        elements = [
            element
            for page_number, page_text in enumerate(pages, start=1)
            for element in self._parse_page(page_text, page_number)
        ]
        return ExtractionResult(source_name=source.name, elements=elements)

    def _parse_page(self, page_text: str, page_number: int) -> list[ExtractedElement]:
        elements = []
        for match in self._element_pattern.finditer(page_text):
            fields = self._parse_fields(match.group("fields"))
            dimensions = self._parse_dimensions(fields.pop("dimensions", None))
            elements.append(
                ExtractedElement(
                    **fields,
                    dimensions=dimensions,
                    source_page=page_number,
                    source_reference=f"page-{page_number}",
                )
            )
        return elements

    @staticmethod
    def _parse_fields(field_text: str) -> dict[str, str | Decimal]:
        fields: dict[str, str | Decimal] = {}
        for pair in field_text.split("|"):
            key, value = pair.split("=", maxsplit=1)
            fields[key] = Decimal(value) if key in {"quantity", "confidence"} else value
        return fields

    @staticmethod
    def _parse_dimensions(value: str | Decimal | None) -> Dimensions | None:
        if value is None:
            return None
        dimensions = {
            key: Decimal(number)
            for key, number in (part.split(":", maxsplit=1) for part in str(value).split(","))
        }
        return Dimensions(**dimensions)