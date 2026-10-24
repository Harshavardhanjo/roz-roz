import uuid

from fastapi import APIRouter, Depends

from .. import stubs
from ..config import settings
from ..deps import current_member, todo
from ..schemas import VoteCreate

router = APIRouter(prefix="/api", tags=["requests"])


@router.get("/households/{hid}/requests")
def list_requests(hid: uuid.UUID, status: str | None = None, member: dict = Depends(current_member)):
    if settings.use_stubs:
        items = [stubs.REQUEST, stubs.VOTE_REQUEST]
        return [r for r in items if status is None or r["status"] == status]
    todo("list requests")


@router.post("/requests/{rid}/votes")
def vote(rid: uuid.UUID, body: VoteCreate, member: dict = Depends(current_member)):
    if settings.use_stubs:
        status = "executed" if body.decision == "approve" else "rejected"
        return {**stubs.VOTE_REQUEST, "id": str(rid), "status": status,
                "votes": [{"member_id": member["member_id"], "decision": body.decision}]}
    todo("services.rules.apply_vote (409 if already decided)")
