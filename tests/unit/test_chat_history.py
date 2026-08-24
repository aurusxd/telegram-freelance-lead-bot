from typing import Any, cast

from telethon import TelegramClient
from telethon.errors import RPCError

from app.telethon_client.client import ResolvedChat
from app.telethon_client.history import (
    TelethonChatHistory,
    build_input_peer,
    extract_texts,
)

CHAT = ResolvedChat(tg_chat_id=-1001234567890, access_hash=42, title="Чат", username="chat")


class FakeMessage:
    def __init__(self, message: Any) -> None:
        self.message = message


class FakeMessagesClient:
    def __init__(self, messages: Any) -> None:
        self._messages = messages
        self.calls: list[tuple[Any, int]] = []

    async def get_messages(self, entity: Any, limit: int) -> Any:
        self.calls.append((entity, limit))
        if isinstance(self._messages, Exception):
            raise self._messages
        return self._messages


def build_history(messages: Any) -> tuple[TelethonChatHistory, FakeMessagesClient]:
    client = FakeMessagesClient(messages)
    return TelethonChatHistory(cast(TelegramClient, client)), client


def test_input_peer_uses_unmarked_channel_id() -> None:
    peer = build_input_peer(CHAT)

    assert peer is not None
    assert peer.channel_id == 1234567890
    assert peer.access_hash == 42


def test_input_peer_requires_access_hash() -> None:
    assert build_input_peer(ResolvedChat(-1001, None, "Чат", "chat")) is None


async def test_reads_and_trims_message_texts() -> None:
    history, client = build_history(
        [FakeMessage("  первый  "), FakeMessage(""), FakeMessage(None), FakeMessage("второй")]
    )

    texts = await history.read_last_messages(CHAT, limit=20)

    assert texts == ["первый", "второй"]
    assert client.calls[0][1] == 20


async def test_chat_without_access_hash_is_not_requested() -> None:
    history, client = build_history([FakeMessage("текст")])

    texts = await history.read_last_messages(ResolvedChat(-1001, None, "Чат", "chat"), limit=5)

    assert texts == []
    assert client.calls == []


async def test_rpc_error_degrades_to_empty_history() -> None:
    history, _ = build_history(RPCError("request", "CHANNEL_PRIVATE"))

    assert await history.read_last_messages(CHAT, limit=5) == []


async def test_unexpected_payload_is_safe() -> None:
    history, _ = build_history(None)

    assert await history.read_last_messages(CHAT, limit=5) == []


def test_extract_texts_ignores_non_iterables_and_strings() -> None:
    assert extract_texts("строка") == []
    assert extract_texts(42) == []
