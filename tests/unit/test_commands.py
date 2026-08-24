from typing import Any, cast

from aiogram.types import Message

from app.bot.handlers.commands import (
    HELP_TEXT,
    START_TEXT,
    format_status,
    handle_help,
    handle_start,
    handle_status,
)
from app.services.chat_service import ChatServiceStatus


class MessageSpy:
    def __init__(self) -> None:
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        del kwargs
        self.answers.append(text)


class ChatServiceStub:
    def __init__(self, status: ChatServiceStatus) -> None:
        self._status = status

    async def build_status(self) -> ChatServiceStatus:
        return self._status


async def test_start_answers_with_intro() -> None:
    message = MessageSpy()

    await handle_start(cast(Message, message))

    assert message.answers == [START_TEXT]


async def test_help_lists_commands() -> None:
    message = MessageSpy()

    await handle_help(cast(Message, message))

    assert message.answers == [HELP_TEXT]


async def test_status_reports_connections() -> None:
    message = MessageSpy()
    status = ChatServiceStatus(telethon_healthy=True, active_chats=2, discovery_interval_minutes=10)

    await handle_status(cast(Message, message), cast(Any, ChatServiceStub(status)))

    assert message.answers == [format_status(status)]
    assert "подключён" in message.answers[0]
    assert "10 мин" in message.answers[0]


def test_status_text_reports_broken_telethon() -> None:
    status = ChatServiceStatus(
        telethon_healthy=False, active_chats=0, discovery_interval_minutes=10
    )

    assert "нет соединения" in format_status(status)
