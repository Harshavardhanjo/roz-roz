import httpx

from ..config import settings


def _graph(path: str) -> str:
    return f"https://graph.facebook.com/{settings.wa_graph_version}/{path}"


def _auth() -> dict:
    return {"Authorization": f"Bearer {settings.wa_access_token}"}


async def download_media(media_id: str) -> bytes:
    """Resolve the media URL, then fetch the bytes immediately (the URL expires)."""
    async with httpx.AsyncClient(timeout=10) as client:
        meta = (await client.get(_graph(media_id), headers=_auth())).raise_for_status().json()
        return (await client.get(meta["url"], headers=_auth())).raise_for_status().content


async def send_text(to_e164_digits: str, body: str) -> dict:
    payload = {"messaging_product": "whatsapp", "to": to_e164_digits, "type": "text", "text": {"body": body}}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(_graph(f"{settings.wa_phone_number_id}/messages"), headers=_auth(), json=payload)
        return r.raise_for_status().json()
