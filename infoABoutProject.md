# ConstructAI_MLCV Project Overview

## 1. Project purpose

ConstructAI_MLCV is a construction estimating and material-takeoff prototype that turns source drawings or PDFs into a structured Bill of Quantities (BOQ) and then maps those quantities to material requirements and approximate costs.

The project is intentionally structured as a foundation/milestone build. It includes the domain contracts, the API layer, the frontend workflow, and the rule-based calculation logic, but it does not yet implement a production-grade AI vision pipeline for full drawing recognition.

---

## 2. What this project is trying to do

The intended workflow is:

1. Upload a PDF or SVG drawing.
   - Human review: confirm the correct drawing/file was selected before extraction begins.
2. Extract structured construction elements from the drawing text.
   - Human review: verify that the extracted elements, labels, and locations look correct.
3. Validate the extracted elements.
   - Human review: check for missing, incorrect, or suspicious values before generating quantities.
4. Calculate approximate quantities.
   - Human review: validate the formula assumptions and unit logic used for the estimate.
5. Generate a BOQ.
   - Human review: confirm the BOQ structure, quantities, and description quality before approval.
6. Review and validate the BOQ.
   - Human review: ensure the numbers are consistent with the source document and project expectations.
7. Map BOQ items to materials using recipe data and cost catalog data.
   - Human review: verify the matched work items and material assumptions before final pricing.
8. Produce a BOM (Bill of Materials) with total cost by category.
   - Human review: approve the final BOM and cost estimate, or send it back for reconciliation.

This is a construction-tech workflow: drawing to estimate, not a general-purpose application, and the design assumes a human remains in control after each step.

---

## 3. High-level architecture

The project has a Python backend and a React frontend:

- Backend: FastAPI application in `app/backend/main.py`
- Frontend: React + Vite in `app/frontend/`
- Core domain model: Python package under `src/constructai/`
- Data files: `data/material_catalog.csv`, `data/recipes.csv`, and sample files under `data/sample/`

### Runtime structure

- `app/backend/` holds the HTTP API layer
- `app/frontend/` holds the UI and browser workflow
- `src/constructai/` holds business logic and data contracts
- `tests/` contains backend validation tests

---

## 4. Technical stack

### Python backend

From the project metadata in `pyproject.toml`:

- Python requirement: `>=3.12`
- Package name: `ConstructAI_MLCV`
- Framework: FastAPI
- Validation and modeling: Pydantic 2.x
- PDF text extraction support: PyMuPDF
- Upload handling: python-multipart
- ASGI server: uvicorn
- Test stack: pytest

### Frontend

In `app/frontend/package.json`:

- Framework: React
- Bundler/tooling: Vite
- TypeScript: TypeScript
- Build flow: `tsc -b && vite build`

### Core data and logic

The project uses:

- CSV-based lookup data for materials and recipes
- deterministic calculation formulas
- TF-IDF cosine similarity for matching BOQ descriptions to recipe work items
- structured Pydantic models for extraction and BOQ contracts

---

## 5. Important project files

### Root project files

- `pyproject.toml` — Python package metadata and dependencies
- `README.md` — basic project overview and quickstart
- `infoABoutProject.md` — this file, designed as a quick understanding guide

### Backend/API

- `app/backend/main.py` — FastAPI app and route definitions

### Frontend

- `app/frontend/index.html` — browser document shell
- `app/frontend/src/App.tsx` — main UI and workflow logic
- `app/frontend/src/main.tsx` — frontend bootstrap
- `app/frontend/src/styles.css` — UI styling

### Domain model / business logic

- `src/constructai/extraction/agent.py` — extraction orchestration
- `src/constructai/extraction/schemas.py` — extraction data contracts
- `src/constructai/boq/calculator.py` — quantity calculation rules
- `src/constructai/boq/generator.py` — BOQ creation from extracted results
- `src/constructai/boq/schemas.py` — BOQ and validation data contracts
- `src/constructai/boq/validation.py` — validation logic for extracted and BOQ data
- `src/constructai/agents/mapping_agent.py` — BOQ to BOM material matching and pricing engine

### Data

