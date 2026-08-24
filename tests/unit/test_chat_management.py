import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import session_scope, utcnow
from app.db.models import DiscoveryProvider, DiscoveryStatus, MonitoredChatOrigin
from app.repositories.discovered_chats import DiscoveredChatRepository
from app.repositories.monitored_chats import MonitoredChatRepository
from app.services.chat_service import (
    AddChatOutcome,
    ChatService,
    PromoteOutcome,
    RemoveChatOutcome,
    normalize_handle,
)
from tests.conftest import FakeChatResolver, make_resolved_chat

HANDLE = "@python_jobs"
CHAT_ID = -1001


def build_service(
    session_factory: async_sessionmaker[AsyncSession], resolver: FakeChatResolver
) -> ChatService:
    return ChatService(session_factory, resolver, discovery_interval_minutes=10)


def resolver_with_chat(title: str = "Python Jobs") -> FakeChatResolver:
    return FakeChatResolver({HANDLE: make_resolved_chat(HANDLE, CHAT_ID, title)})


async def seed_discovered(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: DiscoveryStatus = DiscoveryStatus.approved,
    tg_chat_id: int | None = CHAT_ID,
    username: str | None = "python_jobs",
    title: str | None = "Python Jobs",
) -> int:
    async with session_scope(session_factory) as session:
        chat = await DiscoveredChatRepository(session).upsert_evaluated(
            tg_chat_id=tg_chat_id,
            username=username,
            title=title,
            link="https://t.me/python_jobs",
            provider=DiscoveryProvider.searxng,
            status=status,
            relevance_reason="в чате публикуют заказы на ботов",
            evaluated_at=utcnow(),
        )
        assert chat is not None
        return chat.id


@pytest.mark.parametrize("raw_handle", ["@Python_Jobs", "python_jobs", " @python_jobs "])
def test_handle_normalization_is_stable(raw_handle: str) -> None:
    assert normalize_handle(raw_handle) == HANDLE


