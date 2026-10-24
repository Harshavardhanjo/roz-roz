"""Voice routes (Meta webhook, Twilio sandbox, dev route) and the WhatsApp clients, over httpx.MockTransport."""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid

import httpx
import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select

from app.config import settings
from app.models import Helper, Message
from app.voice import pipeline as pipeline_mod
from app.voice import voice_config, whatsapp_webhook
from app.voice.pipeline import InboundMessage, Pipeline, get_pipeline
from app.voice.store import PgMessageStore
from app.voice.whatsapp_client import (
    MAX_MEDIA_BYTES,
    MediaRejected,
    MediaTooLarge,
    MetaWhatsAppClient,
    TwilioClient,
    twilio_signature,
)

DIGITS = "919876543210"
PHONE = "+" + DIGITS
GRAPH = "https://graph.facebook.com/v21.0"
SEND_URL = f"{GRAPH}/1234567890/messages"
LOOKUP_URL = f"{GRAPH}/MEDIA123"
MEDIA_URL = "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=MEDIA123"
TW_SEND = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages.json"
REPLY = "Sari, naale raja haaktini."
AUTH = {"Authorization": "Bearer test-tools"}


class Mock:
    """Per-URL (method + URL) queue of responses; the last one repeats. Records requests."""

    def __init__(self, routes: dict | None = None):
        self.routes = dict(routes or {})
        self.calls: dict[str, list[httpx.Request]] = {k: [] for k in self.routes}

    def add(self, key, response):
        self.routes[key] = response
        self.calls[key] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        key = f"{request.method} {request.url}"
        if key not in self.routes:
            return httpx.Response(599, json={"unexpected": key})
        request.read()
        self.calls[key].append(request)
        return self.routes[key]

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def sent(self, key=f"POST {SEND_URL}") -> list[dict]:
        return [json.loads(r.content) for r in self.calls.get(key, [])]


def send_ok():
    return httpx.Response(200, json={"messages": [{"id": "wamid.out"}]})


def add_media(mock: Mock, *, file_size=1234, body=b"OggS-voice", headers=None, mime="audio/ogg"):
    mock.add(
        f"GET {LOOKUP_URL}", httpx.Response(200, json={"url": MEDIA_URL, "mime_type": mime, "file_size": file_size})
    )
    mock.add(f"GET {MEDIA_URL}", httpx.Response(200, content=body, headers=headers or {"content-type": "audio/ogg"}))


@pytest.fixture(autouse=True)
def wa_settings(monkeypatch):
    monkeypatch.setattr(settings, "wa_app_secret", "test-secret")
    monkeypatch.setattr(settings, "wa_access_token", "wa-test-token")
    monkeypatch.setattr(settings, "wa_phone_number_id", "1234567890")
    monkeypatch.setattr(settings, "wa_verify_token", "wa-verify")
    monkeypatch.setattr(settings, "wa_graph_version", "v21.0")


@pytest.fixture
def helper_id(db):
    h = Helper(name="Lakshmi Devi", whatsapp_e164=PHONE, lang="kn")
    db.add(h)
    db.commit()
    return str(h.id)


class Env:
    """Pipeline with fake tools / STT / agent / templates and a real WhatsApp client over MockTransport."""

    def __init__(self, helper_id, wa_factory=MetaWhatsAppClient):
        self.helper_id = helper_id
        self.ctx = {
            "known": True,
            "helper_id": helper_id,
            "name": "Lakshmi Devi",
            "lang": "kn",
            "consented": True,
            "households": [
                {"household_id": str(uuid.uuid4()), "name": "Flat 4B", "employment_id": "e1", "consented": True}
            ],
        }
        self.mock = Mock({f"POST {SEND_URL}": send_ok()})
        self.tools_calls, self.transcribe_calls, self.liaison_calls = [], [], []
        self.pipeline = Pipeline(
            tools_call=self.tools_call,
            run_liaison=self.run_liaison,
            render=lambda key, lang, **slots: f"[{key}:{lang}]",
            transcribe=self.transcribe,
            wa=wa_factory(self.mock.client()),
            store=PgMessageStore(),
        )

    async def tools_call(self, name, args, key):
        self.tools_calls.append((name, args, key))
        if name == "get_helper_context":
            return {"ok": True, "result": self.ctx}
        return {"ok": True, "result": {}}

    async def transcribe(self, audio, mime, hint):
        self.transcribe_calls.append((audio, mime, hint))

        class T:
            text, language_code = "naale raja beku", "kn"

        return T()

    async def run_liaison(self, text, ctx, *, message_id, wa_message_id, lang):
        self.liaison_calls.append(text)
        return {"status": "ok", "text": REPLY, "replies": [], "clarify": None, "agent_run_id": None}


