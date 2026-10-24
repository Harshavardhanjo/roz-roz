import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_member, household_of, require_owner
from ..errors import forbidden, not_found
from ..models import Member
from ..schemas import HouseholdCreate, MemberCreate, MemberUpdate, RulesUpdate
from ..services import audit, grants, households, views

router = APIRouter(prefix="/api", tags=["households"])


@router.post("/households", status_code=201)
def create_household(body: HouseholdCreate, db: Session = Depends(get_db)):
    household, owner = households.create_household(db, body.household_name, body.owner_name, body.owner_phone)
    db.commit()
    return {
        "household_id": str(household.id),
        "member_id": str(owner.id),
        "token": owner.link_token,
        "link": households.member_link(owner),
    }


@router.get("/me")
def me(member: Member = Depends(current_member)):
    return {
        "member_id": str(member.id),
        "household_id": str(member.household_id),
        "role": member.role,
        "name": member.name,
    }


@router.post("/households/{hid}/members", status_code=201)
def add_member(
    hid: uuid.UUID, body: MemberCreate, owner: Member = Depends(require_owner), db: Session = Depends(get_db)
):
    household = household_of(db, owner, hid)
    member = households.add_member(db, household, body.name, body.phone, body.split_weight, owner)
    db.commit()
    return {"member_id": str(member.id), "token": member.link_token, "link": households.member_link(member)}


@router.patch("/members/{mid}")
def update_member(
    mid: uuid.UUID, body: MemberUpdate, owner: Member = Depends(require_owner), db: Session = Depends(get_db)
):
    member = db.get(Member, mid)
    if member is None or member.household_id != owner.household_id:
        raise not_found("Member")
    member.split_weight = body.split_weight
    audit.log(
        db,
        household_id=member.household_id,
        actor=f"member:{owner.id}",
        action="update_weight",
        entity="member",
        entity_id=member.id,
        payload={"split_weight": body.split_weight},
        summary=f"{owner.name} set {member.name}'s share weight to {body.split_weight}",
    )
    db.commit()
    return {"member_id": str(member.id), "split_weight": member.split_weight}


@router.put("/households/{hid}/rules")
def put_rules(hid: uuid.UUID, body: RulesUpdate, owner: Member = Depends(require_owner), db: Session = Depends(get_db)):
    rule = households.update_rules(db, household_of(db, owner, hid), body, owner)
    db.commit()
    return {
        "vote_rule": rule.vote_rule,
        "two_person_limit_paise": rule.two_person_limit_paise,
        "emergency_limit_paise": rule.emergency_limit_paise,
    }


@router.post("/members/{mid}/grant", status_code=201)
def create_grant(mid: uuid.UUID, member: Member = Depends(current_member), db: Session = Depends(get_db)):
    if mid != member.id:
        raise forbidden("own_grant_only", "Each member grants the agent their own limits")
    grant = grants.create_grant(db, member)
    db.commit()
    return {"grant_id": grant.id, "scopes": grant.scopes, "status": grant.status}


@router.get("/households/{hid}/dashboard")
def dashboard(hid: uuid.UUID, member: Member = Depends(current_member), db: Session = Depends(get_db)):
    household_of(db, member, hid)
    return views.dashboard(db, member)
