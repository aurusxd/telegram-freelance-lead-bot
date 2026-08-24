from collections.abc import Sequence
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from app.db.models import MonitoredChat, MonitoredChatOrigin
from app.services.chat_service import (
    AddChatOutcome,
    AddChatResult,
    ChatService,
    ChatServiceStatus,
    RemoveChatOutcome,
    RemoveChatResult,
)

router = Router(name="commands")

START_TEXT = (
    "Бот поиска фриланс-заказов запущен.\n"
    "Мониторю чаты из sources.json и присылаю подходящие заявки.\n"
    "Список команд — /help."
)

HELP_TEXT = (
    "Доступные команды:\n"
    "/start — проверка, что бот жив\n"
    "/help — эта справка\n"
    "/status — состояние подключений и мониторимых чатов\n"
    "/add_chat @handle — добавить чат в мониторинг\n"
    "/list_chats — список мониторимых чатов\n"
    "/remove_chat @handle — снять чат с мониторинга\n"
    "/discovered — найденные discovery чаты, ждущие решения"
)

ADD_CHAT_USAGE = "Формат: /add_chat @handle"
REMOVE_CHAT_USAGE = "Формат: /remove_chat @handle"
EMPTY_CHAT_LIST = "Мониторимых чатов пока нет. Добавь через /add_chat или sources.json."

ORIGIN_LABELS = {
    MonitoredChatOrigin.sources_file: "sources.json",
    MonitoredChatOrigin.command: "команда",
}


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    await message.answer(START_TEXT)


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("status"))
async def handle_status(message: Message, chat_service: ChatService) -> None:
    status = await chat_service.build_status()
    await message.answer(format_status(status))


@router.message(Command("add_chat"))
async def handle_add_chat(
    message: Message, command: CommandObject, chat_service: ChatService
) -> None:
    handle = (command.args or "").strip()
    if not handle:
        await message.answer(ADD_CHAT_USAGE)
        return
    await message.answer(format_add_result(await chat_service.add_chat(handle)))


@router.message(Command("remove_chat"))
async def handle_remove_chat(
    message: Message, command: CommandObject, chat_service: ChatService
) -> None:
    handle = (command.args or "").strip()
    if not handle:
        await message.answer(REMOVE_CHAT_USAGE)
        return
    await message.answer(format_remove_result(await chat_service.remove_chat(handle)))


@router.message(Command("list_chats"))
async def handle_list_chats(message: Message, chat_service: ChatService) -> None:
    await message.answer(format_chat_list(await chat_service.list_chats()))


def format_status(status: ChatServiceStatus) -> str:
    telethon_state = "подключён" if status.telethon_healthy else "нет соединения"
    notified = f"(уведомлений отправлено: {status.notified_leads})"
    return "\n".join(
        [
            f"Telethon: {telethon_state}",
            f"Активных мониторимых чатов: {status.active_chats}",
            f"Заявок найдено: {status.total_leads} {notified}",
            f"Найденных чатов ждут решения: {status.pending_discovered}",
            f"Интервал discovery: {status.discovery_interval_minutes} мин",
            f"Последний прогон discovery: {format_last_run(status.last_discovery_run_at)}",
        ]
    )


def format_last_run(last_run_at: datetime | None) -> str:
    if last_run_at is None:
        return "ещё не запускался"
    return last_run_at.strftime("%Y-%m-%d %H:%M UTC")


def format_add_result(result: AddChatResult) -> str:
    title = result.title or result.handle
    if result.outcome is AddChatOutcome.added:
        return f"Чат «{title}» добавлен в мониторинг."
    if result.outcome is AddChatOutcome.reactivated:
        return f"Чат «{title}» снова в мониторинге."
    if result.outcome is AddChatOutcome.already_monitored:
        return f"Чат «{title}» уже мониторится."
    return f"Не удалось найти чат {result.handle}. Проверь handle и доступность чата."


def format_remove_result(result: RemoveChatResult) -> str:
    if result.outcome is RemoveChatOutcome.removed:
        return (
            f"Чат «{result.title or result.handle}» снят с мониторинга. История заявок сохранена."
        )
    return f"Чат {result.handle} не найден среди активных."


def format_chat_list(chats: Sequence[MonitoredChat]) -> str:
    if not chats:
        return EMPTY_CHAT_LIST
    return "Мониторимые чаты:\n" + "\n".join(format_chat_line(chat) for chat in chats)


def format_chat_line(chat: MonitoredChat) -> str:
    state = "активен" if chat.is_active else "выключен"
    handle = f"@{chat.username}" if chat.username else str(chat.tg_chat_id)
    return f"- {chat.title} ({handle}) — {state}, источник: {ORIGIN_LABELS[chat.origin]}"
