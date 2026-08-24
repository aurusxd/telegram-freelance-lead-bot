from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.keyboards import build_contact_url
from app.db.base import session_scope
from app.db.models import MonitoredChatOrigin
from app.llm.relevance import RelevanceChecker
from app.repositories.leads import LeadRepository
from app.repositories.monitored_chats import MonitoredChatRepository
from app.services.lead_service import LeadService
from tests.conftest import (
    BrokenJsonLlm,
    FakeOwnerNotifier,
    FakeVerdictLlm,
    StubPortfolioSummary,
    make_group_message,
)
from tests.unit.fixtures.relevance_messages import MESSAGE_CASES

MONITORED_CHAT_ID = -1001
UNKNOWN_CHAT_ID = -9009
RELEVANT_TEXT = MESSAGE_CASES[0].text


async def seed_monitored_chat(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    is_active: bool = True,
) -> int:
    async with session_scope(session_factory) as session:
        repository = MonitoredChatRepository(session)
        chat = await repository.upsert(
            tg_chat_id=MONITORED_CHAT_ID,
            title="Мониторимый чат",
            username="@monitored_chat",
            origin=MonitoredChatOrigin.sources_file,
        )
        if not is_active:
            await repository.deactivate_by_username("@monitored_chat")
        return chat.id


def build_service(
    session_factory: async_sessionmaker[AsyncSession],
    llm: FakeVerdictLlm | BrokenJsonLlm,
    notifier: FakeOwnerNotifier,
) -> LeadService:
    return LeadService(session_factory, RelevanceChecker(llm), StubPortfolioSummary(), notifier)


async def stored_leads(session_factory: async_sessionmaker[AsyncSession], chat_id: int):
    async with session_scope(session_factory) as session:
        return list(await LeadRepository(session).list_for_chat(chat_id))


async def test_relevant_message_creates_lead_and_marks_notification(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chat_id = await seed_monitored_chat(session_factory)
    notifier = FakeOwnerNotifier()

    lead = await build_service(
        session_factory, FakeVerdictLlm(MESSAGE_CASES), notifier
    ).process_message(make_group_message(RELEVANT_TEXT))

    assert lead is not None
    leads = await stored_leads(session_factory, chat_id)
    assert len(leads) == 1
    assert leads[0].tg_user_id == 555
    assert leads[0].message_text == RELEVANT_TEXT
    assert leads[0].notified_at is not None
    assert notifier.sent == [(lead.id, "Мониторимый чат")]


async def test_repeated_message_does_not_create_second_lead(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chat_id = await seed_monitored_chat(session_factory)
    notifier = FakeOwnerNotifier()
    service = build_service(session_factory, FakeVerdictLlm(MESSAGE_CASES), notifier)
    message = make_group_message(RELEVANT_TEXT)

    first = await service.process_message(message)
    second = await service.process_message(message)

    assert first is not None
    assert second is None
    assert len(await stored_leads(session_factory, chat_id)) == 1
    assert len(notifier.sent) == 1


async def test_message_from_unmonitored_chat_is_ignored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chat_id = await seed_monitored_chat(session_factory)
    llm = FakeVerdictLlm(MESSAGE_CASES)
    notifier = FakeOwnerNotifier()

    lead = await build_service(session_factory, llm, notifier).process_message(
        make_group_message(RELEVANT_TEXT, chat_id=UNKNOWN_CHAT_ID)
    )

    assert lead is None
    assert llm.prompts == []
    assert await stored_leads(session_factory, chat_id) == []
    assert notifier.sent == []


async def test_message_from_deactivated_chat_is_ignored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chat_id = await seed_monitored_chat(session_factory, is_active=False)
    llm = FakeVerdictLlm(MESSAGE_CASES)

    lead = await build_service(session_factory, llm, FakeOwnerNotifier()).process_message(
        make_group_message(RELEVANT_TEXT)
    )

    assert lead is None
    assert llm.prompts == []
    assert await stored_leads(session_factory, chat_id) == []


async def test_broken_llm_json_retries_once_then_degrades(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chat_id = await seed_monitored_chat(session_factory)
    llm = BrokenJsonLlm()
    notifier = FakeOwnerNotifier()

    lead = await build_service(session_factory, llm, notifier).process_message(
        make_group_message(RELEVANT_TEXT)
    )

    assert lead is None
    assert llm.calls == 2
    assert await stored_leads(session_factory, chat_id) == []
    assert notifier.sent == []


async def test_failed_notification_keeps_lead_unnotified(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chat_id = await seed_monitored_chat(session_factory)
    notifier = FakeOwnerNotifier(delivered=False)

    lead = await build_service(
        session_factory, FakeVerdictLlm(MESSAGE_CASES), notifier
    ).process_message(make_group_message(RELEVANT_TEXT))

    assert lead is not None
    leads = await stored_leads(session_factory, chat_id)
    assert len(leads) == 1
    assert leads[0].notified_at is None


def test_contact_url_prefers_username() -> None:
    assert build_contact_url("@customer", 555) == "https://t.me/customer"
    assert build_contact_url("customer", 555) == "https://t.me/customer"


def test_contact_url_falls_back_to_user_id() -> None:
    assert build_contact_url(None, 555) == "tg://user?id=555"
