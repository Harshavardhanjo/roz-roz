import uuid

from fastapi import APIRouter, Depends

from .. import stubs
from ..config import settings
from ..deps import current_member, todo
from ..schemas import TopupCreate

router = APIRouter(prefix="/api", tags=["ledger"])


@router.get("/households/{hid}/ledger")
def ledger(hid: uuid.UUID, month: str | None = None, member: dict = Depends(current_member)):
    if settings.use_stubs:
        return {"entries": [stubs.LEDGER_ENTRY]}
    todo("ledger entries for month")


@router.get("/households/{hid}/contributions")
def contributions(hid: uuid.UUID, month: str | None = None, member: dict = Depends(current_member)):
    if settings.use_stubs:
        return stubs.CONTRIBUTIONS
    todo("services.contributions.statement")


@router.post("/households/{hid}/topups")
def topup(hid: uuid.UUID, body: TopupCreate, member: dict = Depends(current_member)):
    if settings.use_stubs:
        return {"ledger_entry_id": "1ed90000-0000-4000-8000-000000000002",
                "house_balance_paise": stubs.DASHBOARD["house_wallet"]["balance_paise"] + body.amount_paise}
    todo("provider.credit(house wallet) with member_id")
