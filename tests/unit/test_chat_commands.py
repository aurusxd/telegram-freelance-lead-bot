from datetime import UTC, datetime
from typing import Any, cast

import pytest
from aiogram.filters import CommandObject
from aiogram.types import CallbackQuery, Chat, InlineKeyboardMarkup, Message

from app.bot.handlers.commands import (
    ADD_CHAT_USAGE,
    EMPTY_CHAT_LIST,
    REMOVE_CHAT_USAGE,
    format_chat_list,
    handle_add_chat,
    handle_list_chats,
    handle_remove_chat,
)
from app.bot.handlers.discovered import (
    EMPTY_DISCOVERED_LIST,
    UNKNOWN_CALLBACK_ANSWER,
    handle_discovered,
    handle_promote,
)
from app.bot.keyboards import (
    PROMOTE_BUTTON_TEXT,
    build_promote_callback,
    build_promote_keyboard,
    parse_promote_callback,
)
from app.db.models import DiscoveredChat, MonitoredChat, MonitoredChatOrigin
from app.services.chat_service import (
    AddChatOutcome,
    AddChatResult,
    PromoteOutcome,
    PromoteResult,
    RemoveChatOutcome,
    RemoveChatResult,
)


class MessageSpy:
    def __init__(self) -> None:
        self.answers: list[str] = []
        self.keyboards: list[InlineKeyboardMarkup | None] = []
        self.cleared_markup = False

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append(text)
        self.keyboards.append(kwargs.get("reply_markup"))

    async def edit_reply_markup(self, **kwargs: Any) -> None:
        del kwargs
        self.cleared_markup = True


class CardMessage:
    def __init__(self) -> None:
        self.message = Message(
            message_id=10,
            date=datetime.now(UTC),
            chat=Chat(id=555, type="private"),
        )
        self.cleared_markup = False
        object.__setattr__(self.message, "edit_reply_markup", self._record)

    async def _record(self, **kwargs: Any) -> None:
        del kwargs
        self.cleared_markup = True


class CallbackSpy:
    def __init__(self, data: str | None, message: Message | None = None) -> None:
        self.data = data
        self.message = message
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        del kwargs
        self.answers.append(text)


class ChatServiceStub:
    def __init__(
        self,
        *,
        add_result: AddChatResult | None = None,
        remove_result: RemoveChatResult | None = None,
        chats: list[MonitoredChat] | None = None,
        discovered: list[DiscoveredChat] | None = None,
        promote_result: PromoteResult | None = None,
    ) -> None:
        self._add_result = add_result
        self._remove_result = remove_result
        self._chats = chats or []
        self._discovered = discovered or []
        self._promote_result = promote_result
        self.added: list[str] = []
        self.removed: list[str] = []
        self.promoted: list[int] = []

    async def add_chat(self, handle: str) -> AddChatResult:
        self.added.append(handle)
        assert self._add_result is not None
        return self._add_result

    async def remove_chat(self, handle: str) -> RemoveChatResult:
        self.removed.append(handle)
        assert self._remove_result is not None
        return self._remove_result

    async def list_chats(self) -> list[MonitoredChat]:
        return self._chats

    async def list_pending_discovered(self) -> list[DiscoveredChat]:
        return self._discovered

    async def promote_discovered(self, discovered_chat_id: int) -> PromoteResult:
        self.promoted.append(discovered_chat_id)
        assert self._promote_result is not None
        return self._promote_result


def make_command(args: str | None) -> CommandObject:
    return CommandObject(prefix="/", command="add_chat", args=args)


def make_monitored_chat(
    *,
    title: str = "Python Jobs",
    username: str | None = "python_jobs",
    is_active: bool = True,
    origin: MonitoredChatOrigin = MonitoredChatOrigin.command,
    tg_chat_id: int = -1001,
) -> MonitoredChat:
    chat = MonitoredChat()
    chat.tg_chat_id = tg_chat_id
    chat.title = title
    chat.username = username
    chat.is_active = is_active
    chat.origin = origin
    return chat


def make_discovered_chat(
    *,
    chat_id: int = 7,
    title: str | None = "Python Jobs",
    username: str | None = "python_jobs",
    reason: str | None = "в чате публикуют заказы",
) -> DiscoveredChat:
    chat = DiscoveredChat()
    chat.id = chat_id
    chat.title = title
    chat.username = username
    chat.link = "https://t.me/python_jobs"
    chat.relevance_reason = reason
    return chat


async def test_add_chat_without_argument_shows_usage() -> None:
    message = MessageSpy()
    service = ChatServiceStub()

    await handle_add_chat(cast(Message, message), make_command(None), cast(Any, service))

    assert message.answers == [ADD_CHAT_USAGE]
    assert service.added == []


async def test_add_chat_passes_handle_to_service() -> None:
    message = MessageSpy()
    service = ChatServiceStub(
        add_result=AddChatResult(
            outcome=AddChatOutcome.added, handle="@python_jobs", title="Python Jobs"
        )
    )

    await handle_add_chat(
        cast(Message, message), make_command("  @python_jobs "), cast(Any, service)
    )

    assert service.added == ["@python_jobs"]
    assert "Python Jobs" in message.answers[0]
    assert "добавлен" in message.answers[0]


