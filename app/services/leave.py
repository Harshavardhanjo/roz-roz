"""Leave maths. Paid leave is a monthly allowance; anything beyond it is unpaid if the household deducts.

Payroll and summaries use totals (unpaid = max(0, taken - allowed)), so a half day of remaining allowance is never
lost. The per-day 'paid'/'unpaid' kind on leave_entry is for display."""

import calendar
import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import conflict
from ..models import Employment, LeaveEntry


def month_bounds(month: str) -> tuple[date, date]:
    year, mon = map(int, month.split("-"))
    return date(year, mon, 1), date(year, mon, calendar.monthrange(year, mon)[1])


def _days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def working_days(month: str, weekly_off: list[int]) -> list[date]:
    """Dates in the month whose weekday (0 = Monday) is not a weekly off."""
    start, end = month_bounds(month)
    return [d for d in _days(start, end) if d.weekday() not in weekly_off]


def leave_dates(start: date, end: date, weekly_off: list[int]) -> list[date]:
    return [d for d in _days(start, end) if d.weekday() not in weekly_off]


def leave_days_in(start: date, end: date, weekly_off: list[int], half_day: bool = False) -> float:
    """Working days in the range; a single-day half day counts 0.5. Weekly offs cost nothing."""
    days = leave_dates(start, end, weekly_off)
    if half_day and len(days) == 1:
        return 0.5
    return float(len(days))


def split_paid_unpaid(requested: float, paid_left: float, deduct_extra_leave: bool) -> tuple[float, float]:
    """Paid days come out of the remaining balance first; the rest is unpaid only if the household deducts."""
    if not deduct_extra_leave:
        return requested, 0.0
    paid = min(requested, max(paid_left, 0.0))
    return paid, requested - paid


# ---- database ----


def leave_taken(db: Session, employment_id: uuid.UUID, month: str) -> float:
    start, end = month_bounds(month)
    total = db.scalar(
        select(func.coalesce(func.sum(LeaveEntry.fraction), 0)).where(
            LeaveEntry.employment_id == employment_id, LeaveEntry.date.between(start, end)
        )
    )
    return float(total)


def summary(db: Session, emp: Employment, month: str) -> dict:
    allowed = float(emp.paid_leaves_per_month)
    taken = leave_taken(db, emp.id, month)
    unpaid = max(0.0, taken - allowed) if emp.deduct_extra_leave else 0.0
    return {
        "paid_allowed": allowed,
        "paid_used": min(taken, allowed),
        "unpaid_days": unpaid,
        "taken": taken,
        "paid_left": max(0.0, allowed - taken),
    }


def paid_leave_left(db: Session, emp: Employment, month: str) -> float:
    return max(0.0, float(emp.paid_leaves_per_month) - leave_taken(db, emp.id, month))


def record_leave(
    db: Session,
    emp: Employment,
    start: date,
    end: date,
    half_day: bool,
    marked_by: str,
    request_id: uuid.UUID | None = None,
) -> list[LeaveEntry]:
    """One row per working day. Days already recorded are refused, so leave is never counted twice."""
    days = leave_dates(start, end, list(emp.weekly_off))
    if not days:
        return []
    existing = set(
        db.scalars(select(LeaveEntry.date).where(LeaveEntry.employment_id == emp.id, LeaveEntry.date.in_(days))).all()
    )
    if existing:
        taken = ", ".join(d.strftime("%d %b") for d in sorted(existing))
        raise conflict("leave_exists", f"Leave is already recorded on {taken}")
    fraction = 0.5 if half_day and len(days) == 1 else 1.0
    allowed = float(emp.paid_leaves_per_month)
    taken_by_month: dict[str, float] = {}
    entries = []
    for d in days:
        month = clock.month_of(d)
        if month not in taken_by_month:
            taken_by_month[month] = leave_taken(db, emp.id, month)
        paid = not emp.deduct_extra_leave or taken_by_month[month] + fraction <= allowed
        taken_by_month[month] += fraction
        entry = LeaveEntry(
            employment_id=emp.id,
            date=d,
            kind="paid" if paid else "unpaid",
            fraction=fraction,
            request_id=request_id,
            marked_by=marked_by,
        )
        db.add(entry)
        entries.append(entry)
    db.flush()
    return entries
