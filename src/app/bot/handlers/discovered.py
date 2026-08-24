from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import build_promote_keyboard, parse_promote_callback
from app.db.models import DiscoveredChat
from app.services.chat_service import ChatService, PromoteOutcome, PromoteResult

router = Router(name="discovered")

EMPTY_DISCOVERED_LIST = "Новых найденных чатов нет. Discovery добавит их после следующего прогона."
UNKNOWN_CALLBACK_ANSWER = "Кнопка устарела, открой /discovered заново."


@router.message(Command("discovered"))
async def handle_discovered(message: Message, chat_service: ChatService) -> None:
    chats = await chat_service.list_pending_discovered()
    if not chats:
        await message.answer(EMPTY_DISCOVERED_LIST)
        return
    for chat in chats:
        await message.answer(
            format_discovered_chat(chat),
            reply_markup=build_promote_keyboard(chat.id),
        )


@router.callback_query()
async def handle_promote(callback: CallbackQuery, chat_service: ChatService) -> None:
    discovered_chat_id = parse_promote_callback(callback.data)
    if discovered_chat_id is None:
        await callback.answer(UNKNOWN_CALLBACK_ANSWER)
        return
    result = await chat_service.promote_discovered(discovered_chat_id)
    await callback.answer(format_promote_result(result))
    if result.outcome is PromoteOutcome.promoted and isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)


def format_discovered_chat(chat: DiscoveredChat) -> str:
    handle = f"@{chat.username}" if chat.username else chat.link
    reason = chat.relevance_reason or "причина не сохранена"
    return f"{chat.title or handle}\n{handle}\nПочему подходит: {reason}"


def format_promote_result(result: PromoteResult) -> str:
    if result.outcome is PromoteOutcome.promoted:
        return f"Чат «{result.title}» добавлен в мониторинг."
    if result.outcome is PromoteOutcome.unresolved:
        return "Не удалось получить чат в Telegram, попробуй позже."
    return "Кандидат не найден, возможно он уже обработан."