@pytest.fixture
def env(client, helper_id):
    e = Env(helper_id)
    client.app.dependency_overrides[get_pipeline] = lambda: e.pipeline
    yield e
    client.app.dependency_overrides.clear()


def sign(body: bytes, secret="test-secret") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def meta_payload(*messages, statuses=None) -> bytes:
    value = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": "1234567890"}}
    if messages:
        value["messages"] = list(messages)
    if statuses is not None:
        value["statuses"] = statuses
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": value}]}],
        }
    ).encode()


def audio(wa_id="wamid.A1", frm=DIGITS):
    return {
        "from": frm,
        "id": wa_id,
        "timestamp": "1700000000",
        "type": "audio",
        "audio": {"id": "MEDIA123", "mime_type": "audio/ogg; codecs=opus", "voice": True},
    }


def text(body="advance 500 beku", wa_id="wamid.T1", frm=DIGITS):
    return {"from": frm, "id": wa_id, "timestamp": "1700000000", "type": "text", "text": {"body": body}}


def post(client, body: bytes, sig="auto"):
    headers = {"content-type": "application/json"}
    if sig == "auto":
        headers["X-Hub-Signature-256"] = sign(body)
    elif sig is not None:
        headers["X-Hub-Signature-256"] = sig
    return client.post("/webhooks/whatsapp", content=body, headers=headers)


def inbound(db):
    db.expire_all()
    return db.scalars(select(Message).where(Message.direction == "in")).all()


# ---------------------------------------------------------------- verify


def test_verify_success(client):
    r = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "wa-verify", "hub.challenge": "12345"},
    )
    assert r.status_code == 200 and r.text == "12345"


