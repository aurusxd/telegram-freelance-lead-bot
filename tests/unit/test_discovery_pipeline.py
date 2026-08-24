import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import session_scope
from app.db.models import DiscoveryProvider, DiscoveryStatus, MonitoredChatOrigin
from app.discovery.pipeline import EMPTY_HISTORY_REASON, DiscoveryPipeline
from app.discovery.query_generator import QueryGenerator
from app.llm.relevance import RelevanceChecker
from app.repositories.discovered_chats import DiscoveredChatRepository
from app.repositories.monitored_chats import MonitoredChatRepository
from app.repositories.search_queries import SearchQueryRepository
from tests.conftest import (
    FakeChatResolver,
    FakeHistoryReader,
    FakeQueryLlm,
    FakeSourceProvider,
    FakeVerdictLlm,
    StubPortfolioSummary,
    make_candidate,
    make_resolved_chat,
)
from tests.unit.fixtures.relevance_messages import CHAT_CASES, RelevanceCase

QUERIES = ["заказы на телеграм ботов", "нужен парсер разработчик", "фриланс python заказы"]
RELEVANT_CHAT = CHAT_CASES[0]
IRRELEVANT_CHAT = CHAT_CASES[1]


def build_pipeline(
    session_factory: async_sessionmaker[AsyncSession],
    providers: list[FakeSourceProvider],
    resolver: FakeChatResolver,
    history: FakeHistoryReader,
    verdict_llm: FakeVerdictLlm,
    *,
    queries_per_run: int = 3,
    messages_per_chat: int = 20,
) -> DiscoveryPipeline:
    return DiscoveryPipeline(
        session_factory,
        providers,
        QueryGenerator(FakeQueryLlm(QUERIES)),
        resolver,
        history,
        RelevanceChecker(verdict_llm),
        StubPortfolioSummary(),
        queries_per_run=queries_per_run,
        messages_per_chat=messages_per_chat,
    )


async def stored_chats(session_factory: async_sessionmaker[AsyncSession], status: DiscoveryStatus):
    async with session_scope(session_factory) as session:
        return list(await DiscoveredChatRepository(session).list_by_status(status))


async def test_approved_candidate_is_stored_with_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeSourceProvider([make_candidate("python_jobs")])
    resolver = FakeChatResolver(
        {"@python_jobs": make_resolved_chat("@python_jobs", -1001, "Работа")}
    )
    history = FakeHistoryReader({-1001: RELEVANT_CHAT.text.split("\n")})

    result = await build_pipeline(
        session_factory, [provider], resolver, history, FakeVerdictLlm(CHAT_CASES)
    ).run_once()

    approved = await stored_chats(session_factory, DiscoveryStatus.approved)
    assert result.approved == 1
    assert result.rejected == 0
    assert len(approved) == 1
    assert approved[0].username == "python_jobs"
    assert approved[0].tg_chat_id == -1001
    assert approved[0].title == "Работа"
    assert approved[0].provider is DiscoveryProvider.searxng
    assert approved[0].relevance_reason
    assert approved[0].evaluated_at is not None
    assert history.calls == [(-1001, 20)]


