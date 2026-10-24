"""Voice pipeline against the real message table (fakes for STT, WhatsApp, the liaison agent and, mostly, the tools)."""

import asyncio
import logging
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.agents import runtime, tools_client
from app.main import create_app
from app.models import Employment, Helper, Message
from app.voice import pipeline as pipeline_mod
from app.voice.pipeline import InboundMessage, Pipeline, Timer, build_default_pipeline, is_consent_yes
from app.voice.store import PgMessageStore
from app.voice.stt import InvalidAudio, STTError
from app.voice.whatsapp_client import MediaTooLarge

DIGITS = "919876543210"
PHONE = "+" + DIGITS
HH1, HH2 = str(uuid.uuid4()), str(uuid.uuid4())
EMP1, EMP2 = str(uuid.uuid4()), str(uuid.uuid4())
RUN_ID = str(uuid.uuid4())
REPLY = "Sari, naale raja haaktini."


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def helper_id(db):
    h = Helper(name="Lakshmi Devi", whatsapp_e164=PHONE, lang="kn")
    db.add(h)
    db.commit()
    return str(h.id)


def make_ctx(helper_id, consented=(True, True), lang="kn"):
    households = [
        {"household_id": HH1, "name": "Flat 4B", "employment_id": EMP1, "consented": consented[0]},
        {"household_id": HH2, "name": "Flat 7C", "employment_id": EMP2, "consented": consented[1]},
    ]
    return {
        "known": True,
        "helper_id": helper_id,
        "name": "Lakshmi Devi",
        "lang": lang,
        "consented": all(consented),
        "households": households,
    }


class FakeTranscript:
    def __init__(self, text, language_code="kn"):
        self.text, self.language_code = text, language_code


class FakeWA:
    def __init__(self, audio=b"OggS-fake", mime="audio/ogg", download_exc=None, send_exc=None):
        self.sent, self.downloads = [], []
        self.audio, self.mime, self.download_exc, self.send_exc = audio, mime, download_exc, send_exc

    async def send_text(self, to_e164, body):
        if self.send_exc:
            raise self.send_exc
        self.sent.append((to_e164, body))
        return "wamid.out"

    async def download_media(self, media_ref):
        self.downloads.append(media_ref)
        if self.download_exc:
            raise self.download_exc
        return self.audio, self.mime


class Fakes:
    def __init__(
        self,
        ctx_body=None,
        *,
        transcript="naale raja beku",
        stt_exc=None,
        agent_exc=None,
        agent_text=REPLY,
        tools_exc=None,
        wa=None,
    ):
        self.ctx_body = ctx_body
        self.tools_calls, self.transcribe_calls, self.liaison_calls = [], [], []
        self.transcript, self.stt_exc = transcript, stt_exc
        self.agent_exc, self.agent_text, self.tools_exc = agent_exc, agent_text, tools_exc
        self.wa = wa or FakeWA()

    async def tools_call(self, name, args, key):
        self.tools_calls.append((name, args, key))
        if self.tools_exc:
            raise self.tools_exc
        if name == "get_helper_context":
            return self.ctx_body
        return {"ok": True, "result": {"consent_at": "2026-10-24T13:30:00+05:30"}}

    async def transcribe(self, audio, mime, lang_hint):
        self.transcribe_calls.append((audio, mime, lang_hint))
        if self.stt_exc:
            raise self.stt_exc
        return FakeTranscript(self.transcript)

    async def run_liaison(self, text, ctx, *, message_id, wa_message_id, lang):
        self.liaison_calls.append(
            {"text": text, "ctx": ctx, "message_id": message_id, "wa": wa_message_id, "lang": lang}
        )
        if self.agent_exc:
            raise self.agent_exc
        return {"status": "ok", "text": self.agent_text, "replies": [], "clarify": None, "agent_run_id": RUN_ID}

    @staticmethod
    def render(key, lang, **slots):
        return f"[{key}:{lang}]" + ",".join(f"{k}={v}" for k, v in sorted(slots.items()))

    def pipeline(self, render=None) -> Pipeline:
        return Pipeline(
            tools_call=self.tools_call,
            run_liaison=self.run_liaison,
            render=render or self.render,
            transcribe=self.transcribe,
            wa=self.wa,
            store=PgMessageStore(),
        )


