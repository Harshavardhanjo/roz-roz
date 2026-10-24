"""Outbound WhatsApp gateways: Meta Cloud API (default) and a minimal Twilio sandbox client (WA_PROVIDER=twilio).

Both expose `send_text(to_e164, body)` and `download_media(media_ref) -> (bytes, mime)`. Media is audio/* only and at
most 16 MB. Phone numbers are masked and media URLs / tokens are never logged.
"""

import base64
import hashlib
import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol
from urllib.parse import urlparse

import httpx

from ..config import settings
from .voice_config import VoiceSettings, mask_phone, voice_settings

log = logging.getLogger(__name__)

# httpx logs every request URL at INFO; media URLs are short-lived bearer links and must not land in INFO logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

MAX_MEDIA_BYTES = 16 * 1024 * 1024
MAX_TEXT_CHARS = 4096  # WhatsApp text body limit
GRAPH_BASE = "https://graph.facebook.com"
TWILIO_API_BASE = "https://api.twilio.com"
HTTP_TIMEOUT_S = 10.0


class WhatsAppError(Exception):
    """Sending or downloading via the WhatsApp gateway failed."""


class MediaRejected(WhatsAppError):
    """Media is not audio, empty, or over the size cap."""


class MediaTooLarge(MediaRejected):
    pass


class WAClient(Protocol):
    async def send_text(self, to_e164: str, body: str) -> str | None: ...

    async def download_media(self, media_ref: str) -> tuple[bytes, str]: ...


def base_mime(mime: str | None) -> str:
    return (mime or "").split(";")[0].strip().lower()


def is_audio_mime(mime: str | None) -> bool:
    m = base_mime(mime)
    return m.startswith("audio/") and m != "audio/"


@asynccontextmanager
async def _client(http: httpx.AsyncClient | None) -> AsyncIterator[httpx.AsyncClient]:
    if http is not None:
        yield http
        return
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as c:
        yield c


async def _read_capped(resp: httpx.Response, limit: int = MAX_MEDIA_BYTES) -> bytes:
    length = resp.headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > limit:
        raise MediaTooLarge(f"content-length {length} over {limit} bytes")
    buf = bytearray()
    async for chunk in resp.aiter_bytes():
        buf.extend(chunk)
        if len(buf) > limit:
            raise MediaTooLarge(f"media over {limit} bytes")
    if not buf:
        raise MediaRejected("empty media")
    return bytes(buf)


# ---------------------------------------------------------------- signatures


def verify_meta_signature(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    """X-Hub-Signature-256 == "sha256=" + HMAC_SHA256(app_secret, raw_body)."""
    if not app_secret or not header:
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.strip())


def twilio_signature(auth_token: str, url: str, params: list[tuple[str, str]]) -> str:
    """Twilio: base64(HMAC-SHA1(auth_token, url + concat(sorted key+value)))."""
    data = url + "".join(k + v for k, v in sorted(params))
    return base64.b64encode(hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def verify_twilio_signature(auth_token: str, url: str, params: list[tuple[str, str]], header: str | None) -> bool:
    if not auth_token or not header:
        return False
    return hmac.compare_digest(twilio_signature(auth_token, url, params), header.strip())


# ---------------------------------------------------------------- Meta


class MetaWhatsAppClient:
    def __init__(self, http: httpx.AsyncClient | None = None):
        self._http = http

    @property
    def _base(self) -> str:
        return f"{GRAPH_BASE}/{settings.wa_graph_version}"

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {settings.wa_access_token}"}

    async def send_text(self, to_e164: str, body: str) -> str | None:
        url = f"{self._base}/{settings.wa_phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to_e164.lstrip("+"),
            "type": "text",
            "text": {"body": body[:MAX_TEXT_CHARS]},
        }
        try:
            async with _client(self._http) as http:
                resp = await http.post(url, json=payload, headers=self._headers)
        except httpx.HTTPError as e:
            raise WhatsAppError(f"send failed: {type(e).__name__}") from e
        if resp.status_code >= 400:
            raise WhatsAppError(f"send failed: HTTP {resp.status_code}")
        try:
            msg_id = (resp.json().get("messages") or [{}])[0].get("id")
        except (ValueError, AttributeError, IndexError):
            msg_id = None
        log.info("wa send ok provider=meta to=%s status=%s", mask_phone(to_e164), resp.status_code)
        return msg_id

    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        """media_ref is the Graph media id. Two hops: id -> url, url -> bytes (same bearer; the URL expires)."""
        try:
            async with _client(self._http) as http:
                meta = await http.get(f"{self._base}/{media_ref}", headers=self._headers)
                if meta.status_code >= 400:
                    raise WhatsAppError(f"media lookup failed: HTTP {meta.status_code}")
                try:
                    info = meta.json()
                    url = info["url"]
                except (ValueError, KeyError, TypeError) as e:
                    raise WhatsAppError("media lookup returned no url") from e
                mime = base_mime(info.get("mime_type"))
                if mime and not mime.startswith("audio/"):
                    raise MediaRejected(f"media mime {mime} is not audio")
                size = info.get("file_size")
                if isinstance(size, int) and size > MAX_MEDIA_BYTES:
                    raise MediaTooLarge(f"file_size {size} over {MAX_MEDIA_BYTES} bytes")
                if urlparse(url).scheme != "https":
                    raise WhatsAppError("media url is not https")
                async with http.stream("GET", url, headers=self._headers) as resp:
                    if resp.status_code >= 400:
                        raise WhatsAppError(f"media download failed: HTTP {resp.status_code}")
                    ctype = base_mime(resp.headers.get("content-type"))
                    if ctype and not ctype.startswith("audio/") and not mime:
                        raise MediaRejected(f"media content-type {ctype} is not audio")
                    data = await _read_capped(resp)
        except httpx.HTTPError as e:
            raise WhatsAppError(f"media download failed: {type(e).__name__}") from e
        return data, mime or (ctype if ctype.startswith("audio/") else "audio/ogg")


