"""Helper requests: create -> evaluate (house rules + grants) -> auto-approve, vote, or wait for a top-up -> execute.

Status flow:
    pending -> auto_approved -> executed
    pending -> needs_vote -> approved -> executed | rejected
    pending -> needs_topup               (house wallet too low; the helper asks again after a top-up)
    approved -> needs_topup              (balance fell while the vote was open)
`execute` refuses anything not approved, so no caller (agent or code) can move money around the rules."""

import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import bad_request, conflict, not_found
from ..models import Employment, Helper, Household, LedgerEntry, Member, Request, Vote
from ..money import inr
from ..providers.payment import EntryMeta, InsufficientFunds, house_wallet, provider, spending_wallet
from . import audit, grants, households, leave
from .rules import Decision, evaluate_leave, evaluate_money_request, votes_needed

MONEY_KINDS = ("advance", "grocery_money", "reimbursement")
KINDS = ("leave", *MONEY_KINDS, "other")
MAX_LEAVE_SPAN_DAYS = 31
MAX_DAYS_AHEAD = 60


# ---- month totals (from the ledger, the source of truth) ----


def _debits(db: Session, employment_id: uuid.UUID, month: str, kinds: tuple[str, ...]) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount_paise), 0)).where(
                LedgerEntry.employment_id == employment_id,
                LedgerEntry.month == month,
                LedgerEntry.direction == "debit",
                LedgerEntry.kind.in_(kinds),
            )
        )
    )


def advances_paid(db: Session, employment_id: uuid.UUID, month: str) -> int:
    return _debits(db, employment_id, month, ("advance",))


def grocery_budget_used(db: Session, employment_id: uuid.UUID, month: str) -> int:
    """Counts toward the grocery budget: money moved to the spending wallet plus cash repaid."""
    return _debits(db, employment_id, month, ("grocery_transfer", "reimbursement"))  # both debit the house wallet


def grocery_spent(db: Session, employment_id: uuid.UUID, month: str) -> int:
    """Actually spent on groceries: spending-wallet spends plus cash repaid."""
    return _debits(db, employment_id, month, ("grocery_spend", "reimbursement"))


# ---- create ----


def create(
    db: Session,
    emp: Employment,
    kind: str,
    created_by: str,
    *,
    amount_paise: int | None = None,
    leave_from: date | None = None,
    leave_to: date | None = None,
    half_day: bool = False,
    note: str | None = None,
    source_message_id: uuid.UUID | None = None,
) -> Request:
    if kind not in KINDS:
        raise bad_request("invalid_kind", f"Unknown request kind '{kind}'")
    if emp.status != "active":
        raise conflict("employment_ended", "This helper no longer works for the household")
    if created_by == "helper" and emp.consent_at is None:
        raise conflict("no_consent", "The helper hasn't agreed to Roz Roz yet")
    if kind in MONEY_KINDS and (amount_paise is None or amount_paise <= 0):
        raise bad_request("invalid_amount", "A positive amount is required")
    if kind == "leave":
        _validate_leave(leave_from, leave_to, half_day)
    req = Request(
        household_id=emp.household_id,
        employment_id=emp.id,
        kind=kind,
        amount_paise=amount_paise if kind != "leave" else None,
        leave_from=leave_from,
        leave_to=leave_to,
        half_day=bool(half_day and kind == "leave"),
        note=note,
        source_message_id=source_message_id,
        created_by=created_by,
        status="pending",
        created_at=clock.now(),
    )
    db.add(req)
    db.flush()
    audit.log(
        db,
        household_id=emp.household_id,
        actor=_actor(created_by),
        action="create_request",
        entity="request",
        entity_id=req.id,
        summary=f"{helper_name(db, emp)} asked: {describe(db, req)}",
    )
    return req


def _validate_leave(leave_from: date | None, leave_to: date | None, half_day: bool) -> None:
    if leave_from is None or leave_to is None:
        raise bad_request("invalid_dates", "Leave needs a start and end date")
    if leave_to < leave_from:
        raise bad_request("invalid_dates", "Leave ends before it starts")
    if (leave_to - leave_from).days >= MAX_LEAVE_SPAN_DAYS:
        raise bad_request("invalid_dates", "Leave can't span more than a month")
    today = clock.today()
    if not today - timedelta(days=MAX_DAYS_AHEAD) <= leave_from <= today + timedelta(days=MAX_DAYS_AHEAD):
        raise bad_request("invalid_dates", "Leave must be within 60 days of today")
    if half_day and leave_from != leave_to:
        raise bad_request("invalid_dates", "A half day is a single date")


def _actor(created_by: str) -> str:
    return created_by if created_by.startswith("member:") else "helper"


# ---- evaluate ----


