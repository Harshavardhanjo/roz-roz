"""The voice test set (tests/voice/cases.jsonl) and its runner (tests/voice/run.py). Offline: the model is scripted
through runtime.model_http_factory and the runner fakes the tools itself."""

import json
import uuid
from datetime import date, timedelta

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.agents import runtime, tools_client
from app.config import settings
from app.models import AgentRun
from app.schemas import TOOL_ARGS
from app.stubs import EMPLOYMENT_ID
from app.voice.stt import SUPPORTED_LANGS
from tests.voice import run as runner

TODAY = date(2026, 10, 24)
CASES = runner.load_cases(runner.DEFAULT_CASES)
BY_ID = {c["id"]: c for c in CASES}
PREFIX = {"kn": "kn_", "hi": "hi_", "mixed": "mx_"}


# ---- cases.jsonl ----


def test_case_counts_and_ids():
    assert len(CASES) == 30
    groups = [c.get("group") for c in CASES]
    assert (groups.count("kn"), groups.count("hi"), groups.count("mixed")) == (12, 12, 6)
    assert len(BY_ID) == 30, "duplicate ids"
    for c in CASES:
        assert c["id"].startswith(PREFIX[c["group"]]), c["id"]
        assert c["audio"] == f"tests/voice/{c['id']}.ogg", c["id"]
        assert c["lang"] in SUPPORTED_LANGS, c["id"]
        if c["group"] in ("kn", "hi"):
            assert c["lang"] == c["group"], c["id"]
        assert c["say"].strip() and isinstance(c["expect"], list), c["id"]


def test_case_set_covers_the_spec():
    expects = [c["expect"] for c in CASES]
    tools = {e["tool"] for ex in expects for e in ex}
    assert tools == set(runtime.LIAISON_TOOLS)
    assert sum(1 for ex in expects if not ex) >= 1, "needs an ambiguous clarify case"
    assert sum(1 for ex in expects if len(ex) >= 2) >= 3, "needs several two-request messages"
    assert any(e["args"].get("half_day") for ex in expects for e in ex)
    assert BY_ID["kn_01"]["expect"] == [
        {"tool": "create_leave_request", "args": {"leave_from": "2026-10-26", "leave_to": "2026-10-26"}},
        {"tool": "create_advance_request", "args": {"amount_paise": 50000}},
    ]


FILLER = {"employment_id": EMPLOYMENT_ID, "item_note": "vegetables"}


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case_expectations_are_valid_tool_args(case):
    for e in case["expect"]:
        assert set(e) == {"tool", "args"}
        assert e["tool"] in runtime.LIAISON_TOOLS
        model = TOOL_ARGS[e["tool"]]
        args = e["args"]
        assert set(args) <= set(model.model_fields), f"unknown arg in {e}"
        assert "employment_id" not in args and "source_message_id" not in args
        required = {k: v for k, v in FILLER.items() if k in model.model_fields}
        try:
            model.model_validate(required | args)
        except ValidationError as err:  # pragma: no cover - the message is the point
            pytest.fail(f"{case['id']} {e['tool']}: {err}")
        if "amount_paise" in args:
            amount = args["amount_paise"]
            assert isinstance(amount, int) and not isinstance(amount, bool) and amount > 0
            assert amount % 100 == 0, "whole rupees"
        if e["tool"] == "create_leave_request":
            start, end = date.fromisoformat(args["leave_from"]), date.fromisoformat(args["leave_to"])
            assert TODAY <= start <= end <= TODAY + timedelta(days=60)
        elif e["tool"] != "get_balances":
            assert "amount_paise" in args


