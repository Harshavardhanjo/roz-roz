"""Inbound WhatsApp message -> dedupe -> helper context -> consent -> STT -> liaison agent -> reply -> save.

`Pipeline` takes every collaborator as a constructor argument so tests pass fakes; `build_default_pipeline` wires the
real modules (app.agents.* are imported lazily, on first use). `Pipeline.handle` never raises and always tries to send
some reply. Phone numbers are masked in logs; transcripts and reply texts are never logged.
"""

import logging
import time
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from .store import MessageStore, PgMessageStore
from .stt import SUPPORTED_LANGS, InvalidAudio, STTError
from .voice_config import mask_phone
from .whatsapp_client import MediaRejected, WAClient, base_mime, make_wa_client

log = logging.getLogger(__name__)

SLOW_MS = 10_000
MAX_TEXT_CHARS = 2000
LATENCY_KEYS = ("download", "stt", "liaison", "send")

YES_WORDS = frozenset(
    {
        "yes",
        "y",
        "ok",
        "okay",
        "okk",
        "haan",
        "han",
        "haa",
        "ha",
        "haanji",
        "haudu",
        "houdu",
        "howdu",
        "sari",
        "seri",
        "avunu",
        "हाँ",
        "हां",
        "हा",
        "ಹೌದು",
        "ಸರಿ",
        "சரி",
        "ஆமா",
        "ஆம்",
        "అవును",
        "సరే",
    }
)

# Used only if app.agents.templates is missing a key (or fails); the real texts live there.
FALLBACK_TEMPLATES = {
    "not_registered": "This number isn't set up with Roz Roz yet. Please ask your employer to add you.",
    "consent_prompt": "Namaste {name}! {household} uses Roz Roz to record your leave, advances and pay. "
    'They can see what you send. Reply "yes" to agree.',
    "consent_ok": "Thank you. Send a voice note any time for leave, an advance or grocery money.",
    "not_understood": "Sorry, I didn't catch that. Please send the voice note again.",
    "couldnt_hear": "Sorry, I couldn't hear that clearly. Please send the voice note again.",
    "please_send_voice": "Please send a voice note about leave, an advance or grocery money.",
}

ToolsCall = Callable[[str, dict, str], Awaitable[dict]]
RunLiaison = Callable[..., Awaitable[dict]]
Render = Callable[..., str]
Transcribe = Callable[[bytes, str, str | None], Awaitable[Any]]


class ToolFailed(Exception):
    """A tool answered {"ok": false}."""

    def __init__(self, name: str, error: dict | None):
        super().__init__(f"{name}: {(error or {}).get('code', 'unknown')}")
        self.error = error or {}


class Timer:
    """Stage timer: mark(stage) adds the ms since the previous mark (or skip) to that stage."""

    def __init__(self) -> None:
        self._start = self._last = time.perf_counter()
        self.stages: dict[str, int] = {}

    def mark(self, stage: str) -> int:
        now = time.perf_counter()
        ms = int((now - self._last) * 1000)
        self._last = now
        self.stages[stage] = self.stages.get(stage, 0) + ms
        log.debug("pipeline stage=%s ms=%d", stage, ms)
        return ms

    def skip(self) -> None:
        """Move the reference point without attributing the time to a stage (it still counts in total)."""
        self._last = time.perf_counter()

    def total_ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)

    def as_dict(self) -> dict[str, int]:
        out = {k: self.stages.get(k, 0) for k in LATENCY_KEYS}
        out["total"] = self.total_ms()
        return out


@dataclass
class InboundMessage:
    wa_message_id: str
    from_digits: str  # E.164 digits, no "+"
    kind: Literal["text", "audio", "other"]
    msg_type: str = ""
    text: str | None = None
    media_id: str | None = None  # Meta media id, or Twilio MediaUrl0
    mime: str | None = None
    audio_bytes: bytes | None = None  # dev route: the audio is already in hand

    @property
    def e164(self) -> str:
        return "+" + self.from_digits


@dataclass
class PipelineResult:
    outcome: str  # duplicate | replied | <template key>
    reply_text: str | None = None
    template: str | None = None
    transcript: str | None = None
    lang: str = "en"
    latency_ms: dict[str, int] = field(default_factory=dict)
    sent: bool = False
    message_id: uuid.UUID | None = None


def is_consent_yes(text: str | None) -> bool:
    """A short (<= 4 words) message whose first word is a yes-word, in any of our languages or scripts."""
    if not text:
        return False
    cleaned = "".join(" " if unicodedata.category(ch)[0] in "PSZ" else ch for ch in text.lower())
    tokens = cleaned.split()
    if not tokens or len(tokens) > 4:
        return False
    return tokens[0] in YES_WORDS or "".join(tokens) in YES_WORDS


