"""Households, members (owner + roommates), helpers and their employment terms."""

import re
import secrets
import uuid
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..errors import bad_request, conflict
from ..models import Employment, Helper, Household, HouseRule, Member, Person, Wallet
from ..schemas import EmploymentUpdate, HelperCreate, RulesUpdate
from . import audit, signups


def new_token() -> str:
    return secrets.token_urlsafe(24)


def member_link(member: Member) -> str:
    return f"{settings.web_origins[0]}/h/{member.link_token}"


def normalize_e164(number: str) -> str:
    """'+91 98450 12345', '9845012345', '919845012345' -> '+919845012345'."""
    digits = re.sub(r"\D", "", number or "")
    if len(digits) == 10:
        digits = "91" + digits
    if not 11 <= len(digits) <= 15:
        raise bad_request("invalid_phone", f"'{number}' is not a valid WhatsApp number")
    return "+" + digits


def whatsapp_link() -> str | None:
    """wa.me link to Roz Roz's WhatsApp Business number, for the owner to share with a helper."""
    if not settings.wa_business_number:
        return None
    number = re.sub(r"\D", "", settings.wa_business_number)
    return f"https://wa.me/{number}?text={quote('Namaste')}"


def _new_member(db: Session, household_id: uuid.UUID, name: str, phone: str, role: str, split_weight: int) -> Member:
    """Each membership starts as its own person; POST /api/me/link joins memberships the same person holds."""
    person = Person(name=name.strip(), phone=signups.normalize_phone(phone))
    db.add(person)
    db.flush()
    member = Member(
        household_id=household_id,
        person_id=person.id,
        name=name.strip(),
        phone=phone,
        role=role,
        split_weight=split_weight,
        link_token=new_token(),
    )
    db.add(member)
    db.flush()
    return member


def create_household(db: Session, name: str, owner_name: str, owner_phone: str) -> tuple[Household, Member]:
    household = Household(name=name.strip())
    db.add(household)
    db.flush()
    owner = _new_member(db, household.id, owner_name, owner_phone, "owner", 1)
    household.owner_member_id = owner.id
    db.add(HouseRule(household_id=household.id))
    db.add(Wallet(household_id=household.id, kind="house"))
    signups.record(db, "household", owner.name, owner_phone)
    audit.log(
        db,
        household_id=household.id,
        actor=f"member:{owner.id}",
        action="create_household",
        entity="household",
        entity_id=household.id,
        summary=f"{owner.name} created {household.name}",
    )
    return household, owner


def add_member(db: Session, household: Household, name: str, phone: str, split_weight: int, by: Member) -> Member:
    phone_digits = signups.normalize_phone(phone)
    if any(signups.normalize_phone(m.phone or "") == phone_digits for m in voters(db, household.id)):
        raise conflict("member_exists", "Someone with this phone number is already in the flat")
    member = _new_member(db, household.id, name, phone, "roommate", split_weight)
    signups.record(db, "household", member.name, phone)
    audit.log(
        db,
        household_id=household.id,
        actor=f"member:{by.id}",
        action="add_member",
        entity="member",
        entity_id=member.id,
        summary=f"{by.name} added {member.name}",
    )
    return member


def voters(db: Session, household_id: uuid.UUID) -> list[Member]:
    """Everyone who currently votes and shares costs: the owner and all roommates not removed."""
    return list(
        db.scalars(
            select(Member)
            .where(Member.household_id == household_id, Member.removed_at.is_(None))
            .order_by(Member.created_at)
        )
    )


def rules(db: Session, household_id: uuid.UUID) -> HouseRule:
    return db.get(HouseRule, household_id)


def update_rules(db: Session, household: Household, body: RulesUpdate, by: Member) -> HouseRule:
    rule = rules(db, household.id)
    for field, value in body.model_dump().items():
        setattr(rule, field, value)
    audit.log(
        db,
        household_id=household.id,
        actor=f"member:{by.id}",
        action="update_rules",
        entity="house_rule",
        payload=body.model_dump(),
        summary=f"{by.name} updated the house rules",
    )
    return rule


def add_helper(db: Session, household: Household, body: HelperCreate, by: Member) -> tuple[Helper, Employment]:
    _check_limits(
        body.advance_auto_limit_paise,
        body.advance_monthly_limit_paise,
        body.grocery_auto_limit_paise,
        body.grocery_monthly_budget_paise,
        body.salary_paise,
    )
    e164 = normalize_e164(body.whatsapp_e164)
    helper = db.scalar(select(Helper).where(Helper.whatsapp_e164 == e164))
    if helper is None:
        helper = Helper(name=body.name.strip(), whatsapp_e164=e164, lang=body.lang)
        db.add(helper)
        db.flush()
    elif db.scalar(
        select(func.count())
        .select_from(Employment)
        .where(Employment.household_id == household.id, Employment.helper_id == helper.id)
    ):
        raise conflict("helper_exists", f"{helper.name} is already a helper in this household")
    employment = Employment(
        household_id=household.id,
        helper_id=helper.id,
        role=body.role.strip(),
        salary_paise=body.salary_paise,
        payday_dom=body.payday_dom,
        weekly_off=sorted(set(body.weekly_off)),
        paid_leaves_per_month=body.paid_leaves_per_month,
        deduct_extra_leave=body.deduct_extra_leave,
        advance_auto_limit_paise=body.advance_auto_limit_paise,
        advance_monthly_limit_paise=body.advance_monthly_limit_paise,
        grocery_auto_limit_paise=body.grocery_auto_limit_paise,
        grocery_monthly_budget_paise=body.grocery_monthly_budget_paise,
        status="active",
    )
    db.add(employment)
    db.flush()
    db.add(Wallet(household_id=household.id, kind="helper_spending", employment_id=employment.id))
    audit.log(
        db,
        household_id=household.id,
        actor=f"member:{by.id}",
        action="add_helper",
        entity="employment",
        entity_id=employment.id,
        summary=f"{by.name} added {helper.name} ({employment.role})",
    )
    db.flush()
    return helper, employment


def update_employment(db: Session, employment: Employment, body: EmploymentUpdate, by: Member) -> Employment:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise bad_request("no_changes", "Nothing to update")
    lang = changes.pop("lang", None)
    if lang:
        db.get(Helper, employment.helper_id).lang = lang
    if "weekly_off" in changes:
        changes["weekly_off"] = sorted(set(changes["weekly_off"]))
    for field, value in changes.items():
        setattr(employment, field, value)
    _check_limits(
        employment.advance_auto_limit_paise,
        employment.advance_monthly_limit_paise,
        employment.grocery_auto_limit_paise,
        employment.grocery_monthly_budget_paise,
        employment.salary_paise,
    )
    audit.log(
        db,
        household_id=employment.household_id,
        actor=f"member:{by.id}",
        action="update_terms",
        entity="employment",
        entity_id=employment.id,
        payload={**changes, **({"lang": lang} if lang else {})},
        summary=f"{by.name} updated terms",
    )
    return employment


def _check_limits(advance_auto: int, advance_month: int, grocery_auto: int, grocery_month: int, salary: int) -> None:
    if advance_auto > advance_month or grocery_auto > grocery_month:
        raise bad_request("invalid_limits", "An auto-approve limit can't be above its monthly limit")
    if advance_month >= salary:
        # Advances are recovered in full on payday, so a month's advances must stay below the salary.
        raise bad_request("invalid_limits", "The monthly advance limit must be below the salary")
