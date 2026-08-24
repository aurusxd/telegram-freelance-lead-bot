from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from loguru import logger

GITHUB_API_VERSION = "2022-11-28"
REPOS_PER_PAGE = 100
MAX_REPO_PAGES = 5
REQUEST_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class GithubRepo:
    name: str
    description: str | None
    topics: list[str]
    language: str | None
    html_url: str


class GithubClient(Protocol):
    async def list_repos(self) -> list[GithubRepo]: ...


def build_auth_headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def to_repo(payload: dict[str, Any]) -> GithubRepo | None:
    name = payload.get("name")
    html_url = payload.get("html_url")
    if not isinstance(name, str) or not isinstance(html_url, str):
        return None
    raw_topics = payload.get("topics")
    topics = [str(topic) for topic in raw_topics] if isinstance(raw_topics, list) else []
    description = payload.get("description")
    language = payload.get("language")
    return GithubRepo(
        name=name,
        description=description if isinstance(description, str) else None,
        topics=topics,
        language=language if isinstance(language, str) else None,
        html_url=html_url,
    )


def is_own_work(payload: dict[str, Any]) -> bool:
    return not payload.get("fork", False)


class GithubApiClient:
    def __init__(
        self,
        username: str,
        token: str,
        *,
        base_url: str = "https://api.github.com",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._username = username
        self._token = token
        self._base_url = base_url
        self._transport = transport

    async def list_repos(self) -> list[GithubRepo]:
        if not self._username:
            logger.warning("github username is missing, portfolio sync skipped")
            return []
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=build_auth_headers(self._token),
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=self._transport,
        ) as client:
            return await self._collect_repos(client)

    async def _collect_repos(self, client: httpx.AsyncClient) -> list[GithubRepo]:
        repos: list[GithubRepo] = []
        for page in range(1, MAX_REPO_PAGES + 1):
            payloads = await self._fetch_page(client, page)
            if not payloads:
                break
            repos.extend(self._map_payloads(payloads))
            if len(payloads) < REPOS_PER_PAGE:
                break
        return repos

    async def _fetch_page(self, client: httpx.AsyncClient, page: int) -> list[dict[str, Any]]:
        try:
            response = await client.get(
                f"/users/{self._username}/repos",
                params={"per_page": REPOS_PER_PAGE, "page": page, "sort": "updated"},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("github repos request failed: {}", type(error).__name__)
            return []
        return (
            [item for item in payload if isinstance(item, dict)]
            if isinstance(payload, list)
            else []
        )

    def _map_payloads(self, payloads: list[dict[str, Any]]) -> list[GithubRepo]:
        mapped = (to_repo(payload) for payload in payloads if is_own_work(payload))
        return [repo for repo in mapped if repo is not None]


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
