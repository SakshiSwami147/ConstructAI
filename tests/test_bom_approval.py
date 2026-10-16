"""Step 06: human BOM approval gate and handoff into procurement."""
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app.backend import main
from constructai.extraction.schemas import ExtractedElement, ExtractionResult

PLASTER = {"element_type": "wall", "element_id": "P1", "description": "Internal wall plaster 12 mm thick",
           "quantity": D("50"), "unit": "m2"}
PAINT = {"element_type": "wall", "element_id": "P2", "description": "Interior emulsion paint coats",
         "quantity": D("50"), "unit": "m2"}
MASONRY = {"element_type": "wall", "element_id": "W1", "description": "Brick masonry 230 mm thick external wall",
           "quantity": D("30"), "unit": "m2"}
UNKNOWN = {"element_type": "candidate", "element_id": "X1", "description": "Uncertain object",
           "quantity": D("2"), "unit": "pcs"}


@pytest.fixture
def flow(monkeypatch):
    for store in (main.extraction_sessions, main.extraction_revisions, main.boq_sessions,
                  main.boq_extraction_revisions, main.boq_recipe_overrides, main.bom_approvals):
        store.clear()
    elements: list[dict] = []

    def fake_extract(source):
        return ExtractionResult(source_name="Block-A.pdf",
                                elements=[ExtractedElement(confidence=0.9, **e) for e in elements])

    monkeypatch.setattr(main.extraction_agent, "extract", fake_extract)

    def approved_boq(client, *els):
        elements[:] = list(els)
        ext = client.post("/extractions", files={"file": ("d.svg", b"<svg />", "image/svg+xml")}).json()
        for i in range(len(els)):
            assert client.post(f"/extractions/{ext['extraction_id']}/elements/{i}/review",
                               json={"decision": "approved"}).status_code == 200
        boq = client.post(f"/extractions/{ext['extraction_id']}/boq").json()
        client.post(f"/boqs/{boq['boq_id']}/submit")
        client.post(f"/boqs/{boq['boq_id']}/approve")
        return ext["extraction_id"], boq["boq_id"]

    with TestClient(main.app) as client:
        yield client, approved_boq


def approve(client, boq_id, **body):
    return client.post(f"/boqs/{boq_id}/bom/approve", json={"approved_by": "Site Engineer", **body})


def test_approval_hands_bom_to_procurement(flow):
    client, approved_boq = flow
    _, boq_id = approved_boq(client, PLASTER, PAINT)
    bom = client.post(f"/boqs/{boq_id}/bom").json()
    assert bom["validation"]["status"] == "ready" and bom["validation"]["warnings"] == []

    assert client.post(f"/boqs/{boq_id}/bom/approve", json={"approved_by": "   "}).status_code == 422
    r = approve(client, boq_id, comment="Quantities checked", project_code="BLKA")
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["approved_by"] == "Site Engineer" and rec["material_count"] == len(bom["lines"])

    # the procurement list exists, copied from the approved BOM using Order qty
    plist = client.get(f"/procurement/api/procurement-lists/{rec['procurement']['list_id']}").json()
    by_name = {i["name"]: i for i in plist["items"]}
    for line in bom["lines"]:
        assert by_name[line["Material"]]["quantity"] == line["Order qty"]
    pbom = client.get(f"/procurement/api/boms/{rec['procurement']['bom_id']}").json()
    assert pbom["approved_by"] == "Site Engineer" and pbom["approval_comment"] == "Quantities checked"
    assert pbom["read_only"] is True
    project = client.get(f"/procurement/api/projects/{rec['procurement']['project_id']}").json()
    assert project["name"] == "Block-A.pdf" and project["code"] == "BLKA"

    assert approve(client, boq_id).status_code == 409  # no silent re-approval
    assert client.get(f"/boqs/{boq_id}/bom/approval").json()["approved_by"] == "Site Engineer"


def test_warnings_must_be_acknowledged(flow):
    client, approved_boq = flow
    _, boq_id = approved_boq(client, MASONRY)
    warnings = client.post(f"/boqs/{boq_id}/bom").json()["validation"]["warnings"]
    assert warnings  # missing plaster / paint scope
    r = approve(client, boq_id)
    assert r.status_code == 409 and "acknowledge" in r.json()["detail"]
    r = approve(client, boq_id, acknowledge_warnings=True)
    assert r.status_code == 201 and r.json()["warnings_acknowledged"] == warnings
    pbom = client.get(f"/procurement/api/boms/{r.json()['procurement']['bom_id']}").json()
    assert pbom["import_warnings"] == warnings


def test_blocked_bom_cannot_be_approved(flow):
    client, approved_boq = flow
    _, boq_id = approved_boq(client, UNKNOWN)
    r = approve(client, boq_id, acknowledge_warnings=True)
    assert r.status_code == 409 and "blocking" in r.json()["detail"]


def test_bom_approval_requires_approved_boq(flow):
    client, approved_boq = flow
    _, boq_id = approved_boq(client, PLASTER, PAINT)
    client.post(f"/boqs/{boq_id}/reopen")
    assert approve(client, boq_id).status_code == 409


def test_reopen_invalidates_approval_and_reapproval_reuses_project(flow):
    client, approved_boq = flow
    ext_id, boq_id = approved_boq(client, PLASTER, PAINT)
    first = approve(client, boq_id).json()
    client.post(f"/boqs/{boq_id}/reopen")
    assert client.get(f"/boqs/{boq_id}/bom/approval").status_code == 404
    client.post(f"/boqs/{boq_id}/submit")
    client.post(f"/boqs/{boq_id}/approve")
    second = approve(client, boq_id).json()
    assert second["procurement"]["project_id"] == first["procurement"]["project_id"]
    assert second["procurement"]["bom_id"] != first["procurement"]["bom_id"]
    assert "(approval 2)" in second["procurement"]["bom_name"]


def test_mapping_change_invalidates_approval(flow):
    client, approved_boq = flow
    _, boq_id = approved_boq(client, PLASTER, PAINT)
    approve(client, boq_id)
    client.put(f"/boqs/{boq_id}/mapping", json={"item_number": 1, "work_key": "plaster_int"})
    assert client.get(f"/boqs/{boq_id}/bom/approval").status_code == 404


def test_procurement_ui_is_served(flow):
    client, _ = flow
    page = client.get("/procurement/ui/")
    assert page.status_code == 200 and "static/app.js" in page.text
    assert client.get("/procurement/ui/static/app.js").status_code == 200
    assert client.get("/procurement/api/health").json() == {"status": "ok"}
