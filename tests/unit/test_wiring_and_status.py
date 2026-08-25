from datetime import UTC, datetime
from typing import Any, cast

import pytest
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient

from app.bot.handlers.commands import format_last_run, format_status, handle_status
from app.bot.handlers.monitoring import handle_monitored_message
from app.bot.main import (
    build_dispatcher,
    create_github_client,
    create_llm_client,
    start_telethon,
)
from app.bot.middlewares.owner_only import OwnerOnlyMiddleware
from app.config import Settings
from app.db.base import session_scope, utcnow
from app.db.models import DiscoveryProvider, DiscoveryStatus, MonitoredChatOrigin
from app.llm.deepseek_client import DeepSeekClient, FakeDeepSeekClient
from app.portfolio.github_client import FakeGithubClient, GithubApiClient
from app.repositories.discovered_chats import DiscoveredChatRepository
from app.repositories.monitored_chats import MonitoredChatRepository
from app.repositories.portfolio import deserialize_topics
from app.repositories.search_queries import SearchQueryRepository
from app.services.chat_service import ChatService, ChatServiceStatus
from tests.conftest import FakeChatResolver, make_group_message, make_resolved_chat


class MessageSpy:
    def __init__(self) -> None:
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        del kwargs
        self.answers.append(text)


class LeadServiceSpy:
    def __init__(self) -> None:
        self.processed: list[str | None] = []

    async def process_message(self, message: Message) -> None:
        self.processed.append(message.text)


def build_settings(**overrides: Any) -> Settings:
    return Settings(bot_token="token", owner_tg_id=1, **overrides)


async def test_status_counts_leads_and_pending_candidates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(session_factory) as session:
        await MonitoredChatRepository(session).upsert(
            tg_chat_id=-1001,
            title="Мониторимый",
            username="@monitored",
            origin=MonitoredChatOrigin.sources_file,
        )
        await DiscoveredChatRepository(session).upsert_evaluated(
            tg_chat_id=-1002,
            username="candidate_chat",
            title="Кандидат",
            link="https://t.me/candidate_chat",
            provider=DiscoveryProvider.searxng,
            status=DiscoveryStatus.approved,
            relevance_reason="в чате есть заказы",
            evaluated_at=utcnow(),
        )
        queries = SearchQueryRepository(session)
        await queries.add_if_absent("заказы боты")
        await queries.mark_run("заказы боты", datetime(2026, 8, 25, 12, 30, tzinfo=UTC))

    status = await ChatService(
        session_factory, FakeChatResolver(), discovery_interval_minutes=180
    ).build_status()

    assert status.active_chats == 1
    assert status.pending_discovered == 1
    assert status.total_leads == 0
    assert status.notified_leads == 0
    assert status.last_discovery_run_at is not None


async def test_status_handler_renders_all_counters() -> None:
    message = MessageSpy()
    status = ChatServiceStatus(
        telethon_healthy=False,
        active_chats=3,
        discovery_interval_minutes=180,
        total_leads=12,
        notified_leads=11,
        pending_discovered=2,
        last_discovery_run_at=datetime(2026, 8, 25, 9, 5, tzinfo=UTC),
    )

    class StatusStub:
        async def build_status(self) -> ChatServiceStatus:
            return status

    await handle_status(cast(Message, message), cast(Any, StatusStub()))

    text = message.answers[0]
    assert "нет соединения" in text
    assert "Активных мониторимых чатов: 3" in text
    assert "Заявок найдено: 12 (уведомлений отправлено: 11)" in text
    assert "Найденных чатов ждут решения: 2" in text
    assert "2026-08-25 09:05 UTC" in text


def test_status_reports_discovery_never_ran() -> None:
    assert format_last_run(None) == "ещё не запускался"
    assert "ещё не запускался" in format_status(
        ChatServiceStatus(telethon_healthy=True, active_chats=0, discovery_interval_minutes=180)
    )


async def test_monitoring_handler_delegates_to_the_service() -> None:
    service = LeadServiceSpy()

    await handle_monitored_message(make_group_message("ищу разработчика"), cast(Any, service))

    assert service.processed == ["ищу разработчика"]


