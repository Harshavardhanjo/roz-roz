"""ElevenLabs speech-to-text. Confirm the current Scribe model id in ElevenLabs' docs (ELEVENLABS_STT_MODEL)."""
import httpx

from ..config import settings

STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"


async def transcribe(audio: bytes, mime: str = "audio/ogg", language_code: str | None = None) -> dict:
    data = {"model_id": settings.elevenlabs_stt_model}
    if language_code:
        data["language_code"] = language_code
    files = {"file": ("voice.ogg", audio, mime)}
    async with httpx.AsyncClient(timeout=6) as client:
        r = await client.post(STT_URL, headers={"xi-api-key": settings.elevenlabs_api_key}, data=data, files=files)
        j = r.raise_for_status().json()
    # Keep the raw transcript: the liaison agent resolves spoken numbers and dates.
    return {"text": j.get("text", ""), "language_code": j.get("language_code"),
            "language_probability": j.get("language_probability")}
