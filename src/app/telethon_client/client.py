import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loguru import logger
from telethon import TelegramClient, utils
from telethon.errors import FloodWaitError, RPCError, ServerError, TimedOutError
from telethon.tl.types import Channel, Chat

MAX_FLOOD_WAIT_SECONDS = 300
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 2.0

SleepFunction = Callable[[float], Awaitable[None]]


async def run_with_flood_backoff[OperationResult](
    operation: Callable[[], Awaitable[OperationResult]],
    *,
    attempts: int = RETRY_ATTEMPTS,
    sleep: SleepFunction = asyncio.sleep,
    max_flood_wait_seconds: int = MAX_FLOOD_WAIT_SECONDS,
) -> OperationResult | None:
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except FloodWaitError as error:
            if error.seconds > max_flood_wait_seconds or attempt == attempts:
                logger.warning("flood wait of {}s exceeds the budget, giving up", error.seconds)
                return None
            logger.warning("flood wait of {}s, retrying after the pause", error.seconds)
            await sleep(float(error.seconds))
        except (ServerError, TimedOutError) as error:
            if attempt == attempts:
                logger.warning("telegram stayed unavailable: {}", type(error).__name__)
                return None
            await sleep(RETRY_BASE_DELAY_SECONDS * attempt)
    return None


@dataclass(frozen=True)
class ResolvedChat:
    tg_chat_id: int
    access_hash: int | None
    title: str
    username: str | None


class TelegramChatResolver(Protocol):
    async def resolve(self, handle: str) -> ResolvedChat | None: ...

    async def health_check(self) -> bool: ...


def create_telethon_client(api_id: int, api_hash: str, session_path: Path) -> TelegramClient:
    session_path.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(str(session_path), api_id, api_hash)


class TelethonChatResolver:
    def __init__(self, client: TelegramClient, *, sleep: SleepFunction = asyncio.sleep) -> None:
        self._client = client
        self._sleep = sleep

    async def resolve(self, handle: str) -> ResolvedChat | None:
        try:
            entity = await run_with_flood_backoff(
                lambda: self._client.get_entity(handle), sleep=self._sleep
            )
        except (ValueError, RPCError) as error:
            logger.warning("cannot resolve chat {}: {}", handle, type(error).__name__)
            return None
        return to_resolved_chat(entity) if entity is not None else None

    async def health_check(self) -> bool:
        if not self._client.is_connected():
            return False
        return await self._client.is_user_authorized()


def to_resolved_chat(entity: object) -> ResolvedChat | None:
    if isinstance(entity, Channel):
        return ResolvedChat(
            tg_chat_id=utils.get_peer_id(entity),
            access_hash=entity.access_hash,
            title=entity.title,
            username=entity.username,
        )
    if isinstance(entity, Chat):
        return ResolvedChat(
            tg_chat_id=utils.get_peer_id(entity),
            access_hash=None,
            title=entity.title,
            username=None,
        )
    return None
