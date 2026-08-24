import asyncio
from collections.abc import Awaitable, Callable

from aiogram import Bot, Dispatcher
from loguru import logger
from telethon import TelegramClient

from app.bot.handlers import commands
from app.bot.middlewares.owner_only import OwnerOnlyMiddleware
from app.config import Settings, get_settings
from app.db.base import create_engine, create_session_factory
from app.discovery.pipeline import DiscoveryPipeline
from app.discovery.providers.searxng_search import FakeSearxngProvider
from app.logging import SECRET_FIELD_NAMES, describe_secret, setup_logging
from app.scheduler import create_scheduler, register_discovery_job
from app.services.chat_service import ChatService
from app.telethon_client.client import TelethonChatResolver, create_telethon_client


def log_secret_presence(settings: Settings) -> None:
    for field_name in SECRET_FIELD_NAMES:
        value = getattr(settings, field_name)
        logger.info("secret {}: {}", field_name, describe_secret(str(value)))


async def disconnect_telethon(client: TelegramClient) -> None:
    pending = client.disconnect()
    if pending is not None:
        await pending


async def connect_telethon(client: TelegramClient) -> None:
    try:
        await client.connect()
    except OSError as error:
        logger.warning("telethon connection failed: {}", type(error).__name__)


def build_dispatcher(settings: Settings, chat_service: ChatService) -> Dispatcher:
    dispatcher = Dispatcher(chat_service=chat_service)
    dispatcher.message.middleware(OwnerOnlyMiddleware(settings.owner_tg_id))
    dispatcher.include_router(commands.router)
    return dispatcher


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    log_secret_presence(settings)

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    telethon_client = create_telethon_client(
        settings.telegram_api_id,
        settings.telegram_api_hash,
        settings.telethon_session_path,
    )
    await connect_telethon(telethon_client)
    resolver = TelethonChatResolver(telethon_client)

    chat_service = ChatService(session_factory, resolver, settings.discovery_interval_minutes)
    await chat_service.sync_from_sources_file(settings.sources_file_path)

    pipeline = DiscoveryPipeline([FakeSearxngProvider()])
    scheduler = create_scheduler()
    register_discovery_job(scheduler, discovery_job(pipeline), settings.discovery_interval_minutes)
    scheduler.start()

    bot = Bot(token=settings.bot_token)
    dispatcher = build_dispatcher(settings, chat_service)
    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await disconnect_telethon(telethon_client)
        await bot.session.close()
        await engine.dispose()


def discovery_job(pipeline: DiscoveryPipeline) -> Callable[[], Awaitable[None]]:
    async def job() -> None:
        await pipeline.run_once()

    return job


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
