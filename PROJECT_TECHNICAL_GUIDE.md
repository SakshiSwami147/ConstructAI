# ConstructAI_MLCV — Technical Project Guide

This document is the consolidated technical reading guide to the implementation currently in this repository. It covers the implemented workflow, the major design decisions, and the files where each part lives. It describes the code as it exists today; it is not a claim that the prototype is a production-ready estimating system.

## 1. Purpose and implemented workflow

ConstructAI_MLCV is a construction drawing takeoff prototype. It turns text and dimension evidence in PDF, SVG, or image-based drawings into reviewed construction elements, a Bill of Quantities (BOQ), a rule-driven Bill of Materials (BOM), and a procurement handoff.

The primary application flow is:

1. **Upload a drawing** in the React workflow.
2. **Extract text, labels, and dimension annotations.** Depending on the drawing, the extractor reads a PDF text layer, SVG text nodes, or uses Tesseract OCR on a rendered page.
3. **Review extracted elements.** A reviewer can edit element fields and explicitly approve or reject each element. Editing an element returns it to pending review.
4. **Generate a BOQ** using only approved extraction elements. Quantities are calculated from available dimensions or use a supplied extracted quantity.
5. **Review and approve the BOQ.** BOQ edits return it to draft; approval requires a draft-to-review-to-approved transition.
6. **Map BOQ work to material recipes.** Automatic matching is rule/data driven. A reviewer can choose a same-unit recipe where matching is ambiguous or absent.
7. **Review the BOM and its validation.** Missing measurement basis, unresolved recipe matches, and other blockers prevent procurement approval. Warnings require acknowledgement.
8. **Approve the BOM for procurement.** The backend creates a read-only imported BOM snapshot and a separate editable procurement list.
9. **Continue in procurement.** Manage vendors, quotations, purchase orders, material packages, contract drafts, revisions, approvals, and PDF exports. Documents are not automatically signed or sent.

Human approval is a deliberate control in this pipeline. Confidence scores and automatic matches are evidence for review, not approval decisions.

## 2. Architecture at a glance

| Layer | Responsibility | Main implementation |
|---|---|---|
| HTTP backend | FastAPI routes, upload handling, in-process review sessions, workflow gates | `app/backend/main.py` |
| Extraction domain | File routing, positioned text/OCR, dimension parsing, annotation association, provenance | `src/constructai/extraction/` |
| BOQ domain | Typed BOQ contracts, deterministic quantity calculations, validation, status transitions | `src/constructai/boq/` |
| Material mapping | Same-unit recipe matching, quantities, deductions, pricing, scope/conflict checks | `src/constructai/agents/` |
| Engineering and catalog data | Materials, recipes, thresholds, work rules, deductions, scope, conflicts | `data/` |
| Main browser UI | Six-step upload-to-procurement React workflow | `app/frontend/src/` |
| Procurement service | Procurement API, ORM, database, templates, and its own browser UI | `src/constructai/procurement/` |
| Tests | Extraction, BOQ, mapping, approval, and procurement behavior | `tests/` |

The Python application package is under `src/constructai/`. The application entry point imports it through the configured Python package and starts with:

```powershell
uvicorn app.backend.main:app --reload
```

The frontend is a separate Vite development/build application. Procurement is mounted by the backend under `/procurement`, with its own API prefix and static UI.

## 3. Drawing extraction and measurement provenance

### File routing

`app/backend/main.py` configures the API's `ExtractionAgent` with `LocalExtractionProvider`. Therefore the API uses the local verified extraction pipeline rather than treating arbitrary image contours as measured building elements.

`src/constructai/extraction/local_provider.py` routes real drawings as follows:

- SVG `<text>` nodes are read with their positions when available.
- PDF pages with usable text and dimension annotations use the PDF text layer through PyMuPDF.
- PDFs without usable dimension text, raster images, and SVGs without text nodes are rendered and sent to Tesseract OCR.
- Existing `ELEMENT|...` fixture records are parsed through a deterministic compatibility path used by fixtures/tests.

`src/constructai/documents/renderer.py` handles rendering pages and supported drawing extensions. `src/constructai/extraction/text_providers.py` contains text providers used by the extraction layer.

`src/constructai/extraction/agent.py` is the routing/orchestration boundary. It also retains an injectable legacy OpenCV contour-candidate route for raster images. The API does not configure that route as its primary extraction path.

### Reading dimensions and associating evidence

