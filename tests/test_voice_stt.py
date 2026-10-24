"""app/voice/stt.py with httpx.MockTransport (no network)."""

import asyncio
import logging

import httpx
import pytest

from app.config import settings
from app.voice import stt
from app.voice.stt import (
    ELEVENLABS_STT_URL,
    MAX_AUDIO_BYTES,
    SARVAM_STT_URL,
    InvalidAudio,
    STTError,
    Transcript,
    map_language_code,
    transcribe,
)
from app.voice.voice_config import VoiceSettings

AUDIO = b"OggS\x00fake-opus-bytes"
TEXT = "Somavara baralla, aidu nooru advance beku"


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "el-test-key")
    monkeypatch.setattr(settings, "elevenlabs_stt_model", "scribe_v1")


def cfg(**kw) -> VoiceSettings:
    return VoiceSettings(_env_file=None, **kw)


SARVAM = {"stt_provider_kn": "sarvam", "sarvam_api_key": "sv-test-key"}


def el_ok(text=TEXT, lang="kan", prob=0.97):
    return httpx.Response(200, json={"text": text, "language_code": lang, "language_probability": prob, "words": []})


class Mock:
    """Per-URL queue of responses (or exceptions to raise); the last item repeats. Records requests."""

    def __init__(self, routes: dict):
        self.routes = {url: list(items) if isinstance(items, list) else [items] for url, items in routes.items()}
        self.calls: dict[str, list[httpx.Request]] = {url: [] for url in routes}

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url not in self.routes:
            raise AssertionError(f"unexpected request to {url}")
        request.read()
        self.calls[url].append(request)
        queue = self.routes[url]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def go(mock: Mock, *args, config: VoiceSettings | None = None, **kwargs):
    async def inner():
        async with mock.client() as http:
            return await transcribe(*args, http=http, config=config or cfg(), **kwargs)

    return asyncio.run(inner())


def has_field(body: bytes, name: str, value: str | None = None) -> bool:
    marker = f'name="{name}"'.encode()
    if marker not in body:
        return False
    return value is None or value.encode() in body.split(marker, 1)[1][:200]


# ----------------------------------------------------------------- happy path


def test_elevenlabs_happy_path_no_hint():
    m = Mock({ELEVENLABS_STT_URL: el_ok()})
    t = go(m, AUDIO, "audio/ogg; codecs=opus")
    assert isinstance(t, Transcript)
    assert t.text == TEXT and t.language_code == "kn" and t.raw_language_code == "kan"
    assert t.language_probability == pytest.approx(0.97)
    assert t.provider == "elevenlabs" and t.duration_ms >= 0
    req = m.calls[ELEVENLABS_STT_URL][-1]
    assert req.headers["xi-api-key"] == "el-test-key"
    assert has_field(req.content, "model_id", "scribe_v1")
    assert not has_field(req.content, "language_code")
    assert has_field(req.content, "file") and AUDIO in req.content  # sent as-is, no conversion


def test_with_hint_sends_language_code():
    m = Mock({ELEVENLABS_STT_URL: el_ok(lang="hin")})
    t = go(m, AUDIO, lang_hint="hi")
    assert t.language_code == "hi"
    assert has_field(m.calls[ELEVENLABS_STT_URL][-1].content, "language_code", "hin")


def test_transcript_is_frozen():
    t = Transcript(
        text="x", language_code="en", raw_language_code="eng", language_probability=None, duration_ms=1, provider="x"
    )
    with pytest.raises(Exception):  # noqa: B017
        t.text = "y"


@pytest.mark.parametrize(
    "raw,ours",
    [
        ("kan", "kn"),
        ("hin", "hi"),
        ("tam", "ta"),
        ("tel", "te"),
        ("eng", "en"),
        ("KAN", "kn"),
        ("kn-IN", "kn"),
        ("mar", "mar"),
        (None, None),
        ("", None),
    ],
)
def test_language_code_mapping(raw, ours):
    assert map_language_code(raw) == ours


def test_unknown_language_kept_and_numbers_untouched():
    raw = "aidu nooru, 500 rupees, ₹1,000"
    t = go(Mock({ELEVENLABS_STT_URL: el_ok(text=raw, lang="mar")}), AUDIO)
    assert t.language_code == "mar" and t.raw_language_code == "mar" and t.text == raw


# ---------------------------------------------------------------------- retry


