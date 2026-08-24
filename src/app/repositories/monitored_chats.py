from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MonitoredChat, MonitoredChatOrigin


def normalize_username(username: str) -> str:
    return username.strip().removeprefix("@").strip().lower()


class MonitoredChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        tg_chat_id: int,
        title: str,
        username: str | None,
        origin: MonitoredChatOrigin,
        invite_link: str | None = None,
    ) -> MonitoredChat:
        normalized_username = normalize_username(username) if username else None
        statement = (
            insert(MonitoredChat)
            .values(
                tg_chat_id=tg_chat_id,
                title=title,
                username=normalized_username,
                invite_link=invite_link,
                is_active=True,
                origin=origin,
            )
            .on_conflict_do_update(
                index_elements=[MonitoredChat.tg_chat_id],
                set_={
                    "title": title,
                    "username": normalized_username,
                    "invite_link": invite_link,
                    "is_active": True,
                    "origin": origin,
                },
            )
            .returning(MonitoredChat)
        )
        result = await self._session.execute(statement)
        return result.scalar_one()

    async def deactivate_by_username(self, username: str) -> bool:
        chat = await self.get_by_username(username)
        if chat is None:
            return False
        chat.is_active = False
        await self._session.flush()
        return True

    async def get_by_username(self, username: str) -> MonitoredChat | None:
        statement = select(MonitoredChat).where(
            MonitoredChat.username == normalize_username(username)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_tg_chat_id(self, tg_chat_id: int) -> MonitoredChat | None:
        statement = select(MonitoredChat).where(MonitoredChat.tg_chat_id == tg_chat_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[MonitoredChat]:
        statement = select(MonitoredChat).order_by(MonitoredChat.added_at)
        result = await self._session.execute(statement)
        return result.scalars().all()

    async def existing_keys(self) -> set[str]:
        statement = select(MonitoredChat.username, MonitoredChat.tg_chat_id)
        result = await self._session.execute(statement)
        keys: set[str] = set()
        for username, tg_chat_id in result.all():
            if username:
                keys.add(username.lower())
            keys.add(str(tg_chat_id))
        return keys

    async def list_active(self) -> Sequence[MonitoredChat]:
        statement = (
            select(MonitoredChat)
            .where(MonitoredChat.is_active.is_(True))
            .order_by(MonitoredChat.added_at)
        )
        result = await self._session.execute(statement)
        return result.scalars().all()
