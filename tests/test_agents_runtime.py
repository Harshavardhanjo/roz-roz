"""Agent runtimes: tools client, local Claude loop (scripted Anthropic via httpx.MockTransport), AgenticOrg client,
reply building, agent_run rows, and end-to-end runs against the real /tools endpoint."""

import asyncio
import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.agents import runtime, tools_client
from app.agents.runtime import AgentError, minimise_context, parse_output, run_liaison, run_treasurer
from app.agents.tools_client import ToolTransportError
from app.config import settings
from app.main import create_app
from app.models import AgentRun, Request, ToolCallRecord
from app.stubs import EMPLOYMENT_ID, HELPER_CONTEXT, REQUEST_ID, TOOL_RESULTS
from tests.conftest import Flat, tool

MSG_ID = "11110000-0000-4000-8000-000000000001"
LIAISON_UUID = "aaaa0000-0000-4000-8000-00000000000a"
TREASURER_UUID = "bbbb0000-0000-4000-8000-00000000000b"


# ---- helpers ----


def tool_use(name, inp, id_=None):
    return {"type": "tool_use", "id": id_ or f"tu_{uuid.uuid4().hex[:8]}", "name": name, "input": inp}


def text(t):
    return {"type": "text", "text": t}


def msg(*blocks):
    return {"id": "msg", "type": "message", "role": "assistant", "content": list(blocks), "stop_reason": "end_turn"}


class Script:
    """Scripted Anthropic Messages API: each step is a response dict or a callable(request_body) -> dict."""

    def __init__(self, *steps):
        self.steps, self.requests = list(steps), []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append({"url": str(request.url), "headers": dict(request.headers), "body": body})
        step = self.steps.pop(0) if self.steps else msg(text('{"clarify": null}'))
        return httpx.Response(200, json=step(body) if callable(step) else step)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


class FakeTools:
    """Mock /tools endpoint returning the stub result shapes (or a scripted error per tool)."""

    def __init__(self, errors=None):
        self.calls, self.errors = [], errors or {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content)
        self.calls.append({"name": name, "auth": request.headers.get("authorization"), "url": str(request.url)} | body)
        if name in self.errors:
            return httpx.Response(200, json={"ok": False, "error": {"code": self.errors[name], "message": "x"}})
        return httpx.Response(200, json={"ok": True, "result": TOOL_RESULTS[name]})


@pytest.fixture
def fake_tools(monkeypatch):
    fake = FakeTools()
    monkeypatch.setattr(
        tools_client, "http_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    )
    return fake


@pytest.fixture
def real_tools(monkeypatch):
    app = create_app()
    monkeypatch.setattr(
        tools_client, "http_factory", lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), timeout=30)
    )


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-anthropic-key")
    monkeypatch.setattr(settings, "agent_runtime", "off")


def liaison(transcript, script, ctx=HELPER_CONTEXT, wa="wamid.A1", lang="en"):
    async def go():
        async with script.client() as http:
            return await run_liaison(transcript, ctx, MSG_ID, wa_message_id=wa, lang=lang, http=http)

    return asyncio.run(go())


def agent_runs(db, agent=None):
    q = select(AgentRun)
    if agent:
        q = q.where(AgentRun.agent == agent)
    return db.scalars(q).all()


# ---- tools_client ----


def _never(request):
    raise AssertionError("no HTTP call expected")


def test_tools_client_validates_before_sending():
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_never)) as http:
            unknown = await tools_client.call("drop_tables", {}, "k1", http=http)
            bad = await tools_client.call(
                "create_advance_request", {"employment_id": EMPLOYMENT_ID, "amount_paise": -5}, "k2", http=http
            )
            not_uuid = await tools_client.call("get_balances", {"employment_id": "abc"}, "k3", http=http)
            for key in ("", "x" * 201):
                with pytest.raises(ValueError):
                    await tools_client.call("get_balances", {"employment_id": EMPLOYMENT_ID}, key, http=http)
            return unknown, bad, not_uuid

    unknown, bad, not_uuid = asyncio.run(go())
    assert unknown["ok"] is False and unknown["error"]["code"] == "unknown_tool"
    assert bad["error"]["code"] == "invalid_args"
    assert not_uuid["error"]["code"] == "invalid_args"


