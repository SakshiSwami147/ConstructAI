from pathlib import Path
from tempfile import TemporaryDirectory
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from constructai.boq.generator import BOQGenerator
from constructai.boq.review import BOQItemEdit, BOQReviewService
from constructai.boq.schemas import BOQ, ValidationSeverity
from constructai.boq.validation import BOQValidator
from constructai.extraction.schemas import (
    Dimensions,
    ElementReviewStatus,
    ExtractedElement,
    ExtractionResult,
)
from constructai.extraction.agent import ExtractionAgent
from constructai.extraction.text_providers import (
    PyMuPDFTextProvider,
    SvgTextProvider,
)
from constructai.extraction.vision import OpenCVFloorPlanDetector, SUPPORTED_VISUAL_EXTENSIONS
from constructai.agents.mapping_agent import MappingAgent


app = FastAPI(
    title="ConstructAI_MLCV API",
    version="0.1.0",
)

extraction_agent = ExtractionAgent(
    [PyMuPDFTextProvider(), SvgTextProvider()],
    vision_detector=OpenCVFloorPlanDetector(),
)

boq_generator = BOQGenerator()
boq_review_service = BOQReviewService()
boq_validator = BOQValidator()
mapping_agent = MappingAgent()
extraction_sessions: dict[str, ExtractionResult] = {}
extraction_revisions: dict[str, int] = {}
boq_sessions: dict[str, BOQ] = {}
boq_extraction_revisions: dict[str, int] = {}


class ExtractedElementEdit(BaseModel):
    element_type: str | None = None
    description: str | None = None
    location: str | None = None
    dimensions: Dimensions | None = None
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = None
    specification: str | None = None
    source_page: int | None = Field(default=None, ge=1)


class ElementReviewDecision(BaseModel):
    decision: Literal["approved", "rejected"]


def _get_extraction(extraction_id: str) -> ExtractionResult:
    extraction = extraction_sessions.get(extraction_id)
    if extraction is None:
        raise HTTPException(status_code=404, detail="Extraction review session was not found")
    return extraction


def _require_approved_extraction(extraction: ExtractionResult) -> None:
    if not extraction.elements:
        raise HTTPException(status_code=409, detail="An empty extraction cannot generate a BOQ")
    if any(element.review_status is not ElementReviewStatus.APPROVED for element in extraction.elements):
        raise HTTPException(
            status_code=409,
            detail="Every extracted element must be explicitly approved; rejected elements cannot enter the BOQ",
        )
    errors = [
        issue for issue in boq_validator.validate_extraction(extraction)
        if issue.severity is ValidationSeverity.ERROR
    ]
    if errors:
        raise HTTPException(status_code=422, detail="Resolve extraction validation errors before generating the BOQ")


def _require_current_boq(boq: BOQ) -> ExtractionResult:
    if not boq.boq_id or not boq.extraction_id:
        raise HTTPException(status_code=409, detail="BOQ is not linked to a reviewed extraction")
    extraction = _get_extraction(boq.extraction_id)
    if boq_extraction_revisions.get(boq.boq_id) != extraction_revisions.get(boq.extraction_id):
        raise HTTPException(status_code=409, detail="The source extraction changed; regenerate the BOQ")
    _require_approved_extraction(extraction)
    return extraction


def _create_boq(extraction: ExtractionResult) -> BOQ:
    _require_approved_extraction(extraction)
    try:
        boq = boq_generator.generate(extraction)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    boq_id = str(uuid4())
    boq = boq.model_copy(update={"boq_id": boq_id, "extraction_id": extraction.extraction_id})
    boq_sessions[boq_id] = boq
    if extraction.extraction_id:
        boq_extraction_revisions[boq_id] = extraction_revisions[extraction.extraction_id]
    return boq


def _model_json(model: BaseModel) -> dict:
    return jsonable_encoder(model.model_dump(mode="python"), custom_encoder={Decimal: float})


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/extractions", tags=["extraction"])
async def extract_drawing(
    file: UploadFile = File(...)
) -> JSONResponse:
    """Extract structured construction elements from one PDF or SVG drawing."""

    suffix = Path(file.filename or "").suffix.lower()
    supported = {".pdf", ".svg", *SUPPORTED_VISUAL_EXTENSIONS}

    if suffix not in supported:
        return JSONResponse(
            status_code=415,
            content={
                "detail": "Only PDF, SVG, and image-based floor-plan drawings are supported"
            },
        )

    with TemporaryDirectory() as temporary_directory:
        source = Path(temporary_directory) / f"drawing{suffix}"
        source.write_bytes(await file.read())

        try:
            result = extraction_agent.extract(source)
        except ValueError as error:
            return JSONResponse(
                status_code=422,
                content={"detail": str(error)},
            )

    extraction_id = str(uuid4())
    result = result.model_copy(update={"extraction_id": extraction_id})
    extraction_sessions[extraction_id] = result
    extraction_revisions[extraction_id] = 0
    return JSONResponse(content=_model_json(result))


