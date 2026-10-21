from decimal import Decimal

import pytest
from pydantic import ValidationError

from constructai.boq.schemas import BOQItem
from constructai.extraction.schemas import Dimensions, ExtractedElement


def test_extracted_element_supports_drawing_context() -> None:
    element = ExtractedElement(
        category="wall",
        description="External masonry wall",
        location="A-101",
        dimensions=Dimensions(length=Decimal("4.5"), height=Decimal("3")),
        unit="m2",
        source_reference="sheet-A101.pdf:p3",
        confidence=0.92,
    )

    assert element.location == "A-101"
    assert element.dimensions is not None
    assert element.dimensions.length == Decimal("4.5")


def test_extraction_confidence_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        ExtractedElement(
            category="wall",
            description="External masonry wall",
            confidence=1.1,
        )


def test_boq_item_rejects_negative_quantity() -> None:
    with pytest.raises(ValidationError):
        BOQItem(
            item_code="WALL-001",
            description="External masonry wall",
            unit="m2",
            quantity=Decimal("-1"),
        )