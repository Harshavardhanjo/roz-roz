"""Run the voice test set: real STT + real liaison agent, fake tools.

    python -m tests.voice.run [--cases PATH] [--text-only] [--only ID[,ID...]] [--report PATH] [--no-db]

For each case in cases.jsonl: transcribe the clip with app.voice.stt.transcribe (when the file exists and --text-only is
not given; otherwise the case's `say` text is the transcript), then run app.agents.runtime.run_liaison on it. Tool
calls go to a recording httpx.MockTransport installed as tools_client.http_factory, which answers with the stub results
(app/stubs.py), so nothing touches the backend or moves money. "Today" is pinned to 2026-10-24, the date the expected
arguments were written for. The agent_run audit row is written only when DATABASE_URL is reachable (and not --no-db).

Exit codes: 0 pass target met, 1 not met, 2 configuration problem (missing keys, bad cases file).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import statistics
import sys
import threading
import time
import uuid
from collections import Counter
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app import stubs
from app.agents import runtime, tools_client
from app.agents.agent_config import agent_settings
from app.config import settings

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_CASES = HERE / "cases.jsonl"
DEFAULT_REPORT = HERE / "last_run.json"

TEST_TODAY = "2026-10-24"  # the expected dates in cases.jsonl are relative to this Saturday
TARGET_PASS, TARGET_OF = 26, 30
TARGET_TOTAL_MS = 10_000
LIAISON_TOOLS = frozenset(runtime.LIAISON_TOOLS)
GROUPS = ("kn", "hi", "mixed")
MIME_BY_EXT = {
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
}
SHORT = {
    "create_leave_request": "leave",
    "create_advance_request": "advance",
    "create_grocery_request": "grocery_req",
    "record_grocery_spend": "grocery_spend",
    "record_cash_spend": "cash_spend",
    "get_balances": "balances",
}
MESSAGE_NS = uuid.UUID("5e1f0000-0000-4000-8000-00000000c0de")


class ConfigError(Exception):
    """Something the person running the test set has to fix (keys, cases file). Printed without a traceback."""


# ---- cases ----


def load_cases(path: Path) -> list[dict]:
    if not path.is_file():
        raise ConfigError(f"cases file not found: {path}")
    cases = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except ValueError as e:
            raise ConfigError(f"{path.name}:{n}: not JSON ({e})") from e
        missing = [k for k in ("id", "audio", "lang", "say", "expect") if k not in case]
        if missing:
            raise ConfigError(f"{path.name}:{n}: missing {', '.join(missing)}")
        cases.append(case)
    return cases


def select_cases(cases: list[dict], only: list[str] | None) -> list[dict]:
    if not only:
        return cases
    by_id = {c["id"]: c for c in cases}
    unknown = [i for i in only if i not in by_id]
    if unknown:
        raise ConfigError(f"unknown case id(s): {', '.join(unknown)}")
    return [by_id[i] for i in only]


# ---- comparison ----


def values_equal(want: Any, got: Any) -> bool:
    if type(want) is type(got):
        return want == got
    if isinstance(want, int) and not isinstance(want, bool):
        try:
            f = float(got)
        except (TypeError, ValueError):
            return False
        return f.is_integer() and int(f) == want
    return str(want).strip().lower() == str(got).strip().lower()


def arg_diffs(want: dict, got: dict | None) -> list[str]:
    """Expected args the call does not match ('half_day: want True, got False'). None args = not observable."""
    if got is None:
        return []
    out = []
    for key, value in (want or {}).items():
        if key not in got:
            out.append(f"{key}: want {value}, missing")
        elif not values_equal(value, got[key]):
            out.append(f"{key}: want {value}, got {got[key]}")
    return out


def _assign(expect: list[dict], calls: list[dict], used: set[int]) -> bool:
    if not expect:
        return True
    first, rest = expect[0], expect[1:]
    for i, call in enumerate(calls):
        if i in used or call["tool"] != first["tool"] or arg_diffs(first.get("args") or {}, call.get("args")):
            continue
        if _assign(rest, calls, used | {i}):
            return True
    return False


def compare(expect: list[dict], calls: list[dict], clarify: str | None) -> tuple[bool, str]:
    """(passed, why). calls: [{"tool", "args"}] that reached the tools endpoint, in order."""
    names = [c["tool"] for c in calls]
    if not expect:
        if names:
            return False, f"expected a clarify question, got tools: {', '.join(names)}"
        if not clarify:
            return False, "expected a clarify question, got none"
        return True, "asked: " + clarify
    want, got = Counter(e["tool"] for e in expect), Counter(names)
    if want != got:
        parts = []
        if missing := want - got:
            parts.append("missing " + ", ".join(sorted(missing.elements())))
        if extra := got - want:
            parts.append("unexpected " + ", ".join(sorted(extra.elements())))
        return False, "; ".join(parts)
    if _assign(expect, calls, set()):
        note = " (args not observable on this runtime)" if any(c.get("args") is None for c in calls) else ""
        return True, note.strip()
    problems = []
    for e in expect:
        same = [c for c in calls if c["tool"] == e["tool"]]
        diffs = [arg_diffs(e.get("args") or {}, c.get("args")) for c in same]
        if all(diffs):
            problems.append(f"{SHORT.get(e['tool'], e['tool'])} " + "; ".join(min(diffs, key=len)))
    return False, " | ".join(problems) or "args do not match"


# ---- fakes and patches ----


class RecordingTools:
    """Fake POST /tools/{name}: records the body, answers with the stub result for that tool."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        if request.method != "POST" or "/tools/" not in request.url.path or name not in stubs.TOOL_RESULTS:
            return httpx.Response(404, json={"ok": False, "error": {"code": "not_found", "message": name}})
        body = json.loads(request.content or b"{}")
        key = body.get("idempotency_key")
        self.calls.append({"tool": name, "args": body.get("args") or {}, "idempotency_key": key})
        return httpx.Response(200, json={"ok": True, "result": stubs.TOOL_RESULTS[name]})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