def ok(result):
    return {"ok": True, "result": result}


def audio_msg(wa_id="wamid.A1"):
    return InboundMessage(wa_id, DIGITS, "audio", "audio", media_id="MEDIA123", mime="audio/ogg; codecs=opus")


def text_msg(body="advance 500 beku", wa_id="wamid.T1"):
    return InboundMessage(wa_id, DIGITS, "text", "text", text=body)


def rows(db, direction="in"):
    db.expire_all()
    return db.scalars(select(Message).where(Message.direction == direction).order_by(Message.created_at)).all()


# ---------------------------------------------------------------- happy paths


def test_text_happy_path(db, helper_id):
    f = Fakes(ok(make_ctx(helper_id)))
    res = run(f.pipeline().handle(text_msg()))
    assert res.outcome == "replied"
    assert f.wa.sent == [(PHONE, REPLY)]
    assert f.tools_calls[0] == ("get_helper_context", {"whatsapp_e164": PHONE}, "wamid.T1:ctx")
    assert f.transcribe_calls == []
    call = f.liaison_calls[0]
    assert call["text"] == "advance 500 beku" and call["lang"] == "kn" and call["wa"] == "wamid.T1"
    assert call["ctx"]["helper_id"] == helper_id
    (row,) = rows(db)
    assert call["message_id"] == str(row.id)
    assert row.wa_message_id == "wamid.T1" and row.media_kind == "text"
    assert row.transcript == "advance 500 beku" and row.reply_text == REPLY and row.lang == "kn"
    assert str(row.helper_id) == helper_id and str(row.agent_run_id) == RUN_ID
    assert set(row.latency_ms) == {"download", "stt", "liaison", "send", "total"}
    (out,) = rows(db, "out")
    assert out.reply_text == REPLY and str(out.helper_id) == helper_id


def test_audio_happy_path_and_latency(db, helper_id):
    f = Fakes(ok(make_ctx(helper_id)))
    res = run(f.pipeline().handle(audio_msg()))
    assert res.outcome == "replied"
    assert f.wa.downloads == ["MEDIA123"]
    assert f.transcribe_calls == [(b"OggS-fake", "audio/ogg", "kn")]
    assert f.liaison_calls[0]["text"] == "naale raja beku"
    assert set(res.latency_ms) == {"download", "stt", "liaison", "send", "total"}
    assert all(isinstance(v, int) and v >= 0 for v in res.latency_ms.values())
    (row,) = rows(db)
    assert row.media_kind == "audio" and row.transcript == "naale raja beku"
    assert row.latency_ms == res.latency_ms and "total" in row.latency_ms
    assert len(rows(db, "out")) == 1


def test_dedupe_against_message_table(db, helper_id):
    f = Fakes(ok(make_ctx(helper_id)))
    p = f.pipeline()
    run(p.handle(text_msg(wa_id="wamid.X")))
    res = run(p.handle(text_msg(wa_id="wamid.X")))
    assert res.outcome == "duplicate"
    assert len(f.wa.sent) == 1 and len(f.liaison_calls) == 1
    assert len(rows(db)) == 1
    # A row written by someone else (another instance) also stops the pipeline before any tool call.
    db.add(Message(direction="in", wa_message_id="wamid.OTHER"))
    db.commit()
    f2 = Fakes(ok(make_ctx(helper_id)))
    assert run(f2.pipeline().handle(text_msg(wa_id="wamid.OTHER"))).outcome == "duplicate"
    assert f2.tools_calls == [] and f2.wa.sent == []