class Pipeline:
    def __init__(
        self,
        *,
        tools_call: ToolsCall,
        run_liaison: RunLiaison,
        render: Render,
        transcribe: Transcribe,
        wa: WAClient,
        store: MessageStore,
    ):
        self.tools_call = tools_call
        self.run_liaison = run_liaison
        self._render = render
        self.transcribe = transcribe
        self.wa = wa
        self.store = store

    # ------------------------------------------------------------ helpers

    def render(self, key: str, lang: str, **slots) -> str:
        try:
            text = self._render(key, lang, **slots)
            if text:
                return text
        except Exception:
            log.warning("template %s/%s failed; using the fallback text", key, lang, exc_info=True)
        try:
            return FALLBACK_TEMPLATES[key].format(**{"name": "", "household": "your household", **slots})
        except (KeyError, IndexError):
            return FALLBACK_TEMPLATES["not_understood"]

    async def _tool(self, name: str, args: dict, key: str) -> dict:
        body = await self.tools_call(name, args, key)
        if not isinstance(body, dict) or not body.get("ok"):
            raise ToolFailed(name, (body or {}).get("error") if isinstance(body, dict) else None)
        return body.get("result") or {}

    async def _audio_text(self, msg: InboundMessage, lang: str | None, t: Timer) -> Any:
        if msg.audio_bytes is not None:
            audio, mime = msg.audio_bytes, base_mime(msg.mime) or "audio/ogg"
        else:
            audio, mime = await self.wa.download_media(msg.media_id or "")
            mime = base_mime(mime or msg.mime) or "audio/ogg"
            t.mark("download")
        hint = lang if lang in SUPPORTED_LANGS else None
        transcript = await self.transcribe(audio, mime, hint)
        t.mark("stt")
        return transcript

    async def _send(self, msg: InboundMessage, res: PipelineResult, t: Timer, *, send: bool) -> None:
        t.skip()
        if send and res.reply_text:
            try:
                await self.wa.send_text(msg.e164, res.reply_text)
                res.sent = True
            except Exception:
                log.error(
                    "reply send failed wa_message_id=%s to=%s outcome=%s",
                    msg.wa_message_id,
                    mask_phone(msg.from_digits),
                    res.outcome,
                    exc_info=True,
                )
        t.mark("send")
        res.latency_ms = t.as_dict()

    async def _reply(self, msg, res: PipelineResult, t: Timer, key: str, lang: str, *, send: bool, **slots):
        res.outcome = res.template = key
        res.reply_text = self.render(key, lang, **slots)
        await self._send(msg, res, t, send=send)
        return res

    async def _save(self, res: PipelineResult, *, helper_id, lang, agent_run_id=None) -> None:
        """Only for consented helpers: fill in the inbound row and record the outbound reply."""
        if res.message_id is None:
            return
        try:
            await self.store.complete(
                res.message_id,
                helper_id=helper_id,
                transcript=res.transcript,
                lang=lang,
                agent_run_id=agent_run_id,
                reply_text=res.reply_text,
                latency_ms=res.latency_ms,
            )
            if res.sent and res.reply_text:
                await self.store.insert_outbound(helper_id=helper_id, reply_text=res.reply_text, lang=lang)
        except Exception:
            log.error("saving message %s failed", res.message_id, exc_info=True)

    # ------------------------------------------------------------ main entry

    async def handle(self, msg: InboundMessage, *, send: bool = True) -> PipelineResult:
        """Process one inbound message. Never raises; always tries to send a reply."""
        t = Timer()
        res = PipelineResult(outcome="error")
        lang, helper_id, consented = "en", None, False
        wa_id, phone = msg.wa_message_id, mask_phone(msg.from_digits)
        try:
            # 1. dedupe
            media_kind = msg.kind if msg.kind != "other" else (msg.msg_type or "other")
            res.message_id = await self.store.insert_inbound(wa_id, media_kind)
            if res.message_id is None:
                log.info("duplicate delivery wa_message_id=%s; skipped", wa_id)
                res.outcome = "duplicate"
                return res

            # 2. who is this?
            body = await self.tools_call("get_helper_context", {"whatsapp_e164": msg.e164}, f"{wa_id}:ctx")
            ok = isinstance(body, dict) and body.get("ok")
            ctx = (body.get("result") or {}) if ok else {}
            t.skip()
            if not ctx.get("known"):
                log.info("unregistered sender wa_message_id=%s from=%s", wa_id, phone)
                return await self._reply(msg, res, t, "not_registered", "en", send=send)
            lang = ctx.get("lang") or "en"
            res.lang = lang
            helper_id = ctx.get("helper_id")
            await self.store.set_helper(res.message_id, helper_id)

            # 3. consent first; nothing else is stored before it
            if not ctx.get("consented"):
                return await self._consent(msg, ctx, lang, res, t, send=send)
            consented = True

            # 4. text, or the voice note's transcript
            if msg.kind == "other":
                await self._reply(msg, res, t, "please_send_voice", lang, send=send)
                await self._save(res, helper_id=helper_id, lang=lang)
                return res
            stored_lang = lang
            if msg.kind == "text":
                text = msg.text or ""
                if len(text) > MAX_TEXT_CHARS:
                    log.warning("text over %d chars cut wa_message_id=%s chars=%d", MAX_TEXT_CHARS, wa_id, len(text))
                    text = text[:MAX_TEXT_CHARS]
            else:
                try:
                    transcript = await self._audio_text(msg, lang, t)
                except (STTError, InvalidAudio, MediaRejected) as e:
                    log.warning("could not transcribe wa_message_id=%s from=%s: %s", wa_id, phone, type(e).__name__)
                    await self._reply(msg, res, t, "couldnt_hear", lang, send=send)
                    await self._save(res, helper_id=helper_id, lang=lang)
                    return res
                text = getattr(transcript, "text", "") or ""
                detected = getattr(transcript, "language_code", None)
                stored_lang = detected if detected in SUPPORTED_LANGS else lang
            res.transcript = text
            if not text.strip():
                await self._reply(msg, res, t, "couldnt_hear", lang, send=send)
                await self._save(res, helper_id=helper_id, lang=stored_lang)
                return res

            # 5. the liaison agent files the requests and writes the reply
            t.skip()
            reply = await self.run_liaison(text, ctx, message_id=str(res.message_id), wa_message_id=wa_id, lang=lang)
            t.mark("liaison")
            reply = reply if isinstance(reply, dict) else {}
            reply_text = (reply.get("text") or "").strip()
            if not reply_text:
                log.warning("liaison returned no text wa_message_id=%s status=%s", wa_id, reply.get("status"))
                await self._reply(msg, res, t, "not_understood", lang, send=send)
            else:
                res.outcome, res.reply_text = "replied", reply_text
                await self._send(msg, res, t, send=send)

            # 6. save
            await self._save(res, helper_id=helper_id, lang=stored_lang, agent_run_id=reply.get("agent_run_id"))
            return res
        except Exception:
            log.error("pipeline failed wa_message_id=%s from=%s", wa_id, phone, exc_info=True)
            try:
                if res.reply_text is None:
                    await self._reply(msg, res, t, "not_understood", lang, send=send)
                    if consented:
                        await self._save(res, helper_id=helper_id, lang=lang)
            except Exception:
                log.error("fallback reply failed wa_message_id=%s", wa_id, exc_info=True)
            return res
        finally:
            if res.outcome != "duplicate":
                if not res.latency_ms:
                    res.latency_ms = t.as_dict()
                total = res.latency_ms.get("total", 0)
                if total > SLOW_MS:
                    log.warning(
                        "slow message wa_message_id=%s outcome=%s latency_ms=%s", wa_id, res.outcome, res.latency_ms
                    )
                else:
                    log.info(
                        "message handled wa_message_id=%s outcome=%s latency_ms=%s", wa_id, res.outcome, res.latency_ms
                    )

    async def _consent(
        self, msg: InboundMessage, ctx: dict, lang: str, res: PipelineResult, t: Timer, *, send: bool
    ) -> PipelineResult:
        """Ask for consent, or record it if this message says yes. The transcript is not stored."""
        text = msg.text if msg.kind == "text" else None
        if msg.kind == "audio":
            try:
                text = getattr(await self._audio_text(msg, lang, t), "text", None)
            except Exception as e:
                log.warning(
                    "consent voice note not transcribed wa_message_id=%s: %s", msg.wa_message_id, type(e).__name__
                )
        pending = [h for h in ctx.get("households") or [] if not h.get("consented")]
        if is_consent_yes(text):
            await self._tool(
                "record_consent",
                {"helper_id": ctx.get("helper_id"), "employment_ids": [h["employment_id"] for h in pending]},
                f"{msg.wa_message_id}:consent",
            )
            log.info("consent recorded from=%s households=%d", mask_phone(msg.from_digits), len(pending))
            return await self._reply(msg, res, t, "consent_ok", lang, send=send)
        name = (ctx.get("name") or "").split()
        household = pending[0].get("name", "") if pending else ""
        return await self._reply(
            msg, res, t, "consent_prompt", lang, send=send, name=name[0] if name else "", household=household
        )