- `src/constructai/extraction/ocr.py` locates and checks the Tesseract executable, preprocesses images, performs OCR, and returns positioned text lines. The Python package `pytesseract` alone is not the OCR engine; Tesseract must be installed separately. `TESSERACT_CMD` can point to its executable.
- `src/constructai/extraction/dimensions.py` parses explicit metric, imperial, paired, and area notations. It uses exact unit-conversion constants. A bare number is not assigned a unit unless the drawing explicitly declares one.
- `src/constructai/extraction/annotations.py` interprets positioned text, associates dimensions with labels only where evidence supports the association, and records annotations or unresolved items when interpretation is uncertain. OCR readings are cross-checked; unverified or ambiguous readings are not silently promoted to measured elements.
- `src/constructai/extraction/calibration.py` derives a drawing scale only when at least two independent references agree within tolerance. Calibration is reported as verified, single-reference, conflicting, or unavailable. Drawing pixels/points/SVG units are not treated as real-world lengths by default; calibration is not a license to invent missing dimensions.
- `src/constructai/extraction/vision.py` contains the reusable OpenCV contour candidate implementation. A trained YOLO detector/model and a labeled training dataset are not bundled.

### Extraction contracts

`src/constructai/extraction/schemas.py` defines Pydantic models for:

- `ExtractedElement`: element identity/type, description, quantity/unit, dimensions, confidence, review status, source references, and measurement provenance.
- `DimensionAnnotation` and `MeasurementValue`: raw drawing text plus parsed values, normalized values, unit, source, association, and verification information.
- `ScaleCalibration` and `ScaleReference`: calibration evidence and status.
- `UnresolvedItem` and `ExtractionResult`: unresolved evidence, warnings, diagnostics, and the result-level extraction method/status.

The dimension fields are optional and are not defaulted. Provenance such as OCR, text-layer, human input, and measurement status is retained to support review.

## 4. BOQ calculation, validation, and review

### Quantity calculation

`src/constructai/boq/calculator.py` applies deterministic formulas:

- For area units, walls/doors/windows use length × height when those dimensions are available; other area takeoffs can use length × width.
- For volume units, length × width × height is used when all three are present.
- For linear units, length is used.
- If the required dimensions are unavailable, a supplied quantity can be used; otherwise calculation fails explicitly.

`src/constructai/boq/generator.py` converts extraction elements to numbered BOQ items, stores the calculation basis, and collects extraction and BOQ validation issues.

### Validation and workflow states

- `src/constructai/boq/schemas.py` defines `BOQ`, `BOQItem`, `BOQStatus`, and validation issue models.
- `src/constructai/boq/validation.py` checks required text, units, negative quantities, low confidence, and differences between supplied and dimension-derived quantities. Low confidence is a warning, not approval.
- `src/constructai/boq/review.py` enforces BOQ transitions and edits. Draft BOQs can be submitted for review; only a BOQ in review can be approved. Approved BOQs cannot be edited directly.

The API also enforces gates in `app/backend/main.py`: every extraction element must be explicitly approved or rejected before BOQ generation, rejected elements are excluded, and an approved BOQ must still correspond to the current extraction revision.

## 5. BOQ-to-BOM material mapping

`src/constructai/agents/mapping_agent.py` implements the mapping and takeoff engine. At a high level it:

1. Compares each BOQ description with recipe work descriptions and aliases using a TF-IDF-style token vector and cosine similarity.
2. Restricts matches and reviewer recipe choices to the BOQ item's unit.
3. Applies thickness requirements, material recipe consumption rates, and volume allowances.
4. Applies supported opening deductions where an opening has an explicit `host_element_id` link to the host element.
5. Applies wastage and catalog rates, aggregates material totals, and reports costs and category totals.
6. Reports possible missing companion scope and work conflicts as review information; it does not silently add work to the BOQ/BOM.

Unmatched and low-confidence matches block a ready BOM until corrected. Manual mappings are marked and produce a confirmation warning. A recipe requiring thickness cannot proceed without an acceptable, explicit thickness basis. A catalog default is not substituted for missing project/drawing evidence.

The rules loader and cross-file validation live in `src/constructai/agents/bom_rules.py`. Rule files are loaded at application initialization; malformed rows or unknown work keys fail validation rather than silently falling back.

### Data-driven rule files

All adjustable mapping and takeoff assumptions are in `data/`; `data/BOM_RULES.md` documents their meaning and warns that example engineering values must be verified against project specifications and applicable measurement rules.

