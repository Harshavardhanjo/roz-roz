"""Payday job: every day at 09:00 IST, pay each helper whose payday is today (once per month)."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from .. import clock
from ..db import session_scope
from ..errors import ApiError
from ..models import Employment
from . import payroll

log = logging.getLogger(__name__)


def run_due_payrolls() -> list[str]:
    """Returns the employment ids that were paid. Each helper runs in its own transaction."""
    today, month = clock.today(), clock.current_month()
    with session_scope() as db:
        due = [
            e.id
            for e in db.scalars(select(Employment).where(Employment.status == "active"))
            if payroll.payday_in(month, e.payday_dom) == today
        ]
    paid = []
    for employment_id in due:
        try:
            with session_scope() as db:
                run = payroll.run(db, db.get(Employment, employment_id), month, actor="system:scheduler")
                if run.status == "executed":
                    paid.append(str(employment_id))
        except ApiError as exc:
            log.warning("payroll for %s not run: %s", employment_id, exc.message)
    return paid


def start() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=clock.IST)
    scheduler.add_job(run_due_payrolls, "cron", hour=9, minute=0, id="payday", replace_existing=True)
    scheduler.start()
    return scheduler