def evaluate(db: Session, req: Request) -> Decision:
    """Read-only: what the house rules say about this request right now."""
    emp = db.get(Employment, req.employment_id)
    rule = households.rules(db, req.household_id)
    n = len(households.voters(db, req.household_id))
    if req.kind == "leave":
        days = leave.leave_days_in(req.leave_from, req.leave_to, list(emp.weekly_off), req.half_day)
        left = leave.paid_leave_left(db, emp, clock.month_of(req.leave_from))
        d = evaluate_leave(days, left, emp.deduct_extra_leave, n, rule.vote_rule, rule.two_person_limit_paise)
        d.context.update({"unpaid_if_approved": emp.deduct_extra_leave and days > left})
        return d
    if req.kind == "other":
        return Decision(
            "VOTE",
            votes_needed(n, 0, rule.vote_rule, rule.two_person_limit_paise),
            "not covered by the house rules",
            {},
        )
    month = clock.current_month()
    if req.kind == "advance":
        used, auto, limit = (
            advances_paid(db, emp.id, month),
            emp.advance_auto_limit_paise,
            emp.advance_monthly_limit_paise,
        )
    else:
        used, auto, limit = (
            grocery_budget_used(db, emp.id, month),
            emp.grocery_auto_limit_paise,
            emp.grocery_monthly_budget_paise,
        )
    check = grants.check(db, req.household_id, req.kind, emp.id, req.amount_paise)
    balance = provider.balance(db, house_wallet(db, req.household_id))
    d = evaluate_money_request(
        req.amount_paise, used, auto, limit, balance, check.allowed, n, rule.vote_rule, rule.two_person_limit_paise
    )
    d.context.update({"grants": check.label, "grants_checked": check.checked, "auto_limit_paise": auto})
    return d


def apply_decision(db: Session, req: Request, d: Decision, actor: str) -> Request:
    if req.status != "pending":
        raise conflict("already_decided", f"Request is already {req.status}")
    req.rule_applied = d.rule_applied
    if d.kind == "AUTO":
        req.status, req.decided_at = "auto_approved", clock.now()
        audit.log(
            db,
            household_id=req.household_id,
            actor=actor,
            action="approve_request",
            entity="request",
            entity_id=req.id,
            rule_applied=d.rule_applied,
            grantex_decision=d.context.get("grants"),
            summary=f"Auto-approved {describe(db, req)}",
        )
    elif d.kind == "VOTE":
        req.status, req.votes_needed = "needs_vote", d.votes_needed
        audit.log(
            db,
            household_id=req.household_id,
            actor=actor,
            action="open_vote",
            entity="request",
            entity_id=req.id,
            rule_applied=d.rule_applied,
            grantex_decision=d.context.get("grants"),
            summary=f"Asked the house to vote on {describe(db, req)} ({d.votes_needed} needed)",
        )
    else:
        req.status = "needs_topup"
        audit.log(
            db,
            household_id=req.household_id,
            actor=actor,
            action="needs_topup",
            entity="request",
            entity_id=req.id,
            rule_applied=d.rule_applied,
            summary=f"House wallet too low for {describe(db, req)}",
        )
    return req


# ---- execute ----


def execute(db: Session, req: Request, actor: str) -> Request:
    """Move the (simulated) money or record the leave. Only for approved requests."""
    if req.status not in ("auto_approved", "approved"):
        raise conflict("not_approved", f"Request is {req.status}, not approved")
    emp = db.get(Employment, req.employment_id)
    meta = EntryMeta(kind=req.kind, employment_id=emp.id, request_id=req.id, note=req.note)
    try:
        if req.kind == "leave":
            leave.record_leave(
                db, emp, req.leave_from, req.leave_to, req.half_day, marked_by="helper", request_id=req.id
            )
        elif req.kind in ("advance", "reimbursement"):
            provider.debit(db, house_wallet(db, req.household_id), req.amount_paise, meta)
        elif req.kind == "grocery_money":
            provider.transfer(
                db,
                house_wallet(db, req.household_id),
                spending_wallet(db, emp.id),
                req.amount_paise,
                EntryMeta(kind="grocery_transfer", employment_id=emp.id, request_id=req.id, note=req.note),
            )
    except InsufficientFunds:
        req.status = "needs_topup"
        audit.log(
            db,
            household_id=req.household_id,
            actor=actor,
            action="needs_topup",
            entity="request",
            entity_id=req.id,
            summary=f"House wallet too low to pay {describe(db, req)}",
        )
        return req
    req.status = "executed"
    req.decided_at = req.decided_at or clock.now()
    audit.log(
        db,
        household_id=req.household_id,
        actor=actor,
        action="execute_request",
        entity="request",
        entity_id=req.id,
        rule_applied=req.rule_applied,
        summary=f"Done: {describe(db, req)}" + (" (simulated payment)" if req.kind in MONEY_KINDS else ""),
    )
    return req


def auto_process(db: Session, req: Request, actor: str) -> Request:
    """The treasurer's steps in code: evaluate, then approve-and-execute, open a vote, or wait for a top-up."""
    if req.status != "pending":
        return req
    apply_decision(db, req, evaluate(db, req), actor)
    if req.status == "auto_approved":
        execute(db, req, actor)
    return req


# ---- votes ----


