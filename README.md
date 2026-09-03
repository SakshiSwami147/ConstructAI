# ConstructAI Flow

Milestone 1 foundation for the Drawing/PDF to approved BOQ workflow.

## Backend

```powershell
python -m pip install -e ".[dev]"
uvicorn app.backend.main:app --reload
```

The API currently exposes `GET /health`. Extraction, quantity calculation, BOQ generation, and review behavior will be added incrementally.

The Python package contains the initial contracts for extracted construction elements and BOQ items under `src/constructai`. AI extraction and quantity calculation are intentionally not implemented yet.

To run the extraction endpoint locally:

```powershell
$env:PYTHONPATH = "src"
uvicorn app.backend.main:app --reload
```

Then upload a PDF or SVG drawing to `POST /extractions` using the `file` multipart field. The sample fixture is `data/sample/sample_drawing.svg`.

## Frontend

```powershell
cd app/frontend
npm install
npm run dev
```

## Tests

```powershell
pytest
```

## Structure

- `app/backend`: FastAPI application entry point.
- `app/frontend`: React/Vite frontend entry point for the milestone workflow.
- `src/constructai/documents`: document-domain boundary for future PDF and drawing input.
- `src/constructai/extraction`: validated extraction data contracts.
- `src/constructai/quantities`: boundary reserved for deterministic quantity calculation.
- `src/constructai/boq`: validated BOQ data contracts.
- `src/constructai/review`: boundary reserved for human review and approval.
- `tests`: focused backend contract tests.