@pytest.mark.parametrize(
    "body", [ok({"known": False}), {"ok": False, "error": {"code": "invalid_args", "message": "x"}}]
)
def test_not_registered(db, body):
    f = Fakes(body)
    res = run(f.pipeline().handle(audio_msg()))
    assert res.template == "not_registered"
    assert f.wa.sent == [(PHONE, "[not_registered:en]")]
    assert f.wa.downloads == [] and f.liaison_calls == []
    (row,) = rows(db)
    assert row.transcript is None and row.reply_text is None and row.latency_ms is None and row.helper_id is None
    assert rows(db, "out") == []


# ---------------------------------------------------------------- consent


def test_consent_prompt_then_haudu(db, helper_id):
    f = Fakes(ok(make_ctx(helper_id, consented=(True, False))))
    p = f.pipeline()
    res = run(p.handle(text_msg("namaskara", wa_id="w1")))
    assert res.template == "consent_prompt"
    assert f.wa.sent[-1] == (PHONE, "[consent_prompt:kn]household=Flat 7C,name=Lakshmi")
    assert not any(n == "record_consent" for n, _, _ in f.tools_calls)

    res = run(p.handle(text_msg("Haudu!", wa_id="w2")))
    assert res.template == "consent_ok"
    consent = [(a, k) for n, a, k in f.tools_calls if n == "record_consent"]
    assert consent == [({"helper_id": helper_id, "employment_ids": [EMP2]}, "w2:consent")]
    assert f.wa.sent[-1] == (PHONE, "[consent_ok:kn]")
    assert f.liaison_calls == []
    # Nothing but the dedupe rows (plus helper_id) before consent.
    for row in rows(db):
        assert row.transcript is None and row.reply_text is None and row.latency_ms is None
        assert str(row.helper_id) == helper_id
    assert rows(db, "out") == []


def test_consent_via_voice_note(db, helper_id):
    f = Fakes(ok(make_ctx(helper_id, consented=(False, False))), transcript="Houdu.")
    res = run(f.pipeline().handle(audio_msg()))
    assert res.template == "consent_ok"
    (consent,) = [a for n, a, _ in f.tools_calls if n == "record_consent"]
    assert consent["employment_ids"] == [EMP1, EMP2]
    assert rows(db)[0].transcript is None


def test_consent_voice_note_stt_failure_prompts(db, helper_id):
    f = Fakes(ok(make_ctx(helper_id, consented=(False, True))), stt_exc=STTError("bad"))
    res = run(f.pipeline().handle(audio_msg()))
    assert res.template == "consent_prompt" and "household=Flat 4B" in res.reply_text


@pytest.mark.parametrize(
    "text,expected",
    [
        ("yes", True),
        ("Haan", True),
        ("haa ji", True),
        ("HAUDU", True),
        ("houdu", True),
        ("sari.", True),
        ("OK", True),
        ("ಹೌದು", True),
        ("हाँ", True),
        ("சரி", True),
        ("no", False),
        ("", False),
        (None, False),
        ("I want an advance of 500 rupees tomorrow ok", False),
        ("not ok", False),
    ],
)
def test_is_consent_yes(text, expected):
    assert is_consent_yes(text) is expected


# ---------------------------------------------------------------- error replies


def test_non_audio_please_send_voice(db, helper_id):
    f = Fakes(ok(make_ctx(helper_id)))
    res = run(f.pipeline().handle(InboundMessage("wamid.I", DIGITS, "other", "image")))
    assert res.template == "please_send_voice"
    assert f.wa.sent == [(PHONE, "[please_send_voice:kn]")]
    assert rows(db)[0].media_kind == "image"


@pytest.mark.parametrize(
    "kw",
    [
        {"stt_exc": STTError("no speech")},
        {"stt_exc": InvalidAudio("empty")},
        {"wa": FakeWA(download_exc=MediaTooLarge("big"))},
    ],
)
def test_stt_errors_couldnt_hear(db, helper_id, caplog, kw):
    caplog.set_level(logging.INFO)
    f = Fakes(ok(make_ctx(helper_id)), **kw)
    res = run(f.pipeline().handle(audio_msg()))
    assert res.template == "couldnt_hear"
    assert f.wa.sent == [(PHONE, "[couldnt_hear:kn]")]
    assert f.liaison_calls == []
    assert any(r.levelno == logging.WARNING and "transcribe" in r.getMessage() for r in caplog.records)
    assert rows(db)[0].latency_ms["total"] >= 0


