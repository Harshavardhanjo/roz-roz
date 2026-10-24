"""Voice routes (all on this router; app.main includes it without a prefix):

- GET  /webhooks/whatsapp   Meta webhook verification (hub.challenge)
- POST /webhooks/whatsapp   Meta Cloud API messages (X-Hub-Signature-256; 401 unless WA_APP_SECRET is set)
- POST /webhooks/twilio     Twilio sandbox, only when WA_PROVIDER=twilio (X-Twilio-Signature)
- POST /api/dev/voice       demo backup: run the pipeline on an uploaded file and return JSON (Bearer TOOLS_TOKEN)

Webhooks answer at once; the pipeline runs as a background task and never raises.
"""

import hashlib
import hmac
import json
import logging
import uuid
from collections import Counter
from typing import Annotated, Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import settings
from . import voice_config
from .pipeline import InboundMessage, Pipeline, get_pipeline
from .voice_config import e164_digits, mask_phone
from .whatsapp_client import MAX_MEDIA_BYTES, base_mime, is_audio_mime, verify_twilio_signature

log = logging.getLogger(__name__)
router = APIRouter(tags=["whatsapp"])

MAX_BODY_BYTES = 1024 * 1024


# ---------------------------------------------------------------- helpers kept for the backend


def signature_ok(raw_body: bytes, header: str | None) -> bool:
    """X-Hub-Signature-256 check against WA_APP_SECRET; False when the secret or the header is missing."""
    if not settings.wa_app_secret or not header:
        return False
    expected = "sha256=" + hmac.new(settings.wa_app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.strip())


