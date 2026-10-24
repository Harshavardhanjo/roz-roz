"""Agent entry points. AGENT_RUNTIME=agenticorg uses AgenticOrg's A2A endpoint; local runs a Claude tool-use loop
over the same prompts and tools. Both must write an agent_run row. Owned by Divyansh."""
from ..config import settings


async def run_liaison(transcript: str, ctx: dict, message_id: str) -> dict:
    if settings.agent_runtime == "agenticorg":
        # TODO(Divyansh): POST {AGENTICORG_BASE_URL}/api/v1/a2a/message:send to LIAISON_AGENT_ID; parse the final JSON.
        raise NotImplementedError("AgenticOrg liaison")
    # TODO(Divyansh): local loop: model claude-haiku-5-5, tools from tool_schemas.json, max 6 tool calls, 10 s.
    raise NotImplementedError("local liaison")


async def run_treasurer(request_id: str) -> dict:
    """Called by the backend when a request is created; 8 s timeout, then the backend calls the tools directly."""
    # TODO(Divyansh): same two runtimes, prompts/treasurer.md, max 4 tool calls.
    raise NotImplementedError("treasurer")
