from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.backend.main import app
from constructai.boq.calculator import QuantityCalculator, QuantityCalculationError
from constructai.boq.generator import BOQGenerator
from constructai.boq.schemas import BOQItem
from constructai.extraction.schemas import Dimensions, ExtractedElement, ExtractionResult


def test_wall_area_is_calculated_from_length_and_height() -> None:
    element = ExtractedElement(
        element_type="wall",
        element_id="W-001",
        description="External masonry wall",
        dimensions=Dimensions(length=Decimal("4.5"), height=Decimal("3")),
        unit="m2",
        confidence=0.94,
    )

    quantity, calculation = QuantityCalculator().calculate(element)

    assert quantity == Decimal("13.5")
    assert calculation == "4.5 m x 3 m = 13.5 m2"


def test_existing_quantity_is_used_when_dimensions_are_insufficient() -> None:
    element = ExtractedElement(
        element_type="fixture",
        description="Light fixture",
        quantity=Decimal("8"),
        unit="pcs",
        confidence=0.8,
    )

    quantity, calculation = QuantityCalculator().calculate(element)

    assert quantity == Decimal("8")
    assert calculation == "Provided extracted quantity"


def test_missing_quantity_data_is_rejected() -> None:
    element = ExtractedElement(element_type="wall", description="Unmeasured wall", confidence=0.5)

    with pytest.raises(QuantityCalculationError):
        QuantityCalculator().calculate(element)


def test_boq_generator_preserves_element_reference_and_source_page() -> None:
    extraction = ExtractionResult(
        source_name="drawing.pdf",
        elements=[
            ExtractedElement(
                element_type="wall",
                element_id="W-001",
                description="External masonry wall",
                dimensions=Dimensions(length=Decimal("4.5"), height=Decimal("3")),
                unit="m2",
                source_page=2,
                confidence=0.94,
            )
        ],
    )

    boq = BOQGenerator().generate(extraction)

    assert boq.items[0].item_number == 1
    assert boq.items[0].element_id == "W-001"
    assert boq.items[0].source_page == 2
    assert boq.items[0].quantity == Decimal("13.5")


def test_boq_generator_preserves_dimension_source_and_warns_on_quantity_conflict() -> None:
    extraction = ExtractionResult(
        source_name="drawing.pdf",
        elements=[
            ExtractedElement(
                element_type="room",
                element_id="R-001",
                description="Living room",
                dimensions=Dimensions(length=Decimal("5"), width=Decimal("3.3")),
                dimensions_source="human",
                quantity=Decimal("17"),
                unit="m2",
                source_page=1,
                confidence=0.95,
            )
        ],
    )

    boq = BOQGenerator().generate(extraction)

    assert boq.items[0].quantity == Decimal("16.5")
    assert boq.items[0].dimensions_source == "human"
    assert boq.items[0].dimensions is not None
    assert any("differs from the dimension-based quantity 16.5" in issue.message for issue in boq.validation_issues)


def test_boq_generator_keeps_repeated_window_instances_separate() -> None:
    extraction = ExtractionResult(
        source_name="drawing.pdf",
        elements=[
            ExtractedElement(
                element_type="window",
                element_id=f"W-{index:03d}",
                description=f"Window W{index}",
                quantity=Decimal("1"),
                unit="nos",
                source_page=1,
                confidence=0.95,
            )
            for index in range(1, 4)
        ],
    )

    boq = BOQGenerator().generate(extraction)

    assert len(boq.items) == 3
    assert [item.quantity for item in boq.items] == [Decimal(1)] * 3
    assert [item.element_id for item in boq.items] == ["W-001", "W-002", "W-003"]


def test_boq_schema_rejects_negative_quantity() -> None:
    with pytest.raises(ValidationError):
        BOQItem(
            item_number=1,
            description="Invalid item",
            element_type="wall",
            unit="m2",
            quantity=Decimal("-1"),
            calculation="invalid",
            confidence=0.5,
        )


def test_boq_endpoint_rejects_untracked_extraction_payload() -> None:
    response = TestClient(app).post(
        "/boq",
        json={
            "source_name": "drawing.pdf",
            "elements": [
                {
                    "element_type": "wall",
                    "element_id": "W-001",
                    "description": "External masonry wall",
                    "dimensions": {"length": 4.5, "height": 3},
                    "unit": "m2",
                    "source_page": 2,
                    "confidence": 0.94,
                }
            ],
        },
    )

    assert response.status_code == 409
    assert "reviewed in a server session" in response.json()["detail"]