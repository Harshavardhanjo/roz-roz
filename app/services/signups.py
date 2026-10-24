"""Signups are the event's proof of real users: one row per (phone, source)."""

import re
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .. import clock
from ..models import Message, Signup


def normalize_phone(phone: str) -> str:
    """Digits only, Indian 10-digit numbers prefixed with 91."""
    digits = re.sub(r"\D", "", phone or "")
    return "91" + digits if len(digits) == 10 else digits


def record(db: Session, source: str, name: str, phone: str, pays_by: str | None = None) -> None:
    db.execute(
        insert(Signup)
        .values(id=uuid.uuid4(), source=source, name=name.strip(), phone=normalize_phone(phone), pays_by=pays_by)
        .on_conflict_do_nothing(index_elements=["phone", "source"])
    )


def stats(db: Session) -> dict:
    by_source = dict(db.execute(select(Signup.source, func.count()).group_by(Signup.source)).all())
    pays_by = dict(
        db.execute(
            select(Signup.pays_by, func.count()).where(Signup.pays_by.is_not(None)).group_by(Signup.pays_by)
        ).all()
    )
    since = clock.now() - timedelta(hours=1)
    total_ms = Message.latency_ms["total"].as_float()
    median = db.scalar(
        select(func.percentile_cont(0.5).within_group(total_ms)).where(
            Message.direction == "in", Message.latency_ms.is_not(None)
        )
    )
    return {
        "total": db.scalar(select(func.count(func.distinct(Signup.phone)))) or 0,
        "by_source": {s: by_source.get(s, 0) for s in ("landing", "household", "helper")},
        "last_hour": db.scalar(select(func.count(func.distinct(Signup.phone))).where(Signup.created_at >= since)) or 0,
        "pays_by": pays_by,
        "voice_median_latency_ms": round(median) if median is not None else None,
    }
