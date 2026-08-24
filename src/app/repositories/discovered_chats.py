from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DiscoveredChat, DiscoveryProvider, DiscoveryStatus


class DiscoveredChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def existing_keys(self) -> set[str]:
        statement = select(DiscoveredChat.username, DiscoveredChat.tg_chat_id)
        result = await self._session.execute(statement)
        keys: set[str] = set()
        for username, tg_chat_id in result.all():
            if username:
                keys.add(username.lower())
            if tg_chat_id is not None:
                keys.add(str(tg_chat_id))
        return keys

    async def upsert_evaluated(
        self,
        *,
        tg_chat_id: int | None,
        username: str | None,
        title: str | None,
        link: str,
        provider: DiscoveryProvider,
        status: DiscoveryStatus,
        relevance_reason: str | None,
        evaluated_at: datetime,
    ) -> DiscoveredChat | None:
        normalized_username = username.removeprefix("@").lower() if username else None
        conflict_column = (
            DiscoveredChat.username if normalized_username else DiscoveredChat.tg_chat_id
        )
        statement = (
            insert(DiscoveredChat)
            .values(
                tg_chat_id=tg_chat_id,
                username=normalized_username,
                title=title,
                link=link,
                provider=provider,
                status=status,
                relevance_reason=relevance_reason,
                evaluated_at=evaluated_at,
            )
            .on_conflict_do_update(
                index_elements=[conflict_column],
                set_={
                    "tg_chat_id": tg_chat_id,
                    "title": title,
                    "link": link,
                    "status": status,
                    "relevance_reason": relevance_reason,
                    "evaluated_at": evaluated_at,
                },
            )
            .returning(DiscoveredChat)
        )
        try:
            result = await self._session.execute(statement)
        except IntegrityError:
            await self._session.rollback()
            return None
        return result.scalar_one_or_none()

    async def list_by_status(self, status: DiscoveryStatus) -> Sequence[DiscoveredChat]:
        statement = (
            select(DiscoveredChat)
            .where(DiscoveredChat.status == status)
            .order_by(DiscoveredChat.created_at)
        )
        result = await self._session.execute(statement)
        return result.scalars().all()
