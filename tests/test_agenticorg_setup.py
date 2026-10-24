"""The AgenticOrg setup files stay in step with the tools, prompts and output models."""

import json

import pytest

from app.agents import agenticorg_setup as setup
from app.agents.outputs import output_schema
from app.agents.runtime import LIAISON_TOOLS, TREASURER_TOOLS, _tool_schemas


@pytest.mark.parametrize("agent", ["liaison", "treasurer"])
def test_committed_files_match_regeneration(agent):
    committed = (setup.OUT_DIR / f"{agent}.json").read_text(encoding="utf-8")
    assert committed == setup.render(agent), "run: python -m app.agents.agenticorg_setup"


@pytest.mark.parametrize(("agent", "tools"), [("liaison", LIAISON_TOOLS), ("treasurer", TREASURER_TOOLS)])
def test_spec_shape(agent, tools):
    spec = json.loads(setup.render(agent))
    assert [t["name"] for t in spec["tools"]] == list(tools)
    assert spec["output_schema"] == output_schema(agent)
    for tool in spec["tools"]:
        assert tool["method"] == "POST"
        assert tool["url"] == f"https://roz-roz.vercel.app/tools/{tool['name']}"
        body = tool["input_schema"]
        assert body["required"] == ["args", "idempotency_key", "agent_run_id"]
        assert body["properties"]["args"] == _tool_schemas()[tool["name"]]
        assert "<TOOLS_TOKEN" in tool["headers"]["Authorization"]  # a placeholder, never a real token
