from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import session_scope
from app.db.models import MonitoredChatOrigin
from app.repositories.monitored_chats import MonitoredChatRepository
from app.services.chat_service import ChatService, SourcesFileError
from tests.conftest import FakeChatResolver, make_resolved_chat, write_sources_file

FIRST_HANDLE = "@first_chat"
SECOND_HANDLE = "@second_chat"


def build_service(
    session_factory: async_sessionmaker[AsyncSession],
    resolver: FakeChatResolver,
) -> ChatService:
    return ChatService(session_factory, resolver, discovery_interval_minutes=10)


async def list_active_chats(session_factory: async_sessionmaker[AsyncSession]):
    async with session_scope(session_factory) as session:
        return list(await MonitoredChatRepository(session).list_active())


async def test_enabled_entries_land_in_monitored_chats(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    path = write_sources_file(
        tmp_path,
        [{"handle": FIRST_HANDLE, "title": "Первый", "enabled": True}],
    )
    resolver = FakeChatResolver({FIRST_HANDLE: make_resolved_chat(FIRST_HANDLE, -1001, "Первый")})

    result = await build_service(session_factory, resolver).sync_from_sources_file(path)

    assert result.synced == 1
    chats = await list_active_chats(session_factory)
    assert len(chats) == 1
    assert chats[0].tg_chat_id == -1001
    assert chats[0].username == "first_chat"
    assert chats[0].origin is MonitoredChatOrigin.sources_file
    assert chats[0].is_active is True


async def test_sync_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    path = write_sources_file(tmp_path, [{"handle": FIRST_HANDLE, "enabled": True}])
    resolver = FakeChatResolver({FIRST_HANDLE: make_resolved_chat(FIRST_HANDLE, -1001)})
    service = build_service(session_factory, resolver)

    await service.sync_from_sources_file(path)
    await service.sync_from_sources_file(path)

    assert len(await list_active_chats(session_factory)) == 1


async def test_renamed_chat_updates_title_without_duplicate(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    path = write_sources_file(tmp_path, [{"handle": FIRST_HANDLE, "enabled": True}])
    resolver = FakeChatResolver({FIRST_HANDLE: make_resolved_chat(FIRST_HANDLE, -1001, "Старое")})
    service = build_service(session_factory, resolver)
    await service.sync_from_sources_file(path)

    resolver.resolved[FIRST_HANDLE] = make_resolved_chat(FIRST_HANDLE, -1001, "Новое")
    await service.sync_from_sources_file(path)

    chats = await list_active_chats(session_factory)
    assert len(chats) == 1
    assert chats[0].title == "Новое"


async def test_disabled_entry_is_not_resolved(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    path = write_sources_file(tmp_path, [{"handle": SECOND_HANDLE, "enabled": False}])
    resolver = FakeChatResolver()

    result = await build_service(session_factory, resolver).sync_from_sources_file(path)

    assert resolver.calls == []
    assert result.synced == 0
    assert result.deactivated == 0
    assert await list_active_chats(session_factory) == []


async def test_disabled_entry_deactivates_existing_chat(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    enabled_path = write_sources_file(tmp_path, [{"handle": FIRST_HANDLE, "enabled": True}])
    resolver = FakeChatResolver({FIRST_HANDLE: make_resolved_chat(FIRST_HANDLE, -1001)})
    service = build_service(session_factory, resolver)
    await service.sync_from_sources_file(enabled_path)

    disabled_path = write_sources_file(tmp_path, [{"handle": FIRST_HANDLE, "enabled": False}])
    result = await service.sync_from_sources_file(disabled_path)

    assert result.deactivated == 1
    assert await list_active_chats(session_factory) == []


async def test_unresolved_handle_is_skipped_without_breaking_sync(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    path = write_sources_file(
        tmp_path,
        [
            {"handle": FIRST_HANDLE, "enabled": True},
            {"handle": SECOND_HANDLE, "enabled": True},
        ],
    )
    resolver = FakeChatResolver({SECOND_HANDLE: make_resolved_chat(SECOND_HANDLE, -1002)})

    result = await build_service(session_factory, resolver).sync_from_sources_file(path)

    assert result.unresolved == [FIRST_HANDLE]
    assert result.synced == 1
    assert len(await list_active_chats(session_factory)) == 1


async def test_duplicate_handle_stops_sync_before_any_write(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    path = write_sources_file(
        tmp_path,
        [
            {"handle": FIRST_HANDLE, "enabled": True},
            {"handle": FIRST_HANDLE, "enabled": True},
        ],
    )
    resolver = FakeChatResolver({FIRST_HANDLE: make_resolved_chat(FIRST_HANDLE, -1001)})

    with pytest.raises(SourcesFileError, match="duplicate handle"):
        await build_service(session_factory, resolver).sync_from_sources_file(path)

    assert resolver.calls == []
    assert await list_active_chats(session_factory) == []


async def test_command_chat_absent_from_file_stays_active(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    async with session_scope(session_factory) as session:
        await MonitoredChatRepository(session).upsert(
            tg_chat_id=-2002,
            title="Добавлен командой",
            username="@command_chat",
            origin=MonitoredChatOrigin.command,
        )
    path = write_sources_file(tmp_path, [{"handle": FIRST_HANDLE, "enabled": True}])
    resolver = FakeChatResolver({FIRST_HANDLE: make_resolved_chat(FIRST_HANDLE, -1001)})

    await build_service(session_factory, resolver).sync_from_sources_file(path)

    chats = await list_active_chats(session_factory)
    assert {chat.tg_chat_id for chat in chats} == {-1001, -2002}
    command_chat = next(chat for chat in chats if chat.tg_chat_id == -2002)
    assert command_chat.origin is MonitoredChatOrigin.command


async def test_status_reports_active_chats_and_telethon_health(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    path = write_sources_file(tmp_path, [{"handle": FIRST_HANDLE, "enabled": True}])
    resolver = FakeChatResolver(
        {FIRST_HANDLE: make_resolved_chat(FIRST_HANDLE, -1001)}, healthy=False
    )
    service = build_service(session_factory, resolver)
    await service.sync_from_sources_file(path)

    status = await service.build_status()

    assert status.active_chats == 1
    assert status.telethon_healthy is False
    assert status.discovery_interval_minutes == 10