@app.patch("/extractions/{extraction_id}/elements/{element_index}", tags=["extraction"])
def edit_extracted_element(
    extraction_id: str,
    element_index: int,
    edit: ExtractedElementEdit,
) -> JSONResponse:
    extraction = _get_extraction(extraction_id)
    if element_index < 0 or element_index >= len(extraction.elements):
        raise HTTPException(status_code=404, detail="Extracted element was not found")

    current = extraction.elements[element_index]
    updates = edit.model_dump(exclude_unset=True)
    if "dimensions" in updates:
        updates["dimensions_source"] = "human" if updates["dimensions"] is not None else None
    updates["review_status"] = ElementReviewStatus.PENDING
    updates["review_reasons"] = list(dict.fromkeys([*current.review_reasons, "human_edit"]))
    updated = ExtractedElement.model_validate(current.model_dump() | updates)
    elements = list(extraction.elements)
    elements[element_index] = updated
    extraction = extraction.model_copy(update={"elements": elements})
    extraction_sessions[extraction_id] = extraction
    extraction_revisions[extraction_id] += 1
    return JSONResponse(content=_model_json(extraction))


@app.post("/extractions/{extraction_id}/elements/{element_index}/review", tags=["extraction"])
def review_extracted_element(
    extraction_id: str,
    element_index: int,
    decision: ElementReviewDecision,
) -> JSONResponse:
    extraction = _get_extraction(extraction_id)
    if element_index < 0 or element_index >= len(extraction.elements):
        raise HTTPException(status_code=404, detail="Extracted element was not found")

    elements = list(extraction.elements)
    element = elements[element_index]
    if decision.decision == "approved" and (
        not element.element_type.strip() or not element.description.strip() or not element.unit
    ):
        raise HTTPException(status_code=422, detail="Correct the element type, description, and unit before approval")
    next_status = ElementReviewStatus(decision.decision)
    if element.review_status is not next_status:
        elements[element_index] = element.model_copy(update={"review_status": next_status})
        extraction = extraction.model_copy(update={"elements": elements})
        extraction_sessions[extraction_id] = extraction
        extraction_revisions[extraction_id] += 1
    return JSONResponse(content=_model_json(extraction))


@app.post("/extractions/{extraction_id}/boq", tags=["boq"])
def generate_reviewed_boq(extraction_id: str) -> JSONResponse:
    boq = _create_boq(_get_extraction(extraction_id))
    return JSONResponse(content=_model_json(boq))


@app.post("/boq", tags=["boq"])
def generate_boq(
    extraction: ExtractionResult
) -> JSONResponse:
    """Generate a BOQ from the authoritative, reviewed server-side extraction."""

    if not extraction.extraction_id:
        raise HTTPException(status_code=409, detail="Extraction must be reviewed in a server session before BOQ generation")
    reviewed_extraction = _get_extraction(extraction.extraction_id)
    boq = _create_boq(reviewed_extraction)
    return JSONResponse(content=_model_json(boq))


@app.patch("/boqs/{boq_id}/items/{item_number}", tags=["boq"])
def edit_boq_item(boq_id: str, item_number: int, edit: BOQItemEdit) -> JSONResponse:
    boq = boq_sessions.get(boq_id)
    if boq is None:
        raise HTTPException(status_code=404, detail="BOQ review session was not found")
    try:
        boq = boq_review_service.edit_item(boq, item_number, edit)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    boq_sessions[boq_id] = boq
    return JSONResponse(content=_model_json(boq))


@app.post("/boqs/{boq_id}/submit", tags=["boq"])
def submit_boq_for_review(boq_id: str) -> JSONResponse:
    boq = boq_sessions.get(boq_id)
    if boq is None:
        raise HTTPException(status_code=404, detail="BOQ review session was not found")
    _require_current_boq(boq)
    try:
        boq = boq_review_service.submit_for_review(boq)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    boq_sessions[boq_id] = boq
    return JSONResponse(content=_model_json(boq))


@app.post("/boqs/{boq_id}/approve", tags=["boq"])
def approve_boq(boq_id: str) -> JSONResponse:
    boq = boq_sessions.get(boq_id)
    if boq is None:
        raise HTTPException(status_code=404, detail="BOQ review session was not found")
    _require_current_boq(boq)
    try:
        boq = boq_review_service.approve(boq)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    boq_sessions[boq_id] = boq
    return JSONResponse(content=jsonable_encoder(boq, custom_encoder={Decimal: float}))


@app.post("/mapping", tags=["mapping"])
def generate_bom(
    boq: BOQ
) -> JSONResponse:
    """Generate BOM by mapping materials from the BOQ."""

    try:
        bom = mapping_agent.run(boq)
    except ValueError as error:
        return JSONResponse(
            status_code=422,
            content={"detail": str(error)},
        )

    return JSONResponse(
        content=jsonable_encoder(
            bom,
            custom_encoder={Decimal: float},
        )
    )
