from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import SignupCreate
from ..services import signups

router = APIRouter(prefix="/api", tags=["signups"])


@router.post("/signups", status_code=201)
def create_signup(body: SignupCreate, db: Session = Depends(get_db)):
    signups.record(db, body.source, body.name, body.phone, body.pays_by)
    db.commit()
    return {"ok": True}


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    return signups.stats(db)
