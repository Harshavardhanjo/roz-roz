"""Meta WhatsApp Cloud API webhook. Owned by Divyansh. Check field names against Meta's docs at setup."""
import hashlib
import hmac
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from ..config import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])


@router.get("")
def verify(hub_mode: str = Query(alias="hub.mode"), hub_verify_token: str = Query(alias="hub.verify_token"),
           hub_challenge: str = Query(alias="hub.challenge")):
    if hub_mode == "subscribe" and hub_verify_token == settings.wa_verify_token:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403)


def signature_ok(raw_body: bytes, header: str | None) -> bool:
    if not settings.wa_app_secret or not header:
        return False
    expected = "sha256=" + hmac.new(settings.wa_app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def parse_messages(payload: dict) -> list[dict]:
    """Flatten entry[].changes[].value.messages[] into {from, id, type, audio_id, mime_type, text}."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for m in change.get("value", {}).get("messages", []) or []:
                out.append({
                    "from": m.get("from"),
                    "id": m.get("id"),
                    "type": m.get("type"),
                    "audio_id": (m.get("audio") or {}).get("id"),
                    "mime_type": (m.get("audio") or {}).get("mime_type"),
                    "text": (m.get("text") or {}).get("body"),
                })
    return out


@router.post("")
async def receive(request: Request, background: BackgroundTasks):
    raw = await request.body()
    if not signature_ok(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401)
    for msg in parse_messages(await request.json()):
        background.add_task(handle_inbound, msg)
    return {"ok": True}  # answer Meta at once; the work runs in the background


async def handle_inbound(msg: dict) -> None:
    # TODO(Divyansh), per the LLD pipeline:
    # 1. insert message (unique wa_message_id) -> stop on duplicate
    # 2. ctx = tools get_helper_context(whatsapp_e164="+" + msg["from"]); unknown -> not_registered; no consent -> consent flow
    # 3. text = msg["text"] or stt.transcribe(await whatsapp_client.download_media(msg["audio_id"]))
    # 4. reply = agents.runtime.run_liaison(transcript=text, ctx=ctx, message_id=...)
    # 5. whatsapp_client.send_text(msg["from"], reply_text); save latency per stage
    log.info("inbound %s %s", msg.get("type"), msg.get("id"))