def parse_messages(payload: dict) -> list[dict]:
    """Flatten entry[].changes[].value.messages[] into {from, id, type, audio_id, mime_type, text}."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for m in change.get("value", {}).get("messages", []) or []:
                out.append(
                    {
                        "from": m.get("from"),
                        "id": m.get("id"),
                        "type": m.get("type"),
                        "audio_id": (m.get("audio") or {}).get("id"),
                        "mime_type": (m.get("audio") or {}).get("mime_type"),
                        "text": (m.get("text") or {}).get("body"),
                    }
                )
    return out


# ---------------------------------------------------------------- Meta payload validation


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class MetaAudio(_Model):
    id: str = Field(min_length=1, max_length=256)
    mime_type: str = ""


class MetaText(_Model):
    body: str = ""


class MetaMessage(_Model):
    from_: str = Field(alias="from", min_length=1, max_length=32)
    id: str = Field(min_length=1, max_length=256)
    type: str = Field(min_length=1, max_length=32)
    audio: MetaAudio | None = None
    text: MetaText | None = None


class MetaValue(_Model):
    messages: list[MetaMessage] = Field(default_factory=list)
    statuses: list[dict[str, Any]] = Field(default_factory=list)


class MetaChange(_Model):
    field: str | None = None
    value: MetaValue


class MetaEntry(_Model):
    id: str | None = None
    changes: list[MetaChange] = Field(default_factory=list)


class MetaWebhook(_Model):
    object: str | None = None
    entry: list[MetaEntry] = Field(default_factory=list)


async def read_capped_body(request: Request, limit: int = MAX_BODY_BYTES) -> bytes:
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > limit:
        raise HTTPException(413, "request body too large")
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(413, "request body too large")
    return bytes(buf)


def _sender(raw: str, wa_id: str) -> str | None:
    digits = e164_digits(raw)
    if digits is None:
        log.warning("invalid sender number; skipping message wa_message_id=%s from=%s", wa_id, mask_phone(raw))
    return digits


def parse_meta_messages(payload: MetaWebhook) -> list[InboundMessage]:
    out: list[InboundMessage] = []
    for entry in payload.entry:
        for change in entry.changes:
            for m in change.value.messages:
                digits = _sender(m.from_, m.id)
                if digits is None:
                    continue
                if m.type == "audio" and m.audio is not None and is_audio_mime(m.audio.mime_type or "audio/ogg"):
                    out.append(
                        InboundMessage(
                            wa_message_id=m.id,
                            from_digits=digits,
                            kind="audio",
                            msg_type=m.type,
                            media_id=m.audio.id,
                            mime=m.audio.mime_type or "audio/ogg",
                        )
                    )
                elif m.type == "text" and m.text is not None and m.text.body.strip():
                    out.append(
                        InboundMessage(
                            wa_message_id=m.id, from_digits=digits, kind="text", msg_type=m.type, text=m.text.body
                        )
                    )
                else:
                    out.append(InboundMessage(wa_message_id=m.id, from_digits=digits, kind="other", msg_type=m.type))
    return out


def parse_twilio_form(params: dict[str, str]) -> InboundMessage | None:
    sid = params.get("MessageSid") or params.get("SmsMessageSid") or ""
    if not sid:
        log.warning("twilio post without MessageSid")
        return None
    digits = _sender(params.get("From", ""), sid)
    if digits is None:
        return None
    try:
        num_media = int(params.get("NumMedia", "0") or 0)
    except ValueError:
        num_media = 0
    if num_media > 0:
        mime, url = params.get("MediaContentType0", ""), params.get("MediaUrl0", "")
        if is_audio_mime(mime) and url:
            return InboundMessage(
                wa_message_id=sid, from_digits=digits, kind="audio", msg_type="audio", media_id=url, mime=mime
            )
        return InboundMessage(wa_message_id=sid, from_digits=digits, kind="other", msg_type=mime or "media")
    body = params.get("Body", "")
    if body.strip():
        return InboundMessage(wa_message_id=sid, from_digits=digits, kind="text", msg_type="text", text=body)
    return InboundMessage(wa_message_id=sid, from_digits=digits, kind="other", msg_type="unknown")


async def process_messages(pipeline: Pipeline, messages: list[InboundMessage]) -> None:
    """Background task body: never raises."""
    for msg in messages:
        try:
            await pipeline.handle(msg)
        except Exception:
            log.error("background processing failed wa_message_id=%s", msg.wa_message_id, exc_info=True)


def _from_dict(m: dict) -> InboundMessage | None:
    """A parse_messages() item -> InboundMessage (None if the sender is not a valid number)."""
    digits = _sender(m.get("from") or "", m.get("id") or "")
    if digits is None or not m.get("id"):
        return None
    if m.get("type") == "audio" and m.get("audio_id"):
        mime = m.get("mime_type") or "audio/ogg"
        return InboundMessage(m["id"], digits, "audio", "audio", media_id=m["audio_id"], mime=mime)
    if m.get("type") == "text" and (m.get("text") or "").strip():
        return InboundMessage(m["id"], digits, "text", "text", text=m["text"])
    return InboundMessage(m["id"], digits, "other", m.get("type") or "")


async def handle_inbound(msg: InboundMessage | dict) -> None:
    """One message (InboundMessage or a parse_messages() dict) through the default pipeline. Never raises."""
    inbound = _from_dict(msg) if isinstance(msg, dict) else msg
    if inbound is not None:
        await process_messages(get_pipeline(), [inbound])


# ---------------------------------------------------------------- Meta routes


@router.get("/webhooks/whatsapp", response_class=PlainTextResponse)
def verify(request: Request):
    q = request.query_params
    token = q.get("hub.verify_token", "")
    expected = settings.wa_verify_token
    if q.get("hub.mode") == "subscribe" and expected and hmac.compare_digest(token, expected):
        log.info("webhook verified")
        return PlainTextResponse(q.get("hub.challenge", ""))
    log.warning("webhook verification failed mode=%s", q.get("hub.mode"))
    raise HTTPException(status_code=403, detail="verification failed")


@router.post("/webhooks/whatsapp")
async def receive(request: Request, background: BackgroundTasks, pipeline: Pipeline = Depends(get_pipeline)):
    raw = await read_capped_body(request)
    if not signature_ok(raw, request.headers.get("X-Hub-Signature-256")):
        log.warning("webhook signature missing or wrong (or WA_APP_SECRET unset)")
        raise HTTPException(status_code=401, detail="bad signature")
    try:
        payload = MetaWebhook.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as e:
        log.warning("malformed webhook payload: %s", type(e).__name__)
        raise HTTPException(status_code=400, detail="malformed payload") from None

    messages = parse_meta_messages(payload)
    statuses = sum(len(c.value.statuses) for e in payload.entry for c in e.changes)
    log.info(
        "webhook received messages=%d types=%s statuses=%d",
        len(messages),
        dict(Counter(m.msg_type for m in messages)),
        statuses,
    )
    if messages:
        background.add_task(process_messages, pipeline, messages)
    return {"ok": True}  # answer Meta at once; the work runs in the background


# ---------------------------------------------------------------- Twilio sandbox (team testing only)


@router.post("/webhooks/twilio")
async def receive_twilio(request: Request, background: BackgroundTasks, pipeline: Pipeline = Depends(get_pipeline)):
    cfg = voice_config.voice_settings
    if cfg.wa_provider != "twilio":
        raise HTTPException(status_code=404, detail="Not Found")
    raw = await read_capped_body(request)
    try:
        pairs = parse_qsl(raw.decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError:
        pairs = None
    url = settings.public_base_url.rstrip("/") + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    sig = request.headers.get("X-Twilio-Signature")
    if pairs is None or not verify_twilio_signature(cfg.twilio_auth_token, url, pairs, sig):
        log.warning("twilio signature missing or wrong")
        raise HTTPException(status_code=401, detail="bad signature")
    msg = parse_twilio_form(dict(pairs))
    log.info("twilio webhook received messages=%d", int(msg is not None))
    if msg is not None:
        background.add_task(process_messages, pipeline, [msg])
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="text/xml")


# ---------------------------------------------------------------- dev route (demo backup)


def require_dev_access(request: Request) -> None:
    if not voice_config.voice_settings.dev_voice_enabled:
        raise HTTPException(status_code=404, detail="Not Found")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    expected = settings.tools_token
    if scheme.lower() != "bearer" or not expected or not hmac.compare_digest(token.strip(), expected):
        log.warning("dev voice: unauthorized")
        raise HTTPException(status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"})


@router.post("/api/dev/voice", dependencies=[Depends(require_dev_access)])
async def dev_voice(
    file: Annotated[UploadFile, File()],
    phone: Annotated[str, Form()],
    pipeline: Pipeline = Depends(get_pipeline),
) -> dict:
    """Same pipeline as WhatsApp, synchronous, nothing sent on WhatsApp. Returns {transcript, reply_text,
    latency_ms: {download, stt, liaison, send, total}, outcome}."""
    digits = e164_digits(phone)
    if digits is None:
        log.warning("dev voice: invalid phone %s", mask_phone(phone))
        raise HTTPException(status_code=422, detail="phone must be E.164, e.g. +919876543210")
    if not is_audio_mime(file.content_type):
        raise HTTPException(status_code=422, detail="file must be audio/*")
    audio = await file.read(MAX_MEDIA_BYTES + 1)
    if len(audio) > MAX_MEDIA_BYTES:
        raise HTTPException(status_code=413, detail="audio over 16 MB")
    if not audio:
        raise HTTPException(status_code=422, detail="empty audio file")
    msg = InboundMessage(
        wa_message_id=f"dev-{uuid.uuid4()}",
        from_digits=digits,
        kind="audio",
        msg_type="audio",
        mime=base_mime(file.content_type),
        audio_bytes=audio,
    )
    log.info("dev voice received from=%s bytes=%d", mask_phone(digits), len(audio))
    res = await pipeline.handle(msg, send=False)
    return {
        "transcript": res.transcript,
        "reply_text": res.reply_text,
        "latency_ms": res.latency_ms,
        "outcome": res.outcome,
    }
