"""Voice-only settings (env-driven). Shared settings (WA_*, ELEVENLABS_*, TOOLS_TOKEN, ...) live in app.config."""

import re
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class VoiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Kannada STT: elevenlabs (default) or sarvam (needs SARVAM_API_KEY).
    stt_provider_kn: Literal["elevenlabs", "sarvam"] = "elevenlabs"
    sarvam_api_key: str = ""
    # Real Scribe calls on short clips took 6.3-6.6 s from the venue; 6 s cut them off. Two tries plus the 30 s
    # liaison still fit Vercel's 60 s limit.
    stt_timeout_s: float = 10.0

    # meta: WhatsApp Cloud API (default). twilio: the team's Twilio sandbox (/webhooks/twilio).
    wa_provider: Literal["meta", "twilio"] = "meta"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""

    # POST /api/dev/voice (still needs Authorization: Bearer $TOOLS_TOKEN).
    dev_voice_enabled: bool = True


voice_settings = VoiceSettings()

_E164 = re.compile(r"^[1-9]\d{7,14}$")


def e164_digits(raw: str | None) -> str | None:
    """'+91 98111 00009' / 'whatsapp:+9198...' / '9198...' -> '9198...' (digits only), or None if not E.164."""
    if not isinstance(raw, str):
        return None
    s = raw.strip().removeprefix("whatsapp:").strip().removeprefix("+")
    s = re.sub(r"[\s\-()]", "", s)
    return s if _E164.match(s) else None


def mask_phone(raw: str | None) -> str:
    """Never log a phone number: keep only the last 4 digits."""
    digits = re.sub(r"\D", "", raw or "")
    return "***" + digits[-4:] if len(digits) >= 4 else "***"
