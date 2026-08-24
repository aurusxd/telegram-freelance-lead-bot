from typing import Protocol

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import session_scope
from app.db.models import PortfolioItem
from app.portfolio.github_client import GithubClient
from app.repositories.portfolio import PortfolioItemRepository, deserialize_topics

EMPTY_PORTFOLIO_SUMMARY = "Портфолио пустое, оценивай по общему профилю python-разработчика."


class PortfolioSummarySource(Protocol):
    def build_summary(self) -> str: ...


def format_repo_line(
    name: str, language: str | None, description: str | None, topics: list[str]
) -> str:
    topics_text = ", ".join(topics) if topics else "без топиков"
    return (
        f"- {name} ({language or 'язык не указан'}): "
        f"{description or 'без описания'}; топики: {topics_text}"
    )


def build_summary_from_items(items: list[PortfolioItem]) -> str:
    if not items:
        return EMPTY_PORTFOLIO_SUMMARY
    lines = [
        format_repo_line(
            item.repo_name, item.language, item.description, deserialize_topics(item.topics)
        )
        for item in items
    ]
    return "Репозитории владельца:\n" + "\n".join(lines)


class PortfolioService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: GithubClient,
    ) -> None:
        self._session_factory = session_factory
        self._client = client
        self._cached_summary: str | None = None

    async def sync(self) -> int:
        repos = await self._client.list_repos()
        if not repos:
            logger.warning("github returned no repositories, portfolio left unchanged")
            await self.refresh_summary()
            return 0
        async with session_scope(self._session_factory) as session:
            repository = PortfolioItemRepository(session)
            for repo in repos:
                await repository.upsert(
                    repo_name=repo.name,
                    description=repo.description,
                    topics=repo.topics,
                    language=repo.language,
                    html_url=repo.html_url,
                )
        self._cached_summary = None
        await self.refresh_summary()
        logger.info("portfolio synced: {} repositories", len(repos))
        return len(repos)

    async def refresh_summary(self) -> str:
        async with session_scope(self._session_factory) as session:
            items = list(await PortfolioItemRepository(session).list_all())
        self._cached_summary = build_summary_from_items(items)
        return self._cached_summary

    def build_summary(self) -> str:
        return self._cached_summary or EMPTY_PORTFOLIO_SUMMARY
