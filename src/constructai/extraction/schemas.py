from decimal import Decimal

from pydantic import AliasChoices, BaseModel, Field


class Dimensions(BaseModel):
    """Optional dimensions used by a later quantity calculation step."""

    length: Decimal | None = Field(default=None, gt=0)
    width: Decimal | None = Field(default=None, gt=0)
    height: Decimal | None = Field(default=None, gt=0)


class ExtractedElement(BaseModel):
    """Typed contract for a construction element returned by extraction."""

    element_type: str = Field(validation_alias=AliasChoices("element_type", "category"))
    element_id: str | None = None
    description: str
    location: str | None = None
    dimensions: Dimensions | None = None
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = None
    specification: str | None = None
    source_page: int | None = Field(default=None, ge=1)
    source_reference: str | None = None
    confidence: float = Field(ge=0, le=1)

    @property
    def category(self) -> str:
        """Compatibility alias for the original foundation contract."""

        return self.element_type


class ExtractionResult(BaseModel):
    """Structured output returned for one uploaded drawing."""

    source_name: str
    elements: list[ExtractedElement]
