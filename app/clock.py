"""All dates and months are IST. TODAY_OVERRIDE pins the date for rehearsals and tests."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from .config import settings

IST = ZoneInfo("Asia/Kolkata")


def now() -> datetime:
    current = datetime.now(IST)
    if settings.today_override:
        pinned = date.fromisoformat(settings.today_override)
        return current.replace(year=pinned.year, month=pinned.month, day=pinned.day)
    return current


def today() -> date:
    return now().date()


def month_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def current_month() -> str:
    return month_of(today())


def previous_month(month: str) -> str:
    year, mon = map(int, month.split("-"))
    return f"{year - 1:04d}-12" if mon == 1 else f"{year:04d}-{mon - 1:02d}"


def next_month(month: str) -> str:
    year, mon = map(int, month.split("-"))
    return f"{year + 1:04d}-01" if mon == 12 else f"{year:04d}-{mon + 1:02d}"