def test_weekday_dates_match_today():
    """Spot-check the calendar the expectations rely on: 2026-10-24 is a Saturday."""
    assert TODAY.weekday() == 5
    leave = {
        c["id"]: c["expect"][0]["args"] for c in CASES if c["expect"][:1] and "leave_from" in c["expect"][0]["args"]
    }
    assert date.fromisoformat(leave["kn_04"]["leave_from"]).strftime("%A") == "Wednesday"  # Budhavara
    assert date.fromisoformat(leave["hi_09"]["leave_from"]).strftime("%A") == "Tuesday"  # Mangalvaar
    assert date.fromisoformat(leave["hi_10"]["leave_to"]).strftime("%A") == "Wednesday"  # Budhvaar
    assert leave["kn_02"]["leave_from"] == "2026-10-25"  # naale


# ---- comparison ----


def call(tool, **args):
    return {"tool": tool, "args": {"employment_id": EMPLOYMENT_ID} | args}


LEAVE = {"tool": "create_leave_request", "args": {"leave_from": "2026-10-26", "leave_to": "2026-10-26"}}
ADVANCE = {"tool": "create_advance_request", "args": {"amount_paise": 50000}}


def test_compare_passes_in_any_order_and_ignores_extra_args():
    calls = [
        call("create_advance_request", amount_paise=50000, note="advance"),
        call("create_leave_request", leave_from="2026-10-26", leave_to="2026-10-26", half_day=False),
    ]
    assert runner.compare([LEAVE, ADVANCE], calls, None) == (True, "")


def test_compare_tool_multiset():
    ok, why = runner.compare([LEAVE, ADVANCE], [call("create_advance_request", amount_paise=50000)], None)
    assert not ok and why == "missing create_leave_request"
    calls = [call("create_advance_request", amount_paise=50000), call("get_balances")]
    ok, why = runner.compare([ADVANCE], calls, None)
    assert not ok and why == "unexpected get_balances"
    ok, why = runner.compare([ADVANCE], [call("create_advance_request", amount_paise=50000)] * 2, None)
    assert not ok and why == "unexpected create_advance_request"


def test_compare_reports_wrong_args():
    calls = [call("create_leave_request", leave_from="2026-10-27", leave_to="2026-10-27")]
    ok, why = runner.compare([LEAVE], calls, None)
    assert not ok
    assert why == "leave leave_from: want 2026-10-26, got 2026-10-27; leave_to: want 2026-10-26, got 2026-10-27"
    ok, why = runner.compare([ADVANCE], [call("create_advance_request", amount_paise=500)], None)
    assert not ok and why == "advance amount_paise: want 50000, got 500"
    half = {"tool": "create_leave_request", "args": {**LEAVE["args"], "half_day": True}}
    ok, why = runner.compare(
        [half], [call("create_leave_request", leave_from="2026-10-26", leave_to="2026-10-26")], None
    )
    assert not ok and "half_day: want True, missing" in why


def test_compare_value_coercion():
    assert runner.values_equal(50000, "50000") and runner.values_equal(50000, 50000.0)
    assert not runner.values_equal(50000, 50000.5) and not runner.values_equal(50000, "abc")
    assert runner.values_equal(True, "true") and not runner.values_equal(True, 1)
    assert runner.values_equal("2026-10-26", "2026-10-26")


def test_compare_matches_duplicates_by_args():
    """Two calls of the same tool: each expectation needs its own matching call (backtracking, not greedy)."""
    first = {"tool": "create_leave_request", "args": {"leave_from": "2026-10-26"}}
    second = {"tool": "create_leave_request", "args": {"leave_from": "2026-10-26", "leave_to": "2026-10-27"}}
    calls = [
        call("create_leave_request", leave_from="2026-10-26", leave_to="2026-10-27"),
        call("create_leave_request", leave_from="2026-10-26", leave_to="2026-10-26"),
    ]
    assert runner.compare([first, second], calls, None)[0]
    calls[1] = call("create_leave_request", leave_from="2026-10-28", leave_to="2026-10-28")
    assert not runner.compare([first, second], calls, None)[0]


