"""Membership changes: removing a roommate, and one person holding several flats.

Removing keeps history (votes, top-ups, statements) but ends access at once: the link token is replaced, the grant is
revoked, and the person's votes on still-open requests are withdrawn.

A person can be in several flats. Each membership keeps its own link; two memberships are joined into one person only
when the caller proves they hold both links, so nobody can attach another person's flat by typing their phone."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import conflict, forbidden, not_found
from ..models import Household, Member, Person, Request, Vote
from . import audit, contributions, grants, households, requests


def flats(db: Session, member: Member) -> list[dict]:
    """Every active membership of this member's person, including this one."""
    rows = db.execute(
        select(Member, Household.name)
        .join(Household, Household.id == Member.household_id)
        .where(Member.person_id == member.person_id, Member.removed_at.is_(None))
        .order_by(Member.created_at)
    ).all()
    return [
        {
            "household_id": str(m.household_id),
            "household_name": name,
            "member_id": str(m.id),
            "role": m.role,
            "token": m.link_token,
            "link": households.member_link(m),
            "current": m.id == member.id,
        }
        for m, name in rows
    ]


def me(db: Session, member: Member) -> dict:
    return {
        "member_id": str(member.id),
        "household_id": str(member.household_id),
        "role": member.role,
        "name": member.name,
        "flats": flats(db, member),
    }


def link(db: Session, member: Member, other_token: str) -> dict:
    """Join the membership behind `other_token` into this member's person."""
    other = db.scalar(select(Member).where(Member.link_token == other_token, Member.removed_at.is_(None)))
    if other is None:
        raise not_found("Link")
    if other.person_id == member.person_id:
        return me(db, member)
    other_person = other.person_id
    others = list(db.scalars(select(Member).where(Member.person_id == other_person, Member.removed_at.is_(None))))
    mine = {m.household_id for m in db.scalars(select(Member).where(Member.person_id == member.person_id))}
    if any(m.household_id in mine for m in others):
        raise conflict("same_household", "These links are for the same flat")
    for m in db.scalars(select(Member).where(Member.person_id == other_person)):
        m.person_id = member.person_id
    db.flush()
    db.execute(delete(Person).where(Person.id == other_person))
    for m in others:
        audit.log(
            db,
            household_id=m.household_id,
            actor=f"member:{m.id}",
            action="link_flats",
            entity="member",
            entity_id=m.id,
            summary=f"{m.name} joined this flat to their other flats",
        )
    return me(db, member)


def remove(db: Session, household: Household, target_id: uuid.UUID, by: Member) -> dict:
    target = db.get(Member, target_id)
    if target is None or target.household_id != household.id or target.removed_at is not None:
        raise not_found("Member")
    if target.id == household.owner_member_id:
        raise forbidden("cannot_remove_owner", "The owner can't be removed")

    month = clock.current_month()
    final_balance = next(
        r["balance_paise"]
        for r in contributions.compute(db, household.id, month)["members"]
        if r["member_id"] == str(target.id)
    )
    target.removed_at = clock.now()
    target.link_token = households.new_token()  # the old link stops working immediately
    grant = grants.active_grant(db, target)
    if grant is not None:
        grant.status, grant.revoked_at = "revoked", clock.now()

    open_votes = list(
        db.scalars(select(Request).where(Request.household_id == household.id, Request.status == "needs_vote"))
    )
    withdrawn = db.execute(
        delete(Vote).where(Vote.member_id == target.id, Vote.request_id.in_([r.id for r in open_votes]))
    ).rowcount
    audit.log(
        db,
        household_id=household.id,
        actor=f"member:{by.id}",
        action="remove_member",
        entity="member",
        entity_id=target.id,
        payload={"final_balance_paise": final_balance, "votes_withdrawn": withdrawn},
        summary=f"{by.name} removed {target.name}; their balance for {month} is {final_balance} paise",
    )
    db.flush()
    for req in open_votes:
        requests.resolve_votes(db, req, actor=f"member:{by.id}")
    return {
        "member_id": str(target.id),
        "removed_at": target.removed_at.isoformat(),
        "final_balance_paise": final_balance,
        "month": month,
    }
