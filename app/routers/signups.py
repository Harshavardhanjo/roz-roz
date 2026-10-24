from fastapi import APIRouter

from ..config import settings
from ..deps import todo
from ..schemas import SignupCreate

router = APIRouter(prefix="/api", tags=["signups"])


@router.post("/signups")
def create_signup(body: SignupCreate):
    if settings.use_stubs:
        return {"ok": True}
    todo("insert signup (unique on phone + source)")


@router.get("/stats")
def stats():
    if settings.use_stubs:
        return {"total": 0, "by_source": {"landing": 0, "household": 0, "helper": 0}, "last_hour": 0,
                "pays_by": {}, "voice_median_latency_ms": None}
    todo("signup counts")