def test_compare_clarify_cases():
    assert runner.compare([], [], "Eshtu advance beku?") == (True, "asked: Eshtu advance beku?")
    assert runner.compare([], [], None) == (False, "expected a clarify question, got none")
    ok, why = runner.compare([], [call("get_balances")], "Eshtu?")
    assert not ok and why == "expected a clarify question, got tools: get_balances"


def test_compare_names_only_when_args_not_observable():
    ok, why = runner.compare([ADVANCE], [{"tool": "create_advance_request", "args": None}], None)
    assert ok and "not observable" in why


def test_targets_and_percentile():
    assert runner.pass_target(30) == 26 and runner.pass_target(2) == 2 and runner.pass_target(1) == 1
    assert runner.percentile([], 90) is None
    assert runner.percentile(list(range(1, 11)), 90) == 9
    assert runner.percentile([5], 90) == 5


# ---- end to end (scripted model, fake tools) ----


def tool_use(name, inp):
    return {"type": "tool_use", "id": f"tu_{uuid.uuid4().hex[:8]}", "name": name, "input": inp}


def message(*blocks):
    return {"id": "msg", "type": "message", "role": "assistant", "content": list(blocks), "stop_reason": "end_turn"}


class ScriptedModel:
    """Anthropic Messages API stand-in: on the transcript, answer with `plan[say]` (tool_use blocks or a clarify
    question); after tool results, finish with {"clarify": null}."""

    def __init__(self, plan):
        self.plan, self.requests = plan, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        if len(body["messages"]) == 1:
            transcript = json.loads(body["messages"][0]["content"])["transcript"]
            step = self.plan[transcript]
            if isinstance(step, str):
                return httpx.Response(200, json=message({"type": "text", "text": json.dumps({"clarify": step})}))
            blocks = [tool_use(name, {"employment_id": EMPLOYMENT_ID} | args) for name, args in step]
            return httpx.Response(200, json=message(*blocks))
        return httpx.Response(200, json=message({"type": "text", "text": '{"clarify": null}'}))

    def factory(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def plan_from_expect(*ids, **overrides):
    plan = {}
    for cid in ids:
        case = BY_ID[cid]
        steps = []
        for e in case["expect"]:
            args = dict(e["args"])
            if e["tool"] in ("record_grocery_spend", "record_cash_spend"):
                args["item_note"] = "vegetables"
            steps.append((e["tool"], args))
        plan[case["say"]] = overrides.get(cid, steps or "Eshtu advance beku?")
    return plan


@pytest.fixture
def model(monkeypatch):
    def install(plan):
        scripted = ScriptedModel(plan)
        monkeypatch.setattr(runtime, "model_http_factory", scripted.factory)
        return scripted

    monkeypatch.setattr(settings, "anthropic_api_key", "test-anthropic-key")
    monkeypatch.setattr(settings, "agent_runtime", "off")
    return install


def test_runner_end_to_end_text_only(model, tmp_path, capsys, db):
    scripted = model(plan_from_expect("kn_01", "kn_12"))
    factory_before, today_before = tools_client.http_factory, settings.today_override
    report = tmp_path / "report.json"

    code = runner.main(["--text-only", "--only", "kn_01,kn_12", "--report", str(report)])

    out = capsys.readouterr().out
    assert code == 0, out
    lines = {line.split()[0]: line for line in out.splitlines() if line[:3] in ("kn_", "hi_", "mx_")}
    assert "PASS" in lines["kn_01"] and "leave,advance" in lines["kn_01"] and "text-only" in lines["kn_01"]
    assert "PASS" in lines["kn_12"] and "(clarify)" in lines["kn_12"]
    assert "Passed 2/2 (100.0%)  [kn 2/2]" in out
    assert "Pass target >= 2/2: MET" in out
    assert "target p90 < 10000: MET" in out
    assert "ran text-only" in out

    # the model saw the pinned date; tool calls carried the case's idempotency keys and never hit a real backend
    assert "Today is 2026-10-24 (Saturday)" in scripted.requests[0]["system"]
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["summary"]["passed"] == 2 and data["today"] == "2026-10-24" and data["agent_run_rows"] is True
    first = data["cases"][0]
    assert [c["tool"] for c in first["calls"]] == ["create_leave_request", "create_advance_request"]
    assert first["calls"][1]["args"]["amount_paise"] == 50000
    assert first["latency_ms"]["liaison"] is not None and first["latency_ms"]["stt"] is None
    assert data["cases"][1]["status"] == "clarify" and data["cases"][1]["calls"] == []

    # patches are undone; the reachable test database got one agent_run row per case
    assert tools_client.http_factory is factory_before and settings.today_override == today_before
    assert runtime._finish_run.__module__ == "app.agents.runtime"
    rows = db.scalars(select(AgentRun)).all()
    assert len(rows) == 2 and {r.input["wa_message_id"] for r in rows} == {"testset-kn_01", "testset-kn_12"}


def test_runner_reports_failures_and_exit_code(model, tmp_path, capsys, db):
    wrong = [("create_leave_request", {"leave_from": "2026-10-27", "leave_to": "2026-10-27"})]
    model(plan_from_expect("hi_09", "hi_03", hi_03=[("create_advance_request", {"amount_paise": 500})], hi_09=wrong))

    code = runner.main(["--text-only", "--only", "hi_09", "--only", "hi_03", "--report", str(tmp_path / "r.json")])

    out = capsys.readouterr().out
    assert code == 1
    assert "why: advance amount_paise: want 50000, got 500" in out
    assert "why: leave half_day: want True, missing" in out
    assert "Passed 0/2 (0.0%)" in out and "Pass target >= 2/2: NOT MET" in out
    assert db.scalars(select(AgentRun)).all() != []


def test_runner_no_db_skips_agent_run_rows(model, tmp_path, capsys, db):
    model(plan_from_expect("hi_08"))
    code = runner.main(["--text-only", "--only", "hi_08", "--no-db", "--report", str(tmp_path / "r.json")])
    assert code == 0, capsys.readouterr().out
    assert db.scalars(select(AgentRun)).all() == []


def test_runner_fails_fast_without_keys(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "agent_runtime", "off")
    code = runner.main(["--text-only", "--report", str(tmp_path / "r.json")])
    err = capsys.readouterr().err
    assert code == 2
    assert err.startswith("error: ANTHROPIC_API_KEY is not set") and "Traceback" not in err
    assert not (tmp_path / "r.json").exists()


def test_runner_refuses_agenticorg_without_opt_in(monkeypatch, capsys):
    monkeypatch.setattr(settings, "agent_runtime", "agenticorg")
    for name in ("agenticorg_base_url", "agenticorg_api_key", "liaison_agent_id"):
        monkeypatch.setattr(settings, name, "x")
    assert runner.main(["--text-only", "--only", "kn_01"]) == 2
    assert "--allow-live-tools" in capsys.readouterr().err


def test_runner_needs_stt_key_only_for_recorded_clips(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "agent_runtime", "off")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    clip = tmp_path / "kn_01.ogg"
    clip.write_bytes(b"OggS")
    case = dict(BY_ID["kn_01"], audio=str(clip))
    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps(case) + "\n", encoding="utf-8")
    assert runner.main(["--cases", str(cases)]) == 2
    assert "ELEVENLABS_API_KEY is not set" in capsys.readouterr().err
    runner.check_config([case], text_only=True, allow_live_tools=False)  # text-only needs no STT key


def test_runner_rejects_bad_cases_file(tmp_path, capsys):
    bad = tmp_path / "cases.jsonl"
    bad.write_text('{"id": "x"}\n', encoding="utf-8")
    assert runner.main(["--cases", str(bad)]) == 2
    assert "cases.jsonl:1: missing audio, lang, say, expect" in capsys.readouterr().err
    assert runner.main(["--only", "nope"]) == 2
    assert "unknown case id(s): nope" in capsys.readouterr().err
