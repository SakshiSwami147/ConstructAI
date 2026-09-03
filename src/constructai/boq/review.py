from decimal import Decimal

from pydantic import BaseModel, Field

from constructai.boq.schemas import BOQ, BOQItem, BOQStatus, BOQValidationIssue, ValidationSeverity
from constructai.boq.validation import BOQValidator


class BOQItemEdit(BaseModel):
    description: str | None = None
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = None


class BOQReviewService:
    """Manage draft review transitions and pre-approval item corrections."""

    def __init__(self, validator: BOQValidator | None = None) -> None:
        self._validator = validator or BOQValidator()

    def submit_for_review(self, boq: BOQ) -> BOQ:
        self._require_status(boq, BOQStatus.DRAFT)
        return boq.model_copy(update={"status": BOQStatus.REVIEW})

    def edit_item(self, boq: BOQ, item_number: int, edit: BOQItemEdit) -> BOQ:
        if boq.status is BOQStatus.APPROVED:
            raise ValueError("Approved BOQs cannot be edited")
        item_index = next((index for index, item in enumerate(boq.items) if item.item_number == item_number), None)
        if item_index is None:
            raise ValueError(f"BOQ item {item_number} was not found")

        current = boq.items[item_index]
        updates = edit.model_dump(exclude_unset=True)
        updated_item = current.model_copy(update=updates)
        items = list(boq.items)
        items[item_index] = BOQItem.model_validate(updated_item)
        issues = self._validator.validate_boq(boq.model_copy(update={"items": items}))
        return boq.model_copy(update={"items": items, "validation_issues": issues})

    def approve(self, boq: BOQ) -> BOQ:
        self._require_status(boq, BOQStatus.REVIEW)
        issues = self._validator.validate_boq(boq)
        errors = [issue for issue in issues if issue.severity is ValidationSeverity.ERROR]
        if errors:
            raise ValueError("BOQ has validation errors and cannot be approved")
        return boq.model_copy(update={"status": BOQStatus.APPROVED, "validation_issues": issues})

    @staticmethod
    def _require_status(boq: BOQ, expected: BOQStatus) -> None:
        if boq.status is not expected:
            raise ValueError(f"BOQ must be {expected.value} before this transition")