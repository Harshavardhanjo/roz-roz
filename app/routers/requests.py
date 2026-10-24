import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_member, household_of, request_of
from ..errors import bad_request
from ..models import Member, Request
from ..schemas import VoteCreate
from ..services import requests, views

router = APIRouter(prefix="/api", tags=["requests"])

STATUSES = ("pending", "auto_approved", "needs_vote", "needs_topup", "approved", "rejected", "executed")


@router.get("/households/{hid}/requests")
def list_requests(
    hid: uuid.UUID, status: str | None = None, member: Member = Depends(current_member), db: Session = Depends(get_db)
):
    household_of(db, member, hid)
    query = select(Request).where(Request.household_id == hid)
    if status is not None:
        if status not in STATUSES:
            raise bad_request("invalid_status", f"status must be one of {', '.join(STATUSES)}")
        query = query.where(Request.status == status)
    return [views.request_out(db, r) for r in db.scalars(query.order_by(Request.created_at.desc()).limit(200))]


@router.post("/requests/{rid}/votes")
def vote(rid: uuid.UUID, body: VoteCreate, member: Member = Depends(current_member), db: Session = Depends(get_db)):
    req = requests.vote(db, request_of(db, member, rid), member, body.decision)
    db.commit()
    return views.request_out(db, req)
