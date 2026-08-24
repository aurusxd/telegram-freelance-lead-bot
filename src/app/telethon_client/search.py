import asyncio
from typing import Any, Protocol

from loguru import logger
from telethon.errors import RPCError
from telethon.tl.functions.messages import SearchGlobalRequest
from telethon.tl.types import Channel, InputMessagesFilterEmpty, InputPeerEmpty

from app.telethon_client.client import (
    ResolvedChat,
    SleepFunction,
    run_with_flood_backoff,
    to_resolved_chat,
)

DEFAULT_SEARCH_LIMIT = 50


class GlobalChatSearch(Protocol):
    async def search_chats(self, query: str, limit: int) -> list[ResolvedChat]: ...


class RawRequestInvoker(Protocol):
    async def __call__(self, request: Any) -> Any: ...


def is_public_source_chat(chat: object) -> bool:
    if not isinstance(chat, Channel):
        return False
    if not (chat.megagroup or chat.broadcast):
        return False
    return bool(chat.username)


class TelethonGlobalSearch:
    def __init__(self, client: RawRequestInvoker, *, sleep: SleepFunction = asyncio.sleep) -> None:
        self._client = client
        self._sleep = sleep

    async def search_chats(
        self, query: str, limit: int = DEFAULT_SEARCH_LIMIT
    ) -> list[ResolvedChat]:
        response = await self._request_global_search(query, limit)
        if response is None:
            return []
        return collect_public_chats(getattr(response, "chats", []))

    async def _request_global_search(self, query: str, limit: int) -> object | None:
        request = SearchGlobalRequest(
            q=query,
            filter=InputMessagesFilterEmpty(),
            min_date=None,
            max_date=None,
            offset_rate=0,
            offset_peer=InputPeerEmpty(),
            offset_id=0,
            limit=limit,
        )
        try:
            return await run_with_flood_backoff(lambda: self._client(request), sleep=self._sleep)
        except RPCError as error:
            logger.warning("global search failed for query: {}", type(error).__name__)
            return None


def collect_public_chats(chats: object) -> list[ResolvedChat]:
    if not isinstance(chats, list):
        return []
    resolved = (to_resolved_chat(chat) for chat in chats if is_public_source_chat(chat))
    return [chat for chat in resolved if chat is not None]