async def test_rejected_candidate_is_stored_and_hidden_from_approved(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeSourceProvider([make_candidate("daily_chat")])
    resolver = FakeChatResolver({"@daily_chat": make_resolved_chat("@daily_chat", -1002)})
    history = FakeHistoryReader({-1002: IRRELEVANT_CHAT.text.split("\n")})

    result = await build_pipeline(
        session_factory, [provider], resolver, history, FakeVerdictLlm(CHAT_CASES)
    ).run_once()

    assert result.rejected == 1
    assert await stored_chats(session_factory, DiscoveryStatus.approved) == []
    assert len(await stored_chats(session_factory, DiscoveryStatus.rejected)) == 1


@pytest.mark.parametrize(
    "case",
    [case for case in CHAT_CASES if case.text.strip()],
    ids=lambda case: f"{case.kind.value}:{case.description}",
)
async def test_chat_fixture_case_takes_the_expected_branch(
    case: RelevanceCase, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    provider = FakeSourceProvider([make_candidate("fixture_chat")])
    resolver = FakeChatResolver({"@fixture_chat": make_resolved_chat("@fixture_chat", -1500)})
    history = FakeHistoryReader({-1500: case.text.split("\n")})

    result = await build_pipeline(
        session_factory, [provider], resolver, history, FakeVerdictLlm(CHAT_CASES)
    ).run_once()

    approved = await stored_chats(session_factory, DiscoveryStatus.approved)
    assert result.approved == (1 if case.expected_relevant else 0)
    assert len(approved) == (1 if case.expected_relevant else 0)


async def test_empty_history_is_rejected_without_calling_the_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeSourceProvider([make_candidate("silent_chat")])
    resolver = FakeChatResolver({"@silent_chat": make_resolved_chat("@silent_chat", -1003)})
    verdict_llm = FakeVerdictLlm(CHAT_CASES)

    result = await build_pipeline(
        session_factory, [provider], resolver, FakeHistoryReader(), verdict_llm
    ).run_once()

    rejected = await stored_chats(session_factory, DiscoveryStatus.rejected)
    assert result.rejected == 1
    assert verdict_llm.prompts == []
    assert rejected[0].relevance_reason == EMPTY_HISTORY_REASON


async def test_second_run_does_not_duplicate_stored_candidate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeSourceProvider([make_candidate("python_jobs")])
    resolver = FakeChatResolver({"@python_jobs": make_resolved_chat("@python_jobs", -1001)})
    history = FakeHistoryReader({-1001: RELEVANT_CHAT.text.split("\n")})
    pipeline = build_pipeline(
        session_factory, [provider], resolver, history, FakeVerdictLlm(CHAT_CASES)
    )

    first = await pipeline.run_once()
    second = await pipeline.run_once()

    assert first.candidates == 1
    assert second.candidates == 0
    assert second.approved == 0
    assert len(await stored_chats(session_factory, DiscoveryStatus.approved)) == 1
    assert len(history.calls) == 1


async def test_already_monitored_chat_is_skipped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(session_factory) as session:
        await MonitoredChatRepository(session).upsert(
            tg_chat_id=-1001,
            title="Уже мониторится",
            username="@python_jobs",
            origin=MonitoredChatOrigin.sources_file,
        )
    provider = FakeSourceProvider([make_candidate("python_jobs")])
    resolver = FakeChatResolver({"@python_jobs": make_resolved_chat("@python_jobs", -1001)})

    result = await build_pipeline(
        session_factory, [provider], resolver, FakeHistoryReader(), FakeVerdictLlm(CHAT_CASES)
    ).run_once()

    assert result.candidates == 0
    assert resolver.calls == []


async def test_candidates_from_both_providers_are_deduplicated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    telethon_provider = FakeSourceProvider(
        [
            make_candidate(
                "Python_Jobs", provider=DiscoveryProvider.telethon_search, tg_chat_id=-1001
            )
        ]
    )
    searxng_provider = FakeSourceProvider([make_candidate("python_jobs")])
    resolver = FakeChatResolver({"@Python_Jobs": make_resolved_chat("@python_jobs", -1001)})
    history = FakeHistoryReader({-1001: RELEVANT_CHAT.text.split("\n")})

    result = await build_pipeline(
        session_factory,
        [telethon_provider, searxng_provider],
        resolver,
        history,
        FakeVerdictLlm(CHAT_CASES),
    ).run_once()

    assert result.candidates == 1
    assert len(await stored_chats(session_factory, DiscoveryStatus.approved)) == 1


async def test_failing_provider_does_not_break_the_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    broken = FakeSourceProvider([], error=RuntimeError("provider is down"))
    healthy = FakeSourceProvider([make_candidate("python_jobs")])
    resolver = FakeChatResolver({"@python_jobs": make_resolved_chat("@python_jobs", -1001)})
    history = FakeHistoryReader({-1001: RELEVANT_CHAT.text.split("\n")})

    result = await build_pipeline(
        session_factory, [broken, healthy], resolver, history, FakeVerdictLlm(CHAT_CASES)
    ).run_once()

    assert result.approved == 1


async def test_unresolved_candidate_is_counted_and_not_stored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeSourceProvider([make_candidate("ghost_chat")])

    result = await build_pipeline(
        session_factory,
        [provider],
        FakeChatResolver(),
        FakeHistoryReader(),
        FakeVerdictLlm(CHAT_CASES),
    ).run_once()

    assert result.unresolved == 1
    assert await stored_chats(session_factory, DiscoveryStatus.rejected) == []
    assert await stored_chats(session_factory, DiscoveryStatus.approved) == []


async def test_generated_queries_are_persisted_and_marked_as_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeSourceProvider([])

    await build_pipeline(
        session_factory,
        [provider],
        FakeChatResolver(),
        FakeHistoryReader(),
        FakeVerdictLlm(CHAT_CASES),
    ).run_once()

    async with session_scope(session_factory) as session:
        stored = list(await SearchQueryRepository(session).list_all())

    assert [query.query_text for query in stored] == QUERIES
    assert all(query.last_run_at is not None for query in stored)
    assert provider.queries == QUERIES


async def test_queries_are_not_duplicated_across_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    pipeline = build_pipeline(
        session_factory,
        [FakeSourceProvider([])],
        FakeChatResolver(),
        FakeHistoryReader(),
        FakeVerdictLlm(CHAT_CASES),
    )

    await pipeline.run_once()
    await pipeline.run_once()

    async with session_scope(session_factory) as session:
        stored = list(await SearchQueryRepository(session).list_all())

    assert len(stored) == len(QUERIES)
