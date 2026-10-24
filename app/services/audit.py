"""Hash-chained audit log: hash = sha256(prev_hash + canonical JSON of the row's content).

One global chain. Writers take a transaction-scoped advisory lock so two concurrent writes can't fork the chain."""

import hashlib
import json
import uuid
from datetime import UTC

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import clock
from ..models import AuditLog

GENESIS = "genesis"
_LOCK_KEY = 74_201_001  # arbitrary, unique to the audit chain

CONTENT_FIELDS = (
    "at",
    "household_id",
    "actor",
    "action",
    "entity",
    "entity_id",
    "rule_applied",
    "grantex_decision",
    "data_sent_to",
    "payload",
)


def canonical(row: dict) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def chain_hash(prev_hash: str | None, row: dict) -> str:
    return hashlib.sha256(((prev_hash or GENESIS) + canonical(row)).encode()).hexdigest()


def verify_chain(rows: list[dict]) -> bool:
    """rows: oldest first, each with 'prev_hash', 'hash' and its content fields."""
    prev = None
    for r in rows:
        content = {k: v for k, v in r.items() if k not in ("prev_hash", "hash")}
        if r.get("prev_hash") != prev or r["hash"] != chain_hash(prev, content):
            return False
        prev = r["hash"]
    return True


def _content(entry: AuditLog) -> dict:
    return {
        "at": entry.at.astimezone(UTC).isoformat(),
        "household_id": str(entry.household_id) if entry.household_id else None,
        "actor": entry.actor,
        "action": entry.action,
        "entity": entry.entity,
        "entity_id": str(entry.entity_id) if entry.entity_id else None,
        "rule_applied": entry.rule_applied,
        "grantex_decision": entry.grantex_decision,
        "data_sent_to": entry.data_sent_to,
        "payload": entry.payload,
    }


def log(
    db: Session,
    *,
    actor: str,
    action: str,
    household_id: uuid.UUID | None = None,
    entity: str | None = None,
    entity_id: uuid.UUID | None = None,
    rule_applied: str | None = None,
    grantex_decision: str | None = None,
    data_sent_to: dict | None = None,
    summary: str | None = None,
    payload: dict | None = None,
) -> AuditLog:
    """Append one entry in the caller's transaction. `summary` is the plain sentence the audit page shows."""
    db.execute(text("select pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    prev_hash = db.scalar(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))
    body = dict(payload or {})
    if summary:
        body["summary"] = summary
    entry = AuditLog(
        at=clock.now(),
        household_id=household_id,
        actor=actor,
        action=action,
        entity=entity,
        entity_id=entity_id,
        rule_applied=rule_applied,
        grantex_decision=grantex_decision,
        data_sent_to=data_sent_to,
        payload=body or None,
        prev_hash=prev_hash,
    )
    entry.hash = chain_hash(prev_hash, _content(entry))
    db.add(entry)
    db.flush()
    return entry


def verify(db: Session) -> bool:
    """Recompute the whole chain from the database."""
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id)).all()
    return verify_chain([{**_content(r), "prev_hash": r.prev_hash, "hash": r.hash} for r in rows])