@pytest.mark.parametrize("first", [httpx.Response(503), httpx.ReadTimeout("slow"), httpx.ConnectError("down")])
def test_retry_then_success(first, caplog):
    caplog.set_level(logging.INFO, logger="app.voice.stt")
    m = Mock({ELEVENLABS_STT_URL: [first, el_ok()]})
    assert go(m, AUDIO).text == TEXT
    assert len(m.calls[ELEVENLABS_STT_URL]) == 2
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_two_failures_raise(caplog):
    caplog.set_level(logging.INFO, logger="app.voice.stt")
    m = Mock({ELEVENLABS_STT_URL: [httpx.ReadTimeout("slow"), httpx.Response(500)]})
    with pytest.raises(STTError):
        go(m, AUDIO)
    assert len(m.calls[ELEVENLABS_STT_URL]) == 2
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_4xx_not_retried():
    m = Mock({ELEVENLABS_STT_URL: httpx.Response(401)})
    with pytest.raises(STTError):
        go(m, AUDIO)
    assert len(m.calls[ELEVENLABS_STT_URL]) == 1


def test_timeout_setting_used():
    m = Mock({ELEVENLABS_STT_URL: el_ok()})
    go(m, AUDIO, config=cfg(stt_timeout_s=2.5))
    assert m.calls[ELEVENLABS_STT_URL][-1].extensions["timeout"]["read"] == 2.5


def test_default_timeout_is_10s():
    assert cfg().stt_timeout_s == 10


# ------------------------------------------------------------ bad responses


@pytest.mark.parametrize(
    "resp",
    [
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={"language_code": "kan"}),
        httpx.Response(200, json={"text": 123}),
        httpx.Response(200, json=["text"]),
    ],
)
def test_malformed_response_raises(resp):
    with pytest.raises(STTError):
        go(Mock({ELEVENLABS_STT_URL: resp}), AUDIO)


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_text_raises(text):
    with pytest.raises(STTError, match="empty transcript"):
        go(Mock({ELEVENLABS_STT_URL: el_ok(text=text)}), AUDIO)


# ------------------------------------------------------------ input validation


@pytest.mark.parametrize(
    "kwargs",
    [
        {"audio": b""},
        {"audio": b"x" * (MAX_AUDIO_BYTES + 1)},
        {"audio": AUDIO, "mime": "video/mp4"},
        {"audio": AUDIO, "mime": "application/octet-stream"},
        {"audio": AUDIO, "mime": ""},
        {"audio": AUDIO, "mime": "audio/"},
        {"audio": AUDIO, "lang_hint": "fr"},
        {"audio": AUDIO, "lang_hint": "kan"},
    ],
)
def test_invalid_audio_rejected_before_network(kwargs):
    m = Mock({ELEVENLABS_STT_URL: el_ok()})
    with pytest.raises(InvalidAudio):
        go(m, **kwargs)
    assert m.calls[ELEVENLABS_STT_URL] == []
    assert issubclass(InvalidAudio, ValueError)


def test_max_size_accepted():
    assert go(Mock({ELEVENLABS_STT_URL: el_ok()}), b"x" * MAX_AUDIO_BYTES).text == TEXT


# ------------------------------------------------------------------- sarvam


def sarvam_ok(text=TEXT):
    return httpx.Response(200, json={"request_id": "r1", "transcript": text, "language_code": "kn-IN"})


def test_sarvam_routing_with_kn_hint():
    m = Mock({ELEVENLABS_STT_URL: el_ok(), SARVAM_STT_URL: sarvam_ok()})
    t = go(m, AUDIO, lang_hint="kn", config=cfg(**SARVAM))
    assert t.provider == "sarvam" and t.language_code == "kn" and t.raw_language_code == "kn-IN" and t.text == TEXT
    assert m.calls[ELEVENLABS_STT_URL] == []
    req = m.calls[SARVAM_STT_URL][-1]
    assert req.headers["api-subscription-key"] == "sv-test-key"
    assert has_field(req.content, "language_code", "kn-IN") and has_field(req.content, "file")


def test_sarvam_used_when_kannada_detected():
    m = Mock({ELEVENLABS_STT_URL: el_ok(text="el text"), SARVAM_STT_URL: sarvam_ok("sarvam text")})
    t = go(m, AUDIO, config=cfg(**SARVAM))
    assert t.provider == "sarvam" and t.text == "sarvam text"


