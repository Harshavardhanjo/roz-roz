"""Scheduled jobs called over HTTP (Vercel Cron). Same work as the in-process scheduler."""

import hmac

from fastapi import APIRouter, Depends, Header

from ..config import settings
from ..errors import ApiError
from ..services import scheduler

router = APIRouter(prefix="/api/cron", tags=["cron"])


def cron_auth(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {settings.cron_secret}"
    if not settings.cron_secret or not hmac.compare_digest(authorization or "", expected):
        raise ApiError(401, "bad_token", "Invalid cron secret")


@router.get("/payday", dependencies=[Depends(cron_auth)])
def payday():
    """Pays every helper whose payday is today (IST). Safe to call more than once a day."""
    return {"paid": scheduler.run_due_payrolls()}
