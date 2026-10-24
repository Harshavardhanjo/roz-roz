from fastapi import Depends, Header, HTTPException

from . import stubs
from .config import settings


def todo(what: str):
    """Raised by endpoints whose real implementation isn't written yet (USE_STUBS=false)."""
    raise HTTPException(status_code=501, detail={"error": {"code": "not_implemented", "message": what}})


def current_member(x_roz_token: str | None = Header(default=None)) -> dict:
    if not x_roz_token:
        raise HTTPException(status_code=403, detail={"error": {"code": "missing_token", "message": "X-Roz-Token required"}})
    if settings.use_stubs:
        return stubs.ME
    todo("look up member by link_token")  # TODO(Harsha)


def require_owner(member: dict = Depends(current_member)) -> dict:
    if member["role"] != "owner":
        raise HTTPException(status_code=403, detail={"error": {"code": "owner_only", "message": "Owner only"}})
    return member


def tools_auth(authorization: str | None = Header(default=None)) -> None:
    if authorization != f"Bearer {settings.tools_token}":
        raise HTTPException(status_code=401, detail={"error": {"code": "bad_token", "message": "Invalid tools token"}})
