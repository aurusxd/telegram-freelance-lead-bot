from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, User
from loguru import logger


class OwnerOnlyMiddleware(BaseMiddleware):
    def __init__(self, owner_tg_id: int) -> None:
        self._owner_tg_id = owner_tg_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = extract_user(event, data)
        if user is None or user.id != self._owner_tg_id:
            logger.debug("dropping update from non-owner user")
            return None
        return await handler(event, data)


def extract_user(event: TelegramObject, data: dict[str, Any]) -> User | None:
    if isinstance(event, Message) and event.from_user is not None:
        return event.from_user
    event_user = data.get("event_from_user")
    return event_user if isinstance(event_user, User) else None