def test_tools_client_request_shape():
    fake = FakeTools()

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as http:
            return await tools_client.call("get_balances", {"employment_id": EMPLOYMENT_ID}, "wa:0", "run-1", http=http)

    out = asyncio.run(go())
    assert out == {"ok": True, "result": TOOL_RESULTS["get_balances"]}
    (call,) = fake.calls
    assert call["url"] == f"{settings.public_base_url}/tools/get_balances"
    assert call["auth"] == f"Bearer {settings.tools_token}"
    assert call["args"] == {"employment_id": EMPLOYMENT_ID}
    assert call["idempotency_key"] == "wa:0" and call["agent_run_id"] == "run-1"


@pytest.mark.parametrize(
    "respond",
    [
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("down", request=r)),
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)),
        lambda r: httpx.Response(502, text="bad gateway"),
        lambda r: httpx.Response(200, text="<html>"),
        lambda r: httpx.Response(200, json=[1, 2]),
    ],
)
def test_tools_client_transport_errors(respond):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            await tools_client.call("get_balances", {"employment_id": EMPLOYMENT_ID}, "k", http=http)

    with pytest.raises(ToolTransportError):
        asyncio.run(go())


def test_tools_client_passes_business_errors_through():
    fake = FakeTools(errors={"get_balances": "not_found"})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as http:
            return await tools_client.call("get_balances", {"employment_id": EMPLOYMENT_ID}, "k", http=http)

    assert asyncio.run(go())["error"]["code"] == "not_found"


# ---- pure helpers ----


def test_minimise_context_drops_ids_and_phones():
    ctx = json.loads(json.dumps(HELPER_CONTEXT))
    ctx["name"] = "Lakshmi Devi"
    ctx["whatsapp_e164"] = "+919811100009"
    ctx["households"][0] |= {"wallet_id": "w1", "spending_wallet_id": "w2", "owner_phone": "9000000011"}
    small = minimise_context(ctx)
    blob = json.dumps(small)
    assert small["name"] == "Lakshmi" and small["lang"] == "kn"
    assert "helper_id" not in small and HELPER_CONTEXT["helper_id"] not in blob
    assert "9811100009" not in blob and "9000000011" not in blob and "wallet_id" not in blob
    h = small["households"][0]
    assert h["employment_id"] == EMPLOYMENT_ID and h["consented"] is True
    assert {"paid_leave_left", "advances_this_month_paise", "grocery_left_paise", "spending_wallet_paise"} <= set(h)
    assert {"advance_auto_limit_paise", "advance_monthly_limit_paise", "open_requests"} <= set(h)


def test_parse_output_variants():
    assert parse_output({"status": "executed"}) == {"status": "executed"}
    assert parse_output('{"clarify": null}') == {"clarify": None}
    assert parse_output('Done.\n```json\n{"status": "needs_vote", "summary": "x"}\n```') == {
        "status": "needs_vote",
        "summary": "x",
    }
    assert parse_output('sure: {"clarify": "Which house?"} ok') == {"clarify": "Which house?"}
    assert parse_output("no json here") is None
    assert parse_output(None) is None and parse_output("[1]") is None


def test_tool_definitions_and_prompt():
    names = [t["name"] for t in runtime.tool_definitions("liaison")]
    assert names == list(runtime.LIAISON_TOOLS)
    tdefs = {t["name"]: t for t in runtime.tool_definitions("treasurer")}
    assert set(tdefs) == set(runtime.TREASURER_TOOLS)
    assert tdefs["open_vote"]["input_schema"]["required"] == ["request_id", "context_text"]
    assert all(t["description"] for t in tdefs.values())
    prompt = runtime.render_prompt("liaison", date="2026-10-24", message_id=MSG_ID, helper_context_json={"a": 1})
    assert "2026-10-24" in prompt and MSG_ID in prompt and '{"a": 1}' in prompt
    assert '{"clarify": null}' in prompt  # JSON braces survive (str.replace, not str.format)


