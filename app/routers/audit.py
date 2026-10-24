import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_member, household_of
from ..models import AuditLog, Member
from ..services import views

router = APIRouter(prefix="/api", tags=["audit"])


@router.get("/households/{hid}/audit")
def audit_log(
    hid: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=500),
    member: Member = Depends(current_member),
    db: Session = Depends(get_db),
):
    household_of(db, member, hid)
    rows = db.scalars(select(AuditLog).where(AuditLog.household_id == hid).order_by(AuditLog.id.desc()).limit(limit))
    return [views.audit_out(r) for r in rows]
