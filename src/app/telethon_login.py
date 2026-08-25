import asyncio
import inspect

from loguru import logger
from telethon import TelegramClient
from telethon.types import User

from app.config import get_settings
from app.logging import setup_logging
from app.telethon_client.client import create_telethon_client


async def authorize() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    client = create_telethon_client(
        settings.telegram_api_id,
        settings.telegram_api_hash,
        settings.telethon_session_path,
    )
    async with client:
        await sign_in_interactively(client)
        await report_authorized_account(client)


async def sign_in_interactively(client: TelegramClient) -> None:
    started = client.start()
    if inspect.isawaitable(started):
        await started


async def report_authorized_account(client: TelegramClient) -> None:
    account = await client.get_me()
    if isinstance(account, User):
        logger.info("telethon session authorized for user id {}", account.id)
        return
    logger.warning("telethon session saved, but the account could not be read back")


def main() -> None:
    asyncio.run(authorize())


if __name__ == "__main__":
    main()