def test_owner_guard_covers_commands_and_callbacks_but_not_monitoring() -> None:
    dispatcher = build_dispatcher(build_settings(), cast(Any, None), cast(Any, None))
    routers = {router.name: router for router in dispatcher.sub_routers}

    def guards(observer: Any) -> list[Any]:
        return [m for m in observer.middleware if isinstance(m, OwnerOnlyMiddleware)]

    assert set(routers) == {"commands", "discovered", "monitoring"}
    assert guards(routers["commands"].message)
    assert guards(routers["discovered"].message)
    assert guards(routers["discovered"].callback_query)
    assert guards(routers["monitoring"].message) == []


def test_llm_client_falls_back_without_api_key() -> None:
    assert isinstance(create_llm_client(build_settings()), FakeDeepSeekClient)
    assert isinstance(create_llm_client(build_settings(deepseek_api_key="secret")), DeepSeekClient)


def test_github_client_falls_back_without_credentials() -> None:
    assert isinstance(create_github_client(build_settings()), FakeGithubClient)
    assert isinstance(
        create_github_client(build_settings(github_username="aurusxd", github_token="secret")),
        GithubApiClient,
    )


async def test_session_scope_rolls_back_on_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(RuntimeError):
        async with session_scope(session_factory) as session:
            await MonitoredChatRepository(session).upsert(
                tg_chat_id=-1009,
                title="Не должен сохраниться",
                username="@rollback_chat",
                origin=MonitoredChatOrigin.command,
            )
            raise RuntimeError("что-то пошло не так")

    async with session_scope(session_factory) as session:
        assert await MonitoredChatRepository(session).get_by_tg_chat_id(-1009) is None


async def test_conflicting_candidate_is_reported_instead_of_crashing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(session_factory) as session:
        repository = DiscoveredChatRepository(session)
        await repository.upsert_evaluated(
            tg_chat_id=-2001,
            username="first_name",
            title="Первый",
            link="https://t.me/first_name",
            provider=DiscoveryProvider.searxng,
            status=DiscoveryStatus.approved,
            relevance_reason="заказы",
            evaluated_at=utcnow(),
        )

    async with session_scope(session_factory) as session:
        conflicting = await DiscoveredChatRepository(session).upsert_evaluated(
            tg_chat_id=-2001,
            username="second_name",
            title="Второй",
            link="https://t.me/second_name",
            provider=DiscoveryProvider.searxng,
            status=DiscoveryStatus.approved,
            relevance_reason="заказы",
            evaluated_at=utcnow(),
        )

    assert conflicting is None


@pytest.mark.parametrize("raw", [None, "", "не json", '{"не": "список"}', "42"])
def test_topics_deserialization_tolerates_broken_payloads(raw: str | None) -> None:
    assert deserialize_topics(raw) == []


async def test_resolver_stub_records_requested_handles() -> None:
    resolver = FakeChatResolver({"@chat": make_resolved_chat("@chat", -1001)})

    assert await resolver.resolve("@chat") is not None
    assert await resolver.resolve("@missing") is None
    assert resolver.calls == ["@chat", "@missing"]


class TelethonClientStub:
    def __init__(self, *, connect_error: Exception | None = None, authorized: bool = True) -> None:
        self._connect_error = connect_error
        self._authorized = authorized
        self.connected = False

    async def connect(self) -> None:
        if self._connect_error is not None:
            raise self._connect_error
        self.connected = True

    async def is_user_authorized(self) -> bool:
        return self._authorized


async def test_startup_reports_authorized_session() -> None:
    client = TelethonClientStub()

    assert await start_telethon(cast(TelegramClient, client)) is True
    assert client.connected is True


async def test_startup_refuses_unauthorized_session() -> None:
    assert await start_telethon(cast(TelegramClient, TelethonClientStub(authorized=False))) is False


async def test_startup_survives_connection_failure() -> None:
    client = TelethonClientStub(connect_error=OSError("нет сети"))

    assert await start_telethon(cast(TelegramClient, client)) is False
