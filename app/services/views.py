"""Response shapes for contract 2 (web) and the read-side of contract 3 (agent tools).
tests/test_contract_shapes.py checks these against the example payloads in app/stubs.py."""

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..models import (
    AuditLog,
    Employment,
    Helper,
    Household,
    LeaveEntry,
    LedgerEntry,
    Member,
    PayrollRun,
    Request,
    Wallet,
)
from ..money import count, rupees
from ..providers.payment import house_wallet, provider, spending_wallet
from . import contributions, grants, households, leave, payroll, requests

OPEN_STATUSES = ("pending", "needs_vote", "needs_topup")


def _iso(dt) -> str | None:
    return dt.astimezone(clock.IST).isoformat() if dt else None


# ---- single objects ----


def request_out(db: Session, req: Request) -> dict:
    emp = db.get(Employment, req.employment_id)
    return {
        "id": str(req.id),
        "employment_id": str(req.employment_id),
        "helper_name": requests.helper_name(db, emp),
        "kind": req.kind,
        "status": req.status,
        "amount_paise": req.amount_paise,
        "leave_from": req.leave_from.isoformat() if req.leave_from else None,
        "leave_to": req.leave_to.isoformat() if req.leave_to else None,
        "half_day": bool(req.half_day),
        "note": req.note,
        "rule_applied": req.rule_applied,
        "created_by": req.created_by,
        "votes": requests.votes_of(db, req.id),
        "votes_needed": req.votes_needed,
        "created_at": _iso(req.created_at),
        "decided_at": _iso(req.decided_at),
    }


def ledger_out(db: Session, entry: LedgerEntry, names: dict) -> dict:
    wallet = db.get(Wallet, entry.wallet_id)
    who = names.get(entry.member_id) or names.get(entry.employment_id)
    return {
        "id": str(entry.id),
        "at": _iso(entry.created_at),
        "wallet": "house" if wallet.kind == "house" else "spending",
        "direction": entry.direction,
        "kind": entry.kind,
        "amount_paise": int(entry.amount_paise),
        "who": who,
        "request_id": str(entry.request_id) if entry.request_id else None,
        "provider_txn_id": entry.provider_txn_id,
        "simulated": True,
        "note": entry.note,
    }


def payroll_out(run: PayrollRun) -> dict:
    return {
        "payroll_run_id": str(run.id),
        "employment_id": str(run.employment_id),
        "month": run.month,
        "salary_paise": run.salary_paise,
        "working_days": run.working_days,
        "leave_days": float(run.leave_days),
        "unpaid_days": float(run.unpaid_days),
        "deduction_paise": run.deduction_paise,
        "advances_paise": run.advances_paise,
        "net_paise": run.net_paise,
        "status": run.status,
        "simulated": True,
        "executed_at": _iso(run.executed_at),
    }


def audit_out(entry: AuditLog) -> dict:
    return {
        "at": _iso(entry.at),
        "actor": entry.actor,
        "action": entry.action,
        "entity": entry.entity,
        "entity_id": str(entry.entity_id) if entry.entity_id else None,
        "rule_applied": entry.rule_applied,
        "grantex_decision": entry.grantex_decision,
        "summary": (entry.payload or {}).get("summary"),
    }


def terms_out(emp: Employment, helper: Helper) -> dict:
    return {
        "role": emp.role,
        "lang": helper.lang,
        "whatsapp_e164": helper.whatsapp_e164,
        "salary_paise": emp.salary_paise,
        "payday_dom": emp.payday_dom,
        "weekly_off": list(emp.weekly_off),
        "paid_leaves_per_month": float(emp.paid_leaves_per_month),
        "deduct_extra_leave": emp.deduct_extra_leave,
        "advance_auto_limit_paise": emp.advance_auto_limit_paise,
        "advance_monthly_limit_paise": emp.advance_monthly_limit_paise,
        "grocery_auto_limit_paise": emp.grocery_auto_limit_paise,
        "grocery_monthly_budget_paise": emp.grocery_monthly_budget_paise,
        "status": emp.status,
    }


def helper_card(db: Session, emp: Employment, month: str) -> dict:
    helper = db.get(Helper, emp.helper_id)
    lv = leave.summary(db, emp, month)
    return {
        "employment_id": str(emp.id),
        "helper_id": str(helper.id),
        "name": helper.name,
        "role": emp.role,
        "lang": helper.lang,
        "consented": emp.consent_at is not None,
        "salary_paise": emp.salary_paise,
        "next_payday": payroll.next_payday(db, emp).isoformat(),
        "projected_net_paise": payroll.projected_net(db, emp, month),
        "leave": {"paid_allowed": lv["paid_allowed"], "paid_used": lv["paid_used"], "unpaid_days": lv["unpaid_days"]},
        "advances": {
            "this_month_paise": requests.advances_paid(db, emp.id, month),
            "monthly_limit_paise": emp.advance_monthly_limit_paise,
        },
        "grocery": {
            "budget_paise": emp.grocery_monthly_budget_paise,
            "spent_paise": requests.grocery_spent(db, emp.id, month),
            "budget_used_paise": requests.grocery_budget_used(db, emp.id, month),
            "spending_wallet_paise": provider.balance(db, spending_wallet(db, emp.id)),
        },
    }