# ---------------------------------------------------------------- Twilio (team sandbox only)


class TwilioClient:
    """Minimal Twilio WhatsApp sandbox client; credentials from TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN /
    TWILIO_WHATSAPP_FROM."""

    def __init__(self, http: httpx.AsyncClient | None = None, config: VoiceSettings | None = None):
        cfg = config or voice_settings
        self._http = http
        self.account_sid = cfg.twilio_account_sid
        self.auth_token = cfg.twilio_auth_token
        frm = cfg.twilio_whatsapp_from.removeprefix("whatsapp:")
        self.from_number = frm if not frm or frm.startswith("+") else "+" + frm

    @property
    def _auth(self) -> tuple[str, str]:
        return (self.account_sid, self.auth_token)

    async def send_text(self, to_e164: str, body: str) -> str | None:
        if not (self.account_sid and self.auth_token and self.from_number):
            raise WhatsAppError("twilio credentials missing")
        to = to_e164 if to_e164.startswith("+") else "+" + to_e164
        url = f"{TWILIO_API_BASE}/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        data = {"From": f"whatsapp:{self.from_number}", "To": f"whatsapp:{to}", "Body": body[:1600]}
        try:
            async with _client(self._http) as http:
                resp = await http.post(url, data=data, auth=self._auth)
        except httpx.HTTPError as e:
            raise WhatsAppError(f"send failed: {type(e).__name__}") from e
        if resp.status_code >= 400:
            raise WhatsAppError(f"send failed: HTTP {resp.status_code}")
        log.info("wa send ok provider=twilio to=%s status=%s", mask_phone(to), resp.status_code)
        try:
            return resp.json().get("sid")
        except (ValueError, AttributeError):
            return None

    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        """media_ref is MediaUrl0 from the webhook; only https://api.twilio.com URLs are fetched."""
        parsed = urlparse(media_ref)
        if parsed.scheme != "https" or parsed.hostname != "api.twilio.com":
            raise MediaRejected("twilio media url must be https://api.twilio.com/...")
        try:
            async with (
                _client(self._http) as http,
                http.stream("GET", media_ref, auth=self._auth, follow_redirects=True) as resp,
            ):
                if resp.status_code >= 400:
                    raise WhatsAppError(f"media download failed: HTTP {resp.status_code}")
                mime = base_mime(resp.headers.get("content-type"))
                if mime and not mime.startswith("audio/"):
                    raise MediaRejected(f"media mime {mime} is not audio")
                data = await _read_capped(resp)
        except httpx.HTTPError as e:
            raise WhatsAppError(f"media download failed: {type(e).__name__}") from e
        return data, mime or "audio/ogg"


def make_wa_client(http: httpx.AsyncClient | None = None, config: VoiceSettings | None = None) -> WAClient:
    cfg = config or voice_settings
    if cfg.wa_provider == "twilio":
        return TwilioClient(http, cfg)
    return MetaWhatsAppClient(http)


# ---------------------------------------------------------------- module-level helpers (Meta)


async def download_media(media_id: str) -> bytes:
    """Resolve the media URL, then fetch the bytes immediately (the URL expires)."""
    data, _ = await MetaWhatsAppClient().download_media(media_id)
    return data


async def send_text(to_e164_digits: str, body: str) -> str | None:
    return await MetaWhatsAppClient().send_text(to_e164_digits, body)
