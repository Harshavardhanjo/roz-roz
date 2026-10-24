"""Contract 3: POST /tools/{name}, called by the liaison and treasurer agents.

Every call: bearer auth -> args validated against app/schemas.py -> idempotency check -> handler in one transaction ->
audit row. Failures return {"ok": false, "error": {code, message}} with HTTP 200 so agents always get a body to read."""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..deps import tools_auth
from ..errors import ApiError, bad_request, conflict, not_found
from ..models import Employment, Helper, Household, ToolCallRecord
from ..money import rupees
from ..providers.payment import EntryMeta, provider, spending_wallet
from ..schemas import (
    TOOL_ARGS,
    CreateLeaveRequestArgs,
    CreateMoneyRequestArgs,
    EmploymentArgs,
    GetHelperContextArgs,
    OpenVoteArgs,
    PostContributionsArgs,
    RecordConsentArgs,
    RecordSpendArgs,
    RequestArgs,
    RunPayrollArgs,
    ToolCall,
)
from ..services import audit, contributions, grants, households, payroll, requests, signups, treasurer, views
from ..services.rules import votes_needed

log = logging.getLogger(__name__)
router = APIRouter(prefix="/tools", tags=["tools"], dependencies=[Depends(tools_auth)])


def _employment(db: Session, employment_id: uuid.UUID, need_consent: bool = True) -> Employment:
    emp = db.get(Employment, employment_id)
    if emp is None:
        raise not_found("Employment")
    if need_consent and emp.consent_at is None:
        raise conflict("no_consent", "The helper hasn't agreed to Roz Roz yet")
    return emp


# ---- liaison tools ----


def get_helper_context(db: Session, a: GetHelperContextArgs, actor: str) -> dict:
    helper = db.scalar(select(Helper).where(Helper.whatsapp_e164 == households.normalize_e164(a.whatsapp_e164)))
    return {"known": False} if helper is None else views.helper_context(db, helper)


def record_consent(db: Session, a: RecordConsentArgs, actor: str) -> dict:
    helper = db.get(Helper, a.helper_id)
    if helper is None:
        raise not_found("Helper")
    now = clock.now()
    for eid in a.employment_ids:
        emp = _employment(db, eid, need_consent=False)
        if emp.helper_id != helper.id:
            raise bad_request("wrong_helper", "That employment belongs to another helper")
        if emp.consent_at is None:
            emp.consent_at = now
            audit.log(
                db,
                household_id=emp.household_id,
                actor="helper",
                action="consent",
                entity="employment",
                entity_id=emp.id,
                summary=f"{helper.name} agreed to Roz Roz",
            )
    signups.record(db, "helper", helper.name, helper.whatsapp_e164)
    return {"consent_at": now.isoformat()}


def _create_and_process(db: Session, emp: Employment, kind: str, **fields) -> dict:
    req = requests.create(db, emp, kind, "helper", **fields)
    treasurer.process(db, req)
    return {"request_id": str(req.id), "outcome": views.outcome(db, req)}


def create_leave_request(db: Session, a: CreateLeaveRequestArgs, actor: str) -> dict:
    return _create_and_process(
        db,
        _employment(db, a.employment_id),
        "leave",
        leave_from=a.leave_from,
        leave_to=a.leave_to,
        half_day=a.half_day,
        note=a.note,
        source_message_id=a.source_message_id,
    )


def create_advance_request(db: Session, a: CreateMoneyRequestArgs, actor: str) -> dict:
    return _create_and_process(
        db,
        _employment(db, a.employment_id),
        "advance",
        amount_paise=a.amount_paise,
        note=a.note,
        source_message_id=a.source_message_id,
    )


def create_grocery_request(db: Session, a: CreateMoneyRequestArgs, actor: str) -> dict:
    return _create_and_process(
        db,
        _employment(db, a.employment_id),
        "grocery_money",
        amount_paise=a.amount_paise,
        note=a.note,
        source_message_id=a.source_message_id,
    )


def record_cash_spend(db: Session, a: RecordSpendArgs, actor: str) -> dict:
    return _create_and_process(
        db,
        _employment(db, a.employment_id),
        "reimbursement",
        amount_paise=a.amount_paise,
        note=a.item_note,
        source_message_id=a.source_message_id,
    )


def record_grocery_spend(db: Session, a: RecordSpendArgs, actor: str) -> dict:
    emp = _employment(db, a.employment_id)
    wallet = spending_wallet(db, emp.id)
    entry = provider.debit(
        db, wallet, a.amount_paise, EntryMeta(kind="grocery_spend", employment_id=emp.id, note=a.item_note)
    )
    balance = provider.balance(db, wallet)
    name = requests.helper_name(db, emp)
    audit.log(
        db,
        household_id=emp.household_id,
        actor="helper",
        action="grocery_spend",
        entity="ledger_entry",
        entity_id=entry.id,
        summary=f"{name} spent ₹{rupees(a.amount_paise)} on {a.item_note} (simulated)",
    )
    return {
        "ledger_entry_id": str(entry.id),
        "spending_wallet_paise": balance,
        "summary_slots": {"amount": rupees(a.amount_paise), "item": a.item_note, "wallet": rupees(balance)},
    }


