from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import admin_auth

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(admin_auth)])


@router.post("/reset-demo")
def reset_demo(db: Session = Depends(get_db)):
    """Wipes every table and loads the demo seed. Call it from a server-side route (it needs X-Admin-Token)."""
    from seed.demo_seed import reset  # the seed builds on the services; import lazily to keep startup light

    result = reset(db)
    db.commit()
    return result
