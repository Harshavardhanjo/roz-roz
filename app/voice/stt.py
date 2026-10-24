"""Speech-to-text for helper voice notes (WhatsApp ogg/opus).

Providers: ElevenLabs Scribe (default, auto language detection; ELEVENLABS_STT_MODEL) and Sarvam for Kannada
(STT_PROVIDER_KN=sarvam). `transcribe()` validates the input, picks a provider, retries once on transient failures and
returns a frozen `Transcript`. The raw transcript is returned untouched: the liaison agent resolves spoken numbers.
Transcripts and keys are never logged.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from ..config import settings
from .voice_config import VoiceSettings, voice_settings

log = logging.getLogger(__name__)

ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"

MAX_AUDIO_BYTES = 16 * 1024 * 1024
SUPPORTED_LANGS = frozenset({"kn", "hi", "ta", "te", "en"})
FFMPEG_TIMEOUT_S = 10.0

# Containers both providers accept as-is (MIME -> file extension); anything else goes through ffmpeg.
_EXT_BY_MIME = {
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/webm": "webm",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/flac": "flac",
}
ACCEPTED_MIMES = frozenset(_EXT_BY_MIME)

# ISO 639-3 (ElevenLabs) / BCP-47 (Sarvam) -> our 2-letter codes.
_LANG_MAP = {
    "kan": "kn",
    "hin": "hi",
    "tam": "ta",
    "tel": "te",
    "eng": "en",
    "kn-in": "kn",
    "hi-in": "hi",
    "ta-in": "ta",
    "te-in": "te",
    "en-in": "en",
}
# our code -> ElevenLabs language_code
_EL_LANG_CODE = {"kn": "kan", "hi": "hin", "ta": "tam", "te": "tel", "en": "eng"}


class STTError(Exception):
    """Transcription failed; the caller asks the helper to resend."""


class InvalidAudio(ValueError):
    """Input rejected before any network call."""


class Transcript(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    language_code: str | None
    raw_language_code: str | None
    language_probability: float | None
    duration_ms: int
    provider: str


def map_language_code(raw: str | None) -> str | None:
    if not raw:
        return None
    return _LANG_MAP.get(raw.strip().lower(), raw)


class _ElevenLabsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    language_code: str | None = None
    language_probability: float | None = None


class _SarvamResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transcript: str
    language_code: str | None = None


class _Retryable(Exception):
    """Internal: transient failure worth one retry."""


def _ms_since(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


async def _post_with_retry(
    provider: str,
    http: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    data: dict[str, str],
    files: dict[str, Any],
    timeout_s: float,
    audio_bytes: int,
) -> Any:
    """POST once, retry once on timeout / network error / 5xx. Returns the parsed JSON body."""
    attempts = 2
    for attempt in range(1, attempts + 1):
        started = time.perf_counter()
        status: int | str = "-"
        try:
            try:
                resp = await http.post(url, headers=headers, data=data, files=files, timeout=timeout_s)
            except httpx.TimeoutException as exc:
                status = "timeout"
                raise _Retryable("timeout") from exc
            except httpx.TransportError as exc:
                status = "network_error"
                raise _Retryable(type(exc).__name__) from exc
            status = resp.status_code
            if resp.status_code >= 500:
                raise _Retryable(f"http {resp.status_code}")
            if resp.status_code >= 400:
                log.error(
                    "stt request rejected provider=%s attempt=%d status=%s latency_ms=%d",
                    provider,
                    attempt,
                    status,
                    _ms_since(started),
                )
                raise STTError(f"{provider} rejected request: http {resp.status_code}")
            try:
                body = resp.json()
            except ValueError as exc:
                log.error("stt response not json provider=%s attempt=%d", provider, attempt)
                raise STTError(f"{provider} returned non-JSON response") from exc
            log.info(
                "stt response provider=%s attempt=%d status=%s latency_ms=%d audio_bytes=%d",
                provider,
                attempt,
                status,
                _ms_since(started),
                audio_bytes,
            )
            return body
        except _Retryable as exc:
            args = (provider, attempt, status, _ms_since(started), exc)
            if attempt < attempts:
                log.warning("stt attempt failed, retrying provider=%s attempt=%d status=%s latency_ms=%d (%s)", *args)
                continue
            log.error("stt failed after retry provider=%s attempt=%d status=%s latency_ms=%d (%s)", *args)
            raise STTError(f"{provider} failed: {exc}") from exc
    raise STTError(f"{provider} failed")  # pragma: no cover


def _build(provider: str, text: str, raw_lang: str | None, prob: float | None, started: float) -> Transcript:
    if not text.strip():
        log.error("stt empty transcript provider=%s", provider)
        raise STTError("empty transcript")
    return Transcript(
        text=text,
        language_code=map_language_code(raw_lang),
        raw_language_code=raw_lang,
        language_probability=prob,
        duration_ms=_ms_since(started),
        provider=provider,
    )


async def _elevenlabs(
    audio: bytes, mime: str, lang_hint: str | None, cfg: VoiceSettings, http: httpx.AsyncClient
) -> Transcript:
    started = time.perf_counter()
    data = {"model_id": settings.elevenlabs_stt_model}
    if lang_hint:
        data["language_code"] = _EL_LANG_CODE[lang_hint]
    body = await _post_with_retry(
        "elevenlabs",
        http,
        ELEVENLABS_STT_URL,
        headers={"xi-api-key": settings.elevenlabs_api_key},
        data=data,
        files={"file": (f"audio.{_EXT_BY_MIME.get(mime, 'bin')}", audio, mime)},
        timeout_s=cfg.stt_timeout_s,
        audio_bytes=len(audio),
    )
    try:
        parsed = _ElevenLabsResponse.model_validate(body)
    except ValidationError as exc:
        log.error("stt response malformed provider=elevenlabs")
        raise STTError("elevenlabs returned malformed response") from exc
    return _build("elevenlabs", parsed.text, parsed.language_code, parsed.language_probability, started)


async def _sarvam(audio: bytes, mime: str, cfg: VoiceSettings, http: httpx.AsyncClient) -> Transcript:
    started = time.perf_counter()
    body = await _post_with_retry(
        "sarvam",
        http,
        SARVAM_STT_URL,
        headers={"api-subscription-key": cfg.sarvam_api_key},
        data={"language_code": "kn-IN"},
        files={"file": (f"audio.{_EXT_BY_MIME.get(mime, 'bin')}", audio, mime)},
        timeout_s=cfg.stt_timeout_s,
        audio_bytes=len(audio),
    )
    try:
        parsed = _SarvamResponse.model_validate(body)
    except ValidationError as exc:
        log.error("stt response malformed provider=sarvam")
        raise STTError("sarvam returned malformed response") from exc
    return _build("sarvam", parsed.transcript, parsed.language_code or "kn-IN", None, started)


async def to_wav_16k_mono(audio: bytes) -> bytes:
    """Convert arbitrary audio to 16 kHz mono WAV via ffmpeg pipes (no shell, no temp files)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "wav",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        log.error("ffmpeg not found")
        raise STTError("ffmpeg not available") from exc
    try:
        out, err = await asyncio.wait_for(proc.communicate(audio), timeout=FFMPEG_TIMEOUT_S)
    except TimeoutError as exc:
        proc.kill()
        log.error("ffmpeg timed out audio_bytes=%d", len(audio))
        raise STTError("audio conversion timed out") from exc
    if proc.returncode != 0 or not out:
        log.error("ffmpeg failed returncode=%s stderr=%s", proc.returncode, (err or b"")[:300].decode(errors="replace"))
        raise STTError("audio conversion failed")
    return out


