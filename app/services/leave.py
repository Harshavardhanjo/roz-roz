"""Leave maths. Pure functions; the DB-backed record_leave is TODO(Harsha)."""
import calendar
from datetime import date, timedelta


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


def leave_days_in(start: date, end: date, weekly_off: list[int], half_day: bool = False) -> float:
    """Working days in the range; a single-day half day counts 0.5. Weekly offs cost nothing."""
    days = [d for d in _days(start, end) if d.weekday() not in weekly_off]
    if half_day and len(days) == 1:
        return 0.5
    return float(len(days))


def split_paid_unpaid(requested: float, paid_left: float, deduct_extra_leave: bool) -> tuple[float, float]:
    """Paid days come out of the remaining balance first; the rest is unpaid only if the household deducts."""
    if not deduct_extra_leave:
        return requested, 0.0
    paid = min(requested, max(paid_left, 0.0))
    return paid, requested - paid
