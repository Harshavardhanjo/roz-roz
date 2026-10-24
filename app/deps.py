"""Request dependencies: DB session, member auth by link token, ownership and household scoping."""

import uuid

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .errors import ApiError, forbidden, not_found
from .models import Employment, Household, Member, Request


def current_member(x_roz_token: str | None = Header(default=None), db: Session = Depends(get_db)) -> Member:
    if not x_roz_token:
        raise forbidden("missing_token", "X-Roz-Token header is required")
    member = db.scalar(select(Member).where(Member.link_token == x_roz_token))
    if member is None:
        raise forbidden("bad_token", "This link is not valid")
    return member


def require_owner(member: Member = Depends(current_member)) -> Member:
    if member.role != "owner":
        raise forbidden("owner_only", "Only the household owner can do this")
    return member


def tools_auth(authorization: str | None = Header(default=None)) -> None:
    if authorization != f"Bearer {settings.tools_token}":
        raise ApiError(401, "bad_token", "Invalid tools token")


def admin_auth(x_admin_token: str | None = Header(default=None)) -> None:
    if x_admin_token != settings.admin_token:
        raise ApiError(401, "bad_token", "Invalid admin token")


def household_of(db: Session, member: Member, household_id: uuid.UUID) -> Household:
    """The member's own household; any other id is reported as not found."""
    if member.household_id != household_id:
        raise not_found("Household")
    return db.get(Household, household_id)


def employment_of(db: Session, member: Member, employment_id: uuid.UUID) -> Employment:
    employment = db.get(Employment, employment_id)
    if employment is None or employment.household_id != member.household_id:
        raise not_found("Helper")
    return employment


def request_of(db: Session, member: Member, request_id: uuid.UUID) -> Request:
    req = db.get(Request, request_id)
    if req is None or req.household_id != member.household_id:
        raise not_found("Request")
    return req