@contextmanager
def _setattr(obj: Any, name: str, value: Any) -> Iterator[None]:
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


def db_reachable(timeout_s: float = 3.0) -> bool:
    """True when DATABASE_URL answers and has the agent_run table. Runs in a daemon thread so a dead host can't hang."""
    from sqlalchemy import text

    from app.db import engine

    result: dict[str, bool] = {}

    def probe() -> None:
        try:
            with engine.connect() as conn:
                conn.execute(text("select 1 from agent_run limit 1"))
            result["ok"] = True
        except Exception:  # noqa: BLE001 - any failure means "no database"
            result["ok"] = False

    thread = threading.Thread(target=probe, daemon=True)
    thread.start()
    thread.join(timeout_s)
    return result.get("ok", False)


# ---- running ----


def runtime_name() -> str:
    return "agenticorg" if settings.agent_runtime == "agenticorg" else "local"


def check_config(cases: list[dict], text_only: bool, allow_live_tools: bool) -> None:
    problems = []
    if runtime_name() == "local":
        if not settings.anthropic_api_key:
            problems.append("ANTHROPIC_API_KEY is not set (environment or .env): the liaison runs the real model.")
    else:
        if not (settings.agenticorg_base_url and settings.agenticorg_api_key and settings.liaison_agent_id):
            problems.append("AGENT_RUNTIME=agenticorg needs AGENTICORG_BASE_URL, AGENTICORG_API_KEY, LIAISON_AGENT_ID.")
        if not allow_live_tools:
            problems.append(
                "AGENT_RUNTIME=agenticorg: AgenticOrg calls the real /tools endpoint itself, so the tool fake cannot "
                "intercept it. Re-run with --allow-live-tools against a test backend, or unset AGENT_RUNTIME."
            )
    if not text_only and any(audio_path(c).is_file() for c in cases):
        from app.voice.voice_config import voice_settings

        if not settings.elevenlabs_api_key:
            problems.append("ELEVENLABS_API_KEY is not set but audio clips exist. Set it, or run with --text-only.")
        if voice_settings.stt_provider_kn == "sarvam" and not voice_settings.sarvam_api_key:
            problems.append("STT_PROVIDER_KN=sarvam needs SARVAM_API_KEY (or run with --text-only).")
    if problems:
        raise ConfigError("\n".join(problems))


def audio_path(case: dict) -> Path:
    p = Path(case["audio"])
    return p if p.is_absolute() else REPO / p


def _is_auth_error(error: Exception) -> bool:
    msg = str(error)
    return any(s in msg for s in ("HTTP 401", "HTTP 403", "http 401", "http 403"))


