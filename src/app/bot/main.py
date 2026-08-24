import asyncio
from collections.abc import Awaitable, Callable

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from loguru import logger
from telethon import TelegramClient

from app.bot.handlers import commands, monitoring
from app.bot.keyboards import build_contact_keyboard
from app.bot.middlewares.owner_only import OwnerOnlyMiddleware
from app.config import Settings, get_settings
from app.db.base import create_engine, create_session_factory
from app.db.models import Lead
from app.discovery.pipeline import DiscoveryPipeline
from app.discovery.providers.searxng_search import FakeSearxngProvider
from app.llm.deepseek_client import DeepSeekClient, FakeDeepSeekClient, LlmClient
from app.llm.relevance import RelevanceChecker
from app.logging import SECRET_FIELD_NAMES, describe_secret, setup_logging
from app.portfolio.github_client import FakeGithubClient, GithubApiClient, GithubClient
from app.portfolio.service import PortfolioService
from app.scheduler import (
    create_scheduler,
    register_discovery_job,
    register_portfolio_sync_job,
)
from app.services.chat_service import ChatService
from app.services.lead_service import LeadService
from app.telethon_client.client import TelethonChatResolver, create_telethon_client


def format_lead_notification(lead: Lead, chat_title: str) -> str:
    author = lead.tg_first_name or "без имени"
    username = f"@{lead.tg_username}" if lead.tg_username else "без username"
    return "\n".join(
        [
            f"Новая заявка в чате «{chat_title}»",
            f"Автор: {author} ({username})",
            f"Почему подходит: {lead.relevance_reason}",
            "",
            lead.message_text,
        ]
    )


class TelegramOwnerNotifier:
    def __init__(self, bot: Bot, owner_tg_id: int) -> None:
        self._bot = bot
        self._owner_tg_id = owner_tg_id

    async def notify_lead(self, lead: Lead, chat_title: str) -> bool:
        try:
            await self._bot.send_message(
                self._owner_tg_id,
                format_lead_notification(lead, chat_title),
                reply_markup=build_contact_keyboard(lead.tg_username, lead.tg_user_id),
            )
        except TelegramAPIError as error:
            logger.warning("cannot notify owner: {}", type(error).__name__)
            return False
        return True


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


def build_dispatcher(
    settings: Settings,
    chat_service: ChatService,
    lead_service: LeadService,
) -> Dispatcher:
    dispatcher = Dispatcher(chat_service=chat_service, lead_service=lead_service)
    commands.router.message.middleware(OwnerOnlyMiddleware(settings.owner_tg_id))
    dispatcher.include_router(commands.router)
    dispatcher.include_router(monitoring.router)
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

    portfolio = PortfolioService(session_factory, create_github_client(settings))
    await portfolio.sync()

    pipeline = DiscoveryPipeline([FakeSearxngProvider()])
    scheduler = create_scheduler()
    register_discovery_job(scheduler, discovery_job(pipeline), settings.discovery_interval_minutes)
    register_portfolio_sync_job(scheduler, portfolio_sync_job(portfolio))
    scheduler.start()

    bot = Bot(token=settings.bot_token)
    lead_service = LeadService(
        session_factory,
        RelevanceChecker(create_llm_client(settings)),
        portfolio,
        TelegramOwnerNotifier(bot, settings.owner_tg_id),
    )
    dispatcher = build_dispatcher(settings, chat_service, lead_service)
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


def portfolio_sync_job(portfolio: PortfolioService) -> Callable[[], Awaitable[None]]:
    async def job() -> None:
        await portfolio.sync()

    return job


def create_llm_client(settings: Settings) -> LlmClient:
    if settings.deepseek_api_key:
        return DeepSeekClient(
            settings.deepseek_api_key,
            settings.deepseek_model,
            base_url=settings.deepseek_base_url,
        )
    logger.warning("deepseek api key is missing, relevance falls back to the fake client")
    return FakeDeepSeekClient()


def create_github_client(settings: Settings) -> GithubClient:
    if settings.github_username and settings.github_token:
        return GithubApiClient(settings.github_username, settings.github_token)
    logger.warning("github credentials are missing, portfolio falls back to seed repositories")
    return FakeGithubClient()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
