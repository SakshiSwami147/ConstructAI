from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.backend import main
from constructai.extraction.schemas import ExtractedElement, ExtractionResult


@pytest.fixture
def review_session(monkeypatch):
    main.extraction_sessions.clear()
    main.extraction_revisions.clear()
    main.boq_sessions.clear()
    main.boq_extraction_revisions.clear()

    def fake_extract(source):
        return ExtractionResult(
            source_name=source.name,
            elements=[
                ExtractedElement(
                    element_type="candidate",
                    element_id="E-001",
                    description="Uncertain object",
                    quantity=Decimal("2"),
                    unit="pcs",
                    confidence=0.99,
                    review_reasons=["prototype_classification"],
                )
            ],
        )

    monkeypatch.setattr(main.extraction_agent, "extract", fake_extract)
    with TestClient(main.app) as client:
        response = client.post(
            "/extractions",
            files={"file": ("drawing.svg", b"<svg />", "image/svg+xml")},
        )
        assert response.status_code == 200
        yield client, response.json()["extraction_id"]


def approve_element(client: TestClient, extraction_id: str, fields: dict | None = None) -> dict:
    if fields is not None:
        response = client.patch(
            f"/extractions/{extraction_id}/elements/0",
            json=fields,
        )
        assert response.status_code == 200
    response = client.post(
        f"/extractions/{extraction_id}/elements/0/review",
        json={"decision": "approved"},
    )
    assert response.status_code == 200
    return response.json()


def test_pending_and_rejected_elements_cannot_generate_boq(review_session) -> None:
    client, extraction_id = review_session

    assert client.post(f"/extractions/{extraction_id}/boq").status_code == 409
    rejected = client.post(
        f"/extractions/{extraction_id}/elements/0/review",
        json={"decision": "rejected"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["elements"][0]["review_status"] == "rejected"
    assert client.post(f"/extractions/{extraction_id}/boq").status_code == 409


def test_corrected_extraction_values_feed_boq(review_session) -> None:
    client, extraction_id = review_session
    approve_element(
        client,
        extraction_id,
        {
            "element_type": "fixture",
            "description": "Corrected light fitting",
            "quantity": 14,
            "unit": "pcs",
            "specification": "LED",
        },
    )

    response = client.post(f"/extractions/{extraction_id}/boq")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["element_type"] == "fixture"
    assert item["description"] == "Corrected light fitting"
    assert item["quantity"] == 14
    assert item["unit"] == "pcs"


def test_corrected_dimensions_are_used_for_boq_quantity(review_session) -> None:
    client, extraction_id = review_session
    approve_element(
        client,
        extraction_id,
        {
            "element_type": "wall",
            "description": "Measured wall",
            "dimensions": {"length": 5, "height": 3},
            "quantity": None,
            "unit": "m2",
        },
    )

    response = client.post(f"/extractions/{extraction_id}/boq")

    assert response.status_code == 200
    assert response.json()["items"][0]["quantity"] == 15


def test_missing_required_values_block_element_approval(review_session) -> None:
    client, extraction_id = review_session
    client.patch(f"/extractions/{extraction_id}/elements/0", json={"unit": ""})
    response = client.post(
        f"/extractions/{extraction_id}/elements/0/review",
        json={"decision": "approved"},
    )

    assert response.status_code == 422


def test_clearing_dimensions_does_not_retain_previous_ocr_values(review_session) -> None:
    client, extraction_id = review_session
    added = client.patch(
        f"/extractions/{extraction_id}/elements/0",
        json={"dimensions": {"length": 4, "height": 3}},
    )
    assert added.status_code == 200
    cleared = client.patch(
        f"/extractions/{extraction_id}/elements/0",
        json={"dimensions": None},
    )

    assert cleared.status_code == 200
    assert cleared.json()["elements"][0]["dimensions"] is None
    assert cleared.json()["elements"][0]["dimensions_source"] is None


def test_final_approval_requires_review_and_validations(review_session) -> None:
    client, extraction_id = review_session
    approve_element(client, extraction_id)
    generated = client.post(f"/extractions/{extraction_id}/boq").json()
    boq_id = generated["boq_id"]

    assert client.post(f"/boqs/{boq_id}/approve").status_code == 409
    assert client.post(f"/boqs/{boq_id}/submit").status_code == 200
    invalid = client.patch(f"/boqs/{boq_id}/items/1", json={"unit": "bucket"})
    assert invalid.status_code == 200
    assert any(issue["severity"] == "error" for issue in invalid.json()["validation_issues"])
    assert client.post(f"/boqs/{boq_id}/submit").status_code == 200
    assert client.post(f"/boqs/{boq_id}/approve").status_code == 409


def test_editing_approved_element_invalidates_old_boq(review_session) -> None:
    client, extraction_id = review_session
    approve_element(client, extraction_id)
    boq = client.post(f"/extractions/{extraction_id}/boq").json()
    assert client.post(f"/boqs/{boq['boq_id']}/submit").status_code == 200

    edited = client.patch(
        f"/extractions/{extraction_id}/elements/0",
        json={"description": "Corrected after approval"},
    )

    assert edited.status_code == 200
    assert edited.json()["elements"][0]["review_status"] == "pending"
    assert client.post(f"/boqs/{boq['boq_id']}/approve").status_code == 409
    assert client.post(f"/extractions/{extraction_id}/boq").status_code == 409