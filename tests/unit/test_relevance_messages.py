import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import session_scope
from app.db.models import MonitoredChatOrigin
from app.llm.relevance import MAX_MESSAGE_CONTEXT_CHARS, RelevanceChecker
from app.repositories.leads import LeadRepository
from app.repositories.monitored_chats import MonitoredChatRepository
from app.services.lead_service import LeadService
from tests.conftest import (
    FakeOwnerNotifier,
    FakeVerdictLlm,
    StubPortfolioSummary,
    make_group_message,
)
from tests.unit.fixtures.relevance_messages import (
    CHAT_CASES,
    MESSAGE_CASES,
    RelevanceCase,
    empty_text_message_cases,
    message_cases_without_empty_text,
)

MONITORED_CHAT_ID = -1001


async def seed_monitored_chat(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_scope(session_factory) as session:
        chat = await MonitoredChatRepository(session).upsert(
            tg_chat_id=MONITORED_CHAT_ID,
            title="Мониторимый чат",
            username="@monitored_chat",
            origin=MonitoredChatOrigin.sources_file,
        )
        return chat.id


def build_service(
    session_factory: async_sessionmaker[AsyncSession],
    llm: FakeVerdictLlm,
    notifier: FakeOwnerNotifier,
) -> LeadService:
    return LeadService(
        session_factory,
        RelevanceChecker(llm),
        StubPortfolioSummary(),
        notifier,
    )


@pytest.mark.parametrize(
    "case",
    message_cases_without_empty_text(),
    ids=lambda case: f"{case.kind.value}:{case.description}",
)
async def test_message_case_takes_the_expected_branch(
    case: RelevanceCase, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    chat_id = await seed_monitored_chat(session_factory)
    llm = FakeVerdictLlm(MESSAGE_CASES)
    notifier = FakeOwnerNotifier()

    lead = await build_service(session_factory, llm, notifier).process_message(
        make_group_message(case.text)
    )

    async with session_scope(session_factory) as session:
        stored = list(await LeadRepository(session).list_for_chat(chat_id))

    assert (lead is not None) is case.expected_relevant
    assert len(stored) == (1 if case.expected_relevant else 0)
    assert len(notifier.sent) == (1 if case.expected_relevant else 0)


@pytest.mark.parametrize(
    "case",
    empty_text_message_cases(),
    ids=lambda case: f"{case.kind.value}:{case.description}",
)
async def test_empty_message_never_reaches_the_model(
    case: RelevanceCase, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    chat_id = await seed_monitored_chat(session_factory)
    llm = FakeVerdictLlm(MESSAGE_CASES)
    notifier = FakeOwnerNotifier()

    lead = await build_service(session_factory, llm, notifier).process_message(
        make_group_message(case.text)
    )

    async with session_scope(session_factory) as session:
        stored = list(await LeadRepository(session).list_for_chat(chat_id))

    assert lead is None
    assert llm.prompts == []
    assert stored == []
    assert notifier.sent == []


async def test_long_message_is_truncated_before_the_model_call(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_monitored_chat(session_factory)
    long_case = next(case for case in MESSAGE_CASES if len(case.text) > MAX_MESSAGE_CONTEXT_CHARS)
    llm = FakeVerdictLlm(MESSAGE_CASES)

    await build_service(session_factory, llm, FakeOwnerNotifier()).process_message(
        make_group_message(long_case.text)
    )

    assert len(llm.prompts) == 1
    assert long_case.text not in llm.prompts[0]
    assert long_case.text[:MAX_MESSAGE_CONTEXT_CHARS] in llm.prompts[0]


@pytest.mark.parametrize(
    "case",
    [case for case in CHAT_CASES if case.text.strip()],
    ids=lambda case: f"{case.kind.value}:{case.description}",
)
async def test_chat_case_produces_the_expected_verdict(case: RelevanceCase) -> None:
    llm = FakeVerdictLlm(CHAT_CASES)

    verdict = await RelevanceChecker(llm).evaluate_chat(
        case.text, StubPortfolioSummary().build_summary()
    )

    assert verdict.is_relevant is case.expected_relevant


def test_empty_chat_history_case_stays_irrelevant() -> None:
    empty_cases = [case for case in CHAT_CASES if not case.text.strip()]

    assert empty_cases
    assert all(case.expected_relevant is False for case in empty_cases)
