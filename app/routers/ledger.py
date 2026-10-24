import re
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..deps import current_member, household_of
from ..errors import bad_request
from ..models import Member
from ..money import inr
from ..providers.payment import EntryMeta, house_wallet, provider
from ..schemas import TopupCreate
from ..services import audit, contributions, views

router = APIRouter(prefix="/api", tags=["ledger"])


def _month(month: str | None) -> str:
    if month is None:
        return clock.current_month()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise bad_request("invalid_month", "month must be YYYY-MM")
    return month


@router.get("/households/{hid}/ledger")
def ledger(
    hid: uuid.UUID, month: str | None = None, member: Member = Depends(current_member), db: Session = Depends(get_db)
):
    household_of(db, member, hid)
    return views.ledger_page(db, hid, _month(month))


@router.get("/households/{hid}/contributions")
def get_contributions(
    hid: uuid.UUID, month: str | None = None, member: Member = Depends(current_member), db: Session = Depends(get_db)
):
    household_of(db, member, hid)
    return contributions.compute(db, hid, _month(month))


@router.post("/households/{hid}/topups", status_code=201)
def topup(hid: uuid.UUID, body: TopupCreate, member: Member = Depends(current_member), db: Session = Depends(get_db)):
    household_of(db, member, hid)
    wallet = house_wallet(db, hid)
    entry = provider.credit(db, wallet, body.amount_paise, EntryMeta(kind="topup", member_id=member.id))
    audit.log(
        db,
        household_id=hid,
        actor=f"member:{member.id}",
        action="topup",
        entity="ledger_entry",
        entity_id=entry.id,
        summary=f"{member.name} topped up {inr(body.amount_paise)} (simulated)",
    )
    db.commit()
    return {"ledger_entry_id": str(entry.id), "house_balance_paise": provider.balance(db, wallet)}