| File | Purpose |
|---|---|
| `data/recipes.csv` | Work keys, phrases, units, material consumption rates, and thickness requirement flags |
| `data/material_catalog.csv` | Material names/categories, purchase units, INR rates, and wastage percentages |
| `data/mapping_config.json` | Match thresholds, stopwords, thickness keywords, trusted dimension sources, and eligible element types for width-as-thickness |
| `data/units.csv` | Purchase units treated as countable and rounded to whole units |
| `data/work_rules.csv` | Valid thickness ranges, when reviewed wall width can be used, and volume allowances |
| `data/recipe_aliases.csv` | Additional match phrases by work key |
| `data/scope_rules.csv` | Expected companion work and optional suggested quantities; suggestions are not automatically added |
| `data/conflict_rules.csv` | Potentially double-counted pairs, reported as warnings |
| `data/deduction_rules.csv` | Opening-size bands, opening types, host work, and deduction fraction |

The configurable matching thresholds currently distinguish `OK`, `REVIEW`, and `NO MATCH`; exact values are in `data/mapping_config.json`. These labels describe matching confidence and do not replace a human decision.

## 6. BOM approval and procurement handoff

The handoff endpoint in `app/backend/main.py` only proceeds when the BOQ is approved, the BOM is not blocked, and required warning acknowledgement is supplied. BOM approval records the approver and comment.

`src/constructai/procurement/handoff.py` validates the payload through the same BOM parsing service used for imports, then:

- creates or reuses a procurement project;
- stores the approved BOM as an imported source snapshot with approval metadata;
- copies the material lines into a distinct, editable procurement list.

Changing BOQ inputs or recipe mappings invalidates the current approval record. Re-approval creates a new snapshot; earlier procurement data remains available.

### Procurement implementation

- `src/constructai/procurement/app.py` creates and mounts the procurement FastAPI sub-application, initializes the database, and serves the UI.
- `src/constructai/procurement/db.py` configures SQLAlchemy and the SQLite database. Default location: `var/procurement.db`; override with `PROC_DB_URL`.
- `src/constructai/procurement/models.py` defines project, BOM, procurement list/items, vendors, quotations, and related document models and workflow statuses.
- `src/constructai/procurement/routers/` separates project, procurement-list, vendor, purchase-order, package, contract, and history API routes.
- `src/constructai/procurement/services.py`, `schemas.py`, and `pdf.py` contain service logic, payload contracts, and PDF generation.
- `src/constructai/procurement/templates/` contains editable starter supply and contractor agreement templates.
- `src/constructai/procurement/ui/` contains the procurement browser UI.

The document workflow statuses are defined in `models.py`: draft, pending review, returned, approved, rejected, and finalized. Editable states are restricted by the model/service workflow. Approved procurement documents are revision-controlled rather than silently overwritten. Contracts remain drafts until people take the explicit next steps.

## 7. HTTP API and browser applications

### Main application API

The primary routes are implemented in `app/backend/main.py`:

| Route | Function |
|---|---|
| `GET /health` | Backend liveness |
| `GET /health/ocr` | Tesseract availability and diagnostic status |
| `POST /extractions` | Upload and extract a PDF, SVG, or supported image |
| `PATCH /extractions/{id}/elements/{index}` | Edit extraction evidence; edited element returns to pending |
| `POST /extractions/{id}/elements/{index}/review` | Explicitly approve or reject an extracted element |
| `POST /extractions/{id}/boq` | Generate a BOQ from the reviewed extraction |
| `PATCH /boqs/{id}/items/{number}` | Edit a BOQ line |
| `POST /boqs/{id}/submit`, `POST /boqs/{id}/approve`, `POST /boqs/{id}/reopen` | BOQ workflow transitions |
| `POST /boqs/{id}/bom` | Generate a BOM from an approved BOQ |
| `GET /boqs/{id}/mapping-options/{number}`, `PUT /boqs/{id}/mapping` | Retrieve same-unit recipe choices and save a reviewer mapping |
| `POST /boqs/{id}/bom/approve`, `GET /boqs/{id}/bom/approval` | Approve BOM for procurement and read approval information |
| `/procurement/api/...` | Mounted procurement API |
| `/procurement/ui/` | Mounted procurement UI |