@pytest.mark.parametrize(
    "params",
    [
        {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
        {"hub.mode": "unsubscribe", "hub.verify_token": "wa-verify", "hub.challenge": "1"},
        {},
    ],
)
def test_verify_forbidden(client, params):
    assert client.get("/webhooks/whatsapp", params=params).status_code == 403


# ---------------------------------------------------------------- signature / validation


def test_signature_missing_or_wrong_401(client, env):
    body = meta_payload(text())
    assert post(client, body, sig=None).status_code == 401
    assert post(client, body, sig="sha256=" + "0" * 64).status_code == 401
    assert post(client, body, sig=sign(body + b" ")).status_code == 401
    assert env.tools_calls == []


def test_401_when_app_secret_unset(client, env, monkeypatch):
    monkeypatch.setattr(settings, "wa_app_secret", "")
    body = meta_payload(text())
    assert post(client, body).status_code == 401
    assert post(client, body, sig=sign(body, "")).status_code == 401


def test_bad_json_400_after_signature(client, env):
    bad = b"{not json"
    assert post(client, bad, sig=None).status_code == 401
    assert post(client, bad).status_code == 400
    assert post(client, meta_payload({"from": DIGITS, "type": "text"})).status_code == 400  # no id
    assert env.tools_calls == []


def test_body_over_1mb_413(client, env):
    big = b"{" + b" " * (1024 * 1024 + 10) + b"}"
    assert post(client, big).status_code == 413


def test_statuses_only_ignored(client, env):
    body = meta_payload(statuses=[{"id": "wamid.out", "status": "delivered", "recipient_id": DIGITS}])
    assert post(client, body).status_code == 200
    assert env.tools_calls == [] and env.mock.sent() == []


def test_invalid_from_skipped(client, env, caplog):
    caplog.set_level(logging.INFO)
    assert post(client, meta_payload(text(frm="12ab"))).status_code == 200
    assert env.tools_calls == [] and env.mock.sent() == []
    assert any(r.levelno == logging.WARNING and "invalid sender" in r.getMessage() for r in caplog.records)


def test_kept_helpers_signature_ok_and_parse_messages():
    body = meta_payload(audio(), text())
    assert whatsapp_webhook.signature_ok(body, sign(body))
    assert not whatsapp_webhook.signature_ok(body, None)
    assert not whatsapp_webhook.signature_ok(body, sign(body, "other"))
    msgs = whatsapp_webhook.parse_messages(json.loads(body))
    assert msgs[0] == {
        "from": DIGITS,
        "id": "wamid.A1",
        "type": "audio",
        "audio_id": "MEDIA123",
        "mime_type": "audio/ogg; codecs=opus",
        "text": None,
    }
    assert msgs[1]["text"] == "advance 500 beku"


# ---------------------------------------------------------------- happy paths


def test_text_happy_path(client, env, db):
    r = post(client, meta_payload(text()))
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert env.tools_calls[0] == ("get_helper_context", {"whatsapp_e164": PHONE}, "wamid.T1:ctx")
    assert env.mock.sent() == [{"messaging_product": "whatsapp", "to": DIGITS, "type": "text", "text": {"body": REPLY}}]
    assert env.mock.calls[f"POST {SEND_URL}"][0].headers["authorization"] == "Bearer wa-test-token"
    (row,) = inbound(db)
    assert row.wa_message_id == "wamid.T1" and row.reply_text == REPLY and "total" in row.latency_ms


def test_audio_happy_path(client, env, db):
    add_media(env.mock)
    assert post(client, meta_payload(audio())).status_code == 200
    for key in (f"GET {LOOKUP_URL}", f"GET {MEDIA_URL}", f"POST {SEND_URL}"):
        assert env.mock.calls[key][0].headers["authorization"] == "Bearer wa-test-token"
    assert env.transcribe_calls == [(b"OggS-voice", "audio/ogg", "kn")]
    assert env.mock.sent()[0]["to"] == DIGITS
    (row,) = inbound(db)
    assert set(row.latency_ms) == {"download", "stt", "liaison", "send", "total"}
    assert row.transcript == "naale raja beku" and str(row.helper_id) == env.helper_id


def test_dedupe_same_delivery_twice(client, env, db):
    body = meta_payload(text(wa_id="wamid.DUP"))
    assert post(client, body).status_code == 200
    assert post(client, body).status_code == 200
    assert len(env.mock.sent()) == 1 and len(inbound(db)) == 1


def test_non_audio_please_send_voice(client, env):
    img = {"from": DIGITS, "id": "wamid.IMG", "type": "image", "image": {"id": "IMG1", "mime_type": "image/jpeg"}}
    post(client, meta_payload(img))
    assert env.mock.sent()[0]["text"]["body"] == "[please_send_voice:kn]"


@pytest.mark.parametrize(
    "kw",
    [
        {"file_size": MAX_MEDIA_BYTES + 1},
        {"file_size": None, "headers": {"content-type": "audio/ogg", "content-length": str(MAX_MEDIA_BYTES + 1)}},
        {"mime": "image/jpeg"},
    ],
)
def test_bad_media_couldnt_hear(client, env, kw):
    add_media(env.mock, **kw)
    post(client, meta_payload(audio()))
    assert env.transcribe_calls == []
    assert env.mock.sent()[0]["text"]["body"] == "[couldnt_hear:kn]"


def test_meta_client_caps_actual_size():
    async def scenario():
        m = Mock()
        add_media(m, file_size=None, body=b"x" * (MAX_MEDIA_BYTES + 1))
        async with m.client() as http:
            with pytest.raises(MediaTooLarge):
                await MetaWhatsAppClient(http).download_media("MEDIA123")
        m2 = Mock()
        add_media(m2, body=b"")
        async with m2.client() as http:
            with pytest.raises(MediaRejected):
                await MetaWhatsAppClient(http).download_media("MEDIA123")

    asyncio.run(scenario())


def test_handle_inbound_accepts_parse_messages_dict(env, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "_default", env.pipeline)
    for m in whatsapp_webhook.parse_messages(json.loads(meta_payload(text(wa_id="wamid.H")))):
        asyncio.run(whatsapp_webhook.handle_inbound(m))
    assert env.mock.sent()[0]["text"]["body"] == REPLY


def test_logs_never_contain_raw_phone(client, env, caplog):
    caplog.set_level(logging.DEBUG)
    add_media(env.mock)
    post(client, meta_payload(audio(), text(wa_id="w2")))
    post(client, meta_payload(text(frm="12ab", wa_id="w3")))
    post(client, meta_payload(text(wa_id="w4")), sig="bad")
    post(client, meta_payload({"from": DIGITS, "id": "w5", "type": "sticker"}))
    assert caplog.records
    for r in caplog.records:
        blob = str(r.__dict__) + r.getMessage()
        assert DIGITS not in blob and DIGITS[2:] not in blob
        assert "lookaside" not in blob and "wa-test-token" not in blob


# ---------------------------------------------------------------- Twilio sandbox


@pytest.fixture
def twilio_env(client, helper_id, monkeypatch):
    for k, v in {
        "wa_provider": "twilio",
        "twilio_account_sid": "ACtest",
        "twilio_auth_token": "tw-token",
        "twilio_whatsapp_from": "whatsapp:+14155238886",
    }.items():
        monkeypatch.setattr(voice_config.voice_settings, k, v)
    e = Env(helper_id, wa_factory=TwilioClient)
    e.mock.add(f"POST {TW_SEND}", httpx.Response(201, json={"sid": "SMout"}))
    client.app.dependency_overrides[get_pipeline] = lambda: e.pipeline
    yield e
    client.app.dependency_overrides.clear()


def tw_post(client, params: dict, token="tw-token"):
    url = settings.public_base_url.rstrip("/") + "/webhooks/twilio"
    sig = twilio_signature(token, url, list(params.items()))
    return client.post("/webhooks/twilio", data=params, headers={"X-Twilio-Signature": sig})


def test_twilio_text_happy_path(client, twilio_env):
    params = {"MessageSid": "SM1", "From": f"whatsapp:{PHONE}", "Body": "advance beku", "NumMedia": "0"}
    r = tw_post(client, params)
    assert r.status_code == 200 and "<Response>" in r.text
    req = twilio_env.mock.calls[f"POST {TW_SEND}"][0]
    assert dict(httpx.QueryParams(req.content.decode())) == {
        "From": "whatsapp:+14155238886",
        "To": f"whatsapp:{PHONE}",
        "Body": REPLY,
    }
    assert req.headers["authorization"].startswith("Basic ")


def test_twilio_audio_and_bad_signature(client, twilio_env):
    media = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages/MM1/Media/ME1"
    params = {
        "MessageSid": "MM1",
        "From": f"whatsapp:{PHONE}",
        "NumMedia": "1",
        "MediaUrl0": media,
        "MediaContentType0": "audio/ogg",
    }
    assert tw_post(client, params, token="wrong").status_code == 401
    assert client.post("/webhooks/twilio", data=params).status_code == 401
    twilio_env.mock.add(f"GET {media}", httpx.Response(200, content=b"OggS", headers={"content-type": "audio/ogg"}))
    assert tw_post(client, params).status_code == 200
    assert twilio_env.transcribe_calls[0][0] == b"OggS"


def test_serverless_processes_inline(monkeypatch):
    handled = []

    class FakePipeline:
        async def handle(self, msg):
            handled.append(msg.wa_message_id)

    msg = InboundMessage(wa_message_id="SM9", from_digits="919999900001", kind="text", msg_type="text", text="hi")
    background = BackgroundTasks()
    monkeypatch.setattr(settings, "vercel", "1")
    asyncio.run(whatsapp_webhook.dispatch(background, FakePipeline(), [msg]))
    assert handled == ["SM9"] and not background.tasks
    monkeypatch.setattr(settings, "vercel", "")
    asyncio.run(whatsapp_webhook.dispatch(background, FakePipeline(), [msg]))
    assert handled == ["SM9"] and len(background.tasks) == 1


def test_twilio_404_when_provider_meta(client, env):
    assert client.post("/webhooks/twilio", data={"MessageSid": "x"}).status_code == 404


def test_twilio_client_refuses_foreign_media_url():
    async def scenario():
        async with httpx.AsyncClient() as http:
            cfg = voice_config.VoiceSettings(_env_file=None, twilio_account_sid="A", twilio_auth_token="t")
            with pytest.raises(MediaRejected):
                await TwilioClient(http, cfg).download_media("https://evil.example.com/a.ogg")

    asyncio.run(scenario())


# ---------------------------------------------------------------- dev route


def dev_post(client, *, headers=AUTH, phone=PHONE, content=b"OggS-dev", ctype="audio/ogg"):
    return client.post(
        "/api/dev/voice", headers=headers, data={"phone": phone}, files={"file": ("note.ogg", content, ctype)}
    )


def test_dev_voice_auth(client, env):
    assert dev_post(client, headers={}).status_code == 401
    assert dev_post(client, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert env.tools_calls == []


def test_dev_voice_disabled(client, env, monkeypatch):
    monkeypatch.setattr(voice_config.voice_settings, "dev_voice_enabled", False)
    assert dev_post(client).status_code == 404


@pytest.mark.parametrize(
    "kw,status",
    [
        ({"phone": "12ab"}, 422),
        ({"ctype": "image/png"}, 422),
        ({"content": b""}, 422),
        ({"content": b"x" * (MAX_MEDIA_BYTES + 1)}, 413),
    ],
)
def test_dev_voice_validation(client, env, kw, status):
    assert dev_post(client, **kw).status_code == status
    assert env.tools_calls == []


def test_dev_voice_happy_path(client, env, db):
    r = dev_post(client, phone=DIGITS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transcript"] == "naale raja beku" and body["reply_text"] == REPLY
    assert set(body["latency_ms"]) == {"download", "stt", "liaison", "send", "total"}
    assert env.mock.sent() == []  # never sent on WhatsApp
    assert env.transcribe_calls[0][:2] == (b"OggS-dev", "audio/ogg")
    (row,) = inbound(db)
    assert row.wa_message_id.startswith("dev-") and uuid.UUID(row.wa_message_id[4:])
    assert "total" in row.latency_ms