async def run_case(case: dict, tools: RecordingTools, captured: dict, text_only: bool, nonce: str) -> dict:
    from app.voice import stt

    cid = case["id"]
    out: dict[str, Any] = {
        "id": cid,
        "group": case.get("group"),
        "lang": case["lang"],
        "audio": case["audio"],
        "say": case["say"],
        "expect": case["expect"],
        "calls": [],
        "rejected": [],
        "status": None,
        "clarify": None,
        "reply_text": None,
        "pass": False,
        "why": "",
        "latency_ms": {"stt": None, "liaison": None, "total": None},
    }
    start = time.perf_counter()
    path = audio_path(case)
    if text_only or not path.is_file():
        out["mode"] = "text-only"
        transcript = case["say"]
    else:
        out["mode"] = "audio"
        mime = MIME_BY_EXT.get(path.suffix.lower(), "audio/ogg")
        hint = case["lang"] if case["lang"] in stt.SUPPORTED_LANGS else None
        t0 = time.perf_counter()
        try:
            result = await stt.transcribe(path.read_bytes(), mime, hint)
        except (stt.STTError, stt.InvalidAudio) as e:
            out["latency_ms"]["stt"] = _ms(t0)
            out["latency_ms"]["total"] = _ms(start)
            if _is_auth_error(e):
                raise ConfigError(f"speech-to-text key was rejected: {e}") from e
            out["why"] = f"stt failed: {e}"
            return out
        out["latency_ms"]["stt"] = _ms(t0)
        out["stt_language"] = result.language_code
        transcript = result.text
    out["transcript"] = transcript

    first_call = len(tools.calls)
    wa_id = f"testset-{cid}" if runtime_name() == "local" else f"testset-{cid}-{nonce}"
    t1 = time.perf_counter()
    try:
        reply = await runtime.run_liaison(
            transcript,
            stubs.HELPER_CONTEXT,
            str(uuid.uuid5(MESSAGE_NS, cid)),
            wa_message_id=wa_id,
            lang=case["lang"],
        )
    except runtime.AgentError as e:
        out["latency_ms"]["liaison"] = _ms(t1)
        out["latency_ms"]["total"] = _ms(start)
        if _is_auth_error(e):
            raise ConfigError(f"the agent's API key was rejected: {e}") from e
        out["why"] = f"agent error: {e}"
        return out
    out["latency_ms"]["liaison"] = _ms(t1)
    out["latency_ms"]["total"] = _ms(start)

    summary = captured.pop(reply.get("agent_run_id"), [])
    if runtime_name() == "local":
        out["calls"] = [{"tool": c["tool"], "args": c["args"]} for c in tools.calls[first_call:]]
    else:  # AgenticOrg called /tools itself; only names and outcomes are known
        out["calls"] = [{"tool": c["name"], "args": c.get("args")} for c in summary if c.get("ok")]
    out["rejected"] = [{"tool": c["name"], "error": c.get("error")} for c in summary if not c.get("ok")]
    out.update(status=reply.get("status"), clarify=reply.get("clarify"), reply_text=reply.get("text"))
    out["pass"], out["why"] = compare(case["expect"], out["calls"], reply.get("clarify"))
    if not out["pass"] and out["rejected"]:
        out["why"] += " [rejected: " + ", ".join(f"{r['tool']} ({r['error']})" for r in out["rejected"]) + "]"
    return out


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


async def run_all(cases: list[dict], text_only: bool, use_db: bool) -> list[dict]:
    tools = RecordingTools()
    captured: dict[str, list] = {}
    original_finish = runtime._finish_run

    def insert_run(run_id, agent, input_, runtime_):  # agent_run writer, no database
        return None

    def finish_run(run_id, tool_calls, outcome):
        captured[run_id] = tool_calls
        if use_db:
            original_finish(run_id, tool_calls, outcome)

    nonce = uuid.uuid4().hex[:8]
    results = []
    with ExitStack() as stack:
        stack.enter_context(_setattr(tools_client, "http_factory", tools.client))
        stack.enter_context(_setattr(runtime, "_finish_run", finish_run))
        stack.enter_context(_setattr(settings, "today_override", TEST_TODAY))
        if not use_db:
            stack.enter_context(_setattr(runtime, "_insert_run", insert_run))
        for case in cases:
            results.append(await run_case(case, tools, captured, text_only, nonce))
    return results


# ---- reporting ----


