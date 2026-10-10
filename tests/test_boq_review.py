from decimal import Decimal

import pytest
from pydantic import ValidationError

from constructai.boq.generator import BOQGenerator
from constructai.boq.review import BOQItemEdit, BOQReviewService
from constructai.boq.schemas import BOQStatus
from constructai.extraction.schemas import ElementReviewStatus, ExtractedElement, ExtractionResult


def make_boq(*, confidence: float = 0.95, unit: str = "m2"):
    extraction = ExtractionResult(
        source_name="drawing.pdf",
        elements=[
            ExtractedElement(
                element_type="wall",
                element_id="W-001",
                description="External masonry wall",
                quantity=Decimal("13.5"),
                unit=unit,
                source_page=3,
                confidence=confidence,
                review_status=ElementReviewStatus.APPROVED,
            )
        ],
    )
    return BOQGenerator().generate(extraction)


def test_validation_reports_unsupported_unit_and_low_confidence() -> None:
    boq = make_boq(confidence=0.4, unit="bucket")

    assert any(issue.field == "elements[0].unit" for issue in boq.validation_issues)
    assert any(issue.field == "elements[0].confidence" for issue in boq.validation_issues)


def test_invalid_dimensions_and_missing_required_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractedElement(
            element_type="wall",
            description="Wall",
            dimensions={"length": -1},
            confidence=0.9,
        )
    with pytest.raises(ValidationError):
        ExtractedElement(element_type="wall", confidence=0.9)


def test_boq_moves_from_draft_to_review_to_approved() -> None:
    service = BOQReviewService()
    draft = make_boq()

    review = service.submit_for_review(draft)
    approved = service.approve(review)

    assert draft.status is BOQStatus.DRAFT
    assert review.status is BOQStatus.REVIEW
    assert approved.status is BOQStatus.APPROVED


def test_corrected_extraction_data_is_used_for_boq_generation() -> None:
    extraction = ExtractionResult(
        source_name="drawing.pdf",
        elements=[
            ExtractedElement(
                element_type="wall",
                element_id="W-001",
                description="Original wall",
                quantity=Decimal("10"),
                unit="m2",
                source_page=2,
                confidence=0.95,
            )
        ],
    )

    extraction.elements[0].description = "Corrected wall description"
    extraction.elements[0].quantity = Decimal("14")
    extraction.elements[0].unit = "m2"

    boq = BOQGenerator().generate(extraction)

    assert boq.items[0].description == "Corrected wall description"
    assert boq.items[0].quantity == Decimal("14")
    assert boq.items[0].source_page == 2
    assert boq.items[0].element_id == "W-001"


def test_item_can_be_edited_before_approval_and_provenance_is_preserved() -> None:
    service = BOQReviewService()
    draft = make_boq()

    edited = service.edit_item(
        draft,
        item_number=1,
        edit=BOQItemEdit(description="Revised external masonry wall", quantity=Decimal("14")),
    )

    assert edited.items[0].description == "Revised external masonry wall"
    assert edited.items[0].quantity == Decimal("14")
    assert edited.items[0].source_page == 3
    assert edited.items[0].element_id == "W-001"
    assert edited.items[0].calculation == "Provided extracted quantity"


def test_approved_boq_cannot_be_edited() -> None:
    service = BOQReviewService()
    approved = service.approve(service.submit_for_review(make_boq()))

    with pytest.raises(ValueError, match="cannot be edited"):
        service.edit_item(approved, 1, BOQItemEdit(quantity=Decimal("15")))


def test_boq_with_validation_errors_cannot_be_approved() -> None:
    service = BOQReviewService()
    review = service.submit_for_review(make_boq(unit="bucket"))

    with pytest.raises(ValueError, match="validation errors"):
        service.approve(review)