def get_balances(db: Session, a: EmploymentArgs, actor: str) -> dict:
    return views.balances(db, _employment(db, a.employment_id))


# ---- treasurer tools ----


def evaluate_request(db: Session, a: RequestArgs, actor: str) -> dict:
    d = requests.evaluate(db, requests.get(db, a.request_id))
    context = {k: v for k, v in d.context.items() if k != "grants_checked"}
    return {"decision": d.kind, "votes_needed": d.votes_needed, "rule_applied": d.rule_applied, "context": context}


def check_grant(db: Session, a: RequestArgs, actor: str) -> dict:
    req = requests.get(db, a.request_id)
    if req.kind not in grants.SCOPE_KINDS:
        return {"allowed": True, "checked": [], "reason": "no money moves"}
    check = grants.check(db, req.household_id, req.kind, req.employment_id, req.amount_paise)
    return {"allowed": check.allowed, "checked": check.checked}


def execute_request(db: Session, a: RequestArgs, actor: str) -> dict:
    """The agent can only execute what the rules approve: a pending request is re-evaluated here, in code."""
    req = requests.get(db, a.request_id)
    if req.status == "pending":
        decision = requests.evaluate(db, req)
        if decision.kind != "AUTO":
            raise conflict("not_auto_approvable", f"The house rules say {decision.kind}: {decision.rule_applied}")
        requests.apply_decision(db, req, decision, actor)
    requests.execute(db, req, actor)
    return {"status": req.status, "outcome": views.outcome(db, req)}


def open_vote(db: Session, a: OpenVoteArgs, actor: str) -> dict:
    """Votes needed always come from the rules, never from the agent."""
    req = requests.get(db, a.request_id)
    if req.status == "needs_vote":
        return {"status": req.status, "votes_needed": req.votes_needed}
    decision = requests.evaluate(db, req)
    if decision.kind == "AUTO":
        # The rules allow it alone; the agent chose to ask anyway. Respect that with the normal vote count.
        rule = households.rules(db, req.household_id)
        n = len(households.voters(db, req.household_id))
        decision.kind = "VOTE"
        decision.votes_needed = votes_needed(n, req.amount_paise or 0, rule.vote_rule, rule.two_person_limit_paise)
        decision.rule_applied = "the agent asked the house"
    requests.apply_decision(db, req, decision, actor)
    audit.log(
        db,
        household_id=req.household_id,
        actor=actor,
        action="vote_note",
        entity="request",
        entity_id=req.id,
        payload={"agent_context": a.context_text[:500]},
    )
    return {"status": req.status, "votes_needed": req.votes_needed}


def run_payroll(db: Session, a: RunPayrollArgs, actor: str) -> dict:
    return views.payroll_out(payroll.run(db, _employment(db, a.employment_id, need_consent=False), a.month, actor))


def post_contributions(db: Session, a: PostContributionsArgs, actor: str) -> dict:
    if db.get(Household, a.household_id) is None:
        raise not_found("Household")
    return {"members": contributions.post(db, a.household_id, a.month)["members"]}


HANDLERS: dict[str, Callable[[Session, BaseModel, str], dict]] = {
    "get_helper_context": get_helper_context,
    "record_consent": record_consent,
    "create_leave_request": create_leave_request,
    "create_advance_request": create_advance_request,
    "create_grocery_request": create_grocery_request,
    "record_grocery_spend": record_grocery_spend,
    "record_cash_spend": record_cash_spend,
    "get_balances": get_balances,
    "evaluate_request": evaluate_request,
    "check_grant": check_grant,
    "execute_request": execute_request,
    "open_vote": open_vote,
    "run_payroll": run_payroll,
    "post_contributions": post_contributions,
}
TREASURER_TOOLS = {
    "evaluate_request",
    "check_grant",
    "execute_request",
    "open_vote",
    "run_payroll",
    "post_contributions",
}
assert set(HANDLERS) == set(TOOL_ARGS), "every tool in contract 3 needs a handler"


def _fail(code: str, message) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


@router.post("/{name}")
def call_tool(name: str, call: ToolCall, db: Session = Depends(get_db)) -> dict:
    if name not in HANDLERS:
        return _fail("unknown_tool", name)
    try:
        args = TOOL_ARGS[name].model_validate(call.args)
    except ValidationError as e:
        return _fail("invalid_args", e.errors(include_url=False, include_input=False))
    stored = db.get(ToolCallRecord, call.idempotency_key)
    if stored is not None:
        return stored.response if stored.tool == name else _fail("idempotency_conflict", "Key used for another tool")
    actor = f"agent:{'treasurer' if name in TREASURER_TOOLS else 'liaison'}"
    try:
        result = HANDLERS[name](db, args, actor)
        response = {"ok": True, "result": _jsonable(result)}
        db.add(ToolCallRecord(idempotency_key=call.idempotency_key, tool=name, response=response))
        db.commit()
        return response
    except ApiError as e:
        db.rollback()
        return _fail(e.code, e.message)
    except Exception:
        db.rollback()
        log.exception("tool %s failed", name)
        return _fail("internal_error", "Something went wrong; try again")


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, (uuid.UUID, datetime)):
        return str(value) if isinstance(value, uuid.UUID) else value.isoformat()
    return value
