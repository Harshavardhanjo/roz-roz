import uuid

from fastapi import APIRouter, Depends

from .. import stubs
from ..config import settings
from ..deps import current_member, require_owner, todo
from ..schemas import AbsenceCreate, HelperCreate, PayrollRunCreate

router = APIRouter(prefix="/api", tags=["helpers"])


@router.post("/households/{hid}/helpers")
def add_helper(hid: uuid.UUID, body: HelperCreate, owner: dict = Depends(require_owner)):
    if settings.use_stubs:
        return {"helper_id": stubs.HELPER_ID, "employment_id": stubs.EMPLOYMENT_ID,
                "whatsapp_link": "https://wa.me/910000000000?text=Namaste"}
    todo("upsert helper by whatsapp_e164; create employment + helper_spending wallet")


@router.patch("/employments/{eid}")
def patch_employment(eid: uuid.UUID, body: dict, owner: dict = Depends(require_owner)):
    if settings.use_stubs:
        return {**stubs.DASHBOARD["helpers"][0], **body}
    todo("update employment terms")


@router.get("/employments/{eid}")
def helper_detail(eid: uuid.UUID, member: dict = Depends(current_member)):
    if settings.use_stubs:
        return {"employment": stubs.DASHBOARD["helpers"][0],
                "leave_days": [{"date": "2026-10-08", "kind": "paid", "fraction": 1.0},
                               {"date": "2026-10-20", "kind": "paid", "fraction": 1.0}],
                "requests": [stubs.REQUEST, stubs.VOTE_REQUEST], "payroll": []}
    todo("helper detail")


@router.post("/employments/{eid}/absences")
def mark_absent(eid: uuid.UUID, body: AbsenceCreate, member: dict = Depends(current_member)):
    if settings.use_stubs:
        return {"date": body.date.isoformat(), "kind": "unpaid", "fraction": body.fraction, "marked_by": member["member_id"]}
    todo("services.leave.record_leave for a member-marked absence")


@router.post("/employments/{eid}/payroll/run")
def run_payroll(eid: uuid.UUID, body: PayrollRunCreate, owner: dict = Depends(require_owner)):
    if settings.use_stubs:
        return {**stubs.PAYROLL_RUN, "month": body.month}
    todo("services.payroll.run_payroll")


@router.get("/employments/{eid}/payroll")
def payroll_history(eid: uuid.UUID, member: dict = Depends(current_member)):
    if settings.use_stubs:
        return [stubs.PAYROLL_RUN]
    todo("payroll history")