def test_agent_error_not_understood(db, helper_id, caplog):
    caplog.set_level(logging.INFO)
    f = Fakes(ok(make_ctx(helper_id)), agent_exc=runtime.AgentError("timeout"))
    res = run(f.pipeline().handle(text_msg()))
    assert res.template == "not_understood"
    assert f.wa.sent == [(PHONE, "[not_understood:kn]")]
    errs = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errs and errs[0].exc_info
    assert rows(db)[0].reply_text == "[not_understood:kn]"


def test_tool_transport_error_not_understood(db, caplog):
    caplog.set_level(logging.INFO)
    f = Fakes(tools_exc=tools_client.ToolTransportError("down"))
    res = run(f.pipeline().handle(text_msg()))
    assert res.template == "not_understood"
    assert f.wa.sent == [(PHONE, "[not_understood:en]")]
    assert any(r.levelno == logging.ERROR and r.exc_info for r in caplog.records)
    assert rows(db)[0].reply_text is None  # not known to be consented: nothing stored


def test_send_failure_never_raises(db, helper_id, caplog):
    caplog.set_level(logging.INFO)
    f = Fakes(ok(make_ctx(helper_id)), wa=FakeWA(send_exc=RuntimeError("graph down")))
    res = run(f.pipeline().handle(text_msg()))
    assert res.sent is False and res.reply_text == REPLY
    assert any(r.levelno == logging.ERROR and "send failed" in r.getMessage() for r in caplog.records)
    assert rows(db, "out") == []


def test_empty_agent_text_falls_back(db, helper_id):
    f = Fakes(ok(make_ctx(helper_id)), agent_text="  ")
    assert run(f.pipeline().handle(text_msg())).template == "not_understood"


def test_long_text_cut_with_warning(db, helper_id, caplog):
    caplog.set_level(logging.INFO)
    f = Fakes(ok(make_ctx(helper_id)))
    run(f.pipeline().handle(text_msg("a" * 5000)))
    assert len(f.liaison_calls[0]["text"]) == 2000
    assert any(r.levelno == logging.WARNING and "cut" in r.getMessage() for r in caplog.records)


