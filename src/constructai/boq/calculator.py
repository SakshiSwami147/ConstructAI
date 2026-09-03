from decimal import Decimal

from constructai.extraction.schemas import ExtractedElement


class QuantityCalculationError(ValueError):
    """Raised when an element has neither calculable dimensions nor quantity."""


class QuantityCalculator:
    """Apply deterministic, unit-aware quantity formulas to extracted elements."""

    def calculate(self, element: ExtractedElement) -> tuple[Decimal, str]:
        dimensions = element.dimensions
        unit = (element.unit or "").lower()

        if dimensions is not None:
            if unit in {"m2", "m²", "sqm"}:
                if element.element_type.lower() in {"wall", "door", "window"} and dimensions.length and dimensions.height:
                    quantity = dimensions.length * dimensions.height
                    return quantity, f"{dimensions.length} m x {dimensions.height} m = {quantity} m2"
                if dimensions.length and dimensions.width:
                    quantity = dimensions.length * dimensions.width
                    return quantity, f"{dimensions.length} m x {dimensions.width} m = {quantity} m2"
            elif unit in {"m3", "m³", "cum"} and dimensions.length and dimensions.width and dimensions.height:
                quantity = dimensions.length * dimensions.width * dimensions.height
                return quantity, f"{dimensions.length} m x {dimensions.width} m x {dimensions.height} m = {quantity} m3"
            elif unit in {"m", "lm", "linear m"} and dimensions.length:
                return dimensions.length, f"{dimensions.length} m"

        if element.quantity is not None:
            return element.quantity, "Provided extracted quantity"

        raise QuantityCalculationError(f"Insufficient quantity data for element '{element.element_id or element.description}'")