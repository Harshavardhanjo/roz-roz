from fastapi import APIRouter, Depends

from ..deps import require_owner, todo

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/reset-demo")
def reset_demo(owner: dict = Depends(require_owner)):
    todo("seed.demo_seed.reset()")  # TODO(Harsha)
