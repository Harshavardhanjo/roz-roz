import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..deps import current_member, employment_of, household_of, require_owner
from ..errors import bad_request
from ..models import Member, PayrollRun
from ..schemas import AbsenceCreate, EmploymentUpdate, HelperCreate, PayrollRunCreate
from ..services import audit, households, leave, payroll, views

router = APIRouter(prefix="/api", tags=["helpers"])


@router.post("/households/{hid}/helpers", status_code=201)
def add_helper(
    hid: uuid.UUID, body: HelperCreate, owner: Member = Depends(require_owner), db: Session = Depends(get_db)
):
    helper, employment = households.add_helper(db, household_of(db, owner, hid), body, owner)
    db.commit()
    return {
        "helper_id": str(helper.id),
        "employment_id": str(employment.id),
        "whatsapp_link": households.whatsapp_link(),
    }


@router.patch("/employments/{eid}")
def patch_employment(
    eid: uuid.UUID, body: EmploymentUpdate, owner: Member = Depends(require_owner), db: Session = Depends(get_db)
):
    employment = households.update_employment(db, employment_of(db, owner, eid), body, owner)
    db.commit()
    return views.employment_detail(db, employment)


@router.get("/employments/{eid}")
def helper_detail(eid: uuid.UUID, member: Member = Depends(current_member), db: Session = Depends(get_db)):
    return views.employment_detail(db, employment_of(db, member, eid))


@router.post("/employments/{eid}/absences", status_code=201)
def mark_absent(
    eid: uuid.UUID, body: AbsenceCreate, member: Member = Depends(current_member), db: Session = Depends(get_db)
):
    employment = employment_of(db, member, eid)
    if body.date.weekday() in employment.weekly_off:
        raise bad_request("weekly_off", "That day is the helper's weekly off")
    (entry,) = leave.record_leave(
        db, employment, body.date, body.date, half_day=body.fraction < 1, marked_by=f"member:{member.id}"
    )
    audit.log(
        db,
        household_id=employment.household_id,
        actor=f"member:{member.id}",
        action="mark_absent",
        entity="employment",
        entity_id=employment.id,
        summary=f"{member.name} marked an absence on {body.date.isoformat()}",
    )
    db.commit()
    return {
        "date": entry.date.isoformat(),
        "kind": entry.kind,
        "fraction": float(entry.fraction),
        "marked_by": entry.marked_by,
    }


@router.post("/employments/{eid}/payroll/run")
def run_payroll(
    eid: uuid.UUID, body: PayrollRunCreate, owner: Member = Depends(require_owner), db: Session = Depends(get_db)
):
    employment = employment_of(db, owner, eid)
    if body.month > clock.current_month():
        raise bad_request("future_month", "Payroll can't run for a future month")
    run = payroll.run(db, employment, body.month, actor=f"member:{owner.id}")
    db.commit()
    return views.payroll_out(run)


@router.get("/employments/{eid}/payroll")
def payroll_history(eid: uuid.UUID, member: Member = Depends(current_member), db: Session = Depends(get_db)):
    employment = employment_of(db, member, eid)
    runs = db.scalars(
        select(PayrollRun).where(PayrollRun.employment_id == employment.id).order_by(PayrollRun.month.desc())
    ).all()
    return [views.payroll_out(r) for r in runs]