def _cut(text: str | None, width: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= width else text[: width - 1] + "~"


def percentile(values: list[int], p: float) -> int | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def pass_target(n: int) -> int:
    """26 of 30, scaled for a subset run (--only)."""
    return TARGET_PASS if n == TARGET_OF else math.ceil(n * TARGET_PASS / TARGET_OF)


def _by_group(results: list[dict]) -> dict[str, str]:
    out = {}
    for g in GROUPS:
        group = [r for r in results if r["group"] == g]
        if group:
            out[g] = f"{sum(1 for r in group if r['pass'])}/{len(group)}"
    return out


def summarise(results: list[dict]) -> dict:
    n = len(results)
    passed = sum(1 for r in results if r["pass"])
    totals = [r["latency_ms"]["total"] for r in results if r["latency_ms"]["total"] is not None]
    p90 = percentile(totals, 90)
    target = pass_target(n)
    return {
        "cases": n,
        "passed": passed,
        "pass_rate_pct": round(100 * passed / n, 1) if n else 0.0,
        "pass_target": target,
        "pass_target_met": passed >= target,
        "total_ms_median": int(statistics.median(totals)) if totals else None,
        "total_ms_p90": p90,
        "total_ms_max": max(totals) if totals else None,
        "latency_target_ms": TARGET_TOTAL_MS,
        "latency_target_met": p90 is not None and p90 < TARGET_TOTAL_MS,
        "text_only_cases": sum(1 for r in results if r.get("mode") == "text-only"),
        "by_group": _by_group(results),
    }


def _num(v: int | None) -> str:
    return "-" if v is None else str(v)


def print_report(results: list[dict], summary: dict, out=None) -> None:
    out = out or sys.stdout
    row = "{:<6} {:<4} {:<9} {:<38} {:<28} {:<4} {:>6} {:>7} {:>6}"
    print(row.format("id", "lang", "mode", "transcript", "tools called", "res", "stt", "liaison", "total"), file=out)
    print("-" * 115, file=out)
    for r in results:
        tools = ",".join(SHORT.get(c["tool"], c["tool"]) for c in r["calls"]) or ("(clarify)" if r["clarify"] else "-")
        lat = r["latency_ms"]
        print(
            row.format(
                r["id"],
                r["lang"],
                r["mode"],
                _cut(r.get("transcript"), 38),
                _cut(tools, 28),
                "PASS" if r["pass"] else "FAIL",
                _num(lat["stt"]),
                _num(lat["liaison"]),
                _num(lat["total"]),
            ),
            file=out,
        )
        if not r["pass"] and r["why"]:
            print(f"       why: {r['why']}", file=out)
    s = summary
    met = {True: "MET", False: "NOT MET"}
    print("-" * 115, file=out)
    groups = "  ".join(f"{g} {v}" for g, v in s["by_group"].items())
    print(f"Passed {s['passed']}/{s['cases']} ({s['pass_rate_pct']}%)  [{groups}]", file=out)
    print(f"Pass target >= {s['pass_target']}/{s['cases']}: {met[s['pass_target_met']]}", file=out)
    print(
        f"Total latency ms: median {_num(s['total_ms_median'])}, p90 {_num(s['total_ms_p90'])}, "
        f"max {_num(s['total_ms_max'])}  target p90 < {s['latency_target_ms']}: {met[s['latency_target_met']]}",
        file=out,
    )
    if s["text_only_cases"]:
        print(f"Note: {s['text_only_cases']} case(s) ran text-only; their total excludes speech-to-text.", file=out)


def write_report(path: Path, results: list[dict], summary: dict, args: argparse.Namespace, use_db: bool) -> None:
    report = {
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "today": TEST_TODAY,
        "runtime": runtime_name(),
        "model": agent_settings.local_agent_model if runtime_name() == "local" else settings.liaison_agent_id,
        "cases_file": str(args.cases),
        "text_only": args.text_only,
        "agent_run_rows": use_db,
        "summary": summary,
        "cases": results,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m tests.voice.run", description="Run the Roz Roz voice test set.")
    p.add_argument("--cases", type=Path, default=DEFAULT_CASES, help="cases file (JSONL)")
    p.add_argument("--text-only", action="store_true", help="skip speech-to-text; use each case's `say` text")
    p.add_argument("--only", action="append", help="case id(s) to run; repeat or comma-separate")
    p.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="JSON report path")
    p.add_argument("--no-db", action="store_true", help="never write agent_run rows, even if DATABASE_URL answers")
    p.add_argument("--allow-live-tools", action="store_true", help="allow AGENT_RUNTIME=agenticorg (real /tools)")
    args = p.parse_args(argv)
    args.only = [i.strip() for chunk in args.only or [] for i in chunk.split(",") if i.strip()] or None
    return args


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    try:
        cases = select_cases(load_cases(args.cases), args.only)
        check_config(cases, args.text_only, args.allow_live_tools)
        use_db = not args.no_db and db_reachable()
        if runtime_name() == "agenticorg" and not use_db:
            raise ConfigError("AGENT_RUNTIME=agenticorg reads tool calls back from the database; DATABASE_URL is down.")
        mode = "text-only" if args.text_only else "audio where recorded"
        db_note = "agent_run rows written" if use_db else "no database: agent_run rows skipped"
        print(f"Voice test set: {len(cases)} case(s), {runtime_name()} runtime, {mode}, today {TEST_TODAY}, {db_note}")
        results = asyncio.run(run_all(cases, args.text_only, use_db))
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    summary = summarise(results)
    print_report(results, summary)
    write_report(args.report, results, summary, args, use_db)
    print(f"Report: {args.report}")
    return 0 if summary["pass_target_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
