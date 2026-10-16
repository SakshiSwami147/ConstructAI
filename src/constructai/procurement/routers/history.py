"""Approval / document history and project summary."""
from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..db import get_db
from ..schemas import ser_event
from ..services import get_or_404, po_totals, package_totals, r2

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/projects/{pid}/history")
def history(pid: int, doc_type: str | None = None, doc_id: int | None = None, limit: int = 500,
            db: Session = Depends(get_db)):
    stmt = select(m.DocumentEvent).where(m.DocumentEvent.project_id == pid).order_by(m.DocumentEvent.id.desc()).limit(limit)
    if doc_type:
        stmt = stmt.where(m.DocumentEvent.doc_type == doc_type)
    if doc_id:
        stmt = stmt.where(m.DocumentEvent.doc_id == doc_id)
    return [ser_event(e) for e in db.scalars(stmt)]


@router.get("/projects/{pid}/summary")
def summary(pid: int, db: Session = Depends(get_db)):
    get_or_404(db, m.Project, pid, "Project")
    pos = db.scalars(select(m.PurchaseOrder).where(m.PurchaseOrder.project_id == pid,
                                                   m.PurchaseOrder.superseded_by_id.is_(None))).all()
    pks = db.scalars(select(m.Package).where(m.Package.project_id == pid, m.Package.superseded_by_id.is_(None))).all()
    cts = db.scalars(select(m.Contract).where(m.Contract.project_id == pid, m.Contract.superseded_by_id.is_(None))).all()
    lists = db.scalars(select(m.ProcurementList).where(m.ProcurementList.project_id == pid)).all()
    boms = db.scalars(select(m.Bom).where(m.Bom.project_id == pid)).all()
    live = lambda d: d.status != m.REJECTED
    return {
        "boms": {"imported": sum(b.source == "imported" for b in boms), "manual_test": sum(b.source != "imported" for b in boms)},
        "procurement_lists": len(lists),
        "estimated_value": r2(sum(i.quantity * (i.est_rate or 0) for pl in lists for i in pl.items)),
        "po": {"count": len(pos), "value": r2(sum(po_totals(p)["total"] for p in pos if live(p))),
               "by_status": dict(Counter(p.status for p in pos))},
        "package": {"count": len(pks), "value": r2(sum(package_totals(p)["total"] for p in pks if live(p))),
                    "by_status": dict(Counter(p.status for p in pks))},
        "contract": {"count": len(cts), "by_status": dict(Counter(c.status for c in cts))},
        "pending_review": sum(d.status == m.PENDING for d in [*pos, *pks, *cts]),
    }
