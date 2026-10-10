# ConstructAI_MLCV

Milestone 1 foundation for the Drawing/PDF to approved BOQ workflow.

## Backend

```powershell
python -m pip install -e ".[dev]"
uvicorn app.backend.main:app --reload
```

The API exposes `GET /health`, drawing extraction, and server-enforced extraction and BOQ review gates.

## OpenCV floor-plan extraction

The project now includes a reusable vision module at `src/constructai/extraction/vision.py`.

### What it does

- loads a floor-plan image with OpenCV
- converts to grayscale
- applies thresholding and Canny edge detection
- detects contours and classifies likely construction objects such as walls, doors, windows, columns, and beams
- returns structured `ExtractedElement` values compatible with the existing extraction contract
- preserves `source_page` and `source_reference` metadata
- keeps uncertain detections low-confidence and ready for human review
- does not invent missing dimensions or quantities

### Important limitation

A fully trained YOLO object detector or a real labeled construction-drawing dataset is not bundled in this repository. The system includes a YOLO-ready integration class, but it will only work after you provide:

- a trained model weights file (`.weights` or a PyTorch YOLO export)
- a matching config file
- a names file with class labels
- a labeled floor-plan dataset for training or fine-tuning

This is intentional: the code does not pretend that the vision model is already fully trained or accurate for production use.

### Optional OCR support

If `pytesseract` is installed, the detector can try to read labels and dimension text from detected regions. If OCR is not available, the code leaves those fields empty and relies on human review instead of guessing.

```powershell
python -m pip install -e ".[dev,vision]"
```

## Run the extraction endpoint locally

```powershell
$env:PYTHONPATH = "src"
uvicorn app.backend.main:app --reload
```

Then upload a PDF, SVG, or image floor-plan drawing to `POST /extractions` using the `file` multipart field. The sample fixture is `data/sample/sample_drawing.svg`.

Each extraction response includes an `extraction_id`. Correct detections with `PATCH /extractions/{extraction_id}/elements/{index}`, then explicitly approve or reject each element with `POST /extractions/{extraction_id}/elements/{index}/review` and a `{"decision":"approved"}` or `{"decision":"rejected"}` body. Confidence scores do not approve detections, and OCR-derived dimensions remain marked for review.

Generate a BOQ with `POST /extractions/{extraction_id}/boq`. BOQ edits use `PATCH /boqs/{boq_id}/items/{item_number}`; transition through `POST /boqs/{boq_id}/submit` and `POST /boqs/{boq_id}/approve` for final approval. Review sessions are held in process memory for this prototype and are lost when the backend restarts.

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
- `src/constructai/extraction`: extraction contracts, text providers, and reusable vision pipeline.
- `src/constructai/boq`: validated BOQ data contracts and quantity logic.
- `src/constructai/agents`: mapping and material-selection logic.
- `tests`: focused backend and vision tests.

## Human-in-the-loop workflow

The project is intentionally designed so that a human reviews outputs after each major step:

- upload review
- extraction review
- validation review
- BOQ review
- material mapping review
- final approval

This prevents uncertain detections or missing values from silently propagating into the downstream estimate.
