from pathlib import Path

import pytest

from constructai.boq.generator import BOQGenerator
from constructai.boq.review import BOQReviewService
from constructai.boq.schemas import BOQStatus
from constructai.extraction.agent import ExtractionAgent
from constructai.extraction.schemas import ExtractedElement, ExtractionResult
from constructai.extraction.text_providers import SvgTextProvider


SAMPLE_DRAWING = Path("data/sample/sample_drawing.svg")


def test_milestone1_workflow_reaches_approved_with_preserved_data() -> None:
    extraction = ExtractionAgent([SvgTextProvider()]).extract(SAMPLE_DRAWING)
    element = extraction.elements[0]

    boq = BOQGenerator().generate(extraction)
    item = boq.items[0]
    review_service = BOQReviewService()

    review = review_service.submit_for_review(boq)
    approved = review_service.approve(review)

    assert extraction.source_name == "sample_drawing.svg"
    assert element.element_type == item.element_type == "wall"
    assert element.element_id == item.element_id == "W-001"
    assert element.source_page == item.source_page == 1
    assert item.quantity == 13.5
    assert element.unit == item.unit == "m2"
    assert item.calculation == "4.5 m x 3 m = 13.5 m2"
    assert element.confidence == item.confidence == 0.94
    assert boq.status is BOQStatus.DRAFT
    assert review.status is BOQStatus.REVIEW
    assert approved.status is BOQStatus.APPROVED


def test_invalid_boq_data_cannot_reach_approved() -> None:
    extraction = ExtractionResult(
        source_name="invalid-drawing.pdf",
        elements=[
            ExtractedElement(
                element_type="wall",
                element_id="W-INVALID",
                description="Wall with unsupported unit",
                quantity=10,
                unit="truckload",
                source_page=1,
                confidence=0.9,
            )
        ],
    )
    boq = BOQGenerator().generate(extraction)
    review = BOQReviewService().submit_for_review(boq)

    assert any(issue.field == "elements[0].unit" for issue in boq.validation_issues)
    with pytest.raises(ValueError, match="validation errors"):
        BOQReviewService().approve(review)