async def test_add_chat_reports_unresolved_handle() -> None:
    message = MessageSpy()
    service = ChatServiceStub(
        add_result=AddChatResult(outcome=AddChatOutcome.unresolved, handle="@ghost")
    )

    await handle_add_chat(cast(Message, message), make_command("@ghost"), cast(Any, service))

    assert "Не удалось найти чат @ghost" in message.answers[0]


async def test_remove_chat_without_argument_shows_usage() -> None:
    message = MessageSpy()
    service = ChatServiceStub()

    await handle_remove_chat(cast(Message, message), make_command(None), cast(Any, service))

    assert message.answers == [REMOVE_CHAT_USAGE]
    assert service.removed == []


async def test_remove_chat_confirms_history_is_kept() -> None:
    message = MessageSpy()
    service = ChatServiceStub(
        remove_result=RemoveChatResult(
            outcome=RemoveChatOutcome.removed, handle="@python_jobs", title="Python Jobs"
        )
    )

    await handle_remove_chat(
        cast(Message, message), make_command("@python_jobs"), cast(Any, service)
    )

    assert service.removed == ["@python_jobs"]
    assert "История заявок сохранена" in message.answers[0]


async def test_remove_unknown_chat_is_reported() -> None:
    message = MessageSpy()
    service = ChatServiceStub(
        remove_result=RemoveChatResult(outcome=RemoveChatOutcome.not_found, handle="@ghost")
    )

    await handle_remove_chat(cast(Message, message), make_command("@ghost"), cast(Any, service))

    assert "не найден" in message.answers[0]


async def test_list_chats_reports_empty_state() -> None:
    message = MessageSpy()

    await handle_list_chats(cast(Message, message), cast(Any, ChatServiceStub()))

    assert message.answers == [EMPTY_CHAT_LIST]


def test_chat_list_shows_state_and_origin() -> None:
    text = format_chat_list(
        [
            make_monitored_chat(),
            make_monitored_chat(
                title="Хабр Фриланс",
                username="freelansim_ru",
                is_active=False,
                origin=MonitoredChatOrigin.sources_file,
                tg_chat_id=-1002,
            ),
        ]
    )

    assert "Python Jobs (@python_jobs) — активен, источник: команда" in text
    assert "Хабр Фриланс (@freelansim_ru) — выключен, источник: sources.json" in text


def test_chat_list_falls_back_to_chat_id_without_username() -> None:
    text = format_chat_list([make_monitored_chat(username=None, tg_chat_id=-1005)])

    assert "(-1005)" in text


async def test_discovered_reports_empty_state() -> None:
    message = MessageSpy()

    await handle_discovered(cast(Message, message), cast(Any, ChatServiceStub()))

    assert message.answers == [EMPTY_DISCOVERED_LIST]


async def test_discovered_sends_card_with_promote_button() -> None:
    message = MessageSpy()
    service = ChatServiceStub(discovered=[make_discovered_chat()])

    await handle_discovered(cast(Message, message), cast(Any, service))

    assert "Python Jobs" in message.answers[0]
    assert "в чате публикуют заказы" in message.answers[0]
    keyboard = message.keyboards[0]
    assert isinstance(keyboard, InlineKeyboardMarkup)
    assert keyboard.inline_keyboard[0][0].text == PROMOTE_BUTTON_TEXT
    assert keyboard.inline_keyboard[0][0].callback_data == build_promote_callback(7)


async def test_promote_callback_adds_chat_and_clears_button() -> None:
    card = CardMessage()
    callback = CallbackSpy(build_promote_callback(7), card.message)
    service = ChatServiceStub(
        promote_result=PromoteResult(outcome=PromoteOutcome.promoted, title="Python Jobs")
    )

    await handle_promote(cast(CallbackQuery, callback), cast(Any, service))

    assert service.promoted == [7]
    assert "Python Jobs" in callback.answers[0]
    assert card.cleared_markup is True


async def test_failed_promote_keeps_the_button() -> None:
    card = CardMessage()
    callback = CallbackSpy(build_promote_callback(7), card.message)
    service = ChatServiceStub(promote_result=PromoteResult(outcome=PromoteOutcome.unresolved))

    await handle_promote(cast(CallbackQuery, callback), cast(Any, service))

    assert "попробуй позже" in callback.answers[0]
    assert card.cleared_markup is False


async def test_stale_callback_is_answered_without_service_call() -> None:
    callback = CallbackSpy("что-то другое")
    service = ChatServiceStub()

    await handle_promote(cast(CallbackQuery, callback), cast(Any, service))

    assert callback.answers == [UNKNOWN_CALLBACK_ANSWER]
    assert service.promoted == []


@pytest.mark.parametrize(
    ("callback_data", "expected"),
    [
        (build_promote_callback(7), 7),
        ("discovered:add:12", 12),
        ("discovered:add:abc", None),
        ("discovered:remove:7", None),
        ("7", None),
        (None, None),
    ],
)
def test_promote_callback_parsing(callback_data: str | None, expected: int | None) -> None:
    assert parse_promote_callback(callback_data) == expected


def test_promote_keyboard_round_trips_the_id() -> None:
    keyboard = build_promote_keyboard(42)

    assert parse_promote_callback(keyboard.inline_keyboard[0][0].callback_data) == 42
