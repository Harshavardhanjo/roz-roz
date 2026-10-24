import secrets
import uuid

from fastapi import APIRouter, Depends

from .. import stubs
from ..config import settings
from ..deps import current_member, require_owner, todo
from ..schemas import HouseholdCreate, MemberCreate, RulesUpdate

router = APIRouter(prefix="/api", tags=["households"])


@router.post("/households")
def create_household(body: HouseholdCreate):
    if settings.use_stubs:
        token = secrets.token_urlsafe(16)
        return {"household_id": stubs.HOUSEHOLD_ID, "member_id": stubs.OWNER_ID, "token": token,
                "link": f"{settings.web_origin}/h/{token}"}
    todo("create household + owner member + house_rule + house wallet; add signup(source=household)")


@router.get("/me")
def me(member: dict = Depends(current_member)):
    return member


@router.post("/households/{hid}/members")
def add_member(hid: uuid.UUID, body: MemberCreate, owner: dict = Depends(require_owner)):
    if settings.use_stubs:
        token = secrets.token_urlsafe(16)
        return {"member_id": stubs.ROOMMATE_ID, "token": token, "link": f"{settings.web_origin}/h/{token}"}
    todo("create roommate member; add signup(source=household)")


@router.put("/households/{hid}/rules")
def put_rules(hid: uuid.UUID, body: RulesUpdate, owner: dict = Depends(require_owner)):
    if settings.use_stubs:
        return body.model_dump()
    todo("upsert house_rule")


@router.post("/members/{mid}/grant")
def create_grant(mid: uuid.UUID, member: dict = Depends(current_member)):
    if settings.use_stubs:
        return {"grant_id": "grx_stub_" + str(mid)[:8], "scopes": ["roz:advance:max_paise:50000"], "status": "active"}
    todo("services.grantex_client.create_grant")


@router.get("/households/{hid}/dashboard")
def dashboard(hid: uuid.UUID, member: dict = Depends(current_member)):
    if settings.use_stubs:
        return stubs.DASHBOARD
    todo("dashboard aggregation")