# ---- local liaison loop ----


def test_local_liaison_replies_from_outcomes_and_keys(fake_tools, db):
    script = Script(
        msg(
            text("calling tools"),
            tool_use("create_advance_request", {"employment_id": EMPLOYMENT_ID, "amount_paise": 50000}),
            tool_use("get_balances", {"employment_id": EMPLOYMENT_ID}),
        ),
        # the model "says" a wrong number: it must never reach the helper
        msg(text('{"clarify": null, "text": "₹99999 approved"}')),
    )
    out = liaison("naale 500 advance beku, balance eshtu?", script)
    assert out["status"] == "ok" and out["clarify"] is None
    assert out["text"] == (
        "₹500 advance approved. This month's advances: ₹1,500. It will be adjusted in your salary.\n"
        "Paid leave left: 0. Advances this month: ₹1,500. Next pay on 31 Oct: about ₹8,130."
    )
    assert [r["template"] for r in out["replies"]] == ["advance_approved", "balances"]
    assert out["replies"][0]["request_id"] == REQUEST_ID
    # idempotency keys chosen in code, in call order; source_message_id forced; agent_run_id on every call
    assert [c["idempotency_key"] for c in fake_tools.calls] == ["wamid.A1:0", "wamid.A1:1"]
    assert fake_tools.calls[0]["args"]["source_message_id"] == MSG_ID
    assert {c["agent_run_id"] for c in fake_tools.calls} == {out["agent_run_id"]}
    # Anthropic request shape
    req = script.requests[0]
    assert req["url"] == "https://api.anthropic.com/v1/messages"
    assert req["headers"]["x-api-key"] == "test-anthropic-key"
    assert req["headers"]["anthropic-version"] == "2023-06-01"
    assert req["body"]["model"] == "claude-haiku-5-5"
    assert [t["name"] for t in req["body"]["tools"]] == list(runtime.LIAISON_TOOLS)
    assert "naale 500" in req["body"]["messages"][0]["content"]
    second = script.requests[1]["body"]["messages"]
    results = second[-1]["content"]
    assert [r["type"] for r in results] == ["tool_result", "tool_result"]
    assert json.loads(results[0]["content"])["ok"] is True and results[0]["is_error"] is False
    # agent_run row
    (row,) = agent_runs(db, "liaison")
    assert str(row.id) == out["agent_run_id"] and row.runtime == "local"
    assert row.started_at is not None and row.ended_at is not None
    assert [c["idempotency_key"] for c in row.tool_calls] == ["wamid.A1:0", "wamid.A1:1"]
    assert row.outcome["status"] == "ok"
    assert row.input["wa_message_id"] == "wamid.A1" and "helper_id" not in json.dumps(row.input)


def test_duplicate_lines_are_deduped(fake_tools):
    use = {"employment_id": EMPLOYMENT_ID}
    script = Script(msg(tool_use("get_balances", use), tool_use("get_balances", use)), msg(text("{}")))
    out = liaison("balance?", script)
    assert out["text"].count("Paid leave left") == 1 and len(out["replies"]) == 2


