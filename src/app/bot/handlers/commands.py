from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.services.chat_service import ChatService, ChatServiceStatus

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
    "/status — состояние подключений и мониторимых чатов"
)


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


def format_status(status: ChatServiceStatus) -> str:
    telethon_state = "подключён" if status.telethon_healthy else "нет соединения"
    return (
        f"Telethon: {telethon_state}\n"
        f"Активных мониторимых чатов: {status.active_chats}\n"
        f"Интервал discovery: {status.discovery_interval_minutes} мин"
    )
