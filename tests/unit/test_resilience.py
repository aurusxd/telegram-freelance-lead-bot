from typing import Any, cast

import httpx
import pytest
from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError, ServerError, TimedOutError

from app.llm.deepseek_client import AsyncRateLimiter, DeepSeekClient
from app.telethon_client.client import (
    MAX_FLOOD_WAIT_SECONDS,
    RETRY_ATTEMPTS,
    TelethonChatResolver,
    run_with_flood_backoff,
)
from app.telethon_client.history import TelethonChatHistory
from app.telethon_client.search import TelethonGlobalSearch
from tests.unit.test_telegram_search_provider import SearchResponse, make_channel

CHANNEL = make_channel()


class SleepSpy:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def flood_wait(seconds: int) -> FloodWaitError:
    return FloodWaitError(request=None, capture=seconds)


class FlakyOperation:
    def __init__(self, failures: list[Exception], value: str = "готово") -> None:
        self._failures = failures
        self._value = value
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        if self._failures:
            raise self._failures.pop(0)
        return self._value


async def test_flood_wait_is_waited_out_then_retried() -> None:
    sleep = SleepSpy()
    operation = FlakyOperation([flood_wait(7)])

    result = await run_with_flood_backoff(operation, sleep=sleep)

    assert result == "готово"
    assert operation.calls == 2
    assert sleep.delays == [7.0]


async def test_flood_wait_beyond_budget_gives_up_without_sleeping() -> None:
    sleep = SleepSpy()
    operation = FlakyOperation([flood_wait(MAX_FLOOD_WAIT_SECONDS + 1)])

    result = await run_with_flood_backoff(operation, sleep=sleep)

    assert result is None
    assert operation.calls == 1
    assert sleep.delays == []


async def test_repeated_flood_waits_stop_at_the_attempt_limit() -> None:
    sleep = SleepSpy()
    operation = FlakyOperation([flood_wait(5) for _ in range(RETRY_ATTEMPTS)])

    result = await run_with_flood_backoff(operation, sleep=sleep)

    assert result is None
    assert operation.calls == RETRY_ATTEMPTS
    assert len(sleep.delays) == RETRY_ATTEMPTS - 1


@pytest.mark.parametrize(
    "error", [ServerError(None, "сервер лёг"), TimedOutError(None, "истекло время")]
)
async def test_transient_errors_back_off_with_growing_delay(error: Exception) -> None:
    sleep = SleepSpy()
    operation = FlakyOperation([error, error])

    result = await run_with_flood_backoff(operation, sleep=sleep)

    assert result == "готово"
    assert operation.calls == 3
    assert sleep.delays == [2.0, 4.0]


async def test_other_rpc_errors_propagate_to_the_caller() -> None:
    operation = FlakyOperation([RPCError(None, "CHANNEL_PRIVATE")])

    with pytest.raises(RPCError):
        await run_with_flood_backoff(operation, sleep=SleepSpy())


class FloodingClient:
    def __init__(self, error: Exception, entity: Any = CHANNEL) -> None:
        self._error = error
        self._entity = entity
        self.calls = 0

    async def get_entity(self, handle: str) -> Any:
        del handle
        self.calls += 1
        if self.calls == 1:
            raise self._error
        return self._entity

    async def get_messages(self, entity: Any, limit: int) -> Any:
        del entity, limit
        self.calls += 1
        if self.calls == 1:
            raise self._error
        return []

    async def __call__(self, request: Any) -> Any:
        del request
        self.calls += 1
        if self.calls == 1:
            raise self._error
        return SearchResponse([CHANNEL])


async def test_resolver_survives_flood_wait() -> None:
    client = FloodingClient(flood_wait(3))
    sleep = SleepSpy()

    resolved = await TelethonChatResolver(cast(TelegramClient, client), sleep=sleep).resolve(
        "@chat"
    )

    assert resolved is not None
    assert resolved.username == "python_jobs"
    assert sleep.delays == [3.0]


async def test_resolver_returns_none_when_flood_wait_is_too_long() -> None:
    client = FloodingClient(flood_wait(MAX_FLOOD_WAIT_SECONDS * 2))

    resolved = await TelethonChatResolver(cast(TelegramClient, client), sleep=SleepSpy()).resolve(
        "@chat"
    )

    assert resolved is None


async def test_global_search_survives_flood_wait() -> None:
    client = FloodingClient(flood_wait(4))
    sleep = SleepSpy()

    chats = await TelethonGlobalSearch(client, sleep=sleep).search_chats("заказ", limit=10)

    assert [chat.username for chat in chats] == ["python_jobs"]
    assert sleep.delays == [4.0]


async def test_history_survives_flood_wait() -> None:
    from app.telethon_client.client import ResolvedChat

    client = FloodingClient(flood_wait(2))
    sleep = SleepSpy()
    chat = ResolvedChat(tg_chat_id=-1001234567890, access_hash=1, title="Чат", username="chat")

    texts = await TelethonChatHistory(cast(TelegramClient, client), sleep=sleep).read_last_messages(
        chat, limit=5
    )

    assert texts == []
    assert sleep.delays == [2.0]


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_rate_limiter_spaces_out_requests() -> None:
    clock = FakeClock()
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)
        clock.now += delay

    limiter = AsyncRateLimiter(1.5, sleep=sleep, clock=clock)

    await limiter.wait_for_slot()
    await limiter.wait_for_slot()
    await limiter.wait_for_slot()

    assert delays == [1.5, 1.5]


async def test_rate_limiter_does_not_wait_when_enough_time_passed() -> None:
    clock = FakeClock()
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)
        clock.now += delay

    limiter = AsyncRateLimiter(1.0, sleep=sleep, clock=clock)

    await limiter.wait_for_slot()
    clock.now += 5.0
    await limiter.wait_for_slot()

    assert delays == []


async def test_disabled_rate_limiter_never_sleeps() -> None:
    sleep = SleepSpy()
    limiter = AsyncRateLimiter(0.0, sleep=sleep, clock=FakeClock())

    await limiter.wait_for_slot()
    await limiter.wait_for_slot()

    assert sleep.delays == []


async def test_deepseek_client_waits_for_the_rate_limit_slot() -> None:
    sleep = SleepSpy()
    clock = FakeClock()
    limiter = AsyncRateLimiter(2.0, sleep=sleep, clock=clock)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"is_relevant": false, "reason": "нет", "confidence": 0.1}'
                        }
                    }
                ]
            },
        )

    client = DeepSeekClient(
        "key",
        "deepseek-chat",
        base_url="https://api.deepseek.test",
        transport=httpx.MockTransport(handler),
        rate_limiter=limiter,
    )

    await client.complete_json(system_prompt="s", user_prompt="u")
    await client.complete_json(system_prompt="s", user_prompt="u")

    assert sleep.delays == [2.0]
