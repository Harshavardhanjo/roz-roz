"""HTTP client for contract 3 (POST /tools/{name}), used by the local agent runtime.

Arguments are validated against app.schemas.TOOL_ARGS before anything is sent, so a bad model output never reaches
the backend. Business failures come back as {"ok": false, "error": {...}} (HTTP 200); transport failures raise
ToolTransportError."""

import logging
import time
from collections.abc import Callable

import httpx
from pydantic import ValidationError

from ..config import settings
from ..schemas import TOOL_ARGS
from .agent_config import agent_settings

log = logging.getLogger(__name__)

MAX_KEY_LEN = 200


class ToolTransportError(Exception):
    """The tools endpoint could not be reached or did not return a contract 3 body."""


def _default_http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=agent_settings.tools_timeout_s)


# Used when call(..., http=None). Tests point it at the ASGI app:
#   tools_client.http_factory = lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()))
http_factory: Callable[[], httpx.AsyncClient] = _default_http


def _fail(code: str, message) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


async def call(
    name: str,
    args: dict,
    idempotency_key: str,
    agent_run_id: str | None = None,
    *,
    http: httpx.AsyncClient | None = None,
) -> dict:
    if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > MAX_KEY_LEN:
        raise ValueError(f"idempotency_key must be a non-empty string of at most {MAX_KEY_LEN} characters")
    model = TOOL_ARGS.get(name)
    if model is None:
        log.info("tool %s rejected locally: unknown_tool", name)
        return _fail("unknown_tool", f"Unknown tool {name!r}")
    if not isinstance(args, dict):
        log.info("tool %s rejected locally: invalid_args", name)
        return _fail("invalid_args", "args must be an object")
    try:
        model.model_validate(args)
    except ValidationError as e:
        log.info("tool %s rejected locally: invalid_args", name)
        return _fail("invalid_args", e.errors(include_url=False, include_input=False, include_context=False))

    body = {"args": args, "idempotency_key": idempotency_key, "agent_run_id": agent_run_id}
    headers = {"Authorization": f"Bearer {settings.tools_token}"}
    url = f"{settings.public_base_url.rstrip('/')}/tools/{name}"
    start = time.perf_counter()
    client = http if http is not None else http_factory()
    try:
        r = await client.post(url, headers=headers, json=body)
    except httpx.HTTPError as e:
        raise ToolTransportError(f"{name}: {type(e).__name__}") from e
    finally:
        if http is None:
            await client.aclose()
    ms = int((time.perf_counter() - start) * 1000)
    if r.status_code >= 500:
        raise ToolTransportError(f"{name}: HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError as e:
        raise ToolTransportError(f"{name}: response is not JSON (HTTP {r.status_code})") from e
    if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
        raise ToolTransportError(f"{name}: not a contract 3 body (HTTP {r.status_code})")
    outcome = "ok" if data["ok"] else str((data.get("error") or {}).get("code", "error"))
    log.info("tool %s %s %dms", name, outcome, ms)
    return data
