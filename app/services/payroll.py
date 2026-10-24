"""Payroll: salary - unpaid leave - advances paid this month, paid in full once per month."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import conflict
from ..models import Employment, PayrollRun
from ..money import inr
from ..providers.payment import EntryMeta, InsufficientFunds, house_wallet, provider
from . import audit, contributions, grants, leave
from .leave import month_bounds
from .requests import advances_paid


class NegativeNetPay(ValueError):
    """Advances plus deductions exceed the salary."""


@dataclass(frozen=True)
class PayrollResult:
    salary_paise: int
    working_days: int
    leave_days: float
    unpaid_days: float
    deduction_paise: int
    advances_paise: int
    net_paise: int


def round_to_rupee(paise: Decimal) -> int:
    return int((paise / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * 100


def compute_payroll(
    salary_paise: int,
    working_days: int,
    leave_days: float,
    paid_leaves_per_month: float,
    deduct_extra_leave: bool,
    advances_paise: int,
) -> PayrollResult:
    unpaid = max(0.0, leave_days - paid_leaves_per_month) if deduct_extra_leave else 0.0
    deduction = round_to_rupee(Decimal(str(unpaid)) * salary_paise / working_days) if unpaid else 0
    net = salary_paise - deduction - advances_paise
    if net < 0:
        raise NegativeNetPay(f"net {net} < 0")
    return PayrollResult(salary_paise, working_days, leave_days, unpaid, deduction, advances_paise, net)


def payday_in(month: str, payday_dom: int) -> date:
    """Payday for the month; a day past the month's end falls on its last day."""
    start, end = month_bounds(month)
    return start.replace(day=min(payday_dom, end.day))


# ---- database ----


def compute_for(db: Session, emp: Employment, month: str) -> PayrollResult:
    return compute_payroll(
        emp.salary_paise,
        len(leave.working_days(month, list(emp.weekly_off))),
        leave.leave_taken(db, emp.id, month),
        float(emp.paid_leaves_per_month),
        emp.deduct_extra_leave,
        advances_paid(db, emp.id, month),
    )


def get_run(db: Session, employment_id: uuid.UUID, month: str) -> PayrollRun | None:
    return db.scalar(select(PayrollRun).where(PayrollRun.employment_id == employment_id, PayrollRun.month == month))


def projected_net(db: Session, emp: Employment, month: str) -> int:
    run = get_run(db, emp.id, month)
    if run is not None and run.status == "executed":
        return run.net_paise
    try:
        return compute_for(db, emp, month).net_paise
    except NegativeNetPay:
        return 0


def next_payday(db: Session, emp: Employment) -> date:
    month = clock.current_month()
    run = get_run(db, emp.id, month)
    if run is not None and run.status == "executed":
        return payday_in(clock.next_month(month), emp.payday_dom)
    return payday_in(month, emp.payday_dom)


def run(db: Session, emp: Employment, month: str, actor: str) -> PayrollRun:
    """Idempotent per (helper, month): an executed run is returned as-is. A run that couldn't be paid
    (needs_topup) is recomputed and retried."""
    existing = get_run(db, emp.id, month)
    if existing is not None and existing.status == "executed":
        return existing
    try:
        result = compute_for(db, emp, month)
    except NegativeNetPay:
        raise conflict("advances_exceed_pay", "Advances and unpaid leave are more than this month's salary") from None
    check = grants.check(db, emp.household_id, "salary", emp.id, result.net_paise)
    if not check.allowed:
        raise conflict(
            "grant_missing", "Every member must grant the agent its limits before payroll runs: " + check.label
        )
    payroll = existing or PayrollRun(employment_id=emp.id, month=month)
    for field in (
        "salary_paise",
        "working_days",
        "leave_days",
        "unpaid_days",
        "deduction_paise",
        "advances_paise",
        "net_paise",
    ):
        setattr(payroll, field, getattr(result, field))
    db.add(payroll)
    db.flush()
    if result.net_paise > 0:
        try:
            provider.debit(
                db,
                house_wallet(db, emp.household_id),
                result.net_paise,
                EntryMeta(kind="salary", employment_id=emp.id, payroll_run_id=payroll.id, note=f"Salary {month}"),
            )
        except InsufficientFunds:
            payroll.status = "needs_topup"
            audit.log(
                db,
                household_id=emp.household_id,
                actor=actor,
                action="payroll_needs_topup",
                entity="payroll_run",
                entity_id=payroll.id,
                grantex_decision=check.label,
                summary=f"Payroll for {month} needs a top-up: {inr(result.net_paise)} due",
            )
            return payroll
    payroll.status, payroll.executed_at = "executed", clock.now()
    audit.log(
        db,
        household_id=emp.household_id,
        actor=actor,
        action="run_payroll",
        entity="payroll_run",
        entity_id=payroll.id,
        grantex_decision=check.label,
        rule_applied="salary - unpaid leave - advances this month",
        payload={
            "salary_paise": result.salary_paise,
            "deduction_paise": result.deduction_paise,
            "advances_paise": result.advances_paise,
            "net_paise": result.net_paise,
        },
        summary=f"Paid {inr(result.net_paise)} salary for {month}: {inr(result.salary_paise)} - "
        f"{inr(result.deduction_paise)} unpaid leave - {inr(result.advances_paise)} advances "
        f"(simulated payment)",
    )
    contributions.post(db, emp.household_id, month)
    return payroll
