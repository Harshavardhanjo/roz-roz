"""Message persistence for the voice pipeline (Postgres `message` table via app.models.Message).

Sync SQLAlchemy calls run in a worker thread so the event loop is never blocked. Before consent only the dedupe row
(wa_message_id, media_kind, helper_id) is stored; transcripts and replies are written after the reply goes out.
"""

import asyncio
import uuid
from typing import Protocol

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from ..db import SessionLocal
from ..models import Message


def _uuid(value) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


class MessageStore(Protocol):
    async def insert_inbound(self, wa_message_id: str, media_kind: str | None) -> uuid.UUID | None:
        """Insert the dedupe row; None if this wa_message_id was already seen."""

    async def set_helper(self, message_id: uuid.UUID, helper_id: str | None) -> None: ...

    async def complete(
        self,
        message_id: uuid.UUID,
        *,
        helper_id: str | None,
        transcript: str | None,
        lang: str | None,
        agent_run_id: str | None,
        reply_text: str | None,
        latency_ms: dict[str, int],
    ) -> None: ...

    async def insert_outbound(self, *, helper_id: str | None, reply_text: str, lang: str | None) -> uuid.UUID: ...


class PgMessageStore:
    def __init__(self, session_factory=SessionLocal):
        self._sessions = session_factory

    def _insert_inbound(self, wa_message_id: str, media_kind: str | None) -> uuid.UUID | None:
        stmt = (
            insert(Message)
            .values(id=uuid.uuid4(), direction="in", wa_message_id=wa_message_id, media_kind=media_kind)
            .on_conflict_do_nothing(index_elements=["wa_message_id"])
            .returning(Message.id)
        )
        with self._sessions() as db:
            new_id = db.scalar(stmt)
            db.commit()
            return new_id

    async def insert_inbound(self, wa_message_id: str, media_kind: str | None) -> uuid.UUID | None:
        return await asyncio.to_thread(self._insert_inbound, wa_message_id, media_kind)

    def _update(self, message_id: uuid.UUID, **values) -> None:
        with self._sessions() as db:
            db.execute(update(Message).where(Message.id == message_id).values(**values))
            db.commit()

    async def set_helper(self, message_id: uuid.UUID, helper_id: str | None) -> None:
        hid = _uuid(helper_id)
        if hid is not None:
            await asyncio.to_thread(self._update, message_id, helper_id=hid)

    async def complete(
        self,
        message_id: uuid.UUID,
        *,
        helper_id: str | None,
        transcript: str | None,
        lang: str | None,
        agent_run_id: str | None,
        reply_text: str | None,
        latency_ms: dict[str, int],
    ) -> None:
        await asyncio.to_thread(
            self._update,
            message_id,
            helper_id=_uuid(helper_id),
            transcript=transcript,
            lang=lang,
            agent_run_id=_uuid(agent_run_id),
            reply_text=reply_text,
            latency_ms=dict(latency_ms),
        )

    def _insert_outbound(self, helper_id: str | None, reply_text: str, lang: str | None) -> uuid.UUID:
        with self._sessions() as db:
            row = Message(
                id=uuid.uuid4(),
                direction="out",
                helper_id=_uuid(helper_id),
                media_kind="text",
                reply_text=reply_text,
                lang=lang,
            )
            db.add(row)
            db.commit()
            return row.id

    async def insert_outbound(self, *, helper_id: str | None, reply_text: str, lang: str | None) -> uuid.UUID:
        return await asyncio.to_thread(self._insert_outbound, helper_id, reply_text, lang)
