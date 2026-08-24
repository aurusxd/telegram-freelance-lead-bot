from collections.abc import Iterable
from typing import Protocol

from loguru import logger
from telethon import TelegramClient, utils
from telethon.errors import RPCError
from telethon.tl.types import InputPeerChannel

from app.telethon_client.client import ResolvedChat

DEFAULT_HISTORY_LIMIT = 20


class ChatHistoryReader(Protocol):
    async def read_last_messages(self, chat: ResolvedChat, limit: int) -> list[str]: ...


def build_input_peer(chat: ResolvedChat) -> InputPeerChannel | None:
    if chat.access_hash is None:
        return None
    channel_id, _ = utils.resolve_id(chat.tg_chat_id)
    return InputPeerChannel(channel_id=channel_id, access_hash=chat.access_hash)


def extract_texts(messages: object) -> list[str]:
    if not isinstance(messages, Iterable) or isinstance(messages, str):
        return []
    texts = (getattr(message, "message", None) for message in messages)
    return [text.strip() for text in texts if isinstance(text, str) and text.strip()]


class TelethonChatHistory:
    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    async def read_last_messages(
        self, chat: ResolvedChat, limit: int = DEFAULT_HISTORY_LIMIT
    ) -> list[str]:
        peer = build_input_peer(chat)
        if peer is None:
            logger.warning("chat {} has no access hash, history skipped", chat.tg_chat_id)
            return []
        try:
            messages = await self._client.get_messages(peer, limit=limit)
        except (RPCError, ValueError) as error:
            logger.warning("cannot read history of {}: {}", chat.tg_chat_id, type(error).__name__)
            return []
        return extract_texts(messages)
