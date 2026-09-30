from pathlib import Path
from tempfile import TemporaryDirectory
from decimal import Decimal

from fastapi import FastAPI, File, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from constructai.boq.generator import BOQGenerator
from constructai.boq.schemas import BOQ
from constructai.extraction.schemas import ExtractionResult
from constructai.extraction.agent import ExtractionAgent
from constructai.extraction.text_providers import (
    PyMuPDFTextProvider,
    SvgTextProvider,
)
from constructai.agents.mapping_agent import MappingAgent


app = FastAPI(
    title="ConstructAI Flow API",
    version="0.1.0",
)

extraction_agent = ExtractionAgent(
    [PyMuPDFTextProvider(), SvgTextProvider()]
)

boq_generator = BOQGenerator()
mapping_agent = MappingAgent()


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/extractions", tags=["extraction"])
async def extract_drawing(
    file: UploadFile = File(...)
) -> JSONResponse:
    """Extract structured construction elements from one PDF or SVG drawing."""

    suffix = Path(file.filename or "").suffix.lower()

    if suffix not in {".pdf", ".svg"}:
        return JSONResponse(
            status_code=415,
            content={
                "detail": "Only PDF and SVG drawings are supported"
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

    return JSONResponse(
        content=jsonable_encoder(result)
    )


@app.post("/boq", tags=["boq"])
def generate_boq(
    extraction: ExtractionResult
) -> JSONResponse:
    """Generate a validated BOQ from structured extraction JSON."""

    try:
        boq = boq_generator.generate(extraction)
    except ValueError as error:
        return JSONResponse(
            status_code=422,
            content={"detail": str(error)},
        )

    return JSONResponse(
        content=jsonable_encoder(
            boq.model_dump(mode="python"),
            custom_encoder={Decimal: float},
        )
    )


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