The backend retains compatibility endpoints such as `POST /boq` and `POST /mapping`; the six-step frontend workflow uses server-side extraction/BOQ sessions and the gated BOQ/BOM routes.

### Frontend

- `app/frontend/src/main.tsx` mounts the React application.
- `app/frontend/src/App.tsx` implements the six named steps: upload, extraction, BOQ review, approval, BOM/mapping, and procurement. It calls the API, holds current screen state, and surfaces request errors.
- `app/frontend/src/styles.css` provides presentation and layout.
- `app/frontend/index.html`, `package.json`, and `vite.config.ts` define the Vite app shell, scripts/dependencies, and development configuration.

`VITE_API_BASE` can override the frontend API base; the default in `App.tsx` is `/api`.

## 8. Persistence and prototype boundaries

- Extraction results, revisions, BOQ review sessions, manual recipe overrides, and BOM approval records are held in Python process memory in `app/backend/main.py`. They are lost when the backend process restarts and are not a durable multi-user workflow store.
- Procurement entities are stored in SQLAlchemy-backed storage, SQLite by default at `var/procurement.db`. The procurement app creates tables and applies additive nullable-column upgrades at startup.
- Catalog rates and recipe quantities are starter data. They are not live supplier quotations and should not be treated as confirmed project pricing.
- OpenCV contour candidates are not a trained construction-plan recognition model. No trained YOLO weights or labeled training set is included.
- Extraction, calibration, and material outputs retain uncertainty and require comparison with the source drawing and project specifications. This prototype does not guarantee complete detection, measurement compliance, or procurement readiness for a real project.

## 9. Tests and what they cover

Tests are in `tests/` and run with `pytest`. The suite is organized around:

- API health and extraction: `test_health.py`, `test_extraction.py`, `test_real_extraction.py`
- Dimension parsing and scale calibration: `test_dimension_parser.py`, `test_calibration.py`
- Extraction schemas and vision candidates: `test_schemas.py`, `test_vision_extraction.py`
- BOQ calculation/review: `test_boq.py`, `test_boq_review.py`, `test_review_api.py`
- Data-driven BOM rules and approval gates: `test_bom_rules.py`, `test_bom_approval.py`
- Procurement end-to-end behavior: `tests/procurement/test_procurement_workflow.py`

These are automated tests of the implemented prototype behavior; passing tests do not certify engineering assumptions, OCR accuracy on arbitrary drawings, or suitability for live purchasing.

## 10. Development commands

### Python backend and tests

```powershell
python -m pip install -e ".[dev]"
uvicorn app.backend.main:app --reload
pytest
```

Install optional OCR/vision dependencies when needed:

```powershell
python -m pip install -e ".[dev,vision]"
```

Tesseract itself is a separate system installation. Set `TESSERACT_CMD` if its executable is not on `PATH`. `CONSTRUCTAI_LOG_LEVEL` controls backend logging, and `CONSTRUCTAI_SCALE_TOLERANCE_PCT` configures the scale-agreement tolerance.

### Frontend

```powershell
cd app/frontend
npm install
npm run dev
```

For a production frontend bundle, run `npm run build` from `app/frontend`.

## 11. Recommended reading order

1. `README.md` — quick start and operational workflow.
2. `app/backend/main.py` — API composition and server-side gates.
3. `src/constructai/extraction/local_provider.py` and `src/constructai/extraction/annotations.py` — drawing-to-evidence pipeline.
4. `src/constructai/extraction/schemas.py` — extraction contracts and provenance.
5. `src/constructai/boq/calculator.py`, `generator.py`, `validation.py`, and `review.py` — quantity and BOQ lifecycle.
6. `src/constructai/agents/mapping_agent.py` and `src/constructai/agents/bom_rules.py` — takeoff logic and rule loading.
7. `data/BOM_RULES.md` and the CSV/JSON files in `data/` — editable business/engineering assumptions.
8. `src/constructai/procurement/` — procurement persistence, routes, documents, and handoff.
9. `app/frontend/src/App.tsx` — user-facing workflow.
10. `tests/` — executable examples of the expected behavior.

## 12. Project configuration and reference files

- `pyproject.toml` — Python package metadata, Python version requirement, dependencies, pytest configuration, and packaged procurement assets.
- `README.md` — quick start, implemented workflow summary, BOM rules summary, and known vision limitations.
- `data/sample/` — sample drawings used for local exploration and tests.
- `var/procurement.db` — local procurement database created/used by the application; it is runtime data, not source code.