def _validate(audio: bytes, mime: str, lang_hint: str | None) -> str:
    if not audio:
        raise InvalidAudio("empty audio")
    if len(audio) > MAX_AUDIO_BYTES:
        raise InvalidAudio(f"audio too large: {len(audio)} bytes (max {MAX_AUDIO_BYTES})")
    if lang_hint is not None and lang_hint not in SUPPORTED_LANGS:
        raise InvalidAudio(f"unsupported lang_hint: {lang_hint!r}")
    base = (mime or "").split(";", 1)[0].strip().lower()
    if not base.startswith("audio/") or base == "audio/":
        raise InvalidAudio(f"unsupported mime type: {mime!r}")
    return base


async def transcribe(
    audio: bytes,
    mime: str = "audio/ogg",
    lang_hint: str | None = None,
    *,
    config: VoiceSettings | None = None,
    http: httpx.AsyncClient | None = None,
) -> Transcript:
    """Transcribe a voice note. Raises InvalidAudio (bad input, before any network call) or STTError."""
    cfg = config or voice_settings
    base_mime = _validate(audio, mime, lang_hint)

    if base_mime not in ACCEPTED_MIMES:
        log.info("stt converting audio mime=%s audio_bytes=%d", base_mime, len(audio))
        audio = await to_wav_16k_mono(audio)
        base_mime = "audio/wav"

    use_sarvam_kn = cfg.stt_provider_kn == "sarvam"
    client = http or httpx.AsyncClient()
    started = time.perf_counter()
    try:
        if lang_hint == "kn" and use_sarvam_kn:
            result = await _sarvam(audio, base_mime, cfg, client)
        else:
            result = await _elevenlabs(audio, base_mime, lang_hint, cfg, client)
            if use_sarvam_kn and result.language_code == "kn":
                # Detected Kannada: prefer Sarvam, keep the ElevenLabs result as the fallback.
                try:
                    result = await _sarvam(audio, base_mime, cfg, client)
                except STTError:
                    log.warning("sarvam kannada pass failed; using the elevenlabs result")
    finally:
        if http is None:
            await client.aclose()

    result = result.model_copy(update={"duration_ms": _ms_since(started)})
    log.info(
        "stt done provider=%s language=%s raw_language=%s language_probability=%s latency_ms=%d audio_bytes=%d",
        result.provider,
        result.language_code,
        result.raw_language_code,
        result.language_probability,
        result.duration_ms,
        len(audio),
    )
    log.debug("stt transcript_len=%d", len(result.text))
    return result