def test_slow_message_warns(db, helper_id, caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(pipeline_mod, "SLOW_MS", -1)
    f = Fakes(ok(make_ctx(helper_id)))
    run(f.pipeline().handle(text_msg()))
    assert any(r.levelno == logging.WARNING and "slow" in r.getMessage() for r in caplog.records)


def test_render_fallback(db, helper_id):
    def broken(key, lang, **slots):
        raise KeyError(key)

    f = Fakes(ok(make_ctx(helper_id)))
    p = f.pipeline(render=broken)
    res = run(p.handle(InboundMessage("w", DIGITS, "other", "sticker")))
    assert res.reply_text == pipeline_mod.FALLBACK_TEMPLATES["please_send_voice"]
    assert p.render("consent_prompt", "kn", name="Asha", household="Flat 1").startswith("Namaste Asha")


def test_logs_never_contain_raw_phone_or_text(db, helper_id, caplog):
    caplog.set_level(logging.DEBUG)
    cases = [
        (Fakes(ok(make_ctx(helper_id))), audio_msg("l1")),
        (Fakes(ok({"known": False})), text_msg(wa_id="l2")),
        (Fakes(ok(make_ctx(helper_id, consented=(False, False)))), text_msg("yes", wa_id="l3")),
        (Fakes(ok(make_ctx(helper_id)), agent_exc=runtime.AgentError("x")), text_msg(wa_id="l4")),
        (Fakes(ok(make_ctx(helper_id)), wa=FakeWA(send_exc=RuntimeError("x"))), text_msg(wa_id="l5")),
    ]
    for f, msg in cases:
        run(f.pipeline().handle(msg))
    assert caplog.records
    for r in caplog.records:
        blob = str(r.__dict__) + r.getMessage()
        assert DIGITS not in blob and DIGITS[2:] not in blob
        if r.levelno >= logging.INFO:
            assert "naale raja" not in blob and REPLY not in blob and "advance 500" not in blob


def test_timer_keys():
    t = Timer()
    t.mark("stt")
    d = t.as_dict()
    assert set(d) == {"download", "stt", "liaison", "send", "total"} and d["download"] == 0


# ---------------------------------------------------------------- real tools through tools_client


def _register_helper(client) -> tuple[str, str]:
    """Household + helper through the public API, without consent."""
    r = client.post(
        "/api/households", json={"household_name": "Test Flat", "owner_name": "Asha", "owner_phone": "9000000011"}
    ).json()
    body = {
        "name": "Lakshmi Devi",
        "whatsapp_e164": PHONE,
        "lang": "kn",
        "role": "cook",
        "salary_paise": 1_000_000,
        "payday_dom": 31,
        "weekly_off": [6],
        "paid_leaves_per_month": 2,
        "deduct_extra_leave": True,
        "advance_auto_limit_paise": 50_000,
        "advance_monthly_limit_paise": 200_000,
        "grocery_auto_limit_paise": 50_000,
        "grocery_monthly_budget_paise": 600_000,
    }
    h = client.post(f"/api/households/{r['household_id']}/helpers", headers={"X-Roz-Token": r["token"]}, json=body)
    assert h.status_code == 201, h.text
    return h.json()["helper_id"], h.json()["employment_id"]


def test_real_tools_consent_then_liaison(client, db):
    """get_helper_context and record_consent run for real (tools_client -> ASGI app -> Postgres)."""
    helper_id, eid = _register_helper(client)
    f = Fakes()

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app())) as http:

            async def real_tools(name, args, key):
                return await tools_client.call(name, args, key, http=http)

            p = Pipeline(
                tools_call=real_tools,
                run_liaison=f.run_liaison,
                render=f.render,
                transcribe=f.transcribe,
                wa=f.wa,
                store=PgMessageStore(),
            )
            first = await p.handle(text_msg("hello", wa_id="r1"))
            second = await p.handle(text_msg("haudu", wa_id="r2"))
            third = await p.handle(text_msg("advance 500 beku", wa_id="r3"))
            return first, second, third

    first, second, third = run(scenario())
    assert (
        first.template == "consent_prompt" and first.reply_text == "[consent_prompt:kn]household=Test Flat,name=Lakshmi"
    )
    assert second.template == "consent_ok"
    db.expire_all()
    assert db.get(Employment, uuid.UUID(eid)).consent_at is not None
    assert third.outcome == "replied" and f.liaison_calls[0]["ctx"]["helper_id"] == helper_id
    by_wa = {m.wa_message_id: m for m in rows(db)}
    assert by_wa["r1"].transcript is None and str(by_wa["r1"].helper_id) == helper_id
    assert by_wa["r3"].transcript == "advance 500 beku" and "total" in by_wa["r3"].latency_ms
    stats = client.get("/stats")
    if stats.status_code == 200 and "voice_median_latency_ms" in stats.json():
        assert stats.json()["voice_median_latency_ms"] is not None


def test_default_pipeline_wiring(client):
    """build_default_pipeline imports the real app.agents modules and reaches the tools over HTTP."""
    _register_helper(client)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app())) as http:
            p = build_default_pipeline(http=http)
            body = await p.tools_call("get_helper_context", {"whatsapp_e164": PHONE}, "wire:ctx")
            return p, body

    p, body = run(scenario())
    assert body["ok"] and body["result"]["known"] and body["result"]["name"] == "Lakshmi Devi"
    for key in ("not_registered", "consent_ok", "not_understood", "couldnt_hear", "please_send_voice"):
        assert p.render(key, "kn") != pipeline_mod.FALLBACK_TEMPLATES[key]
    assert "Lakshmi" in p.render("consent_prompt", "en", name="Lakshmi", household="Flat 1")
    assert callable(runtime.run_liaison)