def vote_card(db: Session, req: Request, timeout_h: int) -> dict:
    emp = db.get(Employment, req.employment_id)
    return {
        "request_id": str(req.id),
        "helper_name": requests.helper_name(db, emp),
        "kind": req.kind,
        "amount_paise": req.amount_paise,
        "context": requests.vote_context(db, req),
        "votes_needed": req.votes_needed,
        "votes": requests.votes_of(db, req.id),
        "created_at": _iso(req.created_at),
        "overdue": req.created_at is not None and clock.now() - req.created_at > timedelta(hours=timeout_h),
    }


# ---- pages ----


def active_employments(db: Session, household_id: uuid.UUID) -> list[Employment]:
    return list(
        db.scalars(
            select(Employment)
            .where(Employment.household_id == household_id, Employment.status == "active")
            .order_by(Employment.id)
        )
    )


def dashboard(db: Session, member: Member) -> dict:
    hh = db.get(Household, member.household_id)
    month = clock.current_month()
    rule = households.rules(db, hh.id)
    house_balance = provider.balance(db, house_wallet(db, hh.id))
    helpers = [helper_card(db, emp, month) for emp in active_employments(db, hh.id)]
    votes = db.scalars(
        select(Request)
        .where(Request.household_id == hh.id, Request.status == "needs_vote")
        .order_by(Request.created_at)
    ).all()
    waiting = db.scalar(
        select(Request.id).where(Request.household_id == hh.id, Request.status == "needs_topup").limit(1)
    )
    contrib = contributions.compute(db, hh.id, month)
    due = sum(h["projected_net_paise"] for h in helpers if h["next_payday"].startswith(month))
    alerts = []
    if house_balance < due:
        alerts.append(
            {
                "code": "low_balance",
                "message": f"House wallet is ₹{rupees(house_balance)}; ₹{rupees(due)} of salary is due this month",
            }
        )
    if waiting:
        alerts.append({"code": "needs_topup", "message": "A helper's request is waiting for a top-up"})
    status = grants.grant_status(db, member)
    if status != "active":
        alerts.append(
            {
                "code": f"grant_{status}",
                "message": "Grant the agent your limits so small requests can be approved automatically",
            }
        )
    return {
        "household": {"id": str(hh.id), "name": hh.name},
        "me": {"member_id": str(member.id), "role": member.role, "name": member.name, "grant_status": status},
        "house_wallet": {"balance_paise": house_balance, "simulated": True},
        "helpers": helpers,
        "open_votes": [vote_card(db, r, rule.vote_timeout_h) for r in votes],
        "contributions": [
            {k: row[k] for k in ("member_id", "name", "topups_paise", "share_paise", "balance_paise")}
            for row in contrib["members"]
        ],
        "alerts": alerts,
    }


def employment_detail(db: Session, emp: Employment) -> dict:
    month = clock.current_month()
    start, end = leave.month_bounds(month)
    days = db.scalars(
        select(LeaveEntry)
        .where(LeaveEntry.employment_id == emp.id, LeaveEntry.date.between(start, end))
        .order_by(LeaveEntry.date)
    ).all()
    reqs = db.scalars(
        select(Request).where(Request.employment_id == emp.id).order_by(Request.created_at.desc()).limit(50)
    ).all()
    runs = db.scalars(
        select(PayrollRun).where(PayrollRun.employment_id == emp.id).order_by(PayrollRun.month.desc())
    ).all()
    return {
        "employment": helper_card(db, emp, month),
        "terms": terms_out(emp, db.get(Helper, emp.helper_id)),
        "leave_days": [
            {"date": d.date.isoformat(), "kind": d.kind, "fraction": float(d.fraction), "marked_by": d.marked_by}
            for d in days
        ],
        "requests": [request_out(db, r) for r in reqs],
        "payroll": [payroll_out(r) for r in runs],
    }


def ledger_page(db: Session, household_id: uuid.UUID, month: str) -> dict:
    names = {m.id: m.name for m in db.scalars(select(Member).where(Member.household_id == household_id))}
    for emp in db.scalars(select(Employment).where(Employment.household_id == household_id)):
        names[emp.id] = requests.helper_name(db, emp)
    entries = db.scalars(
        select(LedgerEntry)
        .where(LedgerEntry.household_id == household_id, LedgerEntry.month == month)
        .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id)
    ).all()
    return {"month": month, "entries": [ledger_out(db, e, names) for e in entries]}


