"""Runs the treasurer on a new request: the AgenticOrg / local agent when AGENT_RUNTIME is set, otherwise (or if the
agent fails or times out) the same steps in code. The outcome is identical either way because the agent can only act
through the tools, and the tools enforce the rules."""

import asyncio
import logging

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Request
from . import requests

log = logging.getLogger(__name__)
AGENT_TIMEOUT_S = 8


def _run_agent(request_id: str) -> None:
    from ..agents import runtime  # imported lazily: agent code is optional at runtime

    asyncio.run(asyncio.wait_for(runtime.run_treasurer(request_id), timeout=AGENT_TIMEOUT_S))


def process(db: Session, req: Request) -> Request:
    """Must be called from synchronous code (a sync route or a worker thread), never inside an event loop."""
    if settings.agent_runtime in ("agenticorg", "local"):
        db.commit()  # the agent's tool calls run in their own transactions and must see this request
        try:
            _run_agent(str(req.id))
        except Exception as exc:  # noqa: BLE001 - any agent failure falls back to the rules in code
            log.warning("treasurer agent failed for %s (%s); using the rules directly", req.id, exc)
        db.refresh(req)
    if req.status == "pending":
        requests.auto_process(db, req, actor="system:treasurer")
    return req
