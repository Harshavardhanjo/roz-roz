"""USE_STUBS=true: the contract 2 and 3 example payloads, no database. Lets the web app and agents run without the
real backend. Shapes must stay identical to the real API (tests/test_contract_shapes.py checks the real side)."""

import secrets
import uuid

from fastapi import APIRouter, Depends, Header
from pydantic import ValidationError

from . import stubs
from .config import settings
from .deps import tools_auth
from .errors import forbidden
from .schemas import (
    TOOL_ARGS,
    AbsenceCreate,
    EmploymentUpdate,
    HelperCreate,
    HouseholdCreate,
    MemberCreate,
    MemberUpdate,
    PayrollRunCreate,
    RulesUpdate,
    SignupCreate,
    ToolCall,
    TopupCreate,
    VoteCreate,
)

router = APIRouter(prefix="/api", tags=["stubs"])
tools_router = APIRouter(prefix="/tools", tags=["stubs"], dependencies=[Depends(tools_auth)])


def stub_member(x_roz_token: str | None = Header(default=None)) -> dict:
    if not x_roz_token:
        raise forbidden("missing_token", "X-Roz-Token header is required")
    return stubs.ME


def _link() -> tuple[str, str]:
    token = secrets.token_urlsafe(24)
    return token, f"{settings.web_origins[0]}/h/{token}"


@router.post("/households")
def create_household(body: HouseholdCreate):
    token, link = _link()
    return {"household_id": stubs.HOUSEHOLD_ID, "member_id": stubs.OWNER_ID, "token": token, "link": link}


@router.get("/me")
def me(member: dict = Depends(stub_member)):
    return member


@router.post("/households/{hid}/members")
def add_member(hid: uuid.UUID, body: MemberCreate, member: dict = Depends(stub_member)):
    token, link = _link()
    return {"member_id": stubs.ROOMMATE_ID, "token": token, "link": link}


@router.patch("/members/{mid}")
def update_member(mid: uuid.UUID, body: MemberUpdate, member: dict = Depends(stub_member)):
    return {"member_id": str(mid), "split_weight": body.split_weight}


@router.put("/households/{hid}/rules")
def put_rules(hid: uuid.UUID, body: RulesUpdate, member: dict = Depends(stub_member)):
    return body.model_dump()


@router.post("/members/{mid}/grant")
def create_grant(mid: uuid.UUID, member: dict = Depends(stub_member)):
    return {
        "grant_id": "local_stub",
        "scopes": [f"roz:advance:emp:{stubs.EMPLOYMENT_ID}:max_paise:50000"],
        "status": "active",
    }


@router.get("/households/{hid}/dashboard")
def dashboard(hid: uuid.UUID, member: dict = Depends(stub_member)):
    return stubs.DASHBOARD


@router.post("/households/{hid}/helpers")
def add_helper(hid: uuid.UUID, body: HelperCreate, member: dict = Depends(stub_member)):
    return {
        "helper_id": stubs.HELPER_ID,
        "employment_id": stubs.EMPLOYMENT_ID,
        "whatsapp_link": "https://wa.me/910000000000?text=Namaste",
    }


@router.patch("/employments/{eid}")
def patch_employment(eid: uuid.UUID, body: EmploymentUpdate, member: dict = Depends(stub_member)):
    return stubs.EMPLOYMENT_DETAIL


@router.get("/employments/{eid}")
def helper_detail(eid: uuid.UUID, member: dict = Depends(stub_member)):
    return stubs.EMPLOYMENT_DETAIL


@router.post("/employments/{eid}/absences")
def mark_absent(eid: uuid.UUID, body: AbsenceCreate, member: dict = Depends(stub_member)):
    return {"date": body.date.isoformat(), "kind": "unpaid", "fraction": body.fraction, "marked_by": stubs.OWNER_ID}


@router.post("/employments/{eid}/payroll/run")
def run_payroll(eid: uuid.UUID, body: PayrollRunCreate, member: dict = Depends(stub_member)):
    return {**stubs.PAYROLL_RUN, "month": body.month}


@router.get("/employments/{eid}/payroll")
def payroll_history(eid: uuid.UUID, member: dict = Depends(stub_member)):
    return [stubs.PAYROLL_RUN]


@router.get("/households/{hid}/requests")
def list_requests(hid: uuid.UUID, status: str | None = None, member: dict = Depends(stub_member)):
    return [r for r in (stubs.REQUEST, stubs.VOTE_REQUEST) if status is None or r["status"] == status]


@router.post("/requests/{rid}/votes")
def vote(rid: uuid.UUID, body: VoteCreate, member: dict = Depends(stub_member)):
    status = "executed" if body.decision == "approve" else "rejected"
    return {
        **stubs.VOTE_REQUEST,
        "id": str(rid),
        "status": status,
        "votes": [{"member_id": stubs.OWNER_ID, "name": "Harsha", "decision": body.decision}],
    }


@router.get("/households/{hid}/ledger")
def ledger(hid: uuid.UUID, month: str | None = None, member: dict = Depends(stub_member)):
    return {"month": month or "2026-10", "entries": [stubs.LEDGER_ENTRY]}


@router.get("/households/{hid}/contributions")
def contributions(hid: uuid.UUID, month: str | None = None, member: dict = Depends(stub_member)):
    return stubs.CONTRIBUTIONS


@router.post("/households/{hid}/topups")
def topup(hid: uuid.UUID, body: TopupCreate, member: dict = Depends(stub_member)):
    return {
        "ledger_entry_id": "1ed90000-0000-4000-8000-000000000002",
        "house_balance_paise": stubs.DASHBOARD["house_wallet"]["balance_paise"] + body.amount_paise,
    }


@router.get("/households/{hid}/audit")
def audit(hid: uuid.UUID, limit: int = 50, member: dict = Depends(stub_member)):
    return [stubs.AUDIT_ENTRY]


@router.post("/signups")
def create_signup(body: SignupCreate):
    return {"ok": True}


@router.get("/stats")
def stats():
    return stubs.STATS


@tools_router.post("/{name}")
def call_tool(name: str, call: ToolCall):
    model = TOOL_ARGS.get(name)
    if model is None:
        return {"ok": False, "error": {"code": "unknown_tool", "message": name}}
    try:
        model.model_validate(call.args)
    except ValidationError as e:
        return {
            "ok": False,
            "error": {"code": "invalid_args", "message": e.errors(include_url=False, include_input=False)},
        }
    return {"ok": True, "result": stubs.TOOL_RESULTS[name]}