@pytest.mark.parametrize(
    ("code", "template", "status"),
    [
        ("insufficient_funds", "insufficient_funds", "ok"),
        ("leave_exists", "leave_exists", "ok"),
        ("employment_ended", "not_registered", "ok"),
        ("invalid_dates", "not_understood", "not_understood"),
        ("invalid_amount", "not_understood", "not_understood"),
        ("not_found", "not_understood", "not_understood"),
        ("internal_error", "not_understood", "not_understood"),
    ],
)
def test_tool_error_codes_map_to_templates(monkeypatch, code, template, status):
    fake = FakeTools(errors={"record_grocery_spend": code})
    monkeypatch.setattr(
        tools_client, "http_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    )
    args = {"employment_id": EMPLOYMENT_ID, "amount_paise": 30000, "item_note": "vegetables"}
    out = liaison("300 sabzi", Script(msg(tool_use("record_grocery_spend", args)), msg(text('{"clarify": null}'))))
    assert out["status"] == status
    assert out["replies"][0]["template"] == template
    assert out["text"] == runtime.templates.render(template, "en")


def test_no_consent_sends_consent_prompt(monkeypatch):
    fake = FakeTools(errors={"get_balances": "no_consent"})
    monkeypatch.setattr(
        tools_client, "http_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    )
    out = liaison("balance", Script(msg(tool_use("get_balances", {"employment_id": EMPLOYMENT_ID}))))
    assert out["text"].startswith("Namaste Lakshmi! HSR Flat 302 uses Roz Roz")


def test_clarify_path(fake_tools, db):
    out = liaison("advance beku", Script(msg(text('{"clarify": "ಎಷ್ಟು ಹಣ ಬೇಕು?"}'))), lang="kn")
    assert out == {
        "status": "clarify",
        "text": "ಎಷ್ಟು ಹಣ ಬೇಕು?",
        "replies": [],
        "clarify": "ಎಷ್ಟು ಹಣ ಬೇಕು?",
        "agent_run_id": out["agent_run_id"],
    }
    assert fake_tools.calls == []
    assert agent_runs(db, "liaison")[0].outcome["status"] == "clarify"


@pytest.mark.parametrize(
    "final", ["I approved it!", '{"clarify": 5}', json.dumps({"clarify": "x" * 301}), '{"clarify": "  "}', ""]
)
def test_garbage_final_is_not_understood(fake_tools, final):
    out = liaison("hmm", Script(msg(text(final))), lang="hi")
    assert out["status"] == "not_understood"
    assert out["text"] == runtime.templates.TEMPLATES["not_understood"]["hi"]
    assert out["replies"] == [] and out["clarify"] is None


def test_empty_transcript_is_not_understood_without_model(fake_tools, db):
    script = Script()
    out = liaison("   ", script)
    assert out["status"] == "not_understood" and script.requests == []
    assert len(agent_runs(db, "liaison")) == 1


def test_employment_outside_context_and_foreign_tools_are_refused(fake_tools):
    script = Script(
        msg(
            tool_use("create_advance_request", {"employment_id": str(uuid.uuid4()), "amount_paise": 50000}),
            tool_use("execute_request", {"request_id": REQUEST_ID}),
        ),
        msg(text('{"clarify": null}')),
    )
    out = liaison("advance", script)
    assert fake_tools.calls == []
    assert out["status"] == "not_understood"
    results = script.requests[1]["body"]["messages"][-1]["content"]
    assert all(r["is_error"] for r in results)


def test_tool_call_cap_then_tool_choice_none(fake_tools, db):
    use = {"employment_id": EMPLOYMENT_ID}
    script = Script(
        *[msg(tool_use("get_balances", use)) for _ in range(5)],
        msg(tool_use("get_balances", use), tool_use("get_balances", use)),  # 6th allowed, 7th refused
        msg(text('{"clarify": null}')),
    )
    out = liaison("balance", script)
    assert len(fake_tools.calls) == 6
    assert [c["idempotency_key"] for c in fake_tools.calls] == [f"wamid.A1:{i}" for i in range(6)]
    last = script.requests[-1]["body"]
    assert last["tool_choice"] == {"type": "none"}
    refused = last["messages"][-1]["content"][-1]
    assert refused["is_error"] is True and "limit" in refused["content"]
    assert "tool_choice" not in script.requests[0]["body"]
    assert out["status"] == "ok"


def test_model_http_error_without_tools_raises_agent_error(fake_tools, db):
    def boom(request):
        return httpx.Response(500, json={"type": "error"})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as http:
            await run_liaison("advance", HELPER_CONTEXT, MSG_ID, wa_message_id="w", http=http)

    with pytest.raises(AgentError):
        asyncio.run(go())
    assert agent_runs(db, "liaison")[0].outcome["status"] == "error"


def test_model_failure_after_a_tool_still_replies(fake_tools):
    use = {"employment_id": EMPLOYMENT_ID, "amount_paise": 50000}
    steps = [msg(tool_use("create_advance_request", use))]

    def handler(request):
        return httpx.Response(200, json=steps.pop(0)) if steps else httpx.Response(529, json={})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await run_liaison("advance", HELPER_CONTEXT, MSG_ID, wa_message_id="w", http=http)

    out = asyncio.run(go())
    assert out["status"] == "ok" and out["replies"][0]["template"] == "advance_approved"


def test_missing_anthropic_key(monkeypatch, fake_tools):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(AgentError):
        liaison("advance", Script())


# ---- AgenticOrg ----


@pytest.fixture
def agenticorg(monkeypatch):
    monkeypatch.setattr(settings, "agent_runtime", "agenticorg")
    monkeypatch.setattr(settings, "agenticorg_base_url", "https://agenticorg.example/")
    monkeypatch.setattr(settings, "agenticorg_api_key", "test-org-key")
    monkeypatch.setattr(settings, "liaison_agent_id", LIAISON_UUID)
    monkeypatch.setattr(settings, "treasurer_agent_id", TREASURER_UUID)
    monkeypatch.setattr(runtime.agent_settings, "max_retry_after_s", 0.01)


class Org:
    def __init__(self, *responses, on_call=None):
        self.responses, self.requests, self.on_call = list(responses), [], on_call

    def handler(self, request):
        self.requests.append(
            {"url": str(request.url), "headers": dict(request.headers), "body": json.loads(request.content)}
        )
        if self.on_call:
            self.on_call(json.loads(json.loads(request.content)["inputs"]["task"]))
        status, body, headers = self.responses.pop(0)
        return httpx.Response(status, json=body, headers=headers)

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def store(db, key, name):
    db.add(ToolCallRecord(idempotency_key=key, tool=name, response={"ok": True, "result": TOOL_RESULTS[name]}))
    db.commit()


def org_liaison(org, wa="wamid.B2"):
    async def go():
        async with org.client() as http:
            return await run_liaison("advance and balance", HELPER_CONTEXT, MSG_ID, wa_message_id=wa, http=http)

    return asyncio.run(go())


def test_agenticorg_liaison_request_and_recovery(agenticorg, db):
    def agent_side(task):  # what AgenticOrg does: call our tools with the keys we told it
        store(db, "wamid.B2:1", "get_balances")
        store(db, "wamid.B2:0", "create_advance_request")
        store(db, "wamid.B2:x", "record_cash_spend")  # not an integer suffix: ignored
        store(db, "wamid.B22:0", "record_cash_spend")  # another message: ignored
        store(db, "treasurer:abc:0", "execute_request")

    output = 'Done.\n```json\n{"clarify": null}\n```'
    org = Org((200, {"status": "completed", "confidence": 0.93, "output": output}, {}), on_call=agent_side)
    out = org_liaison(org)
    assert [r["template"] for r in out["replies"]] == ["advance_approved", "balances"]
    assert out["text"].startswith("₹500 advance approved.") and out["status"] == "ok"
    (req,) = org.requests
    assert req["url"] == f"https://agenticorg.example/api/v1/agents/{LIAISON_UUID}/run"
    assert req["headers"]["authorization"] == "Bearer test-org-key"
    assert req["body"]["action"] == "process" and req["body"]["context"] == {}
    task = json.loads(req["body"]["inputs"]["task"])
    assert task["transcript"] == "advance and balance" and task["message_id"] == MSG_ID
    assert task["agent_run_id"] == out["agent_run_id"]
    assert "'wamid.B2:<n>'" in task["rules"] and "Roz Roz" in task["instructions"]
    assert HELPER_CONTEXT["helper_id"] not in json.dumps(task)
    (row,) = agent_runs(db, "liaison")
    assert row.runtime == "agenticorg" and row.outcome["confidence"] == 0.93
    assert [c["idempotency_key"] for c in row.tool_calls] == ["wamid.B2:0", "wamid.B2:1"]


def test_agenticorg_clarify_from_dict_output(agenticorg):
    org = Org((200, {"status": "completed", "confidence": 0.5, "output": {"clarify": "Which house?"}}, {}))
    out = org_liaison(org)
    assert out["status"] == "clarify" and out["text"] == "Which house?"


def test_agenticorg_failed_without_tools_raises(agenticorg):
    with pytest.raises(AgentError):
        org_liaison(Org((200, {"status": "failed", "confidence": None, "output": None}, {})))


def test_agenticorg_429_retried_once(agenticorg):
    org = Org(
        (429, {"error": "slow down"}, {"Retry-After": "30"}),
        (200, {"status": "completed", "confidence": 1, "output": '{"clarify": "Kitna?"}'}, {}),
    )
    out = org_liaison(org)
    assert len(org.requests) == 2 and out["text"] == "Kitna?"


def test_agenticorg_429_twice_fails(agenticorg):
    org = Org((429, {}, {}), (429, {}, {}))
    with pytest.raises(AgentError):
        org_liaison(org)
    assert len(org.requests) == 2


def test_agenticorg_agent_id_must_be_uuid(agenticorg, monkeypatch):
    monkeypatch.setattr(settings, "liaison_agent_id", "liaison-agent")
    org = Org()
    with pytest.raises(AgentError):
        org_liaison(org)
    assert org.requests == []


@pytest.mark.parametrize(
    ("org_status", "expected"),
    [("hitl_triggered", "needs_vote"), ("failed", AgentError), ("budget_exceeded", AgentError)],
)
def test_agenticorg_treasurer_status_mapping(agenticorg, monkeypatch, db, org_status, expected):
    org = Org((200, {"status": org_status, "confidence": 0.4, "output": None}, {}))
    monkeypatch.setattr(runtime, "model_http_factory", org.client)
    rid = str(uuid.uuid4())
    if expected is AgentError:
        with pytest.raises(AgentError):
            asyncio.run(run_treasurer(rid))
    else:
        assert asyncio.run(run_treasurer(rid))["status"] == expected
    task = json.loads(org.requests[0]["body"]["inputs"]["task"])
    assert task["request_id"] == rid and f"'treasurer:{rid}:<n>'" in task["rules"]
    assert org.requests[0]["url"].endswith(f"/api/v1/agents/{TREASURER_UUID}/run")
    assert len(agent_runs(db, "treasurer")) == 1


def test_agenticorg_treasurer_completed_uses_tool_records(agenticorg, monkeypatch, db):
    rid = str(uuid.uuid4())

    def agent_side(task):
        store(db, f"treasurer:{rid}:0", "evaluate_request")
        store(db, f"treasurer:{rid}:1", "check_grant")
        store(db, f"treasurer:{rid}:2", "execute_request")

    out = '{"status": "rejected", "summary": "Paid the advance."}'  # model's status is not trusted
    org = Org((200, {"status": "completed", "confidence": 0.9, "output": out}, {}), on_call=agent_side)
    monkeypatch.setattr(runtime, "model_http_factory", org.client)
    res = asyncio.run(run_treasurer(rid))
    assert res["status"] == "executed" and res["summary"] == "Paid the advance."


def test_agenticorg_timeout(agenticorg, monkeypatch):
    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    monkeypatch.setattr(runtime, "model_http_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(slow)))
    with pytest.raises(AgentError):
        asyncio.run(run_treasurer(str(uuid.uuid4())))


# ---- treasurer basics ----


def test_treasurer_off_and_bad_request_id(db):
    with pytest.raises(AgentError):
        asyncio.run(run_treasurer(str(uuid.uuid4())))  # AGENT_RUNTIME=off: the backend handles it
    with pytest.raises(AgentError):
        asyncio.run(run_treasurer("not-a-uuid"))
    assert agent_runs(db) == []


def test_local_treasurer_scripted(monkeypatch, fake_tools, db):
    monkeypatch.setattr(settings, "agent_runtime", "local")
    script = Script(
        msg(tool_use("evaluate_request", {"request_id": REQUEST_ID})),
        msg(tool_use("check_grant", {"request_id": REQUEST_ID})),
        msg(tool_use("execute_request", {"request_id": REQUEST_ID}), tool_use("open_vote", {"request_id": "x"})),
        msg(text('{"status": "executed", "summary": "Auto-approved the advance."}')),
    )
    monkeypatch.setattr(runtime, "model_http_factory", script.client)
    out = asyncio.run(run_treasurer(REQUEST_ID))
    assert out["status"] == "executed" and out["summary"] == "Auto-approved the advance."
    keys = [c["idempotency_key"] for c in fake_tools.calls]
    assert keys == [f"treasurer:{REQUEST_ID}:{i}" for i in range(3)]  # open_vote for another request refused
    assert [t["name"] for t in script.requests[0]["body"]["tools"]] == list(runtime.TREASURER_TOOLS)
    (row,) = agent_runs(db, "treasurer")
    assert row.outcome["status"] == "executed" and len(row.tool_calls) == 4


def test_local_treasurer_without_decision_raises(monkeypatch, fake_tools):
    monkeypatch.setattr(settings, "agent_runtime", "local")
    script = Script(msg(text('{"status": "executed", "summary": "trust me"}')))
    monkeypatch.setattr(runtime, "model_http_factory", script.client)
    with pytest.raises(AgentError):
        asyncio.run(run_treasurer(REQUEST_ID))


# ---- end to end against the real /tools endpoint ----


def test_e2e_liaison_advance(client, db, real_tools):
    flat = Flat(client)
    ctx = tool(client, "get_helper_context", "ctx-1", whatsapp_e164="919811100009")["result"]
    assert ctx["households"][0]["employment_id"] == flat.eid

    def run():
        script = Script(
            msg(tool_use("create_advance_request", {"employment_id": flat.eid, "amount_paise": 50000})),
            msg(text('{"clarify": null}')),
        )
        return liaison("naale aidu nooru advance beku", script, ctx=ctx, wa="wamid.E2E")

    out = run()
    expected = "₹500 advance approved. This month's advances: ₹500. It will be adjusted in your salary."
    assert out["status"] == "ok" and out["text"] == expected
    assert db.get(ToolCallRecord, "wamid.E2E:0").tool == "create_advance_request"
    req = db.scalars(select(Request).where(Request.employment_id == uuid.UUID(flat.eid))).one()
    assert str(req.source_message_id) == MSG_ID
    assert str(req.id) == out["replies"][0]["request_id"]
    # WhatsApp redelivers the same message: same key, stored result, no second advance
    assert run()["text"] == expected
    assert len(db.scalars(select(Request).where(Request.employment_id == uuid.UUID(flat.eid))).all()) == 1


def test_e2e_treasurer_local_inside_tool(client, db, real_tools, monkeypatch):
    """AGENT_RUNTIME=local: the create_advance_request tool runs the treasurer agent (asyncio.run in the route's
    worker thread), whose tool calls go back into the app through ASGITransport."""
    flat = Flat(client)
    monkeypatch.setattr(settings, "agent_runtime", "local")

    def request_id(body):
        return json.loads(body["messages"][0]["content"])["request_id"]

    script = Script(
        lambda b: msg(tool_use("evaluate_request", {"request_id": request_id(b)})),
        lambda b: msg(tool_use("check_grant", {"request_id": request_id(b)})),
        lambda b: msg(tool_use("execute_request", {"request_id": request_id(b)})),
        msg(text('{"status": "executed", "summary": "Auto-approved ₹500."}')),
    )
    monkeypatch.setattr(runtime, "model_http_factory", script.client)
    r = tool(client, "create_advance_request", "e2e-adv", employment_id=flat.eid, amount_paise=50000)
    assert r["ok"], r
    rid = r["result"]["request_id"]
    assert r["result"]["outcome"]["template"] == "advance_approved"
    assert len(script.requests) == 4
    (row,) = agent_runs(db, "treasurer")
    assert row.runtime == "local" and row.outcome["status"] == "executed"
    assert [c["idempotency_key"] for c in row.tool_calls] == [f"treasurer:{rid}:{i}" for i in range(3)]
    db.expire_all()
    assert db.get(Request, uuid.UUID(rid)).status == "executed"
