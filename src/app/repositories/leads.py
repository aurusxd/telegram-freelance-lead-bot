from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Lead


class LeadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_if_absent(
        self,
        *,
        monitored_chat_id: int,
        tg_message_id: int,
        tg_user_id: int,
        tg_username: str | None,
        tg_first_name: str | None,
        message_text: str,
        relevance_reason: str,
    ) -> Lead | None:
        statement = (
            insert(Lead)
            .values(
                monitored_chat_id=monitored_chat_id,
                tg_message_id=tg_message_id,
                tg_user_id=tg_user_id,
                tg_username=tg_username,
                tg_first_name=tg_first_name,
                message_text=message_text,
                relevance_reason=relevance_reason,
            )
            .on_conflict_do_nothing(index_elements=[Lead.monitored_chat_id, Lead.tg_message_id])
            .returning(Lead)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def mark_notified(self, lead_id: int, notified_at: datetime) -> None:
        lead = await self._session.get(Lead, lead_id)
        if lead is None:
            return
        lead.notified_at = notified_at
        await self._session.flush()

    async def list_for_chat(self, monitored_chat_id: int) -> Sequence[Lead]:
        statement = (
            select(Lead).where(Lead.monitored_chat_id == monitored_chat_id).order_by(Lead.found_at)
        )
        result = await self._session.execute(statement)
        return result.scalars().all()