- `data/material_catalog.csv` — material master list with pricing and categories
- `data/recipes.csv` — recipe entries used to map BOQ work items to materials
- `data/sample/` — sample project files

---

## 6. Backend flow and API behavior

The FastAPI app in `app/backend/main.py` exposes these routes:

### GET /health

Returns a basic service health confirmation:

- status: `ok`

### POST /extractions

This is the drawing-extraction route.

Flow:

- Accepts an uploaded file
- Validates extension (`.pdf` or `.svg` only)
- Uses `ExtractionAgent`
- Calls the correct text provider for the file type
- Parses structured `ELEMENT|...` records from extracted text
- Returns an `ExtractionResult` JSON payload

### POST /boq

This creates the BOQ from the extraction result.

Flow:

- Accepts an `ExtractionResult`
- Calls `BOQGenerator.generate(...)`
- Uses `QuantityCalculator` to calculate quantities
- Uses `BOQValidator` to validate extracted data and BOQ contents
- Returns a BOQ payload with validation issues if any exist

### POST /mapping

This maps a generated BOQ to a material BOM.

Flow:

- Accepts a `BOQ` object
- Uses `MappingAgent.run(boq)`
- Matches BOQ line descriptions to recipe work items by TF-IDF similarity
- Converts quantities into material consumption
- Applies wastage and pricing from the material catalog
- Returns aggregated BOM lines and total cost

---

## 7. Extraction logic

The extraction logic is implemented in `src/constructai/extraction/agent.py`.

### Key facts

- It accepts a list of document-text providers.
- It picks the provider based on the uploaded file extension.
- It extracts pages of text and searches for records matching this pattern:

```python
ELEMENT|field1=value|field2=value|...
```

### Data contract details

The model in `src/constructai/extraction/schemas.py` defines:

- `Dimensions` with optional `length`, `width`, and `height`
- `ExtractedElement` with fields such as:
  - `element_type`
  - `description`
  - `location`
  - `quantity`
  - `unit`
  - `specification`
  - `source_page`
  - `source_reference`
  - `confidence`
- `ExtractionResult` containing `source_name` and `elements`

This means the system is built around strongly typed contracts rather than loose dictionaries.

---

## 8. Quantity calculation logic

The calculation engine is in `src/constructai/boq/calculator.py`.

### Core rules

It calculates quantities from dimensions when available:

- If the unit is `m2`, `m²`, or `sqm` and dimensions include length + height or length + width, it multiplies them.
- If the unit is `m3`, `m³`, or `cum`, it multiplies length × width × height.
- If the unit is `m` or `linear m`, it uses the length directly.
- If no dimensions are available, it falls back to `element.quantity`.
- If neither is present, it raises `QuantityCalculationError`.

This makes the quantity logic deterministic and explainable.

---

## 9. BOQ generation logic

The BOQ generator is in `src/constructai/boq/generator.py`.

### What it does

For each extracted element:

- computes quantity and calculation text
- converts it into a `BOQItem`
- creates a BOQ object
- validates extraction and BOQ issues
- returns the full BOQ plus validation issues

### BOQ schema

In `src/constructai/boq/schemas.py` the project defines:

- `BOQStatus`: `DRAFT`, `REVIEW`, `APPROVED`
- `ValidationSeverity`: `error` and `warning`
- `BOQValidationIssue`
- `BOQItem`
- `BOQ`

This is a contract-first design with review status, validation issues, and item-level metadata.

---

## 10. BOQ to BOM mapping engine

The mapping logic is implemented in `src/constructai/agents/mapping_agent.py`.

### How it works

The file explicitly describes the system as:

1. Match each BOQ line to a work item in `data/recipes.csv` using TF-IDF cosine similarity on the description.
2. Convert work quantity to material quantity using recipe consumption rates.
3. Price using `data/material_catalog.csv`.

### Important facts

- It loads the material catalog and recipes as CSV files.
- It builds token dictionaries and inverse document frequency (IDF) values.
- It matches by description and unit only.
- It gives a score and marks status as:
  - `OK` if score >= 0.6
  - `REVIEW` if score >= 0.35
  - `NO MATCH` otherwise