async def test_add_chat_stores_chat_with_command_origin(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_service(session_factory, resolver_with_chat())

    result = await service.add_chat("python_jobs")

    async with session_scope(session_factory) as session:
        stored = await MonitoredChatRepository(session).get_by_tg_chat_id(CHAT_ID)

    assert result.outcome is AddChatOutcome.added
    assert result.title == "Python Jobs"
    assert stored is not None
    assert stored.origin is MonitoredChatOrigin.command
    assert stored.is_active is True
    assert stored.username == "python_jobs"


async def test_add_chat_twice_reports_already_monitored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_service(session_factory, resolver_with_chat())
    await service.add_chat(HANDLE)

    result = await service.add_chat(HANDLE)

    async with session_scope(session_factory) as session:
        stored = list(await MonitoredChatRepository(session).list_all())

    assert result.outcome is AddChatOutcome.already_monitored
    assert len(stored) == 1


async def test_add_chat_reactivates_removed_chat_keeping_origin(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(session_factory) as session:
        await MonitoredChatRepository(session).upsert(
            tg_chat_id=CHAT_ID,
            title="Python Jobs",
            username=HANDLE,
            origin=MonitoredChatOrigin.sources_file,
        )
    service = build_service(session_factory, resolver_with_chat())
    await service.remove_chat(HANDLE)

    result = await service.add_chat(HANDLE)

    async with session_scope(session_factory) as session:
        stored = await MonitoredChatRepository(session).get_by_tg_chat_id(CHAT_ID)

    assert result.outcome is AddChatOutcome.reactivated
    assert stored is not None
    assert stored.is_active is True
    assert stored.origin is MonitoredChatOrigin.sources_file


async def test_add_chat_reports_unresolved_handle(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_service(session_factory, FakeChatResolver())

    result = await service.add_chat("@ghost_chat")

    async with session_scope(session_factory) as session:
        stored = list(await MonitoredChatRepository(session).list_all())

    assert result.outcome is AddChatOutcome.unresolved
    assert result.handle == "@ghost_chat"
    assert stored == []


async def test_remove_chat_deactivates_without_deleting(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_service(session_factory, resolver_with_chat())
    await service.add_chat(HANDLE)

    result = await service.remove_chat("Python_Jobs")

    async with session_scope(session_factory) as session:
        stored = await MonitoredChatRepository(session).get_by_tg_chat_id(CHAT_ID)

    assert result.outcome is RemoveChatOutcome.removed
    assert result.title == "Python Jobs"
    assert stored is not None
    assert stored.is_active is False


async def test_remove_chat_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_service(session_factory, resolver_with_chat())
    await service.add_chat(HANDLE)
    await service.remove_chat(HANDLE)

    result = await service.remove_chat(HANDLE)

    assert result.outcome is RemoveChatOutcome.not_found


async def test_remove_unknown_chat_reports_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_service(session_factory, FakeChatResolver())

    result = await service.remove_chat("@unknown_chat")

    assert result.outcome is RemoveChatOutcome.not_found


async def test_list_chats_returns_active_and_disabled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_service(session_factory, resolver_with_chat())
    await service.add_chat(HANDLE)
    await service.remove_chat(HANDLE)

    chats = list(await service.list_chats())

    assert len(chats) == 1
    assert chats[0].is_active is False


async def test_pending_discovered_lists_only_approved(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_discovered(session_factory)
    await seed_discovered(
        session_factory,
        status=DiscoveryStatus.rejected,
        tg_chat_id=-1002,
        username="daily_chat",
        title="Болталка",
    )
    service = build_service(session_factory, FakeChatResolver())

    pending = await service.list_pending_discovered()

    assert [chat.username for chat in pending] == ["python_jobs"]


async def test_promoted_chat_disappears_from_pending_list(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    discovered_id = await seed_discovered(session_factory)
    service = build_service(session_factory, FakeChatResolver())

    result = await service.promote_discovered(discovered_id)

    async with session_scope(session_factory) as session:
        stored = await MonitoredChatRepository(session).get_by_tg_chat_id(CHAT_ID)

    assert result.outcome is PromoteOutcome.promoted
    assert result.title == "Python Jobs"
    assert stored is not None
    assert stored.origin is MonitoredChatOrigin.command
    assert await service.list_pending_discovered() == []


async def test_promote_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    discovered_id = await seed_discovered(session_factory)
    service = build_service(session_factory, FakeChatResolver())

    await service.promote_discovered(discovered_id)
    second = await service.promote_discovered(discovered_id)

    async with session_scope(session_factory) as session:
        stored = list(await MonitoredChatRepository(session).list_all())

    assert second.outcome is PromoteOutcome.promoted
    assert len(stored) == 1


async def test_promote_resolves_candidate_without_chat_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    discovered_id = await seed_discovered(session_factory, tg_chat_id=None, title=None)
    service = build_service(session_factory, resolver_with_chat())

    result = await service.promote_discovered(discovered_id)

    async with session_scope(session_factory) as session:
        stored = await MonitoredChatRepository(session).get_by_tg_chat_id(CHAT_ID)

    assert result.outcome is PromoteOutcome.promoted
    assert stored is not None
    assert stored.title == "Python Jobs"


async def test_promote_reports_unresolved_when_telegram_is_silent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    discovered_id = await seed_discovered(session_factory, tg_chat_id=None, title=None)
    service = build_service(session_factory, FakeChatResolver())

    result = await service.promote_discovered(discovered_id)

    assert result.outcome is PromoteOutcome.unresolved


async def test_promote_rejects_unknown_and_not_approved_candidates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    rejected_id = await seed_discovered(
        session_factory, status=DiscoveryStatus.rejected, tg_chat_id=-1003, username="noise_chat"
    )
    service = build_service(session_factory, FakeChatResolver())

    assert (await service.promote_discovered(rejected_id)).outcome is PromoteOutcome.not_found
    assert (await service.promote_discovered(999)).outcome is PromoteOutcome.not_found
