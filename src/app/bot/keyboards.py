from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CONTACT_BUTTON_TEXT = "Написать"


def build_contact_url(tg_username: str | None, tg_user_id: int) -> str:
    if tg_username:
        return f"https://t.me/{tg_username.removeprefix('@')}"
    return f"tg://user?id={tg_user_id}"


def build_contact_keyboard(tg_username: str | None, tg_user_id: int) -> InlineKeyboardMarkup:
    button = InlineKeyboardButton(
        text=CONTACT_BUTTON_TEXT,
        url=build_contact_url(tg_username, tg_user_id),
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


PROMOTE_BUTTON_TEXT = "Добавить в мониторинг"
PROMOTE_CALLBACK_PREFIX = "discovered:add"


def build_promote_callback(discovered_chat_id: int) -> str:
    return f"{PROMOTE_CALLBACK_PREFIX}:{discovered_chat_id}"


def parse_promote_callback(callback_data: str | None) -> int | None:
    if callback_data is None:
        return None
    prefix, separator, raw_id = callback_data.rpartition(":")
    if not separator or prefix != PROMOTE_CALLBACK_PREFIX:
        return None
    return int(raw_id) if raw_id.isdigit() else None


def build_promote_keyboard(discovered_chat_id: int) -> InlineKeyboardMarkup:
    button = InlineKeyboardButton(
        text=PROMOTE_BUTTON_TEXT,
        callback_data=build_promote_callback(discovered_chat_id),
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])
