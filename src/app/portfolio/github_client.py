from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GithubRepo:
    name: str
    description: str | None
    topics: list[str]
    language: str | None
    html_url: str


class GithubClient(Protocol):
    async def list_repos(self) -> list[GithubRepo]: ...


SEED_REPOS = (
    GithubRepo(
        name="telegram-freelance-lead-bot",
        description="Telegram bot that finds freelance leads in chats",
        topics=["python", "telegram", "aiogram", "automation"],
        language="Python",
        html_url="https://github.com/aurusxd/telegram-freelance-lead-bot",
    ),
    GithubRepo(
        name="data-parser-toolkit",
        description="Async parsers and scrapers toolkit",
        topics=["python", "parsing", "asyncio"],
        language="Python",
        html_url="https://github.com/aurusxd/data-parser-toolkit",
    ),
)


class FakeGithubClient:
    async def list_repos(self) -> list[GithubRepo]:
        return list(SEED_REPOS)