- It adds warnings for low confidence or no match
- It computes cost by material category and totals by category

This is a lightweight rule-based matching approach rather than a neural or LLM-driven estimator.

---

## 11. Data design

### Material catalog

`data/material_catalog.csv` is the pricing master. It includes material records such as:

- `material_id`
- `name`
- `category`
- `unit`
- `rate_inr`
- `wastage_pct`

### Recipe catalog

`data/recipes.csv` associates work lines with materials and consumption values. Each recipe contains:

- `work_key`
- `match_text`
- `unit`
- `default_mm`
- `material_id`
- `qty_per_unit`
- `note`

This is the core engine driving the material takeoff.

---

## 12. Frontend workflow

The UI in `app/frontend/src/App.tsx` is an estimator workflow separated into stages:

- upload
- extraction
- boq
- approval

It includes:

- file upload interface
- extraction review screen
- BOQ generation screen
- final approval state

The top headline currently shows `ConstructAI_MLCV` in the UI branding, and the app is designed around creating a visual construction-estimating experience.

---

## 13. Current maturity level

This project is a strong starting foundation, but not yet a full production system.

### What is implemented

- backend API skeleton
- input validation
- data contracts with Pydantic
- extraction pipeline architecture
- deterministic quantities
- BOQ validation and generation
- material mapping with cost estimation
- frontend user flow
- human-in-the-loop checkpoints throughout the workflow

### What is not fully implemented

- a fully robust AI-based extraction engine for complex drawings
- production-quality OCR / vision parsing for all drawing types
- advanced review workflows and authentication
- persistence / database layer
- deployment and production packaging

The README explicitly describes the project as a milestone foundation, and the code reflects that state.

---

## 14. How to run the project

### Backend

```powershell
python -m pip install -e ".[dev]"
uvicorn app.backend.main:app --reload
```

If needed for local path resolution:

```powershell
$env:PYTHONPATH = "src"
uvicorn app.backend.main:app --reload
```

### Frontend

```powershell
cd app/frontend
npm install
npm run dev
```

### Tests

```powershell
pytest
```

---

## 15. Main design principles visible in the repo

- Contract-first design using Pydantic models
- Deterministic, explainable calculations
- Clear separation between extraction, BOQ logic, and BOM mapping
- CSV-driven material and recipe catalogs
- API-first architecture with a web frontend on top
- Workflow-oriented UI for estimation and review
- Human-in-the-loop validation after each major stage

---

## 16. Human-in-the-loop workflow model

The system is designed around review gates rather than fully autonomous processing. After each key stage, a user is expected to check the result before continuing:

- after upload: confirm the correct source document
- after extraction: validate extracted elements
- after validation: review errors or suspicious values
- after quantity calculation: confirm assumptions and units
- after BOQ creation: approve or reject the BOQ line items
- after material mapping: validate matched recipes and cost assumptions
- before final approval: confirm the total estimate is acceptable

This keeps the workflow transparent and prevents incorrect data from automatically propagating into later stages.

---

## 17. Recommended reading order

If you want to understand the project quickly, read in this order:

1. `README.md`
2. `app/backend/main.py`
3. `src/constructai/extraction/schemas.py`
4. `src/constructai/extraction/agent.py`
5. `src/constructai/boq/calculator.py`
6. `src/constructai/boq/generator.py`
7. `src/constructai/agents/mapping_agent.py`
8. `app/frontend/src/App.tsx`
9. `data/recipes.csv` and `data/material_catalog.csv`

---

## 17. Short summary

ConstructAI_MLCV is a construction estimator prototype that converts uploaded drawings into extraction data, calculates BOQ quantities, validates the output, and maps it to costed materials. It is built with FastAPI, React, Pydantic, and deterministic rule-based logic rather than a full AI vision stack. It is structured as a milestone foundation for a larger estimating and BOQ workflow system.

This project is best understood as a rule-based construction takeoff prototype with a clear architecture, testable contracts, and a front-end workflow for an estimating pipeline. The human-in-the-loop structure is intentional: every critical stage includes review before the process moves forward.
