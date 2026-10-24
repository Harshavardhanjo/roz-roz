"""HTTP client for contract 3, used by both agent runtimes."""

import httpx

from ..config import settings


async def call(name: str, args: dict, idempotency_key: str, agent_run_id: str | None = None) -> dict:
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.post(
            f"{settings.public_base_url}/tools/{name}",
            headers={"Authorization": f"Bearer {settings.tools_token}"},
            json={"args": args, "idempotency_key": idempotency_key, "agent_run_id": agent_run_id},
        )
        return r.raise_for_status().json()