def test_sarvam_failure_falls_back_to_elevenlabs_result():
    m = Mock({ELEVENLABS_STT_URL: el_ok(text="el text"), SARVAM_STT_URL: httpx.Response(502)})
    t = go(m, AUDIO, config=cfg(**SARVAM))
    assert t.provider == "elevenlabs" and t.text == "el text"
    assert len(m.calls[SARVAM_STT_URL]) == 2


def test_sarvam_not_used_for_hindi():
    m = Mock({ELEVENLABS_STT_URL: el_ok(lang="hin"), SARVAM_STT_URL: httpx.Response(500)})
    assert go(m, AUDIO, config=cfg(**SARVAM)).provider == "elevenlabs"
    assert m.calls[SARVAM_STT_URL] == []


def test_kn_hint_uses_elevenlabs_by_default():
    m = Mock({ELEVENLABS_STT_URL: el_ok(), SARVAM_STT_URL: httpx.Response(500)})
    assert go(m, AUDIO, lang_hint="kn").provider == "elevenlabs"
    assert has_field(m.calls[ELEVENLABS_STT_URL][-1].content, "language_code", "kan")
    assert m.calls[SARVAM_STT_URL] == []


# ------------------------------------------------------------------- ffmpeg


class FakeProc:
    def __init__(self, out=b"RIFFwav-bytes", err=b"", returncode=0):
        self._out, self._err, self.returncode = out, err, returncode
        self.stdin_data = None

    async def communicate(self, data):
        self.stdin_data = data
        return self._out, self._err

    def kill(self):
        pass


def test_ffmpeg_conversion_for_unaccepted_mime(monkeypatch):
    proc, calls = FakeProc(), {}

    async def fake_exec(*args, **kwargs):
        calls["args"], calls["kwargs"] = args, kwargs
        return proc

    monkeypatch.setattr(stt.asyncio, "create_subprocess_exec", fake_exec)
    m = Mock({ELEVENLABS_STT_URL: el_ok()})
    assert go(m, AUDIO, "audio/amr").text == TEXT
    args = calls["args"]
    assert args[0] == "ffmpeg"
    assert list(args[args.index("-ar") : args.index("-ar") + 2]) == ["-ar", "16000"]
    assert list(args[args.index("-ac") : args.index("-ac") + 2]) == ["-ac", "1"]
    assert calls["kwargs"]["stdin"] == asyncio.subprocess.PIPE and "shell" not in calls["kwargs"]
    assert proc.stdin_data == AUDIO
    body = m.calls[ELEVENLABS_STT_URL][-1].content
    assert b"RIFFwav-bytes" in body and b"audio/wav" in body


def test_ogg_not_converted(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("ffmpeg should not run for ogg")

    monkeypatch.setattr(stt.asyncio, "create_subprocess_exec", boom)
    go(Mock({ELEVENLABS_STT_URL: el_ok()}), AUDIO, "audio/ogg")


def test_ffmpeg_failure_and_missing(monkeypatch):
    async def failing(*a, **k):
        return FakeProc(out=b"", err=b"bad input", returncode=1)

    monkeypatch.setattr(stt.asyncio, "create_subprocess_exec", failing)
    with pytest.raises(STTError):
        asyncio.run(stt.to_wav_16k_mono(AUDIO))

    async def missing(*a, **k):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(stt.asyncio, "create_subprocess_exec", missing)
    with pytest.raises(STTError, match="ffmpeg not available"):
        asyncio.run(stt.to_wav_16k_mono(AUDIO))


# ------------------------------------------------------------------ logging


def test_logs_do_not_contain_transcript_or_keys(caplog):
    caplog.set_level(logging.DEBUG, logger="app.voice.stt")
    go(Mock({ELEVENLABS_STT_URL: [httpx.Response(503), el_ok()]}), AUDIO)
    assert TEXT not in caplog.text and "baralla" not in caplog.text and "el-test-key" not in caplog.text
    done = [r for r in caplog.records if r.getMessage().startswith("stt done")]
    assert done and done[0].levelno == logging.INFO
    for key in ("provider=", "language=", "latency_ms=", "audio_bytes="):
        assert key in done[0].getMessage()
    attempts = [r.getMessage() for r in caplog.records if "attempt=" in r.getMessage()]
    assert any("attempt=1" in a for a in attempts) and any("attempt=2" in a for a in attempts)
