from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import session_scope
from app.portfolio.github_client import GithubRepo
from app.portfolio.service import EMPTY_PORTFOLIO_SUMMARY, PortfolioService
from app.repositories.portfolio import PortfolioItemRepository, deserialize_topics

FIRST_REPO = GithubRepo(
    name="lead-bot",
    description="бот для лидов",
    topics=["python", "telegram"],
    language="Python",
    html_url="https://github.com/aurusxd/lead-bot",
)
SECOND_REPO = GithubRepo(
    name="parser-toolkit",
    description=None,
    topics=[],
    language=None,
    html_url="https://github.com/aurusxd/parser-toolkit",
)


class FakeRepoClient:
    def __init__(self, repos: list[GithubRepo]) -> None:
        self.repos = repos
        self.calls = 0

    async def list_repos(self) -> list[GithubRepo]:
        self.calls += 1
        return list(self.repos)


async def stored_items(session_factory: async_sessionmaker[AsyncSession]):
    async with session_scope(session_factory) as session:
        return list(await PortfolioItemRepository(session).list_all())


async def test_sync_stores_repos_and_serializes_topics(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = PortfolioService(session_factory, FakeRepoClient([FIRST_REPO, SECOND_REPO]))

    synced = await service.sync()

    items = await stored_items(session_factory)
    assert synced == 2
    assert [item.repo_name for item in items] == ["lead-bot", "parser-toolkit"]
    assert deserialize_topics(items[0].topics) == ["python", "telegram"]
    assert items[1].topics is None


async def test_sync_is_idempotent_and_updates_changed_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client = FakeRepoClient([FIRST_REPO])
    service = PortfolioService(session_factory, client)
    await service.sync()

    client.repos = [
        GithubRepo(
            name="lead-bot",
            description="обновлённое описание",
            topics=["python", "aiogram"],
            language="Python",
            html_url=FIRST_REPO.html_url,
        )
    ]
    await service.sync()

    items = await stored_items(session_factory)
    assert len(items) == 1
    assert items[0].description == "обновлённое описание"
    assert deserialize_topics(items[0].topics) == ["python", "aiogram"]


async def test_summary_is_empty_until_first_sync(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = PortfolioService(session_factory, FakeRepoClient([FIRST_REPO]))

    assert service.build_summary() == EMPTY_PORTFOLIO_SUMMARY


async def test_summary_rebuilt_after_sync(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = PortfolioService(session_factory, FakeRepoClient([FIRST_REPO, SECOND_REPO]))

    await service.sync()
    summary = service.build_summary()

    assert "lead-bot" in summary
    assert "бот для лидов" in summary
    assert "python, telegram" in summary
    assert "parser-toolkit" in summary
    assert "без описания" in summary
    assert "без топиков" in summary


async def test_summary_reflects_updated_repositories(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client = FakeRepoClient([FIRST_REPO])
    service = PortfolioService(session_factory, client)
    await service.sync()

    client.repos = [SECOND_REPO]
    await service.sync()

    summary = service.build_summary()
    assert "parser-toolkit" in summary
    assert "lead-bot" in summary


async def test_empty_github_response_keeps_previous_portfolio(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client = FakeRepoClient([FIRST_REPO])
    service = PortfolioService(session_factory, client)
    await service.sync()

    client.repos = []
    synced = await service.sync()

    assert synced == 0
    assert len(await stored_items(session_factory)) == 1
    assert "lead-bot" in service.build_summary()
