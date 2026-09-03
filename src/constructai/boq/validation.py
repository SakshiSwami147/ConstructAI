from constructai.boq.schemas import BOQ, BOQValidationIssue, ValidationSeverity
from constructai.extraction.schemas import ExtractionResult


SUPPORTED_UNITS = {"m", "lm", "linear m", "m2", "m²", "sqm", "m3", "m³", "cum", "pcs", "unit", "kg", "ton", "l", "litre"}
LOW_CONFIDENCE_THRESHOLD = 0.75


class BOQValidator:
    """Collect validation issues without hiding them from human reviewers."""

    def validate_extraction(self, extraction: ExtractionResult) -> list[BOQValidationIssue]:
        issues = []
        if not extraction.source_name.strip():
            issues.append(BOQValidationIssue(severity=ValidationSeverity.ERROR, field="source_name", message="Source name is required"))

        for index, element in enumerate(extraction.elements, start=1):
            prefix = f"elements[{index - 1}]"
            if not element.element_type.strip():
                issues.append(self._error(f"{prefix}.element_type", "Element type is required"))
            if not element.description.strip():
                issues.append(self._error(f"{prefix}.description", "Description is required"))
            if not element.unit:
                issues.append(self._error(f"{prefix}.unit", "Unit is required"))
            elif element.unit.lower() not in SUPPORTED_UNITS:
                issues.append(self._error(f"{prefix}.unit", f"Unsupported unit '{element.unit}'"))
            if element.confidence < LOW_CONFIDENCE_THRESHOLD:
                issues.append(
                    BOQValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        field=f"{prefix}.confidence",
                        message=f"Low extraction confidence: {element.confidence:.2f}",
                    )
                )
        return issues

    def validate_boq(self, boq: BOQ) -> list[BOQValidationIssue]:
        issues = []
        for index, item in enumerate(boq.items, start=1):
            prefix = f"items[{index - 1}]"
            if not item.description.strip():
                issues.append(self._error(f"{prefix}.description", "Description is required"))
            if item.unit.lower() not in SUPPORTED_UNITS:
                issues.append(self._error(f"{prefix}.unit", f"Unsupported unit '{item.unit}'"))
            if item.quantity < 0:
                issues.append(self._error(f"{prefix}.quantity", "Quantity cannot be negative"))
            if item.confidence < LOW_CONFIDENCE_THRESHOLD:
                issues.append(
                    BOQValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        field=f"{prefix}.confidence",
                        message=f"Low extraction confidence: {item.confidence:.2f}",
                    )
                )
        return issues

    @staticmethod
    def _error(field: str, message: str) -> BOQValidationIssue:
        return BOQValidationIssue(severity=ValidationSeverity.ERROR, field=field, message=message)