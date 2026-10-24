"""Each member's grant to the treasurer agent: what it may approve and pay on their behalf without asking.

Scopes use Grantex's resource:action:constraint form, one set per helper, frozen at grant time:
    roz:advance:emp:<employment_id>:max_paise:<advance auto limit>
    roz:grocery:emp:<employment_id>:max_paise:<grocery auto limit>   (grocery money and cash reimbursements)
    roz:salary:emp:<employment_id>:max_paise:<salary>
A payment the agent makes alone must be covered by every member's active grant. If terms change or a helper is added
after a grant, the old grant no longer covers it and requests go to a vote until the member grants again.

Enforcement is local (provider 'local'); the Grantex SDK is not wired in yet."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..models import AgentGrant, Employment, Member
from . import audit

SCOPE_KINDS = {"advance": "advance", "grocery_money": "grocery", "reimbursement": "grocery", "salary": "salary"}


@dataclass
class GrantCheck:
    allowed: bool
    checked: list[dict] = field(default_factory=list)

    @property
    def label(self) -> str:
        ok = sum(1 for c in self.checked if c["allowed"])
        return f"{'allowed' if self.allowed else 'refused'} ({ok}/{len(self.checked)} grants, local)"


def scopes_for(db: Session, household_id: uuid.UUID) -> list[str]:
    scopes = []
    for emp in db.scalars(
        select(Employment).where(Employment.household_id == household_id, Employment.status == "active")
    ):
        scopes += [
            f"roz:advance:emp:{emp.id}:max_paise:{emp.advance_auto_limit_paise}",
            f"roz:grocery:emp:{emp.id}:max_paise:{emp.grocery_auto_limit_paise}",
            f"roz:salary:emp:{emp.id}:max_paise:{emp.salary_paise}",
        ]
    return scopes


def active_grant(db: Session, member: Member) -> AgentGrant | None:
    if not member.grantex_grant_id:
        return None
    grant = db.get(AgentGrant, member.grantex_grant_id)
    return grant if grant is not None and grant.status == "active" else None


def create_grant(db: Session, member: Member) -> AgentGrant:
    """Grant (or refresh) the member's limits from the household's current terms; any previous grant is revoked."""
    previous = active_grant(db, member)
    if previous is not None:
        previous.status = "revoked"
        previous.revoked_at = clock.now()
    grant = AgentGrant(
        id=f"local_{uuid.uuid4().hex[:16]}",
        member_id=member.id,
        household_id=member.household_id,
        scopes=scopes_for(db, member.household_id),
        status="active",
        provider="local",
        created_at=clock.now(),
    )
    db.add(grant)
    db.flush()
    member.grantex_grant_id = grant.id
    audit.log(
        db,
        household_id=member.household_id,
        actor=f"member:{member.id}",
        action="grant_limits",
        entity="member",
        entity_id=member.id,
        payload={"grant_id": grant.id, "scopes": grant.scopes},
        summary=f"{member.name} granted the agent its limits",
    )
    return grant


def grant_status(db: Session, member: Member) -> str:
    """active | outdated (terms changed or helpers added since) | missing."""
    grant = active_grant(db, member)
    if grant is None:
        return "missing"
    return "active" if set(scopes_for(db, member.household_id)) <= set(grant.scopes) else "outdated"


def _covers(scopes: list[str], kind: str, employment_id: uuid.UUID, amount: int) -> bool:
    prefix = f"roz:{kind}:emp:{employment_id}:max_paise:"
    return any(s.startswith(prefix) and amount <= int(s[len(prefix) :]) for s in scopes)


def check(db: Session, household_id: uuid.UUID, kind: str, employment_id: uuid.UUID, amount: int) -> GrantCheck:
    """Does every member's active grant cover the agent paying `amount` of this kind for this helper alone?"""
    scope_kind = SCOPE_KINDS.get(kind)
    members = list(
        db.scalars(
            select(Member)
            .where(Member.household_id == household_id, Member.removed_at.is_(None))
            .order_by(Member.created_at)
        )
    )
    checked = []
    for m in members:
        grant = active_grant(db, m)
        if grant is None:
            checked.append({"member_id": str(m.id), "grant_id": None, "allowed": False, "reason": "no grant"})
        elif scope_kind is None or not _covers(grant.scopes, scope_kind, employment_id, amount):
            checked.append(
                {"member_id": str(m.id), "grant_id": grant.id, "allowed": False, "reason": "not covered by this grant"}
            )
        else:
            checked.append({"member_id": str(m.id), "grant_id": grant.id, "allowed": True, "reason": "covered"})
    return GrantCheck(allowed=bool(checked) and all(c["allowed"] for c in checked), checked=checked)
