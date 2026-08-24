from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loguru import logger
from telethon import TelegramClient, utils
from telethon.errors import RPCError
from telethon.tl.types import Channel, Chat


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
    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    async def resolve(self, handle: str) -> ResolvedChat | None:
        try:
            entity = await self._client.get_entity(handle)
        except (ValueError, RPCError) as error:
            logger.warning("cannot resolve chat {}: {}", handle, type(error).__name__)
            return None
        return to_resolved_chat(entity)

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
