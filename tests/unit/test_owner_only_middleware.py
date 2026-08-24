from datetime import UTC, datetime
from typing import Any

from aiogram.types import Chat, Message, TelegramObject, User

from app.bot.middlewares.owner_only import OwnerOnlyMiddleware

OWNER_ID = 111
STRANGER_ID = 222


def make_message(user_id: int) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Никита"),
        text="/start",
    )


class HandlerSpy:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, event: TelegramObject, data: dict[str, Any]) -> str:
        del event, data
        self.calls += 1
        return "handled"


async def test_owner_message_reaches_handler() -> None:
    middleware = OwnerOnlyMiddleware(OWNER_ID)
    handler = HandlerSpy()

    result = await middleware(handler, make_message(OWNER_ID), {})

    assert result == "handled"
    assert handler.calls == 1


async def test_stranger_message_is_dropped() -> None:
    middleware = OwnerOnlyMiddleware(OWNER_ID)
    handler = HandlerSpy()

    result = await middleware(handler, make_message(STRANGER_ID), {})

    assert result is None
    assert handler.calls == 0


async def test_event_without_user_is_dropped() -> None:
    middleware = OwnerOnlyMiddleware(OWNER_ID)
    handler = HandlerSpy()

    result = await middleware(handler, TelegramObject(), {})

    assert result is None
    assert handler.calls == 0