# ---- agent side (contract 3) ----


def helper_context(db: Session, helper: Helper) -> dict:
    month = clock.current_month()
    emps = db.scalars(
        select(Employment)
        .where(Employment.helper_id == helper.id, Employment.status == "active")
        .order_by(Employment.id)
    ).all()
    out = []
    for emp in emps:
        open_reqs = db.scalars(
            select(Request).where(Request.employment_id == emp.id, Request.status.in_(OPEN_STATUSES))
        ).all()
        out.append(
            {
                "household_id": str(emp.household_id),
                "name": requests.household_name(db, emp.household_id),
                "employment_id": str(emp.id),
                "consented": emp.consent_at is not None,
                "paid_leave_left": leave.paid_leave_left(db, emp, month),
                "advances_this_month_paise": requests.advances_paid(db, emp.id, month),
                "advance_auto_limit_paise": emp.advance_auto_limit_paise,
                "advance_monthly_limit_paise": emp.advance_monthly_limit_paise,
                "grocery_left_paise": max(
                    0, emp.grocery_monthly_budget_paise - requests.grocery_budget_used(db, emp.id, month)
                ),
                "spending_wallet_paise": provider.balance(db, spending_wallet(db, emp.id)),
                "open_requests": [
                    {"request_id": str(r.id), "kind": r.kind, "status": r.status, "amount_paise": r.amount_paise}
                    for r in open_reqs
                ],
            }
        )
    return {
        "known": True,
        "helper_id": str(helper.id),
        "name": helper.name,
        "lang": helper.lang,
        "consented": bool(out) and all(h["consented"] for h in out),
        "households": out,
    }


def balances(db: Session, emp: Employment) -> dict:
    month = clock.current_month()
    left = leave.paid_leave_left(db, emp, month)
    used = requests.advances_paid(db, emp.id, month)
    payday = payroll.next_payday(db, emp)
    projected = payroll.projected_net(db, emp, month)
    return {
        "paid_leave_left": left,
        "advances_this_month_paise": used,
        "grocery_left_paise": max(
            0, emp.grocery_monthly_budget_paise - requests.grocery_budget_used(db, emp.id, month)
        ),
        "spending_wallet_paise": provider.balance(db, spending_wallet(db, emp.id)),
        "next_payday": payday.isoformat(),
        "projected_net_paise": projected,
        "summary_slots": {
            "left": count(left),
            "month_total": rupees(used),
            "payday": f"{payday.day} {payday.strftime('%b')}",
            "projected": rupees(projected),
        },
    }


OUTCOME_STATUS = {
    "auto_approved": "executed",
    "approved": "executed",
    "executed": "executed",
    "needs_vote": "needs_vote",
    "needs_topup": "needs_topup",
    "rejected": "rejected",
    "pending": "pending",
}


def outcome(db: Session, req: Request) -> dict:
    """{status, template, summary_slots}: the slot names match the reply templates in app/agents/templates.py."""
    emp = db.get(Employment, req.employment_id)
    status = OUTCOME_STATUS[req.status]
    month = clock.current_month()
    slots: dict = {"household": requests.household_name(db, req.household_id)}
    if req.kind == "leave":
        slots |= {
            "dates": requests.format_dates(req.leave_from, req.leave_to),
            "left": count(leave.paid_leave_left(db, emp, clock.month_of(req.leave_from))),
        }
    elif req.kind == "advance":
        slots |= {"amount": rupees(req.amount_paise), "month_total": rupees(requests.advances_paid(db, emp.id, month))}
    elif req.kind == "grocery_money":
        slots |= {
            "amount": rupees(req.amount_paise),
            "wallet": rupees(provider.balance(db, spending_wallet(db, emp.id))),
        }
    elif req.kind == "reimbursement":
        slots |= {"amount": rupees(req.amount_paise), "item": req.note or ""}
    return {"status": status, "template": _template(req.kind, status), "summary_slots": slots}


def _template(kind: str, status: str) -> str:
    if status == "needs_topup":
        return "needs_topup"
    if status == "rejected":
        return "rejected"
    base = {
        "leave": "leave",
        "advance": "advance",
        "grocery_money": "grocery",
        "reimbursement": "cash",
        "other": "other",
    }[kind]
    if status == "needs_vote":
        return f"{base}_needs_vote" if kind in ("leave", "advance", "grocery_money") else "sent_for_approval"
    return {
        "leave": "leave_approved",
        "advance": "advance_approved",
        "grocery_money": "grocery_approved",
        "reimbursement": "cash_recorded",
        "other": "sent_for_approval",
    }[kind]