# ---------------------------------------------------------------- default wiring


def build_default_pipeline(http=None) -> Pipeline:
    """The real collaborators. app.agents.* are imported on first use so this module imports without them."""

    async def tools_call(name: str, args: dict, key: str) -> dict:
        from ..agents import tools_client

        if http is not None:
            return await tools_client.call(name, args, key, http=http)
        return await tools_client.call(name, args, key)

    async def run_liaison(text: str, ctx: dict, *, message_id: str, wa_message_id: str, lang: str) -> dict:
        from ..agents import runtime

        return await runtime.run_liaison(text, ctx, message_id, wa_message_id=wa_message_id, lang=lang)

    def render(key: str, lang: str, **slots) -> str:
        from ..agents import templates

        return templates.render(key, lang, **slots)

    async def transcribe(audio: bytes, mime: str, lang_hint: str | None):
        from . import stt

        return await stt.transcribe(audio, mime, lang_hint)

    return Pipeline(
        tools_call=tools_call,
        run_liaison=run_liaison,
        render=render,
        transcribe=transcribe,
        wa=make_wa_client(),
        store=PgMessageStore(),
    )


_default: Pipeline | None = None


def get_pipeline() -> Pipeline:
    """FastAPI dependency: one default Pipeline per process, built lazily (tests override this)."""
    global _default
    if _default is None:
        _default = build_default_pipeline()
    return _default
