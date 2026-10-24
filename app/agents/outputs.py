"""Structured final answers of the two agents.

One Pydantic model per agent is the single source of truth: the prompts embed its JSON Schema, the local runtime
offers it as the `final_answer` tool (and forces that tool once the tool-call cap is reached), the AgenticOrg task
carries it, and every answer is validated against it."""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_CLARIFY_CHARS = 300
MAX_SUMMARY_CHARS = 300
FINAL_ANSWER_TOOL = "final_answer"


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LiaisonOutput(_Output):
    """The liaison's final answer. The reply to the helper is built from the tool outcomes, not from this."""

    clarify: str | None = Field(
        default=None,
        max_length=MAX_CLARIFY_CHARS,
        description="null when a tool was called for everything the helper asked. Otherwise one short question in "
        "the helper's language asking for what is missing (which household, an amount, a date).",
    )

    @field_validator("clarify")
    @classmethod
    def _blank_is_none(cls, v: str | None) -> str | None:
        return v or None


class TreasurerOutput(_Output):
    """The treasurer's final answer. The request's real state is read from the tool results, not from this."""

    status: Literal["executed", "needs_vote", "needs_topup", "rejected"] = Field(
        description="What happened to the request: executed (approved and paid out), needs_vote (sent to the "
        "roommates), needs_topup (the house wallet is too low), rejected.",
    )
    summary: str = Field(
        default="",
        max_length=MAX_SUMMARY_CHARS,
        description="One plain sentence for the audit log, using only numbers the tools returned.",
    )

    @field_validator("summary", mode="before")
    @classmethod
    def _truncate(cls, v: Any) -> Any:
        return v.strip()[:MAX_SUMMARY_CHARS] if isinstance(v, str) else v


OUTPUT_MODELS: dict[str, type[_Output]] = {"liaison": LiaisonOutput, "treasurer": TreasurerOutput}


def output_schema(agent: str) -> dict:
    return OUTPUT_MODELS[agent].model_json_schema()


def output_schema_text(agent: str) -> str:
    return json.dumps(output_schema(agent), ensure_ascii=False)


def final_answer_tool(agent: str) -> dict:
    """Anthropic tool definition: calling it is how the local agent gives its structured final answer."""
    return {
        "name": FINAL_ANSWER_TOOL,
        "description": "Give your final answer and finish. Call it once, after all other tool calls.",
        "input_schema": output_schema(agent),
    }
