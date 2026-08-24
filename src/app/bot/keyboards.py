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
