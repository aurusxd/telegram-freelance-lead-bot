from typing import Protocol

from aiogram.types import Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import session_scope, utcnow
from app.db.models import Lead, MonitoredChat
from app.llm.relevance import RelevanceChecker
from app.portfolio.service import PortfolioSummarySource
from app.repositories.leads import LeadRepository
from app.repositories.monitored_chats import MonitoredChatRepository


class OwnerNotifier(Protocol):
    async def notify_lead(self, lead: Lead, chat_title: str) -> bool: ...


def extract_text(message: Message) -> str:
    return (message.text or message.caption or "").strip()


class LeadService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        relevance_checker: RelevanceChecker,
        portfolio: PortfolioSummarySource,
        notifier: OwnerNotifier,
    ) -> None:
        self._session_factory = session_factory
        self._relevance_checker = relevance_checker
        self._portfolio = portfolio
        self._notifier = notifier

    async def process_message(self, message: Message) -> Lead | None:
        text = extract_text(message)
        if not text or message.from_user is None:
            return None

        chat = await self._find_active_chat(message.chat.id)
        if chat is None:
            return None

        verdict = await self._relevance_checker.evaluate_message(
            text, self._portfolio.build_summary()
        )
        if not verdict.is_relevant:
            logger.debug("message {} judged irrelevant", message.message_id)
            return None

        lead = await self._store_lead(chat, message, text, verdict.reason)
        if lead is None:
            logger.debug("lead for message {} already stored", message.message_id)
            return None

        await self._notify_owner(lead, chat.title)
        return lead

    async def _find_active_chat(self, tg_chat_id: int) -> MonitoredChat | None:
        async with session_scope(self._session_factory) as session:
            chat = await MonitoredChatRepository(session).get_by_tg_chat_id(tg_chat_id)
        if chat is None or not chat.is_active:
            return None
        return chat

    async def _store_lead(
        self,
        chat: MonitoredChat,
        message: Message,
        text: str,
        relevance_reason: str,
    ) -> Lead | None:
        author = message.from_user
        if author is None:
            return None
        async with session_scope(self._session_factory) as session:
            return await LeadRepository(session).create_if_absent(
                monitored_chat_id=chat.id,
                tg_message_id=message.message_id,
                tg_user_id=author.id,
                tg_username=author.username,
                tg_first_name=author.first_name,
                message_text=text,
                relevance_reason=relevance_reason,
            )

    async def _notify_owner(self, lead: Lead, chat_title: str) -> None:
        if not await self._notifier.notify_lead(lead, chat_title):
            logger.warning("owner notification failed for lead {}", lead.id)
            return
        async with session_scope(self._session_factory) as session:
            await LeadRepository(session).mark_notified(lead.id, utcnow())