def vote(db: Session, req: Request, member: Member, decision: str) -> Request:
    if req.household_id != member.household_id:
        raise not_found("Request")
    if req.status != "needs_vote":
        raise conflict("already_decided", f"Request is already {req.status}")
    if db.scalar(select(Vote.id).where(Vote.request_id == req.id, Vote.member_id == member.id)):
        raise conflict("already_voted", "You have already voted on this")
    db.add(Vote(request_id=req.id, member_id=member.id, decision=decision, at=clock.now()))
    db.flush()
    audit.log(
        db,
        household_id=req.household_id,
        actor=f"member:{member.id}",
        action=f"vote_{decision}",
        entity="request",
        entity_id=req.id,
        summary=f"{member.name} voted to {decision} {describe(db, req)}",
    )
    return resolve_votes(db, req, actor=f"member:{member.id}")


def resolve_votes(db: Session, req: Request, actor: str) -> Request:
    """Approve (and execute) or reject an open vote once the outcome is certain. Votes needed never exceed the
    number of current voters, so removing a roommate can't leave a vote that can never pass."""
    if req.status != "needs_vote":
        return req
    n = len(households.voters(db, req.household_id))
    req.votes_needed = min(req.votes_needed, n)
    approvals, rejections = _tally(db, req.id)
    if approvals >= req.votes_needed:
        req.status, req.decided_at = "approved", clock.now()
        execute(db, req, actor=actor)
    elif rejections > n - req.votes_needed:
        req.status, req.decided_at = "rejected", clock.now()
        audit.log(
            db,
            household_id=req.household_id,
            actor=actor,
            action="reject_request",
            entity="request",
            entity_id=req.id,
            summary=f"Rejected {describe(db, req)}",
        )
    return req


def _tally(db: Session, request_id: uuid.UUID) -> tuple[int, int]:
    rows = dict(
        db.execute(
            select(Vote.decision, func.count()).where(Vote.request_id == request_id).group_by(Vote.decision)
        ).all()
    )
    return rows.get("approve", 0), rows.get("reject", 0)


def votes_of(db: Session, request_id: uuid.UUID) -> list[dict]:
    rows = db.execute(
        select(Vote, Member.name)
        .join(Member, Member.id == Vote.member_id)
        .where(Vote.request_id == request_id)
        .order_by(Vote.at)
    ).all()
    return [{"member_id": str(v.member_id), "name": name, "decision": v.decision} for v, name in rows]


# ---- words ----


def helper_name(db: Session, emp: Employment) -> str:
    return db.scalar(select(Helper.name).where(Helper.id == emp.helper_id))


def _day(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def format_dates(start: date, end: date) -> str:
    """'26 Oct', '26–28 Oct', '30 Oct–2 Nov'."""
    if start == end:
        return _day(start)
    if start.month == end.month:
        return f"{start.day}–{_day(end)}"
    return f"{_day(start)}–{_day(end)}"


def describe(db: Session, req: Request) -> str:
    name = helper_name(db, db.get(Employment, req.employment_id))
    if req.kind == "leave":
        return f"{name}'s leave on {format_dates(req.leave_from, req.leave_to)}" + (
            " (half day)" if req.half_day else ""
        )
    label = {
        "advance": "advance",
        "grocery_money": "for groceries",
        "reimbursement": "cash repayment",
        "other": "request",
    }[req.kind]
    return f"{inr(req.amount_paise or 0)} {label} for {name}" if req.kind != "other" else f"{name}'s request"


def vote_context(db: Session, req: Request) -> str:
    """The one line roommates see on a vote card. Numbers come from the database, never from a model."""
    emp = db.get(Employment, req.employment_id)
    month = clock.current_month()
    if req.kind == "leave":
        days = leave.leave_days_in(req.leave_from, req.leave_to, list(emp.weekly_off), req.half_day)
        left = leave.paid_leave_left(db, emp, clock.month_of(req.leave_from))
        tail = "it would be unpaid" if emp.deduct_extra_leave and days > left else "it stays paid"
        return (
            f"Leave on {format_dates(req.leave_from, req.leave_to)} ({days:g} day{'s' if days != 1 else ''}); "
            f"{left:g} paid leave left, so {tail}"
        )
    if req.kind == "advance":
        return (
            f"{inr(req.amount_paise)} advance; {inr(advances_paid(db, emp.id, month))} of "
            f"{inr(emp.advance_monthly_limit_paise)} used this month"
        )
    if req.kind in ("grocery_money", "reimbursement"):
        what = "for groceries" if req.kind == "grocery_money" else f"cash spent{': ' + req.note if req.note else ''}"
        return (
            f"{inr(req.amount_paise)} {what}; {inr(grocery_budget_used(db, emp.id, month))} of "
            f"{inr(emp.grocery_monthly_budget_paise)} used this month"
        )
    return req.note or "A request outside the house rules"


def household_name(db: Session, household_id: uuid.UUID) -> str:
    return db.scalar(select(Household.name).where(Household.id == household_id))


def get(db: Session, request_id: uuid.UUID) -> Request:
    req = db.get(Request, request_id)
    if req is None:
        raise not_found("Request")
    return req
