import uuid

from fastapi import APIRouter, Depends

from .. import stubs
from ..config import settings
from ..deps import current_member, todo

router = APIRouter(prefix="/api", tags=["audit"])


@router.get("/households/{hid}/audit")
def audit(hid: uuid.UUID, limit: int = 50, member: dict = Depends(current_member)):
    if settings.use_stubs:
        return [stubs.AUDIT_ENTRY]
    todo("audit_log rows, newest first